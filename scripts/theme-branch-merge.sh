#!/bin/bash
# brain-distribuable: oui
# theme-branch-merge.sh — Merge une branche thème sur main après validation
# Vérifie l'état de la chaîne (claims enfants fermés, aucun BLOCKED_ON)
# avant de merger sur main.
#
# Usage :
#   bash scripts/theme-branch-merge.sh <theme-name>
#   bash scripts/theme-branch-merge.sh brain-engine-be6

set -euo pipefail

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
THEME_NAME="${1:-}"

if [ -z "$THEME_NAME" ]; then
  echo "Usage : bash scripts/theme-branch-merge.sh <theme-name>"
  exit 1
fi

BRANCH="theme/$THEME_NAME"
CURRENT=$(git -C "$BRAIN_ROOT" branch --show-current)

# --- Vérifier que la branche existe ---
if ! git -C "$BRAIN_ROOT" show-ref --quiet "refs/heads/$BRANCH"; then
  echo "🚨 Branche $BRANCH introuvable."
  exit 1
fi

# --- Vérifier qu'on est bien sur la branche thème ---
if [ "$CURRENT" != "$BRANCH" ]; then
  echo "⚠️  Branche courante : $CURRENT"
  echo "   Basculer d'abord : git checkout $BRANCH"
  exit 1
fi

echo "🔍 Validation pré-merge — $BRANCH → main"
echo ""

BLOCKERS=()

# --- Check 1 : aucun claim open (BRAIN-042 — brain.db source unique) ---
OPEN_COUNT=$(bash "$BRAIN_ROOT/scripts/bsi-query.sh" count-open 2>/dev/null || echo "0")
if [ "$OPEN_COUNT" -gt 0 ]; then
  OPEN_LIST=$(bash "$BRAIN_ROOT/scripts/bsi-query.sh" open 2>/dev/null || true)
  while IFS= read -r line; do
    BLOCKERS+=("  🔴 Claim ouvert : $line")
  done <<< "$OPEN_LIST"
fi

# --- Check 2 : aucun signal BLOCKED_ON pending ---
BLOCKED=$(grep -A3 "BLOCKED_ON" "$BRAIN_ROOT/BRAIN-INDEX.md" 2>/dev/null \
  | grep "pending" || true)
if [ -n "$BLOCKED" ]; then
  BLOCKERS+=("  🔴 Signal BLOCKED_ON pending dans BRAIN-INDEX.md")
fi

# --- Check 3 : working tree propre ---
if ! git -C "$BRAIN_ROOT" diff --quiet || ! git -C "$BRAIN_ROOT" diff --cached --quiet; then
  BLOCKERS+=("  🔴 Working tree non propre — commiter avant merge")
fi

# --- Rapport ---
if [ ${#BLOCKERS[@]} -gt 0 ]; then
  echo "🚨 Merge bloqué — résoudre avant :"
  echo ""
  for b in "${BLOCKERS[@]}"; do echo "$b"; done
  echo ""
  exit 1
fi

echo "✅ Chaîne validée — aucun bloqueur détecté"
echo ""

# --- Merge sur main ---
echo "⚙️  Merge $BRANCH → main"
git -C "$BRAIN_ROOT" checkout main
git -C "$BRAIN_ROOT" merge --no-ff "$BRANCH" -m "theme: merge $BRANCH → main [chaîne verte]"

echo ""
echo "✅ Merge terminé — $BRANCH intégré sur main"
echo ""

# --- Proposer suppression branche ---
echo "Supprimer la branche thème ?"
echo "  git branch -d $BRANCH"
echo ""
echo "Régénérer kernel.lock si des fichiers kernel ont changé :"
echo "  bash scripts/kernel-lock-gen.sh && bash scripts/kernel-isolation-check.sh"
