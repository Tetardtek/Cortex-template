#!/usr/bin/env python3
# brain-distribuable: oui
"""Le garde des commandes — hook Claude Code `PreToolUse` sur `Bash`.

Trois gestes ont coûté un incident chacun ; un quatrième en aurait coûté un. Une règle écrite dans la mémoire se
lit ou ne se lit pas ; un hook, lui, est là au moment où la commande part.

    rm avec un motif dans workspace/scratch/    30/09 — `rm -f workspace/scratch/pr-*.md`
                                                a effacé 67 brouillons d'autres sessions
    git add -A (ou . , :/) dans le brain         09-10/09 — l'index est partagé entre les
                                                sessions, et `-A` stage le disque, pointeur
                                                de sous-module compris
    source / . / sh sur MYSECRETS                28/09 — ses lignes se sont exécutées, et
                                                deux fragments d'un mot de passe ont
                                                paru dans la conversation
    grep -r / rg / find -type f sur un dossier   6/10, mesuré — la vue `agents/` : 63 liens
      fait de liens, sans suivre les liens      sur 68, invisibles ; « rien trouvé » sans
                                                le dire
    sed -i sur un LIEN, sans --follow-symlinks   3/10, mesuré avant l'incident — il remplace
                                                le lien par un fichier : sur `agents/`, une
                                                vue ignorée par git, l'écriture sort de git
                                                en silence et le noyau ne bouge pas

    python3 scripts/garde-commandes.py hook     ← l'entrée du hook (JSON sur stdin)
    python3 scripts/garde-commandes.py juger "<commande>" [--cwd <dossier>]
    python3 scripts/garde-commandes.py brancher [--brain <d>]   ← le poser dans `.claude/settings.json`
    python3 scripts/garde-commandes.py etat     [--brain <d>]   ← posé ? sortie 0 oui, 1 non

── Quel brain il juge ──────────────────────────────────────────────────────

Dans un brain cloné par git, celui où il vit (sa position). Installé à part
(`pipx install brain-cortex`, la marque `.cortex-programme`), le programme
n'est pas un brain : le brain jugé est celui de la commande — `BRAIN_ROOT`,
sinon le dossier courant en remontant jusqu'à `brain-compose.local.yml`,
sinon le brain déclaré par `brain init` (`brain-engine/donnees.py`, la même
découverte que tout le programme). Sans brain trouvé, `rm` dans
`workspace/scratch/` et `git add -A` ne sont pas jugés ; les trois autres
gestes, si.

`brain init` (et `brain maj`) le posent dans les réglages DU PROJET
(`.claude/settings.json`), comme le garde de lecture : il n'ajoute que son
entrée, ne fait rien s'il y est déjà.

── Comment il lit une commande ─────────────────────────────────────────────

Comme le shell la découpe (`shlex`, ponctuation comprise) : chaque commande
simple d'une chaîne (`;`, `&&`, `||`, `|`) est jugée seule, et un `cd` déplace
le dossier courant des suivantes. Le dépôt d'un `git add` se demande à git
(`--git-common-dir`) : le tronc et ses worktrees partagent le même.

── Ce qu'il ne fait pas, et le dit ─────────────────────────────────────────

Il ne juge que ces cinq motifs. Une commande qu'il ne sait pas découper, ou
sa propre erreur, la laisse passer : un garde qui plante ne doit pas arrêter
tout le travail. Il ne voit pas non plus ce que le shell ne lui montre pas
(`find … -delete`, un `bash -c` imbriqué) — ce n'est pas un pare-feu, c'est la
règle présente au moment du geste.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROGRAMME = Path(__file__).resolve().parent.parent


def _donnees():
    """`brain-engine/donnees.py` du programme — None sans lui (un banc qui copie ce script seul)."""
    src = PROGRAMME / 'brain-engine' / 'donnees.py'
    if not src.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location('_garde_donnees', src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def brain_de(cwd: Path) -> Path | None:
    """Le brain que juge une commande lancée dans `cwd`. Un brain git : la position, comme
    avant. Un programme installé à part : la découverte des données, depuis `cwd` — None
    si aucun brain n'est trouvé."""
    mod = _donnees()
    if mod is None or not mod.est_a_part(PROGRAMME):
        return PROGRAMME
    try:
        return mod.trouver_donnees(PROGRAMME, cwd=cwd)[0]
    except RuntimeError:
        return None


