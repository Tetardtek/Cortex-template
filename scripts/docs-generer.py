#!/usr/bin/env python3
# brain-distribuable: oui
"""La doc, régénérée depuis ce que le brain contient.

    docs-generer.py              montre ce qui serait écrit (lecture seule)
    docs-generer.py --ecrire     docs/src/*.md → docs/*.md
    docs-generer.py --check      0 docs/ à jour · 1 en retard · 2 illisible
    docs-generer.py --brain <racine>   un autre brain (le gabarit rendu)

Ce qui pourrirait en silence sans lui : **un chiffre ou une liste que le
commit suivant a rendus faux.** La doc publiée le 27/09 annonçait « 81
agents » pour 75, décrivait `key-guardian` et `feature-gate` supprimés trois
semaines plus tôt, « 4 types de session » pour 6, « 26 tables » pour 29. Les
nombres venaient de `docs-inject.sh` — qui comptait encore les agents par
palier commercial, à partir de listes supprimées, et rendait -2 et -5 — et
les listes étaient écrites à la main.

── Ce qui se compte se calcule, ce qui se liste se génère ──────────────────

Dans `docs/src/*.md`, deux formes, remplacées dans `docs/*.md` :

    {{NOM}}                        une valeur
    <!-- genere:NOM -->            un bloc — la ligne entière est remplacée

    valeurs   VERSION, NB_AGENTS, NB_SESSIONS, NB_TABLES, NB_VUES,
              NB_ROUTES, NB_OUTILS
    blocs     sessions   les types de session, depuis contexts/session-*.yml
              agents     les agents, groupés par portée × rôle (frontmatter)
              tables     les tables et les vues, depuis le schéma Dolt
              routes     les routes de l'API, lues dans server.py (ast)
              outils     les outils MCP, lus dans mcp_server.py (ast)

Deux cibles, même mécanisme : `docs/src/` → `docs/` (la doc humaine) et
`skills/brain/src/` → `skills/brain/` (la skill, la doc que l'AGENT croit —
une route morte y serait suivie avec aplomb).
Et un fichier seul : `instance/README.src.md` → `README.md`, le README de
l'instance — absent chez un fork, qui garde celui du gabarit.

La source de chaque valeur est le brain qu'on lui donne, jamais un autre :
lancé sur le gabarit rendu, il compte ce que le gabarit contient. Un agent
est compté s'il est présent ET, quand `agents/CATALOG.yml` existe, déclaré
distribuable — un agent privé n'apparaît pas dans la doc de l'auteur non plus.

Un nom inconnu (`{{AGENT_FULL}}`, `<!-- genere:tier -->`) est une erreur, pas
un vide : une doc qui affiche un blanc ment aussi.

Chaque cible est entièrement générée : une page sans source (au premier niveau
de la cible) est retirée par `--ecrire`, et fait rougir `--check`.
"""

from __future__ import annotations

import argparse
import functools
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # le venv de brain-engine l'a ; le python du système, pas toujours
    yaml = None

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
BLOC = re.compile(r"^<!--[ \t]*genere:([a-z]+)[ \t]*-->[ \t]*$", re.MULTILINE)
EN_TETE_TEXTE = "Généré depuis {nom} par scripts/docs-generer.py — ne pas éditer ici."

#: (sources, sortie) relatives à la racine du brain. Une cible dont le dossier
#: source n'existe pas est ignorée : un brain sans skill a quand même sa doc.
CIBLES = (("docs/src", "docs"), ("skills/brain/src", "skills/brain"))

#: (source, sortie) — un FICHIER, pas un dossier. Le README de la racine ne peut pas
#: être une cible-dossier : `--ecrire` retire toute page sans source au premier
#: niveau d'une cible, et la racine porte KERNEL.md, BRAIN-INDEX.md… Sa source vit
#: dans `instance/`, qui ne part jamais au gabarit : un fork n'a pas cette source,
#: la cible est ignorée, et son README reste celui du gabarit.
FICHIERS = (("instance/README.src.md", "README.md"),)
EN_TETE = "<!-- " + EN_TETE_TEXTE + " -->\n"

