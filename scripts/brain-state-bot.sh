#!/bin/bash
# brain-rattachement: ponctuel  # bot d'etat — ecrit live-states.md, lance a la main
# brain-distribuable: oui
# brain-state-bot.sh — sans serveur : claims + git log
# Lit les claims ouverts + git log → écrit/met à jour workspace/live-states.md
# Commit live-states.md avec "live-states: bot update"
#
# Usage : bash scripts/brain-state-bot.sh [--dry-run]
#
# Règles :
#   - Ne ferme pas les claims BSI
#   - Ne lit pas MYSECRETS
#   - Silencieux sauf erreur critique (stderr)
#   - Ne jamais écraser `needs` si déjà présent

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -uo pipefail

BRAIN_ROOT="${BRAIN_ROOT:-$HOME/Dev/Brain}"
LIVE_STATES="$BRAIN_ROOT/workspace/live-states.md"
DRY_RUN=0

# ─── Args ──────────────────────────────────────────────────────────────────

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
  esac
done

# ─── Helpers ───────────────────────────────────────────────────────────────

_now_iso() {
  date +"%Y-%m-%dT%H:%M"
}

# Convertit un timestamp ISO8601 (YYYY-MM-DDTHH:MM) en epoch seconds
_iso_to_epoch() {
  local ts="$1"
  # Remplacer T par espace pour date
  date -d "${ts/T/ }" +%s 2>/dev/null || echo 0
}

# Extrait un champ YAML simple (key: value) depuis un fichier
_yaml_field() {
  local file="$1" key="$2"
  grep -E "^${key}:[[:space:]]" "$file" 2>/dev/null \
    | head -1 \
    | sed "s/^${key}:[[:space:]]*//" \
    | tr -d '"' \
    | xargs
}

# Dérive le slug projet depuis le filename du claim
# sess-YYYYMMDD-HHMM-slug1-slug2 → slug1 (premier segment après timestamp)
_derive_project() {
  local sess_id="$1"
  # Retirer "sess-YYYYMMDD-HHMM-" puis prendre le premier segment
  local remainder
  remainder=$(echo "$sess_id" | sed 's/^sess-[0-9]\{8\}-[0-9]\{4\}-//')
  # Retirer suffixes connus (boot, brain, supervisor…) si présent après "-"
  echo "$remainder" | cut -d'-' -f1
}

# Dérive le slug depuis le champ scope du claim
# scope: "mon-projet-back/" → "mon-projet"
# scope: "brain/" → "brain"
_project_from_scope() {
  local scope="$1"
  # Prendre le premier token, retirer trailing slash, puis garder partie avant "-"
  local first_token
  first_token=$(echo "$scope" | awk '{print $1}' | tr -d '/')
  # Si contient "-", prendre la partie avant le dernier tiret
  # ex: mon-projet-back → mon-projet
  # ex: brain → brain
  echo "$first_token" | sed 's/-[^-]*$//' | sed 's/\///'
}

# Cherche un repo git pour un slug projet
# Cherche dans Brain/, Gitea/, Github/ (insensible à la casse)
_find_project_repo() {
  local slug="$1"
  local candidates=(
    "$BRAIN_ROOT"
    "$BRAIN_ROOT/brain-ui"
    "$BRAIN_ROOT/brain-engine"
    "$HOME/Dev/Gitea"
    "$HOME/Dev/Github"
  )

  # Match direct : brain → BRAIN_ROOT
  if [ "$slug" = "brain" ]; then
    echo "$BRAIN_ROOT"
    return
  fi

  # Chercher un répertoire qui contient le slug (insensible à la casse)
  for base in "${candidates[@]}"; do
    [ -d "$base" ] || continue
    # Vérifier si base lui-même match (ex: brain-ui)
    local basename
    basename=$(basename "$base" | tr '[:upper:]' '[:lower:]')
    local slug_lc
    slug_lc=$(echo "$slug" | tr '[:upper:]' '[:lower:]')
    if [[ "$basename" == *"$slug_lc"* ]] && [ -d "$base/.git" ]; then
      echo "$base"
      return
    fi
    # Chercher sous-répertoires
    if [ -d "$base" ]; then
      local found
      found=$(find "$base" -maxdepth 1 -type d -iname "*${slug}*" 2>/dev/null | head -1)
      if [ -n "$found" ] && [ -d "$found/.git" ]; then
        echo "$found"
        return
      fi
    fi
  done
  echo ""
}

