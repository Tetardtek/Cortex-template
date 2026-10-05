#!/usr/bin/env bash
# brain-distribuable: oui
# bsi-claim.sh — Open/close claims via db.py (backend: sqlite ou dolt selon .env.local)
#
# Usage :
#   bsi-claim.sh open  <sess_id> [--scope X] [--type X] [--zone X] [--mode X] [--story "X"] [--project X]
#   bsi-claim.sh close <sess_id> [--result X] [--energy high|medium|low] [--intention X] [--tags X] [--deliverables X]
#   bsi-claim.sh close-stale          → ferme tous les claims open > TTL (4h par défaut)
#   bsi-claim.sh rattacher            → reprend le claim d une identité remplacée (session reprise)
#   bsi-claim.sh exists <sess_id>     → exit 0 si open, exit 1 sinon
#   bsi-claim.sh init                 → vérifie DB + table claims
#
# Backend : db.py (lit BRAIN_DB_BACKEND depuis .env.local — dolt ou sqlite)
# Garantie : python3 seul — aucun serveur HTTP requis (brain-engine peut être arrêté).
#
# Exit codes :
#   0 = succès
#   1 = argument manquant / erreur usage
#   2 = erreur Python / DB

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CMD="${1:-help}"
shift || true

python3 - "$BRAIN_ROOT" "$CMD" "$@" <<'PYEOF'
import re
import subprocess
import sys
import os
from datetime import datetime, timezone

brain_root = sys.argv[1]
cmd = sys.argv[2] if len(sys.argv) > 2 else "help"
args = sys.argv[3:]

# Add brain-engine to path for db.py import
sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db

MOTEUR = "http://127.0.0.1:%s" % os.getenv("BRAIN_PORT", "7700")


# ── Qui suis-je ? — BRAIN-077, ─────────────────────────────────────
#
# Claude Code donne a chaque session son identifiant, dans l environnement de
# toute commande qu elle lance. `~/.claude/session-role`, lui, est UN fichier
# pour toute la machine : le 26/09, une session l a relu pour fermer « son »
# claim, et a ferme celui d une autre. On ne le relit plus pour savoir qui l on
# est. Absent (shell humain, cron, autre agent) : `None`, et rien ne change.
def session_agent():
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or None


# `--pas-le-mien` est un DRAPEAU, sans valeur : `parse_opts` ne lit que des
# paires, et l aurait ignore en fin de ligne — ou avale l argument suivant.
# On le retire avant.
def retirer_drapeau(liste, drapeau):
    return [a for a in liste if a != drapeau], drapeau in liste


def par_le_moteur(methode, chemin, corps=None, timeout=3):
    """(code, donnees) si le moteur repond ; None s'il ne repond pas.

    Repris de `scripts/file-lock.sh`, ou ce mecanisme est eprouve depuis
   . La distinction est le coeur du repli : `None` veut dire « je n'ai
    pas pu demander », et c'est la SEULE chose qui l'autorise. Un code HTTP —
    meme 409 — veut dire « le moteur a repondu », et sa reponse fait autorite.

    Se rabattre sur une vraie erreur du moteur masquerait un defaut au lieu de
    le montrer.

    Les routes /bsi/ passent en localhost bypass : aucun jeton ici, et rien a
    lire dans MYSECRETS.
    """
    import json as _json
    import urllib.error
    import urllib.request
    donnees = _json.dumps(corps).encode("utf-8") if corps is not None else None
    entetes = {"Content-Type": "application/json"} if donnees else {}
    requete = urllib.request.Request(MOTEUR + chemin, data=donnees,
                                     method=methode, headers=entetes)
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            brut = reponse.read()
            return reponse.status, (_json.loads(brut) if brut else None)
    except urllib.error.HTTPError as exc:
        brut = exc.read()
        try:
            return exc.code, _json.loads(brut) if brut else None
        except Exception:                                  # noqa: BLE001
            return exc.code, None
    except Exception:                                      # noqa: BLE001
        return None                      # injoignable — le repli est legitime


def avertir_repli():
    """Dire ce que le repli ne fait PAS, pas seulement qu'on est degrade.

    « Mode degrade » ne renseigne personne. Ici l'ecriture locale est complete
    — meme mutex, meme validation, meme derivation — mais elle n'engage que
    cette machine, et le Dashboard ne l'apprendra pas.
    """
    print(f"\u26a0\ufe0f  moteur injoignable ({MOTEUR}) — claim ouvert en repli LOCAL.")
    print("    Les claims des autres machines n'ont PAS ete consultes :")
    print("    ce claim n'engage que cette machine.")
    print("    Le Dashboard n'a PAS ete notifie : il ne verra pas la session.")
    # Le cas type : un fork dont le moteur ne survit pas au reboot. Sans ces
    # deux lignes, rien ne disait quoi faire (Cortex-Template#2).
    print("    Le moteur tourne-t-il ?  bash scripts/brain-engine.sh status")
    print("    Aucun service ne le relance au demarrage ?  bash scripts/brain-engine.sh install systemd")


def parse_opts(args):
    """Parse --key value pairs from args."""
    opts = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--") and i + 1 < len(args):
            opts[args[i][2:]] = args[i + 1]
            i += 2
        else:
            i += 1
    return opts

# L'energie de cloture a TROIS niveaux (BRAIN-046) — tranche par l'owner le
# 29/09. Rien ne le verifiait : mesure le meme jour, les claims portaient une
# vingtaine de valeurs (« 5 », « high », « 4 », « haute », « 9 », « energized »,
# « max »...) et aucune serie n'etait comparable. La valeur se normalise ici,
# AVANT la route et avant le repli local : les deux chemins ecrivent la meme.
ENERGIES = {
    "high": "high", "h": "high", "haute": "high", "haut": "high",
    "medium": "medium", "m": "medium", "moyenne": "medium", "moyen": "medium",
    "low": "low", "l": "low", "basse": "low", "bas": "low",
}


def energie(valeur):
    """`high` / `medium` / `low` — ou None si absente ; sinon on refuse (exit 2)."""
    if valeur is None:
        return None
    n = ENERGIES.get(str(valeur).strip().lower())
    if n is None:
        print(f"❌ energie « {valeur} » refusee — trois niveaux : high / medium / low "
              f"(ou h / m / l). Rien n a ete ferme.")
        sys.exit(2)
    return n


def ttl_du_type(type_: str | None) -> int | None:
    """Le `ttl_hours` que le manifeste du type déclare — ou None.

    Le TTL par type est déclaré dans `contexts/session-<type>.yml`, à côté de la
    posture qui le justifie. `open` ne le lisait pas : il prenait `--ttl`, sinon
    4 h — la route du moteur et le repli aussi. Le TTL du type ne dépendait donc
    que de l'appelant, et deux ouvertures prescrites l'oubliaient : des sessions
    `pilote` ouvertes à 4 h au lieu de 12. `--ttl` reste une surcharge.
    Un type sans manifeste (`satellite`…) garde le défaut.
    """
    if not type_ or not re.fullmatch(r"[a-z][a-z-]*", type_):
        return None
    manifeste = os.path.join(brain_root, "contexts", f"session-{type_}.yml")
    try:
        with open(manifeste, encoding="utf-8") as f:
            for ligne in f:
                m = re.match(r"ttl_hours:\s*(\d+)\s*(?:#.*)?$", ligne)
                if m:
                    return int(m.group(1))
    except OSError:
        return None
    return None


# Le type d'un claim ouvert sans `--type` : le lobby des sessions V2
# (BRAIN-044, BRAIN-047), celui que helloWorld prend quand le signal manque.
# C'était `navigate`, un type V1 sans manifeste : le claim gardait 4 h quand
# `explore` en déclare 8.
TYPE_PAR_DEFAUT = "explore"