#: Les familles d'agents, par (portée, rôle) — les deux champs que tous les
#: frontmatters portent (`brain.scope`, `brain.type`). L'ordre est celui de la page.
FAMILLES = (
    (("project", "metier"), "Sur ton projet — code, qualité, infra, contenu"),
    (("project", "specialist"), "Spécialistes contenu"),
    (("project", "scribe"), "Scribes de projet"),
    (("kernel", "protocol"), "Le fonctionnement du brain"),
    (("kernel", "orchestrator"), "Orchestration"),
    (("kernel", "scribe"), "Scribes du brain — ce qui s'écrit, et où"),
    (("kernel", "metier"), "Sur le brain lui-même"),
    (("kernel", "reader"), "Orientation"),
    (("session", "reader"), "Repères de session"),
    (("kernel", "spec"), "Spécifications"),
    (("kernel", "utility"), "Utilitaires"),
)


class Illisible(RuntimeError):
    """Une source qui ne se lit pas — jamais un zéro."""


# ── Lire le brain ──────────────────────────────────────────────────────────

def _yaml(texte: str, ou: str):
    if yaml is None:
        raise Illisible("PyYAML absent — lancer avec le python du venv (brain-engine/.venv)")
    try:
        return yaml.safe_load(texte)
    except yaml.YAMLError as e:
        raise Illisible(f"{ou} : YAML illisible ({e})") from e


def frontmatter(chemin: Path) -> dict:
    texte = chemin.read_text(encoding="utf-8")
    if not texte.startswith("---"):
        return {}
    fin = texte.find("\n---", 3)
    fm = _yaml(texte[3:fin], str(chemin)) if fin > 0 else None
    return fm if isinstance(fm, dict) else {}


def catalogue(brain: Path) -> tuple[set[str], set[str]] | None:
    """(distribuables, connus) du catalogue — `None` sans catalogue."""
    cat = brain / "agents" / "CATALOG.yml"
    if not cat.is_file():
        return None
    data = _yaml(cat.read_text(encoding="utf-8"), str(cat)) or {}
    entrees = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(entrees, list) or not all(isinstance(a, dict) and "id" in a for a in entrees):
        raise Illisible(f"{cat} : `agents` n'est pas une liste d'entrées avec un `id`")
    return ({a["id"] for a in entrees if a.get("distributable")}, {a["id"] for a in entrees})


def agents(brain: Path) -> list[dict]:
    """Les agents présents. Le catalogue écarte ceux qu'il déclare NON
    distribuables ; un agent qu'il ne connaît pas — créé dans un fork, où le
    générateur du catalogue n'existe pas — compte s'il n'est pas `personal`.
    Sans cette règle, l'agent qu'un fork crée n'apparaissait jamais dans sa
    doc, qui le promettait pourtant (relecture du 28/09)."""
    cat = catalogue(brain)
    trouves = []
    for f in sorted((brain / "agents").rglob("*.md")):
        rel = f.relative_to(brain / "agents")
        if f.name.startswith("_") or f.name == "AGENTS.md" or rel.parts[0] in ("reviews", "archive"):
            continue
        ident = str(rel.with_suffix(""))
        fm = frontmatter(f)
        b = fm.get("brain") if isinstance(fm.get("brain"), dict) else {}
        if cat is not None:
            distribuables, connus = cat
            if ident in connus and ident not in distribuables:
                continue
            if ident not in connus and b.get("scope") == "personal":
                continue
        trouves.append({"id": ident, "description": (fm.get("description") or "").strip(),
                        "scope": b.get("scope"), "type": b.get("type")})
    if not trouves:
        raise Illisible(f"aucun agent lisible dans {brain / 'agents'}")
    return trouves


