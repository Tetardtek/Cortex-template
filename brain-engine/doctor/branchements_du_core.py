#!/usr/bin/env python3
"""Les portes délèguent-elles toujours au CORE ? —.

**Ce fichier remplace `equivalence_decoupage.py`, et c'est un progrès.**

Ce contrôle-là comparait `embed.chunk_by_h2` à `core.indexation.par_sections`
pour autoriser le branchement. Depuis que `embed.py` **délègue**, il compare le
CORE à lui-même — à un détail près qui n'était pas son sujet (les seuils de
l'instance contre les défauts du CORE). Un contrôle qui ne mesure plus ce qu'il
annonce doit changer de question, pas rester par habitude.

La question qui vaut maintenant : **le branchement tient-il ?** Une équivalence
prouvée une fois ne protège de rien si quelqu'un réintroduit demain une
implémentation locale — par commodité, par copier-coller, ou en résolvant un
conflit de fusion du mauvais côté.

    python3 tools/branchements_du_core.py --brain ~/Dev/Brain

── Ce qu'il vérifie, et comment ────────────────────────────────────────────

Par AST, dans le corps de la fonction ou de la route concernée : l'appel au
CORE est-il là ? Pas un `grep` sur le fichier entier — un import de `core` en
tête ne prouve pas que la fonction s'en sert.

Ce qui a été prouvé une fois, au moment où c'était mesurable, et qui n'a pas à
être rejoué chaque jour contre soi-même :

    embed.py     692 fichiers · 6 881 chunks · 0 ecart
                 texte · titre · chemin · identifiant · empreinte
    search.py    8 requetes · memes rangs · ecart de score EXACTEMENT 0.0
    bsi          8 cas de conflit · 0 ecart sur ce que le schema autorise

Le cron d'indexation l'a confirmé en conditions réelles le 11/09 : **6 830
chunks inchangés sur 6 881**, 51 vecteurs regénérés — ceux des fichiers
modifiés ce jour-là. Un découpage qui aurait bougé en aurait regénéré 6 881.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# (fichier, fonction ou route, appel attendu, ce que ca protege)
BRANCHEMENTS = [
    ("embed.py",  "chunk_by_h2",       "par_sections",
     "le decoupage par sections"),
    ("embed.py",  "chunk_by_size",     "par_taille",
     "le decoupage par taille"),
    ("search.py", "_moteur_core",      "Recherche",
     "le classement semantique"),
    ("server.py", "bsi_claims_create", "BSI",
     "le mutex de scope a l'ouverture d'un claim"),

    # Le sixieme — celui dont tout depend.
    #
    # Trois entrees, parce que `db.py` delegue a DEUX briques et qu'un
    # debranchement partiel est le cas le plus vraisemblable : on remet une
    # traduction locale « juste pour un cas », on garde le depot.
    ("db.py", "_prepare_sql", "traduire",
     "la traduction du SQL portable"),
    ("db.py", "_depot", "Depot",
     "la couche d'acces aux donnees"),
    ("db.py", "purge", "purge",
     "la suppression encadree — geler, operer, dater"),
]


def appels_dans(arbre: ast.AST, nom: str) -> set[str] | None:
    """Les noms appelés dans la fonction `nom`, ou None si elle n'existe pas."""
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            out = set()
            for x in ast.walk(n):
                if isinstance(x, ast.Call):
                    f = x.func
                    out.add(f.attr if isinstance(f, ast.Attribute)
                            else getattr(f, "id", ""))
                # `from core.bsi import BSI` DANS la fonction compte aussi :
                # c'est la forme que prennent les branchements paresseux.
                elif isinstance(x, ast.ImportFrom) and (x.module or "").startswith("core"):
                    out |= {a.name for a in x.names}
            return out
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Les portes délèguent-elles au CORE ?")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()
    moteur = a.brain.expanduser().resolve() / "brain-engine"

    manquants, absents = [], []
    for fichier, fonction, attendu, quoi in BRANCHEMENTS:
        chemin = moteur / fichier
        if not chemin.is_file():
            print(f"  ⏭️  {fichier} introuvable")
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        appels = appels_dans(arbre, fonction)
        if appels is None:
            absents.append((fichier, fonction))
            print(f"  ❌ {fichier}:{fonction} — la fonction n'existe plus")
            continue
        ok = attendu in appels
        print(f"  {'✅' if ok else '❌'} {fichier}:{fonction} → {attendu}"
              f"{'' if ok else '  MANQUANT'}   {quoi}")
        if not ok:
            manquants.append((fichier, fonction, attendu, quoi))

    if absents or manquants:
        print(f"\n❌ {len(manquants) + len(absents)} branchement(s) rompu(s).",
              file=sys.stderr)
        for f, fn, att, quoi in manquants:
            print(f"     {f}:{fn} n'appelle plus `{att}` — {quoi} est repassé\n"
                  f"       à une implémentation locale.", file=sys.stderr)
        for f, fn in absents:
            print(f"     {f}:{fn} a disparu — si c'est voulu, retirer l'entrée "
                  f"de BRANCHEMENTS.", file=sys.stderr)
        print(f"\n   Une équivalence prouvée une fois ne protège de rien si le\n"
              f"   branchement se défait.", file=sys.stderr)
        return 1

    print(f"\n✅ les {len(BRANCHEMENTS)} branchements tiennent — les portes "
          f"appellent le CORE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
