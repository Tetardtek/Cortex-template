#!/usr/bin/env python3
"""Ce que la recherche garantit.

    python3 core/test_recherche.py                      # sans Ollama ni base
    python3 core/test_recherche.py --dolt ~/Dev/Brain   # + index réel, lecture seule

Le classement et l'alerte se testent **sans modèle et sans index** : ce sont des
fonctions de vecteurs et de mots. C'est le point de la refonte — l'ancien
`search.py` mêlait l'encodage, la base et le classement dans une seule fonction.
"""

from __future__ import annotations

import argparse
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.persistance import DOLT, SQLITE, Config, Depot     # noqa: E402
from core.modele import Encodeur                             # noqa: E402
from core.recherche import (                                 # noqa: E402
    DimensionsIncompatibles, Index, Recherche,
    alerte_requete, similarite, vecteur_depuis_blob,
)

_ok = _ko = 0

# Levé quand un service DEMANDÉ (`--dolt`, `--brain`) n'a pas répondu : la
# suite sort alors en 3 — « rien mesuré », distinct de 0 et de 1. Le lanceur
# (`core/tests.py`) la compte à part au lieu de l'additionner en silence.
_abstenu = False


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def refuse(nom: str, fn, exception) -> None:
    global _ok, _ko
    try:
        fn()
    except exception:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom} — rien n'a été refusé")


def vecteurs() -> None:
    print("\nLES VECTEURS, SANS MODÈLE NI BASE\n")

    verifie("deux vecteurs identiques valent 1",
            round(similarite([1.0, 0.0], [1.0, 0.0]), 6), 1.0)
    verifie("deux vecteurs orthogonaux valent 0",
            round(similarite([1.0, 0.0], [0.0, 1.0]), 6), 0.0)
    verifie("un vecteur nul ne divise pas par zéro",
            similarite([0.0, 0.0], [1.0, 1.0]), 0.0)

    # ⚠️ Le défaut le plus subtil de l'ancien moteur : zip() tronquait, et une
    # requête de 3 dimensions contre un index de 768 rendait un score plausible.
    refuse("des dimensions différentes sont REFUSÉES, pas tronquées",
           lambda: similarite([1.0, 0.0, 0.0], [1.0, 0.0]),
           DimensionsIncompatibles)

    blob = struct.pack("3f", 1.5, -2.0, 0.25)
    verifie("un blob se relit tel qu'il a été écrit",
            vecteur_depuis_blob(blob), [1.5, -2.0, 0.25])


def alertes() -> None:
    print("\nL'ALERTE PORTE SUR LA REQUÊTE, JAMAIS SUR LE SCORE —\n")

    verifie("un mot alerte", alerte_requete("démyélinisation") is not None, True)
    verifie("deux mots alertent", alerte_requete("le brain") is not None, True)
    verifie("quatre mots alertent encore",
            alerte_requete("comment marche le brain") is not None, True)
    verifie("six mots passent",
            alerte_requete("comment marche le brain de Kevin"), None)
    verifie("une longue requête passe",
            alerte_requete("expliquer le fonctionnement complet du moteur "
                           "de recherche sémantique du brain"), None)


