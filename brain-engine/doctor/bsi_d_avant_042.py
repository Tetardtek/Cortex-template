#!/usr/bin/env python3
"""Un agent décrit-il encore le BSI d'avant BRAIN-042 ?

Ce qui pourrirait en silence sans lui : **une instruction qui ordonne un geste
sur un monde qui n'existe plus, et que l'agent exécute quand même.**

Le 19/03, BRAIN-042 a mis claims et signaux en base : plus de `claims/*.yml`,
plus de table à tenir dans `BRAIN-INDEX.md`. Six mois plus tard, quatorze
agents, trois contextes de boot et la spec elle-même décrivaient encore
l'ancien monde. L'étape 7 de `session-orchestrator` faisait modifier
`claims/<sess-id>.yml` et régénérer `BRAIN-INDEX.md ## Claims` — trouvé le 26/09
en relisant brain#84, par hasard. Réécrits les 26-27/09 (brain#91,
brain-profil#1) ; ce contrôle empêche le retour.

── Ce qu'il cherche ────────────────────────────────────────────────────────

    claims/<…>.yml        un fichier de claim            (supprimés le 19/03)
    ## Claims, ## Signals une section de BRAIN-INDEX     (ni tenue, ni alimentée)
    UNBLOCK               un type de signal              (n'a jamais existé)

── Citer n'est pas ordonner : le marqueur ──────────────────────────────────

Une ligne peut NOMMER l'ancien monde pour dire qu'il est révolu — un bandeau,
un changelog, la spec qui raconte la v1. Elle le DÉCLARE par un marqueur
invisible au rendu :

    `## Claims actifs` à la main : ces sections n'existent plus. <!-- bsi-v1 -->

Toute occurrence NON marquée rougit. Déclaré, pas deviné — tranché le 27/09,
comme pour les chiffres de la doc : un motif d'« instruction » (un verbe devant
la cible) aurait deviné dans du texte libre, avec des faux positifs sur les
citations et des faux négatifs sur les tournures nouvelles.

Deux choses ne sont PAS des occurrences, par la STRUCTURE, pas par le sens :
  - un **titre** markdown (`## Signals — Bus inter-sessions`) : c'est le nom
    d'une section de l'aiguillage, pas une référence à la table morte ;
  - un marqueur entre backticks n'en est pas un (c'est un exemple de la
    convention, comme dans ce texte).

── Où il cherche ───────────────────────────────────────────────────────────

Les fichiers SUIVIS par git — `git ls-files`, jamais le disque :

    brain    agents/ (hors archive/) — ou, si c'est une vue, noyau/agents/ et
             instance/agents/ —, contexts/ (hors archive-v1/), BRAIN-INDEX.md
    profil   specs/  — le dépôt séparé `profil/`, s'il en est un
             la racine, sauf les fichiers qui se DÉCLARENT instantanés (27/09) :
             un bandeau « Instantané non maintenu » ou « Doublon d'une source
             vivante » dans les 16 premières lignes. Leur ancien BSI est un
             instantané daté, pas une consigne ; une procédure vivante de la
             racine, elle, ne doit pas le reprendre.

Git qui ne répond pas sur le brain : ROUGE (un échec n'est pas une abstention).
Un `profil/` qui n'est pas un dépôt git (un fork) : dit, non relu, pas rouge.

    python3 tools/bsi_d_avant_042.py --brain ~/Dev/Brain
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MOTIF = re.compile(r"claims/[^\s`)\]]*\.yml|##\s*Claims\b|##\s*Signals\b|\bUNBLOCK\b")
MARQUEUR = "<!-- bsi-v1 -->"
TITRE = re.compile(r"^\s{0,3}#{1,6}\s")

# `noyau/agents/` et `instance/agents/` : les sources SUIVIES d'un `agents/` qui est
# une vue de liens — la vue, elle, est ignorée par git, et `ls-files` n'y voyait
# rien (mesuré le 3/10 : 7 fichiers relus au lieu de 83). Sans vue, git n'y trouve
# rien, et rien ne change.
BRAIN_CHAMP = ("agents/", "noyau/agents/", "instance/agents/", "contexts/", "BRAIN-INDEX.md")
BRAIN_HORS = ("agents/archive/", "noyau/agents/archive/", "instance/agents/archive/",
              "contexts/archive-v1/")

_ok = _ko = 0


class Illisible(RuntimeError):
    """Une lecture qui n'a pas pu se faire. Jamais « rien trouvé »."""


