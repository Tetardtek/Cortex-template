#!/usr/bin/env python3
"""L'écart entre `kernel.lock` et le disque, rendu lisible avant qu'il crie.

`kernel.lock` porte l'empreinte SHA-256 du noyau. `kernel-update-check.sh` la
vérifiait déjà, correctement, et c'était justement le problème : au 04/09 il
rapportait **123 fichiers modifiés et 7 disparus**, sur cent trente lignes
rouges. Un rapport de cette taille ne se lit pas, il se referme. Le lock avait
dérivé six mois sans qu'une seule séance s'en aperçoive.

Il donne un chiffre, pas une liste, et il rougit selon deux règles de nature
différente. La liste complète, quand on la veut : `--detail`. Le vérificateur
d'avant est retiré le 28/09 : son mode « amont » ne marchait chez aucun fork
(le lock n'est pas distribué), et son mode local, c'est ce `--detail`.

    version    STRICTE — le lock et brain-compose.yml doivent déclarer la même.
               Une release sans régénération est une dérive en soi, quel que
               soit le nombre de fichiers.

    fichiers   AU SEUIL — le brain vit ; entre deux régénérations quelques
               fichiers bougent, et c'est normal. Un contrôle qui rougirait à
               chaque commit finirait ignoré, ce qui est exactement le défaut
               qu'on répare. Le seuil rend le signal lisible.

    python3 tools/derive_du_lock.py --brain ~/Dev/Brain
    python3 tools/derive_du_lock.py --brain ~/Dev/Brain --seuil 5
    python3 tools/derive_du_lock.py --brain ~/Dev/Brain --detail   # toute la liste
"""

from __future__ import annotations

import argparse
import subprocess
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _programme_a_part import programme_du_brain  # noqa: E402 — le programme installé à part

# Au-delà, l'écart cesse d'être le train-train d'une semaine de travail. Dix est
# un choix, pas une mesure : assez large pour ne pas crier sur une session
# ordinaire, assez étroit pour ne jamais laisser s'installer les 123 du 13/08.
SEUIL_DEFAUT = 10

LIGNE_FICHIER = re.compile(r"^  (?P<chemin>[^:]+): (?P<empreinte>[0-9a-f]{64})\s*$")


def empreinte(chemin: Path) -> str | None:
    try:
        return hashlib.sha256(chemin.read_bytes()).hexdigest()
    except OSError:
        return None


def version_declaree(compose: Path) -> str | None:
    """La version du noyau, telle que brain-compose.yml la déclare."""
    if not compose.is_file():
        return None
    for ligne in compose.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r'^version:\s*"?([^"\s]+)"?', ligne)
        if m:
            return m.group(1)
    return None


def lire_lock(lock: Path) -> tuple[str | None, dict[str, str]]:
    version, fichiers = None, {}
    for ligne in lock.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r'^kernel_version:\s*"?([^"\s]+)"?', ligne)
        if m:
            version = m.group(1)
            continue
        m = LIGNE_FICHIER.match(ligne)
        if m:
            fichiers[m.group("chemin")] = m.group("empreinte")
    return version, fichiers