BRAIN = PROGRAMME   # compatibilité : un brain git est son propre programme
SEPARATEURS = {';', '&&', '||', '|', '&', '(', ')', '\n'}
MOTIF_GLOB = re.compile(r'[*?\[]')
TOUT_STAGER = {'-A', '--all', '.', ':/', ':/.', '--no-ignore-removal'}
EXECUTENT = {'source', '.', 'bash', 'sh', 'zsh', 'eval'}


HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
SHELLS = {'bash', 'sh', 'zsh'}


def lignes_jugees(texte: str) -> list[str]:
    """Les lignes à juger : le corps d'un heredoc est du TEXTE donné à une
    commande — sauf si cette commande est un shell, qui l'exécute.

    Le 2/10, le garde a refusé une commande dont le heredoc écrivait une
    proposition : son texte disait « jamais `source` ni `.` … MYSECRETS ».
    """
    sortie, attente = [], []          # attente : [(délimiteur, tabulations, garder)]
    for ligne in texte.split('\n'):
        if attente:
            delim, tabs, garder = attente[0]
            if (ligne.lstrip('\t') if tabs else ligne) == delim:
                attente.pop(0)
            elif garder:
                sortie.append(ligne)
            continue
        sortie.append(ligne)
        executee = lu_par_un_shell(ligne)
        for m in HEREDOC.finditer(ligne):
            attente.append((m.group(3), m.group(1) == '-', executee))
    return sortie


