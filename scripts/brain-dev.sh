#!/usr/bin/env bash
# brain-rattachement: ponctuel  # poste de dev — lance a la main
# brain-distribuable: oui
# brain-dev.sh — Démarrage brain en mode dev local (laptop / offline)
# Usage : bash scripts/brain-dev.sh [--engine] [--ui]
# Sans arguments → démarre brain-engine (mock désactivé) + brain-ui
#   --engine  : démarre brain-engine localement sur :7700 (uvicorn)
#   --ui      : démarre brain-ui en dev (npm run dev)
# Sans aucun argument : démarre les deux (engine + ui)

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRAIN_UI="$BRAIN_ROOT/brain-ui"
ENGINE_PORT=7700

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
info() { echo -e "   $1"; }

# ── Parse args ────────────────────────────────────────────────────────────────
START_ENGINE=false
START_UI=false

if [[ $# -eq 0 ]]; then
  START_ENGINE=true
  START_UI=true
fi

for arg in "$@"; do
  case "$arg" in
    --engine) START_ENGINE=true ;;
    --ui)     START_UI=true ;;
    *)
      echo "Usage: bash scripts/brain-dev.sh [--engine] [--ui]"
      echo "  --engine  : démarre brain-engine sur :$ENGINE_PORT"
      echo "  --ui      : démarre brain-ui en dev"
      echo "  (sans args) : démarre les deux"
      exit 1
      ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     brain-dev.sh — mode dev local            ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Vérifications préalables ──────────────────────────────────────────────────
if $START_ENGINE; then
  if ! command -v python3 &>/dev/null; then
    warn "python3 non trouvé — impossible de démarrer brain-engine"
    START_ENGINE=false
  fi
  if ! command -v uvicorn &>/dev/null && ! python3 -c "import uvicorn" 2>/dev/null; then
    warn "uvicorn non installé — pip3 install uvicorn[standard]"
    START_ENGINE=false
  fi
fi

if $START_UI; then
  if [[ ! -d "$BRAIN_UI" ]]; then
    warn "brain-ui absent ($BRAIN_UI) — --ui ignoré"
    START_UI=false
  elif ! command -v npm &>/dev/null; then
    warn "npm non trouvé — impossible de démarrer brain-ui"
    START_UI=false
  fi
fi

# ── Créer .env.local pour brain-ui ───────────────────────────────────────────
if [[ -d "$BRAIN_UI" ]]; then
  if $START_ENGINE; then
    # engine local disponible → pas de mock
    cat > "$BRAIN_UI/.env.local" << 'EOF'
VITE_USE_MOCK=false
VITE_BRAIN_API=http://localhost:7700
EOF
    ok "brain-ui/.env.local → engine local (:7700)"
  else
    # pas d'engine → mode mock
    cat > "$BRAIN_UI/.env.local" << 'EOF'
VITE_USE_MOCK=true
VITE_BRAIN_API=
EOF
    ok "brain-ui/.env.local → mode mock (pas de VPS requis)"
  fi
fi

# ── Trap Ctrl+C → tuer les processus fils ────────────────────────────────────
PIDS=()
cleanup() {
  echo ""
  info "Arrêt en cours..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  ok "Processus arrêtés proprement."
  exit 0
}
trap cleanup INT TERM

# ── Démarrer brain-engine ─────────────────────────────────────────────────────
if $START_ENGINE; then
  info "Démarrage brain-engine sur :$ENGINE_PORT..."
  cd "$BRAIN_ROOT"
  BRAIN_PORT=$ENGINE_PORT python3 -m uvicorn brain-engine.server:app \
    --host 0.0.0.0 --port $ENGINE_PORT --reload 2>&1 | sed 's/^/[engine] /' &
  PIDS+=($!)
  ok "brain-engine démarré (PID ${PIDS[-1]})"
fi

# ── Démarrer brain-ui ─────────────────────────────────────────────────────────
if $START_UI; then
  info "Démarrage brain-ui (npm run dev)..."
  cd "$BRAIN_UI"
  npm run dev 2>&1 | sed 's/^/[ui] /' &
  PIDS+=($!)
  ok "brain-ui démarré (PID ${PIDS[-1]})"
fi

if [[ ${#PIDS[@]} -eq 0 ]]; then
  warn "Aucun processus démarré — vérifier les prérequis ci-dessus."
  exit 1
fi

echo ""
if $START_ENGINE; then
  info "brain-engine : http://localhost:$ENGINE_PORT"
  info "  /health    : http://localhost:$ENGINE_PORT/health"
fi
if $START_UI; then
  info "brain-ui    : http://localhost:5173 (port Vite par défaut)"
fi
echo ""
info "Ctrl+C pour arrêter."
echo ""

# Attendre les processus fils
wait
