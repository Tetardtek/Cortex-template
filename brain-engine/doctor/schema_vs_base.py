#!/usr/bin/env python3
"""Ce que `schema.sql` déclare existe-t-il vraiment ?

`CREATE TABLE IF NOT EXISTS` crée une table **absente**. Il ne migre jamais une
table **présente**. Une colonne ajoutée au fichier de schéma n'atteint donc
jamais une base déjà créée, et la déclaration devient fausse là où elle
s'exécute — sans que rien ne le dise.

Mesuré le 04/09 : `migrate.py` échouait **chaque jour** sur
`no such column: c.health_score`. En cherchant, ce n'était pas une colonne mais
**neuf**, toutes dans `claims`, déclarées depuis des mois et jamais créées.

C'est le motif de toute la journée — *la déclaration est juste quelque part, et
fausse là où elle s'exécute* — et c'est le seul cas où il est mesurable
mécaniquement : un fichier de schéma dit exactement ce qu'il attend.

    python3 tools/schema_vs_base.py --brain ~/Dev/Brain

Ce qu'il compare : les `CREATE TABLE` de `brain-engine/schema.sql` et ce que la
base SQLite porte réellement. Tables manquantes **et** colonnes manquantes.

Ce qu'il ne fait pas : migrer. Ajouter une colonne à une base est un geste qui
se décide — l'outil dit l'écart et donne l'`ALTER` à jouer, il ne le joue pas.

Sortie 1 si la base ne porte pas ce que le schéma déclare.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

TABLE = re.compile(r"CREATE TABLE(?: IF NOT EXISTS)? (\w+)\s*\((.*?)\n\);", re.S)
NON_COLONNES = {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}


def declare(schema: Path) -> dict[str, dict[str, str]]:
    """Les tables et colonnes que le fichier de schéma annonce."""
    tables: dict[str, dict[str, str]] = {}
    for m in TABLE.finditer(schema.read_text(encoding="utf-8")):
        colonnes: dict[str, str] = {}
        for ligne in m.group(2).splitlines():
            brut = ligne.strip().split("--")[0].strip().rstrip(",")
            m2 = re.match(r"^(\w+)\s+(.+)$", brut)
            if m2 and m2.group(1).upper() not in NON_COLONNES:
                colonnes[m2.group(1)] = m2.group(2).strip()
        tables[m.group(1)] = colonnes
    return tables


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()

    racine = args.brain.expanduser().resolve()
    base = racine / "brain.db"

    # ── Le schéma du MOTEUR, pas un schéma au hasard ─────────────────────────
    #
    # Il y en a deux, et ce ne sont PAS deux versions du même fichier — c'est ce
    # que j'ai cru le 04/09, à tort :
    #
    #     brain-engine/schema.sql   SQLite  · PRAGMA, AUTOINCREMENT, pas de backtick
    #     brain-dolt/schema.sql     MySQL   · backticks, dialecte Dolt
    #
    # Comparer le schéma SQLite à une base Dolt, c'est comparer deux choses
    # incomparables et appeler « vert » le fait qu'elles partagent des noms de
    # tables. Le contrôle lit désormais celui qui correspond au backend actif.
    #
    # Découvert en essayant de rejouer le fichier « complété » : `PRAGMA
    # journal_mode=WAL` — un fichier SQLite auquel j'avais ajouté des
    # `CREATE TABLE` MySQL. Rejouable dans aucun des deux moteurs.
    schema_sqlite = racine / "brain-engine" / "schema.sql"
    schema_dolt = racine / "brain-dolt" / "schema.sql"

    schema = schema_sqlite
    if not schema.is_file():
        print(f"\n  SKIP {schema.name} absent — rien à comparer.\n")
        return 0
    if not base.is_file():
        # « pas encore » etait vrai quand ce controle est ne, le 04/09 : la base
        # SQLite pouvait manquer sur une instance neuve. Depuis le 06/09 elle
        # peut aussi avoir ete RETIREE — `brain.db` ne detenait plus rien que
        # Dolt n'ait pas. Un message qui suppose l'avenir laisse
        # croire a une installation en cours la ou il y a eu une decision.
        print(f"\n  SKIP {base.name} absent — ce controle ne mesure que SQLite.")
        print("     Soit l'instance est neuve, soit le repli a ete retire")
        print("    . Sur un backend Dolt, c'est `schema versionné`")
        print("     et `Dolt vs disque` qui portent la garantie.\n")
        return 0

    attendu = declare(schema)

    # ── Quelle base ? Celle que le brain LIT ──────────────────────────────────
    #
    # Ce contrôle interrogeait `brain.db` (SQLite). Depuis la bascule vers Dolt,
    # il mesurait donc le schéma d'une base que plus personne n'utilise — même
    # défaut que, et il restait vert pour cette seule raison. Mesuré le
    # 04/09 : `brain.db` porte 9 tables, Dolt en porte 29.
    #
    # Repli sur SQLite si le moteur est indisponible : mieux vaut mesurer la
    # mauvaise base en le disant que ne rien mesurer du tout.
    sys.path.insert(0, str(racine / "brain-engine"))
    colonnes_de = None
    try:
        import db as moteur
        if moteur.BACKEND == "sqlite":
            raise RuntimeError("backend sqlite")
        presentes = {list(r.values())[0] for r in moteur.query("SHOW TABLES")}
        vues = {list(r.values())[0] for r in moteur.query(
            "SHOW FULL TABLES WHERE table_type = 'VIEW'")}
        presentes -= vues
        ou = f"`{moteur.BACKEND}`"
        if moteur.BACKEND == "dolt" and schema_dolt.is_file():
            schema = schema_dolt
            attendu = declare(schema)

        def colonnes_de(table: str) -> set[str]:
            return {r["Field"] for r in moteur.query(f"DESCRIBE `{table}`")}
    except Exception:                                      # noqa: BLE001
        c = sqlite3.connect(str(base))
        presentes = {t for (t,) in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        ou = "brain.db (SQLite) — le moteur n'a pas répondu"

        def colonnes_de(table: str) -> set[str]:
            return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}

    tables_absentes = sorted(set(attendu) - presentes)
    colonnes_absentes: dict[str, list[str]] = {}
    for table, colonnes in attendu.items():
        if table not in presentes:
            continue
        reelles = colonnes_de(table)
        manquantes = [nom for nom in colonnes if nom not in reelles]
        if manquantes:
            colonnes_absentes[table] = manquantes

    total = sum(len(v) for v in colonnes_absentes.values())
    print(f"\nSCHÉMA vs BASE — {schema.relative_to(racine)} → {ou}")
    print(f"  {len(attendu)} tables déclarées, {len(presentes)} présentes")
    print(f"\n  tables déclarées et absentes    {len(tables_absentes)}")
    print(f"  colonnes déclarées et absentes  {total}"
          f"{f' dans {len(colonnes_absentes)} table(s)' if total else ''}")

    # ── Le second sens, en avertissement ─────────────────────────────────────
    #
    # `niveaux.py` vérifie les deux sens depuis le 03/09 : ce qui existe doit
    # être déclaré, ET ce qui est déclaré doit exister. Ce contrôle-ci ne voyait
    # que le second. Mesuré le 04/09 : `brain-engine/schema.sql` déclare huit
    # tables, la base vivante en porte vingt-neuf. Le fichier versionné est un
    # fossile ; le schéma réel vit dans `brain-dolt/schema.sql`, qui est
    # **gitignoré** — la déclaration de référence n'est donc pas versionnée.
    #
    # AVERTISSEMENT et non erreur, délibérément : faire rougir sur vingt et une
    # tables fabriquerait un rouge permanent que personne ne peut verdir dans la
    # séance, et c'est un piège déjà vu. Il est chiffré, visible,
    # et il attend un chantier —.
    non_declarees = sorted(presentes - set(attendu))
    if non_declarees:
        print(f"  présentes et NON déclarées      {len(non_declarees)}  "
              f"⚠️  non bloquant —")

    if not tables_absentes and not total:
        print("\n  ✅ la base porte ce que le schéma déclare")
        if non_declarees:
            apercu = ", ".join(non_declarees[:6])
            print(f"     ⚠️  mais {len(non_declarees)} tables ne sont déclarées")
            print(f"         nulle part : {apercu}…")
            print(f"         Et {schema.relative_to(racine)} est "
                  f"{'gitignoré' if 'brain-dolt' in str(schema) else 'versionné'}.")
        print()
        return 0

    for t in tables_absentes:
        print(f"\n  ❌ table absente : {t}")
    for table, manquantes in sorted(colonnes_absentes.items()):
        print(f"\n  ❌ {table} — {len(manquantes)} colonne(s) déclarée(s) et absente(s) :")
        for nom in manquantes:
            typ = attendu[table][nom].split("DEFAULT")[0].replace("NOT NULL", "").strip()
            print(f"       ALTER TABLE {table} ADD COLUMN {nom} {typ};")

    print("\n     `CREATE TABLE IF NOT EXISTS` ne migre pas une table présente :")
    print("     une colonne ajoutée au schéma n'atteint jamais une base déjà")
    print("     créée. L'outil donne l'`ALTER` — il ne le joue pas, parce que")
    print("     toucher au schéma d'une base est un geste qui se décide.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
