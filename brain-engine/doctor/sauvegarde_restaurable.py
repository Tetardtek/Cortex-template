#!/usr/bin/env python3
"""La sauvegarde se recharge-t-elle ?

`brain-db-backup/` pèse 6,1 Go, tourne chaque jour à 4 h, commite et pousse.
Personne n'avait jamais rechargé un de ses dumps. Fait le 04/09 : **il s'arrête
à la troisième table**.

Une sauvegarde qu'on n'a jamais restaurée n'est pas une sauvegarde — c'est une
intention. Ce contrôle la met à l'épreuve.

    python3 tools/sauvegarde_restaurable.py --brain ~/Dev/Brain
    python3 tools/sauvegarde_restaurable.py --brain ~/Dev/Brain --reel

**Ce qu'il fait par défaut** : il extrait le SCHÉMA du dump le plus récent et
le rejoue vraiment dans un Dolt jetable. C'est rapide, et c'est là que le
premier défaut bloque — `dolt dump` exporte les défauts d'`enum` sous forme
d'INDEX (`DEFAULT '4'`) au lieu du littéral, et un rechargement les refuse.

Il compte aussi les valeurs `''` insérées dans des colonnes `enum` qui ne les
acceptent pas : c'est le second défaut, celui des données, et il ne se voit
qu'au chargement des `INSERT`.

**Ce qu'il ne fait pas, et il faut le dire** : le mode par défaut ne rejoue pas
les données — 42 Mo par dump, plusieurs minutes. Un schéma qui passe ne prouve
donc pas que le dump entier se recharge ; c'est `--reel` qui tranche, et il est
lent. Un contrôle qui laisse croire qu'il a tout vu ment par omission.

**Sauf si quelqu'un l'a déjà fait.** Depuis le 04/09, `brain-db-backup.sh`
recharge le dump ENTIER dans un magasin jetable au moment où il l'écrit, et
laisse un témoin — nom du fichier, empreinte SHA-256, nombre de tables, date.
Ce contrôle le lit et **recalcule l'empreinte** : si elle correspond, le vert
porte aussi sur les données ; sinon il le dit et retombe sur le schéma seul.
Une preuve qu'on ne confronte pas à son objet est une affirmation.

Sortie 1 si le dump n'est pas rechargeable.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEBUT_INSERT = re.compile(r"^\s*INSERT\s+INTO", re.I)
COLONNE_ENUM = re.compile(r"`(\w+)`\s+(enum\(([^)]*)\))((?:\s+NOT NULL)?)"
                          r"(?:\s+DEFAULT\s+'([^']*)')?", re.I)


def dernier_dump(racine: Path) -> Path | None:
    dossier = racine / "brain-db-backup"
    dumps = sorted(dossier.glob("brain-*.sql")) if dossier.is_dir() else []
    return dumps[-1] if dumps else None


TEMOIN = ".restauration-verifiee.json"

# Deux jours : la sauvegarde est quotidienne, donc un passage raté ne fait pas
# rougir, deux d'affilée si. Le seuil existe depuis — la sauvegarde
# tournait DEUX fois par jour, cron et timer systemd, et la ligne du crontab a
# été retirée le 06/09. La redondance qui masquait une panne de l'un des deux
# n'est plus là : il faut donc que la disparition se voie.
#
# Sans ce seuil, ce contrôle restait vert indéfiniment sur un dump de plus en
# plus vieux — il prend le plus récent et le recharge, sans jamais regarder sa
# date. Une sauvegarde qui a cessé reste parfaitement restaurable.
JOURS_MAX = 2


def temoin_de_restauration(dump: Path) -> tuple[bool, str]:
    """La preuve écrite par `brain-db-backup.sh` au moment où il a produit le
    dump — il rejoue les DONNÉES complètes, une fois, à l'écriture.

    Ce contrôle-ci ne rejoue que le schéma : deux minutes de restauration par
    jour n'ont pas leur place dans `brain doctor`. Il annonçait donc un vert
    plus étroit que ce qui avait réellement été éprouvé.

    Le témoin porte l'empreinte du dump. On la recalcule : un témoin qu'on ne
    confronte pas à son objet est une affirmation, pas une preuve. Si le dump a
    changé depuis, le témoin ne vaut rien et on le dit.
    """
    fichier = dump.parent / TEMOIN
    if not fichier.is_file():
        return False, "aucun témoin — la sauvegarde n'a pas éprouvé ses données"
    try:
        t = json.loads(fichier.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return False, f"témoin illisible ({e.__class__.__name__})"
    if t.get("fichier") != dump.name:
        return False, f"témoin d'un autre dump ({t.get('fichier')})"
    h = hashlib.sha256()
    with open(dump, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    if t.get("sha256") != h.hexdigest():
        return False, "le dump a changé depuis — le témoin ne le décrit plus"
    return True, (f"{t.get('tables', '?')} tables rejouées le "
                  f"{str(t.get('verifie_le', '?'))[:16]}")


def schema_seul(texte: str) -> str:
    """Tout ce qui n'est pas une ligne d'INSERT — donc le schéma et ses SET."""
    return "\n".join(l for l in texte.splitlines() if not DEBUT_INSERT.match(l))


def defauts_numeriques(texte: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(5)) for m in COLONNE_ENUM.finditer(texte)
            if m.group(5) and m.group(5).isdigit()]


def enums_sans_valeur_vide(texte: str) -> set[str]:
    """Colonnes `enum` dont l'énumération ne contient pas la chaîne vide."""
    sans = set()
    for m in COLONNE_ENUM.finditer(texte):
        valeurs = re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(3))
        if "" not in valeurs:
            sans.add(m.group(1))
    return sans


