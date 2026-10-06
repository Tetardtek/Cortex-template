#!/usr/bin/env python3
# brain-distribuable: oui
"""Le garde de lecture — hook Claude Code `PreToolUse` : aucun sous-agent ne lit le personnel.

L'écriture d'un worker se juge sur le diff de sa PR (`zone-du-diff.py`) ; une lecture, elle, ne laisse aucune
trace dans un diff.
La règle : le personnel ne se lit jamais hors de la session — ni par le worker, ni par un sous-agent lancé en
session (un Explore, un general-purpose) : tous travaillent sans qu'on voie ce qu'ils lisent. La session, elle,
c'est l'humain présent ; son type et sa posture la gardent.

    python3 scripts/garde-lecture.py hook                    ← l'entrée du hook (JSON sur stdin)
    python3 scripts/garde-lecture.py juger <outil> '<json>'  ← l'entrée d'un outil, jugée comme un sous-agent
    python3 scripts/garde-lecture.py brancher [--brain <d>]  ← le poser dans `.claude/settings.json`
    python3 scripts/garde-lecture.py etat [--brain <d>]      ← posé ? sortie 0 oui, 1 non

── Le branchement ──────────────────────────────────────────────────────────

`brancher` ajoute son hook au `.claude/settings.json` du brain — le crée s'il
manque, n'ajoute que cette entrée, laisse tout le reste (un hook `PreToolUse` à
toi reste à côté : Claude Code les joue tous, un refus suffit). Deux fois, rien
de plus. Un fichier qui n'est pas du JSON n'est jamais réécrit : sortie 2.
`brain-setup.sh` et `brain maj` le lancent ; `brain doctor` dit s'il manque.

── Qui il tient ────────────────────────────────────────────────────────────

Un appel d'outil venu d'un sous-agent porte `agent_type` dans l'entrée du hook ; un
appel de la session n'en porte pas. Mesuré le 6/10 sur Claude Code 2.1.282 — non
documenté : si une version le retire, le garde ne voit plus personne, et son
témoin (`TestGardeLecture`) ne le saura pas. Le rejouer après une mise à jour.

── Ce qu'il refuse ─────────────────────────────────────────────────────────

Les chemins de `zone_personal` et de `zone_aucune` (`NIVEAUX.yml`) — illisibles,
ceux du 6/10 par défaut :

    Read                le fichier, liens résolus
    Grep, Glob          un `path` dans le personnel, ou un motif qui le nomme
    Bash                une commande qui nomme un chemin personnel

── Ce qu'il ne voit pas, et le dit ─────────────────────────────────────────

- Un Grep lancé plus haut (la racine) : il ne descend pas dans le personnel —
  ripgrep saute ce que `.gitignore` écarte, et le personnel l'est (mesuré).
- Un Glob lancé plus haut avec `**` : il LISTE les noms du personnel (Glob ne
  lit pas `.gitignore`, mesuré) — des noms, jamais un contenu. Le refuser
  arrêterait chaque recherche d'un sous-agent à la racine.
- Bash : ce que la commande ne nomme pas (`cd profil && cat identity/x`), un
  script qui lit pour elle. Une exclusion (`--exclude-dir=brain-secrets`,
  `':!vie/'`, `-path … -prune`) ne compte pas : elle nomme pour ne pas lire. Ce n'est pas un pare-feu : c'est la règle présente
  au moment du geste.

Sa propre erreur laisse passer, en le disant : un garde qui plante ne doit pas
arrêter tout le travail.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent
PAR_DEFAUT = ('profil/identity/', 'profil/capital*', 'vie/', 'brain-secrets/')
OUTILS = {'Read', 'Grep', 'Glob', 'Bash'}


def prefixes(brain: Path = BRAIN) -> tuple[str, ...]:
    """`zone_personal` et `zone_aucune` de `NIVEAUX.yml` — sans dépendance : deux listes de haut niveau."""
    try:
        lignes = (brain / 'NIVEAUX.yml').read_text(encoding='utf-8').splitlines()
    except OSError:
        return PAR_DEFAUT
    trouves, cle = [], None
    for ligne in lignes:
        if re.match(r'^(zone_personal|zone_aucune):\s*$', ligne):
            cle = ligne
            continue
        if cle and (m := re.match(r'^\s+-\s+(\S+)', ligne)):
            trouves.append(m.group(1).strip('\'"'))
        elif cle and ligne.strip() and not ligne.lstrip().startswith('#'):
            cle = None
    return tuple(trouves) or PAR_DEFAUT


def dans(rel: str, prefixe: str) -> bool:
    """`rel` (relatif au brain) tombe-t-il sous `prefixe` ? `capital*` : le préfixe nu."""
    if prefixe.endswith('*'):
        return rel.startswith(prefixe[:-1])
    base = prefixe.rstrip('/')
    return rel == base or rel.startswith(base + '/')


def personnel(chemin: str, cwd: Path, brain: Path, prefs) -> str | None:
    """Le chemin, s'il est personnel — relatif au brain, liens résolus."""
    if not chemin:
        return None
    p = Path(os.path.expanduser(chemin))
    p = p if p.is_absolute() else cwd / p
    try:
        rel = os.path.relpath(os.path.realpath(p), os.path.realpath(brain))
    except ValueError:
        return None
    if rel.startswith('..'):
        return None
    rel = rel.replace(os.sep, '/')
    return rel if any(dans(rel, x) for x in prefs) else None


