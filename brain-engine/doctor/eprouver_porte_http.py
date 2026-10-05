#!/usr/bin/env python3
"""La porte HTTP répond-elle vraiment ? —.

Le pendant de `eprouver_porte_mcp.py`, et il manquait. Depuis le 10/09 le MCP
pouvait être éprouvé sans toucher au service ; `server.py` ne le pouvait pas —
la seule façon de savoir si une modification tenait était de **redémarrer le
service en production**. Une porte qu'on ne peut vérifier qu'en la mettant en
service n'est pas vérifiable : on constate après coup.

    python3 tools/eprouver_porte_http.py --brain ~/Dev/Brain

── Ce qu'il fait, et ce qu'il ne fait pas ──────────────────────────────────

Il charge `server.py` et appelle l'application **en mémoire**, par le harnais
de FastAPI. Aucun port n'est ouvert, aucun service n'est touché, rien ne
transite par le réseau.

**Toutes les routes appelées sont en LECTURE.** Aucun POST, PUT, PATCH ou
DELETE : elles écriraient dans la base vivante, et un témoin qui écrit n'est
plus un témoin. C'est la règle que `test_controles_rougissent.py` énonce déjà
pour trois autres contrôles.

Sont exclues aussi les routes qui **sortent sur le réseau local** —
`/bsi/network` et `/bsi/claims?include_peers=true` interrogent le laptop
déclaré dans `brain-compose.local.yml`. Éprouver ici reviendrait à sonder une
autre machine de l'utilisateur.

── Les deux témoins, et pourquoi il en faut deux ───────────────────────────

Sans eux, « les routes rendent 200 » ne mesure rien : un routeur à moitié monté
en rendrait aussi.

    1. une route qui n'existe pas doit rendre 404
       — prouve que le routeur JUGE, au lieu de tout accepter

    2. un client NON-localhost doit être refusé sur une route Layer 2
       — prouve que `_is_localhost` garde vraiment, et donc que le vert des
         routes L2 ci-dessus vient de notre adresse et non d'une garde morte

Le second est le plus important : sans lui, une garde qui laisserait tout
passer produirait exactement la même sortie verte.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Uniquement des lectures, et uniquement local. Le commentaire de chaque ligne
# dit ce que la route touche — c'est ce que `contrat/capacites.yml` déclare.
LECTURES = [
    ("/health",      "l'identité du service"),
    ("/state",       "l'environnement dérivé — Layer 2"),
    ("/focus",       "la direction active — base + disque"),
    ("/agents",      "le registre des agents — disque"),
    # `/intentions` retirée le 4/10 : le focus se suit dans les fiches.
    ("/workflows",   "ce qui avance en autonomie — sous-processus"),
    ("/bsi/claims",  "les claims, SANS include_peers"),
    ("/bsi/locks",   "les verrous locaux"),
]

# La route qui doit refuser un client distant. `_is_localhost` la garde, et
# elle est declaree `[L2 only]` dans l'en-tete de `server.py`.
ROUTE_L2 = "/state"


def main() -> int:
    p = argparse.ArgumentParser(description="Éprouver la porte HTTP hors service")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()

    moteur = a.brain.expanduser().resolve() / "brain-engine"
    if not (moteur / "server.py").is_file():
        print("⏭️  SKIP brain-engine/server.py introuvable.", file=sys.stderr)
        return 0
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("⏭️  SKIP fastapi.testclient absent — rien à conclure.", file=sys.stderr)
        return 0

    sys.path.insert(0, str(moteur))
    try:
        import server
    except Exception as exc:                                   # noqa: BLE001
        print(f"❌ le module ne se charge pas : {type(exc).__name__} — {exc}",
              file=sys.stderr)
        return 1

    routes = [r for r in server.app.routes if getattr(r, "path", "").startswith("/")]
    print(f"  ✅ module chargé — {len(routes)} routes montées, aucun port ouvert")

    local = TestClient(server.app, client=("127.0.0.1", 4242))

    # ── 1. les lectures ─────────────────────────────────────────────────────
    echecs = []
    for chemin, quoi in LECTURES:
        try:
            r = local.get(chemin)
        except Exception as exc:                               # noqa: BLE001
            print(f"  ❌ GET {chemin} a levé : {type(exc).__name__} — {exc}",
                  file=sys.stderr)
            echecs.append(chemin)
            continue
        ok = r.status_code < 400
        if not ok:
            echecs.append(chemin)
        print(f"  {'✅' if ok else '❌'} GET {chemin:<16} {r.status_code}  "
              f"{len(r.content):>6} o   {quoi}")

    if echecs:
        print(f"\n❌ {len(echecs)} route(s) de lecture en échec : "
              f"{', '.join(echecs)}", file=sys.stderr)
        return 1

    # ── 2. témoin : le routeur juge-t-il ? ──────────────────────────────────
    r = local.get("/cette-route-n-existe-pas")
    if r.status_code != 404:
        print(f"\n❌ témoin — une route inexistante rend {r.status_code} au lieu "
              f"de 404 : le routeur accepte tout, le vert ci-dessus ne mesure "
              f"rien.", file=sys.stderr)
        return 1
    print(f"  ✅ témoin — une route inexistante rend bien 404")

    # ── 3. témoin : la garde Layer 2 garde-t-elle ? ─────────────────────────
    #
    # Deux façons d'être « pas localhost », et `_is_localhost` traite les deux :
    # une adresse cliente etrangere, et un `X-Forwarded-For` — qui signale un
    # passage par le proxy Apache. On eprouve les deux, parce qu'un garde qui
    # n'en verrait qu'une laisserait l'autre ouverte.
    distant = TestClient(server.app, client=("203.0.113.7", 4242))
    r_ip = distant.get(ROUTE_L2)
    r_fwd = local.get(ROUTE_L2, headers={"X-Forwarded-For": "203.0.113.7"})

    for nom, rep in (("adresse distante", r_ip), ("X-Forwarded-For", r_fwd)):
        if rep.status_code != 403:
            print(f"\n❌ témoin — {ROUTE_L2} accepte une requête « {nom} » "
                  f"({rep.status_code}) alors qu'elle est Layer 2.\n"
                  f"   La garde ne garde pas, et le vert des routes L2 ci-dessus "
                  f"ne venait pas de notre adresse.", file=sys.stderr)
            return 1
        print(f"  ✅ témoin — {ROUTE_L2} refuse « {nom} » en 403")

    print(f"\n✅ la porte répond — {len(LECTURES)} lectures, un routeur qui juge, "
          f"et une garde Layer 2 qui refuse")
    return 0


if __name__ == "__main__":
    sys.exit(main())
