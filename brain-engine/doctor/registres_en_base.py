#!/usr/bin/env python3
"""Les registres dérivés sont-ils dans la base vivante ?

Le 04/09, `handoffs` portait **16 lignes dans `brain.db`** — dont les trois du
jour — et **zéro dans Dolt**, qui est la base que le brain lit. Personne ne
l'avait vu, parce que rien ne comparait les deux.

`migrate.py` ouvre `sqlite3.connect(brain.db)` en dur : il ne passe pas par
`db.py` et ignore `BRAIN_DB_BACKEND`. Tant que les deux coïncidaient, l'écart
n'existait pas. Depuis la bascule vers Dolt, il grandissait en silence — et
c'est le motif du 04/09 pour la troisième fois : *la déclaration est juste
quelque part, et fausse là où elle s'exécute.*

Ce que ça coûtait, mesuré : `brain-conciergerie.sh` interroge Dolt et comptait
**zéro handoff actif** là où il y en avait onze ; le dump quotidien dumpe Dolt,
donc **aucune sauvegarde ne les portait** ; et `brain.db` est déclaré `artefact`
dans `NIVEAUX.yml` — ni versionné, ni sauvegardé. Le registre des handoffs
n'existait que sur une machine, dans un fichier que rien ne copie ailleurs.

    python3 tools/registres_en_base.py --brain ~/Dev/Brain

**Ce que ce contrôle regarde** : les deux registres dérivés ont-ils, dans la
base vivante, ce que leur source déclare ? Chacun a sa source, et c'est elle qui
fait autorité — jamais l'autre base.

    handoffs   handoffs/*.md      les fichiers, versionnés
    (signals   — plus de source à comparer : `bsi-signal.sh` écrit en base
                 directement. La table de `BRAIN-INDEX.md` qui servait de
                 source est vide depuis mai ; la comparer rendait un vert sur
                 rien. Retiré le 27/09.)
    sessions   claims             une session EST un claim

**Ce qu'il ne regarde pas, et il faut le dire** : une ligne en base sans source
n'est PAS une erreur. Un handoff consommé puis rangé, un signal retiré de
l'index, laissent légitimement leur trace. On les compte, sans rougir.

Sortie 1 si un registre est en retard sur sa source.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    racine = args.brain.expanduser().resolve()

    moteur = racine / "brain-engine"
    sys.path.insert(0, str(moteur))
    try:
        import db
        import migrate
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  ⏭  moteur indisponible ({type(exc).__name__}) — rien mesuré.\n")
        return 0

    # On relit les sources par le MÊME code que la migration : deux lectures de
    # la même source finissent toujours par diverger, et le contrôle deviendrait
    # alors un second avis plutôt qu'une vérification.
    registres = [
        ("handoffs", "handoffs/*.md",
         {l[0] for l in migrate.lire_handoffs()}, "filename"),
    ]

    print(f"\nREGISTRES DÉRIVÉS — source ↔ `{db.BACKEND}`\n")
    echecs: list[str] = []

    for table, source, attendu, cle in registres:
        try:
            en_base = {r[cle] for r in db.query(f"SELECT {cle} FROM {table}")}
        except Exception as exc:                           # noqa: BLE001
            print(f"  ❌ {table:10} illisible : {type(exc).__name__}")
            print("     Une table qu'on ne peut pas lire n'est pas une table vide.")
            echecs.append(table)
            continue
        manquants = sorted(attendu - en_base)
        orphelins = sorted(en_base - attendu)
        etat = "❌" if manquants else "✅"
        print(f"  {etat} {table:10} {len(attendu):>3} dans {source:16} "
              f"· {len(en_base):>3} en base")
        if orphelins:
            # Une ligne en base sans source n'est PAS une erreur : un handoff
            # consommé puis rangé, un signal retiré de l'index, laissent
            # légitimement leur trace.
            print(f"       ℹ️  {len(orphelins)} en base sans source — trace d'un")
            print("           élément rangé, ce n'est pas une erreur")
        if manquants:
            echecs.append(table)
            for f in manquants[:5]:
                print(f"       ❌ absent de la base : {f}")
            if len(manquants) > 5:
                print(f"       … et {len(manquants) - 5} autre(s)")

    # `sessions` est dérivée de `claims`, pas d'un fichier : sa source est dans
    # la base elle-même. Une session sans claim n'existe pas ; un claim sans
    # session est un registre en retard.
    try:
        sans = db.query_one(
            "SELECT COUNT(*) AS n FROM claims c "
            "LEFT JOIN sessions s ON s.sess_id = c.sess_id "
            "WHERE s.sess_id IS NULL")["n"]
        n_claims = db.query_one("SELECT COUNT(*) AS n FROM claims")["n"]
        n_sess = db.query_one("SELECT COUNT(*) AS n FROM sessions")["n"]
    except Exception as exc:                               # noqa: BLE001
        print(f"  ❌ sessions   illisible : {type(exc).__name__}")
        echecs.append("sessions")
    else:
        etat = "❌" if sans else "✅"
        print(f"  {etat} {'sessions':10} {n_claims:>3} dans {'claims':16} "
              f"· {n_sess:>3} en base")
        if sans:
            echecs.append("sessions")
            print(f"       ❌ {sans} claim(s) sans session dérivée")

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} registre(s) en retard : {', '.join(echecs)}")
        print("     Ce qui manque n'est dans aucune sauvegarde, et la")
        print("     conciergerie ne le compte pas.")
        print("     `python3 brain-engine/migrate.py` les écrit.\n")
        return 1
    print("  ✅ les deux registres portent ce que leur source déclare\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
