#!/usr/bin/env bash
# brain-distribuable: oui  # brain-init.sh le source
# reglages-doctor.sh — les réglages du doctor d'un brain neuf, posés et commités par init
#
# Usage :
#   source "$PROGRAMME/scripts/lib/reglages-doctor.sh"
#   brain_reglages_doctor <racine du brain> <racine du programme>
#
# Deux réglages d'instance (`instance/doctor/`) : le point de référence de la convention
# de commit (`convention-commits-depuis`, un sha) et le seuil des liens morts
# (`liens-morts-seuil`). Le doctor les posait lui-même à sa première passe — APRÈS le
# premier commit du dépôt de données, dont le premier porte l'empreinte : il ne pouvait
# pas y entrer, et `git status` montrait `?? instance/` sur chaque brain neuf (issue #22).
#
# Ici, sur un dépôt qui a déjà son premier commit :
#   - un réglage absent (ni `instance/doctor/<nom>`, ni l'ancien `workspace/.<nom>`) se
#     pose par l'outil du doctor (`--poser`) — jamais par-dessus un réglage existant ;
#   - les réglages présents et non suivis se commitent à part, par chemins :
#     `config: les réglages du doctor (brain init)`.
# Relancé : rien à poser, rien à commiter — il ne dit rien. Sans dépôt, sans commit, ou
# sans doctor livré : rien.

brain_reglages_doctor() {
  local brain="$1" prog="$2" paire outil nom
  local -a reglages=()
  git -C "$brain" rev-parse -q --verify HEAD >/dev/null 2>&1 || return 0
  for paire in "convention_commits|convention-commits-depuis" "liens_morts|liens-morts-seuil"; do
    outil="$prog/brain-engine/doctor/${paire%%|*}.py"; nom="${paire#*|}"
    if [[ ! -e "$brain/instance/doctor/$nom" && ! -e "$brain/workspace/.$nom" && -f "$outil" ]]; then
      python3 "$outil" --brain "$brain" --poser >/dev/null 2>&1 \
        || echo "⚠️  le réglage $nom du doctor n'a pas pu se poser — le doctor le posera à sa première passe"
    fi
    if [[ -f "$brain/instance/doctor/$nom" ]] \
       && ! git -C "$brain" ls-files --error-unmatch "instance/doctor/$nom" >/dev/null 2>&1; then
      reglages+=("instance/doctor/$nom")
    fi
  done
  (( ${#reglages[@]} )) || return 0
  if git -C "$brain" add -- "${reglages[@]}" >/dev/null 2>&1 \
     && git -C "$brain" commit -q -m "config: les réglages du doctor (brain init)" -- "${reglages[@]}" >/dev/null 2>&1; then
    echo "✅ les réglages du doctor commités : ${reglages[*]#instance/doctor/}"
  else
    echo "⚠️  les réglages du doctor ne sont pas commités — à faire : git -C $brain commit -- instance/doctor/"
    return 1
  fi
}
