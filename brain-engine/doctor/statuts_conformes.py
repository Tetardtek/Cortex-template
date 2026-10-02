#!/usr/bin/env python3
"""Le `status:` d'une fiche projet est-il une valeur que la base accepte ?

Ce qui pourrirait en silence sans lui : **une fiche que la base refusera
d'enregistrer, et qu'on ne découvre qu'en tentant d'écrire.**

Le 24/09, régénérer le cache `projects` a échoué net :

    pymysql.err.OperationalError: (1105, "Data truncated for column 'status'")

`projets/ma-carte.md` portait `status: publie`. La fiche avait porté `prototype`
avant d'être trackée — **les deux hors énumération**, et personne ne l'avait vu.

⚠️ **`normalize_status.py` était VERT pendant ce temps**, et il avait raison :
ce n'est pas un contrôle de conformité, c'est un **migrateur**, écrit
pour sortir la prose de neuf frontmatters cassés. Il ne parcourt jamais
`projets/*.md` — il traite une table `CIBLES` **codée en dur**, figée à l'audit
du 03/09 :

    cibles = {k: v for k, v in CIBLES.items() if not args.only or k == args.only}

Son « rien à normaliser » veut donc dire *« mes 18 cibles sont propres »*, jamais
*« le brain est conforme »*. **Aucune fiche née après le 03/09 n'était jugée.**

    python3 tools/statuts_conformes.py --brain ~/Dev/Brain

── Ce qu'il juge ───────────────────────────────────────────────────────────

    1. une fiche dont `status:` est hors enumeration     ROUGE
    2. deux declarations de l'enumeration qui divergent  ROUGE
    3. une fiche sans `status:`                          info, si `type:` la dispense

Le 2 n'est pas cosmétique : l'énumération est écrite **trois fois** — dans
`schema-dolt.sql`, dans `ENUM` de `normalize_status.py`, et dans le docstring du
même fichier. Mesuré le 24/09 : le docstring en oubliait une (`pause`). Une règle
écrite trois fois finit par ne plus dire la même chose, et c'est le motif que
`contrat/capacites.yml` existe pour empêcher ailleurs.

── La source de vérité est le SCHÉMA, pas la base ──────────────────────────

L'énumération est lue dans `brain-engine/schema-dolt.sql`, pas interrogée sur une
base vivante : un contrôle qui dépend d'un moteur allumé ne juge rien quand il
est éteint. La base, elle, est la seule à **faire respecter** la règle — et elle
la fait respecter trop tard, au moment d'écrire.

── Il n'écrit rien ─────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# 🔴 La table est OBLIGATOIRE dans la recherche. La premiere version cherchait
# `\`status\` enum(...)` n'importe ou dans le fichier et prenait la premiere
# occurrence — celle de `agents` : ('active','stable','draft','deprecated').
# Le controle a alors declare 49 fiches fausses alors qu'elles sont toutes
# bonnes. **Treize tables** de ce schema ont une colonne `status` en enum ; une
# regex qui ignore la table lit forcement la mauvaise.
ENUM_SCHEMA = re.compile(r"`status`\s+enum\(([^)]*)\)", re.I)
CREATE_TABLE = re.compile(r"^CREATE TABLE.*?`?(\w+)`?\s*\(", re.M)
ENUM_CODE = re.compile(r"^ENUM\s*=\s*\(([^)]*)\)", re.M)
FRONT_STATUS = re.compile(r"^status:\s*(.+?)\s*$", re.M)
FRONT_TYPE = re.compile(r"^type:\s*(.+?)\s*$", re.M)

# Un `type:` qui dispense de `status:` — ces fiches ne decrivent pas un projet.
TYPES_DISPENSES = {"reference", "handoff", "backlog", "review", "config"}

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


def valeurs(brut: str) -> list[str]:
    """Les valeurs d'une liste SQL ou Python, sans leurs guillemets."""
    return [v.strip().strip("'\"") for v in brut.split(",") if v.strip().strip("'\"")]


def enum_du_schema(brain: Path, table: str = "projects") -> list[str] | None:
    """L'enumeration `status` de LA table demandee, et d'aucune autre."""
    f = brain / "brain-engine" / "schema-dolt.sql"
    if not f.is_file():
        return None
    courante = None
    for ligne in f.read_text(encoding="utf-8", errors="replace").splitlines():
        mt = CREATE_TABLE.match(ligne)
        if mt:
            courante = mt.group(1)
            continue
        if courante == table:
            me = ENUM_SCHEMA.search(ligne)
            if me:
                return valeurs(me.group(1))
    return None


def enum_du_migrateur() -> list[str] | None:
    f = RACINE / "tools" / "normalize_status.py"
    if not f.is_file():
        return None
    m = ENUM_CODE.search(f.read_text(encoding="utf-8", errors="replace"))
    return valeurs(m.group(1)) if m else None


def enum_du_docstring() -> list[str] | None:
    """Ce que le docstring du migrateur ANNONCE — souvent autre chose."""
    f = RACINE / "tools" / "normalize_status.py"
    if not f.is_file():
        return None
    tete = f.read_text(encoding="utf-8", errors="replace")[:1200]
    trouves = re.findall(r"`([a-z]+)`", tete)
    connus = {"planned", "cadrage", "dev", "active", "prod", "pause", "archived"}
    # On garde l'ordre d'apparition, sans doublon.
    vus, sortie = set(), []
    for t in trouves:
        if t in connus and t not in vus:
            vus.add(t)
            sortie.append(t)
    return sortie or None


