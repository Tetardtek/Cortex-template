#!/usr/bin/env python3
"""Les unités du démarrage forment-elles un cycle ? —

    python3 tools/unites_sans_cycle.py --brain ~/Dev/Brain
    python3 tools/unites_sans_cycle.py --brain <x> --unites <dossier>   (témoin)

Un cycle d'ordre entre unités systemd ne lève aucune erreur : au boot, systemd le
casse en SUPPRIMANT le démarrage de l'une d'elles, et la machine démarre sans elle.
Deux fois : chez un fork (Cortex-Template#5, le moteur arrêté à chaque reboot,
`enabled` pourtant), puis chez l'owner le 3/10 — `dolt-server.service`, posé avant
le correctif du 28/09, portait `After=default.target` ; avec `brain-engine.service`
(`After=dolt-server`) réinstallé le 02/10, la base ne démarrait plus. Le premier
redémarrage l'a montré ; ce contrôle l'aurait dit dès le 02/10.

`systemd-analyze --user verify default.target` voit le cycle sans rien démarrer,
en quelques millisecondes. `--unites` vise un dossier jetable (`SYSTEMD_UNIT_PATH`).

Sans systemd (`systemd-analyze` absent) : SKIP. Sortie 0 : aucun cycle. 1 : un cycle,
nommé.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--unites", type=Path, help="un dossier d'unités jetable (le témoin)")
    a = p.parse_args()
    if not shutil.which("systemd-analyze"):
        print("SKIP systemd-analyze absent — pas de systemd, pas d'unités à juger")
        return 0
    env = dict(os.environ)
    cible = "default.target"
    if a.unites:
        env["SYSTEMD_UNIT_PATH"] = f"{a.unites.resolve()}:"
        cible = str(a.unites.resolve() / "default.target")
    r = subprocess.run(["systemd-analyze", "--user", "verify", cible], capture_output=True,
                       text=True, env=env, timeout=60)
    sortie = r.stdout + r.stderr
    # Sans gestionnaire de session (pas de `XDG_RUNTIME_DIR` : un `env -i`, un bac à
    # sable), `systemd-analyze --user` ne s'initialise pas — et le contrôle disait
    # « aucun cycle » sans avoir rien jugé. Un faux vert : il s'abstient.
    if "Failed to initialize manager" in sortie or "Failed to lookup RuntimeDirectory" in sortie:
        print("SKIP systemd --user ne s'initialise pas ici (pas de session : XDG_RUNTIME_DIR) — rien de jugé")
        return 0
    cycles = [l.strip() for l in sortie.splitlines() if "ordering cycle" in l]
    for l in cycles:
        print(f"  ❌ {l[:200]}")
    if cycles:
        print(f"VERDICT: {len(cycles)} cycle(s) au démarrage — systemd supprimera une unité "
              "au prochain boot ; retirer l'`After=` qui le ferme")
        return 1
    print("VERDICT: ✅ aucun cycle entre les unités du démarrage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
