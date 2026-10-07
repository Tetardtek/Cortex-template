#!/usr/bin/env python3
"""Ce que git garde correspond-il à ce que les niveaux déclarent ?

Le cinquième et dernier des mécanismes qui redéclaraient le niveau chacun à leur
façon. `.gitignore` décide de ce qui est versionné ; `NIVEAUX.yml` dit ce qui
devrait l'être.

    python3 tools/niveaux_vs_git.py --brain ~/Dev/Brain

── Deux distinctions que le premier instrument n'avait pas ─────────────────

**Gitignoré n'est pas « non versionné ».** `brain-ui/`, `toolkit/`, `learning/`,
`profil/`, `todo/`, `draw/`, `audits/` et `progression/` portent leur propre
`.git` : ils sont versionnés ailleurs. Les compter comme perdus était faux, et
c'est ce que la première mesure a fait — quatre désaccords annoncés, quatre faux
positifs.

**`squelette: versionné` existe déjà.** `locks/` et `SUPERVISOR-STATE.md` sont de
l'`etat` dont seule la FORME se distribue — un `.gitkeep`, un gabarit. L'attribut
le disait ; l'instrument ne le lisait pas.

── Ce que « selon » ne disait pas ──────────────────────────────────────────

Le tableau des niveaux dit `donnee → versionné : selon`. Mesuré sur les dix-huit
`donnee` du brain, ce n'était pas ambigu — c'était **non déclaré** :

    versionne: ici             suivi par le dépôt brain          12
    versionne: depot-separe    satellite git, versionné ailleurs  6
    versionne: jamais          reste sur la machine, gitignoré    1  

── Une vue n'est pas un oubli de versionner ────────────────────────────────

`agents/` peut être une VUE (`vue_de: [noyau/agents/, instance/agents/]`) : des
liens construits par `brain vue`, ignorés par git — la nature `programme` vit dans
ses sources, que leurs propres entrées jugent. Quand sa première source existe,
une vue DOIT être ignorée ; suivie par git, elle rougit. Sans source, l'entrée se
juge comme avant.

Sortie 1 si une entrée est versionnée autrement qu'elle ne le déclare.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

VERSIONNE = ("invariant", "programme", "moteur")
JAMAIS = ("etat", "artefact")


sys.path.insert(0, str(Path(__file__).resolve().parent))
from _programme_a_part import programme_a_part  # noqa: E402 — le programme installé à part


def gitignore(racine: Path, chemin: str) -> bool:
    return subprocess.run(["git", "-C", str(racine), "check-ignore", "-q", chemin],
                          capture_output=True).returncode == 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    racine = args.brain.expanduser().resolve()

    try:
        import yaml
    except Exception:                                      # noqa: BLE001
        print("\n  ⏭  PyYAML absent — rien mesuré.\n")
        return 0

    source = racine / "NIVEAUX.yml"
    if not source.is_file():
        print("\n  ❌ `NIVEAUX.yml` introuvable — le contrôle refuse de juger.\n")
        return 1
    entrees = yaml.safe_load(source.read_text(encoding="utf-8")).get("entrees", {})

    fautifs, depots, ici, non_declares, vues, a_part = [], 0, 0, [], 0, 0
    for nom, val in sorted(entrees.items()):
        niveau = val.get("niveau") if isinstance(val, dict) else val
        court = nom.rstrip("/")
        cible = racine / court
        if not cible.exists():
            continue

        sources = val.get("vue_de") if isinstance(val, dict) else None
        if sources and (racine / sources[0]).is_dir():
            if gitignore(racine, court):
                vues += 1
            else:
                fautifs.append((nom, "vue", f"une vue de {sources[0]}, pourtant suivie par git"))
            continue

        # Un lien vers le programme installé à part : versionné avec le programme, pas
        # ici — ignoré par le git du brain, comme il se doit ; suivi, il rougit.
        if programme_a_part(cible) is not None:
            if gitignore(racine, court):
                a_part += 1
            else:
                fautifs.append((nom, str(niveau), "un lien vers le programme installé à part, "
                                "pourtant suivi par git"))
            continue

        depot_propre = (cible / ".git").exists()
        ignore = gitignore(racine, court)
        squelette = isinstance(val, dict) and val.get("squelette") == "versionné"
        mode = val.get("versionne") if isinstance(val, dict) else None

        # Un dépôt séparé est versionné — ailleurs. Ce n'est jamais un défaut.
        if depot_propre:
            depots += 1
            if niveau == "donnee" and mode != "depot-separe":
                non_declares.append((nom, "porte un .git, déclare "
                                     f"`versionne: {mode or '—'}`"))
            continue

        if niveau in VERSIONNE and ignore:
            fautifs.append((nom, str(niveau), "déclaré versionné, gitignoré"))
        elif niveau in JAMAIS and not ignore and not squelette:
            fautifs.append((nom, str(niveau), "déclaré non versionné, suivi"))
        elif niveau == "donnee":
            if mode is None:
                non_declares.append((nom, "`donnee` sans `versionne:`"))
            elif mode == "jamais":
                # Ajouté le 10/09 avec. Le vocabulaire n'avait que
                # `ici` et `depot-separe` : aucun mot pour « cette donnée reste
                # sur la machine ». La décision de l'owner — sortir `identity/`
                # du dépôt sans le sortir du disque — n'était pas exprimable,
                # et le contrôle rougissait sur une déclaration devenue fausse
                # faute de valeur pour dire le vrai.
                if not ignore:
                    fautifs.append((nom, "donnee",
                                    "déclaré `jamais`, pourtant suivi par git"))
                else:
                    ici += 1
            elif mode == "ici" and ignore:
                fautifs.append((nom, "donnee", "déclaré `ici`, gitignoré"))
            elif mode == "ici":
                ici += 1

    print("\nNIVEAUX → GIT — ce que le dépôt garde\n")
    print(f"  {len(entrees)} entrées · {depots} dépôts séparés · {ici} suivies ici"
          + (f" · {vues} vue(s), ignorée(s) comme il se doit" if vues else "")
          + (f" · {a_part} dans le programme installé à part" if a_part else ""))

    if fautifs or non_declares:
        print()
        for nom, niveau, quoi in fautifs:
            print(f"  ❌ {nom:<26} `{niveau}` — {quoi}")
        for nom, quoi in non_declares:
            print(f"  ❌ {nom:<26} {quoi}")
        print("\n     `NIVEAUX.yml` est la source. Un répertoire gitignoré qui porte")
        print("     son propre `.git` n'est pas perdu : il déclare")
        print("     `versionne: depot-separe`.\n")
        return 1

    print("\n  ✅ git garde ce que les niveaux déclarent\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
