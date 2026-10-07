#!/usr/bin/env bash
# brain-distribuable: oui  # des scripts distribuables le sourcent
# python.sh — Le python3 des scripts est celui du venv de brain-engine
#
# Usage :
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"
#
# Principe : un script qui appelle `python3` nu prend le python du systeme, qui
# n a ni `core` (myeline), ni numpy, ni pymysql. Sur une ancienne machine ça marchait
# par accident, grace a des paquets --user sous ~/.local/lib/python3.12 — un
# chemin qui porte la version de Python, donc invisible des qu elle change.
# C est tombe au passage a Python 3.14. [M09 § 2.8]
#
# On met le venv en tete du PATH : tous les `python3` du script (et de ses
# enfants) le trouvent. Sans venv (fork, machine neuve), rien ne change.

# Installé par un paquet (`pipx install brain-cortex`), le programme vit DANS un venv —
# celui de pipx, qui porte ses dépendances : le programme est marqué, et un parent
# porte `pyvenv.cfg`. C'est son python3 qui sert ; il n'y a pas de venv à côté du
# moteur, et il ne s'en crée pas. Sans la marque, rien ne change.
_brain_prog="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
_brain_venv=""
if [[ -e "$_brain_prog/.cortex-programme" ]]; then
  _d="$_brain_prog"
  while [[ "$_d" != "/" && -n "$_d" ]]; do
    if [[ -f "$_d/pyvenv.cfg" && -x "$_d/bin/python3" ]]; then _brain_venv="$_d"; break; fi
    _d="$(dirname "$_d")"
  done
  unset _d
fi
[[ -n "$_brain_venv" ]] || _brain_venv="${BRAIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}/brain-engine/.venv"
if [[ -x "$_brain_venv/bin/python3" ]]; then
  PATH="$_brain_venv/bin:$PATH"
fi
unset _brain_venv _brain_prog
