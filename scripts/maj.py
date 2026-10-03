#!/usr/bin/env python3
# brain-distribuable: oui
"""brain maj — recevoir une version du gabarit, de bout en bout.

    brain maj                    le plan vers la dernière version : rien ne bouge
    brain maj v2.6.3             le plan vers cette version
    brain maj --appliquer        fusionner, régénérer, réinstaller, déclarer
    brain maj --appliquer --sans-unites    sans réinstaller les unités systemd

La procédure de `docs/mettre-a-jour.md`, jouée d'un bout à l'autre. Elle ne se
lance jamais seule : le boot dit qu'une version existe (`maj-disponible.py`),
c'est toi qui décides de la recevoir.

── Ce qui ne bouge jamais ─────────────────────────────────────────────────

Ce que ton fork a créé. Tes pistes, ton profil, tes todos, `vie/`, `contenu/` :
git ne les voit pas, une fusion ne peut pas y toucher. Tes projets et tes
agents : l'amont n'a pas ces fichiers, une fusion ne retire que ce que l'amont
a lui-même retiré. Le plan les compte, pour que ce soit dit.

── Les fichiers générés ne se fusionnent pas, ils se régénèrent ────────────

Le catalogue des agents, la table des pistes, les pages de la doc : chacun se
calcule depuis ce que le brain contient. Le tien compte tes agents et tes
pistes, celui de l'amont les siens : fusionner ces deux calculs n'a pas de sens,
et c'est là que les mises à jour butaient (mesuré le 3/10 : un fork qui a
régénéré son catalogue entre en conflit dès que l'amont régénère le sien).
Sur un tel fichier, l'amont gagne, puis tout est recalculé chez toi — tes
agents et tes pistes y reviennent. Un fichier dont seul un BLOC est généré
(la table de `learning/README.md`) garde ce que tu as écrit autour.

Ce qu'il remplace, il le garde : la version d'avant de chaque fichier généré
qui a changé est posée dans `workspace/scratch/brain-maj-<version>/` (git
l'ignore), avec les commandes pour comparer — à relire avec ton brain.

── Ce qu'il refuse ─────────────────────────────────────────────────────────

Un arbre qui n'est pas propre (committe d'abord). Un conflit sur un fichier
écrit à la main — un agent que vous avez modifié tous les deux, un fichier que
l'amont retire et que tu as modifié : le plan le nomme, et rien n'est fusionné.
Ces choix-là sont les tiens : `git merge <version>`, puis relance `brain maj`
pour la suite. Sans amont déclaré (le brain d'origine, ou un fork qui ne l'a
pas encore fait), il n'a rien à recevoir.

Sortie 0 : à jour, ou plan sans obstacle, ou version reçue. 1 : un obstacle,
rien n'a bougé. 2 : rien à recevoir d'ici.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
VERSION = re.compile(r'^version:\s*"?(\d+)\.(\d+)\.(\d+)"?', re.M)
DEBUT, FIN = "<!-- genere:tracks -->", "<!-- /genere:tracks -->"

# Les fichiers que le brain CALCULE. `entier` : tout le fichier est un calcul,
# l'amont gagne puis on recalcule. `bloc` : seul ce qui est entre les marqueurs
# l'est ; le reste se fusionne comme du texte. `amont` : le calcul décrit la
# version reçue (le lock du noyau livré), il ne se refait pas chez toi.
GENERES = (
    ("agents/CATALOG.yml", "entier"),
    ("skills/brain/SKILL.md", "entier"),
    ("docs/*.md", "entier"),
    ("learning/README.md", "bloc"),
    ("kernel.lock", "amont"),
)


def nature(chemin: str) -> str | None:
    for motif, n in GENERES:
        if fnmatch(chemin, motif) and "/src/" not in chemin:
            return n
    return None


def git(brain: Path, *args, ok=(0,), entree: str | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(brain), *args], capture_output=True, text=True,
                       input=entree, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode not in ok:
        raise RuntimeError(f"git {' '.join(args)} : {(r.stderr or r.stdout).strip()[:300]}")
    return r


def version_de(texte: str):
    m = VERSION.search(texte)
    return tuple(int(x) for x in m.groups()) if m else None


def texte_v(v) -> str:
    return ".".join(map(str, v)) if v else "?"


def blanchir(texte: str) -> str:
    """Le bloc généré vidé : trois versions vidées pareil ne se contredisent plus."""
    if DEBUT not in texte or FIN not in texte:
        return texte
    return texte[:texte.index(DEBUT) + len(DEBUT)] + "\n" + texte[texte.index(FIN):]


def fusion_par_bloc(brain: Path, base: str, cible: str, chemin: str) -> str | None:
    """Fusionne le texte autour du bloc, bloc vidé des trois côtés. None : un vrai conflit."""
    import tempfile

    def contenu(rev):
        r = git(brain, "show", f"{rev}:{chemin}", ok=(0, 128))
        return r.stdout if r.returncode == 0 else ""

    with tempfile.TemporaryDirectory(prefix="brain-maj-") as tmp:
        f = {}
        for nom, rev in (("nous", "HEAD"), ("base", base), ("eux", cible)):
            f[nom] = Path(tmp) / nom
            f[nom].write_text(blanchir(contenu(rev)), encoding="utf-8")
        r = subprocess.run(["git", "merge-file", "-p", str(f["nous"]), str(f["base"]), str(f["eux"])],
                           capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def plan(brain: Path, remote: str, demande: str | None, reseau: bool) -> dict:
    if git(brain, "remote", "get-url", remote, ok=(0, 2, 128)).returncode != 0:
        return {"etat": "sans amont"}
    if reseau:
        git(brain, "fetch", "--quiet", "--tags", remote)
    tags = [t for t in git(brain, "tag", "-l", "v*").stdout.split() if TAG.match(t)]
    if demande:
        if demande not in tags:
            return {"etat": "obstacle", "obstacles": [f"{demande} : aucun tag de ce nom chez l'amont"]}
        cible = demande
    elif tags:
        cible = max(tags, key=lambda t: tuple(int(x) for x in TAG.match(t).groups()))
    else:
        return {"etat": "sans version"}
    locale = version_de((brain / "brain-compose.yml").read_text(encoding="utf-8")
                        if (brain / "brain-compose.yml").is_file() else "")
    p = {"cible": cible, "locale": texte_v(locale), "obstacles": [], "generes": [], "retires": [],
         "a_toi": 0, "modifies": 0, "change": 0}
    if git(brain, "merge-base", "--is-ancestor", cible, "HEAD", ok=(0, 1)).returncode == 0:
        declaree = kernel_version_declaree(brain)
        if declaree and declaree != cible.lstrip("v"):
            return {**p, "etat": "suite à faire", "declaree": declaree}
        return {**p, "etat": "à jour"}
    sale = [l for l in git(brain, "status", "--porcelain", "--untracked-files=no").stdout.splitlines() if l]
    if sale:
        p["obstacles"].append(f"l'arbre n'est pas propre ({len(sale)} fichier(s) modifié(s)) — committe d'abord")
    base = git(brain, "merge-base", "HEAD", cible).stdout.strip()
    p["base"] = base
    p["change"] = len(git(brain, "diff", "--name-only", base, cible).stdout.split())
    p["a_toi"] = len(git(brain, "diff", "--name-only", "--diff-filter=A", base, "HEAD").stdout.split())
    p["modifies"] = len(git(brain, "diff", "--name-only", "--diff-filter=M", base, "HEAD").stdout.split())
    p["retires"] = git(brain, "diff", "--name-only", "--diff-filter=D", base, cible).stdout.split()
    r = git(brain, "merge-tree", "--write-tree", "--name-only", "--no-messages", "HEAD", cible, ok=(0, 1))
    conflits = r.stdout.split("\n")[1:] if r.returncode == 1 else []
    for c in (c for c in conflits if c):
        n = nature(c)
        if n == "bloc" and fusion_par_bloc(brain, base, cible, c) is None:
            p["obstacles"].append(f"{c} — un conflit hors de la table générée")
        elif n:
            p["generes"].append(c)
        else:
            p["obstacles"].append(f"{c} — modifié des deux côtés (ou retiré par l'amont, modifié chez toi)")
    return {**p, "etat": "obstacle" if p["obstacles"] else "prêt"}


def regenerer(brain: Path, dire) -> list[str]:
    """Recalcule chez toi ce que le brain calcule. Rend les chemins touchés."""
    py, env = sys.executable, {**os.environ, "PYTHONPATH": str(brain / "brain-engine")}
    taches = (
        ("agents/CATALOG.yml", [py, "brain-engine/doctor/agent_registry.py", "--brain", ".",
                                "--emit", "agents/CATALOG.yml"]),
        ("learning/README.md", [py, "brain-engine/doctor/zone_learning.py", "--brain", ".", "--ecrire"]),
        ("docs/ skills/brain/SKILL.md", [py, "scripts/docs-generer.py", "--ecrire"]),
    )
    touches = []
    for cible, cmd in taches:
        if not (brain / cmd[1]).is_file():
            continue
        if cible == "learning/README.md":
            idx = brain / cible
            if not idx.is_file() or DEBUT not in idx.read_text(encoding="utf-8"):
                continue
        r = subprocess.run(cmd, cwd=brain, env=env, capture_output=True, text=True, timeout=300)
        # zone_learning sort en 1 quand la zone a un défaut : la table est écrite quand même.
        if r.returncode not in (0, 1):
            dire(f"  ⚠️ {cible} : la régénération a échoué — gardé tel que l'amont le livre")
            continue
        touches += cible.split()
    return touches


def kernel_version_declaree(brain: Path) -> str | None:
    local = brain / "brain-compose.local.yml"
    if not local.is_file():
        return None
    m = re.search(r'^kernel_version:\s*"?([0-9.]+)"?', local.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def declarer(brain: Path, cible: str, dire) -> None:
    local = brain / "brain-compose.local.yml"
    if not local.is_file():
        dire("  ⓘ pas de brain-compose.local.yml : kernel_version à déclarer à la main")
        return
    texte = local.read_text(encoding="utf-8")
    neuf, n = re.subn(r'^kernel_version:.*$', f'kernel_version: "{cible.lstrip("v")}"', texte, flags=re.M)
    if n:
        local.write_text(neuf, encoding="utf-8")
        dire(f"  ✅ kernel_version : {cible.lstrip('v')} (brain-compose.local.yml)")
    else:
        dire("  ⓘ kernel_version absent de brain-compose.local.yml : à déclarer à la main")


def garder_l_avant(brain: Path, avant: str, cible: str, dire) -> None:
    """La version d'avant de chaque fichier généré qui a changé, posée à côté pour comparer."""
    changes = [c for c in git(brain, "diff", "--name-only", avant, "HEAD").stdout.split() if nature(c)]
    gardes = []
    dossier = brain / "workspace" / "scratch" / f"brain-maj-{cible}"
    for c in changes:
        r = git(brain, "show", f"{avant}:{c}", ok=(0, 128))
        if r.returncode != 0:
            continue
        f = dossier / f"{c}.avant"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(r.stdout, encoding="utf-8")
        gardes.append(c)
    if not gardes:
        return
    lignes = [f"# brain maj {cible} — les fichiers générés, tels qu'ils étaient avant", "",
              "Ils ont été recalculés plutôt que fusionnés. Pour voir ce qui a changé :", "", "```bash"]
    lignes += [f"diff -u workspace/scratch/brain-maj-{cible}/{c}.avant {c}" for c in gardes]
    lignes += [f"git diff {avant[:12]} HEAD -- {' '.join(gardes)}   # le même, par git", "```", "",
               "Ce dossier est ignoré par git : efface-le quand tu as relu.", ""]
    (dossier / "README.md").write_text("\n".join(lignes), encoding="utf-8")
    dire(f"  📄 l'avant de {len(gardes)} fichier(s) généré(s) : workspace/scratch/brain-maj-{cible}/ (README : comment comparer)")


