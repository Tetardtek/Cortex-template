#!/bin/bash
# brain-distribuable: oui
# brain-status.sh — l'ancien nom de `brain etat`, gardé pour qui l'appelle encore.
# Lecture seule. Aucune écriture.
#
# Usage :
#   brain-status.sh          → brain etat (le résumé)
#   brain-status.sh claims   → brain sessions (les sessions ouvertes ici)
#   brain-status.sh locks    → brain etat --verrous
#   brain-status.sh signals  → bsi-signal.sh inbox
#
# Il lisait `claims/` et `locks/`, que plus rien n'écrit depuis que le BSI vit en base : il
# répondait « (aucun) » à une session ouverte, et mourait hors d'un dépôt git (un programme
# installé par le paquet). Il relaie désormais à ceux qui savent.

set -euo pipefail
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-all}" in
  all)     exec python3 "$ICI/etat.py" ;;
  claims)  exec python3 "$ICI/sessions.py" ;;
  locks)   exec python3 "$ICI/etat.py" --verrous ;;
  signals) exec bash "$ICI/bsi-signal.sh" inbox ;;
  *)
    echo "Usage : brain-status.sh [all|claims|locks|signals] — le verbe : brain etat" >&2
    exit 1
    ;;
esac