# Obtient le dernier commit message d'un repo
_git_last_commit() {
  local repo="$1"
  [ -d "$repo/.git" ] || { echo ""; return; }
  git -C "$repo" log --oneline -1 2>/dev/null | sed 's/^[a-f0-9]* //' | head -c 80
}

# Obtient le timestamp du dernier commit (epoch)
_git_last_commit_epoch() {
  local repo="$1"
  [ -d "$repo/.git" ] || { echo "0"; return; }
  git -C "$repo" log -1 --format="%ct" 2>/dev/null || echo "0"
}

# ─── Lecture de l'état courant de live-states.md ────────────────────────────

# Extrait un champ YAML d'une entrée de live-states.md identifiée par sess_id
# Retourne "" si le champ n'existe pas ou si le sess_id n'est pas trouvé
_get_existing_field() {
  local sess_id="$1" field="$2"
  local in_block=0 value=""

  while IFS= read -r line; do
    # Début de bloc : ligne "- sess_id: <id>"
    if echo "$line" | grep -qE "^- sess_id:[[:space:]]*${sess_id}[[:space:]]*$"; then
      in_block=1
      continue
    fi
    # Fin de bloc : nouvelle entrée "- sess_id:" ou fin du fichier
    if [ "$in_block" -eq 1 ]; then
      if echo "$line" | grep -qE "^- sess_id:"; then
        break
      fi
      # Lire le champ demandé
      if echo "$line" | grep -qE "^[[:space:]]+${field}:[[:space:]]"; then
        value=$(echo "$line" | sed "s/^[[:space:]]*${field}:[[:space:]]*//" | tr -d '"')
      fi
    fi
  done < "$LIVE_STATES"
  echo "$value"
}

# ─── Écriture d'un bloc dans live-states.md ─────────────────────────────────

# Met à jour ou insère un bloc sess_id dans live-states.md
# Args: sess_id project doing status needs priority updated
_upsert_block() {
  local sess_id="$1"
  local project="$2"
  local doing="$3"
  local status="$4"
  local needs="$5"
  local priority="$6"
  local updated="$7"

  local new_block
  new_block="- sess_id: ${sess_id}
  project: ${project}
  doing: \"${doing}\"
  status: ${status}
  needs: ${needs}
  priority: ${priority}
  team: []
  blocking: []
  context: \"\"
  updated: ${updated}"

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] bloc à écrire pour ${sess_id}:"
    echo "$new_block"
    return
  fi

  # Vérifier si le bloc existe déjà
  if grep -qE "^- sess_id:[[:space:]]*${sess_id}[[:space:]]*$" "$LIVE_STATES" 2>/dev/null; then
    # Mise à jour différentielle : remplacer le bloc existant
    # Utilise python3 pour éviter les conflits de syntaxe awk/bash
    local tmpfile
    tmpfile=$(mktemp)
    python3 - "$LIVE_STATES" "$sess_id" "$new_block" > "$tmpfile" << 'PYEOF'
import sys, re

infile   = sys.argv[1]
sess_id  = sys.argv[2]
new_block = sys.argv[3]

with open(infile) as f:
    lines = f.readlines()

out = []
in_block = False
for line in lines:
    if re.match(r'^- sess_id:\s*' + re.escape(sess_id) + r'\s*$', line):
        in_block = True
        out.append(new_block + "\n")
        continue
    if in_block:
        # Fin du bloc : nouvelle entrée, frontmatter ou commentaire niveau 0
        if re.match(r'^- sess_id:', line) or re.match(r'^---', line) or re.match(r'^#', line):
            in_block = False
            out.append(line)
        # else : ignorer les lignes de l'ancien bloc
    else:
        out.append(line)

