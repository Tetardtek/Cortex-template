#!/usr/bin/env python3
"""
brain-engine/db.py — Couche d'abstraction DB pour le brain-engine.

Point d'entrée unique pour toutes les requêtes DB.
Backend switché via BRAIN_DB_BACKEND (sqlite | dolt).

Usage :
    from db import query, query_one, execute, count

    rows = query("SELECT * FROM claims WHERE status = %s", ('open',))
    row  = query_one("SELECT COUNT(*) as n FROM embeddings WHERE indexed = 1")
    n    = execute("UPDATE claims SET status = %s WHERE sess_id = %s", ('closed', sid))
    c    = count("embeddings", "indexed = 1")

Convention :
    - Placeholders : %s partout (converti en ? pour sqlite en interne)
    - Dates : NOW(), DATE_ADD(x, INTERVAL n HOUR) — traduits par backend
    - Pas de PRAGMA, pas de sqlite_master — utiliser les helpers
"""

import functools
import re
import os
import logging
import threading
from pathlib import Path

log = logging.getLogger('brain-db')

# ── Config ──────────────────────────────────────────────────────────────────

# Deux racines, une source : `racines.py`. La data est reçue
# (`BRAIN_ROOT`), le programme se sait où il est.
from racines import DONNEES as BRAIN_ROOT, PROGRAMME

# Auto-load .env.local si présent (desktop sans pm2) — à côté du PROGRAMME
_env_local = PROGRAMME / '.env.local'
if _env_local.exists():
    for line in _env_local.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

BACKEND     = os.getenv('BRAIN_DB_BACKEND') or 'dolt'    # dolt | sqlite — dolt par défaut (BRAIN-074)

DB_PATH     = Path(os.getenv('BRAIN_DB_PATH') or str(BRAIN_ROOT / 'brain.db'))
DOLT_DIR    = Path(os.getenv('BRAIN_DOLT_DIR') or str(BRAIN_ROOT / 'brain-dolt'))
DOLT_PORT   = int(os.getenv('BRAIN_DOLT_PORT') or '3307')
DOLT_HOST   = os.getenv('BRAIN_DOLT_HOST') or '127.0.0.1'
DOLT_USER   = os.getenv('BRAIN_DOLT_USER') or 'root'

DOLT_DB     = os.getenv('BRAIN_DOLT_DB') or 'brain-dolt'

# ⚠️ Placé ici, après les constantes, et pas à côté de `BACKEND` où il serait
# plus lisible : il NOMME `DB_PATH`, donc il ne peut pas s'exécuter avant.
# Écrit d'abord là-haut, il levait `NameError` — sur le seul chemin qu'il
# existait pour éclairer. Trouvé en exerçant ce chemin, pas en le relisant.
# 🔴 Ce défaut décide QUELLE BASE le brain lit, et il s'applique en silence.
#
# Mesuré le 16/09 : `.env.local` porte `BRAIN_DB_BACKEND=dolt`, donc le défaut
# ne sert jamais ici. Mais qu'il disparaisse — nouvelle machine, fork, fichier
# non copié — et le brain bascule sur `sqlite`, vers `brain.db`, qui **n'existe
# pas sur cette instance**. `sqlite3.connect()` ne refuse pas un chemin absent :
# il CRÉE le fichier. Le brain travaillerait donc sur une base vide en croyant
# lire la sienne, sans qu'une seule erreur soit levée.
#
# Ce n'est pas une hypothèse : le 10/09, une sonde `sqlite3.connect()` a laissé
# un `brain.db` vide à la racine, trouvé deux heures plus tard par `brain
# doctor`. Le même mode de défaillance, par un autre chemin.
#
# Le défaut est `dolt` depuis le 27/09 — tranché par Kevin : Dolt est
# le socle (BRAIN-074), et `scripts/dolt-setup.sh` sait désormais l'installer
# chez un fork. SQLite reste possible, mais DÉCLARÉ : un fichier absent n'est plus
# créé en silence par défaut. Et le défaut, quel qu'il soit, se déclare quand il
# s'applique : il décide de la source de vérité.
if not os.environ.get('BRAIN_DB_BACKEND'):   # absent OU vide : même repli, même aveu
    log.warning(
        "BRAIN_DB_BACKEND non declare — repli sur `%s`. La base lue sera %s. "
        "Si ce n'est pas voulu, `.env.local` est absent ou n'a pas ete charge "
        "(cherche dans %s).",
        BACKEND, DB_PATH if BACKEND == 'sqlite' else 'le depot Dolt', _env_local)


