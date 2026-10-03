#!/usr/bin/env bash
# brain-distribuable: oui
# _vue.sh — la vue des agents suit le checkout. Sourcé par post-checkout et post-merge.
#
# Quand `noyau/agents/` existe, `agents/` est une vue (des liens, ignorée par git) :
# un worktree neuf, une branche, une fusion la laissent vide ou en retard. On la
# reconstruit sur place, avec le `vue.py` de CE checkout. Sans noyau, rien.
vue_suit_le_checkout() {
  [ -d "$BRAIN_WT/noyau/agents" ] || return 0
  [ -f "$BRAIN_WT/scripts/vue.py" ] || return 0
  source "$BRAIN_MAIN/scripts/lib/python.sh" 2>/dev/null || true
  if ! BRAIN_ROOT="$BRAIN_WT" python3 "$BRAIN_WT/scripts/vue.py" --construire >/dev/null 2>&1; then
    echo "⚠️  la vue des agents ne s'est pas reconstruite — bash scripts/brain vue --construire" >&2
  fi
}
