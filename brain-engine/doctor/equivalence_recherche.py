#!/usr/bin/env python3
"""Les deux chemins de recherche du CORE voient-ils la même chose ? —.

🔴 **Ce contrôle a rétréci le 11/09, et c'est une bonne nouvelle.**

Il comparait `search.search()` au CORE pour autoriser le branchement. Depuis que
`search.py` **délègue** à `core.recherche`, cette comparaison oppose le CORE à
lui-même : elle serait verte quoi qu'il arrive, sans rien mesurer. Un contrôle
tautologique est pire qu'absent — il occupe la place d'une garde et rassure.

La preuve a été faite une fois, au moment où elle comptait : l'ancienne version
de `search.py`, relue depuis git, et la nouvelle, côte à côte sur huit
requêtes — **mêmes rangs, mêmes champs, écart de score exactement 0.0**. Elle
est consignée dans le commit du branchement ; elle n'a pas à être rejouée tous
les jours contre elle-même.

Ce qui reste ci-dessous mesure encore quelque chose : `cherche()` calcule par
**numpy** quand la matrice est là, et retombe sur `similarite()` en **Python
pur** sinon. Le second n'est exercé par rien d'autre.

⚠️ **Correction du 11/09** — j'ai d'abord justifié ce contrôle par « un fork en
tier free n'a pas forcément numpy ». C'est faux deux fois : « tier free »
désigne un fork **sans clé API** (`brain-setup.sh` : *« tier free = aucune clé
requise »*), et le template **déclare** `numpy>=1.26.0` dans
`brain-engine/requirements.txt`. Ce repli protège donc une installation où
numpy **manque ou a échoué**, pas un mode de déploiement. C'est plus étroit, et
ça reste une raison de l'éprouver — un chemin que rien n'exerce est un chemin
dont on ignore s'il rend la même chose.

Le pendant de `equivalence_decoupage.py`, sur l'autre moitié du chemin. Prouver
que les deux **indexent** pareil ne dit rien de ce qu'ils **retrouvent** : même
index, deux implémentations de la similarité, et un classement peut diverger sur
un `zip()` tronqué, un tri instable, un filtre de scope appliqué ailleurs.

    python3 tools/equivalence_recherche.py --brain ~/Dev/Brain

Mesuré le 11/09 : **12 requêtes, top 8, même classement ET mêmes scores.** Plus
bas encore, sur 500 paires de vecteurs réels tirés de la base, l'écart maximal
de similarité est **exactement 0.0** — pas « négligeable », nul.

── Ce qu'il compare, et pourquoi les scores comptent ───────────────────────

L'ordre seul ne suffit pas. Deux implémentations peuvent classer pareil avec des
scores légèrement différents — et le jour où deux passages sont à 0,001 près,
l'ordre bascule. Comparer les scores attrape la divergence **avant** qu'elle ne
change un résultat.

── Il s'abstient plutôt que de mentir ──────────────────────────────────────

La recherche encode la requête par Ollama. S'il ne répond pas, les deux côtés
rendent vide — et « identiques » serait vrai sans rien mesurer. Le contrôle le
déclare abstenu.

── Une différence assumée, et elle va dans le bon sens ─────────────────────

`core.recherche.similarite` **lève** `DimensionsIncompatibles` quand les
longueurs diffèrent, là où `search.cosine_sim` laisse `zip()` tronquer en
silence — ce qui laissait passer un index encodé par un autre modèle. Ce n'est
pas une divergence de résultat : sur des vecteurs de même dimension, les deux
rendent le même flottant, au bit près.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Des requetes VARIEES et fixes : vocabulaire du brain, phrases courtes et
# longues, termes techniques et prose. Fixes parce qu'un contrôle qui tire au
# hasard ne se compare pas a lui-meme d'une fois sur l'autre.
REQUETES = [
    "garde de zone", "sauvegarde dolt", "contrat des capacites", "claim BSI",
    "indexation des chunks", "frontmatter yaml", "registre des secrets",
    "myeline core briques", "handoff de session", "politique de corpus",
    "verrou de fichier entre machines", "scope kernel invariant",
]
SCOPES = ["public", "work", "instance", "satellite"]


def main() -> int:
    p = argparse.ArgumentParser(description="Le CORE cherche-t-il comme search.py ?")
    p.add_argument("--brain", required=True, type=Path)
    p.add_argument("--top", type=int, default=8)
    a = p.parse_args()
    racine = a.brain.expanduser().resolve()
    moteur = racine / "brain-engine"

    if not (moteur / "search.py").is_file():
        print("⏭️  SKIP brain-engine/search.py introuvable.", file=sys.stderr)
        return 0

    sys.path.insert(0, str(moteur))
    sys.path.insert(0, str(RACINE))
    try:
        import search
        from core.persistance import Config, Depot, DOLT, SQLITE
        from core.recherche import Recherche
        import db as db_instance
    except Exception as exc:                                   # noqa: BLE001
        print(f"⏭️  SKIP chargement impossible : {type(exc).__name__} — {exc}",
              file=sys.stderr)
        return 0

    # Le CORE ne devine pas ou vivent les donnees : on lui DONNE la
    # configuration de l'instance, lue dans son propre module de connexion.
    backend = getattr(db_instance, "BACKEND", "dolt")
    if backend == "dolt":
        cfg = Config(backend=DOLT,
                     hote=getattr(db_instance, "DOLT_HOST", "127.0.0.1"),
                     port=int(getattr(db_instance, "DOLT_PORT", 3307)),
                     utilisateur=getattr(db_instance, "DOLT_USER", "root"),
                     base=getattr(db_instance, "DOLT_DB", "brain-dolt"))
    else:
        chemin = Path(getattr(db_instance, "DB_PATH", racine / "brain.db"))
        if not chemin.is_file():
            print(f"⏭️  SKIP base SQLite absente ({chemin}).", file=sys.stderr)
            return 0
        cfg = Config(backend=SQLITE, chemin=chemin)

    try:
        depot = Depot(cfg)
    except Exception as exc:                                   # noqa: BLE001
        print(f"⏭️  SKIP base injoignable : {type(exc).__name__} — {exc}",
              file=sys.stderr)
        return 0

    # ── Les DEUX chemins du CORE ────────────────────────────────────────────
    #
    # `Recherche.cherche` calcule par numpy quand la matrice est la, et retombe
    # sur `similarite()` en Python pur sinon. Le second n'est jamais exerce ici
    # — verifie le 11/09 en sabotant `similarite` : le controle restait VERT.
    #
    # Un chemin de repli que rien n'exerce est un chemin dont on ignore s'il
    # rend la meme chose. Et il compte : un fork en tier free n'a pas forcement
    # numpy, et c'est SA recherche.
    import builtins
    vrai_import = builtins.__import__

    def sans_numpy(nom, *args, **kw):
        if nom == "numpy":
            raise ImportError("numpy rendu absent par le contrôle")
        return vrai_import(nom, *args, **kw)

    divergents = []
    try:
        depot2 = Depot(cfg)
        r_np = Recherche(depot2)
        avec = {q: [(x.chunk_id, x.score)
                    for x in r_np.cherche(q, combien=a.top, scopes=SCOPES)[0]]
                for q in REQUETES[:4]}
        depot2.ferme()

        builtins.__import__ = sans_numpy
        depot3 = Depot(cfg)
        r_pur = Recherche(depot3)
        sans = {q: [(x.chunk_id, x.score)
                    for x in r_pur.cherche(q, combien=a.top, scopes=SCOPES)[0]]
                for q in REQUETES[:4]}
        depot3.ferme()
    except Exception as exc:                                   # noqa: BLE001
        print(f"  ⏭️  chemin Python pur non éprouvé : {type(exc).__name__} — {exc}")
        avec = sans = {}
    finally:
        builtins.__import__ = vrai_import

    # L'ORDRE est exige strictement ; les SCORES a une tolerance.
    #
    # numpy calcule en float32, le Python pur en float64 : un ecart existe par
    # construction. Mesure le 11/09 sur 4 requetes en top 8 : **1,5e-07 au
    # maximum**, ordre identique. Exiger l'egalite exacte ferait rougir le
    # controle sur une propriete de l'arithmetique, pas sur un defaut — et un
    # controle qui rougit sur ce qu'on ne peut pas corriger finit ignore.
    #
    # 1e-5 est trois ordres de grandeur au-dessus de l'ecart observe, et trois
    # ordres en dessous de ce qui ferait basculer un classement.
    TOLERANCE = 1e-5
    for q in avec:
        ids_np = [x[0] for x in avec[q]]
        ids_pur = [x[0] for x in sans[q]]
        if ids_np != ids_pur:
            divergents.append((q, "classement", avec[q], sans[q]))
            continue
        pires = [abs(x[1] - y[1]) for x, y in zip(avec[q], sans[q])]
        if pires and max(pires) > TOLERANCE:
            divergents.append((q, f"scores (ecart {max(pires):.2e})",
                               avec[q], sans[q]))
    if avec:
        print(f"  {'✅' if not divergents else '❌'} {len(avec)} requête(s) par les "
              f"DEUX chemins du CORE — numpy et Python pur")
    if divergents:
        for q, quoi, x, y in divergents[:3]:
            print(f"     {q!r} — {quoi}\n       numpy : {x[:3]}\n       pur   : {y[:3]}",
                  file=sys.stderr)
        print(f"\n   Le repli sans numpy ne cherche pas comme le chemin nominal.\n"
              f"   Ce repli sert une installation où numpy manque ou a échoué "
              f"— pas\n   un mode de déploiement : le template le déclare "
              f"(`requirements.txt`).", file=sys.stderr)
        return 1

    print(f"\n✅ les deux chemins du CORE rendent le même classement")
    return 0


if __name__ == "__main__":
    sys.exit(main())