def _commentaire(texte: str, cle: str) -> str:
    m = re.search(r"^#\s*%s\s*:\s*(.+)$" % cle, texte, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else ""


def sessions(brain: Path, publies: set[str]) -> list[dict]:
    trouvees = []
    for f in sorted((brain / "contexts").glob("session-*.yml")):
        texte = f.read_text(encoding="utf-8")
        d = _yaml(texte, str(f)) or {}
        l1 = [re.sub(r"^agents/|\.md$", "", e) for e in (d.get("L1") or [])
              if isinstance(e, str) and e.startswith("agents/")]
        trouvees.append({
            "type": d.get("session_type") or f.stem.removeprefix("session-"),
            "posture": _commentaire(texte, "Posture"),
            "declencheur": _commentaire(texte, "Trigger"),
            "ttl": d.get("ttl_hours"),
            "cible": (d.get("context_target") or {}).get("total_boot", ""),
            "owner": bool(d.get("kerneluser_required")),
            "agents": [a for a in l1 if a in publies],
        })
    if not trouvees:
        raise Illisible(f"aucun contexts/session-*.yml dans {brain}")
    return trouvees


def objets_sql(chemin: Path, motif: str) -> list[str]:
    if not chemin.is_file():
        raise Illisible(f"{chemin} absent")
    return re.findall(motif, chemin.read_text(encoding="utf-8"))


def _premiere_ligne(noeud) -> str:
    import ast
    doc = ast.get_docstring(noeud) or ""
    return doc.strip().splitlines()[0].strip() if doc.strip() else ""


#: `@app.middleware("http")` ou `@app.on_event(...)` ne sont pas des routes.
METHODES = {"get", "post", "put", "patch", "delete", "websocket"}


def routes(brain: Path) -> list[tuple[str, str, str]]:
    """(méthode, chemin, résumé) de chaque route déclarée par un décorateur
    `@app.<méthode>('<chemin>')` — lu dans l'arbre syntaxique, pas dans le
    texte : une route citée en commentaire n'est pas une route."""
    import ast
    src = brain / "brain-engine" / "server.py"
    if not src.is_file():
        raise Illisible(f"{src} absent")
    trouvees = []
    for n in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                    and d.func.attr in METHODES
                    and d.args and isinstance(d.args[0], ast.Constant)):
                trouvees.append((d.func.attr.upper().replace("WEBSOCKET", "WS"),
                                 d.args[0].value, _premiere_ligne(n)))
    if not trouvees:
        raise Illisible(f"aucune route lue dans {src}")
    return trouvees


def outils_mcp(brain: Path) -> list[tuple[str, str]]:
    """(nom, résumé) de chaque fonction décorée `@mcp.tool` dans mcp_server.py."""
    import ast
    src = brain / "brain-engine" / "mcp_server.py"
    if not src.is_file():
        raise Illisible(f"{src} absent")
    trouves = []
    for n in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            f = d.func if isinstance(d, ast.Call) else d
            if isinstance(f, ast.Attribute) and f.attr == "tool" and \
                    isinstance(f.value, ast.Name) and f.value.id == "mcp":
                trouves.append((n.name, _premiere_ligne(n)))
    if not trouves:
        raise Illisible(f"aucun outil MCP lu dans {src}")
    return trouves


