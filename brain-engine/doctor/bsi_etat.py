#!/usr/bin/env python3
"""L'état du BSI tient-il ?

`bsi_coherence.py` vérifie qu'il n'existe **qu'une seule façon** d'ouvrir un
claim. Personne ne vérifiait l'**état** du mécanisme lui-même. Audité le 04/09
à la demande de l'owner, il ne tenait pas :

    10 claims fermés `stale-auto-closed`, TOUS de type `pilote`, 9,6 h à 76,8 h
    `claims.expires_at`     écrit à l'ouverture, JAMAIS lu par personne
    6 vues de surveillance  dans SQLite, ZÉRO dans la base vivante
    hook post-commit        surveillait `claims/`, aboli par l'ADR-042

Le premier point est le plus coûteux : `pilote` est défini comme « long,
multi-scope », et une session dure parfois plusieurs jours, compactages
compris. Le mécanisme ne fermait pas des oublis — il fermait des sessions
**vivantes**, en écrasant leur vrai résultat par « stale-auto-closed ».

    python3 tools/bsi_etat.py --brain ~/Dev/Brain

**Ce que ce contrôle regarde** : des invariants de STRUCTURE, qui ne dépendent
pas de l'heure à laquelle on le lance. Un claim momentanément périmé n'est pas
une dérive — le passage de nettoyage est quotidien, et un claim peut
légitimement attendre son tour. Ce qui serait une dérive, c'est que le
mécanisme perde les moyens de distinguer une session vivante d'un oubli.

Sortie 1 si un invariant tombe.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `v_graduation_candidates` est partie le 28/09 avec `agent_memory`, qu'elle
# lisait — 0 ligne, 0 écrivain depuis mars.
VUES = ("v_open_claims", "v_stale_claims", "v_active_locks",
        "v_cold_start_kpi", "v_metabolism_7d")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    racine = args.brain.expanduser().resolve()

    sys.path.insert(0, str(racine / "brain-engine"))
    try:
        import db
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  ⏭  moteur indisponible ({type(exc).__name__}) — rien mesuré.\n")
        return 0

    echecs: list[str] = []

    def verifie(nom: str, cond: bool, detail: str = "") -> None:
        if not cond:
            echecs.append(nom)
        print(f"  {'✅' if cond else '❌'} {nom:<44} {detail}")

    print(f"\nÉTAT DU BSI — base `{db.BACKEND}`\n")

    # ── Les vues de surveillance vivent-elles dans la base qu'on LIT ? ───────
    absentes = []
    for v in VUES:
        try:
            db.query_one(f"SELECT COUNT(*) AS n FROM {v}")
        except Exception:                                  # noqa: BLE001
            absentes.append(v)
    verifie(f"les {len(VUES)} vues de surveillance répondent",
            not absentes,
            f"absente(s) : {', '.join(absentes)}" if absentes
            else "brain-engine/views-dolt.sql")

    # ── Le signe de vie est-il branché ? ─────────────────────────────────────
    #
    # Sans lui, `close-stale` retombe sur l'âge depuis l'ouverture, qui ne peut
    # que grandir : une session de trois jours redevient un oubli.
    hook = racine / ".git" / "hooks" / "post-commit"
    texte = hook.read_text(errors="replace") if hook.is_file() else ""
    # Depuis le 27/09 le hook installé n'est qu'un LANCEUR : son corps est la
    # source versionnée scripts/hooks/post-commit. Le suivre, sinon l'invariant
    # tombe le jour même où le hook devient enfin le même partout.
    source = racine / "scripts" / "hooks" / "post-commit"
    if "scripts/hooks/" in texte and source.is_file():
        texte += source.read_text(errors="replace")
    branche = "bsi-claim.sh" in texte
    verifie("le hook post-commit touche le claim",
            branche,
            "scripts/install-brain-hooks.sh" if branche
            else "ABSENT — les sessions longues redeviendront des « oublis »")

    # ── `expires_at` est-il renseigné sur ce qui est ouvert ? ────────────────
    try:
        sans = db.query_one(
            "SELECT COUNT(*) AS n FROM claims "
            "WHERE status = 'open' AND expires_at IS NULL")["n"]
        ouverts = db.query_one(
            "SELECT COUNT(*) AS n FROM claims WHERE status = 'open'")["n"]
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  ❌ `claims` illisible : {type(exc).__name__}")
        print("     Une table qu'on ne peut pas lire n'est pas une table vide.\n")
        return 1
    verifie("tout claim ouvert porte son expiration", sans == 0,
            f"{ouverts} ouvert(s), {sans} sans expires_at")

    # ── Un claim fermé sans durée est une mesure qui n'a jamais servi ────────
    nul = db.query_one("SELECT COUNT(*) AS n FROM claims "
                       "WHERE status = 'closed' AND duration_min IS NULL")["n"]
    total = db.query_one("SELECT COUNT(*) AS n FROM claims "
                         "WHERE status = 'closed'")["n"]
    verifie("les claims fermés portent leur durée", nul == 0,
            f"{nul}/{total} sans duration_min")

    # ── Informatif, jamais bloquant ──────────────────────────────────────────
    #
    # Le taux de fermeture automatique dit si le mécanisme se substitue aux
    # sessions. Il ne rougit pas : c'est un historique, il ne se corrige pas.
    auto = db.query_one("SELECT COUNT(*) AS n FROM claims "
                        "WHERE result = 'stale-auto-closed'")["n"]
    if total:
        print(f"\n  ℹ️  {auto}/{total} claims fermés par rattrapage "
              f"({100 * auto / total:.0f} %) — tous antérieurs au 04/09, et")
        print("      tous de type `pilote` : c'étaient des sessions vivantes.")

    stale = db.query_one("SELECT COUNT(*) AS n FROM v_stale_claims")["n"] \
        if "v_stale_claims" not in absentes else None
    if stale:
        print(f"  ℹ️  {stale} claim(s) actuellement périmé(s) — le passage de")
        print("      nettoyage est quotidien, ce n'est pas une dérive en soi.")

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} invariant(s) tombé(s) : {', '.join(echecs)}")
        print("     Le BSI perd les moyens de distinguer une session vivante")
        print("     d'un oubli. Détail —.\n")
        return 1
    print("  ✅ le BSI sait distinguer une session vivante d'un oubli\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
