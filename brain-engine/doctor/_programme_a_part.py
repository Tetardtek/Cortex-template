"""Un brain servi par un programme installé à part.

Le programme (moteur, scripts, noyau, `kernel.lock`, `NIVEAUX.yml`…) porte la
marque `.cortex-programme` à sa racine ; le dossier du brain n'en a que des
liens — la vue. Un contrôle qui juge le PROGRAMME (son lock, ce que git en
garde) doit alors le juger là où il vit : compté dans le dossier du brain, un
lien de la vue se lisait comme un fichier du noyau « jamais vu », et une entrée
du programme comme une donnée « déclarée versionnée, gitignorée ».

Sans la marque — le brain cloné par git, chaque fork —, rien ne change.
"""

from __future__ import annotations

from pathlib import Path

MARQUE = ".cortex-programme"


def programme_a_part(chemin: Path) -> Path | None:
    """La racine du programme installé à part où mène `chemin` (un lien de la vue),
    ou None : `chemin` n'est pas un lien, ou ne mène dans aucun programme marqué."""
    if not chemin.is_symlink():
        return None
    try:
        cible = chemin.resolve()
    except OSError:
        return None
    for d in (cible, *cible.parents):
        if (d / MARQUE).exists():
            return d
    return None


def programme_du_brain(brain: Path) -> Path | None:
    """Le programme installé à part qui sert `brain` — celui où mène son `kernel.lock`."""
    return programme_a_part(brain / "kernel.lock")
