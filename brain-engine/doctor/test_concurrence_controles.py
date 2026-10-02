#!/usr/bin/env python3
"""Un contrôle lancé deux fois accuse-t-il ?

Tous les contrôles écrits jusqu'ici mesurent un **état** : un fichier existe, un
registre s'accorde, un dump se recharge. Aucun ne mesurait un **comportement** —
ce qui arrive quand on interrompt, quand on duplique, quand on presse.

Le 04/09, trois défauts sont sortis de là, tous invisibles à l'unité :

    SIGPIPE tuait le contrôle d'isolation 2 fois sur 10, en silence
    le témoin de discipline Dolt accusait quand deux passes se croisaient
    le témoin du corpus laissait un abri, puis s'abstenait sans qu'on le voie

Les trois ont été trouvés à la main, en lançant deux fois la même chose. Ce
fichier rend le geste permanent.

**La règle éprouvée** : sous concurrence, un contrôle a le droit de **tenir son
verdict** ou de **s'abstenir en le disant**. Il n'a jamais le droit d'**accuser**.
Un faux rouge coûte plus qu'un silence : il finit par être ignoré, et le vrai
rouge avec lui.

    python3 tools/test_concurrence_controles.py --brain ~/Dev/Brain

Ne sont éprouvés que les contrôles qui **touchent à un état partagé** — la base,
l'index, le système de fichiers du brain. Ceux qui ne lisent que des fichiers
sans écrire n'ont rien à craindre de la concurrence, et les lancer deux fois ne
prouverait rien.

Sortie 1 si un contrôle accuse alors qu'il était vert tout seul.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import subprocess
import sys
from pathlib import Path

OUTILS = Path(__file__).resolve().parent

# Ceux qui écrivent, gèlent, purgent ou posent des verrous. Les autres — ceux
# qui lisent des fichiers et rendent un avis — sont hors sujet ici.
EPROUVES = [
    ("discipline d'écriture Dolt", "test_dolt_discipline.py", []),
    ("témoin du corpus",           "test_index_corpus.py",    []),
    ("index vs corpus",            "index_purge.py",          ["--check"]),
]


def joue(outil: str, brain: Path, extra: list[str]) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(OUTILS / outil), "--brain", str(brain),
                        *extra], capture_output=True, text=True, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(code: int, sortie: str) -> str:
    """vert · abstenu · accuse — dans le vocabulaire du doctor."""
    if any(l.startswith("SKIP") for l in sortie.splitlines()):
        return "abstenu"
    return "vert" if code == 0 else "accuse"


def raisons(sortie: str, maxi: int = 6) -> list[str]:
    """Ce qu'un contrôle a dit en rougissant : ses lignes ❌ ou SKIP, sinon sa fin.

    Le 2/10, « témoin du corpus — accuse même seul, rien à conclure » : la sortie
    était jetée, et ce rouge n'a jamais pu être diagnostiqué — relancé seul, le
    témoin était vert. Un rouge qu'on ne montre pas est perdu."""
    lignes = [l.rstrip() for l in sortie.splitlines() if l.strip()]
    dites = [l for l in lignes if "❌" in l or l.lstrip().startswith("SKIP")]
    return (dites or lignes[-3:])[:maxi]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    brain = args.brain.expanduser().resolve()

    print("\nCONCURRENCE — un contrôle lancé deux fois accuse-t-il ?\n")
    echecs = []

    for nom, outil, extra in EPROUVES:
        if not (OUTILS / outil).is_file():
            print(f"  ⏭  {nom:30} outil absent")
            continue

        # D'abord seul : sans ça, un rouge légitime passerait pour un défaut de
        # concurrence. On ne compare que ce qui était vert.
        code, sortie = joue(outil, brain, extra)
        seul = verdict(code, sortie)
        if seul != "vert":
            print(f"  ⏭  {nom:30} {seul} même seul — rien à conclure sur la concurrence")
            for l in raisons(sortie):
                print(f"       │ {l.strip()}")
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a, b = [f.result() for f in
                    [pool.submit(joue, outil, brain, extra) for _ in range(2)]]
        verdicts = sorted([verdict(*a), verdict(*b)])

        accuse = "accuse" in verdicts
        etat = "❌" if accuse else "✅"
        print(f"  {etat} {nom:30} seul: vert · à deux: {', '.join(verdicts)}")
        if accuse:
            echecs.append(nom)
            for code, sortie in (a, b):
                if verdict(code, sortie) == "accuse":
                    for l in raisons(sortie):
                        print(f"       │ {l.strip()}")

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} contrôle(s) accusent sous concurrence : "
              f"{', '.join(echecs)}")
        print("     Un faux rouge coûte plus qu'un silence — il finit ignoré,")
        print("     et le vrai rouge avec lui. Un identifiant d'exécution ou un")
        print("     verrou d'exclusion suffit, selon que l'état est propre ou"
              " partagé.\n")
        return 1
    print("  ✅ aucun contrôle n'accuse quand on le lance deux fois\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