def opts_d_ouverture(brut: list) -> dict:
    """Les options d'un `open` — le type par défaut, puis le TTL de ce type si
    `--ttl` manque.

    Deux chemins ouvrent un claim, la route du moteur et le repli, et chacun
    relit les arguments : la règle vit ici pour qu'ils reçoivent le même.
    """
    opts = parse_opts(brut)
    opts.setdefault("type", TYPE_PAR_DEFAUT)
    if "ttl" not in opts:
        du_type = ttl_du_type(opts.get("type"))
        if du_type is not None:
            opts["ttl"] = str(du_type)
    return opts


def suffixe_de_machine() -> str | None:
    """Le suffixe que porte un identifiant ouvert sur CETTE machine, ou None.

    Une instance `replica-nomad` écrit sur sa branche de la base du fixe
    (BRAIN-078). Deux sessions ouvertes la même minute, même type, même scope,
    sur les deux machines, auraient la même clé — et la fusion des branches en
    ferait un conflit. Tranché le 29/09 (forme « a ») : sur une
    replica, l'identifiant finit par `.<machine>` — `machine:` de
    brain-compose.local.yml. La prod garde les siens. Un fork n'a pas
    posture-gate-check.sh : il reste master, rien ne change pour lui.
    """
    garde = os.path.join(brain_root, "scripts", "posture-gate-check.sh")
    if not os.path.isfile(garde):
        return None
    p = subprocess.run(["bash", garde, "--posture"], capture_output=True, text=True)
    if p.stdout.strip() != "replica-nomad":
        return None
    machine = None
    try:
        import yaml
        with open(os.path.join(brain_root, "brain-compose.local.yml"), encoding="utf-8") as f:
            machine = (yaml.safe_load(f) or {}).get("machine")
    except (OSError, ImportError):
        pass
    return f".{machine}" if machine else ".replica"


def exiger_le_suffixe(sess_id: str) -> None:
    """Sur une replica, refuser un identifiant sans le suffixe de la machine —
    et donner celui à utiliser. Le script ne l'ajoute PAS lui-même : la session
    ne connaîtrait plus son propre identifiant, et sa fermeture échouerait."""
    suffixe = suffixe_de_machine()
    if suffixe is None or sess_id.endswith(suffixe):
        return
    print(f"\u274c sur cette machine (replica-nomad), l'identifiant porte `{suffixe}` :",
          file=sys.stderr)
    print(f"   bash scripts/bsi-claim.sh open {sess_id}{suffixe} …", file=sys.stderr)
    print("   (BRAIN-078 — la même clé ouverte sur les deux machines ferait un conflit)",
          file=sys.stderr)
    sys.exit(1)


def valider_sess_id(sess_id: str) -> None:
    """Un identifiant de session, ou rien.

    `args[0]` etait pris sans etre regarde : un appel mal analyse enregistrait
    un claim sous le nom de son option. La table en porte deux — `--type` et
    `pilote` — et pour chacun, la session reelle n'a jamais existe sous son nom.
    Le doute refuse plutot que d'ecrire n'importe quoi.
    """
    if re.match(r"^sess-[0-9A-Za-z][\w.-]*$", sess_id):
        return
    print(f"\u274c identifiant de session invalide : {sess_id!r}", file=sys.stderr)
    print("   attendu : sess-<AAAAMMJJ>-<HHMM>-<slug>", file=sys.stderr)
    print("   Un claim ouvert sous le nom d'une option n'appartient a personne.",
          file=sys.stderr)
    sys.exit(1)


def valider_handoff(niveau):
    """Un niveau de handoff declare par le schema, ou rien.

    L enum est lu dans la base et jamais recopie ici : une regle dupliquee
    derive de sa source. Le cout est nul dans le cas nominal — `--handoff` est
    rarement passe, et sans lui on ne lit rien.
    """
    if niveau is None:
        return None
    try:
        col = db.query("SHOW COLUMNS FROM claims LIKE 'handoff_level'")
        valeurs = re.findall(r"'([^']*)'", str(col[0]["Type"])) if col else []
    except Exception:                                      # noqa: BLE001
        valeurs = []
    if not valeurs:
        print("\u26a0\ufe0f  enum handoff_level illisible — valeur acceptee sans controle",
              file=sys.stderr)
        return niveau
    if niveau in valeurs:
        return niveau
    print(f"\u274c niveau de handoff invalide : {niveau!r}", file=sys.stderr)
    print(f"   attendu : {' | '.join(valeurs)}", file=sys.stderr)
    print("   Une valeur hors enum est avalee en chaine vide, sans erreur.",
          file=sys.stderr)
    sys.exit(1)


def deriver_session() -> None:
    """Fait naitre la session avec le claim.

    Rien ne planifie `migrate.py` — ni cron, ni timer, verifie le 05/09. La
    table `sessions` ne se remplissait donc qu'a la main, et le controle
    `registres en base` rougissait a CHAQUE boot, sur un etat parfaitement
    sain. Un controle qui accuse le fonctionnement nominal finit ignore, et ne
    dit plus rien le jour ou il a raison.

    Le close ne touche aucun des trois champs derives — date, type,
    handoff_level — donc deriver a l ouverture suffit.

    On appelle la derivation de `migrate.py` plutot que de recopier son INSERT
    ici : elle porte le `CAST(handoff_level AS CHAR)` sans lequel Dolt ecrit
    l index de l enum au lieu de son litteral. Cette derivation-la a deja coute
    118 `'1'` le 05/09 ; deux ecritures de la meme regle finiraient par
    diverger.
    """
    import contextlib
    import io
    try:
        sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
        import migrate
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon):
            total = migrate.migrate_sessions_backend()
        if not total:
            # Le silence est reserve au succes. `migrate_sessions_backend`
            # attrape ses propres erreurs et les imprime sur stdout, qu on
            # vient de detourner : sans ce re-emetteur, un echec de derivation
            # passerait inapercu — le defaut meme que ce controle traque.
            sortie = tampon.getvalue().strip()
            if sortie:
                print(sortie, file=sys.stderr)
    except Exception as exc:                               # noqa: BLE001
        # Le claim est le point critique : s il est ecrit, la session peut
        # attendre. Mais un echec se plaint.
        print(f"\u26a0\ufe0f  session non derivee ({type(exc).__name__}: {exc})"
              " — `python3 brain-engine/migrate.py` la rattrapera.",
              file=sys.stderr)