def lu_par_un_shell(ligne: str) -> bool:
    """Un shell lit-il le heredoc ouvert sur cette ligne ? Oui si l'une des
    commandes de son pipeline est un shell : `bash <<FIN`, mais aussi
    `cat <<FIN | bash`, qui passait le 2/10. Seul `|` prolonge le pipeline ;
    `;`, `&&`, `||` le terminent. Illisible : le premier mot seul."""
    try:
        lex = shlex.shlex(ligne, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        segments, courant = [], []
        for jeton in lex:
            if jeton == '|':
                segments.append(courant)
                courant = []
            elif jeton in SEPARATEURS or set(jeton) <= set(';&|()'):
                segments.append(courant)
                if any(seg and '<<' in seg for seg in segments):
                    break                 # le pipeline du heredoc est fini
                segments, courant = [], []
            else:
                courant.append(jeton)
        segments.append(courant)
    except ValueError:
        return Path((ligne.split() or [''])[0]).name in SHELLS
    return any(Path((sans_affectations(seg) or [''])[0]).name in SHELLS for seg in segments)


def commandes(ligne: str) -> list[list[str]]:
    """Les commandes simples d'une ligne de shell. Lève ValueError si illisible."""
    lex = shlex.shlex(ligne, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    simples, courante = [], []
    for jeton in lex:
        if jeton in SEPARATEURS or set(jeton) <= set(';&|()'):
            if courante:
                simples.append(courante)
            courante = []
        else:
            courante.append(jeton)
    if courante:
        simples.append(courante)
    return simples


def sans_affectations(mots: list[str]) -> list[str]:
    """`FOO=1 BAR=2 cmd …` → `cmd …`."""
    i = 0
    while i < len(mots) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', mots[i]):
        i += 1
    return mots[i:]


def chemin(base: Path, mot: str) -> Path:
    p = Path(os.path.expanduser(mot))
    return p if p.is_absolute() else base / p


def dans_scratch(p: Path, brain: Path | None) -> bool:
    if brain is None:
        return False
    scratch = (brain / 'workspace' / 'scratch').resolve()
    try:
        p.resolve().relative_to(scratch)
        return True
    except ValueError:
        return False


def git_commun(dossier: Path) -> Path | None:
    try:
        r = subprocess.run(['git', '-C', str(dossier), 'rev-parse', '--path-format=absolute',
                            '--git-common-dir'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def est_le_brain(dossier: Path, brain: Path | None) -> bool:
    """Le dépôt de `dossier` partage-t-il le git commun du brain ? (le tronc et
    ses worktrees : un worktree a son `.git` en FICHIER, on demande donc à git)"""
    if brain is None:
        return False
    ici, lui = git_commun(dossier), git_commun(brain)
    return ici is not None and ici == lui


def fait_de_liens(dossier: Path) -> bool:
    """Un dossier dont la plupart des entrées sont des liens — la vue `agents/` :
    une recherche qui ne suit pas les liens n'y voit que les autres."""
    try:
        entrees = list(dossier.iterdir()) if dossier.is_dir() else []
    except OSError:
        return False
    liens = sum(1 for e in entrees if e.is_symlink())
    return liens > 0 and liens * 2 > len(entrees)


def recherche_aveugle(nom: str, args: list[str], ici: Path) -> str | None:
    """`grep -r`, `rg` ou `find … -type f` sans suivre les liens, sur un dossier fait de liens."""
    courtes = ''.join(a[1:] for a in args if re.fullmatch(r'-[A-Za-z]+', a))
    if nom in ('grep', 'egrep', 'fgrep'):
        if not ('r' in courtes or '--recursive' in args) or 'R' in courtes \
                or '--dereference-recursive' in args:
            return None
    elif nom == 'rg':
        if 'L' in courtes or '--follow' in args:
            return None
    elif nom == 'find':
        if 'L' in courtes or not any(args[i] == '-type' and i + 1 < len(args) and args[i + 1] == 'f'
                                     for i in range(len(args))):
            return None
    else:
        return None
    for a in args:
        if not a.startswith('-') and fait_de_liens(chemin(ici, a)):
            return a
    return None


def juger(ligne: str, cwd: Path, brain: Path | None = None) -> str | None:
    """La raison du refus, ou None. `brain` : celui que juge la commande — par défaut,
    `brain_de(cwd)`."""
    if brain is None:
        brain = brain_de(cwd)
    ici = cwd
    simples = []
    for une in lignes_jugees(ligne):
        try:
            simples += commandes(une)
        except ValueError:
            continue                      # une ligne illisible (chaîne sur plusieurs lignes) : sans verdict
    for mots in simples:
        mots = sans_affectations(mots)
        if not mots:
            continue
        nom, args = mots[0], mots[1:]

        if nom == 'cd':
            ici = chemin(ici, args[0]) if args else Path.home()
            continue

        if nom == 'rm':
            cibles = [a for a in args if not a.startswith('-')]
            motifs = [a for a in cibles if MOTIF_GLOB.search(a)]
            if any(dans_scratch(chemin(ici, a).parent, brain) for a in motifs):
                return (f"`rm` avec un motif dans workspace/scratch/ ({' '.join(motifs)}) — le "
                        f"dossier est partagé : le 30/09, `rm -f workspace/scratch/pr-*.md` a "
                        f"effacé 67 brouillons d'autres sessions. Supprimer ses fichiers NOMMÉS "
                        f"un par un ; ses brouillons vont dans le scratchpad de session.")

        if nom == 'git':
            depot, i = ici, 0
            while i < len(args) and args[i].startswith('-'):
                if args[i] == '-C' and i + 1 < len(args):
                    depot = chemin(depot, args[i + 1])
                    i += 2
                elif args[i] in ('-c', '--git-dir', '--work-tree', '--namespace') and i + 1 < len(args):
                    i += 2
                else:
                    i += 1
            if i < len(args) and args[i] == 'add':
                options = args[i + 1:]
                tout = [o for o in options if o in TOUT_STAGER
                        or (re.fullmatch(r'-[A-Za-z]+', o) and 'A' in o)]
                if tout and est_le_brain(depot, brain):
                    return (f"`git add {' '.join(tout)}` dans le brain — l'index est partagé entre "
                            f"les sessions, et `-A` stage le disque (pointeur du wiki compris). "
                            f"Stager par chemins, et commiter par chemins : "
                            f"`git commit -- <chemins>`.")

        if nom == 'sed' and '--follow-symlinks' not in args and any(
                a == '-i' or a.startswith(('-i', '--in-place')) or (re.fullmatch(r'-[A-Za-z]+', a) and 'i' in a)
                for a in args):
            liens = [a for a in args if not a.startswith('-') and chemin(ici, a).is_symlink()]
            if liens:
                return (f"`sed -i` sur un lien ({' '.join(liens)}) — il remplace le lien par un "
                        f"fichier : dans `agents/`, une vue ignorée par git, l'écriture sortirait de "
                        f"git en silence et le noyau ne bougerait pas (mesuré le 3/10). "
                        f"`sed -i --follow-symlinks`, ou écrire la cible (`noyau/…`, `instance/…`).")

        if (dossier := recherche_aveugle(nom, args, ici)):
            suivre = {'rg': 'rg -L', 'find': 'find -L'}.get(nom, 'grep -R')
            return (f"`{nom}` sans suivre les liens, dans {dossier} — la plupart de ses entrées "
                    f"sont des liens (la vue `agents/` : 63 sur 68), que cette recherche saute : "
                    f"elle rendrait « rien » sans le dire (mesuré le 6/10). `{suivre}`, "
                    f"ou chercher dans les cibles (`noyau/agents/`, `instance/agents/`).")

        if nom in EXECUTENT and any('MYSECRETS' in a for a in args):
            return (f"`{nom}` sur MYSECRETS — ses lignes s'exécuteraient, et ce qu'elles "
                    f"affichent arriverait dans la conversation (28/09). Pour une clé : "
                    f"`grep -m1 '^CLE=' …/MYSECRETS | cut -d= -f2-`, sans l'afficher.")
    return None


def hook() -> int:
    """L'entrée du hook : JSON sur stdin, un refus sur stdout, toujours code 0."""
    try:
        entree = json.load(sys.stdin)
        if entree.get('tool_name') != 'Bash':
            return 0
        ligne = (entree.get('tool_input') or {}).get('command') or ''
        cwd = Path(entree.get('cwd') or os.getcwd())
        raison = juger(ligne, cwd)
    except Exception as exc:              # noqa: BLE001 — un garde qui plante ne bloque rien
        print(json.dumps({'systemMessage': f'garde des commandes : erreur ({type(exc).__name__}) — '
                                           f'commande non jugée'}))
        return 0
    if raison:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': f'🛑 garde des commandes : {raison}',
        }}, ensure_ascii=False))
    return 0


