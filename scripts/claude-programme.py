#!/usr/bin/env python3
# brain-distribuable: oui
"""Claude Code voit-il le programme ? — `permissions.additionalDirectories` du brain.

Installé à part (`pipx install brain-cortex`), le programme vit hors du dossier du
brain : `KERNEL.md`, `agents/`, `contexts/` y sont des liens vers lui. Claude Code
ne lit pas un fichier hors du projet sans permission — et en `claude -p`, il
s'arrête là. Mesuré le 8/10 sur le laptop : la session ne lisait ni le noyau ni un
agent.

    python3 scripts/claude-programme.py poser [--brain <d>]   ← le déclarer dans `.claude/settings.json`
    python3 scripts/claude-programme.py etat  [--brain <d>]   ← déclaré ? sortie 0 oui, 1 non

── Ce qui est déclaré ──────────────────────────────────────────────────────

La racine du **venv** qui porte le programme (le dossier qui a `pyvenv.cfg`, en
remontant depuis lui) : son chemin ne bouge pas quand Python change de version,
celui de `site-packages` si. Sans venv, le dossier du programme lui-même.

`poser` l'ajoute à `permissions.additionalDirectories` — le fichier est créé s'il
manque, le reste (le hook du garde de lecture, un réglage à toi) n'est pas touché.
Deux fois, rien de plus. Un fichier qui n'est pas du JSON n'est jamais réécrit :
sortie 2. Un brain cloné par git porte son programme : rien à déclarer, sortie 0.

── Ce que ça ne fait pas ───────────────────────────────────────────────────

Claude Code **ignore les permissions d'un projet tant que son dossier n'est pas
approuvé** (« this workspace has not been trusted » — mesuré le 8/10). L'approbation
est celle de la personne : ouvrir `claude` une première fois dans le dossier du
brain, et l'accepter. Ce script ne l'écrit jamais à sa place (`~/.claude.json`
porte ses jetons).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MARQUE = '.cortex-programme'


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


def programme_de(brain: Path) -> Path | None:
    """Le programme qui sert ce brain, s'il est installé à part — sinon None (un brain git).
    Lu par la vue : `scripts/` du brain est un lien vers celui du programme."""
    scripts = brain / 'scripts'
    if not scripts.is_symlink():
        return None
    prog = scripts.resolve().parent
    return prog if (prog / MARQUE).exists() else None


def a_declarer(programme: Path) -> Path:
    """La racine du venv qui porte le programme, sinon le programme."""
    for d in [programme, *programme.parents]:
        if (d / 'pyvenv.cfg').is_file():
            return d
    return programme


def declares(d: dict) -> list[str]:
    p = d.get('permissions') if isinstance(d.get('permissions'), dict) else {}
    dirs = p.get('additionalDirectories') if isinstance(p.get('additionalDirectories'), list) else []
    return [str(x) for x in dirs]


def couvre(dirs: list[str], programme: Path) -> bool:
    """Une entrée déclarée contient-elle le programme ?"""
    prog = programme.resolve()
    for x in dirs:
        racine = Path(os.path.expanduser(x)).resolve()
        if prog == racine or racine in prog.parents:
            return True
    return False


def poser(brain: Path) -> int:
    programme = programme_de(brain)
    if programme is None:
        print('✅ brain cloné par git — le programme est dans le dossier, rien à déclarer')
        return 0
    try:
        d = lire_reglages(brain)
    except ValueError as e:
        print(f"⛔ {reglages(brain)} n'est pas lisible ({e}) — rien n'est écrit ; Claude Code ne verra pas le programme.")
        return 2
    cible = a_declarer(programme)
    if couvre(declares(d), programme):
        print(f'✅ Claude Code voit déjà le programme ({cible})')
        return 0
    perms = d.get('permissions') if isinstance(d.get('permissions'), dict) else {}
    dirs = perms.get('additionalDirectories') if isinstance(perms.get('additionalDirectories'), list) else []
    perms['additionalDirectories'] = [*dirs, str(cible)]
    d['permissions'] = perms
    f = reglages(brain)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix('.json.programme')
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(f)
    print(f'✅ Claude Code voit le programme — {cible} déclaré dans {f}')
    return 0


def etat(brain: Path) -> int:
    programme = programme_de(brain)
    if programme is None:
        print('SKIP brain cloné par git — le programme est dans le dossier, rien à déclarer')
        return 0
    try:
        dirs = declares(lire_reglages(brain))
    except ValueError as e:
        print(f'❌ {reglages(brain)} illisible ({e})')
        return 1
    if couvre(dirs, programme):
        print(f'✅ Claude Code voit le programme ({a_declarer(programme)})')
        return 0
    quoi = 'absent' if not dirs else f'ne contient pas {programme}'
    print(f'❌ Claude Code ne voit pas le programme : permissions.additionalDirectories {quoi} — '
          f'il ne lira ni le noyau ni les agents. Réparer : brain init (relancé), ou '
          f'python3 scripts/claude-programme.py poser')
    return 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] in ('poser', 'etat'):
        brain = Path(sys.argv[sys.argv.index('--brain') + 1]) if '--brain' in sys.argv else Path.cwd()
        brain = brain.expanduser().absolute()
        return (poser if sys.argv[1] == 'poser' else etat)(brain)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
