#!/bin/bash
# brain-distribuable: oui
# kernel-lock-gen.sh — Génère kernel.lock
# Checksums SHA-256 de tous les fichiers zone:kernel trackés
# Usage : bash scripts/kernel-lock-gen.sh
#         bash scripts/kernel-lock-gen.sh --avec-non-suivis
#           compte aussi les fichiers non suivis mais NON ignorés : ce que la
#           synchro du gabarit publiera, avant son `git add`.

set -euo pipefail

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LOCK_FILE="$BRAIN_ROOT/kernel.lock"

# Extraire la version depuis brain-compose.yml
VERSION=$(grep '^version:' "$BRAIN_ROOT/brain-compose.yml" | head -1 | sed 's/version: "//;s/"//' || true)
GENERATED_AT=$(date +%Y-%m-%dT%H:%M)

# --- Écriture du header ---
cat > "$LOCK_FILE" << EOF
# kernel.lock — généré automatiquement
# Ne pas éditer manuellement.
# Régénérer : bash scripts/kernel-lock-gen.sh
# Vérifier  : bash scripts/kernel-isolation-check.sh

kernel_version: "$VERSION"
generated_at: "$GENERATED_AT"

files:
EOF

# --- Fichiers kernel racine ---
KERNEL_ROOT_FILES=(
  "KERNEL.md"
  "brain-compose.yml"
  "brain-constitution.md"
)

for f in "${KERNEL_ROOT_FILES[@]}"; do
  if [ -f "$BRAIN_ROOT/$f" ]; then
    hash=$(sha256sum "$BRAIN_ROOT/$f" | cut -d' ' -f1)
    echo "  $f: $hash" >> "$LOCK_FILE"
  fi
done

# --- Les fichiers SUIVIS par git, pas ceux du disque —, 26/09 ---
#
# `find` parcourait le disque : il embarquait des fichiers IGNORES par git
# (la distribution Ventoy decompressee, `scripts/ventoy/ventoy-*/` dans
# .gitignore). Le lock dependait donc de la machine qui le generait — le
# checkout principal y mettait neuf scripts Ventoy, un worktree propre les
# retirait. L'en-tete disait deja « fichiers zone:kernel trackés ».
AVEC_NON_SUIVIS=false
[[ "${1:-}" == "--avec-non-suivis" ]] && AVEC_NON_SUIVIS=true
suivis() {   # suivis <pathspec>... → chemins absolus, tries, separes par \0
  local options=()
  $AVEC_NON_SUIVIS && options=(--cached --others --exclude-standard)
  # `${t[@]+"${t[@]}"}` : un tableau vide sous `set -u` plante avant bash 4.4.
  git -C "$BRAIN_ROOT" ls-files ${options[@]+"${options[@]}"} -- "$@" | sort -u \
    | while IFS= read -r rel; do
        [ -f "$BRAIN_ROOT/$rel" ] && printf '%s\0' "$BRAIN_ROOT/$rel"
      done
}

# --- agents/ (hors reviews/) — ou noyau/agents/, quand agents/ est une vue ---
#
# Une vue (des liens, ignorée par git) ne se scelle pas : le lock scelle ce que le
# noyau LIVRE. Sans vue, `noyau/agents/` n'existe pas et rien ne change.
while IFS= read -r -d '' f; do
  case "$f" in */reviews/*|*/_template*) continue ;; esac
  rel="${f#$BRAIN_ROOT/}"
  hash=$(sha256sum "$f" | cut -d' ' -f1)
  echo "  $rel: $hash" >> "$LOCK_FILE"
done < <(suivis 'agents/*.md' 'noyau/agents/*.md')

# --- scripts/ ---
#
# Les scripts qui declarent `# brain-rattachement: ponctuel` sont EXCLUS. Ce
# sont ceux que rien ne rattache au brain : outils de jeu, interventions infra
# d'un jour, bricoles de poste. Mesure le 04/09 — 15 des 73 scripts n'etaient
# cites par aucun agent, aucun contexte, aucun cron, aucun service.
#
# CE QU'ON PERD, et il faut le dire : leur integrite n'est plus verifiee. Un
# `wow-dbc-dump.py` modifie ne fera plus rougir le controle. C'est le prix
# assume pour que la derive du NOYAU redevienne lisible — avant, toucher a son
# lanceur d'un projet declarait le noyau derive.
while IFS= read -r -d '' f; do
  head -12 "$f" | grep -qE '^#\s*brain-rattachement:\s*ponctuel\b' && continue
  rel="${f#$BRAIN_ROOT/}"
  hash=$(sha256sum "$f" | cut -d' ' -f1)
  echo "  $rel: $hash" >> "$LOCK_FILE"
# `scripts/brain` aussi, nommé : une commande n'a pas d'extension, et le motif la
# laissait hors du lock — le même angle mort que la synchro.
done < <(suivis 'scripts/*.sh' 'scripts/*.py' 'scripts/brain')

echo "✅ kernel.lock généré — version $VERSION ($(grep -c ': [a-f0-9]\{64\}' "$LOCK_FILE") fichiers)"
