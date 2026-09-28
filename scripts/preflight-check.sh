#!/bin/bash
# brain-distribuable: oui
# preflight-check.sh — BSI-v3-8 Pre-flight check (BRAIN-036)
# Valide les 6 conditions avant qu'un satellite commence à écrire.
# Backend : db.py (sqlite ou dolt selon .env.local)
#
# Usage :
#   preflight-check.sh check  <sess_id> <filepath>  → 6 checks, exit 0 = go
#   preflight-check.sh fail   <sess_id>             → enregistre un échec (circuit breaker)
#   preflight-check.sh reset  <sess_id>             → reset fail counter après succès
#   preflight-check.sh status <sess_id>             → état circuit breaker
#
# Exit codes (check) :
#   0 = go — toutes les vérifications passent
#   1 = scope violation   — filepath hors scope déclaré
#   2 = fichier locké     — attendre ou signal BLOCKED_ON
#   3 = circuit breaker   — arrêt + signal BLOCKED_ON pilote
#   4 = claim invalide    — claim non-open ou introuvable
#   5 = zone violation    — filepath zone:kernel, claim hors scope kernel (soft lock)
#   6 = mauvaise branche  — theme_branch mismatch

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CMD="${1:-help}"
shift || true

# Read max_consecutive_fails from brain-compose.yml (bash, before Python)
MAX_FAILS=$(grep -A5 'circuit_breaker:' "$BRAIN_ROOT/brain-compose.yml" 2>/dev/null \
  | grep 'max_consecutive_fails:' | sed 's/^[^:]*: *//' | awk '{print $1}' | head -1 || echo 3)
MAX_FAILS="${MAX_FAILS:-3}"

# Read kerneluser from brain-compose.yml
KERNELUSER=$(grep '^kerneluser:' "$BRAIN_ROOT/brain-compose.yml" 2>/dev/null \
  | sed 's/^[^:]*: *//' | tr -d '"' | head -1 || echo "false")

# Current git branch
CURRENT_BRANCH=$(git -C "$BRAIN_ROOT" branch --show-current 2>/dev/null || echo "")

python3 - "$BRAIN_ROOT" "$CMD" "$MAX_FAILS" "$KERNELUSER" "$CURRENT_BRANCH" "$@" <<'PYEOF'
import sys
import os

brain_root = sys.argv[1]
cmd = sys.argv[2] if len(sys.argv) > 2 else "help"
max_fails = int(sys.argv[3]) if len(sys.argv) > 3 else 3
kerneluser = sys.argv[4] if len(sys.argv) > 4 else "false"
current_branch = sys.argv[5] if len(sys.argv) > 5 else ""
args = sys.argv[6:]

sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db

# Chemins zone:kernel — synchronisés avec KERNEL.md
KERNEL_SCOPES = [
    "agents/", "profil/", "scripts/",
    "KERNEL.md", "CLAUDE.md", "PATHS.md",
    "brain-compose.yml", "brain-constitution.md", "BRAIN-INDEX.md"
]


def is_kernel_path(filepath):
    return any(filepath.startswith(ks) or filepath == ks for ks in KERNEL_SCOPES)


def scope_covers_kernel(scope):
    scope_entries = scope.split()
    return any(
        ks.startswith(se) or se.startswith(ks)
        for ks in KERNEL_SCOPES for se in scope_entries
    )


