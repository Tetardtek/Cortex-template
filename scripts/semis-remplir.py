#!/usr/bin/env python3
# brain-distribuable: oui
"""Remplir les fichiers que le gabarit sème à marqueurs : `focus.md`, `PATHS.md`.

    python3 scripts/semis-remplir.py --brain <dossier> --nom <brain_name> [--date AAAA-MM-JJ]
    python3 scripts/semis-remplir.py --brain <dossier> --fichier PATHS.md [--projets <dossier>]

`brain init` les remplit (étapes 3.1 et 3.2) ; `brain maj` aussi, quand la version reçue
change leur semis (`scripts/maj.py`) : les mêmes fonctions, ici.

── focus.md ──

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

── PATHS.md ──

`<BRAIN_ROOT>`, `<HOME>` et `<PROJECTS_ROOT>` (par défaut : le dossier qui contient le brain ;
`--projets` en choisit un autre) se remplacent chacun pour lui-même, partout où ils
restent. Sur stdout, les marqueurs remplacés, séparés d'une espace.

Idempotent : relancé, il ne change rien ; sur un brain déjà rempli, il ne touche que les
marqueurs qui y restent. Un fichier absent, ou qui est un lien, n'est pas touché.
Sortie 0 ; ce qui a changé sur stdout (rien si rien).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXEMPLES = ("my-saas-app", "my-game", "my-website")
SE_DIT_EXEMPLE = re.compile(r"exemple|scaffold", re.I)
LIGNE_INSTANCE = re.compile(r"^(> Instance : \*\*)[^*]*(\*\* — `?)<BRAIN_ROOT>(`?)\s*$")
PROCHAINE_SEMIS = "- Remplacer les exemples par vos vrais projets"
PROCHAINE_NEUVE = "- Déclarer vos premiers projets dans `projets/`\n"
MARQUEURS_PATHS = ("<BRAIN_ROOT>", "<HOME>", "<PROJECTS_ROOT>")
MARQUEUR = re.compile(r"<[A-Z_]+>")
LIGNE_NOMMEE = re.compile(r"^> Instance : \*\*([^*]*)\*\* — `?([^`]*?)`?\s*$")
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


def remplir_paths(texte: str, valeurs: dict) -> tuple[str, list[str]]:
    """Chaque marqueur de `PATHS.md` remplacé pour lui-même, partout où il reste."""
    faits = []
    for m in MARQUEURS_PATHS:
        if m in texte and m in valeurs:
            texte = texte.replace(m, valeurs[m])
            faits.append(m)
    return texte, faits


def defauts(racine: str, nom: str, home: str | None = None, projets: str | None = None,
            date: str | None = None) -> dict:
    """Les valeurs que `brain init` donne aux marqueurs."""
    return {"<BRAIN_ROOT>": racine,
            "<HOME>": home or os.environ.get("HOME", ""),
            "<PROJECTS_ROOT>": projets or os.environ.get("PROJECTS_ROOT") or os.path.dirname(racine),
            "<DATE>": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "nom": nom}


def remplir_fichier(fichier: str, texte: str, valeurs: dict) -> tuple[str, list[str]]:
    """Remplir `PATHS.md` ou `focus.md` (par son nom) avec ces valeurs."""
    if fichier == "PATHS.md":
        return remplir_paths(texte, valeurs)
    if fichier == "focus.md":
        return remplir(texte, valeurs["<BRAIN_ROOT>"], valeurs["nom"], valeurs["<DATE>"])
    raise ValueError(f"{fichier} : pas un fichier semé à remplir")


def deduire(semis: str, rempli: str) -> dict:
    """Les valeurs qu'un fichier rempli a données aux marqueurs de son semis.

    Chaque ligne du semis qui porte des marqueurs devient un motif (un marqueur, une
    capture) ; les lignes du fichier rempli qui s'y ajustent en entier votent. Une ligne
    corrigée à la main sur sa seule valeur (la ligne `projects/` de PATHS.md) donne donc
    cette valeur ; un marqueur jamais rempli se donne lui-même."""
    votes: dict[str, Counter] = {}
    lignes = set(rempli.splitlines())
    for l in semis.splitlines():
        if not MARQUEUR.search(l):
            continue
        motif, groupes, pos = "", {}, 0
        for m in MARQUEUR.finditer(l):
            motif += re.escape(l[pos:m.start()])
            g = m.group()
            if g in groupes:
                motif += f"(?P={groupes[g]})"
            else:
                groupes[g] = f"g{len(groupes)}"
                motif += f"(?P<{groupes[g]}>.+?)"
            pos = m.end()
        rx = re.compile(motif + re.escape(l[pos:]))
        for r in lignes:
            ajuste = rx.fullmatch(r)
            if ajuste:
                for g, nom in groupes.items():
                    votes.setdefault(g, Counter())[ajuste.group(nom)] += 1
    return {g: c.most_common(1)[0][0] for g, c in votes.items()}


def valeurs_du_rempli(fichier: str, semis: str, rempli: str, valeurs_init: dict) -> dict | None:
    """Les valeurs avec lesquelles CE fichier a été rempli, lues dans le fichier lui-même ;
    celles d'init pour ce qui ne s'y lit pas. None : le fichier n'a jamais été rempli
    (un `focus.md` dont la ligne d'instance porte encore son marqueur)."""
    v = {**valeurs_init, **deduire(semis, rempli)}
    if fichier == "focus.md":
        for l in rempli.splitlines():
            if LIGNE_INSTANCE.match(l):
                return None
            m = LIGNE_NOMMEE.match(l)
            if m:
                v["nom"], v["<BRAIN_ROOT>"] = m.group(1), m.group(2)
                break
    return v


def main() -> int:
    p = argparse.ArgumentParser(description="Remplit focus.md ou PATHS.md, semés du gabarit")
    p.add_argument("--brain", required=True)
    p.add_argument("--fichier", choices=("focus.md", "PATHS.md"), default="focus.md")
    p.add_argument("--nom", help="le nom de l'instance (focus.md)")
    p.add_argument("--date", default=None)
    p.add_argument("--projets", default=None, help="<PROJECTS_ROOT> (PATHS.md) ; défaut : le dossier du brain")
    a = p.parse_args()
    if a.fichier == "focus.md" and not a.nom:
        p.error("--nom est requis pour focus.md")
    cible = Path(a.brain) / a.fichier
    if not cible.is_file() or cible.is_symlink():
        return 0
    avant = cible.read_text(encoding="utf-8")
    apres, faits = remplir_fichier(a.fichier, avant, defauts(a.brain, a.nom or "", projets=a.projets, date=a.date))
    if apres != avant:
        cible.write_text(apres, encoding="utf-8")
        print((" " if a.fichier == "PATHS.md" else ", ").join(faits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
