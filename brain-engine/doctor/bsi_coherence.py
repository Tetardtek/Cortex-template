#!/usr/bin/env python3
"""Le claim de session est décrit d'une seule façon

Le BSI existe pour que les sessions parallèles se voient. Il est déclaré
« non négociable » dans `CLAUDE.md`, documenté correctement dans
`BRAIN-INDEX.md` — et pourtant, mesuré le 03/09 : **51 claims, tous fermés,
aucun ouvert**, alors que deux sessions tournaient en parallèle ce jour-là.

La cause était dans le résumé de boot de `helloWorld.md`, c'est-à-dire dans la
partie qui se charge en premier : il décrivait la procédure d'**avant** le 19
mars — écrire `claims/sess-*.yml`, `git add`, `git commit`, `git push`. Or
`claims/` a été vidé ce jour-là par le commit *« kernel: remove claims/ — source
unique brain.db (ADR-042) »*. L'agent demandait d'écrire dans un répertoire
supprimé exprès, pendant que le détail du même fichier, cinquante lignes plus
bas, donnait la bonne commande.

**Rien ne cassait. Le claim ne s'ouvrait simplement pas.**

    python3 tools/bsi_coherence.py --brain ~/Dev/Brain

Trois garanties :

    l'ancien mécanisme n'est décrit nulle part   ni fichier YAML, ni commit, ni push
    `claims/` reste vide                          il a été vidé à dessein
    le bon est nommé là où il faut                helloWorld et BRAIN-INDEX

Sortie 1 si une garantie tombe.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Ce qui décrit l'ancien mécanisme. Chercher `claims/` seul serait trop large :
# le mot apparaît légitimement dans des chemins d'API et des noms de table.
INTERDITS = [
    (re.compile(r"claims/sess-[*\w-]*\.ya?ml"), "écriture d'un claim en fichier YAML"),
    (re.compile(r"git (?:add|commit|push).{0,40}claim", re.I), "claim passé par git"),
    (re.compile(r"bsi: open/close claim"), "exception git accordée aux claims"),
]
# Le nom de la commande qui fait foi.
ATTENDU = "bsi-claim.sh open"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=True)
    args = parser.parse_args()
    root = args.brain.expanduser().resolve()

    echecs: list[str] = []

    def verifie(nom: str, cond: bool, detail: str = "") -> None:
        if not cond:
            echecs.append(nom)
        print(f"  {'✅' if cond else '❌'} {nom:<46} {detail}")

    print("\nCOHÉRENCE DU CLAIM DE SESSION\n")

    # ── 1. l'ancien mécanisme n'est décrit nulle part ────────────────────────
    coupables = []
    for chemin in sorted(root.glob("agents/*.md")) + [root / "BRAIN-INDEX.md"]:
        if not chemin.exists():
            continue
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for motif, quoi in INTERDITS:
            for m in motif.finditer(texte):
                ligne = texte[:m.start()].count("\n") + 1
                coupables.append(f"{chemin.name}:{ligne} ({quoi})")
    verifie("l'ancien mécanisme n'est décrit nulle part", not coupables,
            "; ".join(coupables[:3]) if coupables else "aucune trace de claims/*.yml ni de git")

    # ── 2. `claims/` reste vide ──────────────────────────────────────────────
    dossier = root / "claims"
    restants = [f.name for f in dossier.iterdir()] if dossier.is_dir() else []
    verifie("`claims/` n'est pas revenu", not restants,
            ", ".join(restants[:3]) if restants
            else ("répertoire absent" if not dossier.exists() else "présent mais vide"))

    # ── 3. le bon mécanisme est nommé là où il faut ──────────────────────────
    manquants = [c.name for c in (root / "agents" / "helloWorld.md", root / "BRAIN-INDEX.md")
                 if not c.exists()
                 or ATTENDU not in c.read_text(encoding="utf-8", errors="replace")]
    verifie(f"`{ATTENDU}` nommé dans helloWorld et BRAIN-INDEX", not manquants,
            ", ".join(manquants) if manquants else "les deux le nomment")

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} garantie(s) tombée(s)\n")
        return 1
    print("  ✅ une seule façon d'ouvrir un claim, et c'est la bonne\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
