#!/usr/bin/env python3
# brain-distribuable: oui
"""brain etat — l'instant du brain : qui travaille, ce qui est verrouillé, ce qui attend.

    brain etat              le résumé : les sessions ouvertes ici, les verrous, les signaux — rien ne bouge
    brain etat --verrous    les verrous seulement

Le doctor juge (vert, rouge, dérives) ; `etat` montre l'instant ; `brain_state` (MCP) décrit
l'infrastructure. Chaque section délègue à celui qui sait — `bsi-query.sh open` (le geste de
`brain sessions`), `file-lock.sh list`, `bsi-signal.sh inbox` — et n'en refait aucune lecture.

Une source qui ne répond pas se dit illisible, jamais « aucun » : l'ancien `brain-status.sh`
lisait des dossiers (`claims/`, `locks/`) que plus rien n'écrivait depuis que le BSI vit en
base, et répondait « (aucun) » à une session ouverte (mesuré le 15/10). Une section illisible
rend le résumé rouge (sortie 1).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
BRAIN = ICI.parent

SESSIONS = ("Sessions ouvertes ici", ["bsi-query.sh", "open"],
            "→ brain sessions --toutes : celles des autres machines")
VERROUS = ("Verrous", ["file-lock.sh", "list"], None)
SIGNAUX = ("Signaux en attente", ["bsi-signal.sh", "inbox"],
           "→ brain signaux --accuser <sig_id> : une fois traité")


def racine_des_donnees() -> Path:
    """Le dossier de données : un programme installé à part (la marque de `donnees.py`) n'est
    pas le brain. Sans `donnees.py` (un banc qui ne copie que ce script) : la position."""
    src = BRAIN / "brain-engine" / "donnees.py"
    if not src.is_file():
        return BRAIN
    import importlib.util
    spec = importlib.util.spec_from_file_location("_brain_donnees", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.trouver_donnees(BRAIN, env_d_abord=False)[0]
    except RuntimeError as exc:
        raise SystemExit(f"❌ {exc}")


def en_tete(donnees: Path) -> None:
    machine = "?"
    local = donnees / "brain-compose.local.yml"
    if local.is_file():
        m = re.search(r"^machine:\s*['\"]?([^'\"#\s]+)", local.read_text(encoding="utf-8"), re.M)
        machine = m.group(1) if m else "?"
    r = subprocess.run(["git", "-C", str(donnees), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        b = subprocess.run(["git", "-C", str(donnees), "branch", "--show-current"],
                           capture_output=True, text=True).stdout.strip()
        branche = b or "tête détachée"
    else:
        branche = "pas un dépôt git"
    print(f"🧠 brain etat — {datetime.now(timezone.utc):%H:%M} UTC · machine {machine}")
    print(f"   {donnees} · {branche}")


def section(titre: str, cmd: list[str], renvoi: str | None) -> bool:
    print(f"\n── {titre} " + "─" * max(4, 46 - len(titre)))
    try:
        r = subprocess.run(["bash", str(ICI / cmd[0]), *cmd[1:]], capture_output=True, text=True,
                           timeout=120)
        code, sortie = r.returncode, (r.stdout + r.stderr).rstrip()
    except subprocess.TimeoutExpired:
        code, sortie = "délai dépassé", ""
    if code != 0:
        print(f"  ⚠️  je n'ai pas pu regarder ({' '.join(cmd)} : code {code}) — ce n'est pas un vide")
        for ligne in sortie.splitlines()[-3:]:
            print(f"     {ligne}")
        return False
    for ligne in sortie.splitlines() or ["(la source n'a rien dit)"]:
        print(f"  {ligne}")
    if renvoi:
        print(f"  {renvoi}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(prog="brain etat",
                                description="L'instant du brain : qui travaille, ce qui est verrouillé, ce qui attend.")
    p.add_argument("--verrous", action="store_true", help="les verrous seulement")
    a = p.parse_args()
    if a.verrous:
        return 0 if section(*VERROUS) else 1
    en_tete(racine_des_donnees())
    lues = [section(*s) for s in (SESSIONS, VERROUS, SIGNAUX)]
    return 0 if all(lues) else 1


if __name__ == "__main__":
    sys.exit(main())
