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

── Le noyau et la vue ──────────────────────────────────────────────────────

Un brain dont `agents/` est une VUE (`noyau/agents/`, le noyau livré ;
`instance/agents/`, tes surcharges) : le noyau est levé de sa lecture seule le
temps de la fusion, la vue reconstruite après — le catalogue se calcule en elle,
il ne se commite plus.

Un brain encore à plat qui reçoit une version à vue : AVANT de fusionner, tes
agents passent dans `instance/agents/` — un agent que tu as modifié y emporte ta
version, `agents/` revient à celle que tu avais reçue ; un agent à toi y part tel
quel. Sans ça, git suivrait le renommage et mêlerait ta version au noyau. Après :
le noyau porte la version de l'amont, `instance/` la tienne, et la vue montre la
tienne — les deux restent. Un agent que tu avais retiré revient : le noyau ne se
retire pas, le plan le dit.

── Ce qu'il refuse ─────────────────────────────────────────────────────────

Un arbre qui n'est pas propre (committe d'abord). Un conflit sur un fichier
écrit à la main — un agent que vous avez modifié tous les deux, un fichier que
l'amont retire et que tu as modifié : le plan le nomme, et rien n'est fusionné.
Ces choix-là sont les tiens : `git merge <version>`, puis relance `brain maj`
pour la suite. Sans amont déclaré (le brain d'origine, ou un fork qui ne l'a
pas encore fait), il n'a rien à recevoir.

── Le relais ───────────────────────────────────────────────────────────────

Le `brain maj` qui tourne est celui que tu as — celui de ta version. Ce que la
version reçue apprend à la mise à jour (relire une surcouche de plus, s'arrêter
sur un nouveau risque) ne servirait qu'à la suivante. Il passe donc la main :
si le `scripts/maj.py` de la version reçue diffère du sien, c'est LUI qui
tourne, extrait de la version, avec les mêmes arguments, sur le même brain.
Une seule fois (`BRAIN_MAJ_RELAIS`) : le relais ne se relaie pas.

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


def vue(brain: Path, *args: str) -> bool:
    """`brain vue` sur CE brain — sa propre version du script."""
    script = brain / "scripts" / "vue.py"
    if not script.is_file():
        return False
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True,
                       timeout=600, env={**os.environ, "BRAIN_ROOT": str(brain)})
    return r.returncode == 0


def migration_vers_la_vue(brain: Path, base: str, cible: str) -> dict | None:
    """Ce brain est à plat et la version reçue livre `noyau/agents/` : ses agents à lui."""
    if (brain / "noyau" / "agents").is_dir():
        return None
    if git(brain, "cat-file", "-e", f"{cible}:noyau/agents", ok=(0, 1, 128)).returncode != 0:
        return None
    m = {"modifies": [], "ajoutes": [], "retires": []}
    for ligne in git(brain, "diff", "--name-status", "--no-renames", base, "HEAD", "--", "agents/").stdout.splitlines():
        etat, chemin = ligne.split("\t", 1)
        if chemin == "agents/CATALOG.yml":
            continue                                 # calculé, il ne se garde pas
        {"M": m["modifies"], "A": m["ajoutes"], "D": m["retires"]}.get(etat[0], []).append(chemin)
    return m


def chemin_agent(brain: Path, rev: str, nom: str) -> str | None:
    """Où vit l'agent `nom` dans `rev` : le noyau d'une vue, ou `agents/` d'un brain à plat."""
    for c in (f"noyau/agents/{nom}.md", f"agents/{nom}.md"):
        if git(brain, "cat-file", "-e", f"{rev}:{c}", ok=(0, 1, 128)).returncode == 0:
            return c
    return None


def surcharges_a_relire(brain: Path, base: str, cible: str, migration: dict | None) -> list[dict]:
    """Tes agents REMPLACÉS dont le noyau change dans la version reçue.

    Un complément suit tout seul : la vue l'assemble avec le nouvel agent. Une
    surcharge, non — elle remplace l'agent entier, et ce que le noyau améliore
    ne t'arrive pas. Rien ne l'écrase ; le plan la nomme, avec de quoi comparer.
    Le contenu se compare, pas le chemin : un brain à plat qui passe à la vue
    voit chaque agent déménager sans changer."""
    inst = brain / "instance" / "agents"
    miens = {f.stem for f in inst.glob("*.md")
             if f.name != "README.md" and not f.name.endswith(".complement.md")} if inst.is_dir() else set()
    if migration is not None:
        miens |= {Path(c).stem for c in migration["modifies"]}
    sortie = []
    for nom in sorted(miens):
        avant, apres = chemin_agent(brain, base, nom), chemin_agent(brain, cible, nom)
        if not avant or not apres:
            continue
        a = git(brain, "rev-parse", f"{base}:{avant}").stdout.strip()
        b = git(brain, "rev-parse", f"{cible}:{apres}").stdout.strip()
        if a != b:
            sortie.append({"nom": nom, "diff": f"git diff {base[:12]}:{avant} {cible}:{apres}"})
    return sortie


