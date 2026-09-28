#!/usr/bin/env python3
"""
brain-engine/umap-edges.py — Calcul des liens sémantiques pour Cosmos V2
Lit les vecteurs depuis la DB, calcule les K plus proches voisins (cosine),
stocke les edges dans cosmos_edges.

Usage :
  python3 brain-engine/umap-edges.py            → calcul complet
  python3 brain-engine/umap-edges.py --stats     → stats des edges
  python3 brain-engine/umap-edges.py --threshold 0.85  → seuil custom (défaut: 0.80)
  python3 brain-engine/umap-edges.py --max-k 8   → max voisins par chunk (défaut: 5)

Cron : lancer après umap-positions.py
"""

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db as brain_db


# ── Config ──────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLD = 0.80   # cosine similarity minimum pour créer un edge
DEFAULT_MAX_K = 5          # max voisins par chunk


def ensure_table():
    """Crée la table cosmos_edges si absente."""
    brain_db.execute("""
        CREATE TABLE IF NOT EXISTS cosmos_edges (
            source_id VARCHAR(255) NOT NULL,
            target_id VARCHAR(255) NOT NULL,
            similarity REAL NOT NULL,
            PRIMARY KEY (source_id, target_id)
        )
    """)


def load_vectors():
    """Charge chunk_id + vecteurs depuis la DB."""
    rows = brain_db.query(
        "SELECT chunk_id, `vector`, filepath FROM embeddings WHERE `vector` IS NOT NULL AND x IS NOT NULL"
    )
    ids = []
    vectors = []
    filepaths = []
    for row in rows:
        blob = row['vector']
        vec = struct.unpack(f"{len(blob)//4}f", blob)
        ids.append(row['chunk_id'])
        vectors.append(vec)
        filepaths.append(row['filepath'])
    return ids, vectors, filepaths


def compute_edges(ids, vectors, filepaths, threshold, max_k):
    """Calcule les edges par cosine similarity avec filtrage par seuil."""
    import numpy as np

    X = np.array(vectors, dtype=np.float32)
    n = X.shape[0]
    print(f"Edges : {n} vecteurs, seuil={threshold}, max_k={max_k}")

    # Normalise pour cosine → dot product
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1
    X_norm = X / norms

    edges = []
    t0 = time.time()

    # Process par batch pour limiter la mémoire
    batch_size = 500
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        # Cosine similarity = dot product des vecteurs normalisés
        sims = X_norm[start:end] @ X_norm.T  # (batch, n)

        for i_local in range(end - start):
            i = start + i_local
            row_sims = sims[i_local]
            # Exclure self
            row_sims[i] = -1

            # Filtrer par seuil
            mask = row_sims >= threshold
            candidates = np.where(mask)[0]

            if len(candidates) == 0:
                continue

            # Top-K parmi les candidats
            if len(candidates) > max_k:
                top_idx = np.argsort(row_sims[candidates])[-max_k:]
                candidates = candidates[top_idx]

            for j in int(candidates) if isinstance(candidates, np.integer) else candidates:
                j = int(j)
                # Edge unidirectionnel (source < target pour dédupliquer)
                a, b = (i, j) if ids[i] < ids[j] else (j, i)
                edges.append((ids[a], ids[b], float(row_sims[j])))

    dt = time.time() - t0
    print(f"Calcul terminé en {dt:.1f}s")

    # Dédupliquer (les paires a,b peuvent apparaître 2 fois)
    seen = set()
    unique_edges = []
    for src, tgt, sim in edges:
        key = (src, tgt)
        if key not in seen:
            seen.add(key)
            unique_edges.append((src, tgt, sim))

    print(f"Edges uniques : {len(unique_edges)}")
    return unique_edges


def store_edges(edges):
    """Écrit les edges dans la DB."""
    # Vider la table
    brain_db.execute("DELETE FROM cosmos_edges")

    # Insert par batch
    batch_size = 200
    for i in range(0, len(edges), batch_size):
        batch = edges[i:i + batch_size]
        for src, tgt, sim in batch:
            brain_db.execute(
                "INSERT INTO cosmos_edges (source_id, target_id, similarity) VALUES (%s, %s, %s)",
                (src, tgt, round(sim, 4)),
            )

    # Dolt commit
    if brain_db.BACKEND == 'dolt':
        from db import _dolt_commit
        _dolt_commit(f"cosmos-edges: {len(edges)} liens sémantiques")

    print(f"Edges stockés : {len(edges)}")


def show_stats():
    """Affiche les stats des edges."""
    total = brain_db.count('cosmos_edges', '1=1')
    print(f"Edges totaux : {total}")
    if total > 0:
        row = brain_db.query_one(
            "SELECT MIN(similarity) as smin, MAX(similarity) as smax, "
            "AVG(similarity) as savg FROM cosmos_edges"
        )
        if row:
            print(f"Similarity : min={float(row['smin']):.3f} max={float(row['smax']):.3f} avg={float(row['savg']):.3f}")

        # Nodes connectés
        nodes = brain_db.query_one(
            "SELECT COUNT(DISTINCT source_id) + COUNT(DISTINCT target_id) as n FROM cosmos_edges"
        )
        if nodes:
            print(f"Nodes connectés : ~{int(nodes['n'])}")


def main():
    # Parse args
    threshold = DEFAULT_THRESHOLD
    max_k = DEFAULT_MAX_K

    args = sys.argv[1:]
    if "--threshold" in args:
        idx = args.index("--threshold")
        threshold = float(args[idx + 1])
    if "--max-k" in args:
        idx = args.index("--max-k")
        max_k = int(args[idx + 1])

    ensure_table()

    if "--stats" in args:
        show_stats()
        return

    ids, vectors, filepaths = load_vectors()
    if not vectors:
        print("Aucun vecteur trouvé")
        return

    edges = compute_edges(ids, vectors, filepaths, threshold, max_k)
    store_edges(edges)
    show_stats()


if __name__ == "__main__":
    main()
