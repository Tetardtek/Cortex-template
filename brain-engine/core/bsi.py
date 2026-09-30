"""BSI — claims et locks. La sixième capacité du CORE. [BRAIN-042]

Rapatrié de `scripts/bsi-claim.sh` le 06/09 : 440 lignes de shell dont l'essentiel
est du métier noyé dans une interface en ligne de commande. **Le CORE porte le
métier, la CLI devient une porte** — c'est le sens de, « un binaire,
plusieurs portes ».

Une session EST un claim. Le claim dit qui travaille, sur quoi, depuis quand, et
il est la seule chose qui empêche deux sessions d'écrire au même endroit sans le
savoir.

── Les quatre règles, et ce qu'elles ont coûté d'apprendre ─────────────────

**1. Un identifiant se valide.** `args[0]` était pris sans être regardé : un
appel mal analysé enregistrait un claim sous le nom de son option. La table en
porte deux — `--type` et `pilote` — et pour chacun la session réelle n'a jamais
existé sous son nom.

**2. Le temps se compte en UTC, des deux côtés.** `NOW()` rendait l'heure locale
quand `opened_at` est écrit en UTC : l'âge était surestimé du décalage — 2 h en
CEST. Une session de 2 h 01 était déclarée périmée sous un TTL de 4 h, et le
claim se fermait sous les pieds de qui travaillait dedans (22/08).

**3. On mesure depuis l'EXPIRATION, pas depuis l'ouverture.** L'âge depuis
l'ouverture ne peut que grandir : dix claims vivants ont été fermés en
« stale-auto-closed », de 9,6 h à 76,8 h, tous de type `pilote` — c'étaient des
sessions longues, pas des oublis.

**4. La session naît avec le claim.** Rien ne planifiait la dérivation : la
table `sessions` ne se remplissait qu'à la main, et le contrôle « registres en
base » rougissait à chaque boot sur un état sain.

── Ce que ce module ne fait pas ────────────────────────────────────────────

Il ne connaît **aucun chemin**, ne lit **aucun environnement**, et n'ouvre
**aucune connexion** : il reçoit un `Depot`. C'est ce qui le rend testable sur
une base jetable — l'ancien script ne l'était pas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.persistance import Depot

# Ce que cette brique possède. Un module retiré doit emporter ses tables —
# c'est la condition pour qu'un fork puisse n'en installer qu'une partie.
TABLES = frozenset({"claims", "locks"})

SESS_ID = re.compile(r"^sess-[0-9A-Za-z][\w.-]*$")
TTL_HEURES = 4


class IdentifiantInvalide(ValueError):
    """Un claim ouvert sous le nom d'une option n'appartient à personne."""


def en_utc(valeur) -> datetime | None:
    """Une date, quelle que soit la forme que le backend lui donne.

    ⚠️ **Dolt rend des `datetime`, SQLite des chaînes.** Supposer l'un des deux
    a coûté 43 claims fermés avec 43 durées nulles — un `TypeError` avalé par un
    `except: pass` (22/08). J'avais documenté le piège dans `BSI.ferme()` et je
    suis retombé dedans en écrivant `Verrou.expire`, le 06/09.

    D'où cette fonction : une seule conversion, appelée partout. Une leçon écrite
    à un endroit ne protège pas les autres.
    """
    if valeur is None:
        return None
    if not isinstance(valeur, datetime):
        try:
            valeur = datetime.strptime(str(valeur)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return valeur.replace(tzinfo=timezone.utc) if valeur.tzinfo is None else valeur


class ConflitDeVerrou(RuntimeError):
    """Un fichier est déjà tenu par quelqu'un d'autre."""

    def __init__(self, chemin: str, detenteur: str, expire_le) -> None:
        self.chemin, self.detenteur, self.expire_le = chemin, detenteur, expire_le
        super().__init__(
            f"« {chemin} » est tenu par {detenteur} jusqu'à {expire_le}")


class ConflitDeScope(RuntimeError):
    """Deux sessions se disputent la même zone."""

    def __init__(self, existant: str, scope_existant: str, demande: str) -> None:
        self.existant, self.scope_existant, self.demande = existant, scope_existant, demande
        super().__init__(
            f"zone kernel verrouillée par « {existant} » (scope {scope_existant}) — "
            f"fermer ce claim avant d'ouvrir « {demande} »")


class ClaimDUneAutreSession(RuntimeError):
    """Fermer le claim qu'une AUTRE session a ouvert —, BRAIN-077.

    Le 26/09, une session a fermé le claim d'une autre en relisant un fichier
    commun à toute la machine (`~/.claude/session-role`). La fermeture a réussi
    et rien n'a crié : l'autre session a continué sans claim, invisible.
    """

    def __init__(self, sess_id: str, sienne: str, demandeur: str) -> None:
        self.sess_id, self.sienne, self.demandeur = sess_id, sienne, demandeur
        super().__init__(
            f"{sess_id} appartient à la session {sienne}, pas à {demandeur}")


@dataclass
class Verrou:
    """Un verrou sur UN fichier — là où le claim porte sur un scope.

    Les deux sont complémentaires : le claim dit « je travaille sur ce
    périmètre », le verrou dit « n'écrivez pas ce fichier maintenant ».
    """
    chemin: str
    detenteur: str
    pris_le: datetime | None = None
    expire_le: datetime | None = None
    ttl_min: int = 30

    @property
    def expire(self) -> bool:
        fin = en_utc(self.expire_le)
        return True if fin is None else datetime.now(timezone.utc) >= fin


@dataclass
class Claim:
    sess_id: str
    scope: str
    type: str
    zone: str
    ouvert_le: datetime | None = None
    expire_le: datetime | None = None
    projet: str | None = None
    # La session d'agent qui porte le claim (`CLAUDE_CODE_SESSION_ID` pour Claude
    # Code). `None` : claim ancien, base sans la colonne, ou ouvert hors agent.
    agent_session: str | None = None

    @property
    def age_heures(self) -> float | None:
        ouvert = en_utc(self.ouvert_le)
        if ouvert is None:
            return None
        return (datetime.now(timezone.utc) - ouvert).total_seconds() / 3600


def valide(sess_id: str) -> str:
    """L'identifiant, ou rien. Le doute refuse plutôt que d'écrire n'importe quoi."""
    if SESS_ID.match(sess_id):
        return sess_id
    raise IdentifiantInvalide(
        f"identifiant invalide : {sess_id!r} — attendu sess-<AAAAMMJJ>-<HHMM>-<slug>")