class Mesures:
    """Ce que le brain contient, mesuré À LA DEMANDE : une source n'est lue que
    si une page la réclame — un brain sans `mcp_server.py` a quand même sa doc,
    mais une page qui liste les outils MCP y échoue, et le dit."""

    def __init__(self, brain: Path):
        self.brain = brain

    @functools.cached_property
    def agents(self) -> list[dict]:
        return agents(self.brain)

    @functools.cached_property
    def sessions(self) -> list[dict]:
        return sessions(self.brain, {a["id"] for a in self.agents})

    @functools.cached_property
    def tables(self) -> list[str]:
        return objets_sql(self.brain / "brain-engine" / "schema-dolt.sql", r"CREATE TABLE `([^`]+)`")

    @functools.cached_property
    def vues(self) -> list[str]:
        return objets_sql(self.brain / "brain-engine" / "views-dolt.sql",
                          r"CREATE (?:OR REPLACE )?VIEW `?([a-z_]+)`?")

    @functools.cached_property
    def routes(self) -> list[tuple[str, str, str]]:
        return routes(self.brain)

    @functools.cached_property
    def outils(self) -> list[tuple[str, str]]:
        return outils_mcp(self.brain)

    @functools.cached_property
    def types_commit(self) -> list[str]:
        """Les types de commit, lus dans `KERNEL.md` « Commit types » — COMME le
        hook `commit-msg` les lit : la section, jusqu'au titre suivant, puis les
        lignes de tableau `| `type:` | …`. La skill disait « feat:, fix:,
        scribe:, config:… » à la main, et une session a tenté `release:` et
        `docs:` — refusés tous deux par le hook."""
        kernel = self.brain / "KERNEL.md"
        if not kernel.is_file():
            raise Illisible("KERNEL.md introuvable — les types de commit n'ont pas de source")
        dedans, trouves = False, []
        for ligne in kernel.read_text(encoding="utf-8").splitlines():
            if ligne.startswith("## Commit types"):
                dedans = True
                continue
            if dedans and re.match(r"^## [^C]", ligne):
                break
            if dedans:
                m = re.match(r"^\| *`([a-z]+):` *\|", ligne)
                if m:
                    trouves.append(m.group(1))
        if not trouves:
            raise Illisible("aucun type de commit dans KERNEL.md « Commit types »")
        return trouves

    @functools.cached_property
    def version(self) -> str:
        compose = self.brain / "brain-compose.yml"
        m = re.search(r'^version:\s*"?([^"\s]+)"?', compose.read_text(encoding="utf-8"),
                      re.MULTILINE) if compose.is_file() else None
        if not m:
            raise Illisible("version introuvable dans brain-compose.yml")
        return m.group(1)

    @functools.cached_property
    def satellites(self) -> list[dict]:
        """Les satellites déclarés, et l'adresse de leur dépôt sur la forge.

        La forge se déduit du remote du brain : ses satellites vivent chez le même
        propriétaire. Un identifiant dans l'URL (un clone HTTPS l'y garde parfois)
        est retiré avant toute écriture — il finirait dans le README."""
        decl = self.brain / "satellites.yml"
        if yaml is None or not decl.is_file():
            raise Illisible("satellites.yml absent ou PyYAML manquant")
        sats = (yaml.safe_load(decl.read_text(encoding="utf-8")) or {}).get("satellites") or {}
        # Le brain jugé n'a pas toujours de remote : le hook pre-commit juge une COPIE
        # de l'index, sans .git. La forge se lit alors dans le dépôt du script lui-même.
        url = ""
        for depot in (self.brain, Path(__file__).resolve().parent.parent):
            r = subprocess.run(["git", "-C", str(depot), "remote", "get-url", "origin"],
                               capture_output=True, text=True)
            url = r.stdout.strip()
            if url:
                break
        m = (re.match(r"^[\w.-]+@([\w.-]+):([\w.-]+)/", url)
             or re.match(r"^https?://(?:[^@/]+@)?([\w.:-]+)/([\w.-]+)/", url))
        # Sans forge reconnaissable (un remote en chemin local — un bac à sable, un
        # fork sans forge) : la table sans liens, plutôt qu'une doc illisible.
        forge = f"https://{m.group(1)}/{m.group(2)}" if m else None
        return [{"dossier": d, "depot": v.get("depot", d),
                 "url": f"{forge}/{v.get('depot', d)}" if forge else None,
                 "machines": v.get("machines") or [], "chemin": v.get("chemin")}
                for d, v in sats.items() if isinstance(v, dict)]

    def __getitem__(self, cle: str):  # les blocs lisent m["agents"]…
        return getattr(self, cle)


def mesurer(brain: Path) -> Mesures:
    return Mesures(brain)


# ── Écrire ─────────────────────────────────────────────────────────────────

def bloc_sessions(m: dict) -> str:
    lignes = ["| Type | Posture | Se lance par | Claim | Contexte au boot | Agents chargés d'office |",
              "|---|---|---|---|---|---|"]
    for s in m["sessions"]:
        ags = " · ".join(f"`{a}`" for a in s["agents"]) or "—"
        typ = f"**{s['type']}**" + (" (owner)" if s["owner"] else "")
        lignes.append(f"| {typ} | {s['posture'] or '—'} | `{s['declencheur']}` | "
                      f"{s['ttl']} h | {s['cible'] or '—'} | {ags} |")
    return "\n".join(lignes)


def bloc_agents(m: dict) -> str:
    groupes: dict[tuple, list[dict]] = {}
    for a in m["agents"]:
        groupes.setdefault((a["scope"], a["type"]), []).append(a)
    connues = [cle for cle, _ in FAMILLES]
    sortie = []
    for cle, titre in FAMILLES + tuple(((c, f"{c[0]} / {c[1]}") for c in sorted(groupes, key=str)
                                        if c not in connues)):
        membres = groupes.get(cle)
        if not membres:
            continue
        sortie.append(f"### {titre} ({len(membres)})\n")
        for a in membres:
            sortie.append(f"- **`{a['id']}`** — {a['description'] or 'sans description déclarée'}")
        sortie.append("")
    return "\n".join(sortie).rstrip()


