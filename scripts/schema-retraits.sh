#!/usr/bin/env bash
# brain-distribuable: oui
# schema-retraits.sh — Retire de la base les tables que le schéma a retirées
#
# Usage :
#   bash scripts/schema-retraits.sh              → à blanc : ce qui serait retiré
#   bash scripts/schema-retraits.sh --appliquer  → retire, puis dit ce qui l'a été
#
# Sortie : 0 = rien à faire, ou fait · 1 = refusé (une table porte des lignes)
#          2 = base injoignable ou erreur
#
# ── Pourquoi ce script existe ───────────────────────────────────────────────
#
# Le schéma sait AJOUTER une table chez une instance, jamais en RETIRER une.
# `schema.sql` est rejoué à chaque initialisation, sans aucun `DROP` — un `DROP`
# y effacerait les données d'un fork à chaque démarrage — et `dolt-setup.sh`
# crée, rien ne retire. Mesuré le 28/09, après la v2.3.3 (29 → 21 tables) : le
# laptop avait reçu le nouveau schéma et gardait les huit tables. Chaque retrait
# fait diverger la base d'une instance de son schéma déclaré, en silence ; et
# chez un fork Dolt, `dolt-schema-gen.sh` les réécrirait dans `schema-dolt.sql`,
# d'où un conflit au prochain `git merge` de l'amont.
#
# ── Trois règles ────────────────────────────────────────────────────────────
#
# 1. **Une table qui porte des lignes n'est jamais retirée.** L'amont la sait
#    vide chez lui ; chez l'instance, ces lignes sont peut-être les siennes. Une
#    seule table pleine et RIEN n'est retiré — on ne laisse pas une base à moitié
#    migrée. À l'instance de décider : exporter, vider, puis relancer.
# 2. **Le commit Dolt ne porte que ce qui est retiré.** `Journal.commit` du CORE
#    élargit à TOUT dès qu'une table est introuvable — c'est le cas d'une table
#    qu'on vient de retirer — et embarquerait les écritures en cours d'une autre
#    session. On indexe donc exactement les tables retirées (et `dolt_schemas`
#    si une vue part), rien d'autre.
# 3. **Idempotent.** Ce qui est déjà absent est ignoré ; relancer ne fait rien.
#
# ── Ajouter un retrait ──────────────────────────────────────────────────────
#
# Une entrée dans RETRAITS, dans la PR qui retire la table du schéma — et la
# table sort de `brain-engine/modules.yml` : un module qui part emporte les
# siennes. Les entrées ne s'effacent pas : un fork peut sauter plusieurs versions.

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine
BRAIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$BRAIN_ROOT" "$@" <<'PYEOF'
import sys
from pathlib import Path

RETRAITS = [
    # (version, pourquoi, tables, vues) — la plus ancienne d'abord
    ("2.3.3", "tables en doublon de fichiers, ou jamais écrites",
     ["learning_modules", "learning_tracks", "todo_items", "todo_sections",
      "backlog_visions", "decision_chantiers", "agent_memory", "agent_loads"],
     ["v_graduation_candidates"]),
    ("2.4.1", "les liens de la vue Cosmos, calculés en mars : rien ne les lançait ni ne les lisait",
     ["cosmos_edges"], []),
    ("2.4.3", "le disjoncteur des sessions : jamais écrit, son seul écrivain archivé",
     ["circuit_breaker"], []),
]

racine = Path(sys.argv[1])
args = sys.argv[2:]
inconnus = [a for a in args if a != "--appliquer"]
if inconnus:
    sys.exit(f"argument inconnu : {' '.join(inconnus)} — usage : schema-retraits.sh [--appliquer]")
appliquer = "--appliquer" in args

sys.path.insert(0, str(racine / "brain-engine"))
try:
    import db
except Exception as e:                                     # noqa: BLE001
    print(f"❌ db.py ne se charge pas : {e}"); sys.exit(2)

if db.BACKEND == "dolt":
    cible = f"Dolt {db.DOLT_HOST}:{db.DOLT_PORT}/{db.DOLT_DB}"
else:
    cible = f"SQLite {db.DB_PATH}"
    if not Path(db.DB_PATH).exists():
        # sqlite3 CRÉERAIT le fichier : une base absente n'a rien à retirer.
        print(f"base : {cible} — absente, rien à retirer"); sys.exit(0)
print(f"base : {cible}")

def vue_existe(nom: str) -> bool:
    if db.BACKEND == "dolt":
        r = db.query("SELECT COUNT(*) AS n FROM information_schema.views "
                     "WHERE table_schema = DATABASE() AND table_name = %s", (nom,))
    else:
        r = db.query("SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'view' AND name = ?", (nom,))
    return bool(r and int(r[0]["n"]))

try:
    tables, vues = [], []
    for version, pourquoi, ts, vs in RETRAITS:
        for t in ts:
            if db.table_exists(t):
                tables.append((version, t, int(db.count(t))))
        for v in vs:
            if vue_existe(v):
                vues.append((version, v))
except Exception as e:                                     # noqa: BLE001
    print(f"❌ base injoignable : {e}"); sys.exit(2)

if not tables and not vues:
    print("✅ rien à retirer — la base suit le schéma"); sys.exit(0)

for version, v in vues:
    print(f"  vue    {v:28}  (retirée en {version})")
for version, t, n in tables:
    print(f"  table  {t:28}  {n:>6} ligne(s)  (retirée en {version})")

pleines = [(t, n) for _, t, n in tables if n]
if pleines:
    print("\n🔴 REFUS — ces tables portent des lignes, rien n'est retiré :")
    for t, n in pleines:
        print(f"     {t} : {n} ligne(s)")
    print("   L'amont les a retirées parce que rien ne les lit plus. Si ces lignes")
    print("   comptent pour toi, exporte-les ; puis vide la table et relance.")
    sys.exit(1)

if not appliquer:
    print("\n(à blanc) — relancer avec --appliquer pour retirer")
    sys.exit(0)

try:
    if db.BACKEND == "sqlite":
        for _, v in vues:
            db.execute(f"DROP VIEW IF EXISTS {v}")
        for _, t, _ in tables:
            db.execute(f"DROP TABLE IF EXISTS {t}")
    else:
        db.execute("SET FOREIGN_KEY_CHECKS=0")
        for _, v in vues:
            db.execute(f"DROP VIEW IF EXISTS `{v}`")
        for _, t, _ in tables:
            db.execute(f"DROP TABLE IF EXISTS `{t}`")
        db.execute("SET FOREIGN_KEY_CHECKS=1")
        # Règle 2 : n'indexer que ce qui vient d'être retiré.
        sales = {r["table_name"] for r in db.query("SELECT table_name FROM dolt_status")}
        a_indexer = [t for _, t, _ in tables if t in sales]
        if vues and "dolt_schemas" in sales:
            a_indexer.append("dolt_schemas")
        for t in a_indexer:
            db.execute("CALL DOLT_ADD(%s)", (t,))
        versions = sorted({v for v, *_ in tables} | {v for v, _ in vues})
        db.execute("CALL DOLT_COMMIT('-m', %s)",
                   (f"schema-retraits : {len(tables)} table(s), {len(vues)} vue(s) "
                    f"retirées par le schéma ({', '.join(versions)})",))
except Exception as e:                                     # noqa: BLE001
    print(f"❌ retrait interrompu : {e}"); sys.exit(2)

print(f"\n✅ retiré : {len(tables)} table(s), {len(vues)} vue(s)")
PYEOF
