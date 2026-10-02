#!/usr/bin/env python3
"""Le hook et le CORE disent-ils la même chose des zones ?

La règle a été tranchée le 07/09 : la zone d'écriture se **dérive du niveau** —
`invariant` et `programme` sont kernel — plus les exceptions déclarées par un
attribut `zone:` dans `NIVEAUX.yml`.

⚠️ **Elle est écrite DEUX FOIS.** Dans `scripts/hooks/pre-commit-zone`, qui garde
le dépôt au moment du commit, et dans `myeline/core/zones.py`, qui gardera
l'écriture d'où qu'elle vienne. Le brain ne peut pas encore dépendre d'un dépôt
en chantier — c'est temporaire et assumé.

Mais **deux déclarations de la même règle finissent par diverger**. C'est le
motif que ce chantier passe son temps à défaire : sur `CATALOG.yml`, sur les
fiches, sur les registres. À chaque fois, la même
histoire — deux endroits vrais séparément, faux ensemble.

Ce contrôle est la seule chose qui rende la duplication tenable : il compare les
deux, **chemin par chemin**, et rougit à la première divergence.

    python3 tools/regle_des_zones.py --brain ~/Dev/Brain

Il disparaîtra le jour où le hook appellera le CORE — et ce jour-là, sa
disparition sera la preuve que la dette est payée.

Sortie 1 si les deux ne s'accordent pas.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

OUTILS = Path(__file__).resolve().parent
MYELINE = OUTILS.parent


def zones_du_hook(brain: Path) -> dict[str, str] | None:
    """Ce que le hook considère comme kernel, interrogé DANS son dépôt.

    Le hook déduit sa racine de `git rev-parse --show-toplevel` : l'exécuter
    d'ailleurs lui ferait lire un `NIVEAUX.yml` inexistant et rendre du vide —
    un écart qui accuserait le hook alors qu'il accuserait le contrôle.
    """
    code = ("import runpy, json; "
            "g = runpy.run_path('scripts/hooks/pre-commit-zone', run_name='controle'); "
            "print(json.dumps(g['chemins_kernel']()))")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(brain),
                       capture_output=True, text=True, timeout=60)
    if r.returncode or not r.stdout.strip():
        return None
    return json.loads(r.stdout)


def zones_du_core(brain: Path) -> tuple[set[str], set[str]] | None:
    """(tous les chemins déclarés, ceux que le CORE dit kernel)."""
    sys.path.insert(0, str(MYELINE))
    try:
        import yaml
        from core.zones import KERNEL, Registre
    except Exception:                                      # noqa: BLE001
        return None
    try:
        d = yaml.safe_load((brain / "NIVEAUX.yml").read_text(encoding="utf-8")) or {}
    except Exception:                                      # noqa: BLE001
        return None

    niveaux, exceptions = {}, {}
    for bloc in d.values():
        if not isinstance(bloc, dict):
            continue
        for nom, val in bloc.items():
            if isinstance(val, dict):
                niveaux[nom] = val.get("niveau")
                if val.get("zone"):
                    exceptions[nom] = val["zone"]
            else:
                niveaux[nom] = val
    registre = Registre(niveaux=niveaux, exceptions=exceptions)
    kernel = {c for c in niveaux if registre.zone(c.rstrip("/")) == KERNEL}
    return set(niveaux), kernel


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    brain = args.brain.expanduser().resolve()

    if not (brain / "scripts" / "hooks" / "pre-commit-zone").is_file():
        print("\n  ⏭  le hook de zone n'est pas installé — rien à comparer.\n")
        return 0

    hook = zones_du_hook(brain)
    cote_core = zones_du_core(brain)

    if hook is None or cote_core is None:
        print("\n  ⏭  une des deux déclarations est illisible — rien n'est jugé.")
        print("     Un vert qui ne compare rien serait pire qu'un rouge.\n")
        return 0

    declares, kernel_core = cote_core
    kernel_hook = set(hook)

    print("\nLA RÈGLE DES ZONES — le hook contre le CORE\n")
    print(f"  chemins déclarés dans NIVEAUX.yml   {len(declares):>3}")
    print(f"  kernel selon le hook                {len(kernel_hook):>3}")
    print(f"  kernel selon le CORE                {len(kernel_core):>3}")

    hook_seul = sorted(kernel_hook - kernel_core)
    core_seul = sorted(kernel_core - kernel_hook)

    if not hook_seul and not core_seul:
        print("\n  ✅ les deux déclarations s'accordent, chemin par chemin\n")
        return 0

    print()
    for c in hook_seul:
        print(f"  ❌ {c:<28} kernel pour le hook, pas pour le CORE")
    for c in core_seul:
        print(f"  ❌ {c:<28} kernel pour le CORE, pas pour le hook")
    print("\n     La règle est écrite deux fois — dans le hook et dans")
    print("     `myeline/core/zones.py` — et elles ont divergé. Corriger les")
    print("     DEUX, ou faire enfin appeler le CORE par le hook.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