def _ouvrir_en_repli(sess_id, opts, now):
    """L'ouverture locale, telle qu'elle etait avant etape 4.

    N'est atteinte QUE si le moteur ne repond pas. Elle garde tout ce que
    la porte gouvernee fait — mutex de scope, validation du handoff,
    extraction du projet, derivation de la session — mais elle ne voit que
    cette machine.
    """
    if not args:
        print("❌ Usage: bsi-claim.sh open <sess_id> [--scope X] [--type X] ...", file=sys.stderr)
        sys.exit(1)

    sess_id = args[0]
    valider_sess_id(sess_id)
    opts = opts_d_ouverture(args[1:])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Vérifier si déjà open
    existing = db.query(
        "SELECT status FROM claims WHERE sess_id = %s", (sess_id,)
    )
    if existing and existing[0].get("status") == "open":
        print(f"⚠️  Claim déjà ouvert : {sess_id}")
        sys.exit(0)

    new_scope = opts.get("scope", "brain/")

    # Scope overlap detection — BSI mutex. Le réseau, pas cette base seule :
    # les claims que chaque machine satellite a ouverts sur sa branche comptent
    # aussi (BRAIN-078) — la même source que le verrou du moteur.
    open_claims = db.claims_du_reseau("status = 'open'", colonnes="sess_id, scope, zone")

    for oc in open_claims:
        oc_scope = oc.get("scope") or ""
        if (new_scope.startswith(oc_scope) or oc_scope.startswith(new_scope)
                or new_scope == oc_scope):
            oc_zone = oc.get("zone") or "project"

            # Zone kernel = hard block
            if oc_zone == "kernel" or opts.get("zone") == "kernel":
                print(f"🔴 SCOPE CONFLICT — zone kernel verrouillée")
                print(f"   Existant : {oc['sess_id']} → scope: {oc_scope} (zone: {oc_zone})")
                print(f"   Demandé  : {sess_id} → scope: {new_scope}")
                print(f"   → Fermer le claim existant d'abord : bsi-claim.sh close {oc['sess_id']}")
                sys.exit(1)

            # Zone project = soft warning
            print(f"⚠️  SCOPE OVERLAP détecté")
            print(f"   Existant : {oc['sess_id']} → scope: {oc_scope}")
            print(f"   Demandé  : {sess_id} → scope: {new_scope}")
            print(f"   → Parallélisme autorisé — attention aux conflits d'écriture")

    claim_type = opts["type"]
    zone = opts.get("zone", "project")
    mode = opts.get("mode")
    story = opts.get("story")
    # `"0"` n existe dans aucun des deux mondes. `metabolism-spec.md` declare
    # l enum `NO | SEMI | SEMI+ | FULL`, et `todo-context.md` dit le champ
    # OPTIONNEL — « omettre si = defaut manifest ». La valeur par defaut ecrite
    # ici etait donc hors domaine : MySQL comme Dolt avalent une valeur d enum
    # invalide en chaine vide, sans rien dire. Mesure le 05/09 sur le claim de
    # boot — la seule ligne `''` de la table, face a 54 `NULL`.
    #
    # Ce n est pas la question de niveau 3, qui porte sur le sort des
    # lignes DEJA en base. C est la source qui en fabriquait de nouvelles.
    handoff = valider_handoff(opts.get("handoff"))
    instance = opts.get("instance")

    # Project — explicit or auto-extract from scope (BRAIN-046 + BRAIN-047)
    # Sessions V2: scope convention = "<type>/<project>[/detail]" or "<project>/<detail>"
    # Only auto-extract if scope starts with a known session type prefix
    project = opts.get("project")
    if not project and "/" in new_scope:
        parts = new_scope.split("/")
        known_prefixes = ("work", "brain", "explore", "pilote", "chill",
                          "brainstorm", "debug", "deploy", "infra")  # V2 + legacy
        if parts[0] in known_prefixes and len(parts) > 1:
            # "work/mon-projet" → "mon-projet", "brain/agents" → "brain" (scope = brain itself)
            candidate = parts[1].strip()
            if candidate and len(candidate) < 30:  # sanity check — no free-text scope
                project = candidate
        elif parts[0] not in known_prefixes and " " not in parts[0] and len(parts[0]) < 20:
            # "mon-projet/frontend" → "mon-projet" (project-first scope)
            project = parts[0].strip()

    # Calculate expires_at (4h from now)
    from datetime import timedelta
    # 🔴 Le TTL alimente DEUX choses : la colonne `ttl_hours` et le calcul de
    # `expires_at`. Elles etaient toutes deux a `4` en dur, chacune de son cote
    # — deux valeurs qui doivent rester d accord et que rien ne reliait.
    # `close-stale` lit `expires_at` et retombe sur `opened_at + ttl_hours` :
    # les voir diverger aurait donne deux verdicts selon le chemin emprunte.
    # Une seule source desormais.
    try:
        ttl_h = int(opts.get("ttl", 4))
    except ValueError:
        print(f"\u274c --ttl attend un entier, recu : {opts.get('ttl')}", file=sys.stderr)
        sys.exit(1)
    expires = (datetime.now(timezone.utc)
               + timedelta(hours=ttl_h)).strftime("%Y-%m-%d %H:%M:%S")

    # L identite, si la base locale la porte — BRAIN-077. Ecrite DANS le meme
    # REPLACE, comme la route : une ouverture, une ecriture, un commit. Le repli
    # du laptop tourne sur un SQLite qui peut ne pas avoir la colonne.
    identite = "non transmise"
    agent = session_agent()
    if agent:
        from core.bsi import BSI
        if BSI(db.depot()).porte_identite:
            identite = "enregistree"
        else:
            identite, agent = "base locale sans colonne agent_session", None
    col_identite = ", agent_session" if agent else ""
    val_identite = ", %s" if agent else ""

    db.execute(f"""
        REPLACE INTO claims
            (sess_id, type, scope, status, opened_at, zone, mode, story_angle,
             handoff_level, instance, ttl_hours, expires_at, project{col_identite})
        VALUES (%s, %s, %s, 'open', %s, %s, %s, %s, %s, %s, %s, %s, %s{val_identite})
    """, (sess_id, claim_type, new_scope, now, zone, mode, story, handoff, instance,
          ttl_h, expires, project) + ((agent,) if agent else ()),
        commit_msg=f"bsi: claim ouvert {sess_id} ({new_scope})", tables=["claims"])

    deriver_session()

    proj_info = f" (project: {project})" if project else ""
    print(f"✅ Claim ouvert : {sess_id}{proj_info}")
    dire_identite(identite)


