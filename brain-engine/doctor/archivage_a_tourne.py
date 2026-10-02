#!/usr/bin/env python3
"""L'archivage du dimanche a-t-il tourné ?

Ce qui pourrirait en silence sans lui : **un archivage qui échoue chaque
semaine, dans un journal que personne ne lit.**

Du 13/09 au 27/09, trois dimanches de suite, `brain-conciergerie.sh archive`
s'est arrêté sur une clé primaire en double (`duplicate primary key [pilote]`,
puis deux sessions). Sans perte — l'`INSERT` échoue d'un bloc, avant le
`DELETE` —, mais sans rien archiver, et sans rien dire : le cron enchaîne par
`&&`, l'erreur part dans `brain-engine/conciergerie-cron.log`.

── Ce qu'il mesure, et pourquoi pas le journal ─────────────────────────────

Il ne lit PAS le journal : un journal dit ce qu'un passage a tenté. Il regarde
ce que l'archivage aurait dû laisser : **plus aucune ligne en table vivante
au-delà de sa limite, plus une semaine de marge** (le passage est hebdomadaire).

    claims     fermés, ouverts il y a plus de 30 + 7 jours
    sessions   datées de plus de 30 + 7 jours
    signals    relus (delivered), émis il y a plus de 7 + 7 jours
    handoffs   consommés il y a plus de 7 + 7 jours

Une seule de ces lignes, et l'archivage n'a pas tourné — ou a échoué.

Les limites sont calculées ICI, en UTC, et passées en paramètres : le SQL
reste le même en SQLite et en Dolt, et `NOW()` (heure locale du serveur sur
Dolt) n'entre pas dans la mesure.

── Où il mesure ────────────────────────────────────────────────────────────

La base que le brain lit, par `brain-engine/db.py` — donc celle que désignent
`BRAIN_DB_BACKEND` et `BRAIN_DOLT_DB`. C'est ce qui permet de l'éprouver sur une
branche Dolt jetable. Moteur introuvable : abstention dite, pas un vert.

    python3 tools/archivage_a_tourne.py --brain ~/Dev/Brain
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARGE_JOURS = 7

# (table, colonne de temps, condition d'archivabilité, limite en jours)
REGLES = (
    ("claims",   "opened_at",   "status = 'closed'",   30),
    ("sessions", "date",        "1 = 1",               30),
    ("signals",  "created_at",  "state = 'delivered'",  7),
    ("handoffs", "consumed_at", "status = 'consumed'",  7),
)


def limite(jours: int, maintenant: datetime) -> str:
    """La date au-delà de laquelle une ligne aurait dû partir. Pur."""
    return (maintenant - timedelta(days=jours + MARGE_JOURS)).strftime("%Y-%m-%d %H:%M:%S")


def en_retard(db, maintenant: datetime) -> list[tuple[str, int, str | None]]:
    """(table, lignes en retard, la plus ancienne) pour chaque table en retard."""
    retards = []
    for table, temps, condition, jours in REGLES:
        ligne = db.query_one(
            f"SELECT COUNT(*) AS n, MIN({temps}) AS plus_ancienne FROM {table} "
            f"WHERE {condition} AND {temps} < %s", (limite(jours, maintenant),))
        n = int((ligne or {}).get("n") or 0)
        if n:
            retards.append((table, n, str(ligne.get("plus_ancienne"))))
    return retards


_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def auto_epreuve() -> None:
    print("\nAUTO-ÉPREUVE\n")
    # 🔴 L'incident, à l'instant où il a été mesuré (27/09, 11:30 UTC) : le
    # claim « pilote » du 21/08 09:28 était encore en table vivante.
    mesure = datetime(2026, 9, 27, 11, 30, tzinfo=timezone.utc)
    verifie("l'incident : pilote (21/08 09:28) est en retard le 27/09 à 11:30",
            "2026-08-21 09:28:14" < limite(30, mesure), True)
    # Le même, au passage du dimanche (03:00) : pas encore — la marge joue.
    # Première version de ce témoin : fausse, elle affirmait l'inverse.
    dimanche = datetime(2026, 9, 27, 3, 0, 2, tzinfo=timezone.utc)
    verifie("… mais pas encore à 03:00 : la limite est le 21/08 03:00",
            "2026-08-21 09:28:14" < limite(30, dimanche), False)
    verifie("la limite des claims : 37 jours avant, en UTC",
            limite(30, dimanche), "2026-08-21 03:00:02")
    verifie("celle des signaux : 14 jours avant",
            limite(7, dimanche), "2026-09-13 03:00:02")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    print("L'ARCHIVAGE A TOURNÉ — reste-t-il en table vivante ce qui aurait dû "
          "partir ?\n")

    sys.path.insert(0, str(brain / "brain-engine"))
    try:
        import db  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        auto_epreuve()
        print(f"\nVERDICT: ⏭ moteur indisponible ({type(exc).__name__}) — rien mesuré. "
              f"C'est une abstention, pas un vert.")
        return 1 if _ko else 0

    base = db.info()
    print(f"  base : {base.get('backend')} — {base.get('db_path') or '?'}"
          f"{' · ' + db.DOLT_DB if base.get('backend') == 'dolt' else ''}")
    try:
        retards = en_retard(db, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        auto_epreuve()
        print(f"\nVERDICT: ❌ base illisible ({type(exc).__name__}: {str(exc)[:80]}) — "
              f"« je n'ai pas pu regarder » n'est pas « à jour »")
        return 1

    for table, n, ancienne in retards:
        print(f"  ❌ {table:<9} {n:>4} ligne(s) au-delà de la limite — la plus ancienne : {ancienne}")

    auto_epreuve()
    print()
    if _ko:
        print(f"VERDICT: ❌ auto-épreuve : {_ko} cas sur {_ok + _ko}")
        return 1
    if retards:
        total = sum(n for _, n, _ in retards)
        print(f"VERDICT: ❌ {total} ligne(s) auraient dû être archivées — l'archivage du "
              f"dimanche n'a pas tourné, ou a échoué. Journal : "
              f"brain-engine/conciergerie-cron.log")
        return 1
    print("VERDICT: ✅ rien en table vivante au-delà des limites d'archivage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
