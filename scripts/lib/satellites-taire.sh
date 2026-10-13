#!/usr/bin/env bash
# brain-distribuable: oui  # brain-init.sh le source
# satellites-taire.sh — `brain vue --satellites` lancé par brain init, et ce qu'il a désuivi DIT
#
# Usage :
#   source "$PROGRAMME/scripts/lib/satellites-taire.sh"
#   brain_satellites_taire <racine du brain> <racine du programme>
#     → 0 fait (et, s'il y en a, les fichiers désuivis et la commande pour commiter) · 1 échec
#
# `brain vue --satellites` tait chaque satellite dans le `.gitignore` et, pour un satellite
# devenu dépôt, désuit ses fichiers de semis (`git rm --cached`, jamais du disque). Dans
# brain init sa sortie partait dans /dev/null : relancé, init laissait des suppressions
# indexées que personne n'annonçait. Ici, les suppressions NOUVELLES de l'index (celles
# d'avant l'appel ne comptent pas) sont dites, avec la commande pour les commiter.
# Rien n'est commité : c'est à la personne.

brain_satellites_taire() {
  local brain="$1" prog="$2" avant apres nouveaux
  avant="$(git -C "$brain" diff --cached --name-only --diff-filter=D 2>/dev/null | sort)"
  BRAIN_ROOT="$brain" python3 "$prog/scripts/vue.py" --satellites >/dev/null || return 1
  apres="$(git -C "$brain" diff --cached --name-only --diff-filter=D 2>/dev/null | sort)"
  nouveaux="$(comm -13 <(printf '%s\n' "$avant") <(printf '%s\n' "$apres") | sed '/^$/d')"
  if [[ -n "$nouveaux" ]]; then
    echo "   $(printf '%s\n' "$nouveaux" | wc -l) fichier(s) d'un satellite devenu dépôt ne sont plus suivis par ce dossier (toujours sur le disque) :"
    printf '%s\n' "$nouveaux" | sed 's/^/     /'
    # `git commit -- <chemins>` ne prend pas un fichier désuivi dans un dépôt imbriqué
    # (mesuré : « no changes added ») — on commite l'index, après l'avoir relu.
    echo "   à commiter (l'index : relis-le d'abord, git -C $brain status) : git -C $brain commit -m 'config: les satellites, des dépôts à part'"
  fi
  return 0
}