def bloc_tables(m: dict) -> str:
    return (f"**Tables ({len(m['tables'])})** — " + ", ".join(f"`{t}`" for t in m["tables"])
            + f"\n\n**Vues ({len(m['vues'])})** — " + ", ".join(f"`{v}`" for v in m["vues"]))


def bloc_routes(m: dict) -> str:
    lignes = ["| Méthode | Route | Ce qu'elle fait |", "|---|---|---|"]
    for meth, chemin, resume in sorted(m["routes"], key=lambda r: (r[1], r[0])):
        lignes.append(f"| {meth} | `{chemin}` | {resume.replace('|', '/') or '—'} |")
    return "\n".join(lignes)


def bloc_outils(m: dict) -> str:
    return "\n".join(f"- **`{nom}`** — {resume or 'sans résumé déclaré'}" for nom, resume in m["outils"])


def bloc_satellites(m: dict) -> str:
    lignes = ["| Dossier | Dépôt | Machines |", "|---|---|---|"]
    for s in m["satellites"]:
        url = s["url"]
        if url and s["depot"].endswith(".wiki"):
            url = url[:-len(".wiki")] + "/wiki"       # un wiki Gitea se lit à l'adresse du dépôt
        ou = f"`{s['chemin']}` (hors du brain)" if s["chemin"] else f"`{s['dossier']}/`"
        depot = f"[{s['depot']}]({url})" if url else f"`{s['depot']}`"
        lignes.append(f"| {ou} | {depot} | {', '.join(s['machines']) or '—'} |")
    return "\n".join(lignes)


BLOCS = {"sessions": bloc_sessions, "agents": bloc_agents, "tables": bloc_tables,
         "routes": bloc_routes, "outils": bloc_outils, "satellites": bloc_satellites}


VALEURS = {
    "VERSION": lambda m: m.version,
    "NB_AGENTS": lambda m: str(len(m.agents)),
    "NB_SESSIONS": lambda m: str(len(m.sessions)),
    "NB_TABLES": lambda m: str(len(m.tables)),
    "NB_VUES": lambda m: str(len(m.vues)),
    "NB_ROUTES": lambda m: str(len(m.routes)),
    "NB_OUTILS": lambda m: str(len(m.outils)),
    "NB_SATELLITES": lambda m: str(len(m.satellites)),
    "TYPES_DE_COMMIT": lambda m: ", ".join(f"`{x}:`" for x in m.types_commit),
}


#: Ce qui ressemble à un marqueur sans en être un : `{{ NB_AGENTS }}`,
#: `{{NB_AGENTS2}}`, `<!-- genere:outils-mcp -->` indenté… Resté dans la page,
#: il s'affichait comme un vide — une erreur, pas un silence.
RESTE = re.compile(r"\{\{[^}]*\}\}|<!--\s*genere\s*:[^>]*-->")


def hors_code(texte: str, en_ligne, ligne_entiere) -> str:
    """Applique `en_ligne` au texte HORS code (ni bloc ```, ni `span`) et
    `ligne_entiere` aux lignes hors bloc. Un `{{NB_AGENTS}}` écrit en code est un
    EXEMPLE de la syntaxe : le remplacer faisait dire à la page qui explique le
    mécanisme « `74`, jamais 75 écrit à la main » (relecture du 28/09)."""
    sortie, dans_bloc = [], False
    for ligne in texte.split("\n"):
        if ligne.lstrip().startswith(("```", "~~~")):
            dans_bloc = not dans_bloc
            sortie.append(ligne)
            continue
        if dans_bloc:
            sortie.append(ligne)
            continue
        ligne = ligne_entiere(ligne)
        morceaux = re.split(r"(`[^`]*`)", ligne)
        sortie.append("".join(m if m.startswith("`") and m.endswith("`") and len(m) > 1
                              else en_ligne(m) for m in morceaux))
    return "\n".join(sortie)


