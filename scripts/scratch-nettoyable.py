#!/usr/bin/env python3
# brain-distribuable: oui
"""Ce qui, dans `workspace/scratch/`, peut partir — et pourquoi le reste reste.

LECTURE SEULE : il liste, il ne supprime jamais. La décision est à l'humain, et
la suppression se fait ensuite fichier par fichier, NOMMÉ (le garde des
commandes refuse un `rm` par motif dans `scratch/`).

    python3 scripts/scratch-nettoyable.py              → candidats, puis gardés (raison)
    python3 scripts/scratch-nettoyable.py --jours 60   → un autre seuil d'âge

── La règle (tranchée par l'owner le 1/10, appliquée une première fois ce jour-là) ──

Une entrée de premier niveau de `scratch/` est candidate si TOUT est vrai :

  1. plus de N jours (30) sans modification — pour un dossier, son fichier le
     plus récent ;
  2. citée par AUCUN fichier suivi du brain, par son chemin `scratch/<nom>` —
     par le nom seul, « afr » se trouvait dans 40 fichiers sans les citer ;
  3. pas un dépôt git avec du travail non poussé (modifs, ou commits sans amont) ;
  4. revendiquée par aucune session ouverte (`bsi-query.sh open`) ;
  5. pas un worktree en cours (`wt-*`).

Les claims illisibles ne se devinent pas : sans eux, rien n'est déclaré candidat.

── Pourquoi un outil ───────────────────────────────────────────────────────

Le 30/09, un nettoyage par motif de nom (`pr-*.md`) a effacé 67 brouillons
d'autres sessions. Une règle de propriété et d'âge ne se rejoue pas de mémoire ;
le 1/10 elle tenait dans un script de session, perdu avec la session.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path


def _racine_des_donnees(env_d_abord: bool = False) -> Path:
    """La data de ce script, par `brain-engine/donnees.py` du programme : sans la
    marque d'un programme installé à part, la position (et `BRAIN_ROOT` si `env_d_abord`),
    comme avant. Un banc qui ne copie que ce script n'a pas `donnees.py` : la position."""
    import os as _os
    ici = Path(__file__).resolve().parent.parent
    src = ici / "brain-engine" / "donnees.py"
    if not src.is_file():
        return Path(_os.environ.get("BRAIN_ROOT") or ici) if env_d_abord else ici
    import importlib.util
    spec = importlib.util.spec_from_file_location("_brain_donnees", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.trouver_donnees(ici, env_d_abord=env_d_abord)[0]
    except RuntimeError as exc:
        raise SystemExit(f"❌ {exc}")



def plus_recent(p: Path) -> float:
    if p.is_file() or p.is_symlink():
        return p.lstat().st_mtime
    t = p.stat().st_mtime
    for f in p.rglob('*'):
        try:
            if f.is_file() and '.git' not in f.relative_to(p).parts:
                t = max(t, f.stat().st_mtime)
        except OSError:
            pass
    return t


def taille(p: Path) -> int:
    if p.is_file() and not p.is_symlink():
        return p.stat().st_size
    total = 0
    for f in p.rglob('*'):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def citations(brain: Path, nom: str) -> list[str]:
    motif = 'scratch/' + re.escape(nom) + r'([^A-Za-z0-9._-]|$)'
    r = subprocess.run(['git', '-C', str(brain), 'grep', '-l', '-E', motif, '--', '.',
                        ':!workspace/scratch'], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l]


def travail_non_pousse(p: Path) -> str:
    if not p.is_dir():
        return ''
    depots = {g.parent for g in p.rglob('.git')}
    if (p / '.git').exists():
        depots.add(p)
    for d in sorted(depots):
        modifs = subprocess.run(['git', '-C', str(d), 'status', '--porcelain'],
                                capture_output=True, text=True).stdout.strip()
        sans_amont = subprocess.run(['git', '-C', str(d), 'log', '--branches', '--not', '--remotes',
                                     '--oneline'], capture_output=True, text=True).stdout.strip()
        if modifs or sans_amont:
            quoi = ' et '.join(x for x, v in (('des modifs', modifs), ('des commits sans amont', sans_amont)) if v)
            return f'{d.relative_to(p.parent)} : {quoi}'
    return ''


def claims_ouverts(brain: Path) -> str | None:
    """Le texte des claims ouverts — None s'il est illisible."""
    script = brain / 'scripts' / 'bsi-query.sh'
    if not script.is_file():
        return None
    r = subprocess.run(['bash', str(script), 'open'], capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else None


def trier(brain: Path, jours: int) -> tuple[list[tuple], list[tuple], str | None]:
    scratch = brain / 'workspace' / 'scratch'
    claims = claims_ouverts(brain)
    maintenant = time.time()
    candidats, gardes = [], []
    for p in sorted(scratch.iterdir()) if scratch.is_dir() else []:
        if p.name.startswith('wt-'):
            gardes.append((p.name, 'un worktree en cours (wt-*)'))
            continue
        age = (maintenant - plus_recent(p)) / 86400
        if age < jours:
            gardes.append((p.name, f'récent ({age:.0f} j)'))
            continue
        c = citations(brain, p.name)
        if c:
            gardes.append((p.name, f'cité par {c[0]}' + (f' (+{len(c) - 1})' if len(c) > 1 else '')))
            continue
        t = travail_non_pousse(p)
        if t:
            gardes.append((p.name, f'travail non poussé — {t}'))
            continue
        if claims is None:
            gardes.append((p.name, 'claims illisibles — non jugé'))
            continue
        if p.name in claims:
            gardes.append((p.name, 'revendiqué par un claim ouvert'))
            continue
        candidats.append((p.name, age, taille(p), 'dossier' if p.is_dir() else 'fichier'))
    return candidats, gardes, (None if claims is not None else 'bsi-query.sh open illisible')


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--brain', type=Path, default=_racine_des_donnees())
    p.add_argument('--jours', type=int, default=30)
    a = p.parse_args()
    candidats, gardes, alerte = trier(a.brain.resolve(), a.jours)
    total = sum(c[2] for c in candidats)
    print(f'SCRATCH — {len(candidats)} candidat(s), {total / 1e6:.0f} Mo · {len(gardes)} gardé(s) · seuil {a.jours} j')
    if alerte:
        print(f'⚠️  {alerte} — aucune entrée déclarée candidate sans les claims')
    print('\nCANDIDATS (rien n\'est supprimé : relire, puis supprimer NOMMÉ, un par un)')
    for nom, age, octets, genre in sorted(candidats, key=lambda c: -c[2]):
        print(f'  {octets / 1e6:8.1f} Mo  {age:4.0f} j  {genre:7}  {nom}')
    print('\nGARDÉS (raison)')
    for nom, raison in gardes:
        print(f'  {nom:50} {raison}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
