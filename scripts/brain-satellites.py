#!/usr/bin/env python3
# brain-distribuable: oui
"""Les satellites de CETTE machine sont-ils là, et à jour ? — `satellites.yml`.

    brain-satellites.py            état de chaque dépôt (lecture seule)
    brain-satellites.py --check    idem, pour le doctor : 0 à jour, 1 sinon
    brain-satellites.py --pull     met à jour en avance rapide ce qui est derrière
    brain-satellites.py --cloner   clone les satellites déclarés et absents

Ce qui pourrirait en silence sans lui : **une machine qui boote sur un état
révolu.** Le 27/09, le laptop avait `profil/` en retard de 30 commits — il
bootait sans les règles de travail du jour — et rien ne le disait : aucun
mécanisme ne mettait un satellite à jour hors de l'installation.

Le brain lui-même est compté avec ses satellites : il était en retard aussi.

── Ce qu'il mesure, par dépôt ──────────────────────────────────────────────

    à jour      la tête locale est celle de l'amont
    derrière    l'amont a des commits que la machine n'a pas     → --pull
    devant      des commits locaux jamais poussés — l'autre machine ne les
                verra pas
    divergé     les deux
    absent      déclaré pour cette machine, pas sur le disque (ou
                un dossier vide)                                  → --cloner
    pas un dépôt  un dossier AVEC du contenu à la place : jamais écrasé
    non déclaré un dépôt sous le brain que la liste ignore
    sans amont  une branche qui ne suit rien

Un arbre modifié (« en cours ») est dit, jamais rougi : c'est du travail.

── Lecture seule, vraiment ─────────────────────────────────────────────────

L'état et `--check` interrogent l'amont par `git ls-remote` : ni `fetch`, ni
référence distante réécrite. Seul `--pull` récupère, et il n'avance qu'en
AVANCE RAPIDE (`merge --ff-only`) : jamais un dépôt devant ou divergé, et git
refuse de lui-même si un fichier modifié sur le disque serait écrasé.

Injoignable (réseau, forge) : le dépôt s'abstient. Si aucun ne répond, le
contrôle entier s'abstient — un vert qui n'a rien mesuré est pire qu'un rouge.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent
DELAI = 20  # secondes par appel réseau


# Au boot, personne ne répond à une question : un identifiant HTTPS manquant ou
# une clé d'hôte inconnue ferait ATTENDRE git jusqu'au délai. Il échoue à la
# place, et le dépôt est dit injoignable. Une commande ssh déjà réglée est gardée.
# Et git parle anglais : `motif_du_refus` lit ses messages, un git traduit
# le rendrait muet sans une erreur.
SANS_QUESTION = {"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "LANGUAGE": "",
                 "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")}


def git(depot: Path, *args: str, delai: int = DELAI) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(depot), *args], capture_output=True,
                          text=True, timeout=delai, env={**os.environ, **SANS_QUESTION})


def lire_yaml(chemin: Path) -> dict:
    import yaml
    return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}


def machine_courante(brain: Path) -> str | None:
    f = brain / "brain-compose.local.yml"
    return lire_yaml(f).get("machine") if f.is_file() else None


def base_de_la_forge(brain: Path) -> str | None:
    """L'URL du brain sans son nom : chaque machine garde son transport."""
    r = git(brain, "remote", "get-url", "origin")
    url = r.stdout.strip()
    return url.rsplit("/", 1)[0] if r.returncode == 0 and "/" in url else None