def rendre(source: str, nom: str, m: Mesures) -> str:
    def val(x):
        if x.group(1) not in VALEURS:
            raise Illisible(f"{nom} : valeur inconnue {{{{{x.group(1)}}}}}")
        return VALEURS[x.group(1)](m)

    def bloc(x):
        if x.group(1) not in BLOCS:
            raise Illisible(f"{nom} : bloc inconnu « {x.group(1)} »")
        return BLOCS[x.group(1)](m)

    corps = hors_code(source, lambda t: PLACEHOLDER.sub(val, t), lambda l: BLOC.sub(bloc, l))
    restes = []
    hors_code(corps, lambda t: (restes.extend(RESTE.findall(t)), t)[1], lambda l: l)
    if restes:
        raise Illisible(f"{nom} : marqueur mal formé, resté tel quel — {restes[0]!r}")
    # Une page avec frontmatter porte la mention en commentaire YAML, DEDANS :
    # le moteur retire le frontmatter avant de servir, et le dashboard afficherait
    # un commentaire HTML en texte brut (react-markdown sans HTML).
    if corps.startswith("---\n"):
        return "---\n# " + EN_TETE_TEXTE.format(nom=nom) + "\n" + corps[4:]
    return EN_TETE.format(nom=nom) + corps


def attendu(brain: Path) -> dict[str, str]:
    """{chemin de sortie relatif : texte} pour toutes les cibles présentes."""
    m, voulu, vues = None, {}, 0
    for src_rel, out_rel in CIBLES:
        src = brain / src_rel
        if not src.is_dir():
            continue
        vues += 1
        m = m or mesurer(brain)
        for p in sorted(src.glob("*.md")):
            voulu[f"{out_rel}/{p.name}"] = rendre(p.read_text(encoding="utf-8"),
                                                  f"{src_rel}/{p.name}", m)
    if not vues or not voulu:
        raise Illisible(f"aucune source dans {', '.join(c for c, _ in CIBLES)}")
    for src_rel, out_rel in FICHIERS:
        if (brain / src_rel).is_file():
            voulu[out_rel] = rendre((brain / src_rel).read_text(encoding="utf-8"), src_rel,
                                    m or mesurer(brain))
    return voulu


def presentes(brain: Path) -> set[str]:
    """Les pages générées déjà sur le disque, au premier niveau de chaque cible."""
    trouvees = set()
    for src_rel, out_rel in CIBLES:
        if (brain / src_rel).is_dir():
            trouvees |= {f"{out_rel}/{p.name}" for p in (brain / out_rel).glob("*.md")}
    return trouvees


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", type=Path, default=Path(__file__).resolve().parent.parent)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--ecrire", action="store_true")
    mode.add_argument("--check", action="store_true")
    a = ap.parse_args()
    brain = a.brain.resolve()
    try:
        voulu = attendu(brain)
    except Illisible as e:
        print(f"docs-generer: illisible — {e}", file=sys.stderr)
        return 2
    except Exception as e:  # un frontmatter qui est une liste, un YAML inattendu…
        # 1 veut dire « en retard » : un plantage n'est pas un verdict.
        print(f"docs-generer: illisible — {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    en_retard = sorted(n for n, t in voulu.items()
                       if not (brain / n).is_file() or (brain / n).read_text(encoding="utf-8") != t)
    orphelines = sorted(presentes(brain) - set(voulu))

    if a.ecrire:
        for n in en_retard:
            (brain / n).parent.mkdir(parents=True, exist_ok=True)
            (brain / n).write_text(voulu[n], encoding="utf-8")
            print(f"  ✍️  {n}")
        for n in orphelines:
            (brain / n).unlink()
            print(f"  🧹 {n} — sans source, retirée")
        print(f"✓ à jour — {len(voulu)} pages")
        return 0

    if a.check:
        for n in en_retard:
            print(f"  ⚠ {n} en retard sur sa source ou sur le brain")
        for n in orphelines:
            print(f"  ⚠ {n} sans source")
        if en_retard or orphelines:
            print("✗ pas à jour — python3 scripts/docs-generer.py --ecrire")
            return 1
        print(f"✓ à jour — {len(voulu)} pages")
        return 0

    m = mesurer(brain)
    for k, f in VALEURS.items():
        try:
            print(f"  {{{{{k}}}}} = {f(m)}")
        except Illisible as e:
            print(f"  {{{{{k}}}}} — illisible ({e})")
    print(f"  blocs : {', '.join(BLOCS)} — {len(voulu)} pages, {len(en_retard)} en retard, "
          f"{len(orphelines)} sans source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
