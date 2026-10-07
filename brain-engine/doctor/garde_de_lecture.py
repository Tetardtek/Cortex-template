#!/usr/bin/env python3
"""Le garde de lecture est-il branché — et éprouvé sur ce Claude Code ?

Ce qui passerait inaperçu sans lui : **un sous-agent de Claude Code (le worker
de l'autonomie, un Explore…) qui lit le personnel sans que rien ne l'arrête.**
Le garde est un hook `PreToolUse` du projet (`scripts/garde-lecture.py`), et
son branchement vit dans `.claude/settings.json` — un fichier que le gabarit ne
livre pas : le setup et `brain maj` l'y ajoutent. Un fichier refait à la main,
une machine installée avant lui, et le garde est absent sans un mot.

La mesure est celle du garde lui-même (`garde-lecture.py etat`) : un seul
exemplaire de ce que « branché » veut dire.

── La version éprouvée ────────────────────────────────────────────

Le garde reconnaît un sous-agent au champ `agent_type` que Claude Code passe à
ses hooks — mesuré, non documenté. Une version qui le retire, et le garde
laisse tout passer, branché ou non. `scripts/essai-garde-lecture.sh` l'éprouve
de bout en bout et note, par machine, la version de Claude Code sur laquelle il
a tenu (`${XDG_STATE_HOME:-~/.local/state}/brain/garde-lecture.json`). Ce
contrôle la compare à `claude --version` :

    même version             éprouvé — dit, et sur quelle version
    plus récente, ou autre   ⚠️ « rejouer l'essai »
    jamais éprouvé ici       ⚠️ « lancer l'essai »
    pas de `claude`          rien à comparer, dit

L'écart est un **avertissement**, pas un rouge : Claude Code se met à jour seul,
souvent, et un rouge à chaque version deviendrait un rouge qu'on ne lit plus.
Le rouge reste au garde absent — et à l'essai lui-même, quand il ne tient pas.

    python3 tools/garde_de_lecture.py --brain ~/Dev/Brain

Sortie 0 branché (ou pas de garde sur ce brain, dit), 1 absent ou illisible.
Il n'écrit rien.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ESSAI = "bash scripts/essai-garde-lecture.sh"


def note_par_defaut() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "brain" / "garde-lecture.json"


def version_de(texte: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", texte or "")
    return tuple(int(x) for x in m.groups()) if m else None


def version_installee(claude: str | None) -> tuple[int, ...] | None:
    """`claude --version` — None sans `claude`, ou s'il ne dit pas de version."""
    if not claude:
        return None
    try:
        r = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return version_de(r.stdout)


def version_eprouvee(note: Path) -> tuple[tuple[int, ...] | None, str]:
    """(la version notée par l'essai, sa date) — (None, '') si rien n'est noté ou lisible."""
    try:
        d = json.loads(note.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ""
    if not isinstance(d, dict):
        return None, ""
    return version_de(str(d.get("claude_code", ""))), str(d.get("verifie_le", ""))[:10]


def la_version(installee, eprouvee, date: str) -> str:
    """Ce que le contrôle dit de la version — une phrase, un avertissement s'il faut agir."""
    v = lambda t: ".".join(map(str, t))  # noqa: E731
    if installee is None:
        return "Claude Code introuvable — la version éprouvée n'est pas comparée"
    if eprouvee is None:
        return (f"⚠️ jamais éprouvé de bout en bout sur cette machine (Claude Code {v(installee)}) "
                f"— lancer l'essai : {ESSAI}")
    if installee == eprouvee:
        return f"éprouvé sur Claude Code {v(eprouvee)}" + (f" le {date}" if date else "")
    sens = "plus récent" if installee > eprouvee else "différent"
    return (f"⚠️ Claude Code {v(installee)} est {sens} que la dernière vérification "
            f"({v(eprouvee)}) — rejouer l'essai : {ESSAI}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--claude", default=None,
                   help="le binaire de Claude Code (défaut : `claude` du PATH)")
    p.add_argument("--note", type=Path, default=None,
                   help="la note de l'essai (défaut : $XDG_STATE_HOME/brain/garde-lecture.json)")
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()
    garde = brain / "scripts" / "garde-lecture.py"
    if not garde.is_file():
        print("⏭️  pas de garde de lecture sur ce brain (scripts/garde-lecture.py) — rien à juger")
        return 0
    r = subprocess.run([sys.executable, str(garde), "etat", "--brain", str(brain)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 2:
        # Un garde d'avant `etat` répond par son mode d'emploi : il ne sait pas dire s'il est branché.
        print("❌ ce garde-lecture.py ne sait pas dire son état (antérieur à `etat`) — brain maj")
        return 1
    etat = (r.stdout or r.stderr).strip() or f"garde-lecture.py etat : code {r.returncode}"
    if r.returncode != 0:
        print(etat)
        return 1
    # Branché : la version sur laquelle il a été éprouvé. Un brain qui n'a pas l'essai ne se
    # le voit pas recommander.
    if not (brain / "scripts" / "essai-garde-lecture.sh").is_file():
        print(f"VERDICT: {etat}")
        return 0
    eprouvee, date = version_eprouvee(a.note or note_par_defaut())
    installee = version_installee(a.claude if a.claude is not None else shutil.which("claude"))
    print(f"VERDICT: {etat} — {la_version(installee, eprouvee, date)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