def fiches(brain: Path) -> list[tuple[str, str | None, str | None]]:
    """(nom, status, type) pour chaque fiche de projets/."""
    dossier = brain / "projets"
    if not dossier.is_dir():
        return []
    sortie = []
    for f in sorted(dossier.glob("*.md")):
        if f.stem == "_template":
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")[:2000]
        ms, mt = FRONT_STATUS.search(txt), FRONT_TYPE.search(txt)
        sortie.append((f.name, ms.group(1) if ms else None,
                       mt.group(1) if mt else None))
    return sortie


BRAIN_POUR_EPREUVE: Path = Path.home() / "Dev/Brain"


def auto_epreuve(enum: list[str]) -> None:
    print("\nAUTO-ÉPREUVE — sur des valeurs fabriquées\n")

    # Le temoin negatif d'abord : sans lui, « aucun rouge » ne se distingue pas
    # de « le juge ne juge rien ».
    verifie("témoin négatif : une valeur de l'énumération passe",
            "prod" in enum, True)
    verifie("témoin du défaut réel : `publie` est refusé",
            "publie" in enum, False)
    verifie("… et `prototype` aussi — l'autre valeur qu'avait portée ma-carte",
            "prototype" in enum, False)
    verifie("l'énumération lue au schéma en a bien sept",
            len(enum), 7)
    # 🔴 Le temoin qui manquait, et dont l'absence a coute 49 faux positifs :
    # treize tables ont une colonne `status` en enum. Celle d'`agents` est la
    # PREMIERE du fichier — si on la lit, c'est qu'on ne lit pas par table.
    verifie("on lit bien l'énumération de `projects`, pas celle d'`agents`",
            "stable" in enum, False)
    verifie("… et `agents`, demandée explicitement, rend bien la sienne",
            enum_du_schema(BRAIN_POUR_EPREUVE, "agents"),
            ["active", "stable", "draft", "deprecated"])
    verifie("`pause` en fait partie — c'est elle que le docstring oubliait",
            "pause" in enum, True)
    verifie("la lecture d'une liste SQL retire les guillemets",
            valeurs("'planned','cadrage','dev'"), ["planned", "cadrage", "dev"])
    verifie("… et d'une liste Python aussi",
            valeurs('"planned", "cadrage"'), ["planned", "cadrage"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", type=Path, default=Path.home() / "Dev/Brain")
    args = ap.parse_args()
    brain = args.brain.expanduser().resolve()

    print("STATUTS CONFORMES — le `status:` d'une fiche est-il une valeur "
          "que la base accepte ?\n")

    enum = enum_du_schema(brain)
    if not enum:
        print("SKIP — énumération introuvable dans brain-engine/schema-dolt.sql")
        return 0
    print(f"  énumération (source : schema-dolt.sql) : {', '.join(enum)}\n")

    rouges = 0

    # ── 1. les declarations concordent-elles ? ───────────────────────────────
    code, doc = enum_du_migrateur(), enum_du_docstring()
    for nom, autre in (("ENUM de normalize_status.py", code),
                       ("docstring de normalize_status.py", doc)):
        if autre is None:
            print(f"  ⚪ {nom} : introuvable — non comparé")
        elif set(autre) != set(enum):
            rouges += 1
            manque = sorted(set(enum) - set(autre))
            trop = sorted(set(autre) - set(enum))
            print(f"  ❌ {nom} diverge du schéma")
            if manque:
                print(f"     · il ignore : {', '.join(manque)}")
            if trop:
                print(f"     · il invente : {', '.join(trop)}")
        else:
            print(f"  ✅ {nom} concorde")

    # ── 2. les fiches ───────────────────────────────────────────────────────
    print()
    hors, sans = [], []
    for nom, statut, typ in fiches(brain):
        if statut is None:
            if (typ or "").strip() not in TYPES_DISPENSES:
                sans.append((nom, typ))
            continue
        if statut not in enum:
            hors.append((nom, statut))

    if hors:
        rouges += 1
        print(f"  ❌ {len(hors)} fiche(s) hors énumération — la base les refusera :")
        for nom, statut in hors:
            print(f"     {nom:<34} status: {statut}")
        print("     La base ne s'en plaindra qu'au moment d'écrire, et le message")
        print("     qu'elle rend est « Data truncated », pas « valeur inconnue ».")
    else:
        print(f"  ✅ les {len(fiches(brain))} fiches portent un `status:` accepté")

    if sans:
        print(f"\n  ⚪ {len(sans)} fiche(s) sans `status:`, et sans `type:` qui en "
              f"dispense :")
        for nom, typ in sans[:6]:
            print(f"     {nom:<34} type: {typ or '(aucun)'}")
        print("     Ni un écart ni une dérive — le contrôle ne tranche pas seul")
        print("     si une fiche doit en porter un.")

    globals()['BRAIN_POUR_EPREUVE'] = brain
    auto_epreuve(enum)
    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    if not rouges and not _ko:
        # 🔴 Cette ligne est la DERNIERE `✅` du script, et le doctor resume
        # un controle vert par sa derniere ligne `✅`. Sans elle, il
        # affichait « … et d'une liste Python aussi » — le dernier test de
        # l'auto-epreuve, c'est-a-dire rien de lisible.
        # Le verdict dit ce qui a été COMPARÉ : chez un fork, le migrateur (un
        # outil d'instance) n'est pas là, et « les trois concordent » mentait
        # pour deux d'entre elles.
        comparees = 1 + sum(x is not None for x in (enum_du_migrateur(), enum_du_docstring()))
        quoi = ("les trois declarations de l'enumeration concordent" if comparees == 3
                else f"{comparees} declaration(s) sur trois comparee(s) concordent "
                     "(le migrateur, outil d'instance, est absent)")
        print(f"\n  ✅ {len(fiches(brain))} fiches conformes, et {quoi}")

    return 1 if (rouges or _ko) else 0


if __name__ == "__main__":
    sys.exit(main())
