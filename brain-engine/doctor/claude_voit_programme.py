#!/usr/bin/env python3
"""Claude Code voit-il le programme — un brain servi par un programme installé à part ?

Ce qui passerait inaperçu sans lui : **une session Claude Code qui ne lit ni le
noyau ni les agents.** Installé par le paquet, le programme vit hors du dossier
du brain : `KERNEL.md`, `agents/`, `contexts/` y sont des liens vers lui, et
Claude Code ne lit pas hors du projet sans permission — en `claude -p`, il
s'arrête là (mesuré le 8/10 sur le laptop). `brain init` déclare le programme
dans `.claude/settings.json` (`permissions.additionalDirectories`) ; un fichier
refait à la main, un programme réinstallé ailleurs, et la déclaration ne le
couvre plus, sans un mot.

La mesure est celle du brain lui-même (`scripts/claude-programme.py etat`) : un
seul exemplaire de ce que « déclaré » veut dire. Un brain cloné par git porte son
programme : le contrôle s'abstient, et le dit.

Ce qu'il ne voit pas : l'approbation du dossier dans Claude Code, sans laquelle
les réglages du projet sont ignorés — elle vit dans `~/.claude.json`, qui porte
les jetons de la personne ; il ne le lit pas.

    python3 tools/claude_voit_programme.py --brain ~/Dev/Brain

Sortie 0 déclaré (ou abstention dite), 1 absent ou illisible. Il n'écrit rien.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--brain", type=Path, required=True)
    a = p.parse_args()
    brain = a.brain.expanduser().absolute()
    outil = brain / "scripts" / "claude-programme.py"
    if not outil.is_file():
        print("SKIP pas de scripts/claude-programme.py sur ce brain — rien à juger")
        return 0
    r = subprocess.run([sys.executable, str(outil), "etat", "--brain", str(brain)],
                       capture_output=True, text=True, timeout=60)
    etat = (r.stdout or r.stderr).strip() or f"claude-programme.py etat : code {r.returncode}"
    if r.returncode != 0:
        print(etat)
        return 1
    print(etat if etat.startswith("SKIP") else f"VERDICT: {etat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
