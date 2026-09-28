#!/usr/bin/env bash
# brain-distribuable: oui
# bsi-query.sh — Requêtes BSI via db.py (backend: sqlite ou dolt selon .env.local)
#
# Usage :
#   bsi-query.sh open          → liste les claims open (sess_id | scope | opened_at | age_h)
#   bsi-query.sh stale         → claims open depuis > 4h
#   bsi-query.sh count-open    → nombre de claims open (entier, stdout)
#   bsi-query.sh count-stale   → nombre de claims stale (entier, stdout)
#   bsi-query.sh signals       → signaux pending (CHECKPOINT | HANDOFF | BLOCKED_ON)
#   bsi-query.sh health        → dernière session : health_score + type
#   bsi-query.sh peers         → claims open sur toutes les instances (SSH)
#
# Backend : db.py (lit BRAIN_DB_BACKEND depuis .env.local — dolt ou sqlite)
# Sécurité : lecture seule — aucune écriture
#
# Exit codes :
#   0 = succès (même si 0 résultats)
#   1 = DB inaccessible
#   2 = erreur Python

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CMD="${1:-help}"

# ── Commande peers : interroge les instances distantes via SSH ─────────
if [[ "$CMD" == "peers" ]]; then
    COMPOSE_LOCAL="$BRAIN_ROOT/brain-compose.local.yml"
    MACHINE=$(python3 -c "
import yaml
with open('$COMPOSE_LOCAL') as f:
    print(yaml.safe_load(f).get('machine', 'unknown'))
" 2>/dev/null || echo "unknown")

    echo "🖥  $MACHINE (local)"
    # 🔴 On APPELLE `open` au lieu de redire sa requete. La version precedente
    # dupliquait le SELECT ici, et les deux ont diverge le jour ou `open` a
    # appris a afficher l'expiration [24/09] : `peers` continuait d'annoncer un
    # age nu, c'est-a-dire l'indicateur qui avait justement produit une fausse
    # alerte. Deux endroits qui disent la meme chose finissent par ne plus la
    # dire pareil — c'est la famille de.
    local_out=$("$0" open 2>/dev/null) || true
    if [[ -n "${local_out// }" ]]; then echo "$local_out"; else echo "  (aucun claim ouvert)"; fi

    # Interroger chaque peer
    python3 -c "
import os, yaml, subprocess, sys
sys.path.insert(0, '$BRAIN_ROOT/scripts/lib')
from pair import racine_distante
with open('$COMPOSE_LOCAL') as f:
    c = yaml.safe_load(f)
peers = c.get('peers', {})
for name, info in peers.items():
    if not info.get('active', False):
        continue
    url = info.get('url', '')
    host = url.replace('http://','').replace('https://','').split(':')[0]
    # Le compte SSH se lit dans la declaration du peer, sinon le sien : il etait
    # ecrit en dur au nom de l'owner (la regle de bsi-peer-poll.sh).
    user = info.get('ssh_user') or os.environ.get('USER') or 'root'
    try:
        racine = racine_distante(info, '$BRAIN_ROOT')
    except ValueError as e:
        print(f'REFUS:{name}:{e}')
        continue
    print(f'PEER:{name}:{host}:{user}:{racine}')
" 2>/dev/null | while IFS=: read -r genre name host user racine; do
        if [[ "$genre" == REFUS ]]; then
            echo ""
            echo "💻 $name — ⚠️  sauté : $host${user:+:$user}"
            continue
        fi
        echo ""
        echo "💻 $name ($host)"
        # 🔴 `bash -lc` est obligatoire — eprouve le 23/09 contre le laptop Omarchy.
        # `ssh hote "commande"` lance un shell NON interactif et NON-login : il ne
        # lit ni `.bashrc` ni `.bash_profile`, donc le peer travaille sans son
        # environnement. Le laptop y perdait son `PYTHONPATH` vers le CORE de
        # Myeline, `db.py` levait un ImportError, et le `2>/dev/null` d'avant
        # l'avalait : le desktop affichait une section vide comme s'il n'y avait
        # aucune session, alors qu'il y en avait une.
        erreur=$(mktemp)
        # 🔴 `|| code=$?` et non `code=$?` sur la ligne suivante : ce script tourne
        # sous `set -euo pipefail` (ligne 22). Une affectation dont la substitution
        # echoue TUE le script — eprouve le 23/09 contre une IP morte : le garde-fou
        # ci-dessous etait ecrit, et jamais atteint. Le script sortait en 255, sans
        # un mot, apres avoir affiche le nom du peer. Un correctif qu'on n'a pas vu
        # se declencher n'en est pas un.
        code=0
        result=$(ssh -o BatchMode=yes -o ConnectTimeout=3 "$user@$host" \
            "bash -lc \"cd $racine && bash scripts/bsi-query.sh open\"" 2>"$erreur") || code=$?
        if [[ $code -ne 0 ]]; then
            # 🔴 Un peer MUET n'est pas un peer VIDE — la confusion que
            # nomme, et que l'ancien message (« aucun claim ouvert OU machine
            # injoignable ») affichait sans jamais trancher.
            echo "  ⚠️  injoignable ou en erreur (code $code) — ce n'est PAS « aucune session »"
            sed 's/^/     /' "$erreur" | tail -3
        elif [[ -n "${result// }" ]]; then
            echo "$result"
        else
            echo "  (aucun claim ouvert — le peer a repondu)"
        fi
        rm -f "$erreur"
    done
    exit 0
fi

# ── Toutes les autres commandes via db.py ──────────────────────────────
python3 - "$BRAIN_ROOT" "$CMD" <<'PYEOF'
import sys, os

brain_root = sys.argv[1]
cmd = sys.argv[2] if len(sys.argv) > 2 else "help"

sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db

# 🔴 L'age et l'expiration sont DEUX choses, et les confondre a produit une
# fausse alerte le 24/09 : le laptop a annonce deux claims du desktop « ont
# depasse leur TTL » en lisant l'age affiche ici. L'un venait d'etre `touch`
# trois minutes plus tot. `close-stale` lisait deja `expires_at` — cet affichage
# ne l'avait jamais suivi.
#
# Le calcul se fait en PYTHON, pas en SQL : imbriquer un COALESCE dans un
# INTERVAL casserait le traducteur SQLite du CORE (sa regex s'arrete a la
# premiere parenthese fermante), et ce script tourne sur les deux backends.
from datetime import datetime, timedelta, timezone

def _dt(v):
    """Un horodatage rendu par Dolt (datetime) ou par SQLite (texte)."""
    if v is None or isinstance(v, datetime):
        return v
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(v)[:26], f)
        except ValueError:
            continue
    return None

