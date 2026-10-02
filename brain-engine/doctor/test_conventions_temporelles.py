#!/usr/bin/env python3
"""Témoin des conventions temporelles de la base

Le brain écrit ses horodatages en UTC. La convention a été corrigée trois fois —
dans le code (), dans `intentions` (), dans neuf autres tables
() — et elle est revenue à chaque fois par un chemin que le contrôle
précédent ne regardait pas.

Le dernier en date est le plus net : `TestConventionUTC` interdit `NOW()` dans le
code, mais **il ne voit pas le schéma**. `embeddings.created_at` porte un
`DEFAULT CURRENT_TIMESTAMP`, et `CURRENT_TIMESTAMP` est l'horloge du moteur, donc
l'heure locale. Un `INSERT` qui nomme `updated_at` en UTC et laisse `created_at`
au défaut écrit **deux conventions dans une seule ligne**. Mesuré le 03/09 : 328
chunks avec `created_at` à 18:47 et `updated_at` à 16:47, posés par le même ordre.

Trois invariants, tous exacts — ils ne s'appuient sur aucun seuil :

    aucune valeur ne devance UTC      une horloge en avance sur UTC n'est pas UTC
    created_at <= updated_at          une ligne n'est pas modifiée avant d'exister
    aucun ON UPDATE CURRENT_TIMESTAMP il réécrit l'heure locale à chaque UPDATE,
                                      sans qu'aucun code ne le demande

Le premier ne tient que deux heures après les faits — une valeur locale devance
UTC de deux heures, puis l'horloge la rattrape. Le second, lui, ne se périme
jamais : c'est celui qui protège vraiment.

Les colonnes datées **vers l'avant** sont exclues du premier : `expires_at` vaut
`opened_at + TTL`, elle devance UTC par construction.

    python3 tools/test_conventions_temporelles.py --brain ~/Dev/Brain

Sortie 1 si un invariant tombe.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERS_L_AVANT = ("expires_at", "due_at", "scheduled_at", "deadline")
RE_TEMPOREL = re.compile(r"date|time", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=True)
    args = parser.parse_args()

    root = args.brain.expanduser().resolve()
    sys.path.insert(0, str(root / "brain-engine"))
    import db

    if db.BACKEND != "dolt":
        print(f"SKIP: backend `{db.BACKEND}` — les défauts de schéma visés sont ceux de Dolt.")
        return 0

    echecs: list[str] = []

    def verifie(nom: str, cond: bool, detail: str = "") -> None:
        if not cond:
            echecs.append(nom)
        print(f"  {'✅' if cond else '❌'} {nom:<44} {detail}")

    print("\nCONVENTIONS TEMPORELLES\n")

    tables = [list(r.values())[0] for r in db.query("SHOW TABLES")]
    colonnes: dict[str, list[str]] = {}
    defauts, on_update = [], []
    for table in tables:
        colonnes[table] = [c["Field"] for c in db.query(f"SHOW COLUMNS FROM `{table}`")
                           if RE_TEMPOREL.search(c["Type"])]
        # `SHOW COLUMNS` ne rapporte pas `ON UPDATE` sous Dolt — la DDL, si.
        ddl = list(db.query_one(f"SHOW CREATE TABLE `{table}`").values())[1]
        for ligne in ddl.split("\n"):
            if not re.search(r"CURRENT_TIMESTAMP", ligne, re.I):
                continue
            champ = re.match(r"\s*`(\w+)`", ligne).group(1)
            if re.search(r"ON UPDATE CURRENT_TIMESTAMP", ligne, re.I):
                on_update.append(f"{table}.{champ}")
            elif re.search(r"DEFAULT CURRENT_TIMESTAMP", ligne, re.I):
                defauts.append(f"{table}.{champ}")

    # ── 1. aucune valeur ne devance UTC ──────────────────────────────────────
    # Deux lectures, et seule l'intersection compte.
    #
    # Ce contrôle compare des données vivantes à une horloge vivante. Une écriture
    # en cours pendant la lecture — une passe d'embedding, le témoin du cache, une
    # autre session — fait apparaître une avance qui n'existe plus une seconde
    # après. Observé le 04/09, juste après les ALTER de : rouge au
    # passage du médecin, vert trente secondes plus tard.
    #
    # C'est la même leçon que. Un contrôle qui rougit à tort s'apprend à
    # s'ignorer, et c'est aussi coûteux qu'un contrôle qui ne peut pas rougir.
    def _avances() -> dict[str, int]:
        vus = {}
        for table, cols in colonnes.items():
            for col in cols:
                if col.lower() in VERS_L_AVANT:
                    continue
                n = int(db.query_one(
                    f"SELECT COUNT(*) n FROM `{table}` WHERE `{col}` > UTC_TIMESTAMP()")["n"])
                if n:
                    vus[f"{table}.{col}"] = n
        return vus

    premier = _avances()
    confirme = {k: v for k, v in _avances().items() if k in premier} if premier else {}
    devancent = [f"{k} ({v})" for k, v in confirme.items()]
    verifie("aucune valeur ne devance UTC", not devancent,
            ", ".join(devancent) if devancent else "toutes les horloges concordent")

    # ── 2. created_at <= updated_at ──────────────────────────────────────────
    # L'invariant qui ne se périme pas : une ligne n'est pas modifiée avant
    # d'exister. Deux conventions dans une même ligne le violent forcément.
    inverses = []
    for table, cols in colonnes.items():
        if "created_at" in cols and "updated_at" in cols:
            n = int(db.query_one(f"SELECT COUNT(*) n FROM `{table}` "
                                 f"WHERE created_at > updated_at")["n"])
            if n:
                inverses.append(f"{table} ({n})")
    verifie("created_at <= updated_at", not inverses,
            ", ".join(inverses) if inverses else "aucune ligne modifiée avant sa création")

    # ── 3. aucun ON UPDATE CURRENT_TIMESTAMP ─────────────────────────────────
    verifie("aucun ON UPDATE CURRENT_TIMESTAMP", not on_update,
            ", ".join(on_update) if on_update else "aucune réécriture implicite")

    # ── Inventaire : les DEFAULT restants ────────────────────────────────────
    # Pas encore un échec : les retirer demande de rendre chaque écrivain
    # explicite, table par table. C'est. Mais ils sont comptés ici pour
    # que le chantier ne s'oublie pas — un piège qu'on ne voit plus est un piège
    # qui ressert.
    peuplees = [d for d in defauts
                if int(db.query_one(f"SELECT COUNT(*) n FROM `{d.split('.')[0]}`")["n"])]
    print(f"\n  ℹ️  {len(defauts)} colonne(s) gardent un DEFAULT CURRENT_TIMESTAMP "
          f"— l'horloge du moteur, donc locale")
    print(f"      dont {len(peuplees)} sur une table peuplée : "
          f"{', '.join(peuplees) if peuplees else '—'}")
    print("      Un INSERT qui omet la colonne y écrit de l'heure locale.")

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} invariant(s) tombé(s) : {', '.join(echecs)}\n")
        return 1
    print("  ✅ une seule convention, et le schéma ne la contredit plus\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