sys.stdout.write("".join(out))
PYEOF
    mv "$tmpfile" "$LIVE_STATES"
  else
    # Insertion : ajouter à la fin avec ligne vide de séparation
    echo "" >> "$LIVE_STATES"
    echo "$new_block" >> "$LIVE_STATES"
  fi
}

# ─── Main ────────────────────────────────────────────────────────────────────

[ -f "$LIVE_STATES" ] || { echo "CRITICAL: $LIVE_STATES introuvable" >&2; exit 1; }

NOW_EPOCH=$(date +%s)
TWO_HOURS=7200
UPDATED=0  # Nombre de sessions mises à jour

for claim in "$BRAIN_ROOT/claims"/sess-*.yml; do
  [ -f "$claim" ] || continue

  # Lire les champs du claim
  status=$(_yaml_field "$claim" "status")
  [ "$status" = "open" ] || continue

  sess_id=$(_yaml_field "$claim" "sess_id")
  [ -n "$sess_id" ] || continue

  scope=$(_yaml_field "$claim" "scope")
  opened_at=$(_yaml_field "$claim" "opened_at")

  # Dériver le projet depuis scope, puis depuis sess_id en fallback
  project=""
  if [ -n "$scope" ]; then
    project=$(_project_from_scope "$scope")
  fi
  if [ -z "$project" ]; then
    project=$(_derive_project "$sess_id")
  fi
  [ -n "$project" ] || project="unknown"

  # Trouver le repo git du projet
  repo=$(_find_project_repo "$project")

  # Dériver doing depuis le dernier commit git
  doing=""
  if [ -n "$repo" ]; then
    doing=$(_git_last_commit "$repo")
  fi
  [ -n "$doing" ] || doing="En cours"

  # Récupérer l'état courant du bloc (si existant)
  existing_needs=$(_get_existing_field "$sess_id" "needs")
  existing_status=$(_get_existing_field "$sess_id" "status")
  existing_updated=$(_get_existing_field "$sess_id" "updated")

  # needs : ne jamais écraser si déjà présent
  needs="${existing_needs:-none}"
  # Si needs est vide string, mettre none
  [ -n "$needs" ] || needs="none"

  # Stale detection : si updated > 2h + status progressing + pas de commit récent
  new_status="progressing"
  if [ -n "$existing_status" ] && [ "$existing_status" != "closed" ]; then
    new_status="$existing_status"
  fi

  if [ "$new_status" = "progressing" ]; then
    # Vérifier si stale
    stale=0
    if [ -n "$existing_updated" ]; then
      updated_epoch=$(_iso_to_epoch "$existing_updated")
      age=$(( NOW_EPOCH - updated_epoch ))
      if [ "$age" -gt "$TWO_HOURS" ]; then
        # Pas de commit récent ?
        last_commit_epoch=0
        if [ -n "$repo" ]; then
          last_commit_epoch=$(_git_last_commit_epoch "$repo")
        fi
        commit_age=$(( NOW_EPOCH - last_commit_epoch ))
        if [ "$commit_age" -gt "$TWO_HOURS" ]; then
          stale=1
        fi
      fi
    fi
    if [ "$stale" -eq 1 ]; then
      new_status="idle"
      echo "stale: ${sess_id} → idle" >&2
    fi
  fi

  # Priority : medium par défaut (pas de blocking[] cross-claim)
  priority="medium"

  # Updated : maintenant
  updated_ts=$(_now_iso)

  _upsert_block "$sess_id" "$project" "$doing" "$new_status" "$needs" "$priority" "$updated_ts"
  UPDATED=$(( UPDATED + 1 ))
done

# Commit si des sessions ont été mises à jour (et pas dry-run)
if [ "$DRY_RUN" -eq 0 ] && [ "$UPDATED" -gt 0 ]; then
  git -C "$BRAIN_ROOT" add workspace/live-states.md 2>/dev/null
  git -C "$BRAIN_ROOT" diff --cached --quiet 2>/dev/null || \
    git -C "$BRAIN_ROOT" commit -m "live-states: bot update" 2>/dev/null
fi

exit 0
