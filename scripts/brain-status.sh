#!/bin/bash
# brain-distribuable: oui
# brain-status.sh — Vue live du brain pour toute instance
# Lecture seule. Aucune écriture.
#
# Usage :
#   brain-status.sh          → résumé complet
#   brain-status.sh claims   → claims open uniquement
#   brain-status.sh locks    → fichiers verrouillés
#   brain-status.sh signals  → signaux pending

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/premieres.sh"

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
CLAIMS_DIR="$BRAIN_ROOT/claims"
LOCKS_DIR="$BRAIN_ROOT/locks"
NOW=$(date +%s)

# --- Helpers ---
# Un claim sans le champ : `grep` rend 1, et sous pipefail la valeur vide tuait le script.
claim_field() { { grep "^${2}:" "$1" || true; } | sed 's/^[^:]*: *//' | tr -d '"' | premieres 1; }

status_icon() {
  case "$1" in
    open)          echo "🟢" ;;
    waiting_human) echo "🔶" ;;
    paused)        echo "⏸ " ;;
    closed)        echo "✅" ;;
    failed)        echo "❌" ;;
    *)             echo "❓" ;;
  esac
}

# --- CLAIMS ---
show_claims() {
  local filter="${1:-open waiting_human paused}"
  local found=0

  echo "── Claims ──────────────────────────────────────"
  for f in "$CLAIMS_DIR"/*.yml; do
    [ -f "$f" ] || continue
    local status sess_id scope type opened_at
    status=$(claim_field "$f" status)
    # Filter
    echo "$filter" | grep -qw "$status" || continue
    sess_id=$(claim_field "$f" sess_id)
    scope=$(claim_field "$f" scope)
    type=$(claim_field "$f" type)
    opened_at=$(claim_field "$f" opened_at)
    printf "  %s %-12s  %-42s  [%s]\n" \
      "$(status_icon "$status")" "$type" "$sess_id" "$scope"
    found=1
  done
  [ "$found" -eq 0 ] && echo "  (aucun)" || true
}

# --- LOCKS ---
show_locks() {
  local found=0

  echo "── Locks fichiers ──────────────────────────────"
  for f in "$LOCKS_DIR"/*.lock; do
    [ -f "$f" ] || continue
    local file holder expires_at epoch
    file=$(grep '^file:' "$f" | sed 's/^[^:]*: *//')
    holder=$(grep '^holder:' "$f" | sed 's/^[^:]*: *//')
    expires_at=$(grep '^expires_at:' "$f" | sed 's/^[^:]*: *//')
    epoch=$(date -d "$expires_at" +%s 2>/dev/null \
      || date -j -f "%Y-%m-%dT%H:%M" "$expires_at" +%s 2>/dev/null || echo 0)
    if [ "$NOW" -lt "$epoch" ]; then
      printf "  🔴 %-40s  %s  (exp: %s)\n" "$file" "$holder" "$expires_at"
    else
      printf "  ⚠️  %-40s  expiré\n" "$file"
    fi
    found=1
  done
  [ "$found" -eq 0 ] && echo "  (aucun)" || true
}

# --- SIGNALS ---
show_signals() {
  echo "── Signaux en attente ──────────────────────────"
  # En base, relevés par `bsi-signal.sh inbox` — ici et chez les peers. La
  # table de BRAIN-INDEX.md que cette fonction lisait n'est plus alimentée
  # depuis mai : elle répondait « (aucun) » quoi que dise la base.
  bash "$BRAIN_ROOT/scripts/bsi-signal.sh" inbox 2>&1 | sed 's/^/  /' \
    || echo "  ⚠️  boîte illisible — je n'ai pas pu regarder, ce n'est pas « aucun »"
}

# --- HEADER ---
show_header() {
  local branch
  branch=$(git -C "$BRAIN_ROOT" branch --show-current 2>/dev/null || echo "?")
  local open_count=0 lock_count=0
  while IFS= read -r f; do [ -f "$f" ] && open_count=$((open_count+1)); done \
    < <(find "$CLAIMS_DIR" -name "*.yml" 2>/dev/null)
  # recount only open/waiting/paused
  open_count=0
  for f in "$CLAIMS_DIR"/*.yml; do
    [ -f "$f" ] || continue
    s=$(claim_field "$f" status)
    case "$s" in open|waiting_human|paused) open_count=$((open_count+1)) ;; esac
  done
  for f in "$LOCKS_DIR"/*.lock; do
    [ -f "$f" ] && lock_count=$((lock_count+1))
  done

  echo "╔══════════════════════════════════════════════╗"
  printf "║  🧠 Brain status  %-27s║\n" "$(date +%H:%M)"
  printf "║  branch: %-36s║\n" "$branch"
  printf "║  open: %s claims  locks: %s                   ║\n" "$open_count" "$lock_count"
  echo "╚══════════════════════════════════════════════╝"
}

# --- Router ---
CMD="${1:-all}"
case "$CMD" in
  claims)  show_claims "open waiting_human paused" ;;
  locks)   show_locks ;;
  signals) show_signals ;;
  all|"")
    show_header
    echo ""
    show_claims "open waiting_human paused"
    echo ""
    show_locks
    echo ""
    show_signals
    ;;
  *)
    echo "Usage : brain-status.sh [all|claims|locks|signals]"
    exit 1
    ;;
esac
