#!/bin/bash
# brain-distribuable: oui
# brain-setup.sh — l'ancien nom de `brain init`, gardé comme redirection.
#
# Usage (inchangé) : [BRAIN_MACHINE=laptop] [PROJECTS_ROOT=~/Dev] bash scripts/brain-setup.sh [brain_name] [brain_root] [--sans-service] [--reecrire-claude-md]
#
# Les forks, leur doc et leurs habitudes l'appellent : il passe tout au corps de
# `brain init` (`scripts/brain-init.sh`, que `scripts/brain init` lance aussi) —
# mêmes arguments, même environnement.
exec bash "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/brain-init.sh" "$@"
