#!/usr/bin/env python3
"""Le front rotatif ne sert-il que des intentions actives ?

Ce qui pourrirait en silence sans lui : **un chantier mort servi au boot comme
s'il attendait qu'on s'y mette.**

Mesuré le 23/09, et toujours vrai le 24 :

    mon-app-dependance                         active      21 j
    mon-app-tableau-de-bord                    active      21 j
    un-rituel-mensuel                          stasis      41 j
    une-migration-terminee                     archived   137 j

**Deux sur quatre ne sont pas actives.** L'une est ARCHIVÉE depuis cent
trente-sept jours et tient la place n°4 du front rotatif, avec un `next_step`
qui dit lui-même « Scope original livré ». `brain_focus` les compte dans
« Actives (2 + 4 front) ».

    python3 tools/front_rotatif_actif.py --brain ~/Dev/Brain

── Pourquoi rien ne l'attrape aujourd'hui ──────────────────────────────────

Deux mécanismes existent, et aucun ne couvre ce cas :

    server.py:1335   SELECT ... FROM intentions WHERE front = 1
                     -> aucune condition sur `status`

    brain-audit.sh   SUM(status = 'active' AND DATEDIFF(...) > ttl_days)
                     -> ne juge QUE les actives

Une intention **au front et non active** échappe donc aux deux : le front ne
regarde pas son statut, le TTL ne regarde pas le front. `front` et `status` ne
sont liés par rien.

── 🔴 Ce contrôle ne range rien — il montre ────────────────────────────────

Les intentions sont les décisions de l'owner. Un outil qui « corrigerait » un
front en retirant des lignes prendrait une décision à sa place, et c'est
exactement ce qu'un contrôle ne doit pas faire. Il nomme, il ne touche pas.

── Il n'écrit rien ─────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Le seul statut qui a sa place dans un front rotatif. `identified` n'y est pas :
# une intention identifiee n'est pas encore un chantier en cours.
ACTIF = "active"

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


def juger(lignes: list[dict]) -> tuple[list[dict], list[dict]]:
    """(hors_statut, jamais_touchees). Separe de la collecte pour etre eprouve
    sans base — un controle qui exige un moteur allume ne juge rien quand il
    est eteint."""
    hors = [r for r in lignes if (r.get("status") or "") != ACTIF]
    jamais = [r for r in lignes
              if r.get("last_touched") is None and r.get("total_sessions", 0) == 0]
    return hors, jamais


def age_en_jours(r: dict) -> int | None:
    ref = r.get("last_touched") or r.get("updated_at")
    if not isinstance(ref, datetime):
        return None
    return (datetime.now(timezone.utc).replace(tzinfo=None) - ref).days


def auto_epreuve() -> None:
    print("\nAUTO-ÉPREUVE — sur des lignes fabriquées\n")

    # Le temoin negatif d'abord : sans lui, « aucun rouge » ne se distingue pas
    # de « le juge ne juge rien ».
    verifie("témoin négatif : un front entièrement actif ne rougit pas",
            juger([{"id": "a", "status": "active"},
                   {"id": "b", "status": "active"}])[0], [])

    verifie("témoin du défaut réel : une intention `archived` au front",
            [r["id"] for r in juger([{"id": "a", "status": "active"},
                                     {"id": "v2", "status": "archived"}])[0]],
            ["v2"])

    verifie("`stasis` aussi — une pause n'est pas un chantier en cours",
            [r["id"] for r in juger([{"id": "f", "status": "stasis"}])[0]], ["f"])

    verifie("`identified` aussi — identifiée n'est pas commencée",
            [r["id"] for r in juger([{"id": "i", "status": "identified"}])[0]], ["i"])

    verifie("`done` aussi",
            [r["id"] for r in juger([{"id": "d", "status": "done"}])[0]], ["d"])

    # 🔴 Ce temoin dit qu'on ne confond pas deux defauts differents : une
    # intention ACTIVE mais jamais touchee n'est pas hors statut. Sans lui, on
    # pourrait faire rougir la mauvaise colonne et croire le controle juste.
    verifie("une active jamais touchée n'est PAS un défaut de statut",
            juger([{"id": "n", "status": "active", "last_touched": None,
                    "total_sessions": 0}])[0], [])
    verifie("… mais elle est signalée à part",
            [r["id"] for r in juger([{"id": "n", "status": "active",
                                      "last_touched": None,
                                      "total_sessions": 0}])[1]], ["n"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", type=Path, default=Path.home() / "Dev/Brain")
    args = ap.parse_args()
    brain = args.brain.expanduser().resolve()

    print("FRONT ROTATIF — ne sert-il que des intentions actives ?\n")

    sys.path.insert(0, str(brain / "brain-engine"))
    try:
        import db  # type: ignore
        lignes = db.query(
            "SELECT id, status, project, front_order, next_step, "
            "last_touched, updated_at, total_sessions "
            "FROM intentions WHERE front = 1 ORDER BY front_order")
    except Exception as exc:                                       # noqa: BLE001
        # Non mesurable, et NOMME. Une base injoignable n'est pas un front sain.
        print(f"SKIP — base illisible : {type(exc).__name__} {str(exc)[:80]}")
        auto_epreuve()
        print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
        return 1 if _ko else 0

    if not lignes:
        print("  ⚪ aucune intention au front — rien à juger")
        auto_epreuve()
        print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
        return 1 if _ko else 0

    hors, jamais = juger(lignes)

    for r in lignes:
        j = age_en_jours(r)
        drapeau = "🔴" if (r.get("status") or "") != ACTIF else "  "
        # `front_order` est NULL sur deux des quatre entrees : le champ existe
        # et personne ne le remplit. On affiche « #- » plutot que « #None », qui
        # donnait l'air d'un bug de l'outil alors que c'est l'etat de la donnee.
        rang = r.get("front_order")
        print(f"  {drapeau} #{rang if rang is not None else '-'} {r['id']:<42} "
              f"{r.get('status', '?'):<10} {j if j is not None else '?'} j")

    print()
    if hors:
        print(f"  ❌ {len(hors)} intention(s) au front sans être actives :")
        for r in hors:
            ns = (r.get("next_step") or "").replace("\n", " ")[:64]
            print(f"     {r['id']}  [{r.get('status')}]")
            if ns:
                print(f"       next_step : {ns}")
        print("     Le front les sert au boot comme des chantiers qui attendent.")
        print("     Rien ne les en sort : `front` et `status` ne sont liés par rien")
        print("     — le front ignore le statut, le TTL ne juge que les actives.")
        print("     ⚠️  Ce contrôle ne range pas : ce sont des décisions humaines.")
    else:
        print(f"  ✅ les {len(lignes)} intentions du front sont actives")

    if jamais:
        print(f"\n  ⚪ {len(jamais)} au front n'ont jamais été touchées "
              f"(`last_touched` vide, 0 session) :")
        for r in jamais:
            print(f"     {r['id']}")
        print("     Ni un écart ni une dérive — mais l'étape qui devrait les")
        print("     remplir est une consigne dans `helloWorld.md`, pas un")
        print("     mécanisme. Le champ ressemble à zéro parce qu'il")
        print("     n'a jamais rien enregistré.")

    auto_epreuve()
    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    if not hors and not _ko:
        print(f"\n  ✅ front rotatif sain — {len(lignes)} intentions, toutes actives")
    return 1 if (hors or _ko) else 0


if __name__ == "__main__":
    sys.exit(main())