def cmd_open():
    """Ouvre un claim PAR LE MOTEUR, avec repli local annonce — etape 4.

    Jusqu'au 11/09, ce script et `POST /bsi/claims` ecrivaient tous deux dans
    `claims`, et **pas la meme chose** : le script portait le mutex, la
    validation du handoff et l'extraction du projet ; la route n'avait rien.
    Deux portes sur une table, deux comportements — et la regle BSI existait en
    double, donc elle derivait.

    La route porte desormais la regle du CORE (`core.bsi`) et les trois choses
    qui manquaient. Prouve AVANT de basculer, les deux portes jouees cote a cote
    sans toucher la base : 13 colonnes ecrites par le script, 17 par la route,
    **aucune perdue**, aucune valeur divergente, session derivee des deux cotes,
    handoff hors enum et conflit de scope refuses des deux cotes.

        2xx           acquis
        409           refuse — la reponse du moteur fait autorite
        autre code    erreur, exit 2 : on ne se rabat PAS sur une vraie erreur
        injoignable   repli local, AVEC l'avertissement qui dit ce qui manque

    Se rabattre sur une erreur du moteur masquerait un defaut au lieu de le
    montrer. Seule l'ABSENCE de reponse autorise le repli.
    """
    if not args:
        print("\u274c Usage: bsi-claim.sh open <sess_id> [--scope X] [--type X] ...",
              file=sys.stderr)
        sys.exit(1)

    sess_id = args[0]
    valider_sess_id(sess_id)
    exiger_le_suffixe(sess_id)
    opts = opts_d_ouverture(args[1:])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # `handoff_level` n'est PAS valide ici : la route le fait, en lisant l'enum
    # dans le schema. Le valider aussi avant l'appel remettrait la regle en
    # double — ce que cette bascule vient precisement de supprimer. Le repli,
    # lui, la porte, parce qu'il ecrit sans la route.
    corps = {
        "sess_id":       sess_id,
        "scope":         opts.get("scope", "brain/"),
        "type":          opts["type"],
        "zone":          opts.get("zone", "project"),
        "mode":          opts.get("mode"),
        "story_angle":   opts.get("story"),
        "handoff_level": opts.get("handoff"),
        "instance":      opts.get("instance"),
        "opened_at":     now,
    }
    # `--ttl` : la duree de vie du claim, en heures.
    #
    # La colonne `ttl_hours` existe depuis toujours et RIEN ne l alimentait :
    # 598 claims sur 599 etaient a 4 h, alors qu une session `pilote` dure
    # 11,8 h en moyenne — 16 sur 27 depassaient leur TTL.
    #
    # La valeur vient du MANIFEST du type de session, pas d ici : c est
    # `contexts/session-<type>.yml` qui declare combien de temps sa posture
    # dure, a cote de la posture elle-meme. Le script ne fait que transmettre.
    #
    # ⚠️ Le TTL n est PAS une limite de travail : `touch` le repousse a chaque
    # commit. C est la duree au bout de laquelle une session SANS SIGNE DE VIE
    # devient suspecte. Un TTL plus long pour `pilote` ne rend pas la session
    # eternelle — il reconnait qu on y reflechit plus longtemps entre deux
    # commits.
    ttl = opts.get("ttl")
    if ttl is not None:
        try:
            corps["ttl_hours"] = int(ttl)
        except ValueError:
            print(f"\u274c --ttl attend un entier, recu : {ttl}", file=sys.stderr)
            sys.exit(1)
    # `project` n'est envoye QUE s'il est explicite : sinon la route l'extrait
    # elle-meme, par la regle du CORE. L'envoyer vide ferait croire a un choix.
    if opts.get("project"):
        corps["project"] = opts["project"]
    if session_agent():
        corps["agent_session"] = session_agent()

    reponse = par_le_moteur("POST", "/bsi/claims", corps)

    if reponse is None:
        avertir_repli()
        _ouvrir_en_repli(sess_id, opts, now)
        return

    code, donnees = reponse
    donnees = donnees or {}
    motif = str(donnees.get("detail", "")) or "(sans motif)"

    if code == 409:
        print(f"\U0001f534 SCOPE CONFLICT — {motif}", file=sys.stderr)
        sys.exit(1)
    if code == 422:
        print(f"\u274c refuse par le moteur — {motif}", file=sys.stderr)
        sys.exit(1)
    if not (200 <= code < 300):
        print(f"\u274c le moteur a repondu {code} — {motif}", file=sys.stderr)
        print("   Ce n'est pas une absence de reponse : on ne se rabat pas dessus.",
              file=sys.stderr)
        sys.exit(2)

    # Ce qui se chevauche sans bloquer. Le script l'affichait deja ; la route ne
    # le DISAIT pas avant le 11/09, et basculer l'aurait fait disparaitre.
    for autre in donnees.get("overlap") or []:
        print("\u26a0\ufe0f  SCOPE OVERLAP detecte")
        print(f"   Existant : {autre.get('sess_id')} \u2192 scope: {autre.get('scope')}")
        print(f"   Demande  : {sess_id} \u2192 scope: {corps['scope']}")
        print("   \u2192 Parallelisme autorise — attention aux conflits d'ecriture")

    projet = donnees.get("project")
    proj_info = f" (project: {projet})" if projet else ""
    print(f"\u2705 Claim ouvert : {sess_id}{proj_info}")
    dire_identite(donnees.get("identite"))


def dire_identite(identite):
    """Ce que la base a fait de l identite — la taire serait mentir. BRAIN-077

    Une identite transmise puis jetee ressemble a une identite enregistree ;
    la fermeture sans argument croirait pouvoir s y fier. On se tait seulement
    quand il n y avait rien a transmettre (shell humain, cron).
    """
    if not session_agent() or identite == "enregistree":
        return
    if identite is None:
        raison = "le moteur ne dit pas ce qu il en a fait (version anterieure a BRAIN-077 ?)"
    else:
        raison = identite
    print(f"\u26a0\ufe0f  identite de session NON enregistree — {raison}")
    print("   Fermer ce claim en le nommant : bsi-claim.sh close <sess_id>")


def avertir_repli_close():
    """Dire ce que le repli de FERMETURE ne fait pas.

    Ce n est pas la meme perte qu a l ouverture, et « mode degrade » ne
    renseignerait personne. A l ouverture, le repli ne consulte pas les autres
    machines — il peut donc accorder un scope deja tenu. A la fermeture, il
    ecrit tout ce qu il faut, mais le Dashboard ne l apprend pas : il continue
    d afficher une session qui n existe plus.
    """
    # Dit AVANT la tentative, donc seulement ce qui est deja vrai. « Ferme
    # COMPLETEMENT » s'affichait ici — y compris quand la base refusait
    # l'ecriture, que le claim etait introuvable ou a une autre session.
    # Mesure le 27/09 : le refus et « ferme completement » dans le meme passage.
    # Le bilan se dit apres une ecriture reussie.
    print(f"\u26a0\ufe0f  moteur injoignable ({MOTEUR}) — fermeture en repli LOCAL.")


def _fermer_en_repli(sess_id, now, result,
                     energy, intention, tags, deliverables, pas_le_mien=False):
    """La fermeture locale, telle qu elle etait avant etape 5.

    N est atteinte QUE si le moteur ne repond pas. Elle ecrit les HUIT champs
    — c est le point : un repli qui ecrirait moins serait la perte silencieuse
    que cette bascule existe pour eviter.

    C est ELLE qui lit `opened_at`, et plus `cmd_close`. La lecture a suivi
    l ecriture : ce chemin ecrit en local, donc il lit en local. Le chemin
    gouverne, lui, ne lit rien — le moteur trouve le claim ou rend 404.

    `AND status = 'open'` est garde tel quel : il porte ici le refus que la
    route exprime par un 409. Les deux chemins refusent la meme chose, chacun
    dans sa grammaire.
    """
    from core.bsi import BSI, autre_session
    porte = BSI(db.depot()).porte_identite
    existant = db.query(
        "SELECT sess_id, opened_at" + (", agent_session" if porte else "")
        + " FROM claims WHERE sess_id = %s AND status = 'open'",
        (sess_id,))
    if not existant:
        print(f"\u26a0\ufe0f  Claim non trouve ou deja ferme : {sess_id}")
        return
    # La meme regle que la route, par la meme fonction du CORE — BRAIN-077.
    sienne = existant[0].get("agent_session")
    if autre_session(sienne, session_agent()) and not pas_le_mien:
        print(f"\U0001f534 {sess_id} appartient a une autre session d agent "
              f"({sienne}) — levee : --pas-le-mien", file=sys.stderr)
        sys.exit(1)

    # La duree — la metrique de BRAIN-046. Le backend rend un objet `datetime`,
    # pas une chaine : `strptime` levait `TypeError`, qu un `except: pass`
    # avalait. Mesure du 22/08 : 43 claims fermes, 43 sans duree, et rien ne le
    # disait. On accepte les deux formes, et un echec se plaint.
    duration_min = None
    opened_at = existant[0].get("opened_at")
    if opened_at:
        try:
            if isinstance(opened_at, datetime):
                ouvert = opened_at
            else:
                ouvert = datetime.strptime(str(opened_at)[:19], "%Y-%m-%d %H:%M:%S")
            if ouvert.tzinfo is None:                # stocke en UTC, sous-entendu
                ouvert = ouvert.replace(tzinfo=timezone.utc)
            duration_min = max(
                1, int((datetime.now(timezone.utc) - ouvert).total_seconds() / 60))
        except (ValueError, TypeError) as err:
            print(f"\u26a0\ufe0f  duree non calculee ({type(err).__name__}: {err})",
                  file=sys.stderr)

    # Le refus de la base se dit, comme sur la route (`PATCH /bsi/claims`) :
    # le repli laissait remonter une trace brute qui RECOPIAIT la valeur
    # refusee — `result` porte ce qu'une session a produit, et la route le
    # masque depuis le 26/09. Mesure le 27/09 sur une branche Dolt jetable :
    # 100 caracteres dans un `varchar(64)`, la valeur en clair, le claim
    # reste ouvert sans un mot.
    try:
        db.execute("""
            UPDATE claims
            SET status = 'closed', closed_at = %s, result = %s,
                duration_min = %s, energy = %s, intention = %s, tags = %s, deliverables = %s
            WHERE sess_id = %s AND status = 'open'
        """, (now, result, duration_min, energy, intention, tags, deliverables, sess_id),
            commit_msg=f"bsi: claim ferme {sess_id}" + (f" ({result})" if result else ""),
            tables=["claims"])
    except Exception as exc:                                    # noqa: BLE001
        champs = {"result": result, "energy": energy, "intention": intention,
                  "tags": tags, "deliverables": deliverables}
        tailles = {k: len(v) for k, v in champs.items() if isinstance(v, str)}
        motif = re.sub(r"'[^']{32,}'",
                       lambda m: f"'<valeur masquee : {len(m.group(0)) - 2} caracteres>'",
                       str(exc))
        print(f"\u274c ecriture refusee par la base : {motif}", file=sys.stderr)
        print(f"   Longueurs envoyees : {tailles}. Le claim {sess_id} est reste OUVERT.",
              file=sys.stderr)
        if len(result or "") > 64:
            print("   `result` est une etiquette (varchar 64) : la prose va dans "
                  "--deliverables, qui est un `text`.", file=sys.stderr)
        sys.exit(1)

    dur_info = f" / {duration_min}min" if duration_min else ""
    nrg_info = f" / {energy}" if energy else ""
    print(f"\u2705 Claim ferme (LOCAL) : {sess_id}{dur_info}{nrg_info}")
    print("    Ferme COMPLETEMENT sur cette machine : les huit champs sont ecrits,")
    print("    la duree comprise. Le Dashboard n'a PAS ete notifie : il montrera")
    print("    la session ouverte jusqu'a son prochain chargement.")


