# brain-distribuable: oui
# premieres N — les N premières lignes, et le reste lu sans être montré.
#
# `| head -N` ferme le tuyau pendant que la commande en amont écrit encore :
# SIGPIPE, et sous `set -o pipefail` + `-e` le script meurt sans un mot — mesuré
# 5 fois sur 300 dans sync-template.sh. `premieres` lit tout : rien n'écrit
# jamais dans un tuyau fermé.
#
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/premieres.sh"
#   commande | premieres 5
premieres() { head -n "$1"; cat >/dev/null; }