def donnees_suivies(brain: Path, base: str, cible: str) -> list[str]:
    """Ce que ton dépôt suit et que la version reçue range en satellites.

    Un `.gitignore` ne retire rien de ce qui est déjà suivi : un fork qui a
    commité ses projets les garde dans son dépôt programme. Rien ne se perd —
    le plan le dit, pour qu'il les passe en satellite quand il veut."""
    r = git(brain, "show", f"{cible}:.gitignore", ok=(0, 128))
    if r.returncode != 0:
        return []
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".gitignore", delete=False) as f:
        f.write(r.stdout)
    try:
        ignores = git(brain, "ls-files", "--cached", "--ignored", f"--exclude-from={f.name}").stdout.split()
    finally:
        os.unlink(f.name)
    # Ce que TU as ajouté, pas ce que le gabarit livrait : un fichier de l'amont
    # que la version retire (une spec d'une couche abandonnée) n'est pas ta donnée —
    # la fusion le retire, le plan le dit ailleurs (5/10, la preuve sur un fork 2.7.0).
    a_toi = set(git(brain, "diff", "--name-only", "--diff-filter=A", base, "HEAD").stdout.split())
    return [c for c in ignores if c in a_toi]


def ecrasables(brain: Path, base: str, cible: str) -> list[str]:
    """Ce que la version AJOUTE et qui existe déjà chez toi, hors de git.

    Ce dont git ne te protège pas : un fichier IGNORÉ — ta donnée, dans un
    satellite — est écrasé sans un mot quand une fusion apporte un fichier suivi
    au même chemin (éprouvé le 5/10 : `handoffs/LATEST.md` du fork remplacé par
    le modèle de l'amont). Un fichier non suivi, lui, fait échouer la fusion —
    mais au milieu de l'application. Les deux se disent dans le plan, avant."""
    ajoutes = git(brain, "diff", "--name-only", "--diff-filter=A", base, cible).stdout.split()
    suivis = set(git(brain, "ls-files").stdout.split())
    return [c for c in ajoutes if c not in suivis and (brain / c).exists()]


def ecrire_les_surcharges(brain: Path, cible: str, surcharges: list[dict], dire) -> None:
    """La liste à relire, posée avec l'avant des générés — c'est ton brain qui la lit."""
    if not surcharges:
        return
    dossier = brain / "workspace" / "scratch" / f"brain-maj-{cible}"
    dossier.mkdir(parents=True, exist_ok=True)
    lignes = [f"# brain maj {cible} — tes surcharges, et ce que le noyau a changé dessous", "",
              "Chacun de ces agents est REMPLACÉ par le tien (`instance/agents/<nom>.md`) : ce que le",
              "noyau y améliore ne t'arrive pas. Rien n'a été écrasé. Pour chacun : lire le diff du",
              "noyau, reprendre dans ta surcharge ce que tu veux, ou la réduire à un complément",
              "(`<nom>.complement.md`), qui suit le noyau tout seul.", "", "```bash"]
    lignes += [f"{s['diff']}   # {s['nom']}" for s in surcharges]
    lignes += ["```", "", "Ce dossier est ignoré par git : efface-le quand tu as relu.", ""]
    (dossier / "surcharges.md").write_text("\n".join(lignes), encoding="utf-8")
    dire(f"  📄 {len(surcharges)} surcharge(s) à relire : workspace/scratch/brain-maj-{cible}/surcharges.md")


