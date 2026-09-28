#!/usr/bin/env python3
"""Ce que le BSI garantit. [BRAIN-042]

    python3 core/test_bsi.py

**Tout est éprouvé sur une base jetable**, écriture comprise — le BSI ne dépend
d'aucun service. C'est le premier module du CORE dont les garanties couvrent le
cycle complet : ouvrir, se disputer une zone, fermer, mesurer, expirer.

L'ancien `bsi-claim.sh` ne pouvait pas être testé ainsi : il ouvrait sa base à
l'import et écrivait dans celle du brain.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.bsi import (                                      # noqa: E402
    BSI, ClaimDUneAutreSession, ConflitDeScope, ConflitDeVerrou, IdentifiantInvalide,
    autre_session, projet_depuis_scope, valide,
)
from core.persistance import SQLITE, Config, Depot          # noqa: E402

_ok = _ko = 0
SCHEMA_LOCKS = """
CREATE TABLE locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, filepath TEXT, holder TEXT,
    claimed_at TEXT, expires_at TEXT, ttl_min INTEGER)
"""
SCHEMA = """
CREATE TABLE claims (
    sess_id TEXT PRIMARY KEY, type TEXT, scope TEXT, status TEXT,
    opened_at TEXT, closed_at TEXT, zone TEXT, mode TEXT,
    ttl_hours INTEGER, expires_at TEXT, project TEXT,
    result TEXT, duration_min INTEGER)
