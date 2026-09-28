#!/usr/bin/env python3
"""
brain-engine/umap-positions.py — Calcul positions UMAP 3D pour Cosmos view
Lit les vecteurs 768D depuis la DB, projette en 3D, stocke x,y,z.

Usage :
  python3 brain-engine/umap-positions.py            → calcul complet
  python3 brain-engine/umap-positions.py --stats     → stats des positions

Cron : lancer après embed.py (30 */6 * * * ou à la demande depuis un dashboard)
"""

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db as brain_db


def ensure_columns():
    """Ajoute les colonnes x, y, z si absentes (Dolt : ALTER TABLE)."""
    if brain_db.BACKEND == 'dolt':
        # Dolt : vérifier via information_schema
        for col in ("x", "y", "z"):
            row = brain_db.query_one(
                "SELECT COUNT(*) as n FROM information_schema.columns "
                "WHERE table_name = 'embeddings' AND column_name = %s",
                (col,))
            if row and int(row['n']) == 0:
                brain_db.execute(f"ALTER TABLE embeddings ADD COLUMN {col} REAL")
    else:
        # SQLite : PRAGMA
        conn = brain_db.get_raw_connection()
        existing = {row[1] for row in conn.execute("PRAGMA table_info(embeddings)")}
        for col in ("x", "y", "z"):
            if col not in existing:
                conn.execute(f"ALTER TABLE embeddings ADD COLUMN {col} REAL")
        conn.commit()
        conn.close()


def load_vectors():
    """Charge chunk_id + vecteurs depuis la DB."""
    rows = brain_db.query(
        "SELECT chunk_id, `vector` FROM embeddings WHERE `vector` IS NOT NULL"
    )
    ids = []
    vectors = []
    for row in rows:
        blob = row['vector']
        vec = struct.unpack(f"{len(blob)//4}f", blob)
        ids.append(row['chunk_id'])
        vectors.append(vec)
    return ids, vectors


def compute_umap_3d(vectors):
    """Projette 768D → 3D via UMAP."""
    import numpy as np
    import umap

    X = np.array(vectors, dtype=np.float32)
    print(f"UMAP : {X.shape[0]} vecteurs × {X.shape[1]}D → 3D")

    reducer = umap.UMAP(
        n_components=3,
        n_neighbors=15,
        min_dist=0.1,
        metric="cosine",
        random_state=42,
    )
    t0 = time.time()
    coords = reducer.fit_transform(X)
    dt = time.time() - t0
    print(f"UMAP terminé en {dt:.1f}s")

    # Normalize to [-1, 1] for rendering
    for dim in range(3):
        col = coords[:, dim]
        mn, mx = col.min(), col.max()
        if mx - mn > 0:
            coords[:, dim] = 2 * (col - mn) / (mx - mn) - 1

    return coords


def store_positions(ids, coords):
    """Écrit x, y, z dans la DB."""
    for i, cid in enumerate(ids):
        brain_db.execute(
            "UPDATE embeddings SET x = %s, y = %s, z = %s WHERE chunk_id = %s",
            (float(coords[i][0]), float(coords[i][1]), float(coords[i][2]), cid),
        )
    # Dolt commit
    if brain_db.BACKEND == 'dolt':
        from db import _dolt_commit
        _dolt_commit(f"umap: {len(ids)} positions 3D")
    print(f"Positions stockées : {len(ids)} chunks")


def show_stats():
    """Affiche les stats des positions."""
    total = brain_db.count('embeddings', '`vector` IS NOT NULL')
    positioned = brain_db.count('embeddings', 'x IS NOT NULL')
    print(f"Embeddings avec vecteur : {total}")
    print(f"Embeddings avec position : {positioned}")
    if positioned > 0:
        row = brain_db.query_one(
            "SELECT MIN(x) as xmin, MAX(x) as xmax, MIN(y) as ymin, MAX(y) as ymax, "
            "MIN(z) as zmin, MAX(z) as zmax FROM embeddings WHERE x IS NOT NULL"
        )
        if row:
            print(f"Ranges : x[{float(row['xmin']):.2f}, {float(row['xmax']):.2f}] "
                  f"y[{float(row['ymin']):.2f}, {float(row['ymax']):.2f}] "
                  f"z[{float(row['zmin']):.2f}, {float(row['zmax']):.2f}]")


def main():
    ensure_columns()

    if "--stats" in sys.argv:
        show_stats()
        return

    ids, vectors = load_vectors()
    if not vectors:
        print("Aucun vecteur trouvé")
        return

    coords = compute_umap_3d(vectors)
    store_positions(ids, coords)
    show_stats()


if __name__ == "__main__":
    main()
