#!/usr/bin/env bash
# brain-distribuable: oui  # des scripts distribuables le sourcent
# donnees.sh — la racine de la DATA d'un script, quand le programme est ailleurs
#
# Usage :
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/donnees.sh"
#   BRAIN_ROOT="$(brain_donnees "$(cd "$(dirname "$0")/.." && pwd)")" || exit 1
#
# L'équivalent shell de `trouver_donnees()` (brain-engine/donnees.py), qui en
# est la définition — un test les tient d'accord. Sans la marque
# `.cortex-programme` à la racine du programme (un brain cloné par git, chaque fork, chaque
# banc d'essai), la position fait foi, comme avant : RIEN ne change. Avec elle,
# le programme est installé à part et la data se trouve :
#
#   BRAIN_ROOT, sinon le dossier courant en remontant jusqu'à
#   brain-compose.local.yml, sinon le brain déclaré par `brain init`
#   (${XDG_CONFIG_HOME:-~/.config}/brain-cortex/brain ; en repli `cortex-brain/`, le nom
#   de la v3.5.0). Rien : une erreur.
#
# `brain_donnees` ne lit pas `BRAIN_ROOT` sans la marque : les scripts qui la
# sourcent l'ignoraient, et un banc qui la pose pour un autre script ne doit
# pas les détourner.

brain_donnees() {  # <racine du programme> → la racine de la data, sur stdout
  local prog="$1" d pointeur declare
  if [[ ! -e "$prog/.cortex-programme" ]]; then
    printf '%s\n' "$prog"; return 0
  fi
  if [[ -n "${BRAIN_ROOT:-}" ]]; then
    if [[ -d "$BRAIN_ROOT" ]]; then printf '%s\n' "$BRAIN_ROOT"; return 0; fi
    echo "❌ BRAIN_ROOT=$BRAIN_ROOT ne désigne pas un dossier — le brain refuse de deviner une autre racine." >&2
    return 1
  fi
  d="$(pwd)"
  while :; do
    if [[ -f "$d/brain-compose.local.yml" ]]; then printf '%s\n' "$d"; return 0; fi
    [[ "$d" == "/" || -z "$d" ]] && break
    d="$(dirname "$d")"
  done
  for pointeur in "${XDG_CONFIG_HOME:-$HOME/.config}/brain-cortex/brain" \
                  "${XDG_CONFIG_HOME:-$HOME/.config}/cortex-brain/brain"; do
    if [[ -f "$pointeur" ]]; then
      declare="$(head -1 "$pointeur")"
      declare="${declare/#\~/$HOME}"
      if [[ -d "$declare" ]]; then printf '%s\n' "$declare"; return 0; fi
    fi
  done
  echo "❌ programme installé à part ($prog) et aucun brain trouvé : poser BRAIN_ROOT, lancer depuis le dossier du brain, ou en créer un — brain init <nom> <dossier>." >&2
  return 1
}

brain_env_local() {  # <racine de la data> → le chemin de la config locale du moteur
  # D'ordinaire `brain-engine/.env.local`. Quand `brain-engine/` de la data est un lien
  # vers un programme installé à part (marqué), le programme ne s'écrit pas : la config
  # est à la racine de la data (`.env.local`, tue par le `.gitignore` semé). L'équivalent
  # de `env_local()` (brain-engine/donnees.py).
  local d="$1" moteur prog
  moteur="$(readlink -f "$d/brain-engine" 2>/dev/null || true)"
  prog="${moteur%/*}"
  if [[ -L "$d/brain-engine" && -n "$moteur" && -e "$prog/.cortex-programme" ]]; then
    printf '%s\n' "$d/.env.local"
  else
    printf '%s\n' "$d/brain-engine/.env.local"
  fi
}

brain_env_local_declarer() {  # <racine de la data> → écrit la config locale si elle manque
  # `brain init` la déclare : `BRAIN_DB_BACKEND=dolt`, le défaut — sans elle, `db.py`
  # avertit à chaque appel (« BRAIN_DB_BACKEND non declare »). `dolt-setup.sh` l'écrit
  # déjà ; ceci la garantit quand il s'est arrêté avant (Dolt injoignable, pas de
  # systemd). Un fichier présent n'est JAMAIS touché. Sort 0 et dit le chemin s'il l'a
  # écrit, 1 s'il était là.
  local f
  f="$(brain_env_local "$1")"
  [[ -e "$f" || -L "$f" ]] && return 1
  mkdir -p "$(dirname "$f")"
  printf '%s\n' "# La config locale du moteur — écrite par brain init, jamais versionnée." \
    "# Le modèle commenté : brain-engine/.env.local.example" \
    "BRAIN_DB_BACKEND=dolt" > "$f"
  printf '%s\n' "$f"
}