def autre_session(sienne: str | None, par: str | None) -> bool:
    """Le claim appartient-il à une AUTRE session que celle qui demande ? — BRAIN-077

    Vrai seulement entre deux identités CONNUES et DIFFÉRENTES. Sans demandeur
    (shell humain, cron, `close-stale`) ou sur un claim sans identité, faux :
    le refus ne doit jamais bloquer un geste légitime, sinon on apprend à le
    contourner.

    Fonction pure, et exportée : la route HTTP de fermeture écrit elle-même et
    n'appelle pas `ferme()`. Sans ce partage, la règle existerait en deux
    exemplaires — deux portes, une règle en double, qui dérive.
    """
    return bool(par and sienne and sienne != par)


def projet_depuis_scope(scope: str, projet: str | None = None) -> str | None:
    """Le projet, déclaré ou déduit du scope. Jamais deviné au-delà.

    Le scope suit `<type>/<projet>[/detail]` ou `<projet>/<detail>`. Hors de ces
    formes on rend `None` : un scope en texte libre ne nomme pas un projet, et
    en fabriquer un remplirait la table de faux noms.
    """
    if projet:
        return projet
    if "/" not in scope:
        return None
    parts = scope.split("/")
    connus = ("work", "brain", "explore", "pilote", "chill", "learning")
    if parts[0] in connus and len(parts) > 1:
        candidat = parts[1].strip()
    elif parts[0] not in connus and " " not in parts[0]:
        candidat = parts[0].strip()
    else:
        return None
    return candidat if candidat and len(candidat) < 30 else None


