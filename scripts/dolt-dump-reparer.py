#!/usr/bin/env python3
# brain-distribuable: oui  # dolt-schema-gen.sh l'importe
"""Rendre un `dolt dump` rechargeable.

`dolt dump` exporte les défauts d'`enum` sous forme d'**index interne** au lieu
du littéral :

    `tier` enum('always','hot','warm','cold') NOT NULL DEFAULT '4'
    → Invalid default value for 'tier'

Le dump ne se recharge pas. Aucun des trente dumps de `brain-db-backup/` ne le
faisait, depuis au moins le 04/08.

**La mise à jour de Dolt ne corrige pas ça — mesuré le 04/09.** Le défaut a été
reproduit à l'identique sur un magasin jetable en **1.84.0** (installée) et en
**2.3.2** (la dernière) : deux versions majeures d'écart, même sortie. Dolt
2.3.2 ne sait pas relire son propre dump. Le post-traitement n'est donc pas un
contournement en attendant mieux — c'est la seule voie connue.

── Deux réécritures, toutes deux sur le SCHÉMA ──────────────────────────────

    DEFAULT '4'  →  le littéral à l'index 4 de l'énumération
                    Correspondance exacte, sans perte : l'index EST la valeur.

    enum(…)      →  enum('', …) pour les seules colonnes de COLONNES_VIDES

Le second point mérite d'être justifié deux fois.

**Pourquoi assouplir plutôt que réécrire en NULL.** La base vivante contient
bien des `''` — `claims.handoff_level` en porte. Les réécrire en `NULL` serait
perdre de l'information, et une sauvegarde doit rendre ce qu'on lui a confié.

**Pourquoi une liste et non toutes les enums.** La première version assouplissait
les vingt-deux énumérations du schéma. Mesuré le 04/09 par essais successifs sur
le dump réel : **une seule** en a besoin. Les vingt-et-une autres étaient
assouplies pour rien — et une sauvegarde qui restaure un schéma *plus permissif*
que l'original n'est pas fidèle. Une sauvegarde infidèle dans le sens permissif
est la pire des deux : elle se recharge sans broncher, et la contrainte perdue
ne manque à personne avant le jour où elle aurait servi.

Si une autre colonne se met à porter des `''`, la restauration échouera et le
contrôle rougira. C'est voulu : mieux vaut un refus lisible qu'un assouplissement
silencieux. `--decouvrir` recalcule alors la liste, par essais successifs.

    python3 scripts/dolt-dump-reparer.py <dump.sql> [sortie.sql]
    python3 scripts/dolt-dump-reparer.py <dump.sql> --decouvrir

Sans `sortie.sql`, le dump est réécrit sur place.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Les colonnes `enum` qui portent des `''` en base. Mesurée, pas supposée :
# `--decouvrir` a trouvé celle-ci et seulement celle-ci sur le dump du 04/09,
# en repartant de zéro à chaque tour.
COLONNES_VIDES = ("handoff_level",)

DEFAUT = re.compile(
    r"(enum|set)\(([^)]*)\)((?:\s+(?:NOT NULL|NULL))?)\s+DEFAULT\s+'(\d+)'")
COLONNE = re.compile(r"(`(\w+)`\s+enum\()([^)]*)(\))", re.I)


def valeurs(bloc: str) -> list[str]:
    return re.findall(r"'((?:[^'\\]|\\.)*)'", bloc)


def reparer(texte: str, colonnes: tuple[str, ...]) -> tuple[str, int, int]:
    """Rend le SQL rechargeable. Ne touche à aucune donnée."""

    def litteral(m: re.Match) -> str:
        v, i = valeurs(m.group(2)), int(m.group(4))
        if not 1 <= i <= len(v):
            return m.group(0)
        return f"{m.group(1)}({m.group(2)}){m.group(3)} DEFAULT '{v[i - 1]}'"

    texte, n_def = DEFAUT.subn(litteral, texte)

    # `subn` compte les COÏNCIDENCES du motif, pas les réécritures. Le premier
    # jet annonçait « 22 énumérations assouplies » pour une seule changée : les
    # vingt-deux colonnes `enum` du schéma coïncident, vingt et une repartent
    # inchangées. Un compteur qui compte autre chose que ce qu'il annonce est
    # exactement le genre d'instrument qui a menti huit fois le 04/09.
    faites: list[str] = []

    def tolerer(m: re.Match) -> str:
        if m.group(2) not in colonnes or "" in valeurs(m.group(3)):
            return m.group(0)
        faites.append(m.group(2))
        return f"{m.group(1)}'',{m.group(3)}{m.group(4)}"

    texte = COLONNE.sub(tolerer, texte)
    # Une même colonne peut vivre dans plusieurs tables — `handoff_level` est
    # dans `claims` ET `claims_archive`. Le compte porte sur les colonnes
    # réécrites, pas sur les noms distincts.
    return texte, n_def, len(faites)


def rejoue(sql: Path, dolt: str) -> tuple[bool, str]:
    """Recharge vraiment le fichier dans un magasin jetable. Rien d'autre ne
    prouve qu'une sauvegarde est une sauvegarde."""
    bac = Path(tempfile.mkdtemp(prefix="dump-rejoue-"))
    try:
        subprocess.run([dolt, "init", "--name", "t", "--email", "t@t"],
                       cwd=bac, capture_output=True)
        with open(sql) as f:
            r = subprocess.run([dolt, "sql"], cwd=bac, stdin=f,
                               capture_output=True, text=True)
        err = ((r.stderr or "") + (r.stdout or "")).strip()
        return r.returncode == 0, err.splitlines()[0][:200] if err else ""
    finally:
        shutil.rmtree(bac, ignore_errors=True)


