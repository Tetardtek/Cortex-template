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
                `satellites.yml`), ou un dépôt de code
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
fiche, et la forge borne le reste. Sortie 0, le message le dit.

Sorties : 0 dans la zone (ou dépôt de code) · 1 un chemin hors zone · 2 rien à
juger — agent introuvable, sans `zone_write`, ou `NIVEAUX.yml` illisible.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
AUCUNE = "aucune"


def lire_yaml(chemin: Path) -> dict:
    import yaml
    try:
        return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def registre(brain: Path):
    """Le `Registre` du CORE, nourri de ce que `NIVEAUX.yml` déclare."""
    # Le CORE de CE programme — celui qui vit à côté de l'outil, pas du brain jugé.
    sys.path.insert(0, str(RACINE / "brain-engine"))
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


def prefixe_du_depot(brain: Path, depot: str) -> str | None:
    """`""` pour le brain, `<dossier>/` pour un satellite, None pour un dépôt de code."""
    if depot == "brain":
        return ""
    for dossier, val in (lire_yaml(brain / "satellites.yml").get("satellites") or {}).items():
        # Un satellite qui vit hors du brain (`chemin:`) n'a pas de chemin dans ses zones.
        if isinstance(val, dict) and val.get("depot") == depot and not val.get("chemin"):
            return dossier.rstrip("/") + "/"
    return None


def chemins_du_diff(git: Path, base: str) -> list[str]:
    r = subprocess.run(["git", "-C", str(git), "diff", "--name-only", f"{base}...HEAD"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"❌ git diff {base}...HEAD dans {git} : {r.stderr.strip()}")
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

    prefixe = prefixe_du_depot(a.brain, a.depot)
    if prefixe is None:
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
    sys.exit(main())
