#!/usr/bin/env python3
# brain-distribuable: oui
"""zone-du-diff — la PR d'un worker contre la zone de son agent.

    zone-du-diff.py --agent <nom> --depot <dépôt> [--git <dossier>] [--base <réf>]
    git diff --name-only … | zone-du-diff.py --agent <nom> --depot <dépôt> --stdin

Le worker part avec un agent qui déclare `zone_write` (Convention 6,
`noyau/agents/_conventions.md`) ; l'orchestrator, en jugeant sa PR, rejoue cet
outil comme toute preuve. Chaque chemin du diff reçoit sa zone, et un seul hors
de la déclaration rend le verdict défavorable.

    --depot     le dépôt de la PR, tel que la forge le nomme : `brain`, un
                satellite (`workspace`, `brain-todo`… — son dossier vient de
                `satellites.yml`), ou un dépôt de code — celui qu'une fiche
                projet déclare (`repo:` dans `projets/*.md`)
    --git       le clone où lire le diff (défaut : le dossier courant)
    --base      la base de la PR (défaut : `origin/dev/autonome`)
    --stdin     les chemins, un par ligne, au lieu du diff

Les chemins d'un satellite sont préfixés de son dossier avant d'être jugés : la
PR de `workspace` touche `backlog/…`, le brain y lit `workspace/backlog/…`.

── La règle n'est pas écrite ici ──────────────────────────────────────────

La zone d'un chemin, c'est `core.zones` qui la rend (`Registre.zone`, le préfixe
le plus long) — la même règle que `pre-commit-zone`, un seul exemplaire. Cet
outil fait les LECTURES : `NIVEAUX.yml` (niveaux, exceptions `zone:`,
`zone_personal`, `zone_aucune`), `satellites.yml`, le frontmatter de l'agent.

    `zone_personal`  exclusive : un chemin personnel est `personal`, même là où
                     `kernel` le couvre aussi (`vie/`, `profil/`)
    `zone_aucune`    aucun agent n'y écrit (`brain-secrets/`) : toujours refusé

── Ce qu'il ne juge pas, en le disant ─────────────────────────────────────

Un dépôt de code : les zones parlent du brain. Le périmètre est celui de la
fiche, et la forge borne le reste. Sortie 0, le message le dit. N'est « de code »
que le dépôt d'une fiche projet (`repo:`) ou un satellite qui vit hors du brain
(`chemin:`) : un worker ne part que sur un projet au palier c, qui a sa fiche.
Un nom que le brain ne connaît pas — une faute de frappe, un satellite que ce
brain ne déclare pas — sort en 2 : le juge ne laisse pas passer ce qu'il ne
reconnaît pas.

Sorties : 0 dans la zone (ou dépôt de code) · 1 un chemin hors zone · 2 rien à
juger — dépôt inconnu, agent introuvable, sans `zone_write`, `NIVEAUX.yml`
illisible, ou l'outil
lui-même en panne (`core` introuvable, diff illisible). Une panne n'est jamais
un 1 : « hors zone » se dit d'un chemin, pas d'un plantage.

── Le CORE ────────────────────────────────────────────────────────────────

Un fork le reçoit à côté de l'outil (`brain-engine/core/`). Le brain d'origine
n'en a pas copie : son CORE est celui de Myéline, installé dans le venv de
`brain-engine/`. Lancé par le `python3` du système, l'outil s'y relance donc.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
AUCUNE = "aucune"


class Panne(Exception):
    """L'outil ne peut pas juger — sortie 2, jamais 1."""


def dependances() -> None:
    """`yaml` et le CORE — sinon la relance dans le venv de brain-engine/, une fois."""
    sys.path.insert(0, str(RACINE / "brain-engine"))
    try:
        import yaml  # noqa: F401
        import core.zones  # noqa: F401
    except ImportError as e:
        venv = RACINE / "brain-engine" / ".venv" / "bin" / "python3"
        if venv.is_file() and not os.environ.get("ZONE_DU_DIFF_RELANCE"):
            # Rien n'est encore lu de l'entrée : la relance la reçoit intacte.
            os.environ["ZONE_DU_DIFF_RELANCE"] = "1"
            os.execv(str(venv), [str(venv), *sys.argv])
        raise Panne(f"`{e.name}` introuvable — ni pour ce python, ni dans le venv "
                    f"de brain-engine/") from None


def lire_yaml(chemin: Path) -> dict:
    import yaml
    try:
        return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def registre(brain: Path):
    """Le `Registre` du CORE, nourri de ce que `NIVEAUX.yml` déclare."""
    # Le CORE de CE programme — celui qui vit à côté de l'outil, pas du brain jugé.
    from core.zones import Registre
    d = lire_yaml(brain / "NIVEAUX.yml")
    niveaux, exceptions = {}, {}
    for nom, val in (d.get("entrees") or {}).items():
        if isinstance(val, dict):
            if val.get("niveau"):
                niveaux[nom] = val["niveau"]
            if val.get("zone"):
                exceptions[nom] = val["zone"]
        elif val:
            niveaux[nom] = val
    if not niveaux:
        return None
    # Plus fines que les entrées : le préfixe le plus long les fait l'emporter.
    for prefixe in d.get("zone_personal") or []:
        exceptions[prefixe.rstrip("*")] = "personal"
    for prefixe in d.get("zone_aucune") or []:
        exceptions[prefixe.rstrip("*")] = AUCUNE
    return Registre(niveaux=niveaux, exceptions=exceptions)