def etat(depot: Path) -> tuple[str, str]:
    """(état, détail) d'un dépôt présent. Ne récupère rien."""
    r = git(depot, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if r.returncode != 0:
        return "sans amont", git(depot, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    distant, _, branche = r.stdout.strip().partition("/")
    tete = git(depot, "rev-parse", "HEAD").stdout.strip()
    try:
        r = git(depot, "ls-remote", distant, f"refs/heads/{branche}")
    except subprocess.TimeoutExpired:
        return "injoignable", f"{distant}/{branche} — délai dépassé"
    if r.returncode != 0 or not r.stdout.strip():
        return "injoignable", f"{distant}/{branche}"
    amont = r.stdout.split()[0]
    sale = bool(git(depot, "status", "--porcelain", "--untracked-files=no").stdout.strip())
    note = " · en cours" if sale else ""
    note += "" if branche == "main" else f" · branche {branche}"
    if amont == tete:
        return "à jour", note.lstrip(" ·")
    connu = git(depot, "cat-file", "-e", f"{amont}^{{commit}}").returncode == 0
    if not connu:
        return "derrière", f"l'amont a des commits non récupérés{note}"
    devant = int(git(depot, "rev-list", "--count", f"{amont}..HEAD").stdout or 0)
    derriere = int(git(depot, "rev-list", "--count", f"HEAD..{amont}").stdout or 0)
    if devant and derriere:
        return "divergé", f"{devant} devant, {derriere} derrière{note}"
    if devant:
        return "devant", f"{devant} commit(s) jamais poussé(s){note}"
    return "derrière", f"{derriere} commit(s){note}"


def mettre_a_jour(depot: Path) -> tuple[bool, str]:
    """Avance rapide seulement. Git refuse s'il écraserait un fichier modifié."""
    try:
        if git(depot, "fetch", "-q", delai=120).returncode != 0:
            return False, "fetch échoué"
    except subprocess.TimeoutExpired:
        return False, "fetch — délai dépassé"
    r = git(depot, "merge", "-q", "--ff-only", "@{u}", delai=120)
    if r.returncode != 0:
        return False, motif_du_refus(r.stderr)
    return True, "mis à jour"


def motif_du_refus(stderr: str) -> str:
    """Ce qui bloque, dit utilement. La dernière ligne de git est « Aborting » :
    elle ne dit ni quoi ni pourquoi. Les fichiers qu'il protège, si."""
    lignes = [l.strip() for l in stderr.splitlines() if l.strip()]
    fichiers = [l for l in lignes if not l.endswith((".", ":")) and not l.startswith(
        ("error", "fatal", "hint", "Please", "Aborting"))]
    if "overwritten" in stderr and fichiers:
        return f"modifié ici ET dans l'amont — à commiter d'abord : {', '.join(fichiers[:4])}" \
               + (f" (+{len(fichiers) - 4})" if len(fichiers) > 4 else "")
    return next((l for l in lignes if l.startswith(("error", "fatal"))), lignes[0] if lignes else "refusé")


def vide_ou_absent(dossier: Path) -> bool:
    """Absent, ou dossier vide — `git clone` accepte un dossier vide. Le laptop
    avait un `wiki/` vide depuis son installation : il le restait."""
    return not dossier.exists() or (dossier.is_dir() and not any(dossier.iterdir()))


def emplacement(brain: Path, cle: str, declaration: dict | None) -> Path:
    """Où vit le dépôt : sous le brain, à sa clé — ou ailleurs, à son `chemin:`.

    `chemin:` sert un dépôt dont le brain dépend sans le contenir : `myeline`,
    le CORE, vit hors du brain par décision (PATHS.md). Sans lui dans la liste,
    une machine pouvait tirer un brain qui attend un CORE plus récent que le sien
    — et son moteur ne démarrait plus (1/10). Absolu ou `~`, jamais relatif :
    relatif à quoi, sinon ?
    """
    chemin = (declaration or {}).get("chemin")
    if not chemin:
        return brain / cle
    lieu = Path(os.path.expanduser(str(chemin)))
    if not lieu.is_absolute():
        raise SystemExit(f"❌ satellites.yml : `{cle}` a un chemin relatif ({chemin}) — "
                         "absolu ou `~/…` seulement")
    return lieu


def depots_presents(brain: Path) -> set[str]:
    """Les dépôts git sous le brain (deux niveaux), hors le brain lui-même."""
    return {str(g.parent.relative_to(brain)) for motif in ("*/.git", "*/*/.git")
            for g in brain.glob(motif)}


def main() -> int:
    p = argparse.ArgumentParser(description="Les satellites de cette machine")
    p.add_argument("--brain", type=Path, default=BRAIN)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="pour le doctor : 0 à jour, 1 sinon")
    mode.add_argument("--pull", action="store_true", help="avance rapide de ce qui est derrière")
    mode.add_argument("--cloner", action="store_true", help="clone les satellites absents")
    p.add_argument("--quiet", action="store_true", help="ne dire que ce qui ne va pas")
    a = p.parse_args()
    brain = a.brain.resolve()

    liste = brain / "satellites.yml"
    if not liste.is_file():
        print(f"SKIP {liste.name} absent — aucune liste de satellites déclarée.")
        return 0
    ici = machine_courante(brain)
    if not ici:
        print("SKIP `machine:` absent de brain-compose.local.yml — impossible de "
              "savoir quels satellites concernent cette machine.")
        return 0
    declares = lire_yaml(liste).get("satellites") or {}
    miens = {c: d for c, d in declares.items() if ici in (d or {}).get("machines", [])}
    if not miens:
        # Presque toujours une faute de nom : le laptop s'est déclaré
        # `laptop-perso`, puis `prod-laptop`, quand la liste attendait `laptop`.
        connues = sorted({m for d in declares.values() for m in (d or {}).get("machines", [])})
        print(f"❌ aucun satellite déclaré pour `{ici}` — machines connues : "
              f"{', '.join(connues)}. Vérifier `machine:` dans brain-compose.local.yml.")
        return 1

    if a.cloner:
        base = base_de_la_forge(brain)
        if not base:
            print("❌ l'URL du brain est illisible — impossible de dériver celle des satellites")
            return 1
        manquants = [c for c in miens if vide_ou_absent(emplacement(brain, c, miens[c]))]
        for c in manquants:
            url = f"{base}/{miens[c]['depot']}.git"
            r = subprocess.run(["git", "clone", "-q", url, str(emplacement(brain, c, miens[c]))],
                               capture_output=True, text=True, timeout=600,
                               env={**os.environ, **SANS_QUESTION})
            print(f"  {'✅' if r.returncode == 0 else '❌'} {c:<16} {url}"
                  + ("" if r.returncode == 0 else f" — {r.stderr.strip()[-120:]}"))
        if not manquants:
            print(f"✅ rien à cloner — les {len(miens)} satellites de `{ici}` sont là")
        return 0 if all((emplacement(brain, c, miens[c]) / ".git").exists() for c in miens) else 1

    lignes: list[tuple[str, str, str]] = []
    for chemin in [".", *miens]:
        depot = brain if chemin == "." else emplacement(brain, chemin, miens[chemin])
        if vide_ou_absent(depot):
            lignes.append((chemin, "absent", "→ --cloner"))
            continue
        if not (depot / ".git").exists():
            # Un dossier qui a du contenu n'est jamais écrasé : c'est à l'humain.
            lignes.append((chemin, "pas un dépôt", "le dossier a du contenu — à voir à la main"))
            continue
        e, d = etat(depot)
        if a.pull and e == "derrière":
            ok, d = mettre_a_jour(depot)
            e = "à jour" if ok else "bloqué"
        lignes.append((chemin, e, d))
    for chemin in sorted(depots_presents(brain) - set(declares)):
        lignes.append((chemin, "non déclaré", "absent de satellites.yml"))

    signes = {"à jour": "✅", "injoignable": "⏭️"}
    injoignables = sum(e == "injoignable" for _, e, _ in lignes)
    interroges = [l for l in lignes if l[1] not in ("absent", "non déclaré")]
    derives = [l for l in lignes if l[1] not in ("à jour", "injoignable")]
    if interroges and injoignables == len(interroges):
        print(f"SKIP forge injoignable — {injoignables} dépôt(s) sans réponse, rien mesuré.")
        return 0

    for chemin, e, d in lignes:
        if a.quiet and e in ("à jour", "injoignable"):
            continue
        nom = "brain" if chemin == "." else chemin
        print(f"  {signes.get(e, '❌')} {nom:<16} {e:<12} {d}")
    total = len(miens) + 1
    if derives:
        print(f"❌ {len(derives)} dépôt(s) sur {total} ne sont pas à jour sur `{ici}`"
              + (f" ({injoignables} injoignable(s))" if injoignables else ""))
        if not a.pull:
            print("   → python3 scripts/brain-satellites.py --pull   (et --cloner pour un absent)")
        return 1
    if not a.quiet or injoignables:
        print(f"✅ les {total} dépôts de `{ici}` sont à jour"
              + (f" — {injoignables} injoignable(s), non mesuré(s)" if injoignables else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
