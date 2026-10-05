"""Où vit la configuration du doctor d'une instance.

Les exemptions, les seuils et les points de référence que les contrôles lisent
sont des réglages de L'INSTANCE : ils vivent dans `instance/doctor/<nom>`, qu'une
mise à jour du gabarit ne touche pas — un fork garde les siens.

Ils vivaient dans `workspace/.<nom>`. Un brain qui n'a pas encore déménagé les
garde là : l'ancien emplacement reste lu en repli. Un réglage qui n'existe nulle
part se crée au nouvel emplacement.
"""

from __future__ import annotations

from pathlib import Path


def config_du_doctor(brain: Path, nom: str) -> Path:
    neuf = brain / "instance" / "doctor" / nom
    if neuf.exists():
        return neuf
    ancien = brain / "workspace" / f".{nom}"
    return ancien if ancien.exists() else neuf