class BSI:
    """Les claims, posés sur un dépôt."""

    def __init__(self, depot: Depot, ouverts_du_reseau=None) -> None:
        """`ouverts_du_reseau` : une fonction sans argument qui rend les lignes
        des claims ouverts de TOUT le réseau (mêmes colonnes que `ouverts()`),
        quand l'instance en connaît plusieurs — BRAIN-078 : le laptop écrit sur
        sa branche de la base du fixe. Le CORE ne sait rien des branches ;
        l'instance lui dit où regarder. Elle ne sert qu'au VERROU
        (`recouvrements`, `conflit`, donc `ouvre`) : `ouverts()` et ce qui en
        dépend (la fermeture de ses propres claims) restent sur ce dépôt.
        """
        self.depot = depot
        self._porte_identite: bool | None = None
        self._ouverts_du_reseau = ouverts_du_reseau

    @property
    def porte_identite(self) -> bool:
        """La base sait-elle quelle session porte un claim ? — BRAIN-077

        `False` sur une base qui n'a pas encore la colonne `agent_session` : le
        BSI s'y comporte exactement comme avant. Mais l'appelant doit pouvoir le
        DIRE — une identité transmise et silencieusement jetée ressemblerait à
        une identité enregistrée. Demandé une fois par instance.
        """
        if self._porte_identite is None:
            self._porte_identite = self.depot.colonne_existe("claims", "agent_session")
        return self._porte_identite

    # ── lecture ─────────────────────────────────────────────────────────────

    @staticmethod
    def _claim(r: dict) -> Claim:
        return Claim(r["sess_id"], r["scope"], r["type"], r.get("zone") or "project",
                     r.get("opened_at"), r.get("expires_at"), r.get("project"),
                     r.get("agent_session"))

    def ouverts(self) -> list[Claim]:
        identite = ", agent_session" if self.porte_identite else ""
        return [self._claim(r)
                for r in self.depot.query(
                    "SELECT sess_id, scope, type, zone, opened_at, expires_at, project"
                    f"{identite} FROM claims WHERE status = 'open' ORDER BY opened_at")]

    def _ouverts_pour_le_verrou(self) -> list[Claim]:
        """Les claims qui peuvent bloquer : ceux du réseau si l'instance le
        connaît, sinon ceux de ce dépôt. Deux machines ne doivent pas ouvrir le
        même scope noyau parce que chacune ne regardait que sa base."""
        if self._ouverts_du_reseau is None:
            return self.ouverts()
        return [self._claim(r) for r in self._ouverts_du_reseau()]

    def de_la_session(self, agent_session: str) -> list[Claim]:
        """Les claims ouverts que CETTE session d'agent porte — BRAIN-077.

        Une liste et pas un claim : rien n'empêche une session d'en ouvrir deux,
        et choisir à la place de l'appelant serait deviner. Vide si la base ne
        porte pas l'identité — l'appelant le sait par `porte_identite`.
        """
        if not agent_session:
            return []
        return [c for c in self.ouverts() if c.agent_session == agent_session]

    def rattache(self, anciennes: list[str], nouvelle: str) -> list[str]:
        """Les claims ouverts portés par une identité ANCIENNE passent à la
        nouvelle. Rend leurs `sess_id` — vide si rien n'a bougé.

        Une session d'agent peut changer d'identité sans cesser d'être la même :
        parquée puis reprise dans un autre processus, elle en reçoit une neuve.
        Son claim porte alors l'ancienne, et devient « celui d'une autre
        session » — `close` sans argument ne le trouve plus, `close <id>` est
        refusé. Observé le 27/09 après un compactage.

        Le CORE ne sait pas QUI est l'ancienne identité : c'est à l'appelant de
        le PROUVER (une filiation écrite par l'agent), jamais de le deviner. Il
        garantit seulement de ne toucher qu'aux claims OUVERTS, et qu'à ceux-là.
        """
        if not self.porte_identite or not nouvelle:
            return []
        anciennes = [a for a in anciennes if a and a != nouvelle]
        if not anciennes:
            return []
        marques = ", ".join(["%s"] * len(anciennes))
        visés = [r["sess_id"] for r in self.depot.query(
            f"SELECT sess_id FROM claims WHERE status = 'open' "
            f"AND agent_session IN ({marques}) ORDER BY opened_at", tuple(anciennes))]
        for sess_id in visés:
            self.depot.execute(
                "UPDATE claims SET agent_session = %s WHERE sess_id = %s AND status = 'open'",
                (nouvelle, sess_id))
        return visés

    def est_ouvert(self, sess_id: str) -> bool:
        return self.depot.query_one(
            "SELECT sess_id FROM claims WHERE sess_id = %s AND status = 'open'",
            (valide(sess_id),)) is not None

    def perimes(self, heures_min: int | None = None) -> list[Claim]:
        """Les claims dont l'expiration est dépassée.

        Le seuil porte sur le temps écoulé DEPUIS L'EXPIRATION, pas depuis
        l'ouverture : une session longue n'est pas un oubli.
        """
        seuil = "0" if heures_min is None else str(int(heures_min))
        return [Claim(r["sess_id"], r["scope"], r["type"], r.get("zone") or "project",
                      r.get("opened_at"), r.get("expires_at"), r.get("project"))
                for r in self.depot.query(
                    "SELECT sess_id, scope, type, zone, opened_at, expires_at, project "
                    "FROM claims WHERE status = 'open' AND expires_at IS NOT NULL "
                    f"AND TIMESTAMPDIFF(HOUR, expires_at, UTC_TIMESTAMP()) >= {seuil} "
                    "ORDER BY expires_at")]

    # ── conflits ────────────────────────────────────────────────────────────

    def recouvrements(self, scope: str) -> list[Claim]:
        """Tous les claims ouverts dont le scope recouvre `scope`.

        Distinct de `conflit()` : celui-ci répond « qui BLOQUE », celui-là
        « qui SE CHEVAUCHE ». Hors zone `kernel`, un recouvrement ne bloque
        pas — mais il mérite d'être dit, et jusqu'au 11/09 seule une des deux
        portes le disait.

        `scripts/bsi-claim.sh` affichait « ⚠️ SCOPE OVERLAP détecté » avec les
        deux identifiants ; la route HTTP, qui n'avait que `conflit()`, se
        taisait. Basculer le script sur la route aurait donc **perdu
        l'avertissement** — une perte qu'aucune comparaison d'écritures ne
        montre, puisque les deux écrivent la même ligne.

        Le CORE dit ce qui se recouvre ; l'appelant décide s'il bloque, avertit
        ou se tait. C'est la même frontière que partout ailleurs.
        """
        return [claim for claim in self._ouverts_pour_le_verrou()
                if scope.startswith(claim.scope) or claim.scope.startswith(scope)]

    def conflit(self, scope: str, zone: str = "project") -> Claim | None:
        """Le claim qui bloque, s'il y en a un.

        Un recouvrement de scope en zone `kernel` bloque ; ailleurs il se
        signale et laisse passer — deux sessions peuvent travailler en
        parallèle sur des projets disjoints. Ce qui se signale sans bloquer est
        rendu par `recouvrements()`.
        """
        for claim in self.recouvrements(scope):
            if claim.zone == "kernel" or zone == "kernel":
                return claim
        return None

    # ── écriture ────────────────────────────────────────────────────────────

    def ouvre(self, sess_id: str, *, scope: str, type: str = "explore",
              zone: str = "project", projet: str | None = None,
              mode: str | None = None, ttl_heures: int = TTL_HEURES,
              agent_session: str | None = None) -> Claim:
        """Ouvre un claim. Lève `ConflitDeScope` si la zone est verrouillée.

        `agent_session` n'est écrit que si la base porte la colonne : le claim
        rendu dit alors ce qui a VRAIMENT été enregistré (`None` sinon), pas ce
        qui a été demandé.
        """
        sess_id = valide(sess_id)
        if self.est_ouvert(sess_id):
            return self.ouverts_par_id(sess_id)

        bloquant = self.conflit(scope, zone)
        if bloquant is not None:
            raise ConflitDeScope(bloquant.sess_id, bloquant.scope, sess_id)

        maintenant = datetime.now(timezone.utc)
        expire = maintenant + timedelta(hours=ttl_heures)
        fmt = "%Y-%m-%d %H:%M:%S"
        colonnes = ["sess_id", "type", "scope", "status", "opened_at", "zone",
                    "mode", "ttl_hours", "expires_at", "project"]
        valeurs = [sess_id, type, scope, "open", maintenant.strftime(fmt), zone,
                   mode, ttl_heures, expire.strftime(fmt),
                   projet_depuis_scope(scope, projet)]
        enregistree = agent_session if self.porte_identite else None
        if enregistree:
            colonnes.append("agent_session")
            valeurs.append(enregistree)
        self.depot.execute(
            f"REPLACE INTO claims ({', '.join(colonnes)}) "
            f"VALUES ({', '.join(['%s'] * len(colonnes))})",
            tuple(valeurs))
        return Claim(sess_id, scope, type, zone, maintenant, expire,
                     projet_depuis_scope(scope, projet), enregistree or None)

    def ouverts_par_id(self, sess_id: str) -> Claim | None:
        for c in self.ouverts():
            if c.sess_id == sess_id:
                return c
        return None

    def ferme(self, sess_id: str, *, resultat: str = "success",
              par: str | None = None, meme_si_autre: bool = False) -> int | None:
        """Ferme un claim et rend sa durée en minutes.

        La durée se calcule en UTC des deux côtés. Un `opened_at` peut arriver
        en `datetime` ou en chaîne selon le backend : accepter les deux formes
        est ce qui manquait quand 43 claims fermés portaient 43 durées nulles,
        un `TypeError` avalé par un `except: pass` (22/08).

        `par` : la session d'agent qui demande la fermeture. Si le claim porte
        une AUTRE session, `ClaimDUneAutreSession` — sauf `meme_si_autre`, levée
        nommée. Sans `par` (shell humain, cron, `close-stale`), ou sur un claim
        qui ne porte pas d'identité, rien ne change : le refus ne s'applique
        qu'entre deux identités connues et différentes. — BRAIN-077
        """
        sess_id = valide(sess_id)
        identite = ", agent_session" if self.porte_identite else ""
        ligne = self.depot.query_one(
            f"SELECT opened_at{identite} FROM claims "
            "WHERE sess_id = %s AND status = 'open'",
            (sess_id,))
        if ligne is None:
            return None

        sienne = ligne.get("agent_session")
        if autre_session(sienne, par) and not meme_si_autre:
            raise ClaimDUneAutreSession(sess_id, sienne, par)

        ouvert = en_utc(ligne.get("opened_at"))
        duree = (None if ouvert is None else
                 max(1, int((datetime.now(timezone.utc) - ouvert).total_seconds() / 60)))

        self.depot.execute(
            "UPDATE claims SET status = 'closed', closed_at = %s, result = %s, "
            "duration_min = %s WHERE sess_id = %s AND status = 'open'",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
             resultat, duree, sess_id))
        return duree

    def touche(self, sess_id: str, ttl_heures: int = TTL_HEURES) -> bool:
        """Repousse l'expiration — la session est vivante."""
        sess_id = valide(sess_id)
        expire = (datetime.now(timezone.utc) + timedelta(hours=ttl_heures))
        n = self.depot.execute(
            "UPDATE claims SET expires_at = %s WHERE sess_id = %s AND status = 'open'",
            (expire.strftime("%Y-%m-%d %H:%M:%S"), sess_id))
        return n != 0

    # ── verrous ─────────────────────────────────────────────────────────────
    #
    # Le TTL se compte en MINUTES, pas en heures : un verrou de fichier protège
    # une écriture, pas une séance. Et la comparaison se fait en UTC des deux
    # côtés — le défaut du 22/08 sur les claims vaut ici aussi.

    def verrous(self, *, actifs_seulement: bool = True) -> list[Verrou]:
        sql = ("SELECT filepath, holder, claimed_at, expires_at, ttl_min FROM locks")
        if actifs_seulement:
            sql += " WHERE UTC_TIMESTAMP() < expires_at"
        return [Verrou(r["filepath"], r["holder"], r.get("claimed_at"),
                       r.get("expires_at"), r.get("ttl_min") or 30)
                for r in self.depot.query(sql + " ORDER BY filepath")]

    def verrou_de(self, chemin: str) -> Verrou | None:
        r = self.depot.query_one(
            "SELECT filepath, holder, claimed_at, expires_at, ttl_min "
            "FROM locks WHERE filepath = %s", (chemin,))
        return Verrou(r["filepath"], r["holder"], r.get("claimed_at"),
                      r.get("expires_at"), r.get("ttl_min") or 30) if r else None

    def prend(self, chemin: str, detenteur: str, *, ttl_min: int = 30) -> Verrou:
        """Prend le verrou. Lève `ConflitDeVerrou` s'il est tenu par un autre.

        Un verrou **expiré** ne bloque pas : il est remplacé. C'est ce qui évite
        qu'une session morte gèle un fichier indéfiniment — et c'est pour ça que
        le TTL existe.
        """
        existant = self.verrou_de(chemin)
        if existant and existant.detenteur != detenteur and not existant.expire:
            raise ConflitDeVerrou(chemin, existant.detenteur, existant.expire_le)

        maintenant = datetime.now(timezone.utc)
        expire = maintenant + timedelta(minutes=ttl_min)
        fmt = "%Y-%m-%d %H:%M:%S"
        # Retirer puis poser : un `REPLACE` sur `filepath` supposerait une
        # contrainte d'unicité que le schéma ne déclare pas — la clé est `id`.
        self.depot.execute("DELETE FROM locks WHERE filepath = %s", (chemin,))
        self.depot.execute(
            "INSERT INTO locks (filepath, holder, claimed_at, expires_at, ttl_min) "
            "VALUES (%s, %s, %s, %s, %s)",
            (chemin, detenteur, maintenant.strftime(fmt),
             expire.strftime(fmt), ttl_min))
        return Verrou(chemin, detenteur, maintenant, expire, ttl_min)

    def relache(self, chemin: str, detenteur: str) -> bool:
        """Relâche le verrou. Refuse si un autre le tient.

        Rend `False` plutôt que de lever : relâcher ce qu'on ne tient pas est
        souvent un doublon de nettoyage, pas une faute. Mais on ne le retire
        jamais au nom de quelqu'un d'autre.
        """
        existant = self.verrou_de(chemin)
        if existant is None:
            return False
        if existant.detenteur != detenteur:
            return False
        self.depot.execute("DELETE FROM locks WHERE filepath = %s", (chemin,))
        return True
