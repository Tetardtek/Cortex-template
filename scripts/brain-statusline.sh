#!/usr/bin/env bash
# brain-distribuable: oui
# brain-statusline.sh — la statusline Claude Code du brain, livrée avec lui (issue #27)
#
# Usage :
#   brain-statusline.sh                     la ligne : lit l'entrée JSON de Claude Code sur stdin
#   brain-statusline.sh brancher [--brain <dossier>]
#                                           la pose dans ~/.claude/settings.json — SEULEMENT
#                                           s'il n'y a pas de `statusLine` (brain init le lance)
#
# Ligne 1 : le claim de CETTE session (son `session_id`), son scope et son âge, `(+N)` s'il
#           y en a plusieurs ; « pas de claim » ; « claim ? » si la base ne répond pas.
# Ligne 2 : la branche du dossier (`*` s'il est modifié) · le dossier · le modèle · le contexte.
#
# Ce qu'elle tient :
#   - la data se résout comme pour le moteur : sa position quand on l'appelle par le dossier
#     du brain (la commande que `brancher` pose), sinon `BRAIN_ROOT`, le dossier courant, le
#     brain déclaré par `brain init` (brain-engine/donnees.py) ;
#   - le python du programme (lib/python.sh) : le venv du moteur chez un fork, celui du
#     paquet chez un brain servi par le paquet ;
#   - rapide : la base a 1,5 s (`BRAIN_STATUSLINE_DELAI`), au-delà « claim ? » ; git sans
#     verrou (`GIT_OPTIONAL_LOCKS=0`) — plusieurs sessions la rafraîchissent en même temps ;
#   - aucun secret lu : ni MYSECRETS, ni `brain-compose.local.yml` ; la base par `db.py`,
#     comme tout script du BSI ; une base SQLite absente n'est jamais créée ;
#   - un champ vide plutôt qu'une erreur : rien sur stderr, toujours le code 0 ;
#   - `NO_COLOR` : sans couleur.
#
# `brancher` n'écrit jamais par-dessus une `statusLine` existante (il dit la ligne à poser),
# ni à travers un lien, ni dans un JSON illisible. Sorties : 0 posée · 1 déjà la nôtre ·
# 2 réglages illisibles ou lien (rien écrit) · 3 une autre statusline (laissée).

# Le python du PROGRAMME : `lib/python.sh` cherche le venv sous `BRAIN_ROOT` quand elle est
# posée — la data, qui n'en a pas chez un brain servi par le paquet. On la retire le temps
# de le sourcer : sans elle, il prend la position du programme (et le paquet, par sa marque).
_br="${BRAIN_ROOT-}"; _br_pose="${BRAIN_ROOT+1}"
unset BRAIN_ROOT
source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine, ou du paquet
[[ -n "$_br_pose" ]] && export BRAIN_ROOT="$_br"
unset _br _br_pose

# Appelée par le dossier du brain (`<brain>/scripts/brain-statusline.sh`, la commande posée) :
# ce dossier est la data, même quand `scripts/` y est un lien vers un programme installé à part.
_ici="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)"
if [[ -z "${BRAIN_ROOT:-}" && -f "$_ici/brain-compose.local.yml" ]]; then
  export BRAIN_ROOT="$_ici"
fi
_programme="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"

read -r -d '' _CODE <<'PYEOF'
import json, os, shlex, subprocess, sys, threading
from pathlib import Path

PROGRAMME = Path(sys.argv[1])
MODE = sys.argv[2] if len(sys.argv) > 2 else ""