def mon_claim():
    """Le claim ouvert de CETTE session, retrouve par son identite. BRAIN-077

    Refuse plutot que de deviner : sans identite, sans colonne, sans claim, ou
    avec plusieurs claims, il le dit et sort. Deviner, c est ce qui a ferme le
    claim d une autre session le 26/09.
    """
    agent = session_agent()
    if not agent:
        print("❌ close sans identifiant : aucune identite de session dans "
              "l environnement (shell humain ?) — nommer le claim : "
              "bsi-claim.sh close <sess_id>", file=sys.stderr)
        sys.exit(1)
    from core.bsi import BSI
    bsi = BSI(db.depot())
    if not bsi.porte_identite:
        print("❌ close sans identifiant : la base n a pas la colonne "
              "agent_session (BRAIN-077) — nommer le claim", file=sys.stderr)
        sys.exit(1)
    miens = bsi.de_la_session(agent)
    if len(miens) == 1:
        return miens[0].sess_id
    if not miens:
        print("❌ aucun claim ouvert ne porte cette session — deja ferme, ou "
              "ouvert sans identite. Nommer le claim.", file=sys.stderr)
    else:
        print(f"❌ cette session porte {len(miens)} claims ouverts — nommer "
              "celui a fermer :", file=sys.stderr)
        for c in miens:
            print(f"   {c.sess_id}  ({c.scope})", file=sys.stderr)
    sys.exit(1)


def cmd_close():
    global args
    args, pas_le_mien = retirer_drapeau(args, "--pas-le-mien")
    # Sans identifiant, ou avec une option en tete : c est MON claim.
    if not args or args[0].startswith("--"):
        args = [mon_claim()] + args

    sess_id = args[0]
    valider_sess_id(sess_id)
    opts = parse_opts(args[1:])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    result = opts.get("result", "success")

    # 🔴 AUCUNE lecture locale ici — c est la seconde moitie de la bascule.
    #
    # Le premier jet gardait le `SELECT opened_at` d avant, pour calculer la
    # duree et pour sortir tot sur un claim introuvable. Ca laissait `close` a
    # moitie bascule : il LISAIT en local et ECRIVAIT par la route, et son
    # « Claim non trouve » sortait AVANT l appel — donc le 404 du moteur
    # n etait jamais atteint. Une porte qui juge sur sa propre lecture n a pas
    # delegue, elle a double.
    #
    # Le moteur decide desormais des deux : il trouve le claim, ou rend 404 ;
    # il calcule `duration_min`, ou dit pourquoi il n a pas pu. `cmd_open` ne
    # lit rien non plus — les deux moities de la paire ont la meme forme.
    #
    # La lecture n a pas disparu : elle a suivi l ecriture. `_fermer_en_repli`
    # la fait, parce que c est LUI qui ecrit en local. Sans elle, le repli
    # perdrait la duree — exactement la perte silencieuse que cette bascule
    # existe pour eviter.

    # Enrichment fields (BRAIN-046)
    energy = energie(opts.get("energy"))  # high/medium/low — normalisee, ou refus
    intention = opts.get("intention")    # ce que la session visait, en texte libre — plus un lien : la table `intentions` est retirée le 4/10
    tags = opts.get("tags")              # comma-separated
    deliverables = opts.get("deliverables")  # texte libre

    # ── La fermeture passe par le moteur — etape 5 ─────────────────
    #
    # `cmd_open` y est passe le 11/09 ; `close` fermait encore en local, et
    # L'owner l a releve le 12/09 : « si on a fait l open, on devra faire le
    # close aussi ». Une machine qui ouvre par le moteur et ferme en local
    # laisse le Dashboard croire la session vivante.
    #
    # Prouve AVANT de basculer, au seul moment ou c etait possible
    # (`workspace/scratch/banc-bsi-claim/equivalence_close.py`) : 8 colonnes
    # des deux cotes, aucune perdue, aucune valeur divergente. Le banc a
    # trouve deux defauts au passage — la duree non calculee cote route, et un
    # claim DEJA FERME qui rendait 200 en ecrasant son `closed_at`. Les deux
    # sont corriges cote moteur avant cette bascule.
    #
    # Meme grammaire de reponse que `cmd_open`, et pour la meme raison :
    #
    #     2xx           ferme
    #     404           claim introuvable — la reponse du moteur fait autorite
    #     409           deja ferme : une fermeture ne se rejoue pas
    #     autre code    erreur, exit 2 : on ne se rabat PAS sur une vraie erreur
    #     injoignable   repli local, AVEC l avertissement qui dit ce qui manque
    # `duration_min` n est PAS envoye : la route la calcule depuis l `opened_at`
    # qu elle lit elle-meme. L envoyer supposerait de l avoir lu ici, et c est
    # precisement ce qu on vient de retirer.
    corps = {
        "status":       "closed",
        "closed_at":    now,
        "result":       result,
        "energy":       energy,
        "intention":    intention,
        "tags":         tags,
        "deliverables": deliverables,
    }
    # Les champs absents ne sont pas envoyes : la route n ecrit que ce qu elle
    # recoit, et envoyer `None` ecraserait une valeur posee par ailleurs.
    # `duration_min` fait exception — la route la recalcule si elle manque,
    # mais on envoie la notre quand on l a, pour que les deux chemins
    # s accordent sur la meme origine de temps.
    corps = {k: v for k, v in corps.items() if v is not None}
    # Qui demande, et la levee nommee — la route refuse (409) de fermer le
    # claim d une AUTRE session vivante. BRAIN-077
    if session_agent():
        corps["par"] = session_agent()
    if pas_le_mien:
        corps["meme_si_autre"] = True

    reponse = par_le_moteur("PATCH", f"/bsi/claims/{sess_id}", corps)

    if reponse is None:
        avertir_repli_close()
        _fermer_en_repli(sess_id, now, result,
                         energy, intention, tags, deliverables, pas_le_mien)
        return

    code, donnees = reponse
    motif = str((donnees or {}).get("detail", "")) or "(sans motif)"

    if code == 404:
        print(f"⚠️  Claim non trouvé : {sess_id}")
        return
    if code == 409:
        print(f"⚠️  {motif}", file=sys.stderr)
        sys.exit(1)
    if not (200 <= code < 300):
        print(f"❌ le moteur a repondu {code} — {motif}", file=sys.stderr)
        print("   Ce n'est pas une absence de reponse : on ne se rabat pas dessus.",
              file=sys.stderr)
        sys.exit(2)

    # La duree vient de la REPONSE : le script ne la calcule plus, et ne la
    # relit pas pour l afficher. Si le moteur ne la rapporte pas — vieille
    # version, ou calcul impossible — on n invente rien, on se tait.
    duree = (donnees or {}).get("duration_min")
    dur_info = f" / {duree}min" if duree else ""
    nrg_info = f" / {energy}" if energy else ""
    print(f"✅ Claim fermé : {sess_id}{dur_info}{nrg_info}")

