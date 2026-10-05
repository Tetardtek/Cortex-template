#!/usr/bin/env python3
"""Registre d'agents dérivé — le frontmatter est la seule source de vérité.

`agents/CATALOG.yml` et le frontmatter des agents décrivent la même chose et
divergent (26 % des agents hors registre, 30 % de désaccord sur `export` au
02/09). Un registre *généré* ne peut pas diverger : il est recalculé, jamais
édité.

Cet outil lit `agents/*.md`, classe chaque agent selon ce qu'il déclare déjà, et
émet le catalogue. Il ne tranche jamais un conflit tout seul — il le signale et
sort en erreur.

    python3 tools/agent_registry.py --brain ~/Dev/Brain              # rapport
    python3 tools/agent_registry.py --brain ~/Dev/Brain --emit out.yml
    python3 tools/agent_registry.py --brain ~/Dev/Brain --check      # pour la CI

Classification, sans jugement, depuis ce que les fichiers déclarent :

    scope == personal → PRIVE      ne se distribue pas
    sinon             → PROGRAMME  artefact conçu, livré, ombrable

Décision du 02/09 : `agents/` et `contexts/` sont du programme. La catégorie
ETAT reposait sur `writer:`, qui déclarait une intention jamais exercée — 286
commits dans agents/, tous humains. Le champ a été retiré : une classification
dérivée ne doit dériver que de ce qui décrit la réalité.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("FAIL: PyYAML requis (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(1)

PRIVE, PROGRAMME = "prive", "programme"


class Agent:
    __slots__ = ("id", "path", "meta", "brain", "errors")

    def __init__(self, path: Path, meta: dict, brain: dict, errors: list[str],
                 agent_id: str | None = None):
        self.id = agent_id or path.stem
        self.path = path
        self.meta = meta
        self.brain = brain
        self.errors = errors

    @property
    def scope(self) -> str | None:
        return self.brain.get("scope")

    @property
    def export(self) -> bool | None:
        value = self.brain.get("export")
        return value if isinstance(value, bool) else None

    @property
    def classification(self) -> str:
        return PRIVE if self.scope == "personal" else PROGRAMME

    @property
    def hold(self) -> str | None:
        """Retenue explicite et motivée. Rare, périssable, jamais un booléen nu.

        Remplace l'ancien `export: false` : un booléen ne dit pas pourquoi,
        personne ne sait quand le lever, il se périme en silence.
        """
        value = self.brain.get("hold") or self.meta.get("hold")
        return str(value).strip() if value else None

    # Un agent qu'on a rangé n'est pas un agent qu'on livre. `hold` est une
    # retenue rare et périssable ; un archivage ne se périme pas, il se lit sur
    # le statut. Sans cette règle, `archive/diagram-scribe.md` — retiré le
    # 18/03 — partait au template.
    STATUTS_RANGES = frozenset({"retired", "archived"})

    @property
    def distributable(self) -> bool:
        """Ce qui part dans l'artefact. Dérivé, jamais déclaré à la main."""
        return (self.classification == PROGRAMME
                and not self.hold
                and self.meta.get("status") not in self.STATUTS_RANGES)


# Les zones d'écriture d'un agent — Convention 6, leurs chemins dans `NIVEAUX.yml`.
ZONES_ECRITURE = ("kernel", "instance", "personal")


