#!/usr/bin/env bash
# brain-distribuable: oui
# dolt-schema-gen.sh — régénère la déclaration versionnée du schéma Dolt.
#
#   scripts/dolt-schema-gen.sh          → régénère brain-engine/schema-dolt.sql
#   scripts/dolt-schema-gen.sh --check  → vérifie sans écrire (0 = à jour, 1 = dérive)
#   … --branche <b>                     → lit la branche Dolt <b> au lieu de main
#
# ── Pourquoi ce fichier existe ──────────────────────────────────────────────
#
# `brain-dolt/` est un satellite GITIGNORÉ (.gitignore:24). La déclaration du
# schéma de la base vivante n'était donc versionnée nulle part : mesuré le
# 05/09, DIX-NEUF tables sur vingt-neuf n'existaient dans aucun fichier suivi
# par git. Perdre la machine, c'était perdre la définition des deux tiers de la
# base — et a tranché que l'historique reste local.
#
# `brain-engine/schema.sql` ne comble pas ce trou : il décrit **SQLite**, pour
# `brain.db`. Ce ne sont pas deux versions du même schéma, ce sont deux schémas
# pour deux moteurs — les confondre a produit un hybride rejouable dans aucun
# des deux, le 04/09.
#
# ── Le partage avec views-dolt.sql ──────────────────────────────────────────
#
# Ce script écrit les TABLES. Les cinq vues vivent dans `views-dolt.sql`, écrit à
# la main : elles portent leur raisonnement — pourquoi `TIMESTAMPDIFF`, pourquoi
# `UTC_TIMESTAMP` et non `NOW()`, pourquoi un claim périmé se mesure depuis son
# expiration. Un dump les rendrait sans rien de tout ça. Une source chacun, et
# aucun recouvrement : c'est le piège de, et.
#
# ── Le défaut que Dolt met dans sa propre sortie ────────────────────────────
#
# `dolt dump --schema-only` rend les défauts d'`enum` en INDEX NUMÉRIQUE :
# `DEFAULT '1'` au lieu de `DEFAULT 'open'`. Mesuré le 05/09 : quinze
# occurrences. C'est le même défaut que `dolt dump` sur les données, et
# il survit à la 2.3.2 — ce n'est pas un contournement en attendant mieux.
#
# On réutilise donc `reparer()` de `dolt-dump-reparer.py`, avec une liste de
# colonnes VIDE : l'assouplissement `enum('', …)` est un artifice de
# restauration, légitime pour recharger des données qui contiennent des `''`.
# Un schéma de RÉFÉRENCE doit dire la contrainte, pas l'accommodement — la base
# viole sa propre déclaration sur `handoff_level`, et c'est, pas une
# vérité à graver.
#
# Vingt-deux `DEFAULT '0'` légitimes sur des `int` et `tinyint` ne sont PAS
# touchés : la réécriture ne s'applique qu'aux colonnes `enum`.
#
# ── Ce qui est retiré : le compteur d'AUTO_INCREMENT ────────────────────────
#
# `dolt dump` écrit `) ENGINE=InnoDB AUTO_INCREMENT=2158 …` — la valeur COURANTE
# du compteur, pas une déclaration. Elle monte à chaque insertion : mesurée à
# 2127 puis 2158 à quelques minutes d'intervalle, sans qu'aucune structure ne
# bouge. La garder ferait rougir le contrôle en permanence, sur un écart que
# personne ne peut verdir — le piège de et, dans lequel ce
# script est tombé à sa première exécution.
#
# L'ATTRIBUT `AUTO_INCREMENT` des colonnes reste : c'est lui, la déclaration.
# Seul l'état du compteur part.
#
# ── Lire une branche, pas seulement main ────────────────────────────────────
#
# Un chantier qui touche au schéma l'éprouve sur une branche Dolt jetable
# (`CALL DOLT_BRANCH`, `BRAIN_DOLT_DB=brain-dolt/<b>`). Mais ce script faisait
# `dolt dump`, qui refuse `--branch` (« Global arguments are not supported for
# this command », encore en 2.3.2) : il lisait toujours `main`. Pour ajouter la
# colonne `agent_session`, l'`ALTER` a dû être fusionné dans `main` AVANT de
# pouvoir régénérer ce fichier et le relire dans la PR — l'ordre à l'envers.
#
# Le schéma est donc reconstruit par `SHOW CREATE TABLE`, que `dolt --branch`
# accepte. Mesuré le 27/09 sur `main` : le résultat est IDENTIQUE, octet pour
# octet, à celui de `dolt dump --schema-only` (29 tables, défauts d'enum et
# compteurs compris) — ce ne sont pas deux sources, c'est la même sortie de
# Dolt par une autre porte. Un seul chemin, avec ou sans `--branche`.
#
# `SHOW FULL TABLES WHERE Table_type='BASE TABLE'` ne rend pas les vues : elles
# n'entrent plus du tout, il n'y a plus rien à retirer.
#
# ── La vérification ─────────────────────────────────────────────────────────
#
# Le fichier est REJOUÉ dans un dépôt Dolt jetable avant d'être écrit. Un
# schéma qu'on n'a pas rechargé n'est pas un schéma, c'est un texte — c'est la
# leçon de, où le dump quotidien ne se rechargeait pas depuis des mois
# sans que rien ne le dise.

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/premieres.sh"

