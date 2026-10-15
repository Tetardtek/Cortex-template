#!/usr/bin/env python3
# brain-distribuable: oui
"""brain sessions — les sessions du brain, et leurs claims : les voir, les ouvrir, les fermer.

    brain sessions                       les sessions ouvertes ici — rien ne bouge
    brain sessions --toutes              sur toutes les machines
    brain sessions --vieilles            ouvertes depuis plus que leur durée de vie
    brain sessions --orphelines          ouvertes, mais la session Claude Code ne vit plus
    brain sessions --non-declarees       vivantes dans le brain, sans claim qui les déclare
    brain sessions --ouvrir <id> …       ouvrir le claim d'une session
    brain sessions --prolonger [<id>]    la session est vivante : repousser l'expiration
    brain sessions --fermer <id> …       fermer son claim
    brain sessions --fermer-vieilles     fermer celles qui ont passé leur durée de vie
    brain sessions --rattacher           reprendre le claim d'une identité remplacée

Une façade : le verbe parle français, les scripts font le travail et gardent
leurs noms — `bsi-query.sh` (lire), `bsi-claim.sh` (écrire), `claims-orphelins.py`.
Leur code de sortie traverse tel quel : le boot et le doctor s'y fient. Les noms
d'avant (`--scope`, `--result`…) restent des alias, hors de l'aide.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent

# Les options d'un claim : le nom du verbe → le nom que `bsi-claim.sh` lit, et les
# noms d'avant, acceptés hors de l'aide.
OUVRIR = (("portee", "scope", ["--scope"], "le périmètre (brain/kernel, work/<projet>…)"),
          ("type", "type", [], "le type de session (work, brain, explore, pilote, chill, learning)"),
          ("zone", "zone", [], "la zone du claim"), ("mode", "mode", [], "le mode du claim"),
          ("recit", "story", ["--story"], "une phrase : ce que la session vient faire"),
          ("projet", "project", ["--project"], "le projet"), ("handoff", "handoff", [], "le handoff lié"),
          ("instance", "instance", [], "l'instance"), ("duree", "ttl", ["--ttl"], "la durée de vie, en heures"))
FERMER = (("resultat", "result", ["--result"], "ce que la session a produit"),
          ("energie", "energy", ["--energy"], "high, medium ou low"),
          ("intention", "intention", [], "l'intention"), ("etiquettes", "tags", ["--tags"], "des étiquettes"),
          ("livrables", "deliverables", ["--deliverables"], "les livrables"))


def lancer(cmd: list[str]) -> int:
    return subprocess.run(cmd).returncode


def analyseur() -> argparse.ArgumentParser:
    """Les options du verbe — lues aussi par le test qui juge les instructions des agents."""
    p = argparse.ArgumentParser(prog="brain sessions", description="Les sessions du brain, et leurs claims.")
    geste = p.add_mutually_exclusive_group()
    geste.add_argument("--toutes", action="store_true", help="les sessions ouvertes sur toutes les machines")
    geste.add_argument("--vieilles", action="store_true", help="ouvertes depuis plus que leur durée de vie")
    geste.add_argument("--orphelines", action="store_true", help="ouvertes, mais la session Claude Code ne vit plus")
    geste.add_argument("--non-declarees", action="store_true", help="vivantes dans le brain, sans claim qui les déclare")
    geste.add_argument("--sans-claim", dest="non_declarees", action="store_true", help=argparse.SUPPRESS)
    geste.add_argument("--ouvrir", metavar="ID", help="ouvrir le claim d'une session")
    geste.add_argument("--prolonger", metavar="ID", nargs="?", const="",
                       help="la session est vivante : repousser l'expiration (la sienne, sans ID)")
    geste.add_argument("--fermer", metavar="ID", nargs="?", const="",
                       help="fermer le claim d'une session (la sienne, sans ID)")
    geste.add_argument("--fermer-vieilles", action="store_true", help="fermer celles qui ont passé leur durée de vie")
    geste.add_argument("--rattacher", action="store_true", help="reprendre le claim d'une identité remplacée")
    p.add_argument("--discret", action="store_true", help="avec --orphelines ou --prolonger : rien s'il n'y a rien")
    p.add_argument("--quiet", dest="discret", action="store_true", help=argparse.SUPPRESS)
    # Pour un script : le nombre seul (des ouvertes, ou des vieilles avec --vieilles).
    p.add_argument("--compte", action="store_true", help=argparse.SUPPRESS)
    # La dernière session en base, son type et sa santé — le signal 3 du boot (helloWorld).
    geste.add_argument("--sante", action="store_true", help=argparse.SUPPRESS)
    for nom, _, alias, aide in OUVRIR:
        p.add_argument(f"--{nom}", dest=nom, help=f"avec --ouvrir : {aide}")
        for vieux in alias:
            p.add_argument(vieux, dest=nom, help=argparse.SUPPRESS)
    for nom, _, alias, aide in FERMER:
        p.add_argument(f"--{nom}", dest=nom, help=f"avec --fermer : {aide}")
        for vieux in alias:
            p.add_argument(vieux, dest=nom, help=argparse.SUPPRESS)
    p.add_argument("--pas-le-mien", action="store_true", help="avec --fermer : le claim d'une autre session")
    return p


def main(argv: list[str] | None = None) -> int:
    a = analyseur().parse_args(argv)

    query = ["bash", str(ICI / "bsi-query.sh")]
    claim = ["bash", str(ICI / "bsi-claim.sh")]
    orphelins = [sys.executable, str(ICI / "claims-orphelins.py")]

    def options(table) -> list[str]:
        sortie = []
        for nom, interne, _, _ in table:
            valeur = getattr(a, nom)
            if valeur is not None:
                sortie += [f"--{interne}", valeur]
        return sortie

    if a.ouvrir:
        return lancer(claim + ["open", a.ouvrir] + options(OUVRIR))
    if a.fermer is not None:
        return lancer(claim + ["close"] + ([a.fermer] if a.fermer else []) + options(FERMER) + (["--pas-le-mien"] if a.pas_le_mien else []))
    if a.prolonger is not None:
        # `touch` lit ses options par paires `--clé valeur` : un `--quiet` seul après l'ID
        # passerait inaperçu, et en tête il serait pris pour l'absence d'ID.
        return lancer(claim + ["touch"] + ([a.prolonger] if a.prolonger else []) + (["--quiet", "1"] if a.discret else []))
    if a.fermer_vieilles:
        return lancer(claim + ["close-stale"])
    if a.rattacher:
        return lancer(claim + ["rattacher"])
    if a.orphelines:
        return lancer(orphelins + (["--quiet"] if a.discret else []))
    if a.non_declarees:
        return lancer(orphelins + ["--sans-claim"])
    if a.sante:
        return lancer(query + ["health"])
    if a.toutes:
        return lancer(query + ["peers"])
    if a.vieilles:
        return lancer(query + ["count-stale" if a.compte else "stale"])
    return lancer(query + ["count-open" if a.compte else "open"])


if __name__ == "__main__":
    sys.exit(main())