# ── Lire ───────────────────────────────────────────────────────────────────

def _sans_backticks(ligne: str) -> str:
    return re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), ligne)


def _declare(ligne: str) -> bool:
    """Le marqueur est-il une DÉCLARATION ? Pur.

    Hors backticks fermés sur la ligne — sinon c'est l'exemple de la
    convention. Et précédé d'un nombre PAIR de backticks : un nombre impair
    veut dire qu'un code en ligne s'est ouvert et continue à la ligne suivante
    — le marqueur est DEDANS, il s'afficherait et ne déclarerait rien. Commis en
    posant les premiers marqueurs (BRAIN-INDEX.md, 27/09).
    """
    i = _sans_backticks(ligne).find(MARQUEUR)
    return i != -1 and ligne[:i].count("`") % 2 == 0


def occurrences(texte: str) -> list[tuple[int, str]]:
    """(n° de ligne, ligne) pour chaque référence NON déclarée. Pur.

    La cible est cherchée partout — backticks et blocs de code compris : une
    instruction s'écrit justement souvent en code. Seul le MARQUEUR doit être
    hors backticks pour compter, sinon c'est l'exemple de la convention.
    """
    trouves = []
    for n, ligne in enumerate(texte.splitlines(), start=1):
        if TITRE.match(ligne):
            continue
        if not MOTIF.search(ligne):
            continue
        if _declare(ligne):
            continue
        trouves.append((n, ligne.strip()))
    return trouves