def preparer_la_migration(brain: Path, base: str, m: dict, dire) -> None:
    """Tes agents passent dans `instance/agents/` — un commit, avant la fusion."""
    for chemin in m["modifies"] + m["ajoutes"]:
        rel = chemin[len("agents/"):]
        dest = brain / "instance" / "agents" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if chemin in m["ajoutes"]:
            git(brain, "mv", chemin, str(dest.relative_to(brain)))
        else:
            dest.write_bytes((brain / chemin).read_bytes())
            git(brain, "add", "--", str(dest.relative_to(brain)))
            git(brain, "checkout", base, "--", chemin)       # la version reçue : l'amont la renomme proprement
    if git(brain, "cat-file", "-e", f"{base}:agents/CATALOG.yml", ok=(0, 128)).returncode == 0:
        git(brain, "checkout", base, "--", "agents/CATALOG.yml")
    git(brain, "commit", "--quiet", "--no-verify", "--allow-empty", "-m",
        "brain maj : tes agents passent dans instance/agents/ (la vue arrive)")
    dire(f"  ✅ {len(m['modifies'])} agent(s) modifié(s) et {len(m['ajoutes'])} à toi rangés dans instance/agents/")


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
    p["migration"] = migration_vers_la_vue(brain, base, cible)
    p["surcharges"] = surcharges_a_relire(brain, base, cible, p["migration"])
    p["donnees_suivies"] = donnees_suivies(brain, base, cible)
    for c in ecrasables(brain, base, cible):
        p["obstacles"].append(f"{c} — la version livre un fichier à ce chemin, où tu as le tien "
                              "(hors de git) : il serait écrasé. Déplace-le, puis relance")
    r = git(brain, "merge-tree", "--write-tree", "--name-only", "--no-messages", "HEAD", cible, ok=(0, 1))
    conflits = r.stdout.split("\n")[1:] if r.returncode == 1 else []
    if p["migration"] is not None:
        # Tes agents partent dans `instance/` avant la fusion : leurs conflits n'existeront
        # pas — ni sous `agents/`, ni sous `noyau/agents/`, où git, qui suit le
        # déménagement du dossier, rangerait d'office un agent que tu as ajouté.
        conflits = [c for c in conflits if not c.startswith(("agents/", "noyau/agents/"))]
        p["retires"] = [r for r in p["retires"] if not r.startswith("agents/")]
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
        if cible == "agents/CATALOG.yml" and (brain / "noyau" / "agents").is_dir():
            continue                       # une vue : `brain vue` le calcule, il ne se commite pas
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
    noyau = brain / "noyau" / "agents"
    if noyau.is_dir():
        vue(brain, "--deverrouiller")                       # git doit pouvoir écrire le noyau
    try:
        if p.get("migration") is not None:
            preparer_la_migration(brain, base, p["migration"], dire)
        git(brain, "merge", "--no-ff", "--no-commit", cible, ok=(0, 1))
        if noyau.is_dir():
            vue(brain, "--deverrouiller")
            vue(brain, "--construire")          # AVANT de recalculer : la doc compte les agents de la vue
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
        # `merge --abort` ne défait que la fusion : un fichier régénéré APRÈS elle
        # restait modifié, et le message disait « rien n'a bougé ». L'arbre était
        # propre au départ (le plan l'exige) : revenir à `avant` ne défait que ce
        # que cet outil a écrit.
        git(brain, "merge", "--abort", ok=(0, 128))
        git(brain, "reset", "--quiet", "--hard", avant)
        if noyau.is_dir():
            vue(brain, "--construire")                     # le noyau rendu à sa posture
        dire(f"  ❌ {e} — fusion annulée, l'arbre remis tel qu'il était")
        return 1
    if noyau.is_dir():
        dire("  ✅ la vue reconstruite" if vue(brain, "--construire")
             else "  ⚠️ la vue ne s'est pas reconstruite — bash scripts/brain vue (un fichier réel dans agents/ ?)")
    dire(f"  ✅ {cible} reçue" + (f" — {len(p['generes'])} conflit(s) sur des fichiers générés, résolus en "
                               "recalculant" if p["generes"] else ""))
    garder_l_avant(brain, avant, cible, dire)
    ecrire_les_surcharges(brain, cible, p.get("surcharges") or [], dire)
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


def relayer(brain: Path, cible: str, argv: list[str]) -> int | None:
    """Le `maj` de la version reçue prend la main, s'il diffère de celui-ci.

    None : pas de relais (déjà relayé, pas de `maj.py` dans la version, ou le même)."""
    if os.environ.get("BRAIN_MAJ_RELAIS"):
        return None
    r = git(brain, "show", f"{cible}:scripts/maj.py", ok=(0, 128))
    if r.returncode != 0 or r.stdout == Path(__file__).read_text(encoding="utf-8"):
        return None
    import tempfile
    with tempfile.TemporaryDirectory(prefix="brain-maj-relais-") as tmp:
        script = Path(tmp) / "maj.py"
        script.write_text(r.stdout, encoding="utf-8")
        print(f"↪ relais : le brain maj de {cible} prend la main — il sait ce que la version apporte")
        env = {**os.environ, "BRAIN_MAJ_RELAIS": cible, "BRAIN_ROOT": str(brain)}
        args = argv if "--sans-reseau" in argv else [*argv, "--sans-reseau"]   # les tags sont déjà lus
        return subprocess.run([sys.executable, str(script), *args], env=env).returncode


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
    if p.get("cible") and p["etat"] not in ("à jour", "suite à faire"):
        code = relayer(brain, p["cible"], sys.argv[1:])
        if code is not None:
            return code
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
        if p.get("migration") is not None:
            m = p["migration"]
            print(f"  agents/ devient une vue    {len(m['modifies'])} modifié(s) et {len(m['ajoutes'])} à toi"
                  " → instance/agents/ ; le noyau reçoit l'amont")
            if m["retires"]:
                print(f"  ⓘ tu avais retiré          {', '.join(m['retires'])} — ils reviennent : le noyau ne se retire pas")
        if p.get("surcharges"):
            noms = ", ".join(s["nom"] for s in p["surcharges"])
            print(f"  ⓘ surcharges à relire      {noms} — le noyau les change ; la tienne reste, "
                  f"la liste et les diffs iront dans workspace/scratch/brain-maj-{p['cible']}/surcharges.md")
        if p.get("donnees_suivies"):
            d = p["donnees_suivies"]
            print(f"  ⓘ données encore suivies   {len(d)} fichier(s) que la version range en satellites "
                  f"({', '.join(sorted({c.split('/')[0] + '/' for c in d})[:5])}) — git ne les retire pas ; "
                  "à versionner à part : docs/satellites.md")
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
