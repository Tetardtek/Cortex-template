#!/usr/bin/env python3
"""L'instantané Dolt a-t-il tourné ?

Ce qui pourrirait en silence sans lui : **un instantané qui échoue à chaque
passage, dans un journal que personne ne lit.**

`scripts/dolt-snapshot.sh` (cron, toutes les six heures) commite ce que la base
porte sans commit, pour que les sauvegardes, qui ne copient que les commits,
l'emportent. Pendant cinq jours, chaque passage qui avait quelque chose à
prendre a été refusé par les règles de branche, et seul son journal le disait.

── Ce qu'il lit ────────────────────────────────────────────────────────────

`brain-engine/.instantane-dolt`, que le script écrit à chaque passage :

    tentative=2026-10-04 09:48:12     l'heure murale, en UTC
    resultat=ok | rien | ko           commité, rien à prendre, échec
    erreur=…
    demarrage=1791106391              le démarrage de la machine (btime)
    eveil=1793                        l'horloge d'éveil (CLOCK_MONOTONIC)

Un journal dit ce qu'un passage a tenté ; cet état dit comment il a fini, et
c'est le script qui l'écrit, en erreur comme en succès.

── Ce qu'il juge ───────────────────────────────────────────────────────────

    ❌  le dernier passage a échoué ;
    ❌  aucun passage depuis plus de 7 h D'ÉVEIL : le cron ne tourne plus.
    ⏭  l'instance n'a pas d'instantané, ou aucun passage n'est encore écrit.

Le temps se compte en éveil, pas à l'horloge murale : en veille, le cron ne
tourne pas, et une nuit de veille n'est pas une panne. Même démarrage : l'éveil
écoulé depuis le passage. Démarrage différent : l'éveil depuis le démarrage, le
passage étant d'avant.

    python3 tools/instantane_a_tourne.py --brain ~/Dev/Brain
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

CADENCE_H = 6          # le cron : toutes les six heures
MARGE_H = 1
ECART_DEMARRAGE_S = 5  # `btime` peut bouger d'une seconde entre deux lectures


def lire_etat(chemin: Path) -> dict | None:
    """Les clés de l'état, `None` s'il n'existe pas. Pur hors lecture."""
    if not chemin.is_file():
        return None
    etat = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if "=" in ligne:
            cle, val = ligne.split("=", 1)
            etat[cle.strip()] = val.strip()
    return etat


def _entier(val) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def juger(etat: dict | None, demarrage: int | None, eveil: int) -> tuple[str, str]:
    """('ok' | 'ko' | 'abstention', phrase). Pur."""
    if etat is None:
        return "abstention", "aucun passage écrit — l'instantané n'a pas encore tourné ici"
    quand = etat.get("tentative") or "?"
    if etat.get("resultat") == "ko":
        return "ko", f"le dernier passage a échoué ({quand} UTC) : {etat.get('erreur') or 'sans détail'}"
    if etat.get("resultat") not in ("ok", "rien"):
        return "ko", f"état illisible : resultat={etat.get('resultat')!r}"
    d_etat, e_etat = _entier(etat.get("demarrage")), _entier(etat.get("eveil"))
    meme = (demarrage is not None and d_etat is not None
            and abs(demarrage - d_etat) <= ECART_DEMARRAGE_S)
    if d_etat is None or (meme and e_etat is None):
        return "ko", "état sans repère d'éveil — le script d'avant ? Relancer dolt-snapshot.sh"
    if meme:
        depuis, repere = eveil - e_etat, "depuis ce passage"
    else:
        depuis, repere = eveil, "depuis le démarrage, le passage étant d'avant"
    if depuis > (CADENCE_H + MARGE_H) * 3600:
        return "ko", (f"aucun passage depuis {depuis // 3600} h d'éveil (le dernier : {quand} UTC) — "
                      f"le cron tourne-t-il ?")
    return "ok", (f"dernier passage {quand} UTC : {etat.get('resultat')} — "
                  f"{depuis // 60} min d'éveil {repere}")


def demarrage_de_la_machine() -> int | None:
    try:
        for ligne in Path("/proc/stat").read_text().splitlines():
            if ligne.startswith("btime "):
                return int(ligne.split()[1])
    except (OSError, ValueError):
        pass
    return None


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
    d = 1_791_106_391
    h = 3600

    def etat(resultat, eveil, demarrage=d):
        return {"tentative": "2026-10-04 09:48:12", "resultat": resultat, "erreur": "",
                "demarrage": str(demarrage), "eveil": str(eveil)}

    # 🔴 L'incident : le commit refusé par les règles de branche.
    verifie("l'incident : un passage refusé est rouge",
            juger({**etat("ko", 100), "erreur": "code 1"}, d, 200)[0], "ko")
    verifie("un passage réussi il y a 2 h d'éveil est vert", juger(etat("ok", 100), d, 100 + 2 * h)[0], "ok")
    verifie("« rien à prendre » est un passage", juger(etat("rien", 100), d, 100 + 2 * h)[0], "ok")
    verifie("8 h d'éveil sans passage : le cron ne tourne plus",
            juger(etat("ok", 100), d, 100 + 8 * h)[0], "ko")
    # Une nuit de veille : l'horloge murale avance de 10 h, l'éveil de quelques minutes.
    verifie("une nuit de veille n'est pas une panne", juger(etat("ok", 100), d, 100 + 600)[0], "ok")
    verifie("btime à une seconde près : même démarrage",
            juger(etat("ok", 100), d + 1, 100 + 2 * h)[0], "ok")
    verifie("redémarrée il y a 30 min : pas encore jugé",
            juger(etat("ok", 50_000), d + 86_400, 1800)[0], "ok")
    verifie("redémarrée il y a 8 h sans passage : rouge",
            juger(etat("ok", 50_000), d + 86_400, 8 * h)[0], "ko")
    verifie("aucun état : abstention", juger(None, d, 100)[0], "abstention")
    verifie("un état sans repère d'éveil n'est pas un vert",
            juger({"tentative": "x", "resultat": "ok"}, d, 100)[0], "ko")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    print("L'INSTANTANÉ DOLT A TOURNÉ — son dernier passage a-t-il fini, et date-t-il "
          "de moins de 7 h d'éveil ?\n")

    if not (brain / "scripts" / "dolt-snapshot.sh").is_file():
        auto_epreuve()
        print("\nVERDICT: ⏭ cette instance ne prend pas d'instantané Dolt — rien à juger")
        return 1 if _ko else 0

    verdict, phrase = juger(lire_etat(brain / "brain-engine" / ".instantane-dolt"),
                            demarrage_de_la_machine(), int(time.monotonic()))
    auto_epreuve()
    print()
    if _ko:
        print(f"VERDICT: ❌ auto-épreuve : {_ko} cas sur {_ok + _ko}")
        return 1
    if verdict == "abstention":
        print(f"VERDICT: ⏭ {phrase}. C'est une abstention, pas un vert.")
        return 0
    if verdict == "ko":
        print(f"VERDICT: ❌ {phrase}. Journal : brain-engine/dolt-snapshot.log")
        return 1
    print(f"VERDICT: ✅ {phrase}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
