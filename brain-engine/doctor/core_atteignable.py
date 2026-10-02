#!/usr/bin/env python3
"""Le CORE est-il atteignable depuis le brain ? —.

Tranché le 11/09 : le CORE est un **paquet**, installé en éditable
(`pip install -e`). Le brain dépend du programme sans le contenir — c'est
`core/README.md` appliqué : *« le CORE est un programme, `brain/` est de la
data »*.

Une dépendance qui tient à une installation se perd en silence : nouvelle
machine, environnement recréé, `pip` qui oublie. Elle ne se signale alors qu'au
moment où une porte l'utilise, par une `ImportError` en pleine session.

    python3 tools/core_atteignable.py --brain ~/Dev/Brain

── Le piège que ce contrôle évite ──────────────────────────────────────────

Lancé depuis le dépôt `myeline`, `import core` **réussit sans installation** :
`sys.path[0]` est le répertoire courant. Un contrôle naïf serait donc vert
précisément là où on l'écrit, et rouge nulle part.

Il teste donc l'import dans un **sous-processus lancé depuis un répertoire
neutre**, avec le `cwd` du brain — les conditions réelles d'une porte.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Les briques que des consommateurs du brain vont importer. La liste vient des
# cinq equivalences mesurees le 11/09 — chacune est un branchement a venir.
BRIQUES = {
    "core.zones":       "pre-commit-zone — la regle des zones",
    "core.bsi":         "POST /bsi/claims — le mutex de scope",
    "core.indexation":  "embed.py — le decoupage",
    "core.recherche":   "search.py — le classement",
    "core.persistance": "db.py — la traduction SQL",
}


def main() -> int:
    p = argparse.ArgumentParser(description="Le CORE est-il installé et importable ?")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()
    if not brain.is_dir():
        print("⏭️  SKIP brain introuvable.", file=sys.stderr)
        return 0

    # Depuis le BRAIN. Là où le CORE est un paquet installé (l'instance), on
    # n'ajoute rien au chemin : si l'import réussit, c'est que le paquet est là.
    # (Un ancien commentaire annonçait un `-I` que la commande n'a jamais passé.)
    # Un fork reçoit le CORE COPIÉ dans `brain-engine/core/`, sans installation :
    # le moteur le trouve parce qu'il met `brain-engine/` dans son chemin. On le
    # cherche donc comme lui — et seulement quand le brain le livre, pour que
    # l'instance, qui ne le livre pas, reste jugée sur son paquet installé.
    livre = (brain / "brain-engine" / "core" / "__init__.py").is_file()
    prelude = "sys.path.insert(0, 'brain-engine')\n" if livre else ""
    code = (
        "import json, sys\n"
        + prelude +
        "resultat = {}\n"
        "try:\n"
        "    import core\n"
        "    resultat['version'] = getattr(core, '__version__', '?')\n"
        "    resultat['origine'] = core.__file__\n"
        "except Exception as exc:\n"
        "    resultat['erreur'] = f'{type(exc).__name__}: {exc}'\n"
        "    print(json.dumps(resultat)); sys.exit(0)\n"
        "for m in " + repr(sorted(BRIQUES)) + ":\n"
        "    try:\n"
        "        __import__(m)\n"
        "    except Exception as exc:\n"
        "        resultat.setdefault('manquantes', []).append(f'{m} — {type(exc).__name__}')\n"
        "print(json.dumps(resultat))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(brain),
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"❌ le sous-processus a échoué : {r.stderr.strip()[:200]}",
              file=sys.stderr)
        return 1

    import json
    try:
        d = json.loads(r.stdout.strip() or "{}")
    except Exception:                                          # noqa: BLE001
        print(f"❌ sortie illisible : {r.stdout[:200]}", file=sys.stderr)
        return 1

    if "erreur" in d:
        # Le remède dépend de d'où vient le CORE : livré avec le brain (un
        # fork), ou installé depuis son dépôt (l'instance d'origine).
        if livre:
            remede = ("     le CORE livré est dans brain-engine/core/ : vérifier ses\n"
                      "     dépendances — brain-engine/.venv/bin/pip install -r "
                      "brain-engine/requirements.txt")
        else:
            remede = ("     installer le paquet du CORE depuis son dépôt :\n"
                      "     python3 -m pip install -e <dépôt du CORE> --user "
                      "--no-deps --break-system-packages")
        print(f"❌ le CORE n'est pas atteignable depuis {brain} :\n"
              f"     {d['erreur']}\n\n"
              f"   Le brain en dépend pour cinq branchements. Réparation :\n"
              f"{remede}", file=sys.stderr)
        return 1

    origine = d.get("origine", "?")
    print(f"  ✅ `core` importable depuis le brain — v{d.get('version', '?')}")
    print(f"     {origine}")

    # Editable ou fige ? Les deux marchent, mais ce n'est pas la meme chose :
    # une copie figee ne verrait plus les corrections du depot.
    editable = "Gitea/myeline" in origine or "site-packages" not in origine
    print(f"  {'✅' if editable else 'ℹ️ '} mode "
          + ("éditable — le dépôt fait foi" if editable
             else "figé — une copie, les corrections du dépôt ne s'y voient pas"))

    if d.get("manquantes"):
        print(f"\n❌ {len(d['manquantes'])} brique(s) du CORE n'ont pas pu être "
              f"importées :", file=sys.stderr)
        for m in d["manquantes"]:
            print(f"     {m}", file=sys.stderr)
        return 1
    print(f"  ✅ les {len(BRIQUES)} briques attendues s'importent")
    for nom, qui in sorted(BRIQUES.items()):
        print(f"     {nom:18} {qui}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