def suivis(depot: Path, champ: tuple[str, ...], hors: tuple[str, ...]) -> list[Path]:
    """Les fichiers suivis sous `champ`, hors `hors`. LÈVE si git ne répond pas."""
    r = subprocess.run(["git", "-C", str(depot), "ls-files", "-z", "--", *champ],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Illisible(f"git ls-files a échoué sur {depot} : "
                        f"{(r.stderr or '').strip()[:100] or 'sans message'}")
    return [depot / p for p in r.stdout.split("\0")
            if p and not p.startswith(hors) and (depot / p).is_file()
            and p.endswith((".md", ".yml", ".yaml"))]


INSTANTANE = re.compile(r"Instantané non maintenu|Doublon d'une source vivante")


def est_instantane(texte: str) -> bool:
    """Le fichier se déclare-t-il instantané ? Le bandeau, en tête — pas ailleurs."""
    return bool(INSTANTANE.search("\n".join(texte.splitlines()[:16])))


def racine_vivante(profil: Path) -> list[Path]:
    """Les fichiers suivis de la RACINE de `profil/`, hors instantanés déclarés."""
    return [f for f in suivis(profil, (), ())
            if f.parent == profil
            and not est_instantane(f.read_text(encoding="utf-8", errors="replace"))]


def est_depot(chemin: Path) -> bool:
    r = subprocess.run(["git", "-C", str(chemin), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return r.returncode == 0 and Path(r.stdout.strip()).resolve() == chemin.resolve()


# ── Auto-épreuve ───────────────────────────────────────────────────────────

def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


# 🔴 L'incident, recopié mot pour mot : l'étape 7 de session-orchestrator avant
# brain#84 (`bd0d826^`). Quatre lignes sur six doivent rougir.
INCIDENT = """7. BSI close claim
   → Modifier claims/<sess-id>.yml : status: open → closed, closed_at: <timestamp>
   → Régénérer la table BRAIN-INDEX.md ## Claims (source unique = claims/*.yml) :
     bash $BRAIN_ROOT/scripts/brain-index-regen.sh
   → ⚠️ Ne jamais écrire manuellement dans BRAIN-INDEX.md ## Claims
   git -C $BRAIN_ROOT add BRAIN-INDEX.md claims/<sess-id>.yml"""


def auto_epreuve() -> None:
    print("\nAUTO-ÉPREUVE\n")
    verifie("l'incident du 26/09 : l'étape 7 d'avant brain#84 rougit sur 4 lignes",
            [n for n, _ in occurrences(INCIDENT)], [2, 3, 5, 6])
    verifie("« ## Claims » seul, sans « actifs », est attrapé",
            len(occurrences("Régénérer BRAIN-INDEX.md ## Claims")), 1)
    verifie("« 1. Lire BRAIN-INDEX.md ## Claims actifs » rougit",
            len(occurrences("1. Lire BRAIN-INDEX.md ## Claims actifs")), 1)
    verifie("écrire dans ## Signals rougit",
            len(occurrences("→ Écrire dans BRAIN-INDEX.md ## Signals")), 1)
    verifie("un signal UNBLOCK rougit",
            len(occurrences("→ émettre signal BSI UNBLOCK pour chaque sess_id")), 1)
    verifie("claims/*.yml rougit",
            len(occurrences("Lire les claims fermés (claims/*.yml avec status: closed)")), 1)
    verifie("la même ligne MARQUÉE passe",
            occurrences("`## Claims actifs` n'existent plus. <!-- bsi-v1 -->"), [])
    verifie("un marqueur entre backticks est un exemple, pas une déclaration",
            len(occurrences("écrire `## Claims <!-- bsi-v1 -->` pour l'exemple")), 1)
    verifie("un marqueur DANS un code en ligne coupé par un saut de ligne ne déclare rien",
            len(occurrences("un agent qui demande de « lire `## Claims <!-- bsi-v1 -->\n"
                            "actifs` », d'écrire")), 1)
    verifie("un titre de section n'est pas une référence",
            occurrences("## Signals — Bus inter-sessions"), [])
    verifie("… mais « ## Signals » cité dans du texte l'est",
            len(occurrences("la table ## Signals n'est plus alimentée")), 1)
    verifie("« unblocked » en minuscules dans une phrase ne rougit pas",
            occurrences("the scope is unblocked now"), [])
    verifie("un chemin qui contient claims/ sans .yml ne rougit pas",
            occurrences("le dossier `claims/` a été vidé"), [])
    verifie("un bandeau d'instantané en tête se déclare",
            est_instantane("---\nname: x\n---\n> ⚠️ **Instantané non maintenu — étiqueté.**\n"), True)
    verifie("le même mot loin de la tête ne déclare rien",
            est_instantane("\n" * 30 + "Instantané non maintenu"), False)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    print("LE BSI D'AVANT BRAIN-042 — un agent ordonne-t-il un geste sur un monde "
          "disparu ?\n")

    rouges: list[tuple[str, int, str]] = []
    relus = 0
    try:
        fichiers = [("brain", brain, f) for f in suivis(brain, BRAIN_CHAMP, BRAIN_HORS)]
    except Illisible as exc:
        print(f"  ❌ {exc}")
        auto_epreuve()
        print(f"\nVERDICT: ❌ brain illisible — {exc}")
        return 1

    profil = brain / "profil"
    if est_depot(profil):
        try:
            fichiers += [("profil", profil, f) for f in suivis(profil, ("specs/",), ())]
            fichiers += [("profil", profil, f) for f in racine_vivante(profil)]
        except Illisible as exc:
            print(f"  ❌ {exc}")
            auto_epreuve()
            print(f"\nVERDICT: ❌ profil illisible — {exc}")
            return 1
    else:
        print("  ⚪ profil/ n'est pas un dépôt git ici — ses specs ne sont pas relues")

    for etiquette, depot, f in fichiers:
        relus += 1
        for n, ligne in occurrences(f.read_text(encoding="utf-8", errors="replace")):
            rouges.append((f"{etiquette}:{f.relative_to(depot)}:{n}", n, ligne))

    for ou, _, ligne in rouges:
        print(f"  ❌ {ou:<48} {ligne[:90]}")

    auto_epreuve()
    print()
    if _ko:
        print(f"VERDICT: ❌ auto-épreuve : {_ko} cas sur {_ok + _ko} — l'outil ne "
              f"refuse plus ce qu'il annonce")
        return 1
    if rouges:
        print(f"VERDICT: ❌ {len(rouges)} ligne(s) décrivent le BSI d'avant BRAIN-042 "
              f"sans le déclarer — {rouges[0][0]}. Réécrire sur bsi-claim.sh / "
              f"bsi-signal.sh / bsi-query.sh, ou marquer {MARQUEUR} si la ligne "
              f"CITE l'ancien monde pour le dire révolu.")
        return 1
    print(f"VERDICT: ✅ {relus} fichier(s) relus — aucune instruction sur le BSI "
          f"d'avant BRAIN-042")
    return 0


if __name__ == "__main__":
    sys.exit(main())
