#!/usr/bin/env python3
"""La boucle complète : indexer de vrais fichiers, puis les retrouver.

    python3 core/test_boucle.py --brain ~/Dev/Brain

Les cinq modules qui produisent quelque chose sont enchaînés pour de bon :
`persistance` ouvre une base **jetable**, `indexation` découpe et encode de
**vrais fichiers du brain**, `recherche` les retrouve, `zones` dit où ils vivent.

C'est le seul test qui prouve que le CORE **fonctionne**, par opposition à
« chaque morceau tient ses promesses ». Les six modules peuvent être justes
séparément et ne pas s'emboîter.

⚠️ **Rien n'est écrit dans le brain.** Ses fichiers sont lus, l'index est
construit dans un fichier temporaire détruit à la sortie. Le modèle est
sollicité pour de vrai — c'est ce qui rend ce test lent, et concluant.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.indexation import Indexeur, decoupe                # noqa: E402
from core.persistance import SQLITE, Config, Depot           # noqa: E402
from core.recherche import Encodeur, Recherche               # noqa: E402
from core.zones import KERNEL, Registre                      # noqa: E402

_ok = _ko = 0

# Levé quand un service DEMANDÉ (`--dolt`, `--brain`) n'a pas répondu : la
# suite sort alors en 3 — « rien mesuré », distinct de 0 et de 1. Le lanceur
# (`core/tests.py`) la compte à part au lieu de l'additionner en silence.
_abstenu = False
SCHEMA = """
CREATE TABLE embeddings (
    chunk_id TEXT PRIMARY KEY, filepath TEXT, title TEXT, chunk_text TEXT,
    vector BLOB, model TEXT, indexed INTEGER, scope TEXT,
    content_hash TEXT, created_at TEXT, updated_at TEXT)
"""

# De vrais fichiers du brain, choisis pour parler de sujets distincts : si la
# recherche les confond, c'est qu'elle ne discrimine pas.
FICHIERS = [
    ("KERNEL.md", "invariant"),
    ("PATHS.md", "invariant"),
    ("agents/vps.md", "programme"),
    ("agents/testing.md", "programme"),
    ("agents/mail.md", "programme"),
]


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    brain = args.brain.expanduser().resolve()

    encodeur = Encodeur()
    if encodeur.encode("essai de disponibilité du modèle") is None:
        print("\n  ⏭  le modèle d'embedding est injoignable — rien mesuré.")
        print("     Abstention, pas un vert.\n")
        print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
        return 3

    print("\nLA BOUCLE COMPLÈTE — de vrais fichiers, une base jetable\n")

    with tempfile.TemporaryDirectory(prefix="core-boucle-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "index.db"))
        depot.execute(SCHEMA)

        # ── 1. Découper de vrais fichiers ───────────────────────────────────
        chunks, presents = [], []
        for relatif, _ in FICHIERS:
            fichier = brain / relatif
            if not fichier.is_file():
                continue
            presents.append(relatif)
            chunks.extend(decoupe(fichier.read_text(errors="replace"), relatif))

        verifie("les fichiers du brain sont lus", len(presents) >= 3, True)
        verifie("ils produisent des chunks", len(chunks) > 0, True)
        print(f"  ℹ️  {len(presents)} fichiers → {len(chunks)} chunks")

        # ── 2. Les zones, pendant qu'on y est ───────────────────────────────
        registre = Registre(niveaux=dict(FICHIERS))
        verifie("un `invariant` est en zone kernel",
                registre.zone("KERNEL.md"), KERNEL)
        verifie("un `programme` aussi", registre.zone("agents/vps.md"), KERNEL)

        # ── 3. Indexer pour de vrai ─────────────────────────────────────────
        debut = time.perf_counter()
        rapport = Indexeur(depot, encodeur).indexe(chunks)
        secondes = time.perf_counter() - debut

        verifie("tout est encodé sans échec", rapport.echecs, 0)
        verifie("la base porte les chunks", depot.count("embeddings"), rapport.encodes)
        print(f"  ℹ️  {rapport} en {secondes:.1f}s")

        # ── 4. Retrouver ────────────────────────────────────────────────────
        recherche = Recherche(depot, encodeur)

        essais = [
            ("comment configurer un vhost apache et un certificat ssl", "vps"),
            ("ecrire des tests unitaires avec vitest et mesurer la couverture", "testing"),
            ("configurer les enregistrements dns spf et dkim pour le mail", "mail"),
        ]
        for requete, attendu in essais:
            resultats, alerte = recherche.cherche(requete, combien=3)
            if not resultats:
                verifie(f"« {attendu} » est retrouvé", "aucun résultat", attendu)
                continue
            chemins = [r.chemin for r in resultats]
            trouve = any(attendu in c for c in chemins)
            verifie(f"« {attendu} » est dans les 3 premiers",
                    trouve, True)
            if not trouve:
                print(f"       rendus : {chemins}")

        # ── 5. Ce que la recherche refuse de laisser croire ─────────────────
        _, alerte = recherche.cherche("vps")
        verifie("une requête d'un mot est signalée", alerte is not None, True)

        premiers, _ = recherche.cherche(
            "comment configurer un vhost apache et un certificat ssl", combien=1)
        verifie("le meilleur résultat porte un score", 
                bool(premiers) and premiers[0].score > 0, True)
        if premiers:
            print(f"  ℹ️  meilleur score : {premiers[0].score:.3f} sur "
                  f"{premiers[0].chemin}")

    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
    return 1 if _ko else (3 if _abstenu else 0)


if __name__ == "__main__":
    sys.exit(main())
