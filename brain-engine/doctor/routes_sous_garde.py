#!/usr/bin/env python3
"""Toute route qui ECRIT passe-t-elle le garde du mode ? — ne au.

Ce qui pourrirait en silence sans lui : **une porte d'ecriture qui ignore le
mode de l'instance.** `_readonly_guard()` refuse les ecritures quand
`BRAIN_MODE` vaut `template` ou `demo`. Sur une instance `prod` il laisse tout
passer — donc une route qui l'oublie se comporte exactement comme les autres,
ici, pour toujours. Le defaut ne se revele que la ou on ne regarde pas : chez
quelqu'un qui fait tourner une demo.

    python3 tools/routes_sous_garde.py --brain ~/Dev/Brain

── Ce qui l'a fait naitre ───────────────────────────────────────────────────

Mesure du 15/09, en instruisant : `PATCH /bsi/claims/{sess_id}` etait
la **seule des huit** routes d'ecriture a ne pas appeler `_readonly_guard()`.
Sept sur huit l'avaient. Aucun controle ne comparait les huit entre elles, et
la seule qui manquait etait aussi la seule sans appelant — invisible deux fois.

C'est la meme famille que le trou du 10/09, ou le verbe `patch` entier
echappait aux deux controles de parite. Un ensemble dont on ne compare jamais
les membres derive par son membre le plus discret.

── Pourquoi l'AST, et pas une recherche de texte ────────────────────────────

Un outil qui cherche un motif dans du TEXTE mesure ce qui est ecrit, pas ce qui
s'execute : la chaine `_readonly_guard` apparait dans les commentaires de cette
version meme, et un `grep` la compterait comme un appel. Quatre outils ont ete
repris pour cette raison le 11/09. On parse.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

GARDE = "_readonly_guard"
VERBES_ECRITURE = ("post", "put", "patch", "delete")

# Une route d'ecriture qui n'a legitimement pas a passer le garde se declare
# ICI, avec sa raison. Une liste vide est le bon etat ; une exemption sans
# motif ecrit est une dérive deguisee en decision.
EXEMPTIONS: dict[str, str] = {}


def routes_ecrivantes(source: str) -> list[tuple[str, str, bool, int]]:
    """(verbe, chemin, garde_appelee, ligne) pour chaque route d'ecriture.

    Le garde est cherche dans TOUT le corps de la fonction, appels imbriques
    compris : une route qui le place dans un `if` le passe quand meme — mal,
    mais elle le passe, et ce controle mesure la presence, pas la position.
    """
    arbre = ast.parse(source)
    trouvees = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in noeud.decorator_list:
            cible = deco.func if isinstance(deco, ast.Call) else deco
            if not (isinstance(cible, ast.Attribute)
                    and isinstance(cible.value, ast.Name)
                    and cible.value.id == "app"
                    and cible.attr in VERBES_ECRITURE):
                continue
            chemin = "?"
            if isinstance(deco, ast.Call) and deco.args:
                premier = deco.args[0]
                if isinstance(premier, ast.Constant) and isinstance(premier.value, str):
                    chemin = premier.value
            garde = any(
                isinstance(n, ast.Call)
                and ((isinstance(n.func, ast.Name) and n.func.id == GARDE)
                     or (isinstance(n.func, ast.Attribute) and n.func.attr == GARDE))
                for n in ast.walk(noeud)
            )
            trouvees.append((cible.attr.upper(), chemin, garde, noeud.lineno))
    return trouvees


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(Path.home() / "Dev/Brain"))
    args = ap.parse_args()

    serveur = Path(args.brain).expanduser() / "brain-engine" / "server.py"
    if not serveur.is_file():
        print(f"❌ moteur introuvable : {serveur}")
        return 1

    source = serveur.read_text(encoding="utf-8")

    # Le garde doit exister avant qu'on reproche a quiconque de ne pas
    # l'appeler. Sans cette verification, un serveur qui l'aurait SUPPRIME
    # passerait ce controle au vert : zero route fautive, parce que la regle
    # elle-meme a disparu. Un temoin pris la ou la chose ne peut pas exister
    # compte zero sur zero.
    arbre = ast.parse(source)
    defini = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == GARDE
                 for n in ast.walk(arbre))
    if not defini:
        print(f"❌ `{GARDE}()` n'est pas defini dans {serveur.name} —")
        print("   la regle a disparu, et toutes les routes passeraient au vert.")
        return 1

    routes = routes_ecrivantes(source)
    if not routes:
        print("❌ aucune route d'ecriture trouvee — le motif de detection ne mord plus")
        return 1

    fautives = [(v, c, l) for v, c, g, l in routes
                if not g and c not in EXEMPTIONS]
    exemptees = [(v, c) for v, c, g, _ in routes if not g and c in EXEMPTIONS]

    print(f"ROUTES — {len(routes)} route(s) d'ecriture, garde `{GARDE}()`\n")
    for verbe, chemin, garde, _ in routes:
        marque = "✅" if garde else ("⏭️" if chemin in EXEMPTIONS else "❌")
        print(f"  {marque} {verbe:7} {chemin}")

    for verbe, chemin in exemptees:
        print(f"\n  ⏭️  {verbe} {chemin} — exempte : {EXEMPTIONS[chemin]}")

    print()
    if fautives:
        print(f"  ❌ {len(fautives)} route(s) d'ecriture sans garde de mode :")
        for verbe, chemin, ligne in fautives:
            print(f"       {verbe} {chemin}  ({serveur.name}:{ligne})")
        print()
        print("     Sur une instance `prod` le garde laisse tout passer — ce rouge")
        print("     ne se voit donc jamais a l'usage. Il se voit chez celui qui")
        print("     fait tourner un `template` ou une `demo`.")
        return 1

    print(f"  ✅ les {len(routes)} routes d'ecriture passent le garde du mode")
    return 0


if __name__ == "__main__":
    sys.exit(main())