# ── Le CORE de Myéline ──────────────────────────────────────────────────────
#
# Sixième et dernier branchement. Ce module ne PORTE plus la couche
# d'accès aux données : il la reçoit du CORE, et garde ce qui n'a de sens que
# pour CETTE instance — où vivent ses données, et comment elle les joint.
#
#   core.persistance  la traduction du SQL portable, et le dépôt
#   core.traces       le commit confiné, le gel, la purge encadrée
#
# La frontière est la même que pour les cinq précédents : **le CORE dit ce qui
# est permis, l'instance dit ce qu'elle range.** Les variables d'environnement
# ci-dessus, le repli `.env.local`, le nom du fichier SQLite : rien de tout ça
# ne veut dire quoi que ce soit hors d'ici, et rien de tout ça ne part.
#
# Pas de repli si le CORE manque. Les cinq autres branchements en ont un, parce
# qu'une garde qui s'abstient vaut mieux qu'une garde absente. Ici ce serait
# recopier le CORE dans le module qu'on branche — et `search.py`, `embed.py` et
# `server.py` l'importent déjà : un brain sans `core` est déjà arrêté. Mieux
# vaut le dire à l'import que le découvrir à la première requête.
try:
    from core.persistance import DOLT, SQLITE, Config, Depot, traduire
    from core.traces import Journal, SansVersionnement, tables_ecrites
except ImportError as _exc:                                # pragma: no cover
    raise ImportError(
        f"le CORE de Myéline est introuvable ({_exc}). Il s'installe depuis "
        f"le dépôt `myeline` : `pip install -e . --user`. Sans lui, "
        f"brain-engine n'a pas de couche de données."
    ) from _exc


_DEPOT = None
_JOURNAL = None


def _depot() -> Depot:
    """Le dépôt du CORE, construit une fois depuis la configuration d'ici.

    La configuration est POUSSÉE, jamais devinée : c'est la condition pour que
    le CORE reste un programme et `brain/` de la data. Le dépôt du CORE, lui,
    refuserait de deviner un chemin SQLite.
    """
    global _DEPOT
    if _DEPOT is None:
        if BACKEND == 'dolt':
            _DEPOT = Depot(Config(backend=DOLT, hote=DOLT_HOST, port=DOLT_PORT,
                                  utilisateur=DOLT_USER, base=DOLT_DB,
                                  autocommit=True))
        else:
            _DEPOT = Depot(Config(backend=SQLITE, chemin=DB_PATH))
    return _DEPOT


class _DepotSerialise:
    """Le dépôt du CORE, chaque appel pris sous `_dolt_verrou` — ce qu'on PASSE
    au CORE (`BSI(db.depot())`, `Recherche(db.depot(), …)`).

    Avant, `server.py` lui passait CE MODULE, qui imitait une partie de
    l'interface du `Depot`. Chaque méthode ajoutée au `Depot` et appelée par le
    CORE devait être recopiée ici à la main ; oubliée une fois (`colonne_existe`),
    toute ouverture de claim par le moteur rendait 500. La façade divergeait
    déjà ailleurs : `table_exists` pour `table_existe`, ni `config` ni `ferme`.

    Ici rien n'est recopié : tout est DÉLÉGUÉ au vrai `Depot`. Une méthode
    présente ou future existe d'office.

    Et pourquoi pas `_depot()` tout nu : le `Depot` a son verrou, mais PAR
    INSTRUCTION. `_dolt_verrou`, ré-entrant, garde atomiques « écriture +
    commit confiné » sous la concurrence du moteur — une écriture du CORE ne
    doit pas pouvoir se glisser entre l'écriture d'un autre fil et son commit.
    Un attribut (`config`) est rendu tel quel ; seul un appel prend le verrou.
    """

    def __getattr__(self, nom: str):
        if nom.startswith('_'):
            raise AttributeError(nom)
        cible = getattr(_depot(), nom)
        if not callable(cible):
            return cible

        @functools.wraps(cible)
        def appel(*args, **kwargs):
            with _dolt_verrou:
                return cible(*args, **kwargs)
        return appel


