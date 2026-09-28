#!/usr/bin/env bash
# brain-distribuable: oui
# install-brain-hooks.sh — Installe les hooks git brain
#
# Usage :
#   scripts/install-brain-hooks.sh          → installe dans le .git/hooks du dépôt
#   scripts/install-brain-hooks.sh --check  → vérifie que les cinq sont en place
#
# Hooks installés — leurs SOURCES sont versionnées dans scripts/hooks/ :
#   pre-commit  → posture de l'instance, zone d'écriture du type de session, docs-generer --check
#   commit-msg  → refuse un message sans type déclaré dans KERNEL.md
#   post-commit → signe de vie du claim ; la base suit les handoffs (checkout principal)
#   post-merge  → la base suit les handoffs après une fusion (avance rapide comprise)
#   post-rewrite → la base suit les handoffs après un rebase (un `pull` divergent)
#
# Ce qui s'installe dans .git/hooks n'est qu'un LANCEUR : il exécute la source
# versionnée du dépôt principal. Corriger un hook, c'est corriger sa source et
# la faire relire — plus un fichier hors dépôt que rien ne corrige, écrit à la
# main sur une machine et absent des autres. Worktrees compris : ils partagent
# .git/hooks, et le lanceur retrouve le dépôt principal par --git-common-dir.
#
# Idempotent. Un hook existant qui n'est pas un lanceur est SAUVEGARDÉ à côté
# (<nom>.avant-AAAAMMJJ), jamais effacé. À relancer sur chaque clone frais.

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$(cd "$BRAIN_ROOT" && cd "$(git rev-parse --git-common-dir)" && pwd)/hooks"
HOOKS=(pre-commit commit-msg post-commit post-merge post-rewrite)

lanceur() {
    cat <<EOF
#!/usr/bin/env bash
# brain — installé par scripts/install-brain-hooks.sh. Ne pas éditer : la source
# est scripts/hooks/$1, versionnée ; ce fichier la lance depuis le dépôt principal.
exec bash "\$(cd "\$(git rev-parse --git-common-dir)/.." && pwd)/scripts/hooks/$1" "\$@"
EOF
}

if [[ "${1:-}" == "--check" ]]; then
    manquants=()
    for h in "${HOOKS[@]}"; do
        [[ -f "$HOOKS_DIR/$h" ]] && [[ "$(cat "$HOOKS_DIR/$h")" == "$(lanceur "$h")" ]] \
            || manquants+=("$h")
    done
    if (( ${#manquants[@]} == 0 )); then
        echo "✅ Hooks brain installés — les ${#HOOKS[@]} lanceurs sont en place"
        exit 0
    fi
    echo "⚠️  Hooks brain absents ou écrits à la main : ${manquants[*]}"
    echo "    lancer : scripts/install-brain-hooks.sh"
    exit 1
fi

for h in "${HOOKS[@]}"; do
    [[ -f "$BRAIN_ROOT/scripts/hooks/$h" ]] || { echo "❌ source absente : scripts/hooks/$h" >&2; exit 1; }
done

mkdir -p "$HOOKS_DIR"
for h in "${HOOKS[@]}"; do
    cible="$HOOKS_DIR/$h"
    if [[ -f "$cible" && "$(cat "$cible")" != "$(lanceur "$h")" ]]; then
        sauve="$cible.avant-$(date +%Y%m%d)"
        [[ -e "$sauve" ]] && sauve="$sauve-$(date +%H%M%S)"
        mv "$cible" "$sauve"
        echo "   ↳ $h existant sauvegardé : $(basename "$sauve")"
    fi
    lanceur "$h" > "$cible"
    chmod +x "$cible"
    echo "✅ $h"
done

echo ""
echo "Hooks brain installés dans $HOOKS_DIR — sources : scripts/hooks/"
