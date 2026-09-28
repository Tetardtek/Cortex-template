#!/bin/bash
# brain-distribuable: oui
# human-gate-ack.sh — BSI-v3-5 Human Gate
# Gère les pauses planifiées (gate:human) et les arrêts d'urgence (pause/resume/abort).
# Point de contrôle humain sur le flux satellite.
#
# Usage :
#   human-gate-ack.sh gate   <sess_id> [message]  → déclare un gate:human (satellite s'arrête)
#   human-gate-ack.sh approve <sess_id> [message]  → valide le gate → reprise
#   human-gate-ack.sh reject  <sess_id> [message]  → refuse le gate → failed
#   human-gate-ack.sh pause   <sess_id> [message]  → arrêt d'urgence (cascade enfants)
#   human-gate-ack.sh resume  <sess_id> [message]  → reprise après pause
#   human-gate-ack.sh abort   <sess_id> [message]  → abandon définitif
#   human-gate-ack.sh status  <sess_id>            → état du claim + enfants
#
# Statuts claim :
#   open           → travail en cours
#   waiting_human  → gate:human déclaré — attend confirmation
#   paused         → arrêt d'urgence — pre-flight bloque enfants en cascade
#   closed         → terminé ok
#   failed         → terminé en erreur

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/premieres.sh"

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
CLAIMS_DIR="$BRAIN_ROOT/claims"

# --- Helpers ---

get_claim_file() {
  echo "$CLAIMS_DIR/${1}.yml"
}

get_status() {
  local claim_file="$1"
  { grep '^status:' "$claim_file" || true; } | sed 's/^[^:]*: *//' | tr -d '"' | premieres 1
}

set_status() {
  local claim_file="$1"
  local new_status="$2"
  sed -i "s/^status:.*/status:           $new_status/" "$claim_file"
}

append_gate_event() {
  local claim_file="$1"
  local event="$2"
  local message="${3:-}"
  local ts
  ts=$(date +%Y-%m-%dT%H:%M)
  if ! grep -q '^gate_history:' "$claim_file"; then
    echo "gate_history:" >> "$claim_file"
  fi
  if [ -n "$message" ]; then
    echo "  - { ts: \"$ts\", event: $event, message: \"$message\" }" >> "$claim_file"
  else
    echo "  - { ts: \"$ts\", event: $event }" >> "$claim_file"
  fi
}

write_signal() {
  local sess_id="$1"
  local signal_type="$2"
  local message="${3:-}"
  local sig_id="sig-$(date +%Y%m%d-%H%M%S)-${signal_type,,}"
  local brain_index="$BRAIN_ROOT/BRAIN-INDEX.md"
  local ts
  ts=$(date +%Y-%m-%dT%H:%M)

  # Insérer dans la table signals de BRAIN-INDEX.md
  local signal_row="| $sig_id | $sess_id | — | $signal_type | ${message:-$signal_type} | pending |"
  if grep -q '## Signals' "$brain_index" 2>/dev/null; then
    sed -i "/^## Signals/a $signal_row" "$brain_index"
  fi
  echo "$sig_id"
}