_DEPOT_SERIALISE = _DepotSerialise()


def depot() -> _DepotSerialise:
    """Le dépôt à passer au CORE — le vrai `Depot`, sérialisé. Une seule forme,
    pour le moteur (plusieurs fils) comme pour les scripts (un seul)."""
    return _DEPOT_SERIALISE


def _journal() -> Journal:
    """La discipline d'écriture, posée sur ce dépôt."""
    global _JOURNAL
    if _JOURNAL is None:
        _JOURNAL = Journal(_depot())
    return _JOURNAL


def _prepare_sql(sql: str) -> str:
    """Le SQL portable vers le dialecte du backend — par le CORE.

    Les quatre traducteurs qui vivaient ici (`upsert`, `date_add`,
    `timestampdiff`, dialecte) sont partis dans `core.persistance.traduire`.
    Équivalence prouvée AVANT le branchement, au seul moment où c'était
    possible : 104 requêtes SQL distinctes extraites du brain-engine par AST —
    et non choisies à la main — comparées sur les deux backends, 208
    comparaisons, **zéro écart**, témoin négatif positif.

    Le CORE en corrige un défaut au passage : `TIMESTAMPDIFF` avec une unité
    autre que HOUR ou MINUTE rendait un différentiel en JOURS, silencieusement.
    Mesuré : ce brain n'emploie que MINUTE et HOUR, rien de vivant ne change.
    """
    return traduire(sql, BACKEND)


def _sqlite_conn():
    """Connexion sqlite3 — celle du CORE, pragmas compris.

    Les deux pragmas que ce module posait (`journal_mode=WAL`,
    `foreign_keys=ON`) sont partis dans le CORE le 11/09. `foreign_keys` n'est
    pas un confort : il est OFF par defaut dans SQLite, il vaut par CONNEXION,
    et sans lui une base a cles etrangeres laisse entrer des lignes orphelines
    sans un bruit. C'est une garantie d'integrite — elle appartient au
    programme, pas a l'installation.
    """
    return _depot()._connexion_sqlite()


def _sqlite_query(sql: str, params: tuple = ()) -> list[dict]:
    return _depot().query(sql, params)


def _sqlite_query_one(sql: str, params: tuple = ()) -> dict | None:
    return _depot().query_one(sql, params)


def _sqlite_execute(sql: str, params: tuple = ()) -> int:
    return _depot().execute(sql, params)


# ── Dolt Backend (pymysql → dolt sql-server) ─────────────────────────────

# ── Une connexion, plusieurs fils ───────────────────────────────────
#
# La connexion Dolt vit desormais dans le `Depot` du CORE, mais elle reste
# unique et partagee — et ce verrou-ci la protege toujours. Les routes `async` de server.py sont
# serialisees par la boucle d'evenements, mais celles declarees `def` — `/visualize`,
# `/workflows` — tournent dans le threadpool de FastAPI. pymysql n'est pas concu
# pour ca : mesure du 03/09, quatre fils lisant la meme connexion rendent
# 25 lectures sur 100 et trois exceptions de protocole (« Packet sequence number
# wrong », « read of closed file »).
#
# Le verrou est re-entrant a dessein : `purge()` compose gel + operation + commit,
# et ces trois etapes doivent etre atomiques pour que la garantie — un commit
# ne porte que sa table — tienne encore sous concurrence. Sans lui, un
# autre fil peut ecrire entre l'operation et son commit.
_dolt_verrou = threading.RLock()


