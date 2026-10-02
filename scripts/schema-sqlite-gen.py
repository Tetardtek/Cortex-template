#!/usr/bin/env python3
# brain-distribuable: oui  # un fork qui change son schéma Dolt régénère son repli
"""`schema.sql` dérivé de `schema-dolt.sql` — une source, deux dialectes.

Mesuré le 06/09 : `schema.sql` déclarait **8 tables**, `schema-dolt.sql` en
déclare **29**. Les huit étaient un sous-ensemble strict — aucune divergence,
mais vingt et une absentes. Et parmi les huit, `agent_memory` et `agent_loads`,
les deux tables mortes : zéro ligne, zéro écrivain en cinq mois.

Un fork qui démarre sans Dolt recevait donc un moteur amputé — ni `agents`
(20 lecteurs), ni `embeddings` (12), ni `decisions` (9), ni `projects` (6).
Pas de RAG, pas de catalogue.

**Tranché le 06/09** : un fork reçoit toutes les tables, aucune donnée.

    python3 scripts/schema-sqlite-gen.py            # écrit brain-engine/schema.sql
    python3 scripts/schema-sqlite-gen.py --montrer  # affiche sans écrire

── Pourquoi générer plutôt que corriger ────────────────────────────────────

Corriger à la main aurait tenu jusqu'à la prochaine table. Deux déclarations du
même schéma finissent toujours par diverger : trois fois déjà, le même motif.
`schema-dolt.sql` est lui-même généré depuis la base
par `dolt-schema-gen.sh` : la chaîne devient **base → schema-dolt.sql →
schema.sql**, une seule source à l'origine.

⚠️ **Les six VUES ne sont pas générées.** Elles sont écrites à la main des deux
côtés « parce qu'elles portent leur raisonnement », et celles de SQLite sont
déjà adaptées à son dialecte. Ce script les **reprend telles quelles** depuis le
`schema.sql` existant. Une source chacun.

⚠️ **Aucun `DROP TABLE`.** `schema-dolt.sql` en porte 29 — c'est un dump, il
recrée. `schema.sql` est joué à CHAQUE initialisation par `migrate.py` : un DROP
y effacerait les données du fork à chaque démarrage. `CREATE TABLE IF NOT
EXISTS`, et rien d'autre.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SOURCE = RACINE / "brain-engine" / "schema-dolt.sql"
CIBLE = RACINE / "brain-engine" / "schema.sql"

# MySQL → SQLite. SQLite a une affinité de type souple, mais écrire `varchar`
# dans un fichier SQLite laisserait croire à une largeur qu'il n'applique pas.
TYPES = [
    (r"\bvarchar\(\d+\)", "TEXT"),
    (r"\b(long|medium|tiny)?text\b", "TEXT"),
    (r"\bdatetime\b", "TEXT"),
    (r"\bjson\b", "TEXT"),
    (r"\btimestamp\b", "TEXT"),
    (r"\btinyint(\(\d+\))?\b", "INTEGER"),
    (r"\bbigint(\(\d+\))?\b", "INTEGER"),
    (r"\bint(\(\d+\))?\b", "INTEGER"),
    (r"\bdouble\b", "REAL"),
    (r"\bfloat\b", "REAL"),
    (r"\bdecimal\([\d,]+\)", "REAL"),
]

COLONNE_ENUM = re.compile(r"^\s*`(?P<col>\w+)`\s+enum\((?P<vals>[^)]*)\)(?P<suite>.*)$")
LIGNE_KEY = re.compile(r"^\s*(UNIQUE\s+)?KEY\s+`(?P<nom>\w+)`\s+\((?P<cols>[^)]*)\)")
LIGNE_PK = re.compile(r"^\s*PRIMARY KEY\s+\(`(?P<col>\w+)`\)")


def traduire_table(bloc: list[str], table: str) -> tuple[list[str], list[str]]:
    """Un `CREATE TABLE` MySQL vers SQLite. Rend le corps et les index à part."""
    sortie: list[str] = [f"CREATE TABLE IF NOT EXISTS {table} ("]
    index: list[str] = []
    colonnes: list[str] = []
    auto: str | None = None

    for ligne in bloc:
        if "AUTO_INCREMENT" in ligne:
            m = re.match(r"\s*`(\w+)`", ligne)
            if m:
                auto = m.group(1)
                colonnes.append(f"    {auto} INTEGER PRIMARY KEY AUTOINCREMENT")
                continue

        m = LIGNE_KEY.match(ligne)
        if m:
            cols = m.group("cols").replace("`", "")
            if m.group(1):                    # UNIQUE KEY → contrainte de table
                colonnes.append(f"    UNIQUE ({cols})")
            else:                             # KEY → index séparé en SQLite
                index.append(f"CREATE INDEX IF NOT EXISTS "
                             f"{table}_{m.group('nom')} ON {table} ({cols});")
            continue

        m = LIGNE_PK.match(ligne)
        if m:
            # La clé primaire de la colonne auto-incrémentée est déjà portée
            # par `INTEGER PRIMARY KEY AUTOINCREMENT` — la redéclarer est une
            # erreur de syntaxe en SQLite.
            if m.group("col") != auto:
                colonnes.append(f"    PRIMARY KEY ({m.group('col')})")
            continue

        m = COLONNE_ENUM.match(ligne)
        if m:
            col, vals = m.group("col"), m.group("vals")
            suite = m.group("suite").rstrip(",").strip()
            # SQLite n'a pas d'enum. Un TEXT nu perdrait la contrainte — et
            # c'est précisément l'enum qui a produit trois défauts le 05/09.
            # `CHECK` la garde, et accepte NULL comme MySQL sur colonne nullable.
            colonnes.append(f"    {col} TEXT {suite} "
                            f"CHECK ({col} IS NULL OR {col} IN ({vals}))".rstrip())
            continue

        m = re.match(r"^\s*`(\w+)`\s+(.*?),?\s*$", ligne)
        if m:
            col, reste = m.group(1), m.group(2)
            for motif, vers in TYPES:
                reste = re.sub(motif, vers, reste, flags=re.IGNORECASE)
            colonnes.append(f"    {col} {reste}")

    sortie.append(",\n".join(colonnes))
    sortie.append(");")
    return sortie, index


def vues_existantes() -> list[str]:
    """Les vues du `schema.sql` actuel, reprises telles quelles."""
    if not CIBLE.is_file():
        return []
    texte = CIBLE.read_text(encoding="utf-8")
    i = texte.find("CREATE VIEW")
    if i < 0:
        return []
    # On remonte au commentaire qui introduit la section, s'il existe.
    debut = texte.rfind("\n-- ", 0, i)
    return [texte[debut + 1:].rstrip()]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--montrer", action="store_true", help="affiche sans écrire")
    p.add_argument("--check", action="store_true",
                   help="sortie 1 si le fichier a dérivé de sa source")
    args = p.parse_args()

    if not SOURCE.is_file():
        print(f"\n  ❌ {SOURCE.name} introuvable — rien à dériver.\n")
        return 1

    texte = SOURCE.read_text(encoding="utf-8")
    tables: list[str] = []
    index: list[str] = []
    n = 0
    for m in re.finditer(r"CREATE TABLE `(\w+)` \(\n(.*?)\n\) ENGINE=[^;]*;",
                         texte, re.DOTALL):
        corps, idx = traduire_table(m.group(2).splitlines(), m.group(1))
        tables.append("\n".join(corps))
        index.extend(idx)
        n += 1

    if not n:
        print("\n  ❌ aucune table lue — le format de la source a changé.\n")
        return 1

    vues = vues_existantes()
    rendu = "\n".join([
        "-- brain-engine/schema.sql — le schéma du repli SQLite.",
        "--",
        "-- ⚠️  GÉNÉRÉ par scripts/schema-sqlite-gen.py — ne pas éditer à la main.",
        "--     Source : schema-dolt.sql, lui-même généré depuis la base.",
        "--     La chaîne est base → schema-dolt.sql → schema.sql : une seule",
        "--     déclaration à l'origine. Éditer ici la ferait diverger.",
        "--",
        "-- Toutes les tables, aucune donnée — tranché par l'owner le 06/09 : un fork",
        "-- reçoit tous les modules qu'on propose, vierges.",
        "--",
        "-- Les VUES sont écrites à la main et reprises telles quelles : elles",
        "-- portent leur raisonnement, et celles-ci sont déjà en dialecte SQLite.",
        "",
        "PRAGMA journal_mode=WAL;  -- lectures concurrentes sûres (multi-sessions)",
        "PRAGMA foreign_keys=ON;",
        "",
        f"-- ── {n} tables ─────────────────────────────────────────────────────",
        "",
        "\n\n".join(tables),
        "",
        f"-- ── {len(index)} index ─────────────────────────────────────────────",
        "",
        "\n".join(index),
        "",
        *vues,
        "",
    ])

    if args.montrer:
        print(rendu)
        return 0

    if args.check:
        # Le pendant de `dolt-schema-gen.sh --check`, et la raison d'être de ce
        # mode : une garantie que rien ne vérifie n'en est pas une. Sans lui, la
        # prochaine table ajoutée à la base entrerait dans `schema-dolt.sql` par
        # le générateur Dolt, et jamais dans `schema.sql` — on aurait déplacé la
        # divergence au lieu de la supprimer.
        # ⚠️ On ne compare QUE la part générée — tables et index.
        #
        # `vues_existantes()` relit la cible pour en reprendre les vues et les
        # réinjecte dans `rendu` : comparer les fichiers entiers ferait comparer
        # le contrôle à sa propre lecture. Mesuré en posant le témoin — une ligne
        # ajoutée à la main après les vues passait pour conforme. Un contrôle qui
        # relit sa propre sortie ne mesure rien.
        #
        # Et c'est aussi le bon périmètre : les vues sont écrites à la main, les
        # éditer est légitime. Ce qui ne doit pas dériver, c'est ce qui est dérivé.
        def part_generee(texte: str) -> str:
            i = texte.find("CREATE VIEW")
            return texte if i < 0 else texte[:texte.rfind("\n-- ", 0, i) + 1]

        actuel = CIBLE.read_text(encoding="utf-8") if CIBLE.is_file() else ""
        if part_generee(actuel) == part_generee(rendu):
            print(f"\n  ✅ schema.sql dérive bien de schema-dolt.sql — "
                  f"{n} tables, {len(index)} index")
            print("     Les vues sont écrites à la main : hors périmètre.\n")
            return 0
        print(f"\n  ❌ `schema.sql` a dérivé de `schema-dolt.sql`.")
        print(f"     La source déclare {n} tables ; le fichier ne les porte plus")
        print("     toutes, ou a été édité à la main.")
        print("     `python3 scripts/schema-sqlite-gen.py` le régénère.\n")
        return 1

    CIBLE.write_text(rendu, encoding="utf-8")
    print(f"\n  ✅ {CIBLE.relative_to(RACINE)} — {n} tables, {len(index)} index, "
          f"{len(vues)} bloc(s) de vues repris\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