# La data, quand le programme est ailleurs ; un banc qui copie ce script seul
# n'a pas `lib/donnees.sh` : la position, comme avant.
source "$(dirname "${BASH_SOURCE[0]}")/lib/donnees.sh" 2>/dev/null || brain_donnees() { printf '%s\n' "$1"; }
BRAIN_ROOT="$(brain_donnees "$(cd "$(dirname "$0")/.." && pwd)")" || exit 1
CIBLE="$BRAIN_ROOT/brain-engine/schema-dolt.sql"
CHECK_ONLY=false
BRANCHE=main
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)   CHECK_ONLY=true ;;
        --branche) BRANCHE="${2:?--branche attend un nom de branche}"; shift ;;
        *) echo "❌ argument inconnu : $1"; exit 1 ;;
    esac
    shift
done

command -v dolt >/dev/null 2>&1 || { echo "❌ dolt introuvable"; exit 1; }
[[ -d "$BRAIN_ROOT/brain-dolt/.dolt" ]] || { echo "❌ brain-dolt/ absent"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ── 1. Rendre le schéma des tables de la branche ───────────────────────────
# Deux appels : la liste des tables, puis tous les `SHOW CREATE TABLE` d'un
# coup (un document JSON par instruction) — le même temps qu'un `dolt dump`.
if ! ( cd "$BRAIN_ROOT/brain-dolt" && python3 - "$BRANCHE" "$TMP/brut.sql" ) 2>"$TMP/err" <<'PY'
import json, subprocess, sys
branche, dst = sys.argv[1], sys.argv[2]

def lire(sql):
    r = subprocess.run(["dolt", "--branch", branche, "sql", "-q", sql, "-r", "json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(r.stderr.strip() or r.stdout.strip() or f"dolt : code {r.returncode}")
    docs, i, dec = [], 0, json.JSONDecoder()
    while i < len(r.stdout):
        if r.stdout[i].isspace():
            i += 1
            continue
        doc, i = dec.raw_decode(r.stdout, i)
        docs.append(doc.get("rows", []))
    return docs

(lignes,) = lire("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
tables = sorted(next(v for k, v in l.items() if k.startswith("Tables_in")) for l in lignes)
if not tables:
    sys.exit("aucune table")
ddl = lire("; ".join(f"SHOW CREATE TABLE `{t}`" for t in tables))
assert len(ddl) == len(tables), f"{len(ddl)} réponses pour {len(tables)} tables"

sortie = ["SET FOREIGN_KEY_CHECKS=0;", "SET UNIQUE_CHECKS=0;"]
for t, rows in zip(tables, ddl):
    assert rows[0]["Table"] == t, f"réponse de {rows[0]['Table']} lue pour {t}"
    sortie += [f"DROP TABLE IF EXISTS `{t}`;", rows[0]["Create Table"] + ";"]
open(dst, "w", encoding="utf-8").write("\n".join(sortie) + "\n")
PY
then
    echo "❌ lecture du schéma de la branche « $BRANCHE » impossible — rien n'est écrit."
    sed 's/^/     /' "$TMP/err" | premieres 5
    exit 1
fi

TABLES=$(grep -c '^CREATE TABLE' "$TMP/brut.sql" || echo 0)
[[ "$TABLES" -gt 0 ]] || { echo "❌ aucune table rendue — refus d'écrire un schéma vide"; exit 1; }

# ── 2. Retirer le compteur d'AUTO_INCREMENT ───────────────────────────────
# (Les vues ne sont plus rendues à l'étape 1 : elles ont leur propre source.)
python3 - "$TMP/brut.sql" "$TMP/tables.sql" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
t = open(src, encoding="utf-8").read()
# Le compteur d'AUTO_INCREMENT est un ÉTAT, pas une déclaration : il monte à
# chaque insertion. L'attribut sur la colonne reste — seule la clause de table
# part. Sans ça, le contrôle rougit à la première ligne insérée.
t = re.sub(r" AUTO_INCREMENT=\d+", "", t)
open(dst, "w", encoding="utf-8").write(t)
PY

# ── 3. Réparer les défauts d'enum, SANS assouplir ──────────────────────────
python3 - "$TMP/tables.sql" "$BRAIN_ROOT" <<'PY'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(sys.argv[2]) / "scripts"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "reparer_mod", pathlib.Path(sys.argv[2]) / "scripts" / "dolt-dump-reparer.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
p = pathlib.Path(sys.argv[1])
texte, n_def, n_vides = mod.reparer(p.read_text(encoding="utf-8"), ())
assert n_vides == 0, "une colonne a été assouplie — un schéma de référence ne s'assouplit pas"
p.write_text(texte, encoding="utf-8")
print(f"   {n_def} défaut(s) d'enum réécrit(s) en littéral")
PY

# ── 4. Le rejouer pour de vrai ─────────────────────────────────────────────
ESSAI="$TMP/essai"
mkdir -p "$ESSAI"
if ! ( cd "$ESSAI" && dolt init --name brain --email brain@local >/dev/null 2>&1 \
       && dolt sql < "$TMP/tables.sql" ) >/dev/null 2>"$TMP/err"; then
    echo "❌ le schéma ne se rejoue pas — rien n'est écrit."
    sed 's/^/     /' "$TMP/err" | premieres 5
    exit 1
fi
RECHARGEES=$(cd "$ESSAI" && dolt sql -q "SELECT COUNT(*) FROM information_schema.TABLES \
             WHERE TABLE_TYPE='BASE TABLE'" -r csv 2>/dev/null | tail -1)

# ── 5. En-tête, puis écriture ──────────────────────────────────────────────
{
    echo "-- schema-dolt.sql — la déclaration des tables de la base vivante."
    echo "--"
    echo "-- ⚠️  GÉNÉRÉ par scripts/dolt-schema-gen.sh — ne pas éditer à la main."
    echo "--     Modifier la base, puis régénérer. Éditer ici ferait diverger la"
    echo "--     déclaration de ce qu'elle décrit, ce que tout ce chantier combat."
    echo "--"
    echo "-- Les six VUES ne sont pas ici : elles vivent dans views-dolt.sql, écrites"
    echo "-- à la main parce qu'elles portent leur raisonnement. Une source chacun."
    echo "--"
    echo "-- Les défauts d'enum sont réécrits en littéral : dolt les rend en index"
    echo "-- numérique (DEFAULT '1' pour 'open'), et ce défaut survit à la 2.3.2."
    echo "--"
    echo "-- Vérifié par rechargement réel dans un dépôt Dolt jetable avant écriture."
    echo ""
    cat "$TMP/tables.sql"
} > "$TMP/final.sql"

if $CHECK_ONLY; then
    if [[ -f "$CIBLE" ]] && diff -q <(tail -n +14 "$TMP/final.sql") <(tail -n +14 "$CIBLE") >/dev/null 2>&1; then
        echo "✅ schéma versionné à jour — $TABLES tables (branche $BRANCHE)"
        exit 0
    fi
    echo "❌ le schéma versionné a dérivé de la branche $BRANCHE — scripts/dolt-schema-gen.sh"
    exit 1
fi

mv "$TMP/final.sql" "$CIBLE"
echo "✅ $CIBLE"
echo "   $TABLES tables déclarées (branche $BRANCHE) · $RECHARGEES rechargées à la vérification"