def parse_frontmatter(path: Path, agent_id: str | None = None) -> Agent:
    """Lit le frontmatter. Un fichier illisible est signalé, jamais ignoré."""
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    if not text.startswith("---"):
        return Agent(path, {}, {}, ["pas de frontmatter"], agent_id)
    end = text.find("\n---", 3)
    if end == -1:
        return Agent(path, {}, {}, ["frontmatter non terminé"], agent_id)
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError as exc:
        return Agent(path, {}, {}, [f"YAML invalide : {str(exc).splitlines()[0]}"],
                     agent_id)
    if not isinstance(meta, dict):
        return Agent(path, {}, {}, ["frontmatter n'est pas un mapping"], agent_id)

    brain = meta.get("brain") or {}
    if not isinstance(brain, dict):
        brain, errors = {}, ["bloc `brain:` malformé"]
    # `export` n'est plus attendu : il est dérivé de scope + writer.
    # Un agent qui le porte encore n'a pas été migré.
    if "scope" not in brain:
        errors.append("champ `scope` absent")
    for obsolete, motif in (("export", "dérivé de scope"),
                            ("writer", "retiré — intention jamais exercée")):
        if obsolete in brain:
            errors.append(f"champ `{obsolete}` obsolète — {motif}")
    # `zone_write` : où l'agent ÉCRIT — Convention 6 (`_conventions.md`). Facultatif
    # (un compagnon de session qu'aucun worker ne lance s'en passe), mais déclaré, il
    # est dans le vocabulaire : le worker est jugé contre lui.
    ipc = brain.get("ipc") if isinstance(brain.get("ipc"), dict) else {}
    if "zone_write" in ipc:
        zones = ipc["zone_write"]
        if not isinstance(zones, list):
            errors.append("`zone_write` n'est pas une liste")
        else:
            hors = [z for z in zones if z not in ZONES_ECRITURE]
            if hors:
                errors.append(f"`zone_write` hors vocabulaire : {hors} — "
                              f"{' | '.join(ZONES_ECRITURE)} (Convention 6)")
    return Agent(path, meta, brain, errors, agent_id)


def load_agents(brain_root: Path) -> list[Agent]:
    directory = brain_root / "agents"
    if not directory.is_dir():
        raise SystemExit(f"FAIL: {directory} introuvable")
    # AGENTS.md / CATALOG.yml sont des index ; les fichiers `_*` sont des méta
    # (conventions, gabarits) — `server.py` les exclut déjà de GET /agents.
    #
    # `rglob` et non `glob` : le catalogue ne descendait pas dans les
    # sous-répertoires, donc `games/<jeu>.md` et `archive/diagram-scribe.md`
    # n'étaient déclarés nulle part — et un agent absent du catalogue passait à
    # la publication par défaut, dans le mauvais sens du doute.
    # L'identifiant devient le chemin relatif, sinon deux agents homonymes dans
    # deux répertoires se recouvriraient en silence.
    skip = {"AGENTS", "CATALOG"}
    fichiers = [p for p in sorted(directory.rglob("*.md"))
                if "reviews" not in p.relative_to(directory).parts
                and p.stem not in skip and not p.stem.startswith("_")]
    return [parse_frontmatter(p, str(p.relative_to(directory))[:-3])
            for p in fichiers]


def load_catalog_brut(brain_root: Path) -> dict | None:
    """Le catalogue tel qu'il est écrit, en entier. `None` s'il n'existe pas."""
    path = brain_root / "agents" / "CATALOG.yml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {"agents": []}


def load_catalog(brain_root: Path) -> dict[str, dict]:
    return entrees_par_id(load_catalog_brut(brain_root) or {})


def entrees_par_id(data: dict) -> dict[str, dict]:
    return {e["id"]: e for e in (data.get("agents") or []) if isinstance(e, dict) and "id" in e}


def _tel_qu_emis(registre: dict) -> dict:
    """Le registre tel que `--emit` l'écrirait PUIS qu'on le relirait.

    Comparer à `build_registry` brut serait comparer un objet Python à un
    fichier : un aller-retour YAML met les deux côtés dans la même forme.
    """
    return yaml.safe_load(yaml.safe_dump(registre, allow_unicode=True, sort_keys=False))


