#!/usr/bin/env bash
# brain-distribuable: oui
# _racines.sh — les deux racines d'un hook git brain (sourcé, jamais lancé)
#
#   BRAIN_WT     l'arbre du COMMIT — ses fichiers, son KERNEL.md, ses docs
#   BRAIN_MAIN   le dépôt PRINCIPAL — le venv, .env.local, la base, la posture
#
# Dans le checkout principal les deux sont égales. Dans un worktree (une PR en
# cours), elles diffèrent : l'arbre du commit n'a ni venv, ni .env.local (tous
# deux gitignorés). Un hook qui les y cherchait lisait une base SQLite neuve
# créée sur place, ou s'abstenait (« base injoignable ») — et le garde de zone
# s'éteignait précisément là où passent toutes les PR.

BRAIN_WT="$(git rev-parse --show-toplevel)"
BRAIN_MAIN="$(cd "$BRAIN_WT" && cd "$(git rev-parse --git-common-dir)/.." && pwd)"
export BRAIN_WT BRAIN_MAIN

# Vrai quand le commit se fait ailleurs que dans le checkout principal.
brain_dans_un_worktree() { [[ "$BRAIN_WT" != "$BRAIN_MAIN" ]]; }
