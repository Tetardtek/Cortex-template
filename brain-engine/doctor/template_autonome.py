#!/usr/bin/env python3
"""Le template tient-il debout tout seul ?

Le brain ne peut pas voir ce défaut sur lui-même. Chez lui, `db.py` est là,
les 29 tables sont là, tout importe et tout résout. Le fork, lui, ne reçoit
que `brain-template/` — et si le sync n'a embarqué qu'une moitié, personne
ici ne s'en aperçoit. C'est le motif retourné du chantier : **le code est
juste ici, et faux chez celui qui n'a pas Dolt**.

Mesuré le 05/09 puis le 07/09 : le template livre 4 fichiers de moteur avec
1 364 lignes de retard, sans `db.py`, et son schéma déclare 8 tables contre
29. Rien de tout cela ne le casse — il parle `sqlite3` en dur, il n'importe
pas `db`, et **il n'interroge aucune des 19 tables qui lui manquent**. Il est
en retard, pas cassé, et la nuance décide de l'urgence.

    python3 tools/template_autonome.py --brain ~/Dev/Brain

**Ce que ce contrôle vérifie.** Pas « le template est-il à jour » — un retard
voulu est légitime, et un contrôle qui rougit sur un choix ne protège plus
rien (,). Il vérifie la seule chose qui casse vraiment chez le
fork, et qui est vraie aujourd'hui :

    rien de ce que le template interroge ne manque au template
    rien de ce qu'il importe n'est absent de ce qu'il livre

Ces deux garanties sont vertes ce soir et le resteront tant que le sync est
cohérent. Elles rougissent au premier sync partiel — le cas exact où
`search.py` arriverait sans `db.py`.

**Trois versions précédentes étaient fausses**, et c'est l'enseignement.

Comparer aux seules tables de `schema.sql` faisait rougir `embeddings` :
absente du schéma du template, mais créée à la volée par `embed.py`. Un rouge
sur une chose qui marche.

Chercher `CREATE TABLE` dans tout le brain rendait 94 créateurs pour
`claims`, dont un dump de `brain-db-backup/`. Un dump n'installe rien chez
personne : le vert était acquis d'avance, et **un contrôle qui ne peut pas
rougir ne mesure rien**.

Exiger la parité template/engine, enfin, aurait produit un rouge permanent de
19 tables sur un périmètre assumé.

**Ce qu'il ne dit pas** : que le template est complet, ni qu'il fonctionne. Un
module peut s'importer et échouer à l'exécution. Ce contrôle regarde les
frontières déclarées, pas le comportement — la parité fonctionnelle est
mesurée ailleurs, par `bench/parite_portes.py`.

Sortie 1 si le template dépend de quelque chose qu'il ne livre pas.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# TABLE **et** VIEW. Une vue est un objet interrogeable comme un autre, et
# n'en chercher qu'un type déclarait orphelines les trois `v_*` de
# `migrate.py` — pourtant créées vingt lignes plus haut dans le même schéma.
# Quatrième fois de la soirée où l'instrument accuse le sujet à tort.
CREATEUR = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?`?([a-z_][a-z0-9_]*)`?",
    re.IGNORECASE)

USAGE = re.compile(
    r"\b(?:FROM|INTO|UPDATE|JOIN)\s+`?([a-z_][a-z0-9_]*)`?", re.IGNORECASE)

# Elles existent sans qu'un schéma les crée. Les compter ferait rougir des
# requêtes parfaitement justes.
# `mysql` : le schéma système des comptes et des droits, que tout serveur Dolt
# porte — `SELECT … FROM mysql.user` lit `mysql` en tête. Le test des droits
# du laptop (BRAIN-078) a fait rougir le contrôle le 29/09, le jour où il est
# parti avec le gabarit (v2.4.0).
SYSTEME = {"information_schema", "mysql", "sqlite_master", "sqlite_sequence",
           "dolt_status", "dolt_log", "dolt_branches", "dual"}

# Un mot réservé n'est jamais une table : `DO UPDATE SET`, `INSERT INTO … VALUES`,
# et `BEFORE UPDATE OF <colonne>` d'un déclencheur — lu « table of » le 28/09.
RESERVES = {"set", "select", "where", "values", "key", "table", "into", "from",
            "order", "group", "limit", "using", "on", "of"}

# Les fonctions-tables de SQLite : `FROM pragma_table_info(t)` interroge le
# moteur, pas le schéma (28/09). Reconnues par leur NOM, pas par la parenthèse
# qui suit : `INSERT INTO claims (a, b)` est une vraie table.
def fonction_table(nom: str) -> bool:
    return nom.startswith("pragma_") or nom in {"json_each", "json_tree"}

# La bibliothèque standard et les dépendances tierces ne sont pas au template :
# leur absence du dossier ne prouve rien. On ne juge que les modules LOCAUX,
# c'est-à-dire ceux que le brain, lui, livre dans son propre `brain-engine/`.
def modules_locaux(moteur: Path) -> set[str]:
    return {f.stem for f in moteur.glob("*.py")}


def fichiers(racine: Path) -> list[Path]:
    return [f for f in racine.rglob("*.py")
            if not any(p in f.parts
                       for p in (".git", "node_modules", "__pycache__"))]


def tables_creees(racine: Path) -> set[str]:
    vues: set[str] = set()
    for f in list(racine.rglob("*.sql")) + fichiers(racine):
        try:
            vues |= {t.lower()
                     for t in CREATEUR.findall(f.read_text(encoding="utf-8",
                                                           errors="ignore"))}
        except OSError:
            continue
    return vues


def tables_interrogees(racine: Path) -> dict[str, set[str]]:
    """Les tables citées dans une requête, par fichier.

    On lit l'ARBRE, pas le texte : seules comptent les chaînes passées en
    argument à `query`, `execute` et leurs semblables. Chercher `FROM x` dans
    le source ramasse `from dataclasses import`, y compris cité dans une
    docstring — trois regex ont échoué là-dessus avant qu'on change
    d'instrument.
    """
    PORTES = {"query", "query_one", "execute", "executemany", "count",
              "cursor", "fetchall"}
    par_fichier: dict[str, set[str]] = {}

    def morceaux(noeud) -> list[str]:
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            return [noeud.value]
        if isinstance(noeud, ast.JoinedStr):
            return [v.value for v in noeud.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        if isinstance(noeud, ast.BinOp):
            return morceaux(noeud.left) + morceaux(noeud.right)
        return []

    for f in fichiers(racine):
        try:
            arbre = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, OSError):
            continue
        trouvees: set[str] = set()
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            nom = (noeud.func.attr if isinstance(noeud.func, ast.Attribute)
                   else getattr(noeud.func, "id", ""))
            if nom not in PORTES:
                continue
            for arg in noeud.args:
                for texte in morceaux(arg):
                    trouvees |= {m.lower() for m in USAGE.findall(texte)}
        trouvees = {t for t in trouvees - SYSTEME - RESERVES if not fonction_table(t)}
        if trouvees:
            par_fichier[str(f.relative_to(racine))] = trouvees
    return par_fichier


def imports_locaux(racine: Path, connus: set[str]) -> dict[str, set[str]]:
    """Les modules locaux importés, par fichier — hors stdlib et tiers."""
    par_fichier: dict[str, set[str]] = {}
    for f in fichiers(racine):
        try:
            arbre = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, OSError):
            continue
        vus: set[str] = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                vus |= {a.name.split(".")[0] for a in noeud.names}
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                vus.add(noeud.module.split(".")[0])
        vus &= connus
        if vus:
            par_fichier[str(f.relative_to(racine))] = vus
    return par_fichier


#: L'auto-épreuve, rejouée à chaque passage. Les deux premiers cas sont ceux qui
#: faisaient rougir le contrôle à tort le 28/09, copiés mot pour mot du brain ;
#: les deux derniers vérifient qu'il voit toujours une vraie table manquante.
EPREUVE = (
    ("UPDATE OF <colonne> d'un déclencheur n'est pas une table",
     'con.execute("CREATE TRIGGER mur BEFORE UPDATE OF result ON claims "\n'
     '            "BEGIN SELECT RAISE(ABORT, \'x\'); END")\n', set()),
    ("pragma_table_info(...) est une fonction de SQLite",
     'db.query_one("SELECT COUNT(*) AS n FROM pragma_table_info(%s) '
     'WHERE name = %s", (t, c))\n', set()),
    ("une vraie table interrogée est vue",
     'db.execute("SELECT * FROM fantome WHERE id = 1")\n', {"fantome"}),
    ("INSERT INTO t (colonnes) reste une table",
     'db.execute("INSERT INTO claims (a, b) VALUES (?, ?)", (1, 2))\n', {"claims"}),
    # L'incident du 29/09, mot pour mot : le schéma système des comptes.
    ("mysql.user est le schéma système de Dolt",
     'cur.execute("SELECT COUNT(*) FROM mysql.user WHERE User=\'laptop\'")\n', set()),
)


def auto_epreuve() -> list[str]:
    """Les cas d'EPREUVE qui échouent — vide si l'instrument tient."""
    import tempfile
    rates = []
    for nom, code, attendu in EPREUVE:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "m.py").write_text(code)
            vu = set().union(set(), *tables_interrogees(Path(tmp)).values())
        if vu != attendu:
            rates.append(f"{nom} — vu {sorted(vu)}, attendu {sorted(attendu)}")
    return rates


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    args = p.parse_args()

    brain = args.brain.expanduser().resolve()
    template = brain / "brain-template"
    moteur = brain / "brain-engine"

    if not template.is_dir():
        print("\n  ⏭  pas de brain-template ici — rien mesuré.")
        print("     Un vert qui ne mesure rien serait pire qu'un rouge.\n")
        return 0

    echecs: list[str] = []

    def verifie(nom: str, cond: bool, detail: str = "") -> None:
        if not cond:
            echecs.append(nom)
        print(f"  {'✅' if cond else '❌'} {nom:<44} {detail}")

    print("\nLE TEMPLATE TIENT-IL DEBOUT TOUT SEUL ?\n")

    # L'instrument d'abord : un faux positif accusait le template de ce que
    # l'outil lisait mal (28/09).
    rates = auto_epreuve()
    verifie("l'instrument lit le SQL sans se tromper", not rates,
            f"{len(EPREUVE) - len(rates)}/{len(EPREUVE)} cas")
    for r in rates:
        print(f"       ⚠️  {r}")

    creees = tables_creees(template)
    interrogees = tables_interrogees(template)
    orphelines = {t: f for f, ts in interrogees.items() for t in ts
                  if t not in creees}

    toutes = {t for ts in interrogees.values() for t in ts}
    print(f"     {len(creees)} table(s) créée(s), {len(toutes)} interrogée(s)")
    verifie("rien d'interrogé qui ne soit créé", not orphelines,
            f"{len(orphelines)} orpheline(s)" if orphelines else "")
    for table, ou in sorted(orphelines.items()):
        print(f"       ⚠️  « {table} » interrogée par {ou}, créée nulle part")

    # Les modules que le BRAIN livre : c'est le seul étalon de ce qui est
    # « local ». Un module absent des deux côtés est une dépendance tierce,
    # pas un oubli de sync.
    connus = modules_locaux(moteur)
    utilises = imports_locaux(template, connus)
    presents = modules_locaux(template / "brain-engine")
    manquants = {m: f for f, ms in utilises.items() for m in ms
                 if m not in presents}

    print(f"\n     {len(presents)} module(s) livré(s) — "
          f"le brain en a {len(connus)}")
    verifie("rien d'importé qui ne soit livré", not manquants,
            f"{len(manquants)} absent(s)" if manquants else "")
    for module, ou in sorted(manquants.items()):
        print(f"       ⚠️  « {module} » importé par {ou}, absent du template")

    # Informatif, jamais bloquant : un retard de périmètre est un choix, et
    # un contrôle qui rougit sur un choix finit ignoré.
    ecart = modules_locaux(moteur) - presents
    if ecart:
        print(f"\n  ℹ️  {len(ecart)} module(s) que le brain a et pas le "
              f"template : {', '.join(sorted(ecart))}")
        print("      Périmètre en retard, pas défaut — c'est, "
              "et c'est une décision.")

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} garantie(s) tombée(s) : {', '.join(echecs)}")
        print("     Le template dépend de ce qu'il ne livre pas. Ici tout")
        print("     marche — c'est chez le fork que ça casse, et lui seul le")
        print("     verra.\n")
        return 1
    print("  ✅ le template ne dépend de rien qu'il ne livre\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