def ecarts_au_genere(agents: list[Agent], brut: dict | None) -> list[dict]:
    """Chaque champ où le fichier diffère de ce que `--emit` produirait.

    Le 29/09 : `--check` ne regardait que la présence d'un agent et son
    `export`. Deux descriptions périmées sont restées dans le catalogue sous un
    « ✅ registre cohérent » — `--emit` les a changées de 4 lignes. Le catalogue
    est GÉNÉRÉ : la seule question juste est « est-il ce que `--emit`
    produirait ? », sur la structure entière, pas sur une liste de champs
    choisis — une liste choisie oublie toujours le champ suivant.

    On compare la STRUCTURE relue, pas le texte : le rendu de PyYAML (largeur de
    ligne, guillemets) peut changer d'une version à l'autre sans que le contenu
    change, et un témoin qui rougit sur la mise en page d'une bibliothèque
    apprend à être ignoré.

    Les agents absents d'un côté ne sont pas répétés ici : « hors catalogue » et
    « orphelines » les nomment déjà.
    """
    if brut is None:
        return []
    attendu = _tel_qu_emis(build_registry(agents))
    ecarts = []
    for cle in sorted((set(attendu) | set(brut)) - {"agents"}):
        if brut.get(cle) != attendu.get(cle):
            ecarts.append({"id": "(en-tête)", "champ": cle,
                           "fichier": brut.get(cle), "genere": attendu.get(cle)})
    ecrit, voulu = entrees_par_id(brut), entrees_par_id(attendu)
    for name in sorted(set(ecrit) & set(voulu)):
        for champ in sorted(set(ecrit[name]) | set(voulu[name])):
            if ecrit[name].get(champ) != voulu[name].get(champ):
                ecarts.append({"id": name, "champ": champ,
                               "fichier": ecrit[name].get(champ),
                               "genere": voulu[name].get(champ)})
    # Tout ce qui précède peut être d'accord et la liste différer encore : ordre
    # des entrées, doublon d'un même id (le dict par id l'écrase en silence),
    # entrée sans id. On ne le détaille pas, on refuse de le taire.
    if (not ecarts and set(ecrit) == set(voulu)
            and brut.get("agents") != attendu.get("agents")):
        ecarts.append({"id": "(liste)", "champ": "agents",
                       "fichier": "ordre, doublon ou entrée sans id",
                       "genere": "l'ordre de --emit, une entrée par agent"})
    return ecarts


def diff_against_catalog(agents: list[Agent], catalog: dict[str, dict],
                         brut: dict | None = None) -> dict:
    by_id = {a.id: a for a in agents}
    shared = set(by_id) & set(catalog)
    conflicts = []
    for name in sorted(shared):
        declared = by_id[name].export
        catalogued = catalog[name].get("export")
        if declared is not None and isinstance(catalogued, bool) and declared != catalogued:
            conflicts.append({"id": name, "frontmatter": declared, "catalog": catalogued})
    return {
        "missing_from_catalog": sorted(set(by_id) - set(catalog)),
        "orphan_entries": sorted(set(catalog) - set(by_id)),
        "export_conflicts": conflicts,
        "stale_fields": ecarts_au_genere(agents, brut),
    }


def build_registry(agents: list[Agent]) -> dict:
    entries = []
    for agent in sorted(agents, key=lambda a: (a.classification, a.id)):
        entry = {
            "id": agent.id,
            "classification": agent.classification,
            "scope": agent.scope,
            "distributable": agent.distributable,
            "type": agent.meta.get("type"),
            "status": agent.meta.get("status"),
            "description": (agent.meta.get("description") or "").strip() or None,
        }
        if agent.hold:
            entry["hold"] = agent.hold
        entries.append(entry)

    counts = {k: sum(1 for a in agents if a.classification == k)
              for k in (PROGRAMME, PRIVE)}
    return {
        "generated": True,
        "source": "agents/*.md frontmatter",
        "warning": ("Fichier GÉNÉRÉ — ne pas éditer. Modifier le frontmatter de l'agent, "
                    "puis régénérer avec myeline/tools/agent_registry.py --emit."),
        "derivation": {
            "prive": "scope == personal — ne se distribue pas",
            "programme": "sinon — artefact conçu, livré, ombrable",
            # Ce texte part dans agents/CATALOG.yml, que le gabarit distribue :
            # pas de renvoi au backlog privé — la décision dit sa date.
            "note": "Décision du 02/09 : la categorie ETAT est retiree, `writer:` declarait une intention jamais exercee.",
            "distributable": "programme ET pas de hold",
        },
        "counts": counts,
        "agents": entries,
    }


def _court(valeur, largeur: int = 70) -> str:
    texte = repr(valeur)
    return texte if len(texte) <= largeur else texte[:largeur - 1] + "…"