def _fermer_stale_en_repli(seuil_sql, seuil_params, seuil_txt):
    """La fermeture en masse locale, telle qu elle etait avant etape 5.

    Elle garde la correction de : l UPDATE ferme EXACTEMENT ce que le
    SELECT a liste, par `sess_id`. Les deux chemins — moteur et repli —
    appliquent donc la meme regle, et aucun des deux ne rejoue un critere.
    """
    stale = db.query(f"""
        SELECT sess_id, TIMESTAMPDIFF(MINUTE, opened_at, UTC_TIMESTAMP()) AS age_min
        FROM claims
        WHERE status = 'open'
          AND TIMESTAMPDIFF(HOUR,
                COALESCE(expires_at,
                         DATE_ADD(opened_at, INTERVAL COALESCE(ttl_hours,4) HOUR)),
                UTC_TIMESTAMP()) > {seuil_sql}
    """, seuil_params)

    if not stale:
        print(f"\u2139\ufe0f  Aucun claim stale ({seuil_txt})")
        return

    ids = [c["sess_id"] for c in stale]
    trous = ", ".join(["%s"] * len(ids))
    ferme = db.execute(f"""
        UPDATE claims
        SET status = 'closed',
            closed_at = UTC_TIMESTAMP(),
            result = 'stale-auto-closed',
            duration_min = TIMESTAMPDIFF(MINUTE, opened_at, UTC_TIMESTAMP())
        WHERE status = 'open' AND sess_id IN ({trous})
    """, tuple(ids),
        commit_msg=f"bsi: {len(ids)} claim(s) stale ferme(s) automatiquement",
        tables=["claims"])

    # Entre le SELECT et l UPDATE, une autre session a pu fermer un claim
    # proprement. On ne le rouvre pas en `stale-auto-closed` — le
    # `status = 'open'` du WHERE s en charge — mais l ecart se dit.
    #
    # ⚠️ Inactif en dolt : `db.execute` y rend -1, donc `ferme >= 0` est faux.
    # Il ne sert qu en sqlite — le repli d un fork, et le template.
    #
    # 🔴 Il avait DISPARU en deplacant ce code vers le repli, et c est la
    # relecture du diff qui l a rattrape. Un garde-fou qui s evapore dans un
    # refactoring ne laisse aucune trace : personne ne cherche ce qui ne rougit
    # plus.
    if ferme is not None and ferme >= 0 and ferme != len(ids):
        print(f"\u26a0\ufe0f  {len(ids)} claim(s) liste(s), {ferme} ferme(s) — "
              f"un claim a change d etat entre les deux requetes", file=sys.stderr)

    for c in stale:
        print(f"   \u2022 {c['sess_id']} ({c.get('age_min')} min)")
    print(f"\u2705 {len(ids)} claim(s) stale ferme(s) (LOCAL, {seuil_txt})")


def cmd_close_stale():
    """Ferme les claims restes ouverts au-dela de leur TTL.

    Deux corrections du 22/08, mesurees sur la base et non supposees :

    1. NOW() rendait l heure LOCALE alors que opened_at est ecrit en UTC par
       cmd_open. L age etait donc surestime du decalage du fuseau — 2 h en
       CEST. Une session de 2 h 01 etait declaree stale sous un TTL de 4 h,
       et le claim se fermait sous les pieds de qui travaillait dedans.
       UTC_TIMESTAMP() compare desormais deux dates du meme referentiel.

    2. duration_min n etait pas renseigne ici non plus.

    --min-hours releve le seuil sans toucher au ttl_hours de chaque claim :
    l appel manuel garde le TTL nominal, l appel automatise ne ferme que ce
    qui est certainement un oubli. Une session longue n est pas un oubli.
    """
    opts = parse_opts(args)
    min_hours = opts.get("min-hours")

    if min_hours is not None:
        try:
            min_hours = int(min_hours)
        except ValueError:
            print(f"\u274c --min-hours attend un entier, recu : {min_hours}", file=sys.stderr)
            sys.exit(1)
        seuil_sql = "%s"
        seuil_params = (min_hours,)
        seuil_txt = f"expire depuis > {min_hours}h"
    else:
        seuil_sql = "COALESCE(ttl_hours, 4)"
        seuil_params = ()
        seuil_txt = "expire depuis > TTL du claim"

    # ── Par le moteur — etape 5 ────────────────────────────────
    #
    # Une route dediee, et non une boucle de PATCH cote appelant : le critere
    # — qu est-ce qu un claim oublie ? — est une regle du BSI, pas une affaire
    # de client. Deux clients qui la porteraient finiraient par ne pas fermer
    # les memes claims. C est aussi ce qui permet a la correction de
    # de vivre a UN seul endroit.
    #
    # Ce chemin tourne une fois par jour (timer 06:00) : le cout HTTP n a
    # aucune importance ici, contrairement a `touch`.
    corps = {"min_hours": min_hours} if min_hours is not None else {}
    reponse = par_le_moteur("POST", "/bsi/claims/close-stale", corps, timeout=10)

    if reponse is None:
        print(f"\u26a0\ufe0f  moteur injoignable ({MOTEUR}) — close-stale en repli LOCAL.")
        print("    Les claims sont fermes sur cette machine ; le Dashboard n a")
        print("    PAS ete notifie, et les claims des autres machines ne sont")
        print("    pas concernes — ce repli ne voit que cette base.")
        _fermer_stale_en_repli(seuil_sql, seuil_params, seuil_txt)
        return

    code, donnees = reponse
    if not (200 <= code < 300):
        motif = str((donnees or {}).get("detail", "")) or "(sans motif)"
        print(f"\u274c le moteur a repondu {code} — {motif}", file=sys.stderr)
        sys.exit(2)

    fermes = (donnees or {}).get("fermes") or []
    seuil = (donnees or {}).get("seuil", seuil_txt)
    if not fermes:
        print(f"\u2139\ufe0f  Aucun claim stale ({seuil})")
        return
    for c in fermes:
        print(f"   \u2022 {c.get('sess_id')} ({c.get('age_min')} min)")
    print(f"\u2705 {len(fermes)} claim(s) stale ferm\u00e9(s) ({seuil})")

def _toucher_en_repli(where, params, quiet):
    """Le touch local, tel qu il etait avant etape 5.

    N est atteint QUE si le moteur ne repond pas. Il ecrit la meme chose, avec
    la meme horloge serveur (`UTC_TIMESTAMP()`), et sans commit Dolt — le
    working set est partage et durable.
    """
    ouverts = db.query(f"SELECT sess_id, ttl_hours FROM claims WHERE {where}", params)
    if not ouverts:
        if not quiet:
            print("\u2139\ufe0f  Aucun claim ouvert a prolonger")
        return
    db.execute(
        f"UPDATE claims SET expires_at = DATE_ADD(UTC_TIMESTAMP(), "
        f"INTERVAL COALESCE(ttl_hours, 4) HOUR) WHERE {where}", params)
    if not quiet:
        for c in ouverts:
            print(f"\u2705 {c['sess_id']} \u2014 expiration repoussee de "
                  f"{c['ttl_hours'] or 4} h (LOCAL)")


