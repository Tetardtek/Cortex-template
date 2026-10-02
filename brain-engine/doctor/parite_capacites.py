#!/usr/bin/env python3
"""Les portes exposent-elles ce que le contrat déclare ? —.

Ce qui pourrirait en silence sans lui : **une porte qui s'ouvre ou se ferme sans
que le contrat le dise.** Une route ajoutée à `server.py` et pas au contrat n'est
visible nulle part ; une capacité retirée laisse une déclaration qui ment. Ni
l'une ni l'autre ne lève d'erreur — le serveur démarre, le MCP répond.

C'est la promesse que `bench/parite_portes.py` s'était faite à lui-même :

    « Il deviendra un contrôle le jour où la parité sera une exigence,
      c'est-à-dire quand le binaire déclarera ses capacités en un seul endroit. »

Ce jour est arrivé : `contrat/capacites.yml` est cet endroit.

── Ce qu'il refuse ─────────────────────────────────────────────────────────

    non declaree    une route ou un outil existe, le contrat l'ignore
    fantome         le contrat declare une surface qui n'existe plus
    desaccord       le contrat et le code ne disent pas la meme chose
                    pour une capacite qu'ils declarent tous les deux

── Ce qu'il ne refuse PAS ──────────────────────────────────────────────────

**L'asymétrie.** Une capacité exposée en HTTP et pas en MCP n'est pas un défaut
en soi — dix routes de cette installation sont des *services d'instance*, et le
CORE n'a pas à les porter. Ce que le contrôle exige, c'est que l'asymétrie soit
**déclarée**, pas qu'elle disparaisse.

Il ne refuse pas non plus une `brique: ~`. Attribuer une brique à
`brain_boot` demande une décision, pas une mesure — et un rouge que seul
l'humain peut éteindre est un rouge qu'on apprend à ignorer.

    python3 tools/parite_capacites.py --brain ~/Dev/Brain
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

OUTILS = Path(__file__).resolve().parent
RACINE = OUTILS.parent
sys.path.insert(0, str(RACINE / "bench"))


def charger_contrat(chemin: Path) -> dict:
    import yaml
    return (yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}).get("capacites") or {}


def mecanismes_reels(moteur: Path) -> dict[str, list[str]]:
    """Par où chaque outil MCP atteint la donnée — mesuré, pas déclaré.

    🔴 Écrit le 10/09 après avoir trouvé qu'une affirmation recopiée trois fois
    était fausse. `bench/parite_portes.py`, la fiche, et la première
    version de ce contrat disaient tous : « le MCP n'implémente rien, il appelle
    127.0.0.1:7700 ». Mesuré : **trois mécanismes**, dont deux qui ne passent
    jamais par HTTP.

    Ce qui compte n'est pas le nombre mais la conséquence : `brain_search` par le
    MCP et `GET /search` par HTTP ne traversent pas le même code. Deux chemins
    peuvent diverger ; un contrat qui ne dit pas lequel est emprunté ne protège
    de rien.

    L'import HTTP est **paresseux** — `import urllib.request` à l'intérieur de
    chaque fonction. Un premier motif cherchant les imports en tête de fichier
    n'en voyait aucun et rendait « 0 appel HTTP sur onze outils ».

    ⚠️ **Un outil peut en avoir PLUSIEURS, et la première version l'ignorait.**
    Elle rendait une chaîne — le premier mécanisme trouvé gagnait. Or
    `brain_agents` et `brain_focus` appellent HTTP **et** lisent le disque : le
    code le dit lui-même, *« Fallback filesystem si brain-engine
    indisponible »*. Déclarer `http` pour eux était une demi-vérité, et un
    contrôle qui vérifie une demi-vérité protège à moitié.

    🔴 **Et deux regex successives ont rendu deux réponses différentes** sur
    `brain_write` — l'une le disait `http + disque`, l'autre `http` seul. La
    première attribuait à sa fonction une ligne située **après** elle : découper
    par `@mcp.tool()` ne borne pas un corps de fonction. D'où l'AST, qui sait où
    une fonction s'arrête. `brain_write` est bien `http` seul — le garde de zone
    d'origine n'est pas contourné.
    """
    import ast
    DISQUE = {"read_text", "write_text", "iterdir", "rglob", "glob", "is_file",
              "exists", "open"}
    MEMOIRE = {"run_single_query", "run_boot_queries", "requete_faible"}

    arbre = ast.parse((moteur / "mcp_server.py").read_text(encoding="utf-8"))
    fonctions = {n.name: n for n in arbre.body if isinstance(n, ast.FunctionDef)}

    def appels_de(n: ast.FunctionDef) -> set[str]:
        out = set()
        for x in ast.walk(n):
            if isinstance(x, ast.Call):
                f = x.func
                out.add(f.attr if isinstance(f, ast.Attribute)
                        else getattr(f, "id", ""))
        return out

    def mecanismes(nom: str, vus: set[str] | None = None) -> set[str]:
        """Les mécanismes d'un outil, HELPERS COMPRIS.

        ⚠️ La version précédente ne regardait que les appels directs, et rendait
        « aucun » pour `brain_content` — qui délègue à `_scan_content_zone`.
        Un outil qui lit le disque par un intermédiaire le lit quand même :
        mesurer la façade et conclure sur le tout, c'est la troisième forme du
        même défaut dans la même heure.

        Un niveau ne suffirait pas si les helpers s'appelaient entre eux : la
        descente est récursive, avec `vus` contre les cycles.
        """
        vus = vus or set()
        if nom in vus or nom not in fonctions:
            return set()
        vus.add(nom)
        appels = appels_de(fonctions[nom])
        meca = set()
        if "urlopen" in appels:
            meca.add("http")
        if appels & MEMOIRE:
            meca.add("memoire")
        if appels & DISQUE:
            meca.add("disque")
        for a in appels:
            if a in fonctions and a != nom:
                meca |= mecanismes(a, vus)
        return meca

    return {n: sorted(mecanismes(n)) for n in fonctions if n.startswith("brain_")}


# Ce qu'une route ou un outil touche vraiment. Cinq mecanismes, pas trois : les
# deux derniers ont ete trouves en mesurant `server.py`, ou `/state` et `/infra`
# rendaient « aucun » alors qu'ils lancent `pm2 jlist`.
JEUX_HTTP = {
    "disque":   {"read_text", "write_text", "iterdir", "rglob", "glob", "is_file",
                 "exists", "open", "mkdir", "unlink"},
    "base":     {"query", "execute", "fetchall", "fetchone", "connect"},
    "modele":   {"run_single_query", "run_boot_queries", "requete_faible",
                 "encode", "embed"},
    "sousproc": {"run", "check_output", "Popen", "call"},
    "env":      {"getenv", "environ"},
}


def mecanismes_http(moteur: Path) -> dict[str, list[str]]:
    """{« VERBE /chemin »: [mecanismes]} — ce que chaque route touche.

    Meme descente recursive que du cote MCP, et la meme lecon : un premier jeu
    de mecanismes a trois entrees rendait « aucun » pour sept routes sur
    vingt-sept. Trois etaient legitimes — `/health`, `/ws`, `/ambient/notify`.
    Les quatre autres lancaient des **sous-processus** :

        pm2 jlist                         /state, /infra
        pm2 logs <projet> --lines 50      /logs/{project}
        git log -1 --oneline              /state
        python3 embed.py --file <cible>   PUT /brain/{path}  ← la reindexation

    Ca compte pour : un CORE portable ne peut pas appeler `pm2`. Les
    routes qui le font sont des services d'instance par nature, et la mesure le
    montre au lieu de le supposer.
    """
    import ast
    import re
    src = (moteur / "server.py").read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    fonctions = {n.name: n for n in ast.walk(arbre)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def appels(n) -> set[str]:
        # `x.y()` est note « y », SAUF pour les sous-processus : voir la note
        # sur `QUALIFIES` plus bas — `run` tout nu est trop commun pour dire
        # quoi que ce soit.
        out = set()
        for x in ast.walk(n):
            if isinstance(x, ast.Call):
                f = x.func
                if isinstance(f, ast.Attribute):
                    porteur = getattr(f.value, "id", "")
                    # 🔴 `run` et `call` sont des noms trop communs pour etre
                    # lus seuls. Mesure le 11/09 : apres, la route
                    # `PUT /brain/` appelait `embed.run()` — la reindexation en
                    # BIBLIOTHEQUE, justement ce qui remplace le sous-processus
                    # — et la derivation continuait d'annoncer `sousproc`. Le
                    # contrat aurait donc garde un mecanisme qui n'existait
                    # plus, et le chantier aurait paru inacheve.
                    #
                    # On qualifie donc : seul `subprocess.X` compte.
                    if f.attr in ("run", "call", "check_output", "Popen") \
                       and porteur not in ("subprocess", ""):
                        out.add(f"{porteur}.{f.attr}")
                    else:
                        out.add(f.attr)
                else:
                    out.add(getattr(f, "id", ""))
        return out

    def meca(nom: str, vus: set[str] | None = None) -> set[str]:
        vus = vus or set()
        if nom in vus or nom not in fonctions:
            return set()
        vus.add(nom)
        a = appels(fonctions[nom])
        m = {k for k, jeu in JEUX_HTTP.items() if a & jeu}
        for x in a:
            if x in fonctions and x != nom:
                m |= meca(x, vus)
        return m

    # Les verbes viennent du banc — la meme liste blanche existait ici ET dans
    # `bench/parite_portes.py`, et les deux avaient oublie `patch` (10/09).
    from parite_portes import VERBES

    trouve = {}
    for verbe, chemin, fn in re.findall(
            rf"@app\.({'|'.join(VERBES)})\(\s*['\"]([^'\"]+)['\"]\)\s*\n(?:async )?def (\w+)",
            src):
        trouve[f"{verbe.upper()} {chemin}"] = sorted(meca(fn))
    return trouve


def surfaces_reelles(moteur: Path) -> tuple[dict[str, list[str]], set[str]]:
    """Réutilise l'extraction du banc plutôt que d'en écrire une seconde.

    Deux extractions du même code divergeraient : c'est exactement le défaut que
    ce contrôle est censé attraper, et le commettre ici serait cocasse.
    """
    from parite_portes import routes_http, outils_mcp
    return routes_http(moteur), outils_mcp(moteur)


def main() -> int:
    p = argparse.ArgumentParser(description="Contrat des capacités vs portes réelles")
    p.add_argument("--brain", required=True, type=Path)
    p.add_argument("--contrat", type=Path, default=RACINE / "contrat" / "capacites.yml")
    a = p.parse_args()

    moteur = a.brain.expanduser().resolve() / "brain-engine"
    if not (moteur / "server.py").is_file():
        print("⏭️  SKIP brain-engine/server.py introuvable — rien à comparer.",
              file=sys.stderr)
        return 0
    if not a.contrat.is_file():
        print(f"❌ contrat introuvable : {a.contrat}", file=sys.stderr)
        return 1
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("⏭️  SKIP pyyaml absent.", file=sys.stderr)
        return 0

    contrat = charger_contrat(a.contrat)

    # Avant de comparer quoi que ce soit : l'extraction voit-elle TOUT le
    # serveur ? Un verbe HTTP que le banc ne sait pas lire fait disparaitre ses
    # routes du compte ET de la comparaison — elles ne sont ni declarees ni
    # refusees, juste absentes. C'est arrive le 10/09 avec `patch` :
    # `PATCH /bsi/claims/{sess_id}`, une ecriture sur la table des claims,
    # invisible aux deux controles pendant toute leur existence.
    #
    # Ce test passe donc AVANT les autres : tant qu'il ne passe pas, le reste
    # mesure un sous-ensemble sans le dire.
    from parite_portes import ALIAS, verbes_inconnus

    inconnus = verbes_inconnus(moteur)
    if inconnus:
        print("❌ l'extraction ne voit pas tout le serveur\n", file=sys.stderr)
        print(f"   {len(inconnus)} verbe(s) HTTP inconnu(s) du banc : "
              f"{', '.join(sorted(inconnus))}", file=sys.stderr)
        print("\n   → ajouter le verbe a `VERBES` dans `bench/parite_portes.py`.\n"
              "     Tant qu'il manque, les routes qui l'utilisent ne sont ni\n"
              "     comptees ni refusees : elles n'existent pour personne.",
              file=sys.stderr)
        return 1

    http, mcp = surfaces_reelles(moteur)

    # Ce que le contrat declare, mis a plat pour la comparaison
    http_declare: set[str] = set()
    mcp_declare: set[str] = set()
    for nom, meta in contrat.items():
        meta = meta or {}
        for r in (meta.get("http") or []):
            http_declare.add(str(r).strip())
        if meta.get("mcp"):
            mcp_declare.add(str(meta["mcp"]).strip())

    http_reel = {r for routes in http.values() for r in routes}
    # Le banc rend « GET /chemin » ; le contrat ecrit pareil. On compare des
    # chaines identiques, pas des formes rapprochees — on a paye trois fois
    # le rapprochement approximatif.

    routes_non_declarees = sorted(http_reel - http_declare)
    routes_fantomes = sorted(http_declare - http_reel)
    outils_non_declares = sorted(mcp - mcp_declare)
    outils_fantomes = sorted(mcp_declare - mcp)

    # Le mecanisme declare correspond-il au code ?
    reels = mecanismes_reels(moteur)
    meca_faux = []
    for nom, meta in contrat.items():
        meta = meta or {}
        outil = meta.get("mcp")
        if not outil:
            continue
        brut = meta.get("mecanisme")
        attendu = sorted(brut) if isinstance(brut, list) else ([brut] if brut else [])
        obtenu = reels.get(str(outil))
        if obtenu is not None and attendu != obtenu:
            meca_faux.append(f"{outil} : contrat dit `{'+'.join(attendu) or '~'}`, "
                             f"le code fait `{'+'.join(obtenu) or 'aucun'}`")

    # Cote HTTP : ce que chaque capacite touche, union de ses routes
    routes_meca = mecanismes_http(moteur)
    http_faux = []
    for nom, meta in contrat.items():
        meta = meta or {}
        liste = meta.get("http") or []
        if not liste:
            continue
        obtenu = sorted({m for r in liste for m in routes_meca.get(str(r), [])})
        brut = meta.get("mecanisme_http")
        attendu = sorted(brut) if isinstance(brut, list) else ([brut] if brut else [])
        if attendu != obtenu:
            http_faux.append(f"{nom} : contrat dit `{'+'.join(attendu) or '~'}`, "
                             f"les routes font `{'+'.join(obtenu) or 'aucun'}`")

    total = (len(routes_non_declarees) + len(routes_fantomes)
             + len(outils_non_declares) + len(outils_fantomes)
             + len(meca_faux) + len(http_faux))

    if not total:
        core = sum(1 for m in contrat.values() if (m or {}).get("nature") == "core")
        inst = sum(1 for m in contrat.values() if (m or {}).get("nature") == "instance")
        sans_brique = sorted(n for n, m in contrat.items()
                             if (m or {}).get("nature") == "core" and not (m or {}).get("brique"))
        from collections import Counter
        rep = Counter("+".join(v) or "aucun" for v in reels.values())
        print(f"✅ le contrat décrit les portes — {len(http_reel)} routes, {len(mcp)} outils"
              f" · {core} capacités CORE, {inst} services d'instance")
        print(f"   accès MCP  : " + " · ".join(f"{n} {k}" for k, n in sorted(rep.items())))
        rh = Counter("+".join(v) or "aucun" for v in routes_meca.values())
        print(f"   accès HTTP : " + " · ".join(f"{n} {k}" for k, n in sorted(rh.items())))
        # Compter les sous-processus toutes natures confondues melangeait deux
        # choses (10/09) : `infra` et `logs` en lancent LEGITIMEMENT — ce sont
        # des services d'instance. Le nombre qui doit tomber a zero a la
        # migration est celui des capacites CORE qui en lancent. On affiche les
        # deux, mais on nomme celui qui compte.
        sp = sorted(n for n, m in contrat.items()
                    if "sousproc" in ((m or {}).get("mecanisme_http") or []))
        sp_core = [n for n in sp if (contrat[n] or {}).get("nature") == "core"]
        if sp:
            print(f"ℹ️  {len(sp)} capacité(s) lancent un sous-processus, dont "
                  f"{len(sp_core)} déclarée(s) CORE : {', '.join(sp)}")
            if sp_core:
                print(f"   ⚠️  un CORE portable ne le peut pas — à résorber : "
                      f"{', '.join(sp_core)}")
            else:
                print("   ✅ aucune côté CORE — les autres sont des services "
                      "d'instance, et c'est leur place")
        if sans_brique:
            print(f"ℹ️  {len(sans_brique)} capacité(s) CORE sans brique attribuée — "
                  f"décision, pas défaut : {', '.join(sans_brique)}")

        # Une `brique:` qui ne designe aucun fichier de `core/` est une
        # attribution inventee — exactement ce que le commentaire du contrat
        # dit vouloir eviter en preferant `~`. Verifie, pas suppose.
        coeur = RACINE / "core"
        if coeur.is_dir():
            reelles = {f.stem for f in coeur.glob("*.py")
                       if not f.stem.startswith(("test", "__")) and f.stem != "tests"}
            declarees = {str(m.get("brique")) for m in contrat.values()
                         if (m or {}).get("brique")}
            fantomes = sorted(declarees - reelles)
            if fantomes:
                print(f"\n❌ {len(fantomes)} brique(s) déclarée(s) qui n'existent "
                      f"pas dans `core/` : {', '.join(fantomes)}", file=sys.stderr)
                return 1
            muettes = sorted(reelles - declarees)
            if muettes:
                print(f"ℹ️  {len(muettes)} brique(s) du CORE citée(s) par aucune "
                      f"capacité : {', '.join(muettes)}")
                print(f"   Pas un défaut : `brique` est SINGULIER, et une capacité "
                      f"en compose\n   souvent plusieurs — `brain_write` s'appuie "
                      f"sur traces, zones ET\n   indexation, mais n'en déclare "
                      f"qu'une. À trancher avec.")
        return 0

    print("❌ le contrat et les portes ne disent pas la même chose", file=sys.stderr)
    print("", file=sys.stderr)
    for titre, liste in (
            ("route(s) exposée(s) mais absente(s) du contrat", routes_non_declarees),
            ("route(s) déclarée(s) mais absente(s) du serveur", routes_fantomes),
            ("outil(s) MCP exposé(s) mais absent(s) du contrat", outils_non_declares),
            ("outil(s) déclaré(s) mais absent(s) du MCP", outils_fantomes),
            ("mécanisme(s) d'accès MCP déclaré(s) à tort", meca_faux),
            ("mécanisme(s) d'accès HTTP déclaré(s) à tort", http_faux)):
        if liste:
            print(f"   {len(liste)} {titre} :", file=sys.stderr)
            for x in liste:
                print(f"     • {x}", file=sys.stderr)
    print("", file=sys.stderr)
    print("   → `contrat/capacites.yml` est la source. Une porte qui bouge s'y",
          file=sys.stderr)
    print("     déclare, sinon personne ne saura qu'elle a bougé.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
