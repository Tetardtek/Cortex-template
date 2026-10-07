#!/usr/bin/env bash
# brain-distribuable: oui
# brain-db-sync.sh — Sync DB depuis les sources brain (migrate.py)
# Backend : db.py (sqlite ou dolt selon .env.local)
#
# Usage :
#   brain-db-sync.sh             → migrate + log résultat
#   brain-db-sync.sh --quiet     → log fichier uniquement (pour hooks git)
#   brain-db-sync.sh --check     → exit 0 si la base porte les handoffs du disque
#                                  (statuts compris) ; 2 sinon. N'écrit rien.
#
# Headless : zéro notify-send, zéro dépendance Wayland/display.
# Appelable depuis hook git post-commit, cron, ou manuellement.
#
# Exit codes :
#   0 = sync réussi
#   1 = migrate.py introuvable ou Python absent
#   2 = DB stale (--check uniquement)
#   3 = migrate.py a échoué

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

# La data, quand le programme est ailleurs ; un banc qui copie ce script seul
# n'a pas `lib/donnees.sh` : la position, comme avant.
source "$(dirname "${BASH_SOURCE[0]}")/lib/donnees.sh" 2>/dev/null || brain_donnees() { printf '%s\n' "$1"; }
BRAIN_ROOT="$(brain_donnees "$(cd "$(dirname "$0")/.." && pwd)")" || exit 1
MIGRATE="$BRAIN_ROOT/brain-engine/migrate.py"
LOG_FILE="$BRAIN_ROOT/brain-engine/sync.log"
QUIET=false
CHECK_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=true ;;
        --check) CHECK_ONLY=true ;;
    esac
done

log() {
    local ts
    ts=$(date '+%Y-%m-%dT%H:%M:%S')
    echo "[$ts] $*" >> "$LOG_FILE"
    $QUIET || echo "[brain-db-sync] $*"
}

# Vérifications préalables
if [[ ! -f "$MIGRATE" ]]; then
    log "ERROR: migrate.py introuvable ($MIGRATE)"
    exit 1
fi

if ! python3 -c "pass" 2>/dev/null; then
    log "ERROR: python3 absent"
    exit 1
fi

# --check : la base porte-t-elle ce que handoffs/ dit ? Lecture seule.
if $CHECK_ONLY; then
    # La MESURE est dans migrate.py, à côté de `lire_handoffs()` — la fonction
    # même qui fournit ce que la synchro écrit. Ce --check datait un journal :
    # il comparait le dernier commit handoffs/ à la dernière ligne « OK » de
    # sync.log. Un handoff venu d'un `pull` divergent garde l'heure de sa fusion
    # sur la forge : une synchro locale faite entre-temps le déclarait à jour
    # sans qu'il soit en base. Avant encore (jusqu'au 27/09 matin), il
    # comparait à l'ouverture du dernier claim et écrivait dans sync.log.
    # Un --check ne touche à rien : il répond. 0 à jour, 2 sinon ; `SKIP` et 0
    # quand la base ne peut pas être lue.
    rc=0
    if $QUIET; then
        python3 "$MIGRATE" --verifier-handoffs >/dev/null || rc=$?
    else
        python3 "$MIGRATE" --verifier-handoffs || rc=$?
    fi
    exit "$rc"
fi

# Sync
log "Démarrage migrate.py..."
if python3 "$MIGRATE" >> "$LOG_FILE" 2>&1; then
    claim_count=$(python3 -c "
import sys, os
sys.path.insert(0, os.path.join('$BRAIN_ROOT', 'brain-engine'))
import db
n = db.count('claims')
o = db.count('claims', \"status = 'open'\")
print(f'{o} open / {n} total')
" 2>/dev/null || echo "?")
    log "OK — claims: $claim_count"
else
    log "ERROR: migrate.py a échoué (voir $LOG_FILE)"
    exit 3
fi
