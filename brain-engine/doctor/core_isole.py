#!/usr/bin/env python3
"""Le CORE tient-il debout tout seul ? —,.

`core/README.md` pose deux interdits, et ils sont la raison d'être du CORE :

    1. le CORE ne dépend de rien du moteur — ni `db`, ni `server`, ni `rag`
    2. aucun module ne déduit un chemin de sa propre position, ni ne lit
       l'environnement : il REÇOIT sa configuration

Ces deux propriétés sont ce que « le CORE tient debout seul » veut dire. Elles
étaient **vraies le 11/09 et vérifiées par personne** — une propriété qu'aucun
contrôle ne tient se perd au premier `import` pressé.

    python3 tools/core_isole.py

── Pourquoi l'AST et pas `grep` ────────────────────────────────────────────

`core/persistance.py` **parle** de `Path(__file__).parent.parent` et de
`os.environ` — dans sa docstring, pour expliquer ce que l'ancien moteur faisait
et pourquoi il ne le fait plus. Un `grep` rougirait sur cette explication.

L'AST ne voit que le code exécuté : une docstring n'est pas un appel. Le
contrôle peut donc exiger l'interdit **sans interdire d'en parler** — ce qui
compte, parce que le motif interdit doit rester documenté à l'endroit où il a
été retiré.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Ce que le CORE a le droit d'importer, et rien d'autre.
#
#   stdlib      via sys.stdlib_module_names — pas une liste tenue a la main
#   core        ses propres briques
#   tiers       declares UN PAR UN, avec ce qu'ils coutent en portabilite
TIERS_AUTORISES = {
    "pymysql":  "le pilote Dolt/MySQL — la persistance en a besoin",
    "numpy":    "le calcul vectoriel de la recherche",
}

# Ce qui trahit un module qui devine au lieu de recevoir. Ce sont des APPELS,
# reperes dans l'arbre — pas des chaines dans un fichier.
DEVINE = {
    "__file__":    "déduit un chemin de sa propre position",
    "home":        "`Path.home()` — suppose un utilisateur",
    "getenv":      "lit l'environnement au lieu de recevoir",
    "environ":     "lit l'environnement au lieu de recevoir",
    "expanduser":  "résout un `~` — suppose un utilisateur",
}


def modules_importes(arbre: ast.AST) -> set[str]:
    mods = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.add(n.module.split(".")[0])
    return mods


def devinettes(arbre: ast.AST) -> set[str]:
    """Les motifs de déduction, dans le CODE — les docstrings n'en sont pas."""
    trouves = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name) and n.id in DEVINE:
            trouves.add(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in DEVINE:
            trouves.add(n.attr)
    return trouves


def examiner(dossier: Path) -> tuple[list[str], list[str], int]:
    imports_interdits, deductions, examines = [], [], 0
    stdlib = sys.stdlib_module_names
    for f in sorted(dossier.glob("*.py")):
        if f.name.startswith("test") or f.name == "tests.py":
            continue          # les tests ont le droit de monter des fixtures
        examines += 1
        arbre = ast.parse(f.read_text(encoding="utf-8"))
        for m in sorted(modules_importes(arbre)):
            if m in stdlib or m == "core" or m in TIERS_AUTORISES:
                continue
            imports_interdits.append(f"{f.name} importe `{m}`")
        for d in sorted(devinettes(arbre)):
            deductions.append(f"{f.name} : {DEVINE[d]}  (`{d}`)")
    return imports_interdits, deductions, examines


def main() -> int:
    p = argparse.ArgumentParser(description="Le CORE dépend-il de quelque chose ?")
    p.add_argument("--core", type=Path, default=RACINE / "core")
    p.add_argument("--brain", type=Path, help="ignoré — accepté pour brain_doctor")
    a = p.parse_args()

    if not a.core.is_dir():
        print(f"⏭️  SKIP {a.core} introuvable.", file=sys.stderr)
        return 0

    interdits, deductions, n = examiner(a.core)

    print(f"  {'✅' if not interdits else '❌'} indépendance — {n} brique(s), "
          + ("aucun import hors stdlib/core/tiers déclarés"
             if not interdits else f"{len(interdits)} import(s) interdit(s)"))
    for i in interdits:
        print(f"     ❌ {i}", file=sys.stderr)

    print(f"  {'✅' if not deductions else '❌'} configuration reçue — "
          + ("aucune brique ne devine son environnement"
             if not deductions else f"{len(deductions)} déduction(s)"))
    for d in deductions:
        print(f"     ❌ {d}", file=sys.stderr)

    if interdits or deductions:
        print(f"\n❌ le CORE ne tient plus debout seul — c'est ce que "
              f"« tenir debout seul » veut dire.", file=sys.stderr)
        return 1

    print(f"  ℹ️  tiers déclarés : "
          + " · ".join(f"{k} ({v})" for k, v in sorted(TIERS_AUTORISES.items())))
    print(f"\n✅ le CORE tient debout seul — {n} briques, 0 dépendance au moteur")
    return 0


if __name__ == "__main__":
    sys.exit(main())
