#!/usr/bin/env python3
"""
brain-engine/racines.py — où est le programme, où est la data.

Deux racines, une seule source. Jusqu'au 1/10, sept modules du moteur
(`server`, `db`, `embed`, `search`, `distill`, `migrate`, `mcp_server`)
déduisaient CHACUN la racine du brain de leur propre position
(`Path(__file__).parent.parent`) — et cette racine servait à deux choses :

    la data        le corpus, NIVEAUX.yml, brain-compose.local.yml, la base
    le programme   `.env.local`, `schema.sql`, les modules frères

Tant que le moteur vit dans le brain qu'il sert, les deux coïncident et rien ne
se voit. Le jour où le programme s'installe ailleurs que la data — ce que
Myéline prépare (programme immuable, data de l'utilisateur) —, une racine
déduite désigne le programme, et le moteur sert le mauvais brain. Et changer un
seul module aurait été pire : celui-là lirait `BRAIN_ROOT`, les modules qu'il
importe déduiraient la leur, et rien ne signalerait l'écart.

    PROGRAMME   ce dossier (`brain-engine/`) — toujours déduit : un programme
                sait où il est, c'est la seule chose qu'il ne reçoit pas
    DONNEES     la racine du brain servi — REÇUE par `BRAIN_ROOT` si elle est
                posée, sinon le parent du programme (l'installation d'aujourd'hui)

Une `BRAIN_ROOT` posée qui ne désigne pas un dossier ARRÊTE l'import : deviner
une racine de repli servirait un brain que personne n'a demandé.
"""

import os
from pathlib import Path

PROGRAMME = Path(__file__).parent


def _donnees() -> tuple[Path, str]:
    recue = (os.getenv('BRAIN_ROOT') or '').strip()
    if not recue:
        return PROGRAMME.parent, 'position du programme'
    racine = Path(recue).expanduser()
    if not racine.is_dir():
        raise RuntimeError(
            f"BRAIN_ROOT={recue} ne désigne pas un dossier — le moteur refuse "
            f"de deviner une autre racine. Corriger la variable, ou la retirer "
            f"pour servir le brain qui contient le programme ({PROGRAMME.parent}).")
    return racine, 'BRAIN_ROOT'


DONNEES, ORIGINE = _donnees()


def annonce() -> str:
    """La ligne que les services écrivent au démarrage : quelle racine, et d'où."""
    return f'racine des données : {DONNEES} ({ORIGINE}) · programme : {PROGRAMME}'
