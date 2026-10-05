#!/usr/bin/env python3
"""
brain-engine/fiches_en_cours.py — ce qui est en cours, calculé, jamais déclaré.

Le focus disait « en cours » par la table `intentions` : un front rotatif que
seules des consignes d'agents tenaient à jour. Mesuré le 4/10 : figé depuis le
26/09, `total_sessions` à 0 pour 7 des 8 actives — pendant que le travail se
suivait dans les fiches. Tranché par l'owner : un seul système, les fiches, et
« en cours » se CALCULE.

Une fiche est en cours quand elle est ouverte (son index ne la dit ni livrée ni
en pause) et qu'une PR fusionnée depuis moins de `JOURS` jours porte son
étiquette dans le nom de sa branche (`ABC-12-…`, `scribe/ABC-12-…`) :

    - dans un dépôt de code (tout dépôt sauf celui des fiches), une suffit ;
    - dans le dépôt des fiches (`workspace`), il en faut deux — une PR seule y
      ouvre souvent la fiche, ce n'est pas encore du travail.

Les dépôts lus : le brain, et les satellites de `satellites.yml` posés sur cette
machine. Lecture seule, `git log` local : aucune forge, aucun jeton.

    python3 brain-engine/fiches_en_cours.py      → la liste, pour lire à la main
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

JOURS = 7
DEPOT_DES_FICHES = 'workspace'

# Gitea : « Merge pull request '<titre>' (#n) from <branche> into <base> ».
# Le titre peut contenir « from » : la branche se lit après le numéro.
FUSION = re.compile(r"\(#\d+\) from (\S+) into ")
# L'étiquette ouvre un segment de la branche : `ABC-12-x`, `scribe/ABC-12-x`.
ETIQUETTE = re.compile(r"(?:^|/)([A-Z]{2,6}-\d+)(?=$|[-_/.])")
# Une ligne d'index : | [ABC-12](ABC-12.md) | · | titre | origine |
LIGNE = re.compile(r"^\|\s*\[([A-Z]{2,6}-\d+)\]\([^)]*\)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|")
FERMEES = ('✅', '⏸')


def fiches_ouvertes(racine: Path) -> dict[str, dict]:
    """Les fiches ouvertes, depuis les index générés `workspace/backlog/<projet>/backlog.md`."""
    ouvertes = {}
    for index in sorted((racine / 'workspace' / 'backlog').glob('*/backlog.md')):
        for ligne in index.read_text(encoding='utf-8').splitlines():
            m = LIGNE.match(ligne)
            if m and not m.group(2).startswith(FERMEES):
                ouvertes[m.group(1)] = {'fiche': m.group(1), 'projet': index.parent.name,
                                        'titre': m.group(3), 'etat': m.group(2)}
    return ouvertes


def depots(racine: Path) -> list[tuple[str, Path]]:
    """Le brain, puis chaque satellite déclaré et posé sur cette machine."""
    trouves = [('brain', racine)]
    liste = racine / 'satellites.yml'
    if liste.is_file():
        import yaml
        declares = (yaml.safe_load(liste.read_text(encoding='utf-8')) or {}).get('satellites') or {}
        for nom, conf in declares.items():
            chemin = Path(str((conf or {}).get('chemin') or racine / nom)).expanduser()
            if (chemin / '.git').exists():
                trouves.append((nom, chemin))
    elif (racine / DEPOT_DES_FICHES / '.git').exists():
        trouves.append((DEPOT_DES_FICHES, racine / DEPOT_DES_FICHES))
    return trouves


def fusions(depot: Path, jours: int = JOURS) -> list[tuple[int, str]]:
    """(horodatage, étiquette) de chaque PR fusionnée dans la fenêtre."""
    # Pas de `--since` : git arrête son parcours au premier commit plus ancien que
    # la date, et une fusion récente rangée derrière une plus ancienne (un rebase,
    # une horloge décalée) disparaissait. Les dates se filtrent ici.
    seuil = time.time() - jours * 86400
    r = subprocess.run(['git', '-C', str(depot), 'log', '--merges', '-n', '2000',
                        '--format=%ct%x09%s'], capture_output=True, text=True, timeout=30)
    vues = []
    for ligne in r.stdout.splitlines() if r.returncode == 0 else []:
        quand, _, sujet = ligne.partition('\t')
        if int(quand) < seuil:
            continue
        branche = FUSION.search(sujet)
        etiquette = ETIQUETTE.search(branche.group(1)) if branche else None
        if etiquette:
            vues.append((int(quand), etiquette.group(1)))
    return vues


def en_cours(racine: Path, jours: int = JOURS, limite: int | None = None) -> list[dict]:
    """Les fiches en cours, la plus récemment touchée d'abord."""
    ouvertes = fiches_ouvertes(racine)
    vu: dict[str, dict] = {}
    for nom, depot in depots(racine):
        for quand, fiche in fusions(depot, jours):
            if fiche not in ouvertes:
                continue
            v = vu.setdefault(fiche, {'prs': 0, 'code': 0, 'derniere': 0, 'depots': set()})
            v['prs'] += 1
            v['code'] += nom != DEPOT_DES_FICHES
            v['derniere'] = max(v['derniere'], quand)
            v['depots'].add(nom)
    retenues = [
        {**ouvertes[f], 'prs': v['prs'], 'depots': sorted(v['depots']),
         'derniere': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(v['derniere']))}
        for f, v in vu.items() if v['code'] >= 1 or v['prs'] >= 2
    ]
    retenues.sort(key=lambda x: x['derniere'], reverse=True)
    return retenues[:limite] if limite else retenues


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from racines import DONNEES
    for f in en_cours(DONNEES):
        print(f"{f['fiche']:9} {f['derniere'][:10]}  {f['prs']:2} PR  {', '.join(f['depots']):30}  {f['titre'][:60]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