def index_jetable() -> None:
    print("\nUN INDEX JETABLE — SANS OLLAMA\n")

    with tempfile.TemporaryDirectory(prefix="core-recherche-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "i.db"))
        depot.execute("CREATE TABLE embeddings (chunk_id TEXT, filepath TEXT, "
                      "title TEXT, chunk_text TEXT, vector BLOB, indexed INTEGER, "
                      "scope TEXT)")
        verifie("un index vide rend des métadonnées vides",
                Index(depot).charge()[0], [])

        # Un modèle qui RÉPOND, sur un index vide : la raison est l'index, pas
        # le modèle — et, là non plus, une requête courte ne la masque pas.
        class Repond(Encodeur):
            def encode(self, texte):
                return [1.0, 0.0]
        from core.recherche import INDEX_VIDE
        _, alerte_vide = Recherche(depot, Repond()).cherche("sessions")
        verifie("un index vide se dit, même sous une requête courte", alerte_vide, INDEX_VIDE)

        for i, v in enumerate([(1.0, 0.0), (0.0, 1.0)]):
            depot.execute(
                "INSERT INTO embeddings VALUES (%s,%s,%s,%s,%s,1,'public')",
                (f"c{i}", f"f{i}.md", f"t{i}", f"texte {i}", struct.pack("2f", *v)))

        meta, _ = Index(depot).charge()
        verifie("les deux chunks sont lus", len(meta), 2)
        verifie("le chemin est rendu", meta[0]["chemin"], "f0.md")

        # Un encodeur qui ne répond pas : la recherche doit le DIRE, pas rendre
        # une liste vide qu'on prendrait pour « aucun résultat ».
        muet = Encodeur(url="http://127.0.0.1:1")
        resultats, alerte = Recherche(depot, muet).cherche(
            "une requête assez longue pour ne pas alerter sur sa taille")
        verifie("sans modèle, aucun résultat", resultats, [])
        verifie("et la raison est dite",
                alerte is not None and "injoignable" in alerte, True)

        # Une requête COURTE ne masque pas la panne : l'avis « reformule » était
        # rendu à la place, et la panne passait pour une question mal posée
        #.
        from core.recherche import INJOIGNABLE, INDEX_VIDE
        _, alerte_courte = Recherche(depot, muet).cherche("sessions")
        verifie("une requête courte ne masque pas la panne", alerte_courte, INJOIGNABLE)


def normes_gardees() -> None:
    """Ce que garantit : les normes se gardent, et rien ne change.

    Deux choses à prouver, et la seconde compte plus que la première : que le
    cache serve, et que **le résultat soit le même**. Une optimisation qui
    change le classement n'est pas une optimisation.
    """
    print("\nLES NORMES DE L'INDEX — GARDÉES, PAS RECALCULÉES\n")

    try:
        import numpy as np
    except ImportError:
        print("  ⏭  numpy absent — ce contrôle ne mesure rien sans lui.")
        return

    with tempfile.TemporaryDirectory(prefix="core-normes-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "n.db"))
        depot.execute("CREATE TABLE embeddings (chunk_id TEXT, filepath TEXT, "
                      "title TEXT, chunk_text TEXT, vector BLOB, indexed INTEGER, "
                      "scope TEXT, updated_at TEXT)")
        # Des normes VOLONTAIREMENT différentes : si le calcul était faux ou le
        # cache mal invalidé, des vecteurs de même norme le masqueraient.
        vecteurs = [(3.0, 4.0), (1.0, 0.0), (0.0, 12.0)]     # normes 5, 1, 12
        for i, v in enumerate(vecteurs):
            depot.execute(
                "INSERT INTO embeddings VALUES (%s,%s,%s,%s,%s,1,'public','2026-01-01')",
                (f"c{i}", f"f{i}.md", f"t{i}", f"texte {i}", struct.pack("2f", *v)))

        index = Index(depot)
        meta, matrice = index.charge()
        verifie("l'index jetable se charge", len(meta), 3)

        attendues = [5.0, 1.0, 12.0]
        normes = index.normes()
        verifie("les normes sont justes",
                [round(float(x), 3) for x in normes], attendues)

        # Le cache SERT : le second appel rend le même objet, pas un recalcul.
        verifie("le second appel ne recalcule pas",
                index.normes() is normes, True)

        # Et il vise ce qu'il faut : les normes viennent bien de CET index.
        verifie("autant de normes que de vecteurs", len(normes), matrice.shape[0])

        # ── Le résultat ne change pas. C'est la garantie qui compte.
        q = np.asarray([1.0, 0.0], dtype=np.float32)
        avec = np.divide(matrice @ q, normes * float(np.linalg.norm(q)),
                         out=np.zeros(3, dtype=np.float32),
                         where=(normes * float(np.linalg.norm(q))) != 0)
        recalc = np.linalg.norm(matrice, axis=1) * float(np.linalg.norm(q))
        sans = np.divide(matrice @ q, recalc,
                         out=np.zeros(3, dtype=np.float32), where=recalc != 0)
        verifie("les scores sont identiques au recalcul",
                bool(np.allclose(avec, sans, atol=1e-6)), True)
        verifie("et le classement aussi",
                list(np.argsort(-avec)), list(np.argsort(-sans)))

        # ── L'invalidation : une écriture doit périmer les normes AVEC la
        # matrice. Sans ça, un index qui grandit servirait d'anciennes normes
        # sur de nouveaux vecteurs — un score faux, jamais une erreur.
        depot.execute(
            "INSERT INTO embeddings VALUES (%s,%s,%s,%s,%s,1,'public','2026-06-06')",
            ("c3", "f3.md", "t3", "texte 3", struct.pack("2f", 0.0, 7.0)))
        meta2, matrice2 = index.charge()
        normes2 = index.normes()
        verifie("une écriture périme les normes", normes2 is normes, False)
        verifie("et les nouvelles sont justes",
                [round(float(x), 3) for x in normes2], [5.0, 1.0, 12.0, 7.0])
        verifie("autant de normes que de vecteurs, après écriture",
                len(normes2), matrice2.shape[0])
        depot.ferme()


def index_reel() -> None:
    print("\nL'INDEX RÉEL DU BRAIN — LECTURE SEULE\n")

    depot = Depot(Config(backend=DOLT))
    try:
        meta, matrice = Index(depot).charge()
    except Exception as exc:                               # noqa: BLE001
        # ⚠️ Ne PAS dire « injoignable » : ce message a masqué une erreur de
        # syntaxe SQL pendant tout un essai. Un mot réservé non échappé s'était
        # déguisé en panne de service. Le sens d'une erreur compte autant que
        # son existence — celle qui rassure ne déclenche aucune vérification.
        print(f"  ⏭  l'index réel n'a pas pu être lu — {type(exc).__name__} : "
              f"{str(exc)[:90]}")
        print("     Abstention, pas un vert. Si c'est une erreur de requête,")
        print("     c'est un défaut du CORE, pas du service.\n")
        global _abstenu
        _abstenu = True
        return

    verifie("l'index réel se charge", len(meta) > 0, True)
    print(f"  ℹ️  {len(meta)} chunks indexés"
          f"{f' · matrice {matrice.shape}' if matrice is not None else ' · sans numpy'}")
    if matrice is not None:
        verifie("autant de vecteurs que de métadonnées",
                matrice.shape[0], len(meta))
        print(f"  ℹ️  {matrice.shape[1]} dimensions — le modèle d'embedding")
    depot.ferme()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dolt", type=Path, metavar="BRAIN")
    args = p.parse_args()

    vecteurs()
    alertes()
    index_jetable()
    normes_gardees()
    if args.dolt:
        index_reel()

    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
    return 1 if _ko else (3 if _abstenu else 0)


if __name__ == "__main__":
    sys.exit(main())