# ── brancher : la poser dans ~/.claude/settings.json, jamais par-dessus ─────────────
if MODE == "brancher":
    args = sys.argv[3:]
    brain = None
    if "--brain" in args and args.index("--brain") + 1 < len(args):
        brain = Path(args[args.index("--brain") + 1]).expanduser().absolute()
    if brain is None:
        sys.path.insert(0, str(PROGRAMME / "brain-engine"))
        try:
            from racines import DONNEES as brain
        except Exception as exc:                                  # noqa: BLE001
            print(f"❌ brancher : aucun brain trouvé ({exc}) — --brain <dossier>")
            sys.exit(2)
    commande = "bash " + shlex.quote(str(Path(brain) / "scripts" / "brain-statusline.sh"))
    voulue = {"type": "command", "command": commande, "padding": 0}
    ligne = json.dumps({"statusLine": voulue}, ensure_ascii=False)
    f = Path.home() / ".claude" / "settings.json"
    if f.is_symlink():
        print(f"⚠️  {f} est un lien — rien n'est écrit à travers. La ligne à poser :\n   {ligne}")
        sys.exit(2)
    reglages = {}
    if f.exists():
        try:
            reglages = json.loads(f.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError) as exc:
            print(f"⚠️  {f} illisible ({type(exc).__name__}) — laissé tel quel. La ligne à poser :\n   {ligne}")
            sys.exit(2)
        if not isinstance(reglages, dict):
            print(f"⚠️  {f} n'est pas un objet JSON — laissé tel quel. La ligne à poser :\n   {ligne}")
            sys.exit(2)
    existante = reglages.get("statusLine")
    if existante is not None:
        if isinstance(existante, dict) and existante.get("command") == commande:
            print("statusline du brain déjà branchée")
            sys.exit(1)
        print("ℹ️  une statusline est déjà configurée dans ~/.claude/settings.json — laissée telle quelle.")
        print(f"   Pour celle du brain, remplace sa clé statusLine par :\n   {ligne}")
        sys.exit(3)
    reglages["statusLine"] = voulue
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".brain-tmp")
    tmp.write_text(json.dumps(reglages, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if f.exists():
        os.chmod(tmp, f.stat().st_mode & 0o777)
    os.replace(tmp, f)
    print(f"✅ statusline du brain branchée ({f})")
    sys.exit(0)

# ── la ligne : jamais une erreur, toujours une sortie ──────────────────────────────
# Rien sur stderr : Claude Code n'en fait rien, et un avertissement du moteur (`db.py`)
# n'est pas une ligne d'état.
_nul = os.open(os.devnull, os.O_WRONLY)
os.dup2(_nul, 2)

try:
    entree = json.loads(sys.stdin.read() or "{}")
    if not isinstance(entree, dict):
        entree = {}
except Exception:                                                   # noqa: BLE001
    entree = {}

def champ(*chemin):
    v = entree
    for c in chemin:
        v = v.get(c) if isinstance(v, dict) else None
    return v

COULEUR = not os.environ.get("NO_COLOR")
def c(code, texte):
    return f"\033[{code}m{texte}\033[0m" if COULEUR else texte
VIOLET, ROSE, CYAN, JAUNE, GRIS = "38;5;141", "38;5;211", "38;5;117", "38;5;222", "38;5;245"
SEP = c(GRIS, " · ")

# Le claim de la session — dans un fil, borné : une base lente ne bloque pas la ligne.
sid = champ("session_id") or ""
resultat = {}

def lire_claims():
    try:
        sys.path.insert(0, str(PROGRAMME / "brain-engine"))
        import logging
        logging.disable(logging.CRITICAL)
        import db
        if db.BACKEND != "dolt" and not Path(db.DB_PATH).exists():
            return                                # sqlite3.connect créerait la base
        from core.bsi import BSI
        bsi = BSI(db.depot())
        if not bsi.porte_identite:
            return
        resultat["claims"] = bsi.de_la_session(sid)
    except Exception:                                               # noqa: BLE001
        pass

if sid:
    fil = threading.Thread(target=lire_claims, daemon=True)
    fil.start()
    try:
        delai = float(os.environ.get("BRAIN_STATUSLINE_DELAI") or 1.5)
    except ValueError:
        delai = 1.5
    fil.join(delai)

def age(heures):
    if heures is None:
        return ""
    h, m = int(heures), int((heures - int(heures)) * 60)
    return f"{h}h{m:02d}" if h else f"{m} min"

claims = resultat.get("claims")
if claims is None:
    ligne1 = c(GRIS, "claim ?")
elif not claims:
    ligne1 = c(GRIS, "pas de claim")
else:
    premier = claims[0]
    ligne1 = c(VIOLET, premier.scope)
    a = age(premier.age_heures)
    if a:
        ligne1 += " " + c(GRIS, "⏱") + a
    if len(claims) > 1:
        ligne1 += " " + c(JAUNE, f"(+{len(claims) - 1})")

# Le dossier et sa branche — git sans verrou optionnel, borné.
dossier = champ("workspace", "current_dir") or champ("cwd") or os.getcwd()
env_git = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
def git(*a):
    try:
        r = subprocess.run(["git", "-C", str(dossier), *a], capture_output=True, text=True,
                           timeout=1, env=env_git)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:                                               # noqa: BLE001
        return None
morceaux = []
branche = git("symbolic-ref", "--short", "-q", "HEAD") or git("rev-parse", "--short", "HEAD")
if branche:
    if git("status", "--porcelain", "--untracked-files=no"):
        branche += "*"
    morceaux.append(c(ROSE, branche))
maison = str(Path.home())
affiche = str(dossier)
if affiche == maison or affiche.startswith(maison + "/"):
    affiche = "~" + affiche[len(maison):]
morceaux.append(affiche)
modele = champ("model", "display_name") or champ("model", "id")
if modele:
    morceaux.append(c(VIOLET, str(modele)))
pct = champ("context_window", "used_percentage")
if isinstance(pct, (int, float)):
    p = max(0, min(100, int(pct)))
    plein = p * 8 // 100
    teinte = ROSE if p >= 80 else JAUNE if p >= 50 else CYAN
    morceaux.append(c(teinte, "[" + "█" * plein + "·" * (8 - plein) + "]") + f" {p}%")

sys.stdout.write(ligne1 + "\n" + SEP.join(morceaux) + "\n")
sys.stdout.flush()
os._exit(0)                                     # un fil encore pendu sur la base ne retient rien
PYEOF

exec python3 -c "$_CODE" "$_programme" "$@"