def _serialise(fn):
    """Serialise les acces a la connexion Dolt partagee."""
    @functools.wraps(fn)
    def enveloppe(*args, **kwargs):
        with _dolt_verrou:
            return fn(*args, **kwargs)
    return enveloppe


@_serialise
def _dolt_get_conn():
    """La connexion pymysql persistante — celle du CORE.

    Elle reconnecte toute seule, comme avant. Ce qui change : le CORE **pose**
    son mode d'ecriture par un statement puis le **relit**, au lieu de faire
    confiance au parametre de pymysql.

    Mesure du 11/09 sur un serveur jetable : Dolt 1.84.0 ne pose pas le drapeau
    `SERVER_STATUS_AUTOCOMMIT` dans son paquet d'authentification, et pymysql en
    conclut qu'il n'a rien a envoyer. Le `autocommit=True` ecrit ici depuis des
    mois n'arrivait donc jamais au serveur — qui se trouvait deja dans ce mode.
    Deux erreurs qui se compensaient.
    """
    return _depot()._connexion_dolt()


# ── Discipline d'ecriture ───────────────────────────────────────────
#
# Les donnees sont versionnees, mais l'attribution ne l'etait pas : `DOLT_ADD('.')`
# stage TOUT, donc un commit « embed: N vecteurs » emportait aussi les claims et
# les hit_count qui trainaient dans le working set. Revocable en theorie,
# introuvable en pratique.
#
# Deux regles, l'une mecanique et l'autre de procedure :
#
#   1. Un commit ne porte que ce que son message decrit — `DOLT_ADD` cible les
#      tables nommees. `'.'` est reserve au gel, seul endroit ou « tout » est
#      justement ce qu'on veut capturer.
#   2. Avant toute operation destructive : geler, operer, dater. Sans le gel, le
#      commit de purge emporte ce qui trainait, et l'annuler annulerait des
#      choses sans rapport. Le remede serait pire que le mal.

# La derivation des tables ecrites est partie dans `core.traces`, avec la
# subtilite qui l'a forgee : la queue d'upsert contient un second
# `UPDATE ... SET` qui ne nomme pas une table — sans la coupe,
# `INSERT ... ON CONFLICT DO UPDATE SET x=1` produisait la table « set », et
# `DOLT_ADD('set')` echouait. Temoin pose avant d'y croire.


def _tables_from_sql(sql: str) -> list[str]:
    """Tables ecrites par un statement — par le CORE.

    Le nom reste : `tools/test_dolt_discipline.py` l'appelle, et sa batterie de
    formes SQL est precisement ce qui eprouve cette derivation depuis.
    """
    return tables_ecrites(sql)


def _tables_inconnues(noms: list[str]) -> list[str]:
    """Parmi `noms`, ceux qui ne correspondent a aucune table."""
    return _journal()._tables_inconnues(noms)


@_serialise
def _dolt_commit(message: str, tables: list[str] | None = None):
    """Un commit Dolt confine aux tables nommees — par le CORE.

    `tables=None` stage tout : reserve au gel, seul endroit ou « tout » est
    justement ce qu'on veut capturer. Une table introuvable n'echoue pas
    l'ecriture, elle elargit le commit en le disant fort.

    Deux modules l'importent directement (`distill`, `embed`) : le nom reste,
    le mecanisme part.
    """
    _journal().commit(message, tables)


def dirty_tables() -> list[str]:
    """Tables modifiees et non commitees. Liste vide sans versionnement."""
    return _journal().tables_sales()


@_serialise
def freeze(reason: str) -> list[str]:
    """Fige l'etat courant avant une operation destructive.

    Retourne les tables gelees ; liste vide si rien ne trainait — auquel cas
    aucun commit n'est cree, un commit vide ne protegerait rien.
    """
    return _journal().gele(reason).tables


