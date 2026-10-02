#!/usr/bin/env python3
"""Les compteurs ont-ils quitté la table des vecteurs ?

`embeddings` porte `vector varbinary(4096)` et `chunk_text longtext` dans la
même ligne que `hit_count`. Dolt stocke en arbre de Merkle : incrémenter un
entier y réécrivait le nœud entier, vecteurs voisins compris. Mesuré le 04/09,
sur une branche jetable pour ne rien salir :

    embeddings, une ligne à la fois      16 847 o
    embeddings, groupées                  7 743 o     ← ce que search.py faisait
    table légère, une à la fois           9 653 o
    table légère, groupées                  967 o

En conditions réelles, la bascule fait passer une recherche `top_k=5` de
~15 000 à ~4 100 octets par chunk. Une lecture coûte zéro dans les deux cas :
c'était bien l'écriture.

    python3 tools/hits_hors_table.py --brain ~/Dev/Brain

**Ce que ce contrôle vérifie**, et pourquoi ainsi. Chercher dans le code qui
lit encore `embeddings.hit_count` demanderait un grep sur du SQL, et les faux
positifs y sont garantis — `brain-audit.sh` interroge légitimement les deux
tables dans la même requête. On mesure donc les **données**, où il n'y a pas
d'ambiguïté :

    la colonne gelée n'AUGMENTE plus — si elle augmente, quelqu'un y écrit

Elle peut diminuer, et ce n'est pas une dérive : `embed.py` purge des chunks,
et leurs hits partent avec eux. Le premier jet exigeait une somme constante ;
il a rougi trois heures plus tard, sur une purge parfaitement normale.

Un chunk sans ligne de compteur n'est pas une erreur non plus — c'est un chunk
que personne n'a encore consulté. `search.py` crée sa ligne au premier hit.
Exiger le contraire fabriquerait un rouge après chaque indexation, qu'il
faudrait éteindre en écrivant des milliers de lignes vides.

**Ce qu'il ne dit pas** : qu'aucun code ne *lit* la colonne gelée. Une lecture
ne laisse pas de trace. Elle rendrait une valeur figée au 04/09 — fausse, mais
silencieusement. Les trois lecteurs connus (`brain-audit.sh`,
`brain-conciergerie.sh`, `embed.py`) ont été audités et repointés ce jour-là.

Sortie 1 si le gel a cédé — c'est-à-dire si quelqu'un écrit encore dans la
colonne morte.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# La somme de `embeddings.hit_count` au moment du gel, le 04/09. C'est un
# PLAFOND, pas une valeur attendue : la colonne est morte, elle ne peut que
# perdre des lignes quand `embed.py` purge. Si elle dépasse ce plafond,
# quelqu'un y écrit encore.
SOMME_AU_GEL = 5648


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()

    sys.path.insert(0, str(args.brain.expanduser().resolve() / "brain-engine"))
    try:
        import db
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  ⏭  moteur indisponible ({type(exc).__name__}) — rien mesuré.\n")
        return 0

    echecs: list[str] = []

    def verifie(nom: str, cond: bool, detail: str = "") -> None:
        if not cond:
            echecs.append(nom)
        print(f"  {'✅' if cond else '❌'} {nom:<40} {detail}")

    print("\nCOMPTEURS D'USAGE — hors de la table des vecteurs\n")

    try:
        gelee = db.query_one(
            "SELECT COALESCE(SUM(hit_count), 0) AS s FROM embeddings")["s"]
        vivante = db.query_one(
            "SELECT COALESCE(SUM(hit_count), 0) AS s, COUNT(*) AS n "
            "FROM embedding_hits")
        sans = db.query_one(
            "SELECT COUNT(*) AS n FROM embeddings e "
            "LEFT JOIN embedding_hits h ON h.chunk_id = e.chunk_id "
            "WHERE h.chunk_id IS NULL")["n"]
    except Exception as exc:                               # noqa: BLE001
        print(f"  ❌ mesure impossible : {type(exc).__name__}: {exc}")
        print("     Une table qu'on ne peut pas lire n'est pas une table vide.\n")
        return 1

    # La somme gelée ne doit jamais AUGMENTER — elle peut diminuer.
    #
    # Premier jet : « la somme n'a pas bougé ». Faux, et ça a rougi trois heures
    # plus tard : `embed.py` a purgé un chunk qui portait un hit, et la somme
    # est passée de 5 648 à 5 647. Une colonne gelée reste gelée quand des
    # lignes disparaissent — c'est l'écriture qu'on traque, pas la suppression.
    verifie("la colonne gelée n'a pas augmenté", int(gelee) <= SOMME_AU_GEL,
            f"{int(gelee)} — plafond {SOMME_AU_GEL}"
            + (f", {SOMME_AU_GEL - int(gelee)} ligne(s) purgée(s) depuis"
               if int(gelee) < SOMME_AU_GEL else ""))

    avance = int(vivante["s"]) - SOMME_AU_GEL
    print(f"\n  ℹ️  {int(vivante['s'])} hits sur {vivante['n']} chunks — "
          f"{avance:+d} depuis le gel du 04/09.")

    # Un chunk sans ligne de compteur n'est PAS une erreur : c'est un chunk que
    # personne n'a encore consulté. `search.py` crée sa ligne au premier hit
    # (INSERT … ON DUPLICATE KEY), et la conciergerie le couvre par un LEFT
    # JOIN. Exiger une ligne pour chaque chunk fraîchement indexé fabriquerait
    # un rouge après chaque passage d'`embed.py` — et il faudrait écrire des
    # milliers de lignes vides pour l'éteindre. Un piège déjà vu,
    # et ce contrôle y est tombé à sa première nuit.
    if sans:
        print(f"  ℹ️  {sans} chunk(s) sans ligne de compteur — jamais consultés ;")
        print("      leur ligne naîtra au premier hit.")

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} garantie(s) tombée(s) : {', '.join(echecs)}")
        print("     Quelqu'un écrit encore dans `embeddings.hit_count`. Chaque")
        print("     incrément y coûte ~15 000 o au lieu de ~4 100.")
        print()
        return 1
    print("  ✅ les compteurs avancent hors de la table des vecteurs\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
