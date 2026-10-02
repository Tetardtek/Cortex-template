#!/usr/bin/env python3
"""Ce que le brain relit correspond-il à ce qu'il déclare ?

`NIVEAUX.yml` dit qu'un `invariant` et un `programme` sont « indexés toujours ».
`embed.py CORPUS_PATHS` décide de ce qui l'est vraiment. C'est le troisième des
cinq mécanismes qui redéclarent le niveau chacun à sa façon.

Mesuré le 05/09, avant correction :

    profil/specs/            0 chunk — les dix specs du programme
    PATHS.md                 invariant, absent du corpus
    brain-constitution.md    invariant, absent du corpus

`context-hygiene.md` est cité par **quarante agents**, et le brain ne pouvait pas
se le relire. `profil/` était exclu en bloc — « trop large, inclut bact/ » — ce
qui était vrai avant une découpe, et ne l'est plus.

    python3 tools/niveaux_vs_corpus.py --brain ~/Dev/Brain

── L'exception, et pourquoi elle se déclare ────────────────────────────────

« programme = indexé toujours » est vrai des documents, faux des artefacts qui
partagent leur niveau : `LICENSE` fait onze lignes de droit, `kernel.lock` des
empreintes, `brain-compose.yml` de la configuration. Aucun n'a sa place dans un
corpus sémantique.

L'attribut `indexe: non` porte ces cas. Sans lui, il fallait choisir entre un
tableau de niveaux faux et un `CORPUS_PATHS` qui le contredit en silence — et
c'est le second qui avait été choisi, sans que rien ne le dise.

Sortie 1 si une entrée déclarée indexée ne l'est pas, ou l'inverse.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOUJOURS = ("invariant", "programme")
JAMAIS = ("moteur", "etat", "artefact")


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
        print("     sans sa source.\n")
        return 1
    entrees = yaml.safe_load(source.read_text(encoding="utf-8")).get("entrees", {})

    sys.path.insert(0, str(racine / "brain-engine"))
    try:
        import embed
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  ⏭  moteur indisponible ({type(exc).__name__}) — rien mesuré.\n")
        return 0

    corpus = {c[0].rstrip("/") for c in embed.CORPUS_PATHS if c[0] != "."}
    corpus |= {c[1] for c in embed.CORPUS_PATHS if c[0] == "."}

    manquants, en_trop = [], []
    for nom, val in sorted(entrees.items()):
        niveau = val.get("niveau") if isinstance(val, dict) else val
        exclu = isinstance(val, dict) and val.get("indexe") == "non"
        court = nom.rstrip("/")
        dedans = court in corpus
        if niveau in TOUJOURS and not dedans and not exclu:
            manquants.append((nom, str(niveau)))
        if niveau in JAMAIS and dedans:
            en_trop.append((nom, str(niveau)))

    print(f"\nNIVEAUX → CORPUS — ce que le brain relit\n")
    print(f"  {len(entrees)} entrées déclarées · {len(corpus)} chemins dans CORPUS_PATHS")
    print(f"  exceptions `indexe: non`  "
          f"{sum(1 for v in entrees.values() if isinstance(v, dict) and v.get('indexe') == 'non')}")

    if manquants or en_trop:
        print()
        for nom, niveau in manquants:
            print(f"  ❌ {nom:<28} `{niveau}` — déclaré indexé, absent du corpus")
        for nom, niveau in en_trop:
            print(f"  ❌ {nom:<28} `{niveau}` — jamais indexé, présent dans le corpus")
        print("\n     `NIVEAUX.yml` est la source. Soit `CORPUS_PATHS` s'y accorde,")
        print("     soit l'entrée déclare `indexe: non` avec sa raison.\n")
        return 1

    print("\n  ✅ le corpus dit ce que les niveaux déclarent\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
