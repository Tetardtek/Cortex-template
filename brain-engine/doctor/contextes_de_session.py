#!/usr/bin/env python3
"""Ce qu'un boot charge existe-t-il encore ?

Un contexte de session déclare, couche par couche, les fichiers à charger au
démarrage. Quand l'un d'eux disparaît — un ménage, un renommage — **rien ne
casse** : le boot charge ce qu'il trouve et se tait. La session démarre avec
moins de contexte qu'annoncé, l'agent raisonne sur une carte incomplète, et
personne ne l'apprend avant de constater qu'il ignore quelque chose qu'il
devrait savoir.

C'est la démyélinisation dans sa forme la plus pure, et à l'endroit le plus
coûteux : le boot conditionne tout le reste de la séance.

Ce contrôle est né après le retrait de onze vestiges le 03/09 : la
question « est-ce qu'on vient de casser un boot ? » n'avait aucune réponse
outillée. Elle en a une.

    python3 tools/contextes_de_session.py --brain ~/Dev/Brain

Ce qu'il vérifie :

    L0, L1        chaque fichier déclaré existe
    L2            les motifs portent `{project}` — on vérifie le RÉPERTOIRE,
                  pas le fichier : il dépend du projet en cours
    L0 unanime    les six types partent du MÊME socle — un L0 qui diverge
                  n'est plus un niveau zéro, c'est une préférence
    complément    `instance/contexts/session-<type>.complement.yml` — ce que
                  l'instance AJOUTE au boot d'un type : ses fichiers existent,
                  comme ceux du manifest ; il ne porte que ce que le boot en lit
                  (`L1`, `L2.extras`) ; il complète un type qui existe. Une clé
                  de plus, ou un type inconnu, serait lu nulle part, sans que
                  rien le dise
    règles        `instance/specs/` — seul `collaboration.complement.md` y est
                  lu (au boot, après `profil/specs/collaboration.md`) ; tout
                  autre fichier, une surcharge par exemple, ne l'est nulle part
                 

Ce qu'il ne compte pas comme manquant : un fichier d'un SATELLITE — un dossier que
`NIVEAUX.yml` déclare `versionne: depot-separe`. C'est de la donnée, pas du
programme : `handoffs/LATEST.md` n'existe pas chez un fork neuf tant qu'il n'a
pas écrit son premier handoff, et le gabarit ne doit pas le livrer (un fichier
livré à ce chemin écraserait le sien). Il est dit, pas compté.

Ce qu'il ne vérifie pas, et le dit : que le fichier chargé ait le bon contenu,
ni que les six types de session soient les bons. Un contrôle doit annoncer sa
portée, sinon il rassure au-delà de ce qu'il a regardé.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MOTIF = re.compile(r"\{[a-z_]+\}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()

    racine = args.brain.expanduser().resolve()
    dossier = racine / "contexts"
    if not dossier.is_dir():
        print("\n  ❌ contexts/ introuvable — aucun type de session déclaré.\n")
        return 1

    import yaml

    fichiers = sorted(dossier.glob("session-*.yml"))
    if not fichiers:
        print("\n  ❌ aucun contexts/session-*.yml — le boot n'est déclaré nulle "
              "part.\n")
        return 1

    manquants: list[tuple[str, str, str]] = []
    a_ecrire: list[tuple[str, str, str]] = []
    niveaux = racine / "NIVEAUX.yml"
    entrees = ((yaml.safe_load(niveaux.read_text(encoding="utf-8")) or {}).get("entrees") or {}
               if niveaux.is_file() else {})
    satellites = {n.rstrip("/") for n, v in entrees.items()
                  if isinstance(v, dict) and v.get("versionne") == "depot-separe"}
    comptes = 0
    socles: dict[str, tuple] = {}

    def juger(nom: str, d: dict) -> None:
        """Chaque fichier qu'un manifest — ou un complément — fait charger."""
        nonlocal comptes
        for niveau in ("L0", "L1"):
            for ref in d.get(niveau) or []:
                if not isinstance(ref, str):
                    continue
                comptes += 1
                if not (racine / ref).exists():
                    (a_ecrire if ref.split("/")[0] in satellites else manquants).append((nom, niveau, ref))

        l2 = d.get("L2")
        if isinstance(l2, dict):
            refs = [l2.get("template"), *(l2.get("extras") or [])]
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                comptes += 1
                # `todo/{project}.md` — le fichier dépend du projet, le
                # répertoire non. C'est le répertoire qui doit exister.
                #
                # Premier jet : `(racine / "todo/").parent`, qui vaut la racine —
                # le contrôle ne pouvait alors PAS rougir sur un template. C'est
                # le témoin négatif qui l'a dit, pas la lecture du code.
                if MOTIF.search(ref):
                    cible = racine / MOTIF.split(ref)[0].rstrip("/")
                else:
                    cible = racine / ref
                if not cible.exists():
                    manquants.append((nom, "L2", ref))

    for f in fichiers:
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            manquants.append((f.name, "—", f"YAML illisible : {exc}"))
            continue

        socles[f.stem] = tuple(d.get("L0") or [])
        juger(f.name, d)

    # Le complément de l'instance : il s'ajoute au boot du type.
    types = {f.name[len("session-"):-len(".yml")] for f in fichiers}
    complements = sorted((racine / "instance" / "contexts").glob("session-*.complement.yml"))
    for f in complements:
        nom = f"instance/contexts/{f.name}"
        type_ = f.name[len("session-"):-len(".complement.yml")]
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            manquants.append((nom, "—", f"YAML illisible : {exc}"))
            continue
        if not isinstance(d, dict):
            manquants.append((nom, "—", "ni L1 ni L2 : ce n'est pas un mapping"))
            continue
        if type_ not in types:
            manquants.append((nom, "—", f"complète un type qui n'existe pas (contexts/session-{type_}.yml) "
                                        "— lu nulle part"))
        hors = sorted(set(d) - {"L1", "L2"})
        l2 = d.get("L2")
        if isinstance(l2, dict):
            hors += [f"L2.{k}" for k in sorted(set(l2) - {"extras"})]
        elif l2 is not None:
            hors.append("L2")
        if hors:
            manquants.append((nom, "—", f"{', '.join(hors)} : le boot ne lit d'un complément "
                                        "que L1 et L2.extras"))
        juger(nom, d)

    # Les règles de travail de l'instance : un seul fichier est lu.
    LUES = "collaboration.complement.md"
    specs = racine / "instance" / "specs"
    regles = (specs / LUES).is_file()
    if specs.is_dir():
        for f in sorted(specs.rglob("*")):
            rel = f.relative_to(specs)
            if (f.is_file() and str(rel) not in (LUES, "README.md")
                    and not any(x.startswith(".") for x in rel.parts)):
                manquants.append((f"instance/specs/{rel}", "—",
                                  f"lu nulle part : seul instance/specs/{LUES} s'ajoute aux règles"))

    print(f"\nCONTEXTES — {len(fichiers)} types de session, "
          + (f"{len(complements)} complément(s) de l'instance, " if complements else "")
          + ("ses règles de travail, " if regles else "")
          + f"{comptes} fichiers déclarés au boot")

    # `L0` n'est pas « tout ce qui est toujours chargé » — CLAUDE.md s'en charge
    # et les deux s'additionnent. `L0` est ce que le TYPE ajoute avant tout le
    # reste, et c'est pour ça qu'il doit être le MÊME pour tous : un socle qui
    # varie selon le type n'est plus un socle.
    formes = set(socles.values())
    if len(formes) > 1:
        print(f"\n  ❌ {len(formes)} socles L0 différents pour {len(socles)} types :")
        for forme in sorted(formes, key=len):
            qui = sorted(k for k, v in socles.items() if v == forme)
            print(f"       {', '.join(qui)}")
            print(f"         → {list(forme)}")
        print("\n     Un L0 qui diverge n'est plus un niveau zéro : c'est une")
        print("     préférence de type, et elle a sa place en L1.\n")
        return 1
    print(f"  ✅ socle L0 unanime — {list(next(iter(formes))) if formes else []}")

    if a_ecrire:
        print(f"  ⓘ {len(a_ecrire)} donnée(s) de satellite pas encore écrite(s) — "
              + ", ".join(sorted({r for _, _, r in a_ecrire})))
    if manquants:
        print(f"\n  ❌ {len(manquants)} déclaré(s) et introuvable(s) :")
        for nom, niveau, ref in manquants:
            print(f"       {nom:24} {niveau:3} → {ref}")
        print("\n     Le boot ne casse pas là-dessus : il charge ce qu'il trouve")
        print("     et se tait. La session démarre avec moins que ce qui est")
        print("     annoncé, et rien ne le dit.\n")
        return 1

    print("  ✅ tout ce qu'un boot déclare charger existe\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
