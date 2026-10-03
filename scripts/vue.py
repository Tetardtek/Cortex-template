#!/usr/bin/env python3
# brain-distribuable: oui
"""brain vue — `agents/` comme une vue du noyau livré et de la surcharge de l'instance.

    brain vue                    l'état de la vue : rien ne bouge
    brain vue --construire       poser les liens, calculer le catalogue, appliquer la posture

    noyau/agents/X.md        le noyau livré — reçu par `brain maj`, jamais modifié chez un fork
    instance/agents/X.md     la surcharge de l'instance — à elle
    agents/X.md              un lien vers instance/… s'il existe, sinon vers noyau/…

Tous les lecteurs d'un agent — la session qui suit un chemin écrit, le moteur, le MCP,
l'indexation — lisent `agents/X.md` : ils voient la bonne version par construction,
sans qu'un seul chemin change. La version publiée et la surcharge restent là toutes les
deux.

── Ce qu'il ne fait jamais ─────────────────────────────────────────────────

Écraser un fichier RÉEL de `agents/`. Un fichier qui n'est pas un lien est peut-être
le travail de quelqu'un (un `sed -i` ou un `mv` remplace un lien par un fichier) : il
est signalé, jamais touché. Il ne retire que des liens dont la cible a disparu.

Un fichier réel que ni le noyau ni l'instance ne fournit (un agent écrit directement
dans `agents/`) est signalé lui aussi : `agents/` est ignorée par git, personne d'autre
ne le verrait, et il serait lu comme un agent sans jamais être commité.

── Ce qu'il calcule ────────────────────────────────────────────────────────

`agents/CATALOG.yml` : le catalogue de ce que l'instance voit vraiment — le noyau, ses
surcharges, ses agents à elle. Un calcul, écrit dans la vue ; celui que livrerait le
noyau décrirait le noyau de l'amont, pas ce qui est lu ici.

── La posture décide du droit d'écrire le noyau ────────────────────────────

Une instance dont la posture refuse le kernel (`kernel_write: false`) a son `noyau/` en
lecture seule ; les autres le gardent modifiable. git ne garde pas ce droit : il est
reposé à chaque construction. Une garde contre l'accident, pas contre le propriétaire
de la machine.

Sans `noyau/`, il s'abstient : rien à construire. Sortie 0 : la vue est juste (ou
construite). 1 : elle est à construire, ou un fichier réel bloque une entrée ou
n'est fourni par rien.
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

CALCULES = {Path("CATALOG.yml")}        # écrits dans la vue, jamais liés


def racines(brain: Path) -> tuple[Path, Path, Path]:
    return brain / "noyau" / "agents", brain / "instance" / "agents", brain / "agents"


def voulu(brain: Path) -> dict[Path, Path]:
    """Chaque entrée de la vue → sa cible. L'instance passe après le noyau : elle gagne."""
    noyau, instance, _ = racines(brain)
    v: dict[Path, Path] = {}
    for racine in (noyau, instance):
        if racine.is_dir():
            for f in sorted(racine.rglob("*")):
                rel = f.relative_to(racine)
                # Un fichier caché (le `.gitkeep` d'`instance/agents/`) n'est pas un agent :
                # relié, il restait en lien mort après un retour arrière (3/10).
                if f.is_file() and rel not in CALCULES and not f.name.startswith("."):
                    v[rel] = f
    return v


def etat(brain: Path) -> dict:
    _, _, vue = racines(brain)
    v = voulu(brain)
    e = {"a_creer": [], "a_corriger": [], "reels": [], "etrangers": [], "orphelins": [], "justes": 0}
    for rel, cible in v.items():
        lien = vue / rel
        attendu = os.path.relpath(cible, lien.parent)
        if lien.is_symlink():
            if os.readlink(lien) == attendu:
                e["justes"] += 1
            else:
                e["a_corriger"].append(rel)
        elif lien.exists():
            e["reels"].append(rel)
        else:
            e["a_creer"].append(rel)
    if vue.is_dir():
        for l in sorted(vue.rglob("*")):
            rel = l.relative_to(vue)
            if l.is_symlink() and rel not in v:
                e["orphelins"].append(rel)
            elif l.is_file() and not l.is_symlink() and rel not in v and rel not in CALCULES:
                e["etrangers"].append(rel)
    return e


def construire(brain: Path) -> dict:
    _, _, vue = racines(brain)
    v = voulu(brain)
    e = etat(brain)
    for rel in e["a_creer"] + e["a_corriger"]:
        lien = vue / rel
        lien.parent.mkdir(parents=True, exist_ok=True)
        if lien.is_symlink():
            lien.unlink()
        lien.symlink_to(os.path.relpath(v[rel], lien.parent))
    for rel in e["orphelins"]:
        lien = vue / rel
        if lien.is_symlink():                      # jamais un fichier réel
            lien.unlink()
    return e


def generateur(brain: Path) -> Path | None:
    """Le registre des agents : livré avec le doctor du gabarit, sinon celui de Myéline."""
    livre = brain / "brain-engine" / "doctor" / "agent_registry.py"
    if livre.is_file():
        return livre
    myeline = os.environ.get("MYELINE_ROOT")
    if myeline and (Path(myeline) / "tools" / "agent_registry.py").is_file():
        return Path(myeline) / "tools" / "agent_registry.py"
    return None