def cmd_touch():
    """Repousse l expiration des claims ouverts : la session est vivante.

    Le probleme, mesure le 04/09 en auditant le BSI. Sur 52 claims fermes,
    DIX portent le resultat `stale-auto-closed` — et les dix sont de type
    `pilote`, de 9,6 h a 76,8 h. Aucune session courte oubliee dans le lot.
    Or `pilote` est defini comme « long, multi-scope » ; l'owner confirme qu une
    session dure parfois plusieurs jours, compactages compris. Le mecanisme ne
    fermait donc pas des oublis : il fermait des sessions VIVANTES, et ecrasait
    leur vrai resultat par « stale-auto-closed ».

    La cause tient en une ligne : rien ne distinguait une session vivante d une
    session abandonnee. `close-stale` mesurait l age depuis `opened_at`, ce qui
    ne peut que grandir. Et `claims.expires_at` etait ecrit a l ouverture et
    JAMAIS lu — un champ mort qui portait deja la bonne idee.

    Ce `touch` lui donne son role : il repousse `expires_at` de `ttl_hours`.
    Appele par le hook git post-commit, il fait d un commit un signe de vie.
    Une session qui travaille reste ouverte ; une session abandonnee cesse de
    commiter, et expire.

    SANS commit Dolt : le working set est partage et durable, la valeur est
    donc visible des autres processus tout de suite. Un commit par `touch`
    ajouterait 3,7 Ko a chaque commit git, pour un compteur.
    """
    opts = parse_opts(args)
    quiet = "quiet" in opts or (args and args[0] == "--quiet")
    cible = args[0] if args and not args[0].startswith("-") else None

    # Un signe de vie ne vaut que pour celui qui le donne. Sans cible, ce sont
    # les claims de CETTE session (BRAIN-077) ; sans identite (shell humain,
    # cron), rien — on ne sait pas qui vit. Jusqu au 27/09, « sans cible »
    # repoussait TOUS les claims ouverts : une session morte n expirait jamais
    # tant qu une autre commitait.
    where = "status = 'open'"
    params = ()
    agent = None
    if cible:
        where += " AND sess_id = %s"
        params = (cible,)
    else:
        agent = session_agent()
        if not agent:
            if not quiet:
                print("\u2139\ufe0f  touch sans cible et sans identite de session : rien "
                      "n est repousse — nommer le claim : bsi-claim.sh touch <sess_id>")
            return
        where += " AND agent_session = %s"
        params = (agent,)

    # ── Par le moteur — etape 5 ────────────────────────────────
    #
    # `touch` ne dit pas « ecris cette date », il dit « je suis vivant ». Le
    # calcul de la nouvelle expiration tient a `ttl_hours`, une regle du claim
    # que l appelant n a pas a connaitre — d ou une route dediee plutot qu un
    # champ de plus sur PATCH.
    #
    # ⏱️ Le cout a ete MESURE avant de basculer, parce que ce chemin est celui
    # du hook `post-commit` — 201 commits en 7 jours, et il s execute PENDANT
    # le `git commit` :
    #
    #     moteur qui repond   0,008 s
    #     moteur ARRETE       0,020 s   <- refus immediat sur loopback
    #     une ip qui pend     3,003 s   <- n arrive pas sur 127.0.0.1
    #
    # Le hook coute deja 0,08 s : l ajout est sous le bruit. La crainte d un
    # timeout de 3 s par commit etait fondee en theorie et fausse ici — un
    # port ferme en local REFUSE, il ne fait pas attendre.
    #
    # `timeout=1` quand meme, et c est le seul cas ou l on s ecarte du defaut :
    # un moteur vivant mais BLOQUE ferait patienter le commit. Une seconde
    # suffit sur loopback, et le repli local est complet.
    corps = {"sess_id": cible} if cible else {"agent_session": agent}
    reponse = par_le_moteur("POST", "/bsi/claims/touch", corps, timeout=1)

    if reponse is None:
        if not quiet:
            print(f"\u26a0\ufe0f  moteur injoignable ({MOTEUR}) — touch en repli LOCAL.")
            print("    L expiration est repoussee sur cette machine.")
            print("    Le Dashboard n a PAS ete notifie.")
        if agent:
            from core.bsi import BSI
            if not BSI(db.depot()).porte_identite:
                if not quiet:
                    print("\u2139\ufe0f  base locale sans colonne agent_session : "
                          "rien n est repousse — nommer le claim")
                return
        _toucher_en_repli(where, params, quiet)
        return

    code, donnees = reponse
    if not (200 <= code < 300):
        motif = str((donnees or {}).get("detail", "")) or "(sans motif)"
        print(f"\u274c le moteur a repondu {code} — {motif}", file=sys.stderr)
        sys.exit(2)

    touches = (donnees or {}).get("touches") or []
    if not quiet:
        if not touches:
            print("\u2139\ufe0f  Aucun claim ouvert a prolonger")
        for c in touches:
            print(f"\u2705 {c.get('sess_id')} \u2014 expiration repoussee de "
                  f"{c.get('ttl_hours', 4)} h")


def cmd_exists():
    if not args:
        print("❌ Usage: bsi-claim.sh exists <sess_id>", file=sys.stderr)
        sys.exit(1)

    rows = db.query(
        "SELECT status FROM claims WHERE sess_id = %s AND status = 'open'",
        (args[0],)
    )
    sys.exit(0 if rows else 1)

def cmd_init():
    n = db.count("claims")
    if n == 0:
        # Auto-restore guard (BRAIN-046) — check legacy SQLite backup
        bak_path = os.path.join(brain_root, "brain.db.bak")
        if os.path.exists(bak_path):
            import sqlite3 as sl
            try:
                bak = sl.connect(bak_path)
                bak_count = bak.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
                bak.close()
                if bak_count > 0:
                    print(f"⚠️  Table claims vide — brain.db.bak contient {bak_count} claims (legacy SQLite, migration scriptée retirée 26/04)")
                    return
            except Exception:
                pass
    backend = db.info()['backend']
    print(f"✅ DB prête ({backend}) — table claims ({n} entrées)")

def cmd_restore():
    """Cascade restore : legacy SQLite .bak → import vers DB active (BRAIN-046)"""
    bak_path = os.path.join(brain_root, "brain.db.bak")
    if not os.path.exists(bak_path):
        print("❌ brain.db.bak introuvable — restauration impossible")
        print("   Le repli SQLite a ete retire le 06/09 : il ne")
        print("   detenait plus rien que Dolt n'ait pas, verifie ligne a ligne.")
        print("   Le gel est dans brain-db-backup/sqlite-fossile-20260906.db,")
        print("   versionne et pousse — le copier ici pour restaurer.")
        print("   Source alternative : git log --grep='bsi:'")
        sys.exit(1)

    import sqlite3 as sl
    try:
        bak = sl.connect(bak_path)
        bak_count = bak.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    except Exception as e:
        print(f"❌ brain.db.bak illisible : {e}")
        sys.exit(1)

    current_count = db.count("claims")
    if current_count > 0:
        print(f"⚠️  Table claims contient {current_count} claims — restauration refusée (risque écrasement)")
        print(f"   brain.db.bak contient {bak_count} claims")
        sys.exit(1)

    # Import claims from SQLite bak into active DB backend
    rows = bak.execute("SELECT * FROM claims").fetchall()
    cols = [d[0] for d in bak.cursor().description] if hasattr(bak, 'cursor') else []
    # Re-fetch with column names
    bak.row_factory = sl.Row
    rows = bak.execute("SELECT * FROM claims").fetchall()
    bak.close()

    imported = 0
    for row in rows:
        row_dict = dict(row)
        # Build portable INSERT with available columns
        keys = [k for k in row_dict.keys() if row_dict[k] is not None]
        vals = [row_dict[k] for k in keys]
        placeholders = ', '.join(['%s'] * len(keys))
        col_list = ', '.join(keys)
        try:
            db.execute(f"REPLACE INTO claims ({col_list}) VALUES ({placeholders})", tuple(vals))
            imported += 1
        except Exception as e:
            print(f"⚠️  Skip {row_dict.get('sess_id', '?')}: {e}")

    backend = db.info()['backend']
    print(f"✅ Restauration : {imported}/{bak_count} claims importés depuis brain.db.bak → {backend}")

