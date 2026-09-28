"""Persistance — la première des six capacités du CORE.

Rapatriée de `brain-engine/db.py` le 06/09, **relue et redécidée** plutôt que
copiée. Ce qui est éprouvé est repris tel quel — la traduction SQL portable a
survécu à six mois d'usage et à la bascule SQLite → Dolt. Ce qui tenait à
l'installation est refait.

── Les quatre choses qui changent, et pourquoi ─────────────────────────────

**1. La configuration est reçue, jamais devinée.** L'ancien module faisait
`BRAIN_ROOT = Path(__file__).parent.parent` : il déduisait où vivent les données
de sa propre position sur le disque. Un programme qui fait ça n'est plus un
programme — il devient une partie de l'installation qu'il sert, et il ne peut
pas vivre ailleurs. C'est précisément ce que Myéline sépare.

**2. Rien ne se décide à l'import.** L'ancien lisait `.env.local` et figeait
`BACKEND` au chargement du module. Conséquences : impossible d'ouvrir deux dépôts
dans le même processus, impossible de tester sans toucher la vraie base, et un
`import db` suffisait à écrire dans `os.environ`. Ici, un `Depot` se construit.

**3. `get_raw_connection()` n'est pas rapatrié.** Sa propre docstring disait « À
éliminer progressivement » et il lève déjà en mode Dolt. Un accès brut qui ne
fonctionne que sur un backend n'est pas une capacité du CORE, c'est une dette.

**4. La discipline d'écriture Dolt viendra à part.** `freeze`, `purge`,
`dirty_tables` et le commit confiné par tables sont une capacité distincte —
c'est *l'écriture gouvernée* et les *traces*, deux autres briques de. Les
mêler à la persistance, c'est ce qui rend l'ancien module impossible à tester.

── Ce qui ne change pas ────────────────────────────────────────────────────

Le SQL reste écrit en dialecte portable — `%s`, `NOW()`, `DATE_ADD`,
`TIMESTAMPDIFF` — et c'est le dépôt qui traduit. Six mois de requêtes sont
écrites ainsi, et la traduction est la partie la plus éprouvée de l'ancien
moteur.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("myeline.persistance")

# Les tables que cette brique possède — aucune.
#
# La persistance est un **pont** : elle porte n'importe quelle requête vers
# n'importe quelle table, et n'en possède aucune. Déclarer un ensemble vide
# n'est pas un oubli, c'est le sens de la brique.
TABLES: frozenset[str] = frozenset()

SQLITE = "sqlite"
DOLT = "dolt"


# ── Traduction du SQL portable ──────────────────────────────────────────────
#
# Reprise telle quelle de `db.py`, à ceci près que le backend est un ARGUMENT
# et non une variable de module. C'est ce qui rend ces fonctions testables sans
# base : ce sont des fonctions pures, de texte vers texte.

def _upsert(sql: str, backend: str) -> str:
    """`ON CONFLICT … DO UPDATE SET` (SQLite) → `ON DUPLICATE KEY UPDATE` (MySQL)."""
    if backend != DOLT:
        return sql
    m = re.search(r"ON\s+CONFLICT\s*\([^)]*\)\s*DO\s+UPDATE\s+SET\s+(.+)",
                  sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return sql
    clause = re.sub(r"excluded\.(`?\w+`?)", r"VALUES(\1)", m.group(1).strip())
    clause = re.sub(r"COALESCE\(VALUES\((`?\w+`?)\),\s*\w+\.(`?\w+`?)\)",
                    r"COALESCE(VALUES(\1), \2)", clause)
    return sql[:m.start()] + "ON DUPLICATE KEY UPDATE " + clause


def _date_add(sql: str, backend: str) -> str:
    """`DATE_ADD(x, INTERVAL n UNIT)` → `datetime(x, '+n unit')` pour SQLite."""
    if backend != SQLITE:
        return sql
    unites = {"HOUR": "hours", "MINUTE": "minutes", "DAY": "days"}

    def remplace(m: re.Match) -> str:
        expr, n, unite = (g.strip() for g in m.groups())
        return f"datetime({expr}, '+' || {n} || ' {unites.get(unite.upper(), 'hours')}')"

    return re.sub(r"DATE_ADD\((.+?),\s*INTERVAL\s+(.+?)\s+(HOUR|MINUTE|DAY)\)",
                  remplace, sql, flags=re.IGNORECASE)


def _decouper_arguments(inner: str) -> list[str]:
    """Découpe sur les virgules de premier niveau — `NOW()` en contient."""
    parts, courant, profondeur = [], "", 0
    for ch in inner:
        if ch == "(":
            profondeur += 1
        elif ch == ")":
            profondeur -= 1
        elif ch == "," and profondeur == 0:
            parts.append(courant.strip())
            courant = ""
            continue
        courant += ch
    parts.append(courant.strip())
    return parts


# Un jour julien vaut 1 ; tout le reste en découle. `DAY` n'a pas de facteur,
# et c'est pour ça qu'il marchait par coïncidence quand les unités inconnues
# tombaient toutes dans ce cas.
_FACTEURS_JULIANDAY = {
    "SECOND": " * 86400",
    "MINUTE": " * 1440",
    "HOUR": " * 24",
    "DAY": "",
    "WEEK": " / 7",
}


def _timestampdiff(sql: str, backend: str) -> str:
    """`TIMESTAMPDIFF(unit, a, b)` → arithmétique `julianday` pour SQLite.

    Le découpage est manuel parce qu'une expression régulière ne compte pas les
    parenthèses : `TIMESTAMPDIFF(HOUR, NOW(), x)` la ferait s'arrêter au
    premier `)`. Défaut connu et corrigé dans l'ancien moteur — on le reprend.

    ⚠️ La conversion rend un FLOTTANT là où MySQL rend un entier tronqué.
    C'est le comportement de l'ancien moteur, six mois de requêtes sont écrites
    dessus, et le changer ici serait changer des résultats sans qu'on l'ait
    demandé. Noté, pas corrigé.
    """
    if backend != SQLITE:
        return sql

    def une_fois(s: str) -> str:
        m = re.search(r"TIMESTAMPDIFF\s*\(", s, re.IGNORECASE)
        if not m:
            return s
        ouvrante = m.end() - 1
        profondeur, pos = 1, ouvrante + 1
        while pos < len(s) and profondeur:
            profondeur += (s[pos] == "(") - (s[pos] == ")")
            pos += 1
        if profondeur:
            return s
        args = _decouper_arguments(s[ouvrante + 1:pos - 1])
        if len(args) != 3:
            return s
        unite, a, b = args
        facteur = _FACTEURS_JULIANDAY.get(unite.upper())
        if facteur is None:
            # 🔴 Ne PAS traduire une unité qu'on ne sait pas convertir.
            #
            # L'ancien moteur — et cette fonction avant le 11/09 — se rabattait
            # silencieusement sur un différentiel en JOURS pour toute unité
            # inconnue : `TIMESTAMPDIFF(SECOND, a, b)` rendait des jours. Pas
            # d'erreur, pas de log, un nombre plausible et faux de 86 400 fois.
            #
            # Laisser le SQL intact fait échouer SQLite franchement — « no such
            # function: TIMESTAMPDIFF » — et cet échec EST l'information
            # cherchée. Mesuré : le brain n'emploie que MINUTE et HOUR, donc
            # rien de vivant ne change ; mais le CORE sert d'autres instances.
            log.warning("TIMESTAMPDIFF(%s, …) : unité non convertible en SQLite, "
                        "laissée telle quelle plutôt que rendue en jours", unite)
            return s
        jours = f"(julianday({b}) - julianday({a}))"
        # Les parenthèses externes n'ont de sens qu'autour d'un produit : sans
        # facteur, `jours` est déjà parenthésé et en ajouter creerait un ecart
        # de texte avec le moteur en place, sans rien apporter.
        expr = f"({jours}{facteur})" if facteur else jours
        return s[:m.start()] + expr + s[pos:]

    precedent = None
    while precedent != sql:
        precedent, sql = sql, une_fois(sql)
    return sql


def _dialecte(sql: str, backend: str) -> str:
    """Les derniers écarts : placeholders, `NOW()`, `REPLACE INTO`."""
    if backend != SQLITE:
        return sql                      # Dolt parle MySQL, tout passe
    # ⚠️ `UTC_TIMESTAMP()` n'existe pas en SQLite, et l'ancien `db.py` ne le
    # traduisait PAS — trouvé le 06/09 en écrivant les verrous. Treize usages
    # dans `bsi-claim.sh` et `file-lock.sh` : sur un backend SQLite, fermer un
    # claim périmé ou poser un verrou levait « no such function ». Personne ne
    # l'avait vu parce que cette instance tourne sur Dolt — mais un fork en
    # SQLite, lui, tombait dessus.
    #
    # `datetime('now')` de SQLite rend déjà de l'UTC : la traduction est directe,
    # et c'est ce qui la rend sûre.
    sql = sql.replace("%s", "?")
    for horloge in ("UTC_TIMESTAMP()", "NOW()"):
        sql = sql.replace(horloge, "datetime('now')")
    if sql.strip().upper().startswith("REPLACE INTO"):
        sql = "INSERT OR " + sql.strip()
    return sql


def traduire(sql: str, backend: str) -> str:
    """Le SQL portable vers le dialecte du backend. Fonction pure."""
    for etape in (_upsert, _date_add, _timestampdiff, _dialecte):
        sql = etape(sql, backend)
    return sql


# ── La configuration, explicite ─────────────────────────────────────────────

@dataclass(frozen=True)
class Config:
    """Où vivent les données, et comment on les atteint.

    Immuable et sans valeur devinée. `chemin` n'a de sens que pour SQLite ;
    l'hôte et le port n'en ont que pour Dolt. Ce n'est pas élégant, mais c'est
    honnête : les deux backends ne se joignent pas de la même façon, et le
    prétendre produirait une abstraction qui ment.
    """
    backend: str = SQLITE
    chemin: Path | None = None                 # SQLite
    hote: str = "127.0.0.1"                    # Dolt
    port: int = 3307
    utilisateur: str = "root"
    base: str = "brain-dolt"

    # Dolt — chaque statement est-il commité de lui-même ?
    #
    # `True` par défaut, et ce n'est pas une commodité : la connexion Dolt est
    # **persistante et partagée**, et une connexion transactionnelle qui ne
    # commit jamais après une lecture fige son instantané. Le mode transactionnel
    # se demande explicitement, pour un dépôt qui sait qu'il le veut.
    autocommit: bool = True

    def __post_init__(self) -> None:
        if self.backend not in (SQLITE, DOLT):
            raise ValueError(
                f"backend inconnu : {self.backend!r} — attendu {SQLITE} ou {DOLT}")
        if self.backend == SQLITE and self.chemin is None:
            raise ValueError("backend sqlite : `chemin` est obligatoire. "
                             "Le CORE ne devine pas où vivent les données.")


# ── Le dépôt ────────────────────────────────────────────────────────────────

class Depot:
    """Le point d'entrée unique vers les données.

    Un dépôt par base. Deux dépôts peuvent coexister dans le même processus —
    ce que l'ancien module interdisait, son backend étant figé à l'import.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._conn = None
        # pymysql n'est pas conçu pour l'accès concurrent sur une connexion
        # partagée, et les routes du serveur tournent dans un threadpool. Le
        # verrou est repris de l'ancien moteur, où il répare un défaut réel.
        self._verrou = threading.Lock()

    # ── lecture ─────────────────────────────────────────────────────────────

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """SELECT → une liste de dictionnaires."""
        sql = traduire(sql, self.config.backend)
        if self.config.backend == DOLT:
            with self._verrou:
                curseur = self._connexion_dolt().cursor()
                curseur.execute(sql, params)
                return list(curseur.fetchall())
        conn = self._connexion_sqlite()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        """SELECT → la première ligne, ou `None`.

        Elle ne passe pas par `query()` : celui-ci rapatrie TOUT le résultat
        avant d'en jeter la fin. Sur un `SELECT` sans `LIMIT` — et le brain en
        écrit — c'est la table entière en mémoire pour une ligne. L'ancien
        moteur faisait un `fetchone`, et il avait raison.
        """
        sql = traduire(sql, self.config.backend)
        if self.config.backend == DOLT:
            with self._verrou:
                curseur = self._connexion_dolt().cursor()
                curseur.execute(sql, params)
                return curseur.fetchone()
        conn = self._connexion_sqlite()
        try:
            ligne = conn.execute(sql, params).fetchone()
            return dict(ligne) if ligne else None
        finally:
            conn.close()

    def count(self, table: str, where: str = "1=1") -> int:
        ligne = self.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}")
        return int(ligne["n"]) if ligne else 0

    def table_existe(self, table: str) -> bool:
        if self.config.backend == DOLT:
            ligne = self.query_one(
                "SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s", (table,))
        else:
            ligne = self.query_one(
                "SELECT COUNT(*) AS n FROM sqlite_master "
                "WHERE type='table' AND name = %s", (table,))
        return bool(ligne and int(ligne["n"]) > 0)

    def colonne_existe(self, table: str, colonne: str) -> bool:
        """La colonne est-elle dans la table ? —

        Une colonne s'ajoute à la base d'une instance APRÈS que le CORE sait
        s'en servir : le laptop en repli SQLite, un fork, la prod avant son
        `ALTER`. Le CORE demande plutôt que de supposer — une requête qui nomme
        une colonne absente casse tout le module, pas seulement la nouveauté.

        Côté Dolt, `table_schema = DATABASE()` : le serveur peut porter
        plusieurs bases, et une table homonyme ailleurs répondrait à tort.
        """
        if self.config.backend == DOLT:
            ligne = self.query_one(
                "SELECT COUNT(*) AS n FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = %s "
                "AND column_name = %s", (table, colonne))
        else:
            ligne = self.query_one(
                "SELECT COUNT(*) AS n FROM pragma_table_info(%s) WHERE name = %s",
                (table, colonne))
        return bool(ligne and int(ligne["n"]) > 0)

    # ── écriture ────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> int:
        """INSERT/UPDATE/DELETE → nombre de lignes touchées.

        ⚠️ **Sans commit Dolt.** L'écriture reste dans le working set. Le commit
        confiné par tables, le gel avant suppression et la purge encadrée sont
        *l'écriture gouvernée* et les *traces* — deux autres briques de,
        qui viendront dans leur propre module. Les mêler ici est ce qui rend
        l'ancien `db.py` impossible à tester.
        """
        sql = traduire(sql, self.config.backend)
        if self.config.backend == DOLT:
            with self._verrou:
                conn = self._connexion_dolt()
                curseur = conn.cursor()
                n = curseur.execute(sql, params)
                # Pas de `commit()` quand le serveur est en autocommit : chaque
                # statement l'est deja, et l'appel ne serait qu'un aller-retour
                # de plus par ecriture. En mode transactionnel il est requis.
                if not self.config.autocommit:
                    conn.commit()
                return n
        conn = self._connexion_sqlite()
        try:
            curseur = conn.execute(sql, params)
            conn.commit()
            return curseur.rowcount
        finally:
            conn.close()

    # ── connexions ──────────────────────────────────────────────────────────

    def _connexion_sqlite(self) -> sqlite3.Connection:
        """Une connexion SQLite — et les deux pragmas que l'ancien moteur posait.

        🔴 `foreign_keys` est **OFF par défaut dans SQLite**, et ce réglage est
        par CONNEXION : une base dont le schéma déclare des clés étrangères ne
        les fait respecter que si chaque connexion le demande. Ne pas le poser
        ne casse rien visiblement — ça laisse simplement entrer des lignes
        orphelines, silencieusement. C'est une garantie d'intégrité, pas une
        préférence d'installation : elle appartient au CORE.

        `journal_mode=WAL` est repris du moteur en place, où il permet à un
        lecteur et un écrivain de cohabiter. Contrairement au précédent, il
        s'inscrit dans le fichier et vaut pour toutes les connexions suivantes.
        """
        conn = sqlite3.connect(str(self.config.chemin))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _connexion_dolt(self):
        """La connexion Dolt, persistante — et son mode d'écriture VÉRIFIÉ.

        🔴 **Le paramètre `autocommit` de pymysql ne suffit pas contre Dolt.**
        Mesuré le 11/09 sur un serveur jetable (Dolt 1.84.0) : le paquet
        d'authentification de Dolt **ne pose pas** le drapeau
        `SERVER_STATUS_AUTOCOMMIT`. pymysql en conclut que la connexion est déjà
        en autocommit *off*, compare `False != False`, et **n'envoie donc
        rien**. Le serveur reste à `@@autocommit = 1`.

            handshake seul : flag = False   mais @@autocommit = 1

        Ce qui rendait l'ancien `autocommit=False` inopérant — et le dépôt se
        croyait transactionnel, `commit()` à l'appui, pendant que le serveur
        commitait tout seul. Deux erreurs qui se compensent. Le jour où Dolt
        corrige son drapeau, les lectures d'une connexion partagée se figent sur
        un instantané : `SET AUTOCOMMIT = 0` envoyé à la main sur ce même serveur
        fige aussitôt les lectures répétées. Rien ne lève, tout répond, et les
        réponses datent.

        On ne fait donc pas confiance au paramètre : on **pose** le mode par un
        statement, puis on **relit** `@@autocommit` pour vérifier qu'il a pris.
        Un dépôt qui ne sait pas dans quel mode il écrit ne doit pas écrire.
        """
        if self._conn is not None:
            try:
                self._conn.ping(reconnect=True)
                return self._conn
            except Exception:                              # noqa: BLE001
                self._conn = None
        import pymysql                                     # tardif : optionnel
        conn = pymysql.connect(
            host=self.config.hote, port=self.config.port,
            user=self.config.utilisateur, database=self.config.base,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=self.config.autocommit)
        vise = 1 if self.config.autocommit else 0
        curseur = conn.cursor()
        curseur.execute(f"SET AUTOCOMMIT = {vise}")
        curseur.execute("SELECT @@autocommit AS ac")
        obtenu = int(curseur.fetchone()["ac"])
        if obtenu != vise:
            conn.close()
            raise RuntimeError(
                f"le serveur refuse le mode d'écriture demandé : "
                f"@@autocommit = {obtenu}, attendu {vise}. Écrire sans savoir "
                f"si les statements sont commités n'est pas une option.")
        self._conn = conn
        return self._conn

    def ferme(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def etat(self) -> dict:
        cible = (str(self.config.chemin) if self.config.backend == SQLITE
                 else f"{self.config.hote}:{self.config.port}/{self.config.base}")
        return {"backend": self.config.backend, "cible": cible}