def calculer_catalogue(brain: Path) -> str:
    _, _, vue = racines(brain)
    g = generateur(brain)
    if g is None:
        return "ⓘ catalogue non calculé : aucun registre d'agents (brain-engine/doctor/ ni MYELINE_ROOT)"
    cible = vue / "CATALOG.yml"
    if cible.is_symlink():
        cible.unlink()                             # un ancien lien vers le noyau : jamais écrire à travers
    r = subprocess.run([sys.executable, str(g), "--brain", str(brain), "--emit", str(cible)],
                       capture_output=True, text=True, timeout=300, cwd=brain,
                       env={**os.environ, "PYTHONPATH": str(brain / "brain-engine")})
    return ("✅ catalogue calculé dans la vue" if r.returncode == 0 and cible.is_file()
            else f"⚠️ catalogue non calculé : {(r.stderr or r.stdout).strip()[-200:]}")


def ecrit_le_kernel(brain: Path) -> bool:
    """La posture de l'instance active — la lecture de `serve.py`, la même source.

    Illisible : si l'instance DÉCLARE une posture autre que `master`, on verrouille et
    on le dit — se rabattre sur « modifiable » ouvrait le noyau d'un satellite en
    silence. Rien de déclaré (un fork neuf) : modifiable, comme avant."""
    sys.path.insert(0, str(brain / "brain-engine"))
    # Pas de `__pycache__` : la synchro construit la vue d'un RENDU, et le bytecode de
    # `serve.py` partait avec le gabarit (répétition générale du 3/10).
    sys.dont_write_bytecode = True
    try:
        import serve
        return serve.ecrit_le_kernel(brain, serve.posture_de(brain))
    except Exception as e:                                     # noqa: BLE001
        import re
        local = brain / "brain-compose.local.yml"
        texte = local.read_text(encoding="utf-8", errors="replace") if local.is_file() else ""
        declaree = re.search(r"^\s*posture:\s*['\"]?([\w-]+)", texte, re.M)
        if declaree and declaree.group(1) != "master":
            print(f"  ⚠️ la posture ne se lit pas ({e.__class__.__name__}) — « {declaree.group(1)} » "
                  "déclarée : le noyau est verrouillé par prudence", file=sys.stderr)
            return False
        return True
    finally:
        sys.path.pop(0)


def droit_d_ecrire(brain: Path, ecrire: bool) -> None:
    """Le noyau en lecture seule, ou rendu à l'écriture — fichiers ET dossiers, `noyau/`
    compris : sans lui, un `mv noyau/agents …` passait (3/10)."""
    noyau, _, _ = racines(brain)
    chemins = [noyau.parent, noyau, *noyau.rglob("*")] if noyau.is_dir() else []
    for p in sorted(chemins, key=lambda p: len(p.parts), reverse=not ecrire):
        if p.is_symlink():
            continue
        m = p.stat().st_mode
        p.chmod(m | stat.S_IWUSR if ecrire else m & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--construire", action="store_true")
    a.add_argument("--deverrouiller", action="store_true",
                   help="rendre le noyau modifiable le temps d'une mise à jour (brain maj)")
    o = a.parse_args()
    brain = Path(os.environ.get("BRAIN_ROOT") or Path(__file__).resolve().parent.parent)
    noyau, _, _ = racines(brain)
    if not noyau.is_dir():
        print("brain vue : pas de noyau/agents/ — ce brain n'a pas de vue à construire.")
        return 0
    if o.deverrouiller:
        droit_d_ecrire(brain, True)
        print("noyau/ modifiable — `brain vue --construire` le rendra à sa posture")
        return 0
    e = construire(brain) if o.construire else etat(brain)
    verbe = "posés" if o.construire else "à poser"
    print(f"\nBRAIN VUE — {e['justes']} juste(s)")
    if e["a_creer"] or e["a_corriger"]:
        print(f"  liens {verbe}             {len(e['a_creer']) + len(e['a_corriger'])}")
    if e["orphelins"]:
        print(f"  liens orphelins {'retirés' if o.construire else 'à retirer'}  {len(e['orphelins'])}")
    for rel in e["reels"]:
        print(f"  ⚠️ agents/{rel} est un fichier réel, pas un lien — jamais touché. "
              f"À ranger : instance/agents/{rel} (ta version), puis le retirer de agents/")
    for rel in e["etrangers"]:
        print(f"  ⚠️ agents/{rel} est un fichier réel que rien ne fournit — git ne le voit pas. "
              f"À ranger : instance/agents/{rel}, puis `brain vue --construire`")
    bloque = e["reels"] or e["etrangers"]
    if not o.construire:
        a_faire = e["a_creer"] or e["a_corriger"] or e["orphelins"]
        # L'état dit aussi le verrou : la posture le décide, le disque peut l'avoir perdu
        # (un `--deverrouiller` resté sans `--construire`).
        ouvert = os.access(noyau, os.W_OK) and os.geteuid() != 0
        if ecrit_le_kernel(brain):
            print("  noyau/ modifiable (posture qui écrit le kernel)")
        elif ouvert:
            print("  ⚠️ la posture refuse le kernel et noyau/ est modifiable")
            a_faire = True
        else:
            print("  🔒 noyau/ en lecture seule (la posture refuse le kernel)")
        if a_faire:
            print("  `brain vue --construire` pour la construire")
        return 1 if (a_faire or bloque) else 0
    print(f"  {calculer_catalogue(brain)}")
    ecrire = ecrit_le_kernel(brain)
    droit_d_ecrire(brain, ecrire)
    print("  noyau/ modifiable (posture qui écrit le kernel)" if ecrire
          else "  🔒 noyau/ en lecture seule (la posture refuse le kernel)")
    return 1 if bloque else 0


if __name__ == "__main__":
    sys.exit(main())