# Trouve tous les enfants directs d'un claim (parent_satellite = sess_id)
find_children() {
  local parent_id="$1"
  grep -l "parent_satellite:.*$parent_id" "$CLAIMS_DIR"/*.yml 2>/dev/null \
    | xargs -I{} basename {} .yml 2>/dev/null || true
}

# --- GATE (satellite déclare son arrêt planifié) ---
cmd_gate() {
  local sess_id="$1"
  local message="${2:-gate:human déclenché}"
  local claim_file
  claim_file=$(get_claim_file "$sess_id")

  [ -f "$claim_file" ] || { echo "❌ Claim introuvable : $sess_id"; exit 1; }

  local current
  current=$(get_status "$claim_file")
  if [ "$current" != "open" ]; then
    echo "❌ Claim non-open (status: $current) — gate:human ignoré"
    exit 1
  fi

  set_status "$claim_file" "waiting_human"
  append_gate_event "$claim_file" "HUMAN_GATE" "$message"
  write_signal "$sess_id" "HUMAN_GATE" "$message" > /dev/null

  echo "🔶 HUMAN GATE — $sess_id"
  echo "   Message  : $message"
  echo "   Status   : waiting_human"
  echo "   Commande : human-gate-ack.sh approve|reject $sess_id"
}

# --- APPROVE ---
cmd_approve() {
  local sess_id="$1"
  local message="${2:-approuvé}"
  local claim_file
  claim_file=$(get_claim_file "$sess_id")

  [ -f "$claim_file" ] || { echo "❌ Claim introuvable : $sess_id"; exit 1; }

  local current
  current=$(get_status "$claim_file")
  if [ "$current" != "waiting_human" ]; then
    echo "❌ Claim non en waiting_human (status: $current)"
    exit 1
  fi

  set_status "$claim_file" "open"
  append_gate_event "$claim_file" "APPROVED" "$message"

  echo "✅ Gate approuvé — $sess_id"
  echo "   Satellite peut reprendre."
}

# --- REJECT ---
cmd_reject() {
  local sess_id="$1"
  local message="${2:-refusé}"
  local claim_file
  claim_file=$(get_claim_file "$sess_id")

  [ -f "$claim_file" ] || { echo "❌ Claim introuvable : $sess_id"; exit 1; }

  set_status "$claim_file" "failed"
  append_gate_event "$claim_file" "REJECTED" "$message"
  write_signal "$sess_id" "BLOCKED_ON" "$message" > /dev/null

  echo "🚫 Gate refusé — $sess_id → failed"
}

# --- PAUSE (arrêt d'urgence + cascade) ---
cmd_pause() {
  local sess_id="$1"
  local message="${2:-pause urgence}"
  local claim_file
  claim_file=$(get_claim_file "$sess_id")

  [ -f "$claim_file" ] || { echo "❌ Claim introuvable : $sess_id"; exit 1; }

  local current
  current=$(get_status "$claim_file")
  if [ "$current" = "closed" ] || [ "$current" = "failed" ]; then
    echo "❌ Claim déjà terminé (status: $current)"
    exit 1
  fi

  set_status "$claim_file" "paused"
  append_gate_event "$claim_file" "PAUSED" "$message"
  write_signal "$sess_id" "PAUSED" "$message" > /dev/null

  echo "⏸  PAUSE — $sess_id"
  echo "   Message  : $message"
  echo "   Cascade  : pré-flight bloquera tous les enfants"

  # Cascade — pause récursive des enfants open/waiting
  local children
  children=$(find_children "$sess_id")
  if [ -n "$children" ]; then
    echo "   Enfants  :"
    for child_id in $children; do
      local child_file
      child_file=$(get_claim_file "$child_id")
      local child_status
      child_status=$(get_status "$child_file")
      if [ "$child_status" = "open" ] || [ "$child_status" = "waiting_human" ]; then
        set_status "$child_file" "paused"
        append_gate_event "$child_file" "PAUSED_CASCADE" "parent $sess_id paused"
        echo "     ⏸  $child_id (cascade)"
      fi
    done
  fi

  echo ""
  echo "   Reprise  : human-gate-ack.sh resume $sess_id"
  echo "   Abandon  : human-gate-ack.sh abort  $sess_id"
}

# --- RESUME ---
cmd_resume() {
  local sess_id="$1"
  local message="${2:-reprise}"
  local claim_file
  claim_file=$(get_claim_file "$sess_id")

  [ -f "$claim_file" ] || { echo "❌ Claim introuvable : $sess_id"; exit 1; }

  local current
  current=$(get_status "$claim_file")
  if [ "$current" != "paused" ]; then
    echo "❌ Claim non en pause (status: $current)"
    exit 1
  fi

  set_status "$claim_file" "open"
  append_gate_event "$claim_file" "RESUMED" "$message"

  echo "▶️  RESUME — $sess_id"

  # Cascade resume des enfants paused par cascade
  local children
  children=$(find_children "$sess_id")
  if [ -n "$children" ]; then
    for child_id in $children; do
      local child_file
      child_file=$(get_claim_file "$child_id")
      local child_status
      child_status=$(get_status "$child_file")
      if [ "$child_status" = "paused" ]; then
        # Vérifier que la pause vient bien d'une cascade (pas d'une pause manuelle directe)
        if grep -q "PAUSED_CASCADE" "$child_file" 2>/dev/null; then
          set_status "$child_file" "open"
          append_gate_event "$child_file" "RESUMED_CASCADE" "parent $sess_id resumed"
          echo "   ▶️  $child_id (cascade)"
        fi
      fi
    done
  fi

  echo "   Satellite peut reprendre — pre-flight passera CHECK 1."
}

# --- ABORT ---
cmd_abort() {
  local sess_id="$1"
  local message="${2:-abandon}"
  local claim_file
  claim_file=$(get_claim_file "$sess_id")

  [ -f "$claim_file" ] || { echo "❌ Claim introuvable : $sess_id"; exit 1; }

  set_status "$claim_file" "failed"
  append_gate_event "$claim_file" "ABORTED" "$message"
  write_signal "$sess_id" "BLOCKED_ON" "aborted: $message" > /dev/null

  echo "💀 ABORT — $sess_id → failed"

  # Cascade abort des enfants
  local children
  children=$(find_children "$sess_id")
  if [ -n "$children" ]; then
    for child_id in $children; do
      local child_file
      child_file=$(get_claim_file "$child_id")
      local child_status
      child_status=$(get_status "$child_file")
      if [ "$child_status" != "closed" ] && [ "$child_status" != "failed" ]; then
        set_status "$child_file" "failed"
        append_gate_event "$child_file" "ABORTED_CASCADE" "parent $sess_id aborted"
        echo "   💀 $child_id (cascade)"
      fi
    done
  fi
}

# --- STATUS ---
cmd_status() {
  local sess_id="$1"
  local claim_file
  claim_file=$(get_claim_file "$sess_id")

  [ -f "$claim_file" ] || { echo "❌ Claim introuvable : $sess_id"; exit 1; }

  local current
  current=$(get_status "$claim_file")
  local scope
  scope=$(grep '^scope:' "$claim_file" | sed 's/^[^:]*: *//' | tr -d '"')

  case "$current" in
    open)          echo "🟢 open          — $sess_id [$scope]" ;;
    waiting_human) echo "🔶 waiting_human — $sess_id [$scope]" ;;
    paused)        echo "⏸  paused        — $sess_id [$scope]" ;;
    closed)        echo "✅ closed        — $sess_id [$scope]" ;;
    failed)        echo "❌ failed        — $sess_id [$scope]" ;;
    *)             echo "❓ $current      — $sess_id [$scope]" ;;
  esac

  # Enfants
  local children
  children=$(find_children "$sess_id")
  if [ -n "$children" ]; then
    echo "   Enfants :"
    for child_id in $children; do
      local child_file
      child_file=$(get_claim_file "$child_id")
      local child_status
      child_status=$(get_status "$child_file")
      echo "     $child_status — $child_id"
    done
  fi
}

# --- Router ---
CMD="${1:-}"
case "$CMD" in
  gate)    cmd_gate    "${2:-}" "${3:-}" ;;
  approve) cmd_approve "${2:-}" "${3:-}" ;;
  reject)  cmd_reject  "${2:-}" "${3:-}" ;;
  pause)   cmd_pause   "${2:-}" "${3:-}" ;;
  resume)  cmd_resume  "${2:-}" "${3:-}" ;;
  abort)   cmd_abort   "${2:-}" "${3:-}" ;;
  status)  cmd_status  "${2:-}" ;;
  *)
    echo "Usage : human-gate-ack.sh <gate|approve|reject|pause|resume|abort|status> <sess_id> [message]"
    exit 1
    ;;
esac