def _echeance(r):
    """Quand ce claim expire VRAIMENT, et sur quelle base on l'a su.

    `expires_at` fait foi : c'est lui que `touch` repousse. On ne retombe sur
    `opened_at + ttl_hours` que s'il est absent — et on le DIT, parce qu'un
    repli silencieux est ce qui a produit la fausse alerte.
    """
    exp = _dt(r.get("expires_at"))
    if exp:
        return exp, ""
    ouv = _dt(r.get("opened_at"))
    if not ouv:
        return None, " (echeance inconnue)"
    return ouv + timedelta(hours=float(r.get("ttl_hours") or 4)), " (deduit du ttl)"

def _ligne(r):
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    ouv = _dt(r.get("opened_at"))
    age = f"{(maintenant - ouv).total_seconds() / 3600:.1f}h" if ouv else "?"
    ech, note = _echeance(r)
    if ech is None:
        etat = "echeance inconnue"
    else:
        reste = (ech - maintenant).total_seconds() / 3600
        etat = f"expire dans {reste:.1f}h" if reste >= 0 else f"EXPIRE depuis {-reste:.1f}h"
    return f"{r['sess_id']} | {r['scope']} | {r['opened_at']} UTC | age {age} | {etat}{note}"

if cmd == "open":
    rows = db.query("""
        SELECT sess_id, scope, opened_at, expires_at, ttl_hours
        FROM claims WHERE status = 'open'
        ORDER BY opened_at DESC
    """)
    for r in rows:
        print(_ligne(r))

elif cmd == "stale":
    # Le seuil de 4 h code en dur a disparu : il ignorait `ttl_hours` ET
    # `expires_at`, donc il declarait stale toute session `pilote` de plus de
    # 4 h alors que son TTL est de 12. etait applique dans
    # `close-stale` et jamais propage ici.
    rows = db.query("""
        SELECT sess_id, scope, opened_at, expires_at, ttl_hours
        FROM claims WHERE status = 'open'
        ORDER BY opened_at DESC
    """)
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    stales = [r for r in rows
              if (_echeance(r)[0] is not None and _echeance(r)[0] < maintenant)]
    for r in sorted(stales, key=lambda x: _echeance(x)[0]):
        print(_ligne(r))

elif cmd == "count-open":
    print(db.count("claims", "status = 'open'"))

elif cmd == "count-stale":
    # Le MEME critere que `stale`, par la meme fonction : l echeance du claim.
    # Il comptait « ouvert depuis plus de 4 h » — le seuil que `stale` avait
    # abandonne, et qui declarait perimee toute session `pilote` (TTL 12 h) des
    # sa quatrieme heure. Deux criteres pour un meme mot finissent toujours par
    # se contredire.
    rows = db.query("""
        SELECT sess_id, opened_at, expires_at, ttl_hours
        FROM claims WHERE status = 'open'
    """)
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    print(sum(1 for r in rows
              if _echeance(r)[0] is not None and _echeance(r)[0] < maintenant))

elif cmd == "signals":
    rows = db.query("""
        SELECT sig_id, type, from_sess, to_sess, projet, payload
        FROM signals
        WHERE state = 'pending'
          AND type IN ('CHECKPOINT', 'HANDOFF', 'BLOCKED_ON')
        ORDER BY created_at DESC
    """)
    for r in rows:
        print(f"{r['sig_id']} | {r['type']} | {r['from_sess']} → {r['to_sess']} | {r['projet']}")

elif cmd == "health":
    row = db.query_one("""
        SELECT sess_id, date, type, health_score, cold_start_kpi_pass
        FROM sessions
        ORDER BY date DESC, sess_id DESC
        LIMIT 1
    """)
    if row:
        kpi = {1: '✅', 0: '❌'}.get(row.get('cold_start_kpi_pass'), '—')
        print(f"{row['sess_id']} | {row['type']} | health={row['health_score']} | cold_start={kpi}")
    else:
        print("aucune session dans la DB")

else:
    print("Usage: bsi-query.sh open|stale|count-open|count-stale|signals|health|peers", file=sys.stderr)
    sys.exit(0)
PYEOF
