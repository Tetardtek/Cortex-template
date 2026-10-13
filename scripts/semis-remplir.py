#!/usr/bin/env python3
# brain-distribuable: oui
"""Remplir `focus.md`, semé du gabarit, pour l'instance qui naît.

    python3 scripts/semis-remplir.py --brain <dossier> --nom <brain_name> [--date AAAA-MM-JJ]

Le gabarit sème un `focus.md` à marqueurs : `<BRAIN_ROOT>`, `<DATE>`, une instance
nommée en dur (« **prod** ») et trois projets d'exemple présentés comme actifs
(`my-saas-app`, `my-game`, `my-website`). Rien ne les remplissait : le premier
briefing d'un brain neuf lisait des marqueurs et des projets qui n'existent pas
(issue #22). `brain init` appelle ce script, à chaque passage.

Ce qu'il fait, et seulement tant que c'est encore le semis :

- `<BRAIN_ROOT>` → le dossier du brain ; `<DATE>` → la date du jour, en UTC (le brain
  compte en UTC) ;
- la ligne `> Instance : **<nom>** — <BRAIN_ROOT>` porte le nom de l'instance — elle
  n'est réécrite que si elle porte encore le marqueur : un nom posé à la main reste ;
- une ligne de tableau qui nomme un projet d'exemple ET se dit exemple (« Exemple »,
  « exemple a remplacer », « scaffold ») est retirée ; un tableau qui n'a plus de ligne
  devient « *(aucun projet …)* », que le briefing lit comme tel ; la puce « Remplacer les
  exemples par vos vrais projets » devient « Déclarer vos premiers projets ».

Idempotent : relancé, il ne change rien ; sur un brain déjà rempli, il ne touche que les
marqueurs qui y restent. Un `focus.md` absent, ou qui est un lien, n'est pas touché.
Sortie 0 ; la liste de ce qui a changé sur stdout (rien si rien).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

EXEMPLES = ("my-saas-app", "my-game", "my-website")
SE_DIT_EXEMPLE = re.compile(r"exemple|scaffold", re.I)
LIGNE_INSTANCE = re.compile(r"^(> Instance : \*\*)[^*]*(\*\* — `?)<BRAIN_ROOT>(`?)\s*$")
PROCHAINE_SEMIS = "- Remplacer les exemples par vos vrais projets"
PROCHAINE_NEUVE = "- Déclarer vos premiers projets dans `projets/`\n"
AUCUN = "*(aucun projet pour l'instant — le premier se déclare dans `projets/`, depuis `projets/_template.md`)*"


def cellules(ligne: str) -> list[str] | None:
    """Les cellules d'une ligne de tableau markdown, ou None."""
    s = ligne.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    return [c.strip().strip("*").strip() for c in s[1:-1].split("|")]


def est_exemple(ligne: str) -> bool:
    c = cellules(ligne)
    return bool(c) and any(x in EXEMPLES for x in c) and bool(SE_DIT_EXEMPLE.search(ligne))


def est_separateur(ligne: str) -> bool:
    c = cellules(ligne)
    return bool(c) and all(re.fullmatch(r":?-{3,}:?", x) for x in c)


def sans_exemples(lignes: list[str]) -> tuple[list[str], int]:
    """Retire les lignes d'exemple ; un tableau vidé devient la ligne « aucun projet »."""
    sortie: list[str] = []
    retirees = 0
    i = 0
    while i < len(lignes):
        # Un tableau : un en-tête, un séparateur, puis ses lignes.
        if cellules(lignes[i]) is not None and i + 1 < len(lignes) and est_separateur(lignes[i + 1]):
            j = i + 2
            corps = []
            while j < len(lignes) and cellules(lignes[j]) is not None:
                corps.append(lignes[j])
                j += 1
            gardees = [l for l in corps if not est_exemple(l)]
            retirees += len(corps) - len(gardees)
            if corps and not gardees:
                sortie.append(AUCUN + "\n")
            else:
                sortie.extend([lignes[i], lignes[i + 1], *gardees])
            i = j
            continue
        sortie.append(lignes[i])
        i += 1
    return sortie, retirees


def remplir(texte: str, racine: str, nom: str, date: str) -> tuple[str, list[str]]:
    faits: list[str] = []
    lignes = texte.splitlines(keepends=True)
    for k, l in enumerate(lignes):
        fin = "\n" if l.endswith("\n") else ""
        m = LIGNE_INSTANCE.match(l.rstrip("\n"))
        if m:
            lignes[k] = f"{m.group(1)}{nom}{m.group(2)}{racine}{m.group(3)}{fin}"
            faits.append(f"l'instance : {nom}")
    texte = "".join(lignes)
    if "<BRAIN_ROOT>" in texte:
        texte = texte.replace("<BRAIN_ROOT>", racine)
        faits.append("<BRAIN_ROOT>")
    if "<DATE>" in texte:
        texte = texte.replace("<DATE>", date)
        faits.append("<DATE>")
    lignes, n = sans_exemples(texte.splitlines(keepends=True))
    if n:
        faits.append(f"{n} ligne(s) de projets d'exemple retirée(s)")
    if any(l.rstrip("\n") == PROCHAINE_SEMIS for l in lignes):
        lignes = [PROCHAINE_NEUVE if l.rstrip("\n") == PROCHAINE_SEMIS else l for l in lignes]
        faits.append("la prochaine frontière")
    return "".join(lignes), faits


def main() -> int:
    p = argparse.ArgumentParser(description="Remplit focus.md, semé du gabarit")
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--nom", required=True)
    p.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    a = p.parse_args()
    focus = a.brain / "focus.md"
    if not focus.is_file() or focus.is_symlink():
        return 0
    avant = focus.read_text(encoding="utf-8")
    apres, faits = remplir(avant, str(a.brain), a.nom, a.date)
    if apres != avant:
        focus.write_text(apres, encoding="utf-8")
        print(", ".join(faits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