def appliquer(brain: Path, p: dict, sans_unites: bool, dire) -> int:
    cible, base = p["cible"], p["base"]
    avant = git(brain, "rev-parse", "HEAD").stdout.strip()
    git(brain, "merge", "--no-ff", "--no-commit", cible, ok=(0, 1))
    try:
        for c in p["generes"]:
            if nature(c) == "bloc":
                (brain / c).write_text(fusion_par_bloc(brain, base, cible, c), encoding="utf-8")
            else:
                r = git(brain, "show", f"{cible}:{c}", ok=(0, 128))
                if r.returncode == 0:
                    (brain / c).write_text(r.stdout, encoding="utf-8")
                else:
                    git(brain, "rm", "--quiet", "--", c)
                    continue
            git(brain, "add", "--", c)
        for t in regenerer(brain, dire):
            git(brain, "add", "--", t)
        reste = git(brain, "diff", "--name-only", "--diff-filter=U").stdout.split()
        if reste:
            raise RuntimeError(f"conflit restant : {', '.join(reste)}")
        git(brain, "commit", "--quiet", "--no-verify", "-m", f"brain maj : {cible}")
    except Exception as e:                                       # noqa: BLE001
        git(brain, "merge", "--abort", ok=(0, 128))
        dire(f"  ❌ {e} — fusion annulée, rien n'a bougé")
        return 1
    dire(f"  ✅ {cible} reçue" + (f" — {len(p['generes'])} conflit(s) sur des fichiers générés, résolus en "
                               "recalculant" if p["generes"] else ""))
    garder_l_avant(brain, avant, cible, dire)
    return la_suite(brain, cible, sans_unites, dire)


