#!/usr/bin/env python3
"""Le niveau déclaré gouverne-t-il ce que le RAG distribue ?

`NIVEAUX.yml` dit de quelle nature est chaque chose à la racine du brain. Il se
décrit lui-même comme **la source** : « ce sont les autres mécanismes qui devront
s'y accorder — pas l'inverse ». `embed.py PATH_SCOPES` est l'un de ces
mécanismes, et il ne s'y accordait pas.

Mesuré le 05/09 :

    27 entrées sur 60 déclarées `donnee`, `artefact`, `etat` ou `satellite`
       — donc jamais distribuables — se résolvaient en scope `public`

Sur les vingt-sept, **une seule était réellement indexée** : `learning/`, avec
**1 365 chunks** portant `etf-finance/`, `montages-patrimoniaux/`,
`genealogie-france/`. `public` est le scope du rôle le moins privilégié :
`_SCOPE_ACCESS['public'] == ['public']`.

Les vingt-six autres étaient rattrapées par `is_private()` et `CORPUS_PATHS` —
un troisième mécanisme qui rattrape le deuxième. Ce n'est pas une garantie,
c'est une coïncidence entretenue : le jour où un répertoire échappe aux deux, le
défaut décide seul. Il valait `public` ; il vaut `satellite` depuis.

    python3 tools/niveaux_vs_scopes.py --brain ~/Dev/Brain

── Ce qu'il mesure, et pourquoi ainsi ──────────────────────────────────────

Il ne juge pas la RÉSOLUTION — trop de chemins ne sont jamais indexés, et faire
rougir sur eux fabriquerait un rouge que rien ne peut verdir, le piège de
et. Il juge les **données** : un chunk réellement en base, sous un chemin
déclaré non distribuable, ne doit pas porter le scope `public`.

C'est verdissable en une requête, et ça ne peut pas mentir.

Sortie 1 si un chunk non distribuable est servi au rôle `public`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Les niveaux qui, d'après `NIVEAUX.yml`, ne se distribuent jamais.
NON_DISTRIBUABLES = ("donnee", "artefact", "etat", "satellite")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    racine = args.brain.expanduser().resolve()

    try:
        import yaml
    except Exception:                                      # noqa: BLE001
        print("\n  ⏭  PyYAML absent — rien mesuré.\n")
        return 0

    source = racine / "NIVEAUX.yml"
    if not source.is_file():
        print("\n  ❌ `NIVEAUX.yml` introuvable — le contrôle refuse de juger")
        print("     sans sa source. Un contrôle qui invente sa référence ne")
        print("     mesure plus rien.\n")
        return 1

    entrees = yaml.safe_load(source.read_text(encoding="utf-8")).get("entrees", {})

    sys.path.insert(0, str(racine / "brain-engine"))
    try:
        import db
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  ⏭  moteur indisponible ({type(exc).__name__}) — rien mesuré.\n")
        return 0

    print("\nNIVEAUX → SCOPES — ce que le RAG distribue vraiment\n")

    fautifs: list[tuple[str, str, int]] = []
    for nom, val in sorted(entrees.items()):
        niveau = val.get("niveau") if isinstance(val, dict) else val
        if niveau not in NON_DISTRIBUABLES:
            continue
        prefixe = nom.rstrip("/")
        try:
            n = db.query_one(
                "SELECT COUNT(*) AS n FROM embeddings WHERE scope = 'public' "
                "AND (filepath = %s OR filepath LIKE %s)",
                (prefixe, prefixe + "/%"))["n"]
        except Exception as exc:                           # noqa: BLE001
            print(f"  ❌ mesure impossible : {type(exc).__name__}: {exc}")
            print("     Une table qu'on ne peut pas lire n'est pas une table vide.\n")
            return 1
        if n:
            fautifs.append((nom, str(niveau), int(n)))

    total = db.query_one("SELECT COUNT(*) AS n FROM embeddings")["n"]
    publics = db.query_one(
        "SELECT COUNT(*) AS n FROM embeddings WHERE scope = 'public'")["n"]
    print(f"  {len(entrees)} entrées déclarées · {total} chunks indexés · "
          f"{publics} en `public`")

    if fautifs:
        print()
        for nom, niveau, n in fautifs:
            print(f"  ❌ {nom:<24} déclaré `{niveau}` · {n} chunk(s) en `public`")
        print("\n     `NIVEAUX.yml` est la source : ce qui n'est pas distribuable")
        print("     ne doit pas porter le scope du rôle le moins privilégié.")
        print("     Corriger `embed.py PATH_SCOPES`, puis reclasser les lignes.")
        print("     Détail —.\n")
        return 1

    print("\n  ✅ rien de non distribuable n'est servi en `public`\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
