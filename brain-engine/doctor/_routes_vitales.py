#!/usr/bin/env python3
"""Les routes vitales du brain répondent-elles ? Auxiliaire de `brain_doctor.py`.

Le seul contrôle qui exerce le brain **vivant** plutôt que ses fichiers. Sans
jeton il s'abstient : mesurer des 401 en croyant mesurer le service serait pire
que ne rien mesurer.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# `/infra` en est sorti le 29/09 : la route est retirée (brain#294).
VITALES = ("/health", "/agents", "/focus", "/bsi/claims", "/workflows",
           "/state", "/visualize")


def jeton() -> str | None:
    if valeur := os.environ.get("BRAIN_TOKEN_OWNER"):
        return valeur
    # Le service tourne : son environnement porte le jeton. On le lit sans
    # jamais l'afficher.
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            ligne = (proc / "cmdline").read_bytes().decode(errors="replace")
            if "server.py" not in ligne:
                continue
            for entree in (proc / "environ").read_bytes().decode(errors="replace").split("\0"):
                if entree.startswith("BRAIN_TOKEN_OWNER="):
                    return entree.split("=", 1)[1]
        except OSError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:7700")
    args = parser.parse_args()

    cle = jeton()
    if not cle:
        print("SKIP: BRAIN_TOKEN_OWNER introuvable — le service tourne-t-il ?")
        return 0

    codes, echecs = {}, []
    for route in VITALES:
        requete = urllib.request.Request(f"{args.url}{route}",
                                         headers={"Authorization": f"Bearer {cle}"})
        try:
            with urllib.request.urlopen(requete, timeout=600) as reponse:
                codes[route] = reponse.status
        except urllib.error.HTTPError as exc:
            codes[route] = exc.code
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            codes[route] = f"injoignable ({type(exc).__name__})"
        if codes[route] != 200:
            echecs.append(f"{route} → {codes[route]}")

    if echecs:
        print(f"❌ {len(echecs)}/{len(VITALES)} route(s) hors service : {', '.join(echecs)}")
        return 1
    print(f"✅ {len(VITALES)} routes vitales en 200")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