def la_suite(brain: Path, cible: str, sans_unites: bool, dire) -> int:
    """Ce qui suit la fusion : déclarer la version, réinstaller les unités, dire le reste."""
    declarer(brain, cible, dire)
    unite = subprocess.run(["systemctl", "--user", "cat", "brain-engine.service"],
                           capture_output=True, text=True) if not sans_unites else None
    # L'unité installée doit être celle de CE brain : sur une machine qui porte
    # plusieurs brains (un fork d'essai à côté du vrai), réinstaller depuis l'un
    # remplacerait les unités de l'autre.
    if unite is not None and unite.returncode == 0 and str(brain.resolve()) not in unite.stdout:
        dire("  ⓘ les unités installées sont celles d'un autre brain : pas touchées")
    elif unite is not None and unite.returncode == 0:
        r = subprocess.run(["bash", "scripts/brain-engine.sh", "install", "systemd"], cwd=brain,
                           capture_output=True, text=True, timeout=600)
        dire("  ✅ unités réinstallées et relancées" if r.returncode == 0
             else "  ⚠️ install systemd a échoué — relance : bash scripts/brain-engine.sh install systemd")
    else:
        dire("  ⓘ unités non réinstallées : bash scripts/brain-engine.sh install systemd (ou stop/start)")
    dire("\nEnsuite, à la main :")
    dire("  bash scripts/schema-retraits.sh      # à blanc : ce que la version retire de ta base")
    dire("  brain doctor")
    dire(f"  les notes de la {cible} : ce qui se fait hors du dépôt")
    return 0


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("version", nargs="?", help="le tag à recevoir (défaut : le plus récent)")
    a.add_argument("--appliquer", action="store_true")
    a.add_argument("--sans-unites", action="store_true")
    a.add_argument("--sans-reseau", action="store_true", help="ne pas relire les tags de l'amont")
    o = a.parse_args()
    brain = Path(os.environ.get("BRAIN_ROOT") or Path(__file__).resolve().parent.parent)
    remote = os.environ.get("BRAIN_MAJ_REMOTE") or "upstream"
    try:
        p = plan(brain, remote, o.version, not o.sans_reseau)
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1
    if p["etat"] == "sans amont":
        print(f"Pas d'amont « {remote} » : ce brain est la source, ou l'amont n'est pas déclaré "
              "(docs/mettre-a-jour.md, « Une seule fois »).")
        return 2
    if p["etat"] == "sans version":
        print("L'amont ne porte aucune version (aucun tag vX.Y.Z).")
        return 2
    print(f"\nBRAIN MAJ — ta version : {p.get('locale', '?')} · l'amont : {p.get('cible', '?')}\n")
    if p["etat"] == "à jour":
        print(f"  ✅ {p['cible']} est déjà dans ton historique — rien à recevoir")
        return 0
    if p["etat"] == "suite à faire":
        print(f"  ⓘ {p['cible']} est fusionnée, mais kernel_version dit encore {p['declaree']} : la suite n'est pas faite")
        if not o.appliquer:
            print("  `brain maj --appliquer` : régénérer, déclarer, réinstaller les unités")
            return 0
        sale = git(brain, "status", "--porcelain", "--untracked-files=no").stdout.strip()
        if sale:
            print("  ❌ l'arbre n'est pas propre — committe d'abord")
            return 1
        touches = regenerer(brain, print)
        if touches:
            git(brain, "add", "--", *touches)
            if git(brain, "diff", "--cached", "--quiet", ok=(0, 1)).returncode == 1:
                git(brain, "commit", "--quiet", "--no-verify", "-m", f"brain maj : {p['cible']}, générés recalculés")
                print("  ✅ les fichiers générés recalculés")
        return la_suite(brain, p["cible"], o.sans_unites, print)
    if "base" in p:
        print(f"  ce que l'amont change      {p['change']} fichier(s)")
        print(f"  ce qui est à toi seul      {p['a_toi']} fichier(s) que l'amont n'a pas — intouchés")
        print("                             (et tout ce que git ignore : pistes, profil, todos, vie/…)")
        print(f"  ce que tu as modifié       {p['modifies']} fichier(s) du gabarit — fusionnés, pas écrasés")
        if p["retires"]:
            print(f"  ce que l'amont retire      {len(p['retires'])} : {', '.join(p['retires'][:6])}"
                  + (" …" if len(p["retires"]) > 6 else ""))
        if p["generes"]:
            print(f"  générés, à recalculer      {', '.join(p['generes'])}")
        print(f"  l'avant des générés        gardé dans workspace/scratch/brain-maj-{p['cible']}/")
    for o_ in p.get("obstacles", []):
        print(f"  ❌ {o_}")
    if p["etat"] == "obstacle":
        print("\nRien n'est fusionné. Ces choix sont les tiens : `git merge "
              f"{p.get('cible', '<version>')}`, résous, committe — puis `brain maj` pour la suite.")
        return 1
    if not o.appliquer:
        print("\n  ✅ rien ne s'y oppose — `brain maj --appliquer` pour la recevoir")
        return 0
    print()
    return appliquer(brain, p, o.sans_unites, print)


if __name__ == "__main__":
    sys.exit(main())
