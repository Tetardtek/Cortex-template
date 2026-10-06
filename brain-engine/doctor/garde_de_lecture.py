#!/usr/bin/env python3
"""Le garde de lecture est-il branché ?

Ce qui passerait inaperçu sans lui : **un sous-agent de Claude Code (le worker
de l'autonomie, un Explore…) qui lit le personnel sans que rien ne l'arrête.**
Le garde est un hook `PreToolUse` du projet (`scripts/garde-lecture.py`), et
son branchement vit dans `.claude/settings.json` — un fichier que le gabarit ne
livre pas : le setup et `brain maj` l'y ajoutent. Un fichier refait à la main,
une machine installée avant lui, et le garde est absent sans un mot.

La mesure est celle du garde lui-même (`garde-lecture.py etat`) : un seul
exemplaire de ce que « branché » veut dire.

    python3 tools/garde_de_lecture.py --brain ~/Dev/Brain

Sortie 0 branché (ou pas de garde sur ce brain, dit), 1 absent ou illisible.
Il n'écrit rien.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--brain", type=Path, required=True)
    brain = p.parse_args().brain.expanduser().resolve()
    garde = brain / "scripts" / "garde-lecture.py"
    if not garde.is_file():
        print("⏭️  pas de garde de lecture sur ce brain (scripts/garde-lecture.py) — rien à juger")
        return 0
    r = subprocess.run([sys.executable, str(garde), "etat", "--brain", str(brain)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 2:
        # Un garde d'avant `etat` répond par son mode d'emploi : il ne sait pas dire s'il est branché.
        print("❌ ce garde-lecture.py ne sait pas dire son état (antérieur à `etat`) — brain maj")
        return 1
    print((r.stdout or r.stderr).strip() or f"garde-lecture.py etat : code {r.returncode}")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
