#!/bin/bash
# brain-distribuable: oui
# theme-branch-open.sh — Ouvre une branche thème pour un pilote ou satellite
# Crée la branche git theme/<name> depuis main et y bascule.
#
# Usage :
#   bash scripts/theme-branch-open.sh <theme-name>
#   bash scripts/theme-branch-open.sh brain-engine-be6
#   bash scripts/theme-branch-open.sh mon-api-v3
#
# Convention branche : theme/<name>
# La branche reste locale jusqu'au merge — pas de push automatique.

set -euo pipefail

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
THEME_NAME="${1:-}"

if [ -z "$THEME_NAME" ]; then
  echo "Usage : bash scripts/theme-branch-open.sh <theme-name>"
  echo "Exemple : bash scripts/theme-branch-open.sh brain-engine-be6"
  exit 1
fi

BRANCH="theme/$THEME_NAME"
CURRENT=$(git -C "$BRAIN_ROOT" branch --show-current)

# --- Vérifier qu'on part de main ---
if [ "$CURRENT" != "main" ]; then
  echo "⚠️  Branche courante : $CURRENT (attendu : main)"
  echo "   Basculer sur main d'abord : git checkout main"
  exit 1
fi

# --- Vérifier que la branche n'existe pas déjà ---
if git -C "$BRAIN_ROOT" show-ref --quiet "refs/heads/$BRANCH"; then
  echo "⚠️  Branche $BRANCH existe déjà."
  echo "   Pour reprendre : git checkout $BRANCH"
  exit 1
fi

# --- Vérifier que main est propre ---
if ! git -C "$BRAIN_ROOT" diff --quiet || ! git -C "$BRAIN_ROOT" diff --cached --quiet; then
  echo "🚨 Working tree non propre — commiter ou stasher avant d'ouvrir une branche thème."
  exit 1
fi

# --- Créer + basculer ---
git -C "$BRAIN_ROOT" checkout -b "$BRANCH"

echo ""
echo "✅ Branche thème ouverte : $BRANCH"
echo ""
echo "Workflow :"
echo "  → Satellites commitent sur cette branche"
echo "  → Quand chaîne verte : bash scripts/theme-branch-merge.sh $THEME_NAME"
echo ""
echo "Rappel claim : déclarer theme_branch: $BRANCH dans le claim du pilote"