def cmd_check():
    if len(args) < 2:
        print("❌ Usage: preflight-check.sh check <sess_id> <filepath>", file=sys.stderr)
        sys.exit(4)

    sess_id = args[0]
    filepath = args[1]

    print(f"🛫 PRE-FLIGHT — {sess_id} → {filepath}")
    print("")

    # CHECK 1 — Claim status
    claim = db.query_one(
        "SELECT status, scope, parent_sess, theme_branch FROM claims WHERE sess_id = %s",
        (sess_id,)
    )
    if not claim:
        print(f"❌ CHECK 1 — Claim introuvable : {sess_id}")
        sys.exit(4)
    if claim['status'] == 'paused':
        print(f"❌ CHECK 1 — Claim en pause : {sess_id}")
        print(f"   → human-gate-ack.sh resume {sess_id}")
        sys.exit(4)
    if claim['status'] == 'waiting_human':
        print(f"❌ CHECK 1 — Gate:human actif : {sess_id}")
        print(f"   → human-gate-ack.sh approve|reject {sess_id}")
        sys.exit(4)
    if claim['status'] != 'open':
        print(f"❌ CHECK 1 — Claim non-open : {claim['status']}")
        sys.exit(4)
    print("✅ CHECK 1 — Claim open")

    # CHECK 1b — Cascade pause (parent paused = enfant bloqué)
    parent_id = claim.get('parent_sess')
    if parent_id:
        parent = db.query_one(
            "SELECT status FROM claims WHERE sess_id = %s", (parent_id,)
        )
        if parent:
            if parent['status'] == 'paused':
                print(f"❌ CHECK 1b — Parent en pause : {parent_id}")
                print(f"   → human-gate-ack.sh resume {parent_id}")
                sys.exit(4)
            if parent['status'] == 'failed':
                print(f"❌ CHECK 1b — Parent failed : {parent_id} — satellite orphelin")
                sys.exit(4)
        print("✅ CHECK 1b — Parent ok")

    # CHECK 2 — Scope check
    claim_scope = claim.get('scope', '')
    scope_ok = any(
        filepath.startswith(se) or filepath == se
        for se in claim_scope.split()
    )
    if not scope_ok:
        print(f"❌ CHECK 2 — Scope violation : {filepath} ∉ [{claim_scope}]")
        sys.exit(1)
    print("✅ CHECK 2 — Scope ok")

    # CHECK 3 — Zone check (soft lock kernel)
    if is_kernel_path(filepath):
        if not scope_covers_kernel(claim_scope):
            if kerneluser == "true":
                print(f"⚠️  CHECK 3 — Zone:kernel (kerneluser bypass) : {filepath}")
                print(f"   Scope [{claim_scope}] hors kernel — modification kernel sur confirmation humaine")
            else:
                print(f"❌ CHECK 3 — Zone violation : {filepath} est zone:kernel")
                print(f"   Scope déclaré [{claim_scope}] n'inclut pas de zone:kernel")
                sys.exit(5)
    if not is_kernel_path(filepath) or scope_covers_kernel(claim_scope):
        print("✅ CHECK 3 — Zone ok")

    # CHECK 4 — Lock check
    lock = db.query_one("""
        SELECT holder, expires_at FROM locks
        WHERE filepath = %s AND UTC_TIMESTAMP() < expires_at AND holder != %s
    """, (filepath, sess_id))
    if lock:
        print(f"❌ CHECK 4 — Fichier locké par : {lock['holder']} (expire : {lock['expires_at']})")
        sys.exit(2)
    print("✅ CHECK 4 — Lock ok")

    # CHECK 5 — Circuit breaker
    cb = db.query_one(
        "SELECT COALESCE(fail_count, 0) AS fc FROM circuit_breaker WHERE sess_id = %s",
        (sess_id,)
    )
    fail_count = cb['fc'] if cb else 0
    if fail_count >= max_fails:
        print(f"❌ CHECK 5 — Circuit breaker : {fail_count}/{max_fails} fails consécutifs")
        print(f"   → Signal BLOCKED_ON pilote requis — reset manuel après résolution")
        sys.exit(3)
    print(f"✅ CHECK 5 — Circuit breaker ok ({fail_count}/{max_fails})")

    # CHECK 6 — Theme branch
    theme_branch = claim.get('theme_branch') or ''
    if theme_branch:
        if current_branch != theme_branch:
            print(f"❌ CHECK 6 — Mauvaise branche : sur '{current_branch}', attendu '{theme_branch}'")
            print(f"   git checkout {theme_branch}")
            sys.exit(6)
    print(f"✅ CHECK 6 — Branch ok ({theme_branch or 'main'})")

    print("")
    print("🟢 PRE-FLIGHT PASS — go")


def cmd_fail():
    if not args:
        print("❌ Usage: preflight-check.sh fail <sess_id>", file=sys.stderr)
        sys.exit(2)

    sess_id = args[0]

    # Upsert circuit breaker
    db.execute("""
        REPLACE INTO circuit_breaker (sess_id, fail_count, last_fail_at, updated_at)
        VALUES (%s,
            COALESCE((SELECT fail_count + 1 FROM circuit_breaker WHERE sess_id = %s), 1),
            UTC_TIMESTAMP(), UTC_TIMESTAMP())
    """, (sess_id, sess_id))

    cb = db.query_one("SELECT fail_count FROM circuit_breaker WHERE sess_id = %s", (sess_id,))
    fail_count = cb['fail_count'] if cb else 1
    print(f"⚠️  Fail enregistré : {fail_count}/{max_fails} ({sess_id})")
    if fail_count >= max_fails:
        print("🔴 Circuit breaker déclenché — signal BLOCKED_ON pilote")


def cmd_reset():
    if not args:
        print("❌ Usage: preflight-check.sh reset <sess_id>", file=sys.stderr)
        sys.exit(2)

    db.execute("DELETE FROM circuit_breaker WHERE sess_id = %s", (args[0],))
    print(f"✅ Circuit breaker reset : {args[0]}")


def cmd_status():
    if not args:
        print("❌ Usage: preflight-check.sh status <sess_id>", file=sys.stderr)
        sys.exit(2)

    sess_id = args[0]
    cb = db.query_one(
        "SELECT COALESCE(fail_count, 0) AS fc FROM circuit_breaker WHERE sess_id = %s",
        (sess_id,)
    )
    fail_count = cb['fc'] if cb else 0
    if fail_count >= max_fails:
        print(f"🔴 Circuit breaker déclenché : {fail_count}/{max_fails} ({sess_id})")
    else:
        print(f"✅ Circuit breaker ok : {fail_count}/{max_fails} ({sess_id})")


def cmd_help():
    print("Usage : preflight-check.sh <check|fail|reset|status>")
    print("")
    print("  check  <sess_id> <filepath>  → 6 checks avant écriture (exit 0=go)")
    print("  fail   <sess_id>             → enregistre un échec (circuit breaker)")
    print("  reset  <sess_id>             → reset fail counter après succès")
    print("  status <sess_id>             → état circuit breaker")
    sys.exit(1)


commands = {
    "check": cmd_check,
    "fail": cmd_fail,
    "reset": cmd_reset,
    "status": cmd_status,
    "help": cmd_help,
}

fn = commands.get(cmd, cmd_help)
fn()
PYEOF
