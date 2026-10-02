#!/usr/bin/env python3
"""Tous les tests du CORE, en un passage.

    python3 core/tests.py                      # ce qui ne demande aucun service
    python3 core/tests.py --brain ~/Dev/Brain  # + la base et le modèle réels

Sans `--brain`, rien n'est requis : ni base, ni modèle, ni réseau. C'est la
propriété que le rapatriement a cherchée — l'ancien moteur ne pouvait pas être
testé sans sa base.

Avec `--brain`, trois tests de plus interrogent la base vivante **en lecture
seule**, et `test_boucle` sollicite le modèle pour de vrai.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent

# (fichier, a besoin du brain ?)
SUITES = [
    ("test_briques.py", "--brain"),
    ("test_persistance.py", "--dolt"),
    ("test_traces.py", "--dolt"),
    ("test_bsi.py", False),
    ("test_recherche.py", "--dolt"),
    ("test_indexation.py", False),
    ("test_zones.py", "--brain"),
    ("test_boucle.py", "requis"),
]

COMPTE = re.compile(r"(\d+) garantie\(s\) tenue\(s\), (\d+) manquée")
# La ligne qu'une sous-suite imprime quand elle s'abstient : sa raison, relayée telle quelle.
ABSTENTION = re.compile(r"ABSTENTION — (.+)")


def pourquoi_abstenue(exc: BaseException) -> str:
    """Ce qu'une sous-suite dit quand la base vivante ne se lit pas. Pur.

    Le sens d'une erreur compte autant que son existence. Le 27/09 puis le 2/10,
    un Python sans `pymysql` s'est annoncé « dolt sql-server injoignable », et
    l'on a cherché un service en panne : le service allait bien, c'était le
    Python. Seule une erreur de connexion dit « injoignable »."""
    if isinstance(exc, ModuleNotFoundError):
        return (f"ce Python n'a pas le module « {exc.name} » ({sys.executable}) — "
                f"le doctor lance la suite avec le Python du moteur")
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return f"dolt sql-server injoignable ({type(exc).__name__})"
    return f"{type(exc).__name__} : {str(exc)[:90]}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path,
                   help="ajoute les tests qui lisent la base et le modèle réels")
    args = p.parse_args()
    brain = args.brain.expanduser().resolve() if args.brain else None

    print("\nLES TESTS DU CORE\n")
    tenues = manquees = 0
    echecs: list[str] = []
    # Une sous-suite qui sort en 3 n'a RIEN mesuré de ce qu'on lui demandait
    # (un service injoignable). Additionner ses garanties sans le dire donnait
    # « 230 tenues — le CORE tient toutes ses promesses » avec 17 garanties non
    # mesurées (27/09) ; le contrôle des chiffres en concluait que la DOC était
    # fausse. Elle est désormais comptée à part.
    abstenues: list[str] = []

    for fichier, besoin in SUITES:
        if besoin == "requis" and not brain:
            print(f"  ⏭  {fichier:<22} demande --brain")
            continue
        commande = [sys.executable, str(ICI / fichier)]
        if brain and besoin in ("--dolt", "--brain", "requis"):
            commande += [besoin if besoin.startswith("--") else "--brain", str(brain)]

        r = subprocess.run(commande, capture_output=True, text=True,
                           cwd=str(RACINE), timeout=900)
        m = COMPTE.search(r.stdout)
        if not m:
            manquees += 1
            echecs.append(fichier)
            fin = (r.stdout + r.stderr).strip().splitlines()
            print(f"  ❌ {fichier:<22} illisible — {fin[-1][:46] if fin else '?'}")
            continue
        ok, ko = int(m.group(1)), int(m.group(2))
        tenues += ok
        manquees += ko
        if r.returncode == 3 and not ko:
            abstenues.append(fichier)
            raison = ABSTENTION.search(r.stdout)
            print(f"  ⏭  {fichier:<22} {ok:>3} tenue(s) — ABSTENUE : "
                  + (raison.group(1).strip() if raison else "un service demandé n'a pas répondu"))
            continue
        if ko or r.returncode:
            echecs.append(fichier)
        etat = "✅" if not ko and not r.returncode else "❌"
        print(f"  {etat} {fichier:<22} {ok:>3} tenue(s)"
              + (f", {ko} manquée(s)" if ko else ""))

    print(f"\n  {tenues} garanties tenues · {manquees} manquées"
          + (f" · {len(abstenues)} sous-suite(s) abstenue(s)" if abstenues else ""))
    if abstenues and brain:
        # On a DEMANDÉ la base (--brain) : ne pas l'avoir est un échec, pas un vert.
        print(f"  ❌ abstenue(s) alors que --brain était demandé : {', '.join(abstenues)}")
        print("     Le compte ci-dessus est INCOMPLET — ce n'est pas une mesure.\n")
        return 1
    if echecs:
        print(f"  ❌ {', '.join(echecs)}\n")
        return 1
    print("  ✅ le CORE tient toutes ses promesses\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