def rejoue(sql: str) -> tuple[bool, str]:
    """Rejoue du SQL dans un Dolt jetable. (réussi, première erreur)."""
    if not shutil.which("dolt"):
        return True, "dolt absent — rien n'a été rejoué"
    with tempfile.TemporaryDirectory(prefix="restaure-temoin-") as tmp:
        base = Path(tmp)
        subprocess.run(["dolt", "init", "-b", "main", "--name", "temoin",
                        "--email", "temoin@local"], cwd=base, capture_output=True)
        r = subprocess.run(["dolt", "sql"], cwd=base, input=sql,
                           capture_output=True, text=True, timeout=900)
        if r.returncode == 0:
            return True, ""
        sortie = (r.stderr or r.stdout).strip().splitlines()
        return False, (sortie[-1][:160] if sortie else "échec sans message")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--reel", action="store_true",
                   help="rejoue le dump ENTIER, données comprises (lent)")
    args = p.parse_args()

    racine = args.brain.expanduser().resolve()
    # Ce contrôle juge les dumps de `brain-db-backup.sh` — la sauvegarde de
    # l'instance, qui ne part pas au gabarit. Un brain qui n'a pas ce script n'a
    # rien à restaurer par lui : il s'abstient. Là où le script existe, un dump
    # absent ou vieilli reste rouge.
    if not (racine / "scripts" / "brain-db-backup.sh").is_file():
        print("SKIP scripts/brain-db-backup.sh absent — pas de sauvegarde de ce type à juger")
        return 0
    dump = dernier_dump(racine)
    if dump is None:
        print("\n  ❌ aucun dump dans brain-db-backup/ — il n'y a rien à "
              "restaurer.\n")
        return 1

    texte = dump.read_text(errors="replace")
    mo = dump.stat().st_size / 1e6
    age = (datetime.now() - datetime.fromtimestamp(dump.stat().st_mtime)).days
    print(f"\nSAUVEGARDE — {dump.name}, {mo:.0f} Mo, {age} jour(s)")

    if age > JOURS_MAX:
        print(f"\n  ❌ le dump le plus récent a {age} jours — la sauvegarde a cessé.")
        print(f"     Elle est quotidienne, et un seul ordonnanceur la porte depuis")
        print(f"     le 06/09 : `systemctl --user status brain-db-backup.timer`.")
        print("     Un dump qui ne vieillit pas ne prouve rien s'il ne se renouvelle plus.\n")
        return 1

    numeriques = defauts_numeriques(texte)
    stricts = enums_sans_valeur_vide(texte)
    vides = len(re.findall(r",''(?=[,)])", texte))

    print(f"\n  défauts d'enum exportés en index   {len(numeriques)}")
    print(f"  colonnes enum refusant ''          {len(stricts)}")
    print(f"  valeurs '' insérées (toutes col.)  {vides}")

    sql = texte if args.reel else schema_seul(texte)
    portee = "dump entier" if args.reel else "schéma seul"
    ok, erreur = rejoue(sql)
    print(f"\n  rejoué : {portee}")

    if not ok:
        print(f"\n  ❌ le dump ne se recharge pas.")
        print(f"     {erreur}")
        print("\n     Une sauvegarde qu'on n'a jamais rechargée n'est pas une")
        print("     sauvegarde, c'est une intention. Détail —.\n")
        return 1

    if not args.reel:
        print("  ✅ le schéma se recharge")
        atteste, quoi = temoin_de_restauration(dump)
        if atteste:
            print(f"  ✅ les données aussi — {quoi}")
            print("\n     Éprouvé à l'écriture par brain-db-backup.sh, pas ici :")
            print("     la preuve est produite une fois et confrontée à")
            print("     l'empreinte du dump, plutôt que refaite chaque jour.\n")
            return 0
        if vides and stricts:
            print(f"\n  ⚠️  {vides} valeurs '' restent à éprouver : seul `--reel`")
            print("     charge les données, et c'est là que le second défaut")
            print("     se manifeste. Ce vert ne couvre que le schéma.")
            print(f"     {quoi}.")
        print()
        return 0

    print("  ✅ le dump entier se recharge — données comprises\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