def report(agents: list[Agent], diff: dict) -> int:
    buckets = {PRIVE: [], PROGRAMME: []}
    for agent in agents:
        buckets[agent.classification].append(agent)

    print(f"\n{len(agents)} agents lus\n")
    print(f"  {'PROGRAMME':<12} {len(buckets[PROGRAMME]):>3}   artefact livré, ombrable")
    print(f"  {'PRIVÉ':<12} {len(buckets[PRIVE]):>3}   scope: personal — ne part pas")

    held = [a for a in agents if a.hold]
    if held:
        print(f"\nRETENUS (`hold`) — {len(held)}, à relire, pas à oublier :")
        for agent in held:
            print(f"  {agent.id:<24} {agent.hold}")

    problems = 0

    malformed = [a for a in agents if a.errors]
    if malformed:
        problems += len(malformed)
        print(f"\nFRONTMATTER INCOMPLET — {len(malformed)} agents :")
        for agent in malformed[:15]:
            print(f"  {agent.id:<24} {', '.join(agent.errors)}")

    contradictions = [
        a for a in agents if a.scope == "personal" and a.export is True
    ]
    if contradictions:
        problems += len(contradictions)
        print(f"\nCONTRADICTION `scope: personal` + `export: true` — {len(contradictions)} :")
        for agent in contradictions:
            print(f"  {agent.id}")

    if diff["missing_from_catalog"]:
        problems += len(diff["missing_from_catalog"])
        print(f"\nHORS CATALOGUE — {len(diff['missing_from_catalog'])} agents :")
        print("  " + ", ".join(diff["missing_from_catalog"]))

    if diff["orphan_entries"]:
        problems += len(diff["orphan_entries"])
        print(f"\nENTRÉES ORPHELINES (catalogue sans fichier) — {len(diff['orphan_entries'])} :")
        print("  " + ", ".join(diff["orphan_entries"]))

    if diff["export_conflicts"]:
        problems += len(diff["export_conflicts"])
        print(f"\nDÉSACCORD `export` fichier vs catalogue — {len(diff['export_conflicts'])} :")
        for conflict in diff["export_conflicts"]:
            print(f"  {conflict['id']:<24} frontmatter={str(conflict['frontmatter']):<6} "
                  f"catalogue={conflict['catalog']}")

    if diff.get("stale_fields"):
        ecarts = diff["stale_fields"]
        problems += len(ecarts)
        print(f"\nCATALOGUE EN RETARD sur `--emit` — {len(ecarts)} champs :")
        for e in ecarts[:20]:
            print(f"  {e['id']:<24} {e['champ']:<15} fichier={_court(e['fichier'])}")
            print(f"  {'':<24} {'':<15} généré ={_court(e['genere'])}")
        if len(ecarts) > 20:
            print(f"  … et {len(ecarts) - 20} autres")
        print("  → régénérer : agent_registry.py --emit agents/CATALOG.yml")

    print(f"\n{'✅ registre cohérent' if not problems else f'❌ {problems} incohérences — '
          'aucune tranchée automatiquement'}")
    return problems



# ── Régénération de la table Dolt ───────────────────────────────────
#
# `agents/CATALOG.yml` est dérivé du frontmatter. La table Dolt
# `agents` est une TROISIÈME copie de la même information, et personne ne l'avait
# alignée : mesuré le 03/09, son seul lecteur vivant est `brain-validate.sh:69`,
# comme `projects` avant.
#
# Elle est un instantané d'avant deux décisions déjà appliquées — `writer` sur
# 91/91 lignes alors qu'il a été retiré du frontmatter, `export_template` sur
# 91/91 alors que `export:` a été remplacé par `hold:`. Un registre régénéré
# ne peut pas conserver ce que la source ne dit plus.

COLONNES_DB = ("id", "name", "type", "context_tier", "domain", "status", "scope",
               "owner", "lifecycle", "read_mode", "triggers", "receives_from",
               "sends_to", "zone_access", "signals", "description")