COMMANDE = 'python3 "$CLAUDE_PROJECT_DIR/scripts/garde-commandes.py" hook'
MATCHER = 'Bash'


def reglages(brain: Path) -> Path:
    return brain / '.claude' / 'settings.json'


def lire_reglages(brain: Path) -> dict:
    """Les réglages du brain — `{}` s'ils n'existent pas ; ValueError s'ils ne sont pas du JSON."""
    f = reglages(brain)
    if not f.is_file():
        return {}
    d = json.loads(f.read_text(encoding='utf-8') or '{}')
    if not isinstance(d, dict):
        raise ValueError('pas un objet JSON')
    return d


def branche(d: dict) -> bool:
    """Le garde est-il dans ces réglages ?"""
    for entree in ((d.get('hooks') or {}).get('PreToolUse') or []):
        for h in (entree.get('hooks') or []) if isinstance(entree, dict) else []:
            if isinstance(h, dict) and 'garde-commandes' in str(h.get('command', '')):
                return True
    return False


def brancher(brain: Path) -> int:
    """Le hook dans `.claude/settings.json` du brain — son entrée seule, une fois. La
    commande passe par `$CLAUDE_PROJECT_DIR/scripts/` : dans un brain servi à part,
    `scripts/` est la vue vers le programme installé, comme pour le garde de lecture."""
    try:
        d = lire_reglages(brain)
    except ValueError as e:
        print(f"⛔ {reglages(brain)} n'est pas lisible ({e}) — rien n'est écrit ; le garde n'est pas posé.")
        return 2
    if branche(d):
        print('✅ garde des commandes déjà branché')
        return 0
    d.setdefault('hooks', {}).setdefault('PreToolUse', []).append(
        {'matcher': MATCHER, 'hooks': [{'type': 'command', 'command': COMMANDE}]})
    f = reglages(brain)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix('.json.commandes')
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(f)
    print(f'✅ garde des commandes branché — {f}')
    return 0


def etat(brain: Path) -> int:
    try:
        ok = branche(lire_reglages(brain))
    except ValueError as e:
        print(f'⛔ {reglages(brain)} illisible ({e})')
        return 1
    print('✅ garde des commandes branché' if ok
          else '❌ garde des commandes absent — python3 scripts/garde-commandes.py brancher')
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] in ('brancher', 'etat'):
        if '--brain' in sys.argv:
            brain = Path(sys.argv[sys.argv.index('--brain') + 1])
        else:
            brain = brain_de(Path.cwd())
            if brain is None:
                print('❌ aucun brain trouvé — --brain <dossier>')
                return 2
        return (brancher if sys.argv[1] == 'brancher' else etat)(brain.expanduser().resolve())
    if len(sys.argv) >= 2 and sys.argv[1] == 'hook':
        return hook()
    if len(sys.argv) >= 3 and sys.argv[1] == 'juger':
        cwd = Path(sys.argv[sys.argv.index('--cwd') + 1]) if '--cwd' in sys.argv else Path.cwd()
        raison = juger(sys.argv[2], cwd)
        print(raison or 'passe')
        return 1 if raison else 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
