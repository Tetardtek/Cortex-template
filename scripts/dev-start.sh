#!/usr/bin/env bash
# brain-rattachement: ponctuel  # poste de dev — lance a la main
# brain-distribuable: oui
# dev-start.sh — Démarre l'environnement dev brain local complet
# Usage : bash scripts/dev-start.sh
#
# Lance :
#   1. brain-engine/server.py   → port 7700 (BRAIN_TIER=owner)
#   2. brain-ui (Vite)          → port 5173
#
# Arrêt propre : Ctrl+C (trap SIGINT → kill les deux processus)

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_SERVER="$BRAIN_ROOT/brain-engine/server-dev.log"
LOG_VITE="/tmp/vite-brain.log"

# Charger les secrets si disponibles (silencieux)
SECRETS_FILE="$HOME/Dev/Brain/brain-secrets/MYSECRETS"
if [[ -f "$SECRETS_FILE" ]]; then
  set -a && source "$SECRETS_FILE" && set +a
fi

# Rôle owner en dev — pas de token requis
export BRAIN_TIER=owner

cleanup() {
  echo ""
  echo "→ Arrêt dev-start..."
  kill "$PID_SERVER" 2>/dev/null || true
  kill "$PID_VITE"   2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

# Tuer les instances précédentes si elles tournent
lsof -ti:7700 | xargs kill 2>/dev/null || true
lsof -ti:5173 | xargs kill 2>/dev/null || true
sleep 1

echo "🧠 brain-engine  → http://localhost:7700  (log: $LOG_SERVER)"
python3 "$BRAIN_ROOT/brain-engine/server.py" > "$LOG_SERVER" 2>&1 &
PID_SERVER=$!

echo "🎨 brain-ui      → http://localhost:5173/ui/"
cd "$BRAIN_ROOT/brain-ui" && npm run dev > "$LOG_VITE" 2>&1 &
PID_VITE=$!

echo ""
echo "Ctrl+C pour tout arrêter"
echo "---"

# Attendre que les deux process soient up
sleep 3
if kill -0 "$PID_SERVER" 2>/dev/null && kill -0 "$PID_VITE" 2>/dev/null; then
  echo "✅ brain-engine  PID $PID_SERVER"
  echo "✅ brain-ui      PID $PID_VITE"
else
  echo "❌ Un process n'a pas démarré — vérifier les logs"
fi

wait