# Une EXCLUSION nomme un chemin pour ne PAS le lire : la règle d'audit veut même qu'on exclue
# `brain-secrets/` explicitement. Le 6/10, l'orchestrator, en sous-agent, s'est vu refuser
# `grep -rn … --exclude-dir=brain-secrets` — le garde punissait le bon geste. Ces formes sont
# retirées de la commande avant de la juger ; ce qu'elle lit ailleurs se juge toujours.
EXCLUSIONS = re.compile(
    r"""--exclude(?:-dir)?(?:=|\s+)(?:"[^"]*"|'[^']*'|\S+)"""   # grep --exclude-dir=…, --exclude …
    r"""|--glob(?:=|\s+)['"]?!\S+"""                          # rg --glob '!…'
    r"""|-g\s+['"]?!\S+"""                                     # rg -g '!…'
    r"""|['"]:(?:!|\(exclude\))[^'"]*['"]"""                   # git pathspec ':!…', ':(exclude)…'
    r"""|-path\s+\S+\s+-prune""")                             # find … -path … -prune


def sans_exclusions(commande: str) -> str:
    return EXCLUSIONS.sub(' ', commande)


def nomme(texte: str, prefs) -> str | None:
    """Un texte (commande, motif) qui nomme un chemin personnel."""
    for x in prefs:
        base = re.escape(x.rstrip('*').rstrip('/'))
        suite = '' if x.endswith('*') else r'(?=/|[\s\'"]|$)'
        if m := re.search(r'(?:^|(?<=[\s\'"=:/(]))' + base + suite, texte):
            return m.group(0)
    return None


def juger(outil: str, entree: dict, cwd: Path, brain: Path = BRAIN) -> str | None:
    """La raison du refus, ou None."""
    prefs = prefixes(brain)
    if outil == 'Read':
        return personnel(entree.get('file_path', ''), cwd, brain, prefs)
    if outil in ('Grep', 'Glob'):
        trouve = personnel(entree.get('path') or '', cwd, brain, prefs)
        if trouve:
            return trouve
        for cle in ('pattern', 'glob') if outil == 'Glob' else ('glob',):
            # `!vie/**` : un motif d'exclusion ne lit rien.
            if entree.get(cle) and not str(entree[cle]).startswith('!') \
                    and (n := nomme(entree[cle], prefs)):
                return n
        return None
    if outil == 'Bash':
        return nomme(sans_exclusions(entree.get('command') or ''), prefs)
    return None


def hook() -> int:
    """L'entrée du hook : JSON sur stdin, un refus sur stdout, toujours code 0."""
    try:
        entree = json.load(sys.stdin)
        outil = entree.get('tool_name')
        if not entree.get('agent_type') or outil not in OUTILS:
            return 0
        cwd = Path(entree.get('cwd') or os.getcwd())
        trouve = juger(outil, entree.get('tool_input') or {}, cwd)
    except Exception as exc:              # noqa: BLE001 — un garde qui plante ne bloque rien
        print(json.dumps({'systemMessage': f'garde de lecture : erreur ({type(exc).__name__}) — '
                                           f'lecture non jugée'}, ensure_ascii=False))
        return 0
    if trouve:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                f'🛑 garde de lecture : un sous-agent ne lit pas le personnel ({trouve}) — '
                f'profil/identity/, profil/capital*, vie/, brain-secrets/ se lisent en session, '
                f'par l\'humain présent. Rapporte ce qui te manque au lieu de le chercher.'),
        }}, ensure_ascii=False))
    return 0


COMMANDE = 'python3 "$CLAUDE_PROJECT_DIR/scripts/garde-lecture.py" hook'
MATCHER = 'Read|Grep|Glob|Bash'


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
            if isinstance(h, dict) and 'garde-lecture.py' in str(h.get('command', '')):
                return True
    return False


def brancher(brain: Path) -> int:
    try:
        d = lire_reglages(brain)
    except ValueError as e:
        print(f'⛔ {reglages(brain)} n\'est pas lisible ({e}) — rien n\'est écrit ; le garde n\'est pas posé.')
        return 2
    if branche(d):
        print('✅ garde de lecture déjà branché')
        return 0
    d.setdefault('hooks', {}).setdefault('PreToolUse', []).append(
        {'matcher': MATCHER, 'hooks': [{'type': 'command', 'command': COMMANDE}]})
    f = reglages(brain)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix('.json.garde')
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(f)
    print(f'✅ garde de lecture branché — {f}')
    return 0


def etat(brain: Path) -> int:
    try:
        ok = branche(lire_reglages(brain))
    except ValueError as e:
        print(f'⛔ {reglages(brain)} illisible ({e})')
        return 1
    print('✅ garde de lecture branché' if ok
          else '❌ garde de lecture absent — python3 scripts/garde-lecture.py brancher')
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == 'hook':
        return hook()
    if len(sys.argv) >= 4 and sys.argv[1] == 'juger':
        trouve = juger(sys.argv[2], json.loads(sys.argv[3]), Path.cwd())
        print(f'refusé : {trouve}' if trouve else 'passe')
        return 1 if trouve else 0
    if len(sys.argv) >= 2 and sys.argv[1] in ('brancher', 'etat'):
        brain = Path(sys.argv[sys.argv.index('--brain') + 1]) if '--brain' in sys.argv else BRAIN
        return (brancher if sys.argv[1] == 'brancher' else etat)(brain.expanduser().resolve())
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