def couverts(racine: Path) -> set[str]:
    """Ce que `kernel-lock-gen.sh` empreinte — la même règle, écrite ici aussi.

    Deux endroits décrivent le même périmètre : c'est exactement le défaut que
    ce projet traque. Assumé faute de mieux, et signalé — le jour où le
    générateur lira les déclarations `brain-distribuable`, cette
    fonction devra suivre, et le témoin le dira avant l'utilisateur.
    """
    trouves = {"KERNEL.md", "brain-compose.yml", "brain-constitution.md"}
    for f in (racine / "agents").rglob("*.md"):
        rel = f.relative_to(racine)
        if "reviews" in rel.parts or f.name.startswith("_template"):
            continue
        trouves.add(str(rel))
    for motif in ("*.sh", "*.py"):
        for f in (racine / "scripts").rglob(motif):
            # Même règle que le générateur : ce qui se déclare `ponctuel` n'est
            # pas du noyau et n'a pas à peser dans sa dérive.
            try:
                tete = "".join(f.open(encoding="utf-8", errors="replace")
                               .readlines()[:12])
            except OSError:
                tete = ""
            if re.search(r"^#\s*brain-rattachement:\s*ponctuel\b", tete, re.M):
                continue
            trouves.add(str(f.relative_to(racine)))
    # Le générateur n'empreinte que ce que git SUIT. Compter le disque ajoutait
    # tout ce que .gitignore écarte : le 27/09, les 9 scripts d'une distribution
    # Ventoy posée sous scripts/ventoy/ (ignorée) pesaient 9 sur un seuil de 10
    # — le prochain fichier du noyau aurait rougi à tort. Hors dépôt git (un
    # banc jetable), on retombe sur le disque.
    suivis = subprocess.run(["git", "-C", str(racine), "ls-files"],
                            capture_output=True, text=True)
    if suivis.returncode == 0 and suivis.stdout:
        trouves &= set(suivis.stdout.splitlines())
    return {c for c in trouves if (racine / c).is_file()}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--seuil", type=int, default=SEUIL_DEFAUT)
    p.add_argument("--detail", action="store_true",
                   help="lister tous les fichiers d'écart, pas seulement les quatre premiers")
    args = p.parse_args()

    racine = args.brain.expanduser().resolve()
    # Un brain servi par un programme installé à part : le lock décrit le programme,
    # il se juge là où le programme vit — pas sur les liens de la vue.
    programme = programme_du_brain(racine)
    if programme is not None:
        print(f"\n  le noyau vit dans le programme installé à part : {programme}")
        racine = programme
    lock = racine / "kernel.lock"
    if not lock.is_file():
        print("\n  ❌ kernel.lock absent — le noyau n'a aucune empreinte.\n")
        return 1

    version_lock, empreintes = lire_lock(lock)
    if not empreintes:
        print("\n  ❌ kernel.lock ne contient aucune empreinte — illisible ou "
              "généré de travers.\n")
        return 1

    modifies, disparus = [], []
    for chemin, attendue in empreintes.items():
        obtenue = empreinte(racine / chemin)
        if obtenue is None:
            disparus.append(chemin)
        elif obtenue != attendue:
            modifies.append(chemin)

    nouveaux = sorted(couverts(racine) - set(empreintes))
    ecart = len(modifies) + len(disparus) + len(nouveaux)

    version_compose = version_declaree(racine / "brain-compose.yml")
    desaccord_version = (version_lock and version_compose
                         and version_lock != version_compose)

    print(f"\nLOCK — {len(empreintes)} fichiers empreints, version {version_lock}")
    print(f"\n  modifiés    {len(modifies)}")
    print(f"  disparus    {len(disparus)}")
    print(f"  jamais vus  {len(nouveaux)}")
    print(f"  écart       {ecart} — seuil {args.seuil}")

    if desaccord_version:
        print(f"\n  ❌ le lock déclare {version_lock}, brain-compose.yml "
              f"{version_compose}.")
        print("     Une release sans régénération : l'empreinte décrit un noyau")
        print("     qui n'existe plus. Régénérer avant toute autre lecture.")
    elif ecart > args.seuil:
        print(f"\n  ❌ {ecart} fichiers d'écart — au-delà du seuil.")
        for titre, liste in (("modifiés", modifies), ("disparus", disparus),
                             ("jamais vus", nouveaux)):
            for c in (liste if args.detail else liste[:4]):
                print(f"       {titre:11} {c}")
            if not args.detail and len(liste) > 4:
                print(f"       {'':11} … et {len(liste) - 4} autres")
    else:
        print("\n  ✅ le lock décrit le noyau qui est là — écart sous le seuil")

    if desaccord_version or ecart > args.seuil:
        print("\n     Régénérer : bash scripts/kernel-lock-gen.sh")
        print("     Le détail fichier par fichier : --detail\n")
        return 1
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