def decouvrir(brut: str, dolt: str, maxi: int = 25) -> list[str] | None:
    """La liste minimale, par essais successifs. Lent — une restauration
    complète par tour. À lancer quand le contrôle rougit, pas tous les jours."""
    trouvees: list[str] = []
    for tour in range(1, maxi + 1):
        texte, _, _ = reparer(brut, tuple(trouvees))
        bac = Path(tempfile.mkdtemp(prefix="decouverte-"))
        essai = bac / "essai.sql"
        try:
            essai.write_text(texte, encoding="utf-8")
            ok, err = rejoue(essai, dolt)
            if ok:
                print(f"  tour {tour} : ✅ restauration complète")
                return trouvees
            print(f"  tour {tour} : ❌ {err}")
            m = re.search(r"column '(\w+)'", err)
            col = m.group(1) if m else None
            if not col or col in trouvees:
                print(f"  → colonne non identifiée ou déjà traitée ({col})")
                return None
            trouvees.append(col)
            print(f"    → on assouplit `{col}` et on recommence")
        finally:
            shutil.rmtree(bac, ignore_errors=True)
    return None


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    src = Path(args[0])
    if not src.is_file():
        print(f"❌ introuvable : {src}")
        return 1

    dolt = shutil.which("dolt")
    if not dolt:
        print("❌ `dolt` introuvable dans le PATH — rien à vérifier avec.")
        return 1

    brut = src.read_text(errors="replace")

    if "--decouvrir" in args:
        print(f"DÉCOUVERTE — quelles enums ont besoin de '' dans {src.name}\n")
        trouvees = decouvrir(brut, dolt)
        if trouvees is None:
            print("\n  ❌ pas de liste stable — le dump porte autre chose.")
            return 1
        print(f"\n  liste minimale : {', '.join(trouvees) or 'aucune'}")
        if tuple(trouvees) != COLONNES_VIDES:
            print(f"  ⚠️  elle diffère de COLONNES_VIDES = {COLONNES_VIDES}")
            print("     Mettre à jour la constante en tête de ce fichier.")
            return 1
        print("  ✅ conforme à COLONNES_VIDES")
        return 0

    dst = Path(args[1]) if len(args) > 1 and not args[1].startswith("-") else src
    texte, n_def, n_enum = reparer(brut, COLONNES_VIDES)

    # Zéro défaut n'est pas forcément une bonne nouvelle : ça peut vouloir dire
    # que Dolt a été corrigé — auquel cas cette réparation n'a plus lieu d'être
    # et il faut le savoir — ou que le dump est tronqué. Dans les deux cas, se
    # taire serait le pire choix.
    if n_def == 0:
        print(f"  ℹ️  aucun défaut d'enum dans {src.name}.")
        print("     Soit Dolt exporte correctement — vérifier, et retirer cette")
        print("     étape ; soit le dump est incomplet. Ne pas ignorer.")

    dst.write_text(texte, encoding="utf-8")
    print(f"  {n_def} défauts d'enum réécrits en littéral")
    print(f"  {n_enum} colonne(s) enum assouplie(s) pour accueillir '' "
          f"— {', '.join(COLONNES_VIDES)}")
    print(f"  → {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
