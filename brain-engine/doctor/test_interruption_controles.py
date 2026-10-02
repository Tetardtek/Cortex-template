#!/usr/bin/env python3
"""Un contrôle tué en cours de route nettoie-t-il derrière lui ?

Le pendant de `test_concurrence_controles.py`. Celui-là éprouve la duplication ;
celui-ci éprouve **l'interruption**, l'autre moitié du trou.

Le 04/09, trois passages de `brain doctor` tués par un `timeout` ont laissé un
abri de témoin sur le disque. Un `git add -A` l'a commité, le témoin s'est mis à
s'abstenir en refusant de s'installer sur un reste, et il a fallu **compter les
lignes du rapport** pour s'en apercevoir. La cause tient en une phrase :
`finally` ne s'exécute pas sur SIGTERM, et SIGTERM est ce que `timeout` envoie.

Ce que ce témoin vérifie, pour chaque contrôle qui **s'installe** quelque part :

    on le tue en pleine exécution, et rien ne doit rester —
    ni abri sur le disque, ni verrou dans la base.

Ce qu'il ne vérifie pas, et il faut le dire : qu'un contrôle interrompu rende un
verdict juste. Un contrôle tué n'a pas de verdict — c'est déjà ce que dit le
`trap` de `kernel-isolation-check.sh`. Ici on ne juge que **la trace**.

    python3 tools/test_interruption_controles.py --brain ~/Dev/Brain

Sortie 1 si un contrôle laisse quelque chose derrière lui.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

OUTILS = Path(__file__).resolve().parent

# (nom, outil, motif d'abri, verrou attendu dans `locks`). Seuls ceux qui
# s'installent quelque part.
EPROUVES = [
    ("témoin du corpus",           "test_index_corpus.py",
     "workspace/_temoin-my34*", "_my34-exclusif.md"),
    ("discipline d'écriture Dolt", "test_dolt_discipline.py",
     None, "_my32-exclusif.md"),
]

# On ne coupe pas après un temps DEVINÉ : on coupe dès que la trace est là.
# Un délai fixe n'attraperait jamais un contrôle de 0,47 s, et couperait un
# contrôle de 8 s avant qu'il ait rien posé. Attendre le verrou rend la mesure
# déterministe — c'est la différence entre éprouver et espérer.
ATTENTE_MAX = 30.0
PAS = 0.05


def locks_temoins(brain: Path) -> list[str]:
    """Les verrous que les témoins posent, vus depuis la base."""
    moteur = brain / "brain-engine"
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import db\n"
        "print('\\n'.join(str(r['filepath']) for r in "
        "db.query(\"SELECT filepath FROM locks\")))\n" % str(moteur)
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [l for l in r.stdout.splitlines() if l.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    brain = args.brain.expanduser().resolve()

    print("\nINTERRUPTION — un contrôle tué laisse-t-il une trace ?\n")

    avant = set(locks_temoins(brain))
    echecs = []

    for nom, outil, motif, verrou in EPROUVES:
        chemin = OUTILS / outil
        if not chemin.is_file():
            print(f"  ⏭  {nom:30} outil absent")
            continue

        proc = subprocess.Popen(
            [sys.executable, str(chemin), "--brain", str(brain)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Attendre que le contrôle se soit INSTALLÉ, puis couper.
        debut = time.time()
        installe = False
        while time.time() - debut < ATTENTE_MAX:
            if verrou and verrou in locks_temoins(brain):
                installe = True
                break
            if motif and any(brain.glob(motif)):
                installe = True
                break
            if proc.poll() is not None:
                break
            time.sleep(PAS)

        if not installe:
            fini = proc.poll() is not None
            print(f"  ⏭  {nom:30} "
                  + ("fini sans rien poser" if fini else "rien posé en 30 s")
                  + " — rien à conclure")
            if not fini:
                proc.terminate(); proc.wait(timeout=10)
            continue
        proc.terminate()                       # SIGTERM, comme `timeout`
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=10)

        time.sleep(0.5)
        restes = []
        if motif:
            restes += [str(x.relative_to(brain)) for x in brain.glob(motif)]
        nouveaux = set(locks_temoins(brain)) - avant
        restes += sorted(nouveaux)

        etat = "❌" if restes else "✅"
        print(f"  {etat} {nom:30} {', '.join(restes) if restes else 'rien ne reste'}")
        if restes:
            echecs.append(nom)
            # On ne laisse pas le témoin salir le brain qu'il éprouve.
            for x in (brain.glob(motif) if motif else []):
                subprocess.run(["rm", "-rf", str(x)])

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} contrôle(s) laissent une trace : "
              f"{', '.join(echecs)}")
        print("     `finally` ne s'exécute pas sur SIGTERM. Convertir le signal")
        print("     en exception suffit — c'est ce que fait le témoin du corpus")
        print("     depuis, et le `trap … EXIT TERM INT` côté shell.\n")
        return 1
    print("  ✅ rien ne survit à l'interruption\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
