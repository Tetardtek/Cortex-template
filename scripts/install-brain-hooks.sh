#!/usr/bin/env bash
# brain-distribuable: oui
# install-brain-hooks.sh — Installe les hooks git brain
#
# Usage :
#   scripts/install-brain-hooks.sh          → installe dans le .git/hooks du dépôt
#   scripts/install-brain-hooks.sh --check  → vérifie que les six sont en place
#
# Hooks installés — leurs SOURCES sont versionnées dans scripts/hooks/ :
#   pre-commit  → posture de l'instance, zone d'écriture du type de session, docs-generer --check
#   commit-msg  → refuse un message sans type déclaré dans KERNEL.md
#   post-commit → signe de vie du claim ; la base suit les handoffs (checkout principal)
#   post-merge  → la base suit les handoffs après une fusion (avance rapide comprise)
#   post-rewrite → la base suit les handoffs après un rebase (un `pull` divergent)
#   post-checkout → la vue des agents suit un checkout de branche, un worktree neuf
#   (post-merge la reconstruit aussi : `agents/` est une vue quand `noyau/agents/` existe)
#
# Quand un dossier du brain est un satellite (son propre dépôt), trois lanceurs de
# plus dans ses hooks — post-commit, post-merge, post-rewrite :
#   handoffs/         → scripts/hooks/handoffs-satellite : la base suit les handoffs
#   instance/agents/  → scripts/hooks/agents-satellite : la vue suit la couche de l'instance
#   progression/      → scripts/hooks/agents-satellite : la carte des compléments suit la progression
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
HOOKS=(pre-commit commit-msg post-commit post-merge post-rewrite post-checkout)

# Les satellites à hooks : <chemin sous le brain>:<source dans scripts/hooks/>. Leurs hooks
# s'installent s'ils sont un dépôt à eux. Simple dossier du brain, `git -C <chemin>`
# répondrait par le dépôt du brain — d'où le `.git`.
BRAIN_MAIN="$(cd "$HOOKS_DIR/../.." && pwd)"
SAT_HOOKS=(post-commit post-merge post-rewrite)
SATELLITES=(handoffs:handoffs-satellite instance/agents:agents-satellite progression:agents-satellite)
sat_dir() {  # <chemin> → son dossier de hooks, vide s'il n'est pas un dépôt à lui
    [[ -e "$BRAIN_MAIN/$1/.git" ]] || return 0
    echo "$(cd "$BRAIN_MAIN/$1" && cd "$(git rev-parse --git-common-dir)" && pwd)/hooks"
}


lanceur() {
    cat <<EOF
#!/usr/bin/env bash
# brain — installé par scripts/install-brain-hooks.sh. Ne pas éditer : la source
# est scripts/hooks/$1, versionnée ; ce fichier la lance depuis le dépôt principal.
exec bash "\$(cd "\$(git rev-parse --git-common-dir)/.." && pwd)/scripts/hooks/$1" "\$@"
EOF
}

# Le lanceur d'un hook du satellite : le brain est au-dessus de son dépôt, d'autant de
# niveaux que son chemin en compte (`handoffs` : un, `instance/agents` : deux).
lanceur_satellite() {  # <hook> <chemin> <source>
    local remonte="/.." part parts
    IFS=/ read -ra parts <<< "$2"
    for part in "${parts[@]}"; do remonte="$remonte/.."; done
    cat <<EOF
#!/usr/bin/env bash
# brain — installé par scripts/install-brain-hooks.sh dans le satellite $2/. Ne pas
# éditer : la source est scripts/hooks/$3, versionnée dans le brain.
exec bash "\$(cd "\$(git rev-parse --git-common-dir)$remonte" && pwd)/scripts/hooks/$3" $1 "\$@"
EOF
}

if [[ "${1:-}" == "--check" ]]; then
    manquants=()
    for h in "${HOOKS[@]}"; do
        [[ -f "$HOOKS_DIR/$h" ]] && [[ "$(cat "$HOOKS_DIR/$h")" == "$(lanceur "$h")" ]] \
            || manquants+=("$h")
    done
    poses=()
    for sat in "${SATELLITES[@]}"; do
        chemin="${sat%%:*}"; source="${sat#*:}"; dir="$(sat_dir "$chemin")"
        [[ -n "$dir" ]] || continue
        for h in "${SAT_HOOKS[@]}"; do
            [[ -f "$dir/$h" ]] && [[ "$(cat "$dir/$h")" == "$(lanceur_satellite "$h" "$chemin" "$source")" ]] \
                || manquants+=("$chemin/$h")
        done
        poses+=("$chemin/")
    done
    if (( ${#manquants[@]} == 0 )); then
        echo "✅ Hooks brain installés — les ${#HOOKS[@]} lanceurs sont en place"
        for p in "${poses[@]}"; do echo "✅ Satellite $p — ses ${#SAT_HOOKS[@]} lanceurs aussi"; done
        exit 0
    fi
    echo "⚠️  Hooks brain absents ou écrits à la main : ${manquants[*]}"
    echo "    lancer : scripts/install-brain-hooks.sh"
    exit 1
fi

for h in "${HOOKS[@]}" "${SATELLITES[@]#*:}"; do
    [[ -f "$BRAIN_ROOT/scripts/hooks/$h" ]] || { echo "❌ source absente : scripts/hooks/$h" >&2; exit 1; }
done

installer() {  # <dossier des hooks> <hook> <contenu du lanceur>
    local cible="$1/$2" sauve
    if [[ -f "$cible" && "$(cat "$cible")" != "$3" ]]; then
        sauve="$cible.avant-$(date +%Y%m%d)"
        [[ -e "$sauve" ]] && sauve="$sauve-$(date +%H%M%S)"
        mv "$cible" "$sauve"
        echo "   ↳ $2 existant sauvegardé : $(basename "$sauve")"
    fi
    printf '%s\n' "$3" > "$cible"
    chmod +x "$cible"
}

mkdir -p "$HOOKS_DIR"
for h in "${HOOKS[@]}"; do
    installer "$HOOKS_DIR" "$h" "$(lanceur "$h")"
    echo "✅ $h"
done

for sat in "${SATELLITES[@]}"; do
    chemin="${sat%%:*}"; source="${sat#*:}"; dir="$(sat_dir "$chemin")"
    [[ -n "$dir" ]] || continue
    mkdir -p "$dir"
    for h in "${SAT_HOOKS[@]}"; do
        installer "$dir" "$h" "$(lanceur_satellite "$h" "$chemin" "$source")"
        echo "✅ $chemin/ $h"
    done
done

echo ""
echo "Hooks brain installés dans $HOOKS_DIR — sources : scripts/hooks/"
