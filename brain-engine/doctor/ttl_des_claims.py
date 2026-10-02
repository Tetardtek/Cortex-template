#!/usr/bin/env python3
"""Un claim ouvert suit-il le TTL de son type ?

Ce qui pourrirait en silence sans lui : **une session fermée à tort.** Le TTL
d'un claim (`ttl_hours`) est la durée pendant laquelle il vit sans signe de vie ;
au-delà, `close-stale` le ferme. Chaque type déclare le sien dans
`contexts/session-<type>.yml`, à côté de la posture qui le justifie — `pilote`
12 h, parce qu'une session d'orchestration réfléchit longtemps entre deux commits.

Mesuré le 27/09 : trois sessions `pilote` et une `explore` ouvertes à 4 h — le
défaut — au lieu de 12 h et 8 h. `bsi-claim.sh open` ne lisait pas le manifeste :
le TTL du type ne dépendait que de l'appelant, et deux ouvertures prescrites
l'oubliaient. Il le lit désormais ; ce contrôle vérifie que ce qui est OUVERT le
suit, quel que soit le chemin qui l'a ouvert.

Il ne juge que les claims ouverts : un claim fermé porte le TTL qu'il a eu, c'est
de l'histoire. Un type sans manifeste (`satellite`…) n'a pas de TTL déclaré : il
n'est pas jugé. Base injoignable : abstention.

    python3 tools/ttl_des_claims.py --brain ~/Dev/Brain

Sortie 1 si un claim ouvert a un TTL différent de celui de son type.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def ttl_declare(brain: Path, type_: str | None) -> int | None:
    """Le `ttl_hours` du manifeste du type — ou None s'il n'en déclare pas."""
    if not type_ or not re.fullmatch(r"[a-z][a-z-]*", type_):
        return None
    manifeste = brain / "contexts" / f"session-{type_}.yml"
    if not manifeste.is_file():
        return None
    return lire_ttl(manifeste.read_text(encoding="utf-8"))


def lire_ttl(texte: str) -> int | None:
    """La clé racine `ttl_hours` — pas une clé indentée, pas un commentaire."""
    for ligne in texte.splitlines():
        m = re.match(r"ttl_hours:\s*(\d+)\s*(?:#.*)?$", ligne)
        if m:
            return int(m.group(1))
    return None


def ecarts(claims: list[dict], brain: Path) -> list[tuple[str, str, int | None, int]]:
    """(sess_id, type, ttl du claim, ttl du type) pour chaque claim hors de son type."""
    sortie = []
    for c in claims:
        attendu = ttl_declare(brain, c.get("type"))
        if attendu is not None and c.get("ttl_hours") != attendu:
            sortie.append((c["sess_id"], c.get("type"), c.get("ttl_hours"), attendu))
    return sortie


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
    verifie("ttl_hours à la racine est lu", lire_ttl("type: pilote\nttl_hours: 12\n"), 12)
    verifie("un commentaire en fin de ligne ne gêne pas", lire_ttl("ttl_hours: 8  # explore\n"), 8)
    verifie("une clé indentée n'est pas celle du manifeste", lire_ttl("x:\n  ttl_hours: 3\n"), None)
    verifie("un type au nom douteux n'ouvre aucun fichier",
            ttl_declare(Path("/nulle/part"), "../etc"), None)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    print("LE TTL DES CLAIMS — un claim ouvert suit-il le TTL de son type ?\n")
    sys.path.insert(0, str(brain / "brain-engine"))
    try:
        import db  # noqa: PLC0415
        ouverts = db.query("SELECT sess_id, type, ttl_hours FROM claims WHERE status = 'open'")
    except Exception as exc:  # noqa: BLE001
        auto_epreuve()
        print(f"\nSKIP base injoignable ({type(exc).__name__}) — rien mesuré.")
        return 0

    hors = ecarts(ouverts, brain)
    for sess, type_, ttl, attendu in hors:
        print(f"  ❌ {sess:<44} {type_:<9} {ttl} h — son type déclare {attendu} h")
    auto_epreuve()
    print()
    if _ko:
        print(f"VERDICT: ❌ auto-épreuve : {_ko} cas sur {_ok + _ko}")
        return 1
    if hors:
        print(f"VERDICT: ❌ {len(hors)} claim(s) ouvert(s) hors du TTL de leur type — "
              f"un chemin d'ouverture ne lit pas le manifeste")
        return 1
    print(f"VERDICT: ✅ les {len(ouverts)} claim(s) ouvert(s) suivent le TTL de leur type")
    return 0


if __name__ == "__main__":
    sys.exit(main())