def cmd_rattacher():
    """Reprendre le claim d une identite que CETTE session a remplacee.

    Parquee puis reprise dans un autre processus, une session recoit une
    identite neuve ; son claim porte l ancienne, et devient « celui d une autre
    session ». Le rattachement ne devine rien : il suit la filiation que Claude
    Code ecrit lui-meme (`scripts/lib/filiation.py`), et ne touche qu aux
    claims OUVERTS portes par une identite anterieure prouvee.

    Le hook de la boite l appelle tout seul quand aucun claim ne porte la
    session ; cette commande est le meme geste, a la main.
    """
    agent = session_agent()
    if not agent:
        print("❌ rattacher : aucune identite de session dans l environnement "
              "(shell humain ?) — rien a rattacher", file=sys.stderr)
        sys.exit(1)
    sys.path.insert(0, os.path.join(brain_root, "scripts", "lib"))
    from filiation import lire, anciennes
    from pathlib import Path
    dossier = Path(os.environ.get("CLAUDE_SESSIONS_DIR")
                   or Path.home() / ".claude" / "sessions")
    sessions = lire(dossier)
    if sessions is None:
        print(f"❌ rattacher : filiation illisible ({dossier} absent) — je n ai pas "
              "pu regarder, ce n est pas « rien a rattacher »", file=sys.stderr)
        sys.exit(2)
    avant = anciennes(agent, sessions)
    if not avant:
        print("ⓘ aucune identite anterieure ecrite pour cette session — rien a rattacher")
        return
    from core.bsi import BSI
    bsi = BSI(db.depot())
    if not bsi.porte_identite:
        print("❌ rattacher : la base n a pas la colonne agent_session", file=sys.stderr)
        sys.exit(1)
    deplaces = bsi.rattache(avant, agent)
    if not deplaces:
        print(f"ⓘ {len(avant)} identite(s) anterieure(s), aucun claim ouvert a leur nom")
        return
    for sess_id in deplaces:
        print(f"✅ rattache : {sess_id} — porte desormais cette session ({agent[:8]}…)")


def demarrage_de_la_machine():
    """L'heure du dernier démarrage (UTC), lue dans `/proc/stat` (`btime`).

    `None` si illisible : l'appelant garde alors la prudence d'avant.
    `BRAIN_PROC_STAT` le remplace dans les tests, comme `CLAUDE_SESSIONS_DIR`.
    """
    chemin = os.environ.get("BRAIN_PROC_STAT") or "/proc/stat"
    try:
        with open(chemin, encoding="utf-8") as f:
            for ligne in f:
                if ligne.startswith("btime "):
                    return datetime.fromtimestamp(int(ligne.split()[1]), timezone.utc)
    except (OSError, ValueError, IndexError):
        return None
    return None


def cmd_plantes():
    """Les claims OUVERTS dont la session a planté — un par ligne.

    Planté, deux cas :

    1. l'identité portée par le claim a un fichier de session sur CETTE
       machine, son processus est mort, et aucune session vivante n'en descend
       (`scripts/lib/filiation.py`) ;
    2. l'identité est INCONNUE ici, et la machine a redémarré APRÈS l'ouverture
       du claim — aucune session d'avant le démarrage ne peut plus y vivre
      . Mesuré sur un brain du réseau le 29/09 : après un
       reboot, les fichiers des sessions coupées ont disparu, et leurs claims
       tenaient leur scope jusqu'à l'expiration (12 h en `pilote`).

    Une identité inconnue d'un claim ouvert APRÈS le démarrage n'est jamais
    déclarée plantée : l'expiration s'en charge. Un claim sans identité non
    plus : on ne peut rien en dire. Les claims d'une autre machine ne sont pas
    lus ici — `ouverts()` ne voit que la base de CETTE machine (BRAIN-078).
    Lecture seule — c'est l'appelant (le daemon) qui ferme.
    """
    sys.path.insert(0, os.path.join(brain_root, "scripts", "lib"))
    from filiation import lire, mortes
    from pathlib import Path
    dossier = Path(os.environ.get("CLAUDE_SESSIONS_DIR")
                   or Path.home() / ".claude" / "sessions")
    sessions = lire(dossier)
    if sessions is None:
        print(f"❌ plantes : {dossier} absent — je n ai pas pu regarder", file=sys.stderr)
        sys.exit(2)
    from core.bsi import BSI
    bsi = BSI(db.depot())
    if not bsi.porte_identite:
        return
    morts = mortes(sessions)
    connues = {s["sessionId"] for s in sessions}
    demarrage = demarrage_de_la_machine()
    from core.bsi import en_utc
    for c in bsi.ouverts():
        if not c.agent_session:
            continue
        if c.agent_session in morts:
            print(f"{c.sess_id}|{c.agent_session}")
            continue
        ouvert = en_utc(c.ouvert_le)
        if (c.agent_session not in connues and demarrage is not None
                and ouvert is not None and ouvert < demarrage):
            print(f"{c.sess_id}|{c.agent_session}")


def cmd_help():
    print("Usage: bsi-claim.sh <open|close|close-stale|touch|plantes|rattacher|exists|init|restore|help>")
    print("  open  <sess_id> [--scope X] [--type X] [--zone X] [--mode X] [--story 'X'] [--project X]")
    print("  close [<sess_id>] [--result X] [--energy high|medium|low] [--intention X] [--tags X] [--deliverables X] [--pas-le-mien]")
    print("        sans sess_id : le claim de CETTE session, retrouve par CLAUDE_CODE_SESSION_ID")
    print("        (BRAIN-077). Fermer celui d une AUTRE session est refuse, sauf --pas-le-mien.")
    print("  close-stale       — ferme les claims dont l expiration est passee")
    print("  touch [sess_id]   — repousse l expiration : la session est vivante")
    print("  plantes           — les claims ouverts dont la session a plante (lecture seule)")
    print("  rattacher         — reprend le claim d une identite que cette session a remplacee")
    print("                      (session parquee puis reprise) — sur filiation ecrite, jamais devinee")
    print("  exists <sess_id>  — exit 0 si open, exit 1 sinon")
    print("  init              — vérifie DB + table claims")
    print("  restore           — restaure claims depuis brain.db.bak legacy (cascade BRAIN-046)")

commands = {
    "open": cmd_open,
    "close": cmd_close,
    "close-stale": cmd_close_stale,
    "touch": cmd_touch,
    "rattacher": cmd_rattacher,
    "plantes": cmd_plantes,
    "exists": cmd_exists,
    "init": cmd_init,
    "restore": cmd_restore,
    "help": cmd_help,
}

fn = commands.get(cmd, cmd_help)
fn()
PYEOF
