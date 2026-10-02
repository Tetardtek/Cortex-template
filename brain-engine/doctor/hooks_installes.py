#!/usr/bin/env python3
"""Les hooks git du brain sont-ils ceux de l'installateur, et le garde voit-il la base ?

Ce qui pourrirait en silence sans lui : **un hook écrit à la main sur une
machine, absent des autres, et un garde de zone qui s'abstient sans que
personne le lise.** Constaté le 27/09 : le `pre-commit` du fixe écrit à la main
le 06/09, aucun sur le laptop ; l'installateur n'écrivait jamais de
`pre-commit` ; et le garde répondait « base injoignable » dans chaque worktree,
un message honnête que rien ne remontait.

Deux mesures :

    hooks      `install-brain-hooks.sh --check` — les cinq hooks sont les
               lanceurs de l'installateur (pas une copie à la main, pas absents)
    garde      le garde de zone, chargé comme le hook le charge (BRAIN_MAIN),
               lit les claims ouverts — `None` veut dire « base injoignable »

    python3 tools/hooks_installes.py --brain ~/Dev/Brain

Sortie 1 si l'un des deux échoue. Il n'écrit rien : `--check` est en lecture, et
le garde n'est interrogé que sur sa lecture de la base.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def hooks(brain: Path) -> tuple[bool, str]:
    script = brain / "scripts" / "install-brain-hooks.sh"
    if not script.is_file():
        return False, "install-brain-hooks.sh introuvable"
    r = subprocess.run(["bash", str(script), "--check"], cwd=brain,
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else ""


def garde(brain: Path) -> tuple[bool, str]:
    source = brain / "scripts" / "hooks" / "pre-commit-zone"
    if not source.is_file():
        return True, "pas de garde de zone sur cette instance — rien à joindre"
    os.environ["BRAIN_MAIN"] = str(brain)
    chargeur = importlib.machinery.SourceFileLoader("garde_de_zone", str(source))
    spec = importlib.util.spec_from_loader("garde_de_zone", chargeur)
    module = importlib.util.module_from_spec(spec)
    try:
        chargeur.exec_module(module)
        ouverts = module.sessions_ouvertes()
    except Exception as exc:                                   # noqa: BLE001
        return False, f"le garde ne se charge pas : {type(exc).__name__}"
    if ouverts is None:
        return False, "le garde ne joint pas la base — il s'abstiendrait à chaque commit"
    return True, f"le garde lit la base — {len(ouverts)} claim(s) ouvert(s)"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    brain = p.parse_args().brain.expanduser().resolve()

    ok_h, dit_h = hooks(brain)
    ok_g, dit_g = garde(brain)
    print(f"  {'✅' if ok_h else '❌'} hooks   {dit_h}")
    print(f"  {'✅' if ok_g else '❌'} garde   {dit_g}")
    if ok_h and ok_g:
        print("\nVERDICT: les hooks sont ceux de l'installateur, et le garde voit la base")
        return 0
    print("\nVERDICT: " + " ; ".join(d for ok, d in ((ok_h, "hooks à réinstaller"),
                                                     (ok_g, "garde aveugle")) if not ok))
    print("     scripts/install-brain-hooks.sh — et le venv du dépôt principal.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