# Le vocabulaire des FICHES n'est pas celui de la BASE. Une fiche rangée dit
# `retired` ou `archived` (STATUTS_RANGES) ; l'énumération de la colonne
# `agents.status` ne connaît que active, stable, draft, deprecated. Sans
# traduction, `--apply` s'arrêtait sur `archive/diagram-scribe.md` au milieu de
# l'écriture — table à moitié réécrite, rien commité (28/09). Tranché par l'owner :
# la base dit `deprecated`, les fiches ne changent pas.
STATUT_DB = {"retired": "deprecated", "archived": "deprecated"}


def statut_db(statut):
    return STATUT_DB.get(statut, statut)


def hors_enum(voulues: dict, permis: set) -> list[str]:
    """Les lignes dont le statut n'entre pas dans la colonne — à refuser AVANT d'écrire."""
    return sorted(f"{i} ({l['status']})" for i, l in voulues.items()
                  if l["status"] is not None and l["status"] not in permis)


def enum_de(db, table: str, colonne: str) -> set:
    """Les valeurs qu'une colonne ENUM accepte, lues dans la base — pas recopiées."""
    rangs = db.query("SELECT COLUMN_TYPE AS t FROM information_schema.COLUMNS "
                     "WHERE TABLE_NAME = %s AND COLUMN_NAME = %s", (table, colonne))
    texte = rangs[0]["t"] if rangs else ""
    return set(re.findall(r"'([^']*)'", texte)) if texte.startswith("enum(") else set()


DOMAINE_RE = re.compile(r"^>\s*\*{0,2}Domaine\s*:?\*{0,2}\s*(.+)$", re.M)


def _liste(valeur):
    """JSON d'une liste. Un scalaire devient une liste d'un élément.

    `domain` est une chaîne dans 61 fiches et une liste dans 30. La migration
    d'origine ne gérait que le second cas : la colonne valait `[]` pour les 61
    autres. Normaliser récupère 58 valeurs perdues.
    """
    if valeur in (None, "", [], {}):
        return None
    return json.dumps(valeur if isinstance(valeur, list) else [valeur])


def ligne_depuis_agent(agent) -> dict:
    """La ligne que cette fiche décrit."""
    brain = agent.brain or {}
    ipc = brain.get("ipc") or {}
    description = (agent.meta.get("description") or "").strip()
    if not description:
        # 20 fiches n'ont pas de `description:` — leur corps porte une ligne
        # `> Domaine : …`. La base avait scrapé la PREMIÈRE ligne du blockquote,
        # qui est souvent « Dernière validation : … » : 67 descriptions sur 91
        # étaient donc du bruit. Viser la bonne ligne les répare toutes.
        trouve = DOMAINE_RE.search(agent.path.read_text(encoding="utf-8"))
        description = trouve.group(1).strip().lstrip("*").strip() if trouve else None
    return {
        "id":            agent.id,
        "name":          agent.meta.get("name") or agent.id,
        "type":          agent.meta.get("type"),
        "context_tier":  agent.meta.get("context_tier"),
        "domain":        _liste(agent.meta.get("domain")),
        "status":        statut_db(agent.meta.get("status")),
        "scope":         brain.get("scope"),
        "owner":         brain.get("owner"),
        "lifecycle":     brain.get("lifecycle"),
        "read_mode":     brain.get("read"),
        "triggers":      _liste(brain.get("triggers")),
        "receives_from": _liste(ipc.get("receives_from")),
        "sends_to":      _liste(ipc.get("sends_to")),
        "zone_access":   _liste(ipc.get("zone_access")),
        "signals":       _liste(ipc.get("signals")),
        "description":   description or None,
    }


