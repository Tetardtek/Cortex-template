#!/bin/bash
# brain-distribuable: oui
# posture-gate-check.sh — Vérifie si une session type est autorisée par la posture courante (BRAIN-069)
# Returns 0 (allowed) / 1 (blocked) / 2 (usage error)
#
# Usage :
#   bash scripts/posture-gate-check.sh --posture                  # echo posture courante
#   bash scripts/posture-gate-check.sh --check-session <type>     # 0=allowed, 1=blocked
#   bash scripts/posture-gate-check.sh --check-kernel-write       # 0=allowed, 1=blocked
#   bash scripts/posture-gate-check.sh --noyau                    # echo la clé `noyau:` (vide sans elle)
#
# `noyau:` n'est pas une posture : `lecture` fige `noyau/` d'un fork (le hook de posture
# refuse son commit), sans fermer aucune session ni toucher au kernel_write.
# Override exception (BRAIN-069) : BRAIN_KERNEL_OVERRIDE=1 force le PASS pour replica-nomad

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -uo pipefail

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
COMPOSE_FILE="$BRAIN_ROOT/brain-compose.local.yml"

# --- Lire la posture de l'instance active depuis brain-compose.local.yml ---
_get_posture() {
  [ -f "$COMPOSE_FILE" ] || { echo "master"; return; }
  local posture="master"
  if command -v python3 &>/dev/null && python3 -c "import yaml" &>/dev/null 2>&1; then
    posture=$(BRAIN_COMPOSE="$COMPOSE_FILE" python3 - <<'PYEOF' 2>/dev/null
import yaml, os, sys
path = os.environ.get('BRAIN_COMPOSE', '')
try:
    with open(path) as f:
        data = yaml.safe_load(f)
    instances = data.get('instances', {})
    for name, inst in instances.items():
        if inst.get('active'):
            print(inst.get('posture', 'master'))
            sys.exit(0)
except Exception:
    pass
print('master')
PYEOF
)
  else
    # Fallback grep — capture la première occurrence de "posture:" sous l'instance active
    posture=$(grep "^\s*posture:" "$COMPOSE_FILE" | head -1 | awk '{print $NF}' | tr -d "'\"")
  fi
  echo "${posture:-master}"
}

# --- La clé `noyau:` de l'instance active (lecture, ouvert) — vide sans elle ---
_get_noyau() {
  [ -f "$COMPOSE_FILE" ] || return 0
  if command -v python3 &>/dev/null && python3 -c "import yaml" &>/dev/null 2>&1; then
    BRAIN_COMPOSE="$COMPOSE_FILE" python3 - <<'PYEOF' 2>/dev/null && return 0
import yaml, os
data = yaml.safe_load(open(os.environ['BRAIN_COMPOSE'])) or {}
for inst in (data.get('instances') or {}).values():
    if isinstance(inst, dict) and inst.get('active'):
        print(inst.get('noyau') or '')
        break
PYEOF
  fi
  # Sans YAML lisible : la ligne déclarée — une déclaration ne se perd pas en silence.
  grep -E "^\s+noyau:" "$COMPOSE_FILE" | head -1 | awk '{print $2}' | tr -d "'\""
}

# --- Sessions autorisées par posture ---
# Returns 0 (allowed) / 1 (blocked)
_session_allowed() {
  local posture="$1" session="$2"
  case "$posture" in
    master)
      # Tous types autorisés
      return 0
      ;;
    replica-nomad)
      case "$session" in
        work|explore|chill)
          return 0
          ;;
        brain|pilote)
          # Override exception : BRAIN_KERNEL_OVERRIDE=1
          if [ "${BRAIN_KERNEL_OVERRIDE:-0}" = "1" ]; then
            echo "⚠️ posture replica-nomad — override BRAIN_KERNEL_OVERRIDE=1 actif (session $session autorisée exceptionnellement)" >&2
            return 0
          fi
          return 1
          ;;
        *)
          # Type inconnu (ex: futur tag) → fallback explore — autorisé
          return 0
          ;;
      esac
      ;;
    *)
      # Posture inconnue → fail open avec warn (future-proof, détection typos)
      echo "⚠️ posture '$posture' inconnue — fallback master (autorisé)" >&2
      return 0
      ;;
  esac
}

# --- Main ---
ACTION="${1:-}"
POSTURE=$(_get_posture)

case "$ACTION" in
  --posture)
    echo "$POSTURE"
    exit 0
    ;;
  --noyau)
    _get_noyau
    exit 0
    ;;
  --check-session)
    SESSION="${2:-}"
    if [ -z "$SESSION" ]; then
      echo "Usage: posture-gate-check.sh --check-session <type>" >&2
      exit 2
    fi
    if _session_allowed "$POSTURE" "$SESSION"; then
      exit 0
    else
      cat >&2 <<EOF
🚦 PRE-FLIGHT — posture replica-nomad
Cette instance ne fait pas de session '$SESSION' par défaut (BRAIN-069).
Override exception : BRAIN_KERNEL_OVERRIDE=1 brain boot $SESSION
Sinon : brain boot work/<projet> ou brain boot explore.
EOF
      exit 1
    fi
    ;;
  --check-kernel-write)
    case "$POSTURE" in
      master)
        exit 0
        ;;
      replica-nomad)
        if [ "${BRAIN_KERNEL_OVERRIDE:-0}" = "1" ]; then
          exit 0
        fi
        exit 1
        ;;
      *)
        echo "⚠️ posture '$POSTURE' inconnue — fallback master (kernel_write autorisé)" >&2
        exit 0
        ;;
    esac
    ;;
  *)
    cat >&2 <<EOF
Usage:
  posture-gate-check.sh --posture                  # echo current posture
  posture-gate-check.sh --check-session <type>     # 0=allowed, 1=blocked
  posture-gate-check.sh --check-kernel-write       # 0=allowed, 1=blocked
  posture-gate-check.sh --noyau                    # echo noyau: (lecture, ouvert, vide)

Override exception (BRAIN-069):
  BRAIN_KERNEL_OVERRIDE=1 forces PASS for replica-nomad

Postures connues : master, replica-nomad
Posture inconnue : fail open avec warn stderr (future-proof)
EOF
    exit 2
    ;;
esac
