#!/usr/bin/env python3
# brain-distribuable: oui
"""brain schema — la base suit-elle le schéma ? Retirer ce qu'une version a retiré.

    brain schema               à blanc : la base visée, et les tables qui partiraient — rien ne bouge
    brain schema --appliquer   les retirer ; refusé tout entier si une seule porte des lignes

Le schéma sait ajouter une table chez une instance, jamais en retirer une : `schema.sql` est
rejoué sans `DROP`. Une façade : le verbe parle français, `schema-retraits.sh` fait le
travail et garde son nom ; son code de sortie traverse tel quel. Son `--check` est le contrat du
doctor, pas une option du verbe.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent


def analyseur() -> argparse.ArgumentParser:
    """Les options du verbe — lues aussi par le test qui juge les instructions des agents."""
    p = argparse.ArgumentParser(prog="brain schema",
                                description="La base suit-elle le schéma ? Retirer ce qu'une version a retiré.")
    p.add_argument("--appliquer", action="store_true",
                   help="retirer les tables ; refusé tout entier si une seule porte des lignes")
    return p


def main() -> int:
    a = analyseur().parse_args()
    cmd = ["--appliquer"] if a.appliquer else []
    return subprocess.run(["bash", str(ICI / "schema-retraits.sh"), *cmd]).returncode


if __name__ == "__main__":
    sys.exit(main())
