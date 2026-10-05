#!/usr/bin/env python3
"""Un agent du noyau renvoie-t-il vers un fichier déprécié ?

`helloWorld` présentait `profil/session-types.md` comme la source des couches de
contexte — un fichier `status: deprecated` depuis le 20/03, qui le dit en titre.
Aucun lien n'était mort : le fichier existe. Le contrôle des liens morts ne
pouvait pas le voir ; la session qui lisait l'agent suivait le renvoi.

    une référence entre accents graves, dans `noyau/agents/*.md` (hors archive/),
    vers un fichier du brain dont le frontmatter dit
    `status: deprecated | archived | superseded | retired`

Ne rougit pas : une ligne qui DIT que la cible est retirée (« déprécié »,
« retiré », « archivé », « remplacé », « superseded »…) — c'est un renvoi
historique, assumé —, ni une ligne de changelog (`| 20…`). Un fichier absent
n'est pas jugé ici : c'est le travail des liens morts.

    python3 tools/renvois_deprecies.py --brain ~/Dev/Brain

Il s'éprouve avant de juger. Sortie 1 si un renvoi tient vers un fichier déprécié.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ETATS = {"deprecated", "archived", "superseded", "retired"}
DECLARE = re.compile(r"déprécié|deprecated|retir|archiv|supersed|remplac|obsolète|n'existe plus", re.I)
REFERENCE = re.compile(r"`(?:brain/)?([\w][\w./-]*\.(?:md|ya?ml|sh|py))`")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.S)
STATUT = re.compile(r'^status:\s*"?([\w-]+)', re.M)


def etat(fichier: Path) -> str | None:
    """L'état déprécié que déclare le frontmatter du fichier, ou None."""
    try:
        texte = fichier.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = FRONTMATTER.match(texte)
    s = STATUT.search(m.group(1)) if m else None
    return s.group(1).lower() if s and s.group(1).lower() in ETATS else None


def juger(brain: Path) -> tuple[list[str], int]:
    """(les renvois fautifs, le nombre d'agents lus)."""
    brain = Path(brain)
    connus: dict[str, str | None] = {}
    defauts, agents = [], sorted((brain / "noyau" / "agents").glob("*.md"))
    for agent in agents:
        for n, ligne in enumerate(agent.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if ligne.startswith("| 20") or DECLARE.search(ligne):
                continue
            for chemin in REFERENCE.findall(ligne):
                if chemin not in connus:
                    cible = brain / chemin
                    connus[chemin] = etat(cible) if cible.is_file() else None
                if connus[chemin]:
                    defauts.append(f"noyau/agents/{agent.name}:{n} → `{chemin}` ({connus[chemin]})")
    return defauts, len(agents)


def auto_epreuve() -> list[str]:
    """Le défaut doit être vu, et les renvois sains ne pas rougir."""
    rates = []
    with tempfile.TemporaryDirectory(prefix="renvois-") as tmp:
        b = Path(tmp)
        (b / "noyau" / "agents").mkdir(parents=True)
        (b / "profil").mkdir()
        (b / "profil" / "vieux.md").write_text("---\nname: vieux\nstatus: deprecated\n---\n# vieux\n")
        (b / "profil" / "neuf.md").write_text("---\nname: neuf\nstatus: active\n---\n# neuf\n")
        agent = b / "noyau" / "agents" / "a.md"

        def voit(ligne: str) -> bool:
            agent.write_text(f"# a\n{ligne}\n")
            return bool(juger(b)[0])

        if not voit("Les couches : `profil/vieux.md`."):
            rates.append("non vu : un renvoi vers un fichier `status: deprecated`")
        if not voit("Les couches : `brain/profil/vieux.md`."):
            rates.append("non vu : le même renvoi, préfixé `brain/`")
        for sain, quoi in (("Les couches : `profil/neuf.md`.", "un renvoi vers un fichier actif"),
                           ("`profil/vieux.md` est déprécié — ne plus le lire.", "un renvoi qui dit le retrait"),
                           ("| 2026-03-20 | `profil/vieux.md` → `profil/neuf.md` |", "une ligne de changelog"),
                           ("Voir `profil/absent.md`.", "un fichier absent (les liens morts le jugent)")):
            if voit(sain):
                rates.append(f"rougit à tort : {quoi}")
    return rates


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    rates = auto_epreuve()
    if rates:
        print("\nLES RENVOIS DU NOYAU — l'auto-épreuve a échoué, rien n'est jugé :")
        for r in rates:
            print(f"  ❌ {r}")
        return 1
    if not (brain / "noyau" / "agents").is_dir():
        print(f"SKIP pas de `noyau/agents/` dans {brain}")
        return 0

    defauts, n = juger(brain)
    print("\nLES RENVOIS DU NOYAU\n")
    print("  auto-épreuve         le défaut vu (deux formes), quatre renvois sains ne rougissent pas")
    print(f"  agents lus           {n}")
    if not defauts:
        print("\n  ✅ aucun agent du noyau ne renvoie vers un fichier déprécié")
        return 0
    print()
    for d in defauts:
        print(f"  ❌ {d}")
    print("\n  Un renvoi vers un fichier retiré se suit sans erreur : le dire retiré sur la ligne,")
    print("  ou renvoyer vers ce qui l'a remplacé.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
