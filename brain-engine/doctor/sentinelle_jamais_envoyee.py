#!/usr/bin/env python3
"""Un test attend-il une sentinelle que sa source n'envoie jamais ? — ne le 16/09.

Ce qui pourrirait en silence sans lui : **une branche d'erreur qui ne s'execute
jamais, dans un code qui a l'air de la gerer.**

C'est le defaut de. `bsi_network` testait :

    if peer_claims is not None and isinstance(peer_claims, list):
        status = 'online'
    else:
        status = 'offline'

Le test etait juste, ecrit d'avance, et attendait un `None`. Mais
`_fetch_peer_claims` rendait `[]` sur echec — jamais `None`. **La branche
`offline` n'etait atteignable par aucune valeur**, et un peer eteint
s'affichait `online`.

Le garde-fou existait ; sa sentinelle avait ete retiree en amont, et rien ne
reliait les deux. C'est pire qu'une absence de garde-fou : le code MONTRE qu'il
gere le cas.

    python3 tools/sentinelle_jamais_envoyee.py --brain ~/Dev/Brain

── Ce qu'il cherche, exactement ─────────────────────────────────────────────

    une variable affectee depuis un appel a une fonction du meme fichier
    testee par `is None` ou `is not None`
    alors qu'AUCUN `return` de cette fonction ne peut valoir None

── Trois affinages, et pourquoi ils comptent ────────────────────────────────

Le premier jet ne trouvait RIEN — pas meme le defaut d'origine, qu'il avait sous les yeux :
il traitait tout `return <expression>` comme un None possible, donc se taisait
sur toute fonction reelle. **Un balayage qui ne trouve rien doit d'abord
prouver qu'il trouve le cas connu.** C'est le role du temoin, plus bas.

Le deuxieme rendait 4 resultats dont 2 faux :

    `return min(ages) if ages else None`   un IfExp — le None n'est pas a la racine
    `conn = None` puis `conn = connect()`  la variable a DEUX sources

Corriges : on cherche la constante `None` partout dans l'expression retournee,
et une variable affectee au moins une fois depuis autre chose qu'un appel n'est
pas suivie. Il reste alors exactement un resultat : le defaut d'origine.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Un couple (fichier, fonction appelee) dont on a etabli que le test est
# legitime se declare ICI, avec sa raison. Vide est le bon etat.
EXEMPTIONS: dict[tuple[str, str], str] = {}


def contient_none(noeud: ast.AST) -> bool:
    """La constante `None` apparait-elle quelque part dans l'expression ?

    `return min(ages) if ages else None` la porte dans une branche d'`IfExp` ;
    `return x or None` dans un `BoolOp`. Chercher a la racine seulement fait
    passer les deux pour « ne rend jamais None ».
    """
    return any(isinstance(x, ast.Constant) and x.value is None
               for x in ast.walk(noeud))


def jamais_none(f: ast.AST) -> bool:
    retours = [n for n in ast.walk(f) if isinstance(n, ast.Return)]
    if not retours:
        return False                       # tombe en fin de corps -> None
    for r in retours:
        if r.value is None or contient_none(r.value):
            return False
    return True


def valeur_de_secours(f: ast.AST) -> list[str]:
    """Ce que la fonction rend depuis ses `except` — la cause habituelle."""
    sortie = []
    for h in ast.walk(f):
        if not isinstance(h, ast.ExceptHandler):
            continue
        for r in h.body:
            if not isinstance(r, ast.Return):
                continue
            v = r.value
            if isinstance(v, ast.List) and not v.elts:
                sortie.append("[]")
            elif isinstance(v, ast.Dict) and not v.keys:
                sortie.append("{}")
            elif isinstance(v, ast.Constant) and v.value in ("", 0, False):
                sortie.append(repr(v.value))
    return sortie


def sources(f: ast.AST) -> dict[str, str | None]:
    """Nom de variable -> fonction appelee, ou None si une source n'en est pas une.

    Une variable affectee DEUX fois — `conn = None` puis `conn = connect()` —
    n'est pas suivie : le test `is not None` y est legitime, et l'accuser
    ferait de ce controle un bruit qu'on apprend a ignorer.
    """
    vues: dict[str, str | None] = {}
    for n in ast.walk(f):
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)):
            continue
        nom = n.targets[0].id
        if isinstance(n.value, ast.Call):
            a = n.value.func
            appelee = a.id if isinstance(a, ast.Name) else getattr(a, "attr", "")
            vues[nom] = None if nom in vues and vues[nom] != appelee else appelee
        else:
            vues[nom] = None               # une source qui n'est pas un appel
    return vues


def analyse(chemin: Path) -> list[tuple[int, str, str, list[str]]]:
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    fonctions = {f.name: f for f in ast.walk(arbre)
                 if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    trouves = []
    for f in ast.walk(arbre):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        src = sources(f)
        for n in ast.walk(f):
            if not (isinstance(n, ast.Compare)
                    and any(isinstance(o, (ast.Is, ast.IsNot)) for o in n.ops)):
                continue
            cible = n.comparators[0]
            if not (isinstance(cible, ast.Constant) and cible.value is None):
                continue
            if not isinstance(n.left, ast.Name):
                continue
            appelee = src.get(n.left.id)
            if not appelee or appelee not in fonctions:
                continue
            if not jamais_none(fonctions[appelee]):
                continue
            trouves.append((n.lineno, f.name, appelee,
                            valeur_de_secours(fonctions[appelee])))
    return trouves


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    args = ap.parse_args()
    moteur = args.brain.expanduser().resolve() / "brain-engine"
    if not moteur.is_dir():
        print(f"❌ moteur introuvable : {moteur}")
        return 1

    fichiers = [p for p in sorted(moteur.glob("*.py"))
                if not p.name.startswith("test_")]
    if not fichiers:
        print("❌ aucun fichier a analyser — le motif de collecte ne mord plus")
        return 1

    # ── Le temoin ───────────────────────────────────────────────────────
    #
    # Ce controle sait-il trouver quoi que ce soit ? On lui donne le defaut
    # d'origine, reconstitue en memoire. Sans lui, un balayage casse annoncerait
    # « aucun ecart » et ce serait indiscernable d'un code sain — exactement le
    # defaut qu'il surveille, applique a lui-meme.
    faux = ast.parse(
        "def source():\n"
        "    try:\n"
        "        return charger()\n"
        "    except Exception:\n"
        "        return []\n"
        "def appelant():\n"
        "    v = source()\n"
        "    if v is not None:\n"
        "        return 'online'\n"
        "    return 'offline'\n")
    fns = {f.name: f for f in ast.walk(faux)
           if isinstance(f, ast.FunctionDef)}
    if not jamais_none(fns["source"]):
        print("❌ temoin : le defaut d'origine (une sentinelle jamais envoyée) n'est plus reconnu —")
        print("   ce controle ne mesure plus rien, et son vert ne vaut rien.")
        return 1
    print("  ✅ témoin — le défaut d'origine est reconnu\n")

    total = 0
    for chemin in fichiers:
        for ligne, fn, appelee, secours in analyse(chemin):
            cle = (chemin.name, appelee)
            if cle in EXEMPTIONS:
                print(f"  ⏭️  {chemin.name}:{ligne} {fn}() -> {appelee}() — "
                      f"exempte : {EXEMPTIONS[cle]}")
                continue
            total += 1
            print(f"  🔴 {chemin.name}:{ligne}  {fn}() teste `is [not] None`")
            print(f"       source `{appelee}()` — ne rend JAMAIS None"
                  f"{', mais ' + ', '.join(secours) + ' sur echec' if secours else ''}")

    print()
    if total:
        print(f"  ❌ {total} branche(s) qui ne s'executeront jamais.")
        print("     Le test est juste et attend une sentinelle que sa source")
        print("     n'envoie pas. C'est pire qu'une absence de garde-fou :")
        print("     le code MONTRE qu'il gere le cas.")
        return 1
    print(f"  ✅ aucun test n'attend une sentinelle qu'il ne recevra pas "
          f"({len(fichiers)} fichiers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
