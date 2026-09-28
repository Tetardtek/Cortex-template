#!/usr/bin/env bash
# brain-distribuable: oui  # des scripts distribuables le sourcent
# python.sh — Le python3 des scripts est celui du venv de brain-engine
#
# Usage :
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"
#
# Principe : un script qui appelle `python3` nu prend le python du systeme, qui
# n a ni `core` (myeline), ni numpy, ni pymysql. Sur le fixe Pop!_OS ça marchait
# par accident, grace a des paquets --user sous ~/.local/lib/python3.12 — un
# chemin qui porte la version de Python, donc invisible des qu elle change.
# C est tombe a la migration Omarchy (Python 3.14). [M09 § 2.8]
#
# On met le venv en tete du PATH : tous les `python3` du script (et de ses
# enfants) le trouvent. Sans venv (fork, machine neuve), rien ne change.

_brain_venv="${BRAIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}/brain-engine/.venv"
if [[ -x "$_brain_venv/bin/python3" ]]; then
  PATH="$_brain_venv/bin:$PATH"
fi
unset _brain_venv
