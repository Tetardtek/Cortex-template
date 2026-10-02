#!/usr/bin/env python3
"""Les portes du CORE déclarent-elles les mêmes capacités ?

Le CORE est atteint par quatre portes, et le but est « un binaire, plusieurs
portes ». Avant de construire le binaire, il faut savoir ce que les portes
existantes exposent — et où elles divergent.

    python3 bench/parite_portes.py --brain ~/Dev/Brain

── Ce que c'est, et ce que ce n'est PAS ────────────────────────────────────

**Une mesure, pas un contrôle.** Il ne sort jamais en 1 et n'entre pas dans
`brain doctor`. Les asymétries qu'il montre sont connues et personne n'a décidé
de les corriger : en faire un rouge fabriquerait un piège déjà vu
— un contrôle que personne ne peut verdir, qu'on apprend à ignorer.

Il deviendra un contrôle le jour où la parité sera une **exigence**, c'est-à-dire
quand le binaire déclarera ses capacités en un seul endroit.

── Pourquoi c'est constructible avant de trancher le langage ───────────────

Les trois questions ouvertes du binaire — Python ou Rust, les tables
opérationnelles passent-elles par la porte, `brain serve` remplace-t-il
`server.py` — ne changent rien à ce que ce banc mesure. Une capacité exposée deux
fois le reste quel que soit le langage qui l'implémente.

C'est aussi ce qui le rend jetable sans regret : si la direction change, on perd
un fichier de mesure, pas une architecture.

── Comment il rapproche ────────────────────────────────────────────────────

Par le nom, seul rapprochement dont on dispose : `brain_search` ↔ une route qui
contient `search`. Les correspondances qui ne suivent pas cette règle sont
déclarées ci-dessous plutôt que devinées — un rapprochement approximatif rendrait
des paires qui n'en sont pas, et ce défaut a déjà été commis trois fois.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# Ce que le nom ne rapproche pas tout seul.
ALIAS = {
    "brain_content_promote": "brain",     # passe par PUT /brain/{path}
    "brain_write": "brain",               # idem
}

# Ce qui n'est pas une capacité du CORE : diagnostic, identité du serveur.
HORS_CAPACITE = {"brain_version", "brain_mcp", "brain_key"}

# Les verbes que ce banc sait lire. **Source unique** : `tools/parite_capacites.py`
# l'importe au lieu de le réécrire — la même liste blanche existait en deux
# exemplaires, et les deux avaient le même trou.
#
# 🔴 10/09 — `patch` manquait aux DEUX. `PATCH /bsi/claims/{sess_id}` — une
# route d'ÉCRITURE sur la table des claims — n'était donc vue par aucun des deux
# contrôles : ni compté dans les 27 routes, ni refusé comme non déclaré. Un
# contrôle qui ignore en silence ce qu'il ne sait pas lire ne contrôle rien.
#
# La parade n'est pas d'ajouter `patch` à la liste : c'est de REFUSER l'inconnu.
# `verbes_inconnus()` rougit sur tout `@app.X(` hors de cet ensemble, pour que
# le prochain verbe (`head`, `options`, un routeur monté autrement) se signale
# au lieu de disparaître.
VERBES = ("get", "post", "put", "patch", "delete", "websocket")

def _decorateurs(moteur: Path) -> list[tuple[str, str]]:
    r"""(verbe, chemin) pour chaque `@app.X("/…")` — par l'AST, pas par regex.

    🔴 Corrigé le 11/09. La première version cherchait le motif dans le SOURCE
    BRUT :

        _DECORATEUR = re.compile(r"@app\.(\w+)\(\s*['\"]([^'\"]+)['\"]")

    Elle trouvait donc les décorateurs écrits dans une **docstring**. Le jour
    où un commentaire a expliqué pourquoi `@app.on_event('startup')` avait été
    ÉCARTÉ, ce banc a refusé le serveur entier : « 1 verbe HTTP inconnu :
    on_event ». Le verbe n'existait nulle part dans le code.

    Un extracteur qui lit du texte mesure ce qui est écrit, pas ce qui
    s'exécute. C'est exactement le défaut trouvé le matin même dans le banc
    d'équivalence de traduction SQL, qui comparait une docstring citant
    `TIMESTAMPDIFF`. Le même jour, deux fois, sur deux outils différents.

    L'AST ne voit que de vrais décorateurs.
    """
    arbre = ast.parse((moteur / "server.py").read_text(encoding="utf-8",
                                                       errors="replace"))
    sortie = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in noeud.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            f = deco.func
            if not (isinstance(f, ast.Attribute)
                    and getattr(f.value, "id", None) == "app"):
                continue
            if deco.args and isinstance(deco.args[0], ast.Constant) \
               and isinstance(deco.args[0].value, str):
                sortie.append((f.attr, deco.args[0].value))
    return sortie


def verbes_inconnus(moteur: Path) -> set[str]:
    """Les verbes que le serveur utilise et que ce banc ne sait pas lire.

    Le témoin négatif de l'extraction elle-même : tant qu'il rend l'ensemble
    vide, « 27 routes » veut dire quelque chose. Dès qu'il rend un nom, le
    compte est faux et le dit.
    """
    return {v for v, _ in _decorateurs(moteur)} - set(VERBES)


def routes_http(moteur: Path) -> dict[str, list[str]]:
    """Les routes déclarées par le serveur, groupées par premier segment."""
    par_segment: dict[str, list[str]] = {}
    for verbe, chemin in _decorateurs(moteur):
        if verbe not in VERBES:
            continue                       # signalé par `verbes_inconnus()`
        segment = chemin.strip("/").split("/")[0].split("{")[0] or "/"
        par_segment.setdefault(segment, []).append(f"{verbe.upper()} {chemin}")
    return par_segment


def outils_mcp(moteur: Path) -> set[str]:
    """Les outils DÉFINIS, pas les chaînes qui leur ressemblent.

    Le premier jet cherchait `\bbrain_[a-z_]+` partout et rendait `brain_engine`
    comme un outil — c'est une clé de configuration, `ports.get('brain_engine')`.
    Un nom dans une chaîne n'est pas une définition : même défaut que le
    `tr -dc '0-9'` qui lisait « 3350 tuiles » dans « client 3.3.5a : 0 ».
    """
    src = (moteur / "mcp_server.py").read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"^def (brain_[a-z_]+)", src, re.MULTILINE)) - HORS_CAPACITE


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()
    moteur = args.brain.expanduser().resolve() / "brain-engine"

    if not (moteur / "server.py").is_file():
        print("\n  ❌ `brain-engine/server.py` introuvable — rien à mesurer.\n")
        return 0

    http = routes_http(moteur)
    mcp = outils_mcp(moteur)

    doublees, mcp_seul = [], []
    for outil in sorted(mcp):
        cle = ALIAS.get(outil, outil.removeprefix("brain_"))
        if cle in http:
            doublees.append((outil, http[cle]))
        else:
            mcp_seul.append(outil)

    couverts = {ALIAS.get(o, o.removeprefix("brain_")) for o in mcp}
    http_seul = sorted(s for s in http if s not in couverts)

    print("\nPARITÉ DES PORTES — ce que le CORE expose, et par où\n")
    print(f"  routes HTTP        {sum(len(v) for v in http.values()):>3}"
          f"  ·  {len(http)} segments")
    print(f"  outils MCP         {len(mcp):>3}")
    print(f"  capacités doublées {len(doublees):>3}")

    print("\n  ── exposées des deux côtés ──")
    for outil, routes in doublees:
        print(f"     {outil:<24} {', '.join(routes)[:60]}")

    if mcp_seul:
        print("\n  ── MCP seul, aucune route HTTP ──")
        for o in mcp_seul:
            print(f"     {o}")

    if http_seul:
        print("\n  ── HTTP seul, aucun outil MCP ──")
        for s in http_seul:
            print(f"     {s:<24} {', '.join(http[s])[:60]}")

    # 🔴 Ces trois lignes affirmaient : « Le MCP n'implémente rien : il appelle
    # 127.0.0.1:7700. Le doublon est de SURFACE, pas d'implémentation. »
    #
    # C'est FAUX, mesuré le 10/09 en écrivant `contrat/capacites.yml`. La phrase
    # est née ici, puis a été recopiee dans une fiche, et dans la premiere
    # version du contrat — trois fois, sans que personne ne la remesure. Corrigee
    # dans les deux autres le matin ; ce banc la reimprimait encore le soir.
    #
    # Le MCP atteint la donnee par TROIS mecanismes. Le detail par capacite est
    # dans `contrat/capacites.yml`, qui est desormais la source — et
    # `tools/parite_capacites.py` verifie chaque mecanisme contre le code.
    print("\n  Le MCP n'est PAS une simple facade : il atteint la donnee par")
    print("  trois chemins — HTTP, memoire, disque — qui peuvent diverger.")
    print("  Le doublon n'est donc pas que de surface. Detail et verification :")
    print("  contrat/capacites.yml + tools/parite_capacites.py \n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
