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

── Un programme installé à part ──────────────────────────────────────

Un programme qui porte la marque `.cortex-programme` à sa racine n'est PAS un
brain : il en sert un, ailleurs. Sa racine ne vaut alors jamais pour la data, et
la data se TROUVE, dans cet ordre :

    BRAIN_ROOT                 posée : elle fait foi
    le dossier courant         en remontant jusqu'à `brain-compose.local.yml`,
                               comme git cherche `.git`
    le brain déclaré           par `brain init`, dans
                               `${XDG_CONFIG_HOME:-~/.config}/brain-cortex/brain`
                               (en repli `cortex-brain/`, la v3.5.0)

Rien de trouvé : une erreur qui dit quoi faire — jamais le programme servi comme
un brain. Sans la marque (un brain cloné par git, chaque fork, chaque banc d'essai), RIEN ne
change : `BRAIN_ROOT`, sinon la position. La marque est posée par ce qui installe
le programme à part (la roue du paquet ; `essai-separe.sh` d'ici là),
jamais par le gabarit. La recherche vit dans `donnees.py` (importable sans rien
calculer) ; `scripts/lib/donnees.sh` en est l'équivalent shell — un test les tient
d'accord.
"""

import os
from pathlib import Path

PROGRAMME = Path(__file__).parent
try:
    from donnees import MARQUE, REPERE, est_a_part, pointeur, trouver_donnees  # noqa: F401 — une seule définition
    from donnees import cache as _cache, env_local as _env_local
except ImportError:
    def _env_local(racine_programme, donnees):  # noqa: ARG001
        return Path(racine_programme) / 'brain-engine' / '.env.local'

    def _cache(racine_programme, donnees):  # noqa: ARG001
        return Path(donnees) / 'brain-engine'

    def est_a_part(racine):  # noqa: ARG001
        return False

    # Un banc (ou un outil du doctor) qui copie `racines.py` seul n'a pas `donnees.py` :
    # la règle d'avant — `BRAIN_ROOT`, sinon la position. Un programme sans `donnees.py`
    # ne porte pas la marque : il n'a rien d'autre à trouver.
    def trouver_donnees(racine_programme, cwd=None, env_d_abord=True):  # noqa: ARG001
        recue = (os.getenv('BRAIN_ROOT') or '').strip()
        if recue and env_d_abord:
            racine = Path(recue).expanduser()
            if not racine.is_dir():
                raise RuntimeError(
                    f"BRAIN_ROOT={recue} ne désigne pas un dossier — le brain refuse de deviner une "
                    f"autre racine. Corriger la variable, ou la retirer.")
            return racine, 'BRAIN_ROOT'
        return Path(racine_programme), 'position du programme'


DONNEES, ORIGINE = trouver_donnees(PROGRAMME.parent)
# La config locale et les caches : à côté du moteur d'ordinaire, dans la data quand
# le programme est installé à part — il ne s'écrit pas.
ENV_LOCAL = _env_local(PROGRAMME.parent, DONNEES)
CACHE = _cache(PROGRAMME.parent, DONNEES)
A_PART = est_a_part(PROGRAMME.parent)


def annonce() -> str:
    """La ligne que les services écrivent au démarrage : quelle racine, et d'où."""
    return f'racine des données : {DONNEES} ({ORIGINE}) · programme : {PROGRAMME}'


if __name__ == '__main__':
    # `python3 racines.py --donnees <racine du programme>` : la data, une ligne —
    # ce que l'équivalent shell doit rendre (le test d'accord la compare) ; comme lui,
    # `BRAIN_ROOT` n'y compte qu'avec la marque.
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--donnees':
        try:
            print(trouver_donnees(Path(sys.argv[2]), env_d_abord=False)[0])
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            sys.exit(1)
    else:
        print(annonce())
