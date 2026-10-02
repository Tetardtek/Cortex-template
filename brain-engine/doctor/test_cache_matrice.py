#!/usr/bin/env python3
"""Témoin du cache de matrice

Mesuré au banc le 04/09 : `load_matrix()` coûtait **155 ms sur 177**, soit 87 %
du temps d'une recherche. Le brain relisait 17 Mo de vecteurs dans Dolt à chaque
requête, pour un produit matriciel qui tient dans le bruit.

La matrice reste donc en mémoire, et une empreinte dit quand la relire. Elle
porte **deux** grandeurs, et il en faut deux :

    MAX(updated_at)   voit les écritures
    COUNT(*)          voit les suppressions

C'est la leçon de : un `DELETE` n'avance aucun horodatage, et le cache
de `/visualize` a servi des points disparus pour cette exacte raison. Un cache
qui ne voit pas les suppressions ment sans jamais casser.

    python3 tools/test_cache_matrice.py --brain ~/Dev/Brain

Quatre garanties :

    le cache sert            deux appels de suite, le second ne relit pas
    une écriture invalide    updated_at bouge → la matrice est relue
    une suppression invalide COUNT bouge → la matrice est relue
    les résultats sont les mêmes  froid et chaud rendent le même classement

Écrit un chunk témoin dans l'index et le retire. Sortie 1 si une garantie tombe.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

TEMOIN = "_my65-temoin-cache"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=True)
    args = parser.parse_args()

    root = args.brain.expanduser().resolve()
    sys.path.insert(0, str(root / "brain-engine"))
    import db
    import search

    if db.BACKEND != "dolt":
        print(f"SKIP: backend `{db.BACKEND}` — le témoin écrit dans l'index Dolt.")
        return 0
    # Un index sans vecteurs — la recherche sémantique est facultative, et sans
    # Ollama il reste vide — n'a rien à mettre en cache : froid et chaud valent
    # tous deux 1 ms, et « le cache sert » ne mesure rien.
    # AVANT le gel : s'abstenir ne doit rien commiter.
    avec_vecteurs = db.query_one(
        "SELECT COUNT(*) n FROM embeddings WHERE `vector` IS NOT NULL")
    if not avec_vecteurs or not int(avec_vecteurs["n"]):
        print("SKIP index sans vecteurs — rien à mettre en cache (recherche sémantique non indexée)")
        return 0

    # Un working set sale fausserait les assertions — mais ici la saleté est
    # ATTENDUE : chaque recherche incrémente `hit_count` sans commit, et c'est
    # voulu : « acceptable pour les compteurs à haute fréquence ».
    # S'abstenir rendrait ce témoin inexécutable après la moindre recherche.
    # On gèle plutôt, comme `test_dolt_discipline.py` : ce qui traînait part dans
    # son propre commit daté, et les assertions repartent d'un état net.
    sales = db.dirty_tables()
    if sales:
        db.freeze(f"avant le témoin du cache de matrice — {', '.join(sales)}")
        print(f"  ℹ️  working set gelé avant de mesurer ({', '.join(sales)})")

    echecs: list[str] = []

    def verifie(nom: str, cond: bool, detail: str = "") -> None:
        if not cond:
            echecs.append(nom)
        print(f"  {'✅' if cond else '❌'} {nom:<42} {detail}")

    print("\nCACHE DE MATRICE\n")

    try:
        # ── 1. le cache sert ──────────────────────────────────────────────────
        search.vider_cache()
        debut = time.perf_counter()
        meta_froid, _ = search.load_matrix()
        froid = (time.perf_counter() - debut) * 1000
        debut = time.perf_counter()
        meta_chaud, _ = search.load_matrix()
        chaud = (time.perf_counter() - debut) * 1000
        verifie("le cache sert", chaud < froid / 2,
                f"{froid:.0f} ms froid → {chaud:.0f} ms chaud")
        verifie("même contenu servi", len(meta_froid) == len(meta_chaud),
                f"{len(meta_chaud)} chunks")

        # ── 2. une suppression invalide ───────────────────────────────────────
        # On ajoute d'abord, ce qui teste COUNT dans un sens ; on retire ensuite,
        # ce qui le teste dans l'autre — celui qu'un premier correctif avait raté.
        vecteur = struct.pack('768f', *([0.001] * 768))
        db.execute("INSERT INTO embeddings (chunk_id, filepath, chunk_text, scope, "
                   "`vector`, indexed, created_at, updated_at) "
                   "VALUES (%s, %s, %s, %s, %s, 1, UTC_TIMESTAMP(), UTC_TIMESTAMP())",
                   (TEMOIN, "_my65-temoin.md", "témoin du cache", "satellite", vecteur))
        apres_ajout, _ = search.load_matrix()
        verifie("un ajout invalide le cache", len(apres_ajout) == len(meta_chaud) + 1,
                f"{len(meta_chaud)} → {len(apres_ajout)}")

        # Et le témoin négatif du témoin : sans relecture, on aurait le même compte.
        db.execute("DELETE FROM embeddings WHERE chunk_id = %s", (TEMOIN,))
        apres_retrait, _ = search.load_matrix()
        verifie("une suppression invalide le cache",
                len(apres_retrait) == len(meta_chaud),
                f"{len(apres_ajout)} → {len(apres_retrait)}")

        # ── 3. les résultats ne changent pas ──────────────────────────────────
        requete = "politique de securite et gestion des secrets"
        search.vider_cache()
        a = [r['filepath'] for r in search.search(requete, top_k=5)]
        b = [r['filepath'] for r in search.search(requete, top_k=5)]
        verifie("froid et chaud rendent le même classement", a == b,
                (a[0][:44] if a else "aucun résultat"))

    finally:
        db.execute("DELETE FROM embeddings WHERE chunk_id = %s", (TEMOIN,))
        if db.dirty_tables():
            db._dolt_commit("purge : témoin du cache de matrice",
                            tables=["embeddings"])

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} garantie(s) tombée(s) : {', '.join(echecs)}\n")
        return 1
    print("  ✅ le cache sert, et il voit les deux sens du changement\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
