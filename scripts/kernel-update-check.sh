#!/bin/bash
# brain-distribuable: oui
# kernel-update-check.sh — Comparaison kernel local vs upstream
# Détecte les fichiers mis à jour upstream + conflits avec modifications locales
# avant de puller une nouvelle version du kernel.
#
# Usage :
#   bash scripts/kernel-update-check.sh
#   bash scripts/kernel-update-check.sh --remote <url-ou-path>  # upstream custom
#   bash scripts/kernel-update-check.sh --apply                 # applique les updates non-conflictuelles

set -euo pipefail

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LOCAL_LOCK="$BRAIN_ROOT/kernel.lock"
REMOTE=${1:-""}
REMOTE_ARG=${2:-""}
APPLY=false

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --remote) REMOTE_PATH="$2"; shift 2 ;;
    --apply)  APPLY=true; shift ;;
    *)        shift ;;
  esac
done

# --- Résolution de l'upstream ---
# Priorité : --remote > brain-compose.yml kernel_upstream > git remote origin/brain-template
UPSTREAM_REMOTE="${REMOTE_PATH:-}"

if [ -z "$UPSTREAM_REMOTE" ]; then
  # Lire depuis brain-compose.yml si défini
  UPSTREAM_REMOTE=$(grep '^kernel_upstream:' "$BRAIN_ROOT/brain-compose.yml" 2>/dev/null \
    | sed "s/kernel_upstream: *['\"]//;s/['\"]$//" || true)
fi

if [ -z "$UPSTREAM_REMOTE" ]; then
  echo "ℹ️  Upstream non configuré."
  echo "   Option 1 : bash scripts/kernel-update-check.sh --remote /path/to/brain-template"
  echo "   Option 2 : ajouter 'kernel_upstream: <url>' dans brain-compose.yml"
  echo ""
  echo "   Mode local — vérification intégrité uniquement (checksums vs fichiers actuels)"
  echo ""
  UPSTREAM_REMOTE=""
fi

# --- Lecture du kernel.lock local ---
if [ ! -f "$LOCAL_LOCK" ]; then
  echo "🚨 kernel.lock introuvable — lancer d'abord : bash scripts/kernel-lock-gen.sh"
  exit 1
fi

LOCAL_VERSION=$(grep '^kernel_version:' "$LOCAL_LOCK" | sed 's/kernel_version: "//;s/"//')
echo "🔍 Kernel update check — version locale : $LOCAL_VERSION"
echo ""

