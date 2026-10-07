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


# Le dossier de configuration porte le nom du paquet, `brain-cortex`. La v3.5.0 écrivait
# `cortex-brain/` (le nom d'avant, pris sur PyPI par un tiers) : il se lit encore, en repli.
CONFIG = 'brain-cortex'
CONFIG_AVANT = 'cortex-brain'


def pointeur() -> Path:
    """Le fichier où `brain init` déclare le brain d'un programme installé à part."""
    base = os.getenv('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base) / CONFIG / 'brain'


def pointeurs() -> list[Path]:
    """Ceux qu'on lit, dans l'ordre : le nom du paquet, puis celui de la v3.5.0."""
    return [pointeur(), pointeur().parent.parent / CONFIG_AVANT / 'brain']


def est_a_part(racine: Path) -> bool:
    """Le programme à `racine` est-il installé à part de sa data (la marque) ?"""
    return (Path(racine) / MARQUE).exists()


def env_local(racine_programme: Path, donnees: Path) -> Path:
    """La config locale du moteur (`.env.local` : backend, ports de Dolt). D'ordinaire à
    côté du moteur, dans `brain-engine/`. Installé à part, le programme ne s'écrit pas —
    une roue vit dans un site-packages : la config est à la data, à sa racine
    (`.env.local`, que le `.gitignore` semé tait)."""
    if est_a_part(racine_programme):
        return Path(donnees) / '.env.local'
    return Path(racine_programme) / 'brain-engine' / '.env.local'


def cache(racine_programme: Path, donnees: Path) -> Path:
    """Où le moteur range ses caches (`viz_cache_*.json`). D'ordinaire `brain-engine/` de
    la data ; installé à part, `brain-engine/` de la data est un lien vers le programme :
    `.cache/` à la racine de la data, que la vue tait au dépôt."""
    if est_a_part(racine_programme):
        return Path(donnees) / '.cache'
    return Path(donnees) / 'brain-engine'


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
    for p in pointeurs():
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