@_serialise
def purge(sql: str, params: tuple = (), *, reason: str = '', tables: list[str] | None = None) -> int:
    """DELETE encadre : geler, operer, dater.

    🔴 **Ne degenere plus en un simple execute sans versionnement.**

    Jusqu'au 11/09, sur un backend SQLite, cette fonction supprimait sans geler
    et sans le dire : l'appelant se croyait protege par une garantie qui
    n'existait pas sur son backend. Le CORE refuse desormais — « un dispositif
    de securite qui s'efface en silence est pire que son absence ».

    Sans effet sur ce brain, qui tourne en Dolt depuis des mois (`BRAIN-074` :
    *Dolt est le socle de persistance*). Ce qui change, c'est ce qu'un fork
    herite : une erreur franche plutot qu'une suppression sans filet.
    """
    return _journal().purge(sql, params, raison=reason, tables=tables)


@_serialise
def _dolt_query(sql: str, params: tuple = ()) -> list[dict]:
    return _depot().query(sql, params)


@_serialise
def _dolt_query_one(sql: str, params: tuple = ()) -> dict | None:
    return _depot().query_one(sql, params)


@_serialise
def _dolt_execute(sql: str, params: tuple = (), commit_msg: str | None = None,
                  tables: list[str] | None = None) -> int:
    """L'ecriture, et son commit confine — l'assemblage reste ici.

    Le CORE separe les deux a dessein : `Depot.execute` ecrit, `Journal.commit`
    attribue. C'est leur melange qui rendait l'ancien module impossible a
    eprouver sans une base Dolt vivante. Les recomposer est le travail de
    l'instance, et le verrou re-entrant ci-dessus est ce qui garde les deux
    etapes atomiques.
    """
    rowcount = _depot().execute(sql, params)
    if commit_msg:
        cibles = tables or _tables_from_sql(_prepare_sql(sql))
        if not cibles:
            # Le commit part quand meme — mieux vaut une ecriture attribuee
            # grossierement qu'une ecriture qui flotte. Mais il se plaint.
            log.error('execute: tables indeterminees dans %r — commit elargi a tout',
                      sql[:120])
        _dolt_commit(commit_msg, cibles or None)
    return rowcount


# ── Public API ──────────────────────────────────────────────────────────────

def query(sql: str, params: tuple = ()) -> list[dict]:
    """SELECT → list of dicts."""
    if BACKEND == 'dolt':
        return _dolt_query(sql, params)
    return _sqlite_query(sql, params)


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """SELECT → first row as dict, or None."""
    if BACKEND == 'dolt':
        return _dolt_query_one(sql, params)
    return _sqlite_query_one(sql, params)


def execute(sql: str, params: tuple = (), commit_msg: str | None = None,
            tables: list[str] | None = None) -> int:
    """INSERT/UPDATE/DELETE → rowcount (-1 si dolt).

    `commit_msg` cree un commit Dolt confine aux tables ecrites (deduites du SQL,
    ou nommees via `tables`). Sans lui, l'ecriture reste dans le working set —
    acceptable pour les compteurs a haute frequence, jamais pour un evenement.
    Pour un DELETE, preferer `purge()` : il gele avant d'operer.
    """
    if BACKEND == 'dolt':
        return _dolt_execute(sql, params, commit_msg=commit_msg, tables=tables)
    return _sqlite_execute(sql, params)


def count(table: str, where: str = '1=1') -> int:
    """Raccourci COUNT(*) sur une table."""
    row = query_one(f"SELECT COUNT(*) as n FROM {table} WHERE {where}")
    if row:
        return int(row['n'])
    return 0


# ── Le réseau des branches — BRAIN-078 ───────────────────────────────────────
#
# Une machine satellite (le laptop) écrit sur SA branche de cette base, et ses
# sessions portent le suffixe de sa machine : `sess-…-<slug>.laptop` sur la
# branche `laptop`. Lue seule, `claims` ne montre donc que le fixe. Ici, chaque
# machine fait foi pour ses lignes : les claims `.<branche>` viennent de leur
# branche, tous les autres de `main` — une ligne du laptop déjà fusionnée dans
# `main` n'y est pas lue en double, et c'est sa version sur la branche qui
# compte. Sur SQLite, ou quand on est soi-même sur une branche (le laptop voit
# `main` par son rafraîchissement), il n'y a pas de satellites.