# --- Mode intégrité locale (pas d'upstream) ---
if [ -z "$UPSTREAM_REMOTE" ]; then
  MODIFIED=()
  MISSING=()

  while IFS= read -r line; do
    # Extraire chemin et hash depuis "  chemin: hash"
    if [[ "$line" =~ ^[[:space:]]+([^:]+):[[:space:]]([a-f0-9]{64})$ ]]; then
      filepath="${BASH_REMATCH[1]}"
      expected_hash="${BASH_REMATCH[2]}"
      fullpath="$BRAIN_ROOT/$filepath"

      if [ ! -f "$fullpath" ]; then
        MISSING+=("  ❓ ABSENT  $filepath")
      else
        actual_hash=$(sha256sum "$fullpath" | cut -d' ' -f1)
        if [ "$actual_hash" != "$expected_hash" ]; then
          MODIFIED+=("  ✏️  MODIFIÉ $filepath")
        fi
      fi
    fi
  done < "$LOCAL_LOCK"

  if [ ${#MISSING[@]} -gt 0 ]; then
    echo "❓ Fichiers kernel absents :"
    for m in "${MISSING[@]}"; do echo "$m"; done
    echo ""
  fi

  if [ ${#MODIFIED[@]} -gt 0 ]; then
    echo "✏️  Fichiers kernel modifiés localement depuis le dernier lock :"
    for m in "${MODIFIED[@]}"; do echo "$m"; done
    echo ""
    echo "   → Régénérer le lock après validation : bash scripts/kernel-lock-gen.sh"
  else
    echo "✅ Intégrité kernel OK — aucun fichier modifié depuis kernel.lock v$LOCAL_VERSION"
  fi
  exit 0
fi

# --- Mode upstream (comparaison avec une source externe) ---
UPSTREAM_LOCK=""

# Déterminer si c'est un path local ou une URL git
if [ -d "$UPSTREAM_REMOTE" ]; then
  UPSTREAM_LOCK="$UPSTREAM_REMOTE/kernel.lock"
elif [[ "$UPSTREAM_REMOTE" == git@* ]] || [[ "$UPSTREAM_REMOTE" == https://* ]]; then
  # Clone shallow pour récupérer kernel.lock uniquement
  TMPDIR=$(mktemp -d)
  trap "rm -rf $TMPDIR" EXIT
  echo "📡 Récupération upstream : $UPSTREAM_REMOTE"
  git clone --depth=1 --quiet "$UPSTREAM_REMOTE" "$TMPDIR/upstream" 2>/dev/null
  UPSTREAM_LOCK="$TMPDIR/upstream/kernel.lock"
else
  echo "🚨 Format upstream non reconnu : $UPSTREAM_REMOTE"
  echo "   Attendu : /path/local, git@host:repo, ou https://host/repo"
  exit 1
fi

if [ ! -f "$UPSTREAM_LOCK" ]; then
  echo "🚨 kernel.lock introuvable dans upstream : $UPSTREAM_REMOTE"
  exit 1
fi

UPSTREAM_VERSION=$(grep '^kernel_version:' "$UPSTREAM_LOCK" | sed 's/kernel_version: "//;s/"//')
echo "   Version upstream : $UPSTREAM_VERSION"
echo ""

# --- Comparaison fichier par fichier ---
UPDATES=()      # Upstream plus récent, pas modifié localement → safe to pull
CONFLICTS=()    # Upstream plus récent ET modifié localement → revue requise
ONLY_LOCAL=()   # Fichier local non présent upstream → custom local

declare -A UPSTREAM_HASHES
declare -A LOCAL_HASHES

# Charger hashes upstream
while IFS= read -r line; do
  if [[ "$line" =~ ^[[:space:]]+([^:]+):[[:space:]]([a-f0-9]{64})$ ]]; then
    UPSTREAM_HASHES["${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
  fi
done < "$UPSTREAM_LOCK"

# Charger hashes locaux
while IFS= read -r line; do
  if [[ "$line" =~ ^[[:space:]]+([^:]+):[[:space:]]([a-f0-9]{64})$ ]]; then
    LOCAL_HASHES["${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
  fi
done < "$LOCAL_LOCK"

# Comparer
for filepath in "${!UPSTREAM_HASHES[@]}"; do
  upstream_hash="${UPSTREAM_HASHES[$filepath]}"
  local_hash="${LOCAL_HASHES[$filepath]:-}"
  actual_hash=""

  if [ -f "$BRAIN_ROOT/$filepath" ]; then
    actual_hash=$(sha256sum "$BRAIN_ROOT/$filepath" | cut -d' ' -f1)
  fi

  if [ "$upstream_hash" != "$local_hash" ]; then
    # Upstream a changé vs notre lock
    if [ "$actual_hash" = "$local_hash" ] || [ -z "$actual_hash" ]; then
      # Fichier non modifié localement → update safe
      UPDATES+=("$filepath")
    else
      # Modifié localement ET changé upstream → conflit
      CONFLICTS+=("$filepath")
    fi
  fi
done

# Fichiers locaux non présents upstream
for filepath in "${!LOCAL_HASHES[@]}"; do
  if [ -z "${UPSTREAM_HASHES[$filepath]:-}" ]; then
    ONLY_LOCAL+=("$filepath")
  fi
done

# --- Rapport ---
if [ ${#UPDATES[@]} -gt 0 ]; then
  echo "⬆️  Mises à jour disponibles ($LOCAL_VERSION → $UPSTREAM_VERSION) :"
  for f in "${UPDATES[@]}"; do echo "   ✅ $f"; done
  echo ""
fi

if [ ${#CONFLICTS[@]} -gt 0 ]; then
  echo "⚠️  Conflits — modifiés localement ET mis à jour upstream :"
  for f in "${CONFLICTS[@]}"; do echo "   🔴 $f"; done
  echo "   → Revue manuelle requise avant pull."
  echo ""
fi

if [ ${#ONLY_LOCAL[@]} -gt 0 ]; then
  echo "🔵 Fichiers locaux uniquement (non présents upstream) :"
  for f in "${ONLY_LOCAL[@]}"; do echo "   🔵 $f"; done
  echo ""
fi

if [ ${#UPDATES[@]} -eq 0 ] && [ ${#CONFLICTS[@]} -eq 0 ]; then
  echo "✅ Kernel à jour — aucune différence avec upstream v$UPSTREAM_VERSION"
fi

# --- Apply mode ---
if $APPLY && [ ${#UPDATES[@]} -gt 0 ]; then
  echo ""
  echo "⚙️  --apply : copie des updates non-conflictuelles..."
  for filepath in "${UPDATES[@]}"; do
    src=""
    if [ -d "$UPSTREAM_REMOTE" ]; then
      src="$UPSTREAM_REMOTE/$filepath"
    else
      src="$TMPDIR/upstream/$filepath"
    fi
    if [ -f "$src" ]; then
      cp "$src" "$BRAIN_ROOT/$filepath"
      echo "   ✅ $filepath"
    fi
  done
  echo ""
  echo "→ Régénérer le lock : bash scripts/kernel-lock-gen.sh"
fi