"""


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def refuse(nom: str, fn, exception) -> None:
    global _ok, _ko
    try:
        fn()
    except exception:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom} — rien n'a été refusé")


def identifiants() -> None:
    print("\nUN IDENTIFIANT SE VALIDE —\n")
    verifie("une forme correcte passe",
            valide("sess-20260906-1400-pilote-myeline"), "sess-20260906-1400-pilote-myeline")
    refuse("le nom d'une option est refusé",
           lambda: valide("--type"), IdentifiantInvalide)
    refuse("un mot nu est refusé", lambda: valide("pilote"), IdentifiantInvalide)
    refuse("le préfixe seul ne suffit pas", lambda: valide("sess-"), IdentifiantInvalide)


def projets() -> None:
    print("\nLE PROJET SE DÉDUIT, OU RESTE VIDE\n")
    verifie("<type>/<projet>", projet_depuis_scope("pilote/myeline"), "myeline")
    verifie("<projet>/<detail>", projet_depuis_scope("mon-projet/frontend"), "mon-projet")
    verifie("déclaré, il l'emporte",
            projet_depuis_scope("pilote/myeline", "autre"), "autre")
    verifie("sans séparateur, rien", projet_depuis_scope("brain"), None)
    verifie("du texte libre ne nomme pas un projet",
            projet_depuis_scope("une phrase avec des espaces/x"), None)


def cycle() -> None:
    print("\nLE CYCLE COMPLET, SUR UNE BASE JETABLE\n")
    with tempfile.TemporaryDirectory(prefix="core-bsi-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "b.db"))
        depot.execute(SCHEMA)
        bsi = BSI(depot)

        c = bsi.ouvre("sess-20260906-1400-pilote-myeline",
                      scope="pilote/myeline", type="pilote", zone="kernel")
        verifie("le claim est ouvert", bsi.est_ouvert(c.sess_id), True)
        verifie("le projet est déduit", c.projet, "myeline")
        verifie("un seul claim ouvert", len(bsi.ouverts()), 1)

        # Zone kernel : un scope qui recouvre doit être refusé.
        refuse("un scope recouvrant en zone kernel est bloqué",
               lambda: bsi.ouvre("sess-20260906-1401-autre",
                                 scope="pilote/myeline/detail", zone="kernel"),
               ConflitDeScope)

        # Zone project sur un scope disjoint : autorisé.
        bsi.ouvre("sess-20260906-1402-mon-projet", scope="work/mon-projet", zone="project")
        verifie("un scope disjoint passe", len(bsi.ouverts()), 2)

        # ── Ce qui se chevauche sans bloquer — ──────────────────────
        #
        # `conflit()` répond « qui BLOQUE » ; hors zone kernel, il rend None et
        # la question « qui se chevauche ? » restait sans réponse. Le shell
        # l'affichait (« SCOPE OVERLAP détecté »), la route HTTP se taisait :
        # basculer l'un sur l'autre aurait perdu l'avertissement, sans qu'une
        # comparaison d'écritures ne le montre — les deux écrivent pareil.
        verifie("un scope qui recouvre est VU, même hors kernel",
                [c.sess_id for c in bsi.recouvrements("pilote/myeline/detail")],
                ["sess-20260906-1400-pilote-myeline"])
        verifie("mais il ne bloque pas hors kernel",
                bsi.conflit("work/mon-projet/front", zone="project"), None)
        verifie("et il bloque en kernel",
                bsi.conflit("pilote/myeline/detail", zone="kernel").sess_id,
                "sess-20260906-1400-pilote-myeline")
        verifie("un scope disjoint ne recouvre personne",
                bsi.recouvrements("explore/rien-a-voir"), [])

        verifie("un identifiant inconnu n'est pas ouvert",
                bsi.est_ouvert("sess-20260906-9999-fantome"), False)

        duree = bsi.ferme(c.sess_id)
        verifie("la fermeture rend une durée", isinstance(duree, int), True)
        verifie("la durée est d'au moins une minute", duree >= 1, True)
        verifie("le claim n'est plus ouvert", bsi.est_ouvert(c.sess_id), False)
        verifie("fermer deux fois ne ment pas", bsi.ferme(c.sess_id), None)


def expiration() -> None:
    print("\nL'EXPIRATION SE MESURE DEPUIS L'EXPIRATION —\n")
    with tempfile.TemporaryDirectory(prefix="core-bsi-exp-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "b.db"))
        depot.execute(SCHEMA)
        bsi = BSI(depot)

        fmt = "%Y-%m-%d %H:%M:%S"
        maintenant = datetime.now(timezone.utc)

        # Une session LONGUE mais vivante : ouverte il y a 30 h, expiration
        # repoussée. L'ancien calcul la déclarait périmée sur son âge.
        depot.execute(
            "INSERT INTO claims (sess_id, type, scope, status, opened_at, "
            "expires_at, zone) VALUES (%s,'pilote','x','open',%s,%s,'project')",
            ("sess-20260905-0000-longue",
             (maintenant - timedelta(hours=30)).strftime(fmt),
             (maintenant + timedelta(hours=2)).strftime(fmt)))

        # Un vrai oubli : expiré depuis 6 h.
        depot.execute(
            "INSERT INTO claims (sess_id, type, scope, status, opened_at, "
            "expires_at, zone) VALUES (%s,'work','y','open',%s,%s,'project')",
            ("sess-20260905-0100-oublie",
             (maintenant - timedelta(hours=10)).strftime(fmt),
             (maintenant - timedelta(hours=6)).strftime(fmt)))

        perimes = [c.sess_id for c in bsi.perimes()]
        verifie("une session longue mais vivante n'est PAS périmée",
                "sess-20260905-0000-longue" in perimes, False)
        verifie("un claim expiré depuis 6 h l'est",
                "sess-20260905-0100-oublie" in perimes, True)
        verifie("un seuil de 8 h épargne celui de 6 h",
                len(bsi.perimes(heures_min=8)), 0)

        verifie("toucher un claim le rend vivant",
                bsi.touche("sess-20260905-0100-oublie"), True)
        verifie("après le touch, il n'est plus périmé",
                len(bsi.perimes()), 0)
        verifie("toucher un claim inexistant rend False",
                bsi.touche("sess-20260906-9999-fantome"), False)


def verrous() -> None:
    print("\nLES VERROUS — un fichier, pas un scope\n")
    with tempfile.TemporaryDirectory(prefix="core-bsi-lock-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "b.db"))
        depot.execute(SCHEMA)
        depot.execute(SCHEMA_LOCKS)
        bsi = BSI(depot)

        v = bsi.prend("agents/vps.md", "sess-a", ttl_min=30)
        verifie("le verrou est pris", v.detenteur, "sess-a")
        verifie("il n'est pas expiré", v.expire, False)
        verifie("il apparaît dans les actifs", len(bsi.verrous()), 1)

        # Le même détenteur peut reprendre — c'est un renouvellement.
        bsi.prend("agents/vps.md", "sess-a")
        verifie("le même détenteur reprend sans conflit", len(bsi.verrous()), 1)

        refuse("un AUTRE détenteur est refusé",
               lambda: bsi.prend("agents/vps.md", "sess-b"), ConflitDeVerrou)

        verifie("relâcher au nom d'un autre est refusé",
                bsi.relache("agents/vps.md", "sess-b"), False)
        verifie("le verrou tient toujours", len(bsi.verrous()), 1)
        verifie("le détenteur le relâche", bsi.relache("agents/vps.md", "sess-a"), True)
        verifie("il a disparu", len(bsi.verrous()), 0)
        verifie("relâcher ce qui n'existe pas rend False",
                bsi.relache("agents/vps.md", "sess-a"), False)

        # ⚠️ Un verrou EXPIRÉ ne doit pas geler un fichier indéfiniment.
        passe = (datetime.now(timezone.utc) - timedelta(minutes=10)
                 ).strftime("%Y-%m-%d %H:%M:%S")
        depot.execute(
            "INSERT INTO locks (filepath, holder, claimed_at, expires_at, ttl_min) "
            "VALUES (%s,%s,%s,%s,5)", ("mort.md", "sess-morte", passe, passe))
        verifie("un verrou expiré ne compte pas parmi les actifs",
                len(bsi.verrous()), 0)
        verifie("mais il est là si on demande tout",
                len(bsi.verrous(actifs_seulement=False)), 1)
        neuf = bsi.prend("mort.md", "sess-c")
        verifie("un verrou expiré est repris par quelqu'un d'autre",
                neuf.detenteur, "sess-c")
        verifie("et il ne reste qu'une ligne",
                len(bsi.verrous(actifs_seulement=False)), 1)


SCHEMA_IDENTITE = SCHEMA.replace("duration_min INTEGER)",
                                 "duration_min INTEGER, agent_session TEXT)")


def identite() -> None:
    print("\nUN CLAIM CONNAÎT SA SESSION —, BRAIN-077\n")
    moi, autre = "claude-session-pilote", "claude-session-learning"

    with tempfile.TemporaryDirectory(prefix="core-bsi-id-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "b.db"))
        depot.execute(SCHEMA_IDENTITE)
        bsi = BSI(depot)
        verifie("la base porte l'identité", bsi.porte_identite, True)

        # ── L'incident du 26/09, tel qu'il s'est produit ─────────────────────
        #
        # Deux sessions sur la même machine. La seconde a réécrit le fichier
        # commun `session-role` ; la première a relu ce fichier pour fermer
        # « son » claim, et a fermé celui de l'autre. Succès affiché.
        bsi.ouvre("sess-20260926-2219-pilote-brain", scope="pilote/brain",
                  type="pilote", zone="kernel", agent_session=moi)
        bsi.ouvre("sess-20260926-2233-omarchy", scope="learning/omarchy",
                  type="learning", agent_session=autre)
        refuse("fermer le claim d'une AUTRE session est refusé (l'incident du 26/09)",
               lambda: bsi.ferme("sess-20260926-2233-omarchy", par=moi),
               ClaimDUneAutreSession)
        verifie("et ce claim-là est toujours ouvert",
                bsi.est_ouvert("sess-20260926-2233-omarchy"), True)

        verifie("chaque session retrouve SON claim",
                [c.sess_id for c in bsi.de_la_session(moi)],
                ["sess-20260926-2219-pilote-brain"])
        verifie("et pas celui de l'autre",
                [c.sess_id for c in bsi.de_la_session(autre)],
                ["sess-20260926-2233-omarchy"])
        verifie("une session inconnue n'en porte aucun",
                bsi.de_la_session("claude-session-fantome"), [])
        verifie("une identité vide ne désigne rien", bsi.de_la_session(""), [])
        verifie("l'identité remonte dans la lecture",
                {c.sess_id: c.agent_session for c in bsi.ouverts()},
                {"sess-20260926-2219-pilote-brain": moi,
                 "sess-20260926-2233-omarchy": autre})

        verifie("une session ferme son propre claim",
                isinstance(bsi.ferme("sess-20260926-2219-pilote-brain", par=moi), int),
                True)

        # Les trois chemins qui doivent rester ouverts — sinon le refus
        # bloquerait les gestes légitimes et apprendrait à le contourner.
        verifie("la levée nommée ferme quand même",
                isinstance(bsi.ferme("sess-20260926-2233-omarchy", par=moi,
                                     meme_si_autre=True), int), True)

        bsi.ouvre("sess-20260926-2300-humain", scope="work/x", type="work",
                  agent_session=autre)
        verifie("sans demandeur (shell humain, cron), la fermeture passe",
                isinstance(bsi.ferme("sess-20260926-2300-humain"), int), True)

        c = bsi.ouvre("sess-20260926-2301-sans-agent", scope="work/y", type="work")
        verifie("un claim ouvert hors agent ne porte pas d'identité",
                c.agent_session, None)
        verifie("et n'importe quelle session peut le fermer",
                isinstance(bsi.ferme("sess-20260926-2301-sans-agent", par=moi), int),
                True)

    # ── Une base qui n'a pas encore la colonne ───────────────────────────────
    #
    # Le laptop en repli SQLite, un fork, la prod avant son ALTER. Le BSI doit
    # s'y comporter comme avant — et le DIRE, pour que l'appelant avertisse.
    with tempfile.TemporaryDirectory(prefix="core-bsi-sans-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "b.db"))
        depot.execute(SCHEMA)
        bsi = BSI(depot)
        verifie("sans la colonne, la base le dit", bsi.porte_identite, False)
        c = bsi.ouvre("sess-20260926-2302-ancien", scope="work/z", type="work",
                      agent_session=moi)
        verifie("le claim s'ouvre quand même", bsi.est_ouvert(c.sess_id), True)
        verifie("et il ne prétend pas porter l'identité jetée", c.agent_session, None)
        verifie("la lecture tient", len(bsi.ouverts()), 1)
        verifie("personne n'y est retrouvé par identité", bsi.de_la_session(moi), [])
        verifie("la fermeture passe comme avant",
                isinstance(bsi.ferme(c.sess_id, par=autre), int), True)

        verifie("une colonne inconnue n'existe pas",
                depot.colonne_existe("claims", "n_existe_pas"), False)
        verifie("une table inconnue non plus",
                depot.colonne_existe("table_fantome", "sess_id"), False)
        verifie("une colonne réelle existe", depot.colonne_existe("claims", "scope"), True)


def rattachement() -> None:
    print("\nUNE SESSION REPARQUÉE REPREND SON CLAIM —\n")
    ancienne, nouvelle, tierce = "da05c924-avant", "5db52755-apres", "claude-autre"

    with tempfile.TemporaryDirectory(prefix="core-bsi-rattache-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "b.db"))
        depot.execute(SCHEMA_IDENTITE)
        bsi = BSI(depot)

        # ── L'incident du 27/09 ─────────────────────────────────────────────
        # Parquée puis reprise, la session porte une identité neuve ; son claim
        # porte l'ancienne, et la fermeture le refuse comme « d'une autre ».
        bsi.ouvre("sess-20260926-2257-pilote-brain", scope="pilote/brain",
                  type="pilote", zone="kernel", agent_session=ancienne)
        bsi.ouvre("sess-20260927-0900-autre", scope="work/x", type="work",
                  agent_session=tierce)
        refuse("avant : sa propre fermeture est refusée (l'incident du 27/09)",
               lambda: bsi.ferme("sess-20260926-2257-pilote-brain", par=nouvelle),
               ClaimDUneAutreSession)

        verifie("le rattachement rend le claim déplacé",
                bsi.rattache([ancienne], nouvelle), ["sess-20260926-2257-pilote-brain"])
        verifie("la session retrouve son claim",
                [c.sess_id for c in bsi.de_la_session(nouvelle)],
                ["sess-20260926-2257-pilote-brain"])
        verifie("l'ancienne identité n'en porte plus", bsi.de_la_session(ancienne), [])
        verifie("le claim d'une TIERCE session n'a pas bougé",
                [c.sess_id for c in bsi.de_la_session(tierce)], ["sess-20260927-0900-autre"])
        verifie("rejoué, il ne déplace plus rien", bsi.rattache([ancienne], nouvelle), [])
        verifie("après : la session ferme son claim",
                isinstance(bsi.ferme("sess-20260926-2257-pilote-brain", par=nouvelle), int), True)

        # Un claim FERMÉ n'est jamais réécrit : c'est de l'historique.
        bsi.ouvre("sess-20260927-1000-ferme", scope="work/y", type="work",
                  agent_session=ancienne)
        bsi.ferme("sess-20260927-1000-ferme", par=ancienne)
        verifie("un claim fermé ne change pas de porteur", bsi.rattache([ancienne], nouvelle), [])
        ligne = depot.query_one("SELECT agent_session FROM claims WHERE sess_id = %s",
                                ("sess-20260927-1000-ferme",))
        verifie("… et garde son identité d'origine", ligne["agent_session"], ancienne)

        verifie("sans ancienne identité, rien", bsi.rattache([], nouvelle), [])
        verifie("sans nouvelle identité, rien", bsi.rattache([ancienne], ""), [])
        verifie("l'identité courante n'est pas une ancienne d'elle-même",
                bsi.rattache([nouvelle], nouvelle), [])

    with tempfile.TemporaryDirectory(prefix="core-bsi-rattache-sans-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "b.db"))
        depot.execute(SCHEMA)
        verifie("une base sans la colonne ne rattache rien",
                BSI(depot).rattache([ancienne], nouvelle), [])


def horloge_utc() -> None:
    print("\nL'HORLOGE DU CORE EST EN UTC — aucune requête n'appelle NOW() —\n")
    # `perimes()` comparait `expires_at` (UTC) à `NOW()` — l'heure LOCALE du
    # serveur sur Dolt : +2 h en été, mesuré le 27/09. Un claim expiré depuis 1 h
    # y passait pour expiré depuis 3 h. Les tests ne pouvaient pas le voir : ils
    # tournent sur SQLite, où `NOW()` se traduit en `datetime('now')`, déjà UTC.
    # D'où ce garde sur le CODE, pas sur un comportement : aucune chaîne du CORE
    # hors docstring ne porte `NOW()`. Par `ast`, pas par regex sur le texte —
    # les docstrings qui racontent l'incident ne comptent pas.
    import ast
    import re
    fautes = []
    for f in sorted((Path(__file__).resolve().parent).glob("*.py")):
        if f.name.startswith("test") or f.name in ("persistance.py", "__init__.py"):
            continue   # persistance.py TRADUIT `NOW()` : c'est son métier de le nommer
        arbre = ast.parse(f.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(arbre)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                        ast.AsyncFunctionDef))
                      and n.body and isinstance(n.body[0], ast.Expr)
                      and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(arbre):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docstrings and re.search(r"\bNOW\(\)", n.value)):
                fautes.append(f"{f.name}:{n.lineno}")
    verifie("aucune requête du CORE n'appelle NOW() — l'horloge est UTC_TIMESTAMP()",
            fautes, [])


def regle_partagee() -> None:
    print("\nLA RÈGLE, SANS BASE — celle que la route HTTP appelle aussi\n")
    verifie("deux identités différentes : une autre session",
            autre_session("claude-a", "claude-b"), True)
    verifie("la même identité : pas une autre", autre_session("claude-a", "claude-a"), False)
    verifie("sans demandeur : jamais une autre", autre_session("claude-a", None), False)
    verifie("claim sans identité : jamais une autre", autre_session(None, "claude-b"), False)
    verifie("identité vide : comme absente", autre_session("", "claude-b"), False)
    verifie("demandeur vide : comme absent", autre_session("claude-a", ""), False)


def main() -> int:
    identifiants()
    projets()
    cycle()
    expiration()
    verrous()
    identite()
    rattachement()
    horloge_utc()
    regle_partagee()
    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(main())
