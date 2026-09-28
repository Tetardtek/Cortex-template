# brain-distribuable: oui
"""Où vit le brain d'un peer ?

Les appels aux peers faisaient tous `cd ~/Dev/Brain` : le chemin de
l'installation de l'owner. Un peer installé ailleurs (un fork cloné dans
`~/src/mon-fork`) répondait « No such file », et sa section s'affichait en erreur.

La règle, tranchée par Kevin le 28/09 : le peer déclare `brain_root` dans
`brain-compose.local.yml` ; sinon, le chemin du brain LOCAL relatif à `$HOME`
(`~/Dev/Brain` ici — rien ne change pour une instance déjà installée).

La racine est écrite telle quelle dans une commande exécutée sur le peer : elle
est donc VALIDÉE, jamais échappée — `~/` en tête, puis lettres, chiffres,
`.`, `_`, `/`, `-`, sans `..`. Le reste est refusé : le peer est sauté, et dit.
"""
from __future__ import annotations

import re
from pathlib import Path

SURE = re.compile(r"^(~/)?[A-Za-z0-9._/-]+$")


def racine_distante(info: dict | None, brain_local: str | Path) -> str:
    """La racine du brain d'un peer, prête à suivre `cd `. `ValueError` si refusée."""
    racine = (info or {}).get("brain_root")
    if not racine:
        local = Path(brain_local).resolve()
        home = Path.home().resolve()
        racine = f"~/{local.relative_to(home)}" if local.is_relative_to(home) else str(local)
    racine = str(racine)
    if not SURE.match(racine) or ".." in racine.split("/"):
        raise ValueError(f"brain_root refusé : {racine!r} — seuls ~/, lettres, chiffres, "
                         f"« . _ / - » sont permis, sans « .. »")
    return racine