def emettre_db(brain_root: Path, agents: list, *, appliquer: bool, forcer: bool) -> int:
    """Réécrit la table Dolt depuis le frontmatter. Gèle avant, date après."""
    sys.path.insert(0, str(brain_root / "brain-engine"))
    import db

    voulues = {a.id: ligne_depuis_agent(a) for a in agents if not a.errors}
    refusees = [a.id for a in agents if a.errors]
    if not voulues:
        print("\n  ❌ REFUS — aucune fiche exploitable. Un répertoire vide et un")
        print("     répertoire absent se ressemblent ; on ne vide pas une table là-dessus.\n")
        return 1

    # Refuser AVANT le gel et avant la première écriture : une valeur que la
    # colonne n'accepte pas arrêtait l'écriture au milieu de la table.
    permis = enum_de(db, "agents", "status")
    if permis and (fautives := hors_enum(voulues, permis)):
        print(f"\n  ❌ REFUS — statut hors de la colonne ({', '.join(sorted(permis))}) :")
        for f in fautives:
            print(f"     {f}")
        print("     Rien n'est écrit. Traduire dans STATUT_DB, ou corriger la fiche.\n")
        return 1

    base = {r["id"]: r for r in db.query("SELECT * FROM agents")}
    a_supprimer = sorted(set(base) - set(voulues))
    proportion = len(a_supprimer) / len(base) if base else 0

    print(f"\nRÉGÉNÉRATION — {len(voulues)} fiches → table `agents`\n")
    print(f"  à écrire     {len(voulues):>3}")
    print(f"  à supprimer  {len(a_supprimer):>3}   {', '.join(a_supprimer) or '—'}")
    if refusees:
        print(f"  ⚠️  écartées  {len(refusees):>3}   {', '.join(refusees)} — frontmatter en erreur")
    if proportion > 0.25 and not forcer:
        print(f"\n  ❌ REFUS — {proportion:.0%} de la table serait supprimée.")
        print("     Au-delà d'un quart, c'est un évènement : le justifier, puis `--force`.\n")
        return 1
    if not appliquer:
        print("\n  → `--apply` pour geler, écrire, dater\n")
        return 0

    db.freeze("régénération de `agents` depuis le frontmatter")
    for nom, ligne in sorted(voulues.items()):
        if nom in base:
            db.execute("UPDATE agents SET "
                       + ", ".join(f"`{c}` = %s" for c in COLONNES_DB[1:])
                       + ", updated_at = UTC_TIMESTAMP() WHERE id = %s",
                       tuple(ligne[c] for c in COLONNES_DB[1:]) + (nom,))
        else:
            db.execute(
                f"INSERT INTO agents ({', '.join(COLONNES_DB)}, created_at, updated_at) "
                f"VALUES ({', '.join('%s' for _ in COLONNES_DB)}, "
                f"UTC_TIMESTAMP(), UTC_TIMESTAMP())",
                tuple(ligne[c] for c in COLONNES_DB))
    for nom in a_supprimer:
        db.execute("DELETE FROM agents WHERE id = %s", (nom,))
    db._dolt_commit(f"agents : régénéré depuis {len(voulues)} fiches",
                    tables=["agents"])

    apres = {r["id"] for r in db.query("SELECT id FROM agents")}
    coherent = apres == set(voulues)
    print(f"\n  table : {len(apres)} lignes · "
          f"{'✅ conforme aux fiches' if coherent else '❌ ' + str(apres ^ set(voulues))}\n")
    return 0 if coherent else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain", type=Path, required=True)
    parser.add_argument("--emit", type=Path, help="écrire le registre généré")
    parser.add_argument("--check", action="store_true", help="sortie non nulle si incohérence")
    parser.add_argument("--emit-db", action="store_true", dest="emit_db",
                        help="régénérer la table Dolt `agents` (aperçu sans --apply)")
    parser.add_argument("--apply", action="store_true", help="écrire, avec --emit-db")
    parser.add_argument("--force", action="store_true",
                        help="passer outre le plafond de suppressions")
    args = parser.parse_args()

    brain = args.brain.expanduser().resolve()
    agents = load_agents(brain)
    brut = load_catalog_brut(brain)
    diff = diff_against_catalog(agents, entrees_par_id(brut or {}), brut)
    problems = report(agents, diff)

    if args.emit:
        args.emit.parent.mkdir(parents=True, exist_ok=True)
        args.emit.write_text(
            yaml.safe_dump(build_registry(agents), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        print(f"→ {args.emit}")

    if args.emit_db:
        return emettre_db(brain, agents, appliquer=args.apply, forcer=args.force)
    return 1 if (args.check and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
