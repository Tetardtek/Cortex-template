#!/usr/bin/env python3
"""Le socle du boot désigne-t-il des fichiers qui existent ? —,.

`contextes_de_session.py` vérifie depuis le 04/09 que chaque fichier déclaré
dans un `L0`/`L1` existe. **Le socle, lui, n'était vérifié par personne.**

Le socle, c'est l'ordre de bootstrap écrit en tête de `~/.claude/CLAUDE.md` —
six fichiers lus à chaque session, quel que soit le type. Trois outils citent ce
fichier (`bsi_coherence.py`, `contextes_de_session.py`, `liens_morts.py`) et
aucun n'ouvre son contenu : `liens_morts.py` n'en connaît que le **nom**, dans
une liste de fichiers racine.

Conséquence mesurée le 10/09 : déplacer `profil/forge-locale.md` casserait le
boot de **toutes** les sessions sans qu'un seul contrôle rougisse. Les six
existaient ce jour-là — rien ne le garantissait.

    python3 tools/socle_du_boot.py --brain ~/Dev/Brain

── Il vérifie deux socles : celui d'ici, et celui qu'un fork reçoit ────────

    ~/.claude/CLAUDE.md        le socle de CETTE machine
    profil/CLAUDE.md.example   le gabarit distribué au template

Un écart entre les deux est **normal** — `profil/forge-locale.md` porte les
réflexes de cette instance et n'a rien à faire chez un fork ; il a été sorti de
`collaboration.md` le 05/09 exactement pour ça. Cet écart-là est donc
**déclaré** ci-dessous, avec son motif.

🔴 **Tout autre écart rougit.** C'est le point : un gabarit qui perd un fichier
du socle livre un brain qui boote incomplet, et personne ne s'en aperçoit —
c'est arrivé quatre fois sur d'autres sujets cette semaine.

── ENTRYPOINT.md, et pourquoi il ne doit pas revenir ───────────────────────

Il existait un troisième socle : `ENTRYPOINT.md`, *« point d'entrée universel,
valide pour tout LLM »*, écrit le 06/09. **Supprimé le 11/09**, et le
motif tient en trois faits mesurés : 0 référence exécutable, absent du template,
et divergent de `CLAUDE.md` sur 4 fichiers sur 6.

Le fait qui a tranché : un client qui l'aurait suivi bootait **sans gardien des
secrets et sans claim BSI** — donc invisible aux autres sessions, et faisant
basculer la garde `pre-commit-zone` qui n'applique le registre d'écriture que
s'il y a exactement un claim ouvert. Un contrat neutre qui perd les deux
garanties non négociables n'est pas neutre, il est faux.

Ce contrôle **signale son retour**. Pas pour l'interdire — mais parce qu'un
troisième socle qui réapparaît sans décision est exactement ce qu'on vient de
retirer.

Ce qui le fait rougir : **un fichier déclaré qui n'existe pas**, ou **un écart
non déclaré entre les deux socles**.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# `0. \`/chemin/absolu\`  — commentaire`  (CLAUDE.md)
# `0. chemin/relatif      → commentaire`  (ENTRYPOINT.md, dans un bloc code)
NUMEROTEE = re.compile(r"^\s*\d+\.\s+`?([^`\s]+)`?")


# Les ecarts VOULUS entre le socle de cette machine et le gabarit distribue.
# Tout ce qui n'est pas ici fait rougir : un gabarit qui perd un fichier du
# socle livre un brain qui boote incomplet, sans que rien ne le dise.
ECARTS_ATTENDUS = {
    "forge-locale.md":
        "porte les réflexes de CETTE instance — sorti de `collaboration.md` "
        "le 05/09 précisément parce que celui-ci est distribué",
}


def socle(texte: str, titre: str) -> list[str]:
    """Les chemins de la première liste numérotée qui suit `titre`."""
    lignes = texte.splitlines()
    depart = next((i for i, l in enumerate(lignes)
                   if titre.lower() in l.lower() and l.lstrip().startswith("#")), None)
    if depart is None:
        return []
    trouves, commence = [], False
    for ligne in lignes[depart + 1:]:
        m = NUMEROTEE.match(ligne)
        if m:
            commence = True
            trouves.append(m.group(1))
        elif commence and ligne.strip() and not ligne.strip().startswith(("```", ">", "#")):
            break
        elif ligne.lstrip().startswith("## ") and commence:
            break
    return trouves


def verifier(nom: str, chemins: list[str], brain: Path) -> list[str]:
    """Chaque chemin declare designe-t-il un fichier ?

    🔴 `<BRAIN_ROOT>` se RESOUT, il ne se saute pas. La premiere version
    traitait tout `<...>` comme un gabarit indesignable et sautait les CINQ
    chemins du socle distribue : le controle annoncait « tout ce que le boot
    declare existe » sans avoir rien verifie de ce qu'un fork recoit. Un vert
    creux, trouve en le relisant le 11/09.

    Reste un vrai gabarit, qui lui ne designe rien : `projets/<projet>.md`,
    ou le chevron porte une VARIABLE et non une racine.
    """
    absents = []
    for c in chemins:
        # `<BRAIN_ROOT>` est une racine connue — on la resout.
        c = c.replace("<BRAIN_ROOT>/", "").replace("<BRAIN_ROOT>", "")
        # Ce qui porte encore un chevron est un gabarit : `projets/<projet>.md`
        # ne designe pas un fichier, il en decrit une famille.
        if "<" in c or ">" in c:
            print(f"     ⏭️  {c}  (gabarit, pas un fichier)")
            continue
        p = Path(c).expanduser() if c.startswith(("/", "~")) else brain / c
        if p.is_file():
            print(f"     ✅ {c}")
        else:
            print(f"     ❌ {c}  — DECLARE ET ABSENT")
            absents.append(c)
    return absents


def main() -> int:
    p = argparse.ArgumentParser(description="Le socle du boot désigne-t-il des fichiers réels ?")
    p.add_argument("--brain", required=True, type=Path)
    p.add_argument("--claude-md", type=Path,
                   default=Path.home() / ".claude" / "CLAUDE.md")
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    sources = []
    if a.claude_md.is_file():
        sources.append(("CLAUDE.md", a.claude_md, "Bootstrap"))
    else:
        print(f"⏭️  {a.claude_md} introuvable — socle client non vérifiable.")
    gabarit = brain / "profil" / "CLAUDE.md.example"
    if gabarit.is_file():
        sources.append(("CLAUDE.md.example", gabarit, "Bootstrap"))
    else:
        print(f"⏭️  {gabarit} introuvable — le socle distribué n'est pas "
              f"vérifiable.")

    # Le troisieme socle, retire le 11/09 : on verifie qu'il ne revient pas.
    revenant = brain / "ENTRYPOINT.md"

    absents_total, ecarts_total, socles = 0, 0, {}

    # ── PATHS.md — le rang 0 du socle, et personne ne le verifiait ──────────
    #
    # `PATHS.md` est le fichier `0` des DEUX socles, et il declare les chemins
    # machine dont tout depend. Rien ne verifiait qu'ils existent : une passe du
    # 10/09 a trouve CINQ entrees fausses sur dix-sept — dont trois
    # qui n'etaient pas mortes mais MAL DECLAREES. Le defaut s'est donc deja
    # produit, ce qui est la meilleure raison d'outiller.
    #
    # C'est ici et pas dans un 51e controle : « ce que le boot declare
    # existe-t-il ? » est exactement la question de ce fichier. PATHS.md en est
    # le premier maillon.
    chemins = brain / "PATHS.md"
    if chemins.is_file():
        motif = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")
        vus, manquants = 0, []
        for ligne in chemins.read_text(encoding="utf-8").splitlines():
            m = motif.match(ligne)
            if not m:
                continue
            vus += 1
            cible = Path(m.group(2)).expanduser()
            if not cible.exists():
                manquants.append((m.group(1), m.group(2)))
        print(f"\n  PATHS.md — {vus} chemin(s) machine déclaré(s)")
        for nom, cible in manquants:
            print(f"     ❌ {nom} → {cible}  — DECLARE ET ABSENT")
        if manquants:
            absents_total += len(manquants)
        elif vus:
            print(f"     ✅ tous existent")


    if not sources:
        if absents_total:
            print(f"\n❌ {absents_total} chemin(s) déclaré(s) et absent(s).",
                  file=sys.stderr)
            return 1
        print("⏭️  aucun socle client à vérifier — seul PATHS.md l'a été.")
        return 0

    for nom, chemin, titre in sources:
        # On ne lit QUE la liste numerotee : le reste du fichier ne nous regarde
        # pas, et `CLAUDE.md` n'a pas a etre recopie dans une sortie d'outil.
        declares = socle(chemin.read_text(encoding="utf-8"), titre)
        socles[nom] = declares
        if not declares:
            print(f"  ⚠️  {nom} — aucune liste numérotée sous « {titre} » : le "
                  f"format a changé, ce contrôle ne voit plus rien")
            continue
        print(f"  {nom} — {len(declares)} fichier(s) déclaré(s)")
        absents_total += len(verifier(nom, declares, brain))

    # ── L'ecart entre le socle d'ici et celui qu'un fork recoit ────────────
    #
    # Un ecart DECLARE est normal ; tout autre rougit. La difference compte :
    # « il y a un ecart » ne dit rien, « il y a un ecart qu'on n'a pas voulu »
    # dit tout.
    if len(socles) == 2:
        noms = list(socles)
        ici = {Path(x).name for x in socles[noms[0]]}
        distribue = {Path(x).name for x in socles[noms[1]]}
        communs = ici & distribue
        print(f"\n  ℹ️  les deux socles partagent {len(communs)} fichier(s) sur "
              f"{max(len(ici), len(distribue))}")

        inattendus = []
        for fichier in sorted(ici - distribue):
            motif = ECARTS_ATTENDUS.get(fichier)
            if motif:
                print(f"      ✅ {fichier} — ici seulement, et c'est voulu : {motif}")
            else:
                print(f"      ❌ {fichier} — dans le socle d'ici, ABSENT du "
                      f"gabarit distribué", file=sys.stderr)
                inattendus.append(fichier)
        for fichier in sorted(distribue - ici):
            print(f"      ❌ {fichier} — dans le gabarit, absent du socle d'ici",
                  file=sys.stderr)
            inattendus.append(fichier)
        if inattendus:
            print(f"      → un fork qui installe ce gabarit bootera sans ces "
                  f"fichiers.\n        Si c'est voulu, l'inscrire dans "
                  f"`ECARTS_ATTENDUS`.", file=sys.stderr)
            # 🔴 Compté À PART. Mélanger les deux avec `absents_total` faisait
            # dire « N fichiers déclarés au boot et absents du disque » alors
            # que le fichier EXISTE — c'est le gabarit qui ne le déclare pas.
            # Un message qui décrit mal envoie chercher au mauvais endroit.
            ecarts_total += len(inattendus)

    # ── Le troisieme socle ne doit pas revenir ──────────────────────────────
    if revenant.is_file():
        print(f"\n  ⚠️  `ENTRYPOINT.md` est de retour à la racine.\n"
              f"      Il a été supprimé le 11/09 : 0 référence, absent\n"
              f"      du template, et un client qui le suivait bootait SANS\n"
              f"      gardien des secrets ni claim BSI. S'il revient, c'est une\n"
              f"      décision — qu'elle soit écrite.")

    if absents_total:
        print(f"\n❌ {absents_total} fichier(s) déclaré(s) au boot et absent(s) du "
              f"disque.\n   Un boot qui charge un fichier disparu ne se plaint "
              f"pas : il continue sans.", file=sys.stderr)
    if ecarts_total:
        print(f"\n❌ {ecarts_total} écart(s) NON DÉCLARÉ(S) entre le socle d'ici "
              f"et le gabarit\n   distribué. Les fichiers existent — c'est leur "
              f"DÉCLARATION qui diverge,\n   et un fork n'en saura rien.",
              file=sys.stderr)
    if absents_total or ecarts_total:
        return 1
    print(f"\n✅ tout ce que le boot déclare existe, ici et dans le gabarit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