_NOM_DE_BRANCHE = re.compile(r'^[a-z0-9][a-z0-9-]*$')


def branches_satellites() -> list[str]:
    """Les branches autres que `main`, dont le nom peut servir de suffixe."""
    if BACKEND != 'dolt' or '/' in DOLT_DB:
        return []
    noms = [r['name'] for r in query("SELECT name FROM dolt_branches")]
    return sorted(n for n in noms if n != 'main' and _NOM_DE_BRANCHE.match(n))


def claims_du_reseau(where: str = '1=1', params: tuple = (), colonnes: str = '*') -> list[dict]:
    """Les claims de cette base, et ceux que chaque satellite a ouverts sur sa
    branche. Chaque ligne porte `_branche` : None pour la base, sinon la branche."""
    satellites = branches_satellites()
    exclure = ''.join(" AND sess_id NOT LIKE %s" for _ in satellites)
    lignes = query(f"SELECT {colonnes} FROM claims WHERE ({where}){exclure}",
                   tuple(params) + tuple(f'%.{b}' for b in satellites))
    for r in lignes:
        r['_branche'] = None
    for b in satellites:
        venues = query(f"SELECT {colonnes} FROM `{DOLT_DB}/{b}`.claims "
                       f"WHERE ({where}) AND sess_id LIKE %s", tuple(params) + (f'%.{b}',))
        for r in venues:
            r['_branche'] = b
        lignes += venues
    return lignes


def ouverts_du_reseau() -> list[dict]:
    """Les claims ouverts de tout le réseau, dans la forme que le verrou du CORE
    attend — à passer à `BSI(depot(), ouverts_du_reseau=…)` (BRAIN-078).

    Le verrou de scope (`conflit`, `recouvrements`, `ouvre`) voit alors aussi
    les claims que chaque machine satellite a ouverts sur sa branche. La route
    construit le `BSI` elle-même : c'est ce que `branchements_du_core.py`
    vérifie — le CORE branché là où il décide.
    """
    return claims_du_reseau("status = 'open'",
                            colonnes="sess_id, scope, type, zone, opened_at, expires_at, project")


def table_exists(table: str) -> bool:
    """Vérifie si une table existe — par le CORE, qui connait les deux formes."""
    if BACKEND == 'dolt':
        with _dolt_verrou:
            return _depot().table_existe(table)
    return _depot().table_existe(table)


def colonne_existe(table: str, colonne: str) -> bool:
    """La colonne est-elle dans la table ? — par le CORE.

    Pour le code du BRAIN qui interroge la base (le garde de zone). Le CORE,
    lui, ne reçoit plus ce module : il reçoit `depot()`, le vrai `Depot`
    sérialisé. C'est ici qu'était né le défaut — `server.py` passait ce module
    au CORE, et quand `BSI.ouverts()` s'est mis à appeler `colonne_existe`,
    toute ouverture de claim par le moteur aurait rendu 500 (26/09, trouvé par
    un moteur d'essai avant la prod).
    """
    if BACKEND == 'dolt':
        with _dolt_verrou:
            return _depot().colonne_existe(table, colonne)
    return _depot().colonne_existe(table, colonne)


def get_raw_connection():
    """Retourne une connexion sqlite3 brute — UNIQUEMENT pour les cas legacy
    qui nécessitent un accès direct (vectors binaires, cursors custom).
    À éliminer progressivement.

    Le CORE ne la rapatrie pas, et c'est delibere : un acces brut qui ne
    fonctionne que sur un backend n'est pas une capacite, c'est une dette. Elle
    reste donc ici, ou elle a un nom et une date de peremption.
    """
    if BACKEND == 'dolt':
        raise RuntimeError('get_raw_connection() non supporté en mode dolt — utiliser query/execute')
    return _sqlite_conn()


# ── Info ────────────────────────────────────────────────────────────────────

def info() -> dict:
    """Retourne les infos de la couche DB pour /health et debug."""
    return {
        'backend': BACKEND,
        'db_path': str(DB_PATH) if BACKEND == 'sqlite' else str(DOLT_DIR),
        'status': 'ok',
    }
