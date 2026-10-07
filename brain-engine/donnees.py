#!/usr/bin/env python3
"""brain-engine/donnees.py — trouver la data d'un programme installé à part.

La seule définition ; `racines.py` s'en sert pour le moteur, les scripts de
`scripts/` l'importent sans rien calculer à l'import (un programme à part sans
brain trouvé lève à l'appel, pas en chargeant le module). L'ordre, et pourquoi :
la docstring de `racines.py`. L'équivalent shell : `scripts/lib/donnees.sh`.
"""

import os
from pathlib import Path

MARQUE = '.cortex-programme'
REPERE = 'brain-compose.local.yml'


def pointeur() -> Path:
    """Le fichier où `brain init` déclare le brain d'un programme installé à part."""
    base = os.getenv('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base) / 'cortex-brain' / 'brain'


def est_a_part(racine: Path) -> bool:
    """Le programme à `racine` est-il installé à part de sa data (la marque) ?"""
    return (Path(racine) / MARQUE).exists()


def trouver_donnees(racine_programme: Path, cwd: Path | None = None,
                    env_d_abord: bool = True) -> tuple[Path, str]:
    """(la racine de la data, d'où elle vient) pour le programme à `racine_programme`.

    `env_d_abord=False` : sans la marque, la position fait foi même si `BRAIN_ROOT`
    est posée — le comportement des scripts qui l'ont toujours ignorée."""
    racine_programme = Path(racine_programme)
    a_part = est_a_part(racine_programme)
    recue = (os.getenv('BRAIN_ROOT') or '').strip()
    if recue and (env_d_abord or a_part):
        racine = Path(recue).expanduser()
        if not racine.is_dir():
            raise RuntimeError(
                f"BRAIN_ROOT={recue} ne désigne pas un dossier — le brain refuse de deviner une "
                f"autre racine. Corriger la variable, ou la retirer.")
        return racine, 'BRAIN_ROOT'
    if not a_part:
        return racine_programme, 'position du programme'
    ici = Path(cwd or os.getcwd()).absolute()
    for d in (ici, *ici.parents):
        if (d / REPERE).is_file():
            return d, 'dossier courant'
    p = pointeur()
    if p.is_file():
        declare = Path(p.read_text(encoding='utf-8').strip()).expanduser()
        if declare.is_dir():
            return declare, f'déclaré par brain init ({p})'
    raise RuntimeError(
        f"programme installé à part ({racine_programme}) et aucun brain trouvé : poser "
        f"BRAIN_ROOT, lancer depuis le dossier du brain, ou en créer un — brain init "
        f"<nom> <dossier>.")


def donnees_du_script(fichier: str, env_d_abord: bool = False) -> Path:
    """La data d'un script de `scripts/` (ou de `scripts/lib/`, en remontant d'un
    cran de plus) : sa racine de programme, puis `trouver_donnees`. Sans la marque,
    la position — ce que le script calculait lui-même."""
    ici = Path(fichier).resolve().parent
    racine = ici.parent.parent if ici.name == 'lib' else ici.parent
    return trouver_donnees(racine, env_d_abord=env_d_abord)[0]