def zone_write(brain: Path, agent: str) -> list[str] | None:
    """La `zone_write` de l'agent — la vue d'abord, sinon l'instance, puis le noyau."""
    for dossier in ("agents", "instance/agents", "noyau/agents"):
        fichier = brain / dossier / f"{agent}.md"
        if not fichier.is_file():
            continue
        texte = fichier.read_text(encoding="utf-8")
        fin = texte.find("\n---", 3)
        if not texte.startswith("---") or fin == -1:
            return None
        import yaml
        try:
            meta = yaml.safe_load(texte[3:fin]) or {}
        except yaml.YAMLError:
            return None
        ipc = (meta.get("brain") or {}).get("ipc") or {}
        zones = ipc.get("zone_write") if isinstance(ipc, dict) else None
        return zones if isinstance(zones, list) else None
    return None


CODE = object()   # un dépôt de code connu : les zones n'y jugent rien


def depots_de_code(brain: Path) -> set[str]:
    """Les dépôts que les fiches projet déclarent (`repo:`) — le dernier segment."""
    noms = set()
    for fiche in sorted((brain / "projets").glob("*.md")):
        texte = fiche.read_text(encoding="utf-8", errors="replace")
        fin = texte.find("\n---", 3)
        if not texte.startswith("---") or fin == -1:
            continue
        for ligne in texte[3:fin].splitlines():
            if ligne.startswith("repo:"):
                valeur = ligne[5:].split("#", 1)[0].strip().strip("'\"").rstrip("/")
                nom = valeur.rsplit("/", 1)[-1].removesuffix(".git")
                if nom and "<" not in nom:      # le gabarit d'une fiche : `<depot>`
                    noms.add(nom)
    return noms


def prefixe_du_depot(brain: Path, depot: str):
    """`""` pour le brain, `<dossier>/` pour un satellite, CODE pour un dépôt de code
    connu, None pour un nom que ce brain ne connaît pas."""
    if depot == "brain":
        return ""
    for dossier, val in (lire_yaml(brain / "satellites.yml").get("satellites") or {}).items():
        if isinstance(val, dict) and val.get("depot") == depot:
            # Un satellite qui vit hors du brain (`chemin:`) n'a pas de chemin dans ses zones.
            return CODE if val.get("chemin") else dossier.rstrip("/") + "/"
    return CODE if depot in depots_de_code(brain) else None


def chemins_du_diff(git: Path, base: str) -> list[str]:
    r = subprocess.run(["git", "-C", str(git), "diff", "--name-only", f"{base}...HEAD"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Panne(f"git diff {base}...HEAD dans {git} : {r.stderr.strip()}")
    return [l for l in r.stdout.splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", required=True)
    ap.add_argument("--depot", required=True)
    ap.add_argument("--git", type=Path, default=Path.cwd())
    ap.add_argument("--base", default="origin/dev/autonome")
    ap.add_argument("--brain", type=Path, default=RACINE)
    ap.add_argument("--stdin", action="store_true")
    a = ap.parse_args()
    dependances()

    prefixe = prefixe_du_depot(a.brain, a.depot)
    if prefixe is None:
        print(f"⛔ {a.depot} : dépôt inconnu — ni `brain`, ni un satellite de `satellites.yml`, "
              f"ni le `repo:` d'une fiche projet. Rien à juger.")
        return 2
    if prefixe is CODE:
        print(f"ⓘ  {a.depot} est un dépôt de code : les zones parlent du brain, elles ne "
              f"jugent rien ici — le périmètre de la fiche, et la forge.")
        return 0

    zones = zone_write(a.brain, a.agent)
    if zones is None:
        print(f"⛔ {a.agent} : agent introuvable, ou sans `zone_write` — un worker ne part "
              f"pas sans elle (Convention 6). Rien à juger.")
        return 2
    reg = registre(a.brain)
    if reg is None:
        print("⛔ NIVEAUX.yml illisible — aucune zone à rendre. Rien à juger.")
        return 2

    chemins = ([l.strip() for l in sys.stdin if l.strip()] if a.stdin
               else chemins_du_diff(a.git, a.base))

    hors = []
    print(f"{a.agent} — zone_write: [{', '.join(zones)}] · dépôt {a.depot}")
    for c in chemins:
        complet = prefixe + c
        z = reg.zone(complet)
        ok = z != AUCUNE and z in zones
        print(f"  {'✅' if ok else '❌'} {complet:<60} {z}")
        if not ok:
            hors.append(complet)

    if hors:
        print(f"\nVERDICT : {len(hors)} chemin(s) hors de la zone de {a.agent} — défavorable.")
        return 1
    print(f"\nVERDICT : {len(chemins)} chemin(s), tous dans la zone de {a.agent}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Panne as e:
        print(f"⛔ {e} — rien à juger.")
        sys.exit(2)
    except Exception:
        import traceback
        traceback.print_exc()
        print("⛔ l'outil est en panne (trace ci-dessus) — rien à juger.")
        sys.exit(2)
