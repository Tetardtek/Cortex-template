#!/usr/bin/env python3
"""Tout frontmatter est-il du YAML que les DEUX portes savent lire ? —.

Le brain porte **trois** parseurs de frontmatter, et ils ne se comportent pas
pareil face à un YAML invalide :

    server.py       repli regex — lit quand même, et journalise une fois
    mcp_server.py   rend `None` — les metadonnees sont PERDUES
    embed.py        get_frontmatter_scope, pour le scope d'indexation

Mesuré le 11/09 : un billet de `content/posts/` portait
`format: … (1: une scène …)`. Le `: ` dans une valeur non quotée fait
lire `1:` comme une clé imbriquée — *« mapping values are not allowed here »*.

Conséquence, vérifiée et pas déduite : `server.py` rend `status: published`,
le MCP rend `unknown`, et **`brain_content(status='published')` ne trouve pas
le fichier.** Un contenu publié devient invisible à toute session qui filtre.

    python3 tools/frontmatter_valide.py --brain ~/Dev/Brain

── Pourquoi contrôler la DONNÉE et pas seulement le parseur ────────────────

Aligner les trois parseurs est le vrai geste, et il appartient à — un
parseur unique, pas un quatrième. En attendant, un frontmatter invalide est un
défaut *dans la donnée*, réparable en une paire de guillemets, et qui se
détecte mécaniquement.

Ce contrôle ne remplace pas l'unification : il empêche la classe de revenir
pendant qu'elle attend.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Les zones dont le frontmatter est LU par une porte. Inutile de balayer tout
# le disque : ce qui compte est ce qu'une porte parse.
ZONES = ("agents", "profil/decisions", "handoffs", "projets",
         "contenu", "workspace/content", "contexts", "todo")
# `contenu` : le satellite du pipeline de contenu (BRAIN-080) — `brain_content`
# en parse le frontmatter. `workspace/content` garde `story/` jusqu'à l'étape 4.

ENTETE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def main() -> int:
    p = argparse.ArgumentParser(description="Les frontmatters sont-ils du YAML valide ?")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()
    racine = a.brain.expanduser().resolve()

    try:
        import yaml
    except ImportError:
        print("⏭️  SKIP pyyaml absent — rien à conclure.", file=sys.stderr)
        return 0

    casses, examines, avec_entete = [], 0, 0
    doubles = []      # scope declare deux fois — meme valeur ou non
    for zone in ZONES:
        d = racine / zone
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            # Gabarits et index ne sont pas des documents — meme regle que
            # `server.py` et `agent_registry.py`, et que le repli du MCP depuis
            # le 10/09. La respecter ici evite de rougir sur un fichier qui
            # n'est lu par personne : verifie, `agents/games/_template.md`
            # declare `kernel` a la racine et `personal` sous `brain:`, et il a
            # **0 embedding** — sa contradiction n'atteint aucune porte.
            #
            # Un controle qui rougit sur ce qui n'est pas dans le perimetre use
            # l'attention qu'il devra reclamer le jour ou ca compte.
            if f.name == "AGENTS.md" or f.stem.startswith("_"):
                continue
            examines += 1
            texte = f.read_text(encoding="utf-8", errors="replace")
            m = ENTETE.match(texte)
            if not m:
                continue                    # pas de frontmatter : ce n'est pas un defaut
            avec_entete += 1
            # Le `scope` gouverne l'ACCES — il ne se declare pas deux fois.
            #
            # Mesure du 11/09 : la convention du brain le met sous `brain:`
            # (188 fichiers), et `embed.py` le trouve par un parsing naif qui
            # accepte n'importe quelle indentation. Huit fichiers le declarent
            # AUSSI a la racine. Aujourd'hui les deux valeurs concordent — mais
            # `embed.py` retient le PREMIER dans l'ordre du fichier, la lecture
            # structuree retient celui de la racine. Le jour ou l'une des deux
            # bouge seule, les deux portes classent le meme fichier
            # differemment, et un scope est une frontiere d'acces.
            valeurs = [l.split(":", 1)[1].split("#")[0].strip()
                       for l in m.group(1).splitlines()
                       if l.strip().startswith("scope:")]
            if len(valeurs) > 1:
                doubles.append((str(f.relative_to(racine)), valeurs))

            try:
                yaml.safe_load(m.group(1))
            except Exception as exc:        # noqa: BLE001
                premiere = str(exc).splitlines()[0]
                # La ligne fautive, quand PyYAML la donne — c'est ce qui rend le
                # message reparable au lieu d'etre seulement vrai.
                ou = re.search(r"line (\d+), column (\d+)", str(exc))
                place = f"  (l.{int(ou.group(1)) + 1} du fichier, col. {ou.group(2)})" if ou else ""
                casses.append((str(f.relative_to(racine)), premiere, place))

    print(f"  {examines} fichier(s) examiné(s), {avec_entete} avec frontmatter")

    divergents = [(c, v) for c, v in doubles if len(set(v)) > 1]
    if divergents:
        print(f"\n❌ {len(divergents)} fichier(s) déclarent un `scope` DIFFÉRENT "
              f"deux fois :", file=sys.stderr)
        for c, v in divergents:
            print(f"     {c} → {' vs '.join(v)}", file=sys.stderr)
        print(f"\n   `embed.py` retient le PREMIER dans l'ordre du fichier, la "
              f"lecture structurée\n   celui de la racine. Les deux portes "
              f"classent donc ce fichier différemment,\n   et un scope est une "
              f"frontière d'accès.", file=sys.stderr)
        return 1
    if doubles:
        print(f"  ℹ️  {len(doubles)} fichier(s) déclarent leur `scope` deux fois "
              f"— racine ET sous `brain:`")
        print(f"     Les valeurs concordent, donc rien ne casse aujourd'hui. Mais "
              f"c'est une\n     déclaration en double, et le contrôle rougira si "
              f"l'une bouge seule.")

    if not casses:
        print(f"\n✅ tous les frontmatters sont du YAML valide — les trois "
              f"parseurs liront la même chose")
        return 0

    print(f"\n❌ {len(casses)} frontmatter(s) que `yaml.safe_load` refuse :\n",
          file=sys.stderr)
    for chemin, motif, place in casses:
        print(f"     {chemin}{place}\n       {motif}", file=sys.stderr)
    print(f"\n   `server.py` les lit par son repli regex ; `mcp_server.py` rend "
          f"`None`\n   et PERD les métadonnées — le fichier reste listé, mais avec\n"
          f"   `status: unknown`, sans série ni dates. Un filtre ne le trouve plus.\n"
          f"\n   Réparation : mettre la valeur entre guillemets. Un `: ` dans une\n"
          f"   valeur non quotée est lu comme une clé imbriquée.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
