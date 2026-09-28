#!/usr/bin/env python3
"""Ce que la discipline d'écriture garantit.

    python3 core/test_traces.py                      # sans base
    python3 core/test_traces.py --dolt ~/Dev/Brain   # + lecture réelle

⚠️ **Ce qui n'est PAS couvert, et il faut le dire.** Le gel et le commit confiné
ne s'éprouvent qu'en ÉCRIVANT dans une base versionnée. Le brain est de la data :
ce test n'y écrit rien. `tools/test_dolt_discipline.py` couvre ce cas depuis
, sur une branche jetable depuis — et c'est lui qui fait foi pour
ces deux garanties, pas ce fichier.

Ce qui est couvert ici : la déduction des tables, le refus de purger sans
raison, et **le refus de purger sur un backend sans versionnement** — la
redécision du rapatriement.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.persistance import DOLT, SQLITE, Config, Depot     # noqa: E402
from core.traces import Journal, SansVersionnement, tables_ecrites  # noqa: E402

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


def deduction() -> None:
    print("\nQUELLES TABLES UN STATEMENT ÉCRIT — fonction pure\n")

    verifie("INSERT", tables_ecrites("INSERT INTO claims (a) VALUES (1)"), ["claims"])
    verifie("UPDATE", tables_ecrites("UPDATE claims SET a = 1"), ["claims"])
    verifie("DELETE", tables_ecrites("DELETE FROM claims WHERE a = 1"), ["claims"])
    verifie("REPLACE", tables_ecrites("REPLACE INTO claims (a) VALUES (1)"), ["claims"])
    verifie("les backticks n'y changent rien",
            tables_ecrites("INSERT INTO `claims` (a) VALUES (1)"), ["claims"])
    verifie("un SELECT n'écrit rien",
            tables_ecrites("SELECT * FROM claims"), [])

    # Le cas qui a motivé la coupure : la queue d'un upsert contient un second
    # `UPDATE … SET` qui ne nomme aucune table.
    verifie("la queue d'un upsert ne fabrique pas de fausse table",
            tables_ecrites("INSERT INTO embeddings (a) VALUES (1) "
                           "ON DUPLICATE KEY UPDATE a = VALUES(a)"), ["embeddings"])
    verifie("deux tables dans un même lot sont toutes deux vues",
            tables_ecrites("INSERT INTO claims (a) VALUES (1); "
                           "UPDATE sessions SET b = 2"), ["claims", "sessions"])
    verifie("une forme non reconnue rend vide, pas un nom deviné",
            tables_ecrites("CALL DOLT_ADD('.')"), [])


def refus() -> None:
    print("\nCE QUE LE JOURNAL REFUSE\n")

    with tempfile.TemporaryDirectory(prefix="core-traces-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "essai.db"))
        journal = Journal(depot)

        verifie("un backend sans versionnement se déclare tel quel",
                journal.versionne, False)
        refuse("purger sans raison est refusé",
               lambda: journal.purge("DELETE FROM t", raison=""), ValueError)

        # ⚠️ La redécision du rapatriement : l'ancien moteur dégradait ici en
        # silence, et l'appelant croyait geler.
        refuse("purger sans versionnement est REFUSÉ, pas dégradé en silence",
               lambda: journal.purge("DELETE FROM t", raison="essai"),
               SansVersionnement)

        verifie("rien ne traîne quand rien n'est versionné",
                journal.tables_sales(), [])
        verifie("un gel sans versionnement ne prétend rien avoir gelé",
                bool(journal.gele("essai")), False)
        verifie("un commit sans versionnement rend False, pas True",
                journal.commit("essai"), False)


def dolt_lecture() -> None:
    print("\nLA BASE VIVANTE — LECTURE SEULE\n")

    journal = Journal(Depot(Config(backend=DOLT)))
    try:
        sales = journal.tables_sales()
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⏭  dolt sql-server injoignable ({type(exc).__name__}) — rien mesuré.\n")
        global _abstenu
        _abstenu = True
        return

    verifie("le journal se sait versionné", journal.versionne, True)
    print(f"  ℹ️  {len(sales)} table(s) dans le working set"
          f"{' : ' + ', '.join(sales) if sales else ''}")
    verifie("les tables sales sont lisibles", isinstance(sales, list), True)

    print("\n  ⏭  gel et commit confiné : NON couverts ici — ils demandent")
    print("     d'écrire. `tools/test_dolt_discipline.py` les éprouve sur une")
    print("     branche jetable, et c'est lui qui fait foi.")
    journal.depot.ferme()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dolt", type=Path, metavar="BRAIN")
    args = p.parse_args()

    deduction()
    refus()
    if args.dolt:
        dolt_lecture()

    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
    return 1 if _ko else (3 if _abstenu else 0)


if __name__ == "__main__":
    sys.exit(main())
