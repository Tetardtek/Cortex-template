#!/bin/bash
# brain-distribuable: oui
# file-lock.sh — Mutex fichier BSI-v3-7 (BRAIN-036)
# Empêche deux satellites d'écrire simultanément dans le même fichier.
#
# ── Deux chemins, et le script dit lequel a servi — 10/09, decision de l'owner ────
#
# Mesure du 10/09 : ce script posait ses verrous en SQL direct, sans jamais
# consulter les autres machines. La verification croisee existe — elle est dans
# `POST /bsi/locks`, cote serveur — mais AUCUN appelant ne l'empruntait. Deux
# postes pouvaient donc verrouiller le meme fichier sans se voir, et le rsync
# manuel de `brain-dolt-sync.sh` n'y change rien : ce n'est pas une replication.
#
# L'owner a tranche : les verrous DOIVENT coordonner plusieurs machines.
#
# Mais ce script part dans le template (`brain-distribuable: oui`), et un fork
# n'a pas forcément de brain-engine qui tourne. « HTTP a la place » aurait
# casse une garantie du produit distribue. Donc :
#
#     moteur joignable  -> POST /bsi/locks : peers consultes, 409 si tenu
#                          ailleurs, et diffusion WebSocket vers le Dashboard
#     moteur eteint     -> repli SQL local, ET ON LE DIT
#
# Le repli ne coordonne rien. Il ne doit donc jamais reussir en SILENCE : c'est
# exactement le defaut qu'on vient de mesurer. Un verrou pris en repli s'annonce
# comme local, pour que celui qui le lit sache ce qu'il n'a pas.
#
# Backend du repli : db.py (sqlite ou dolt selon .env.local)
#
# Usage :
#   file-lock.sh acquire <filepath> <sess-id> [ttl_minutes]  → acquiert le lock
#   file-lock.sh release <filepath> <sess-id>                → libère le lock
#   file-lock.sh check   <filepath>                          → qui détient le lock ?
#   file-lock.sh list                                        → tous les locks actifs
#   file-lock.sh cleanup                                     → supprime les locks expirés
#
# Exit codes :
#   0 = succès
#   1 = lock déjà détenu par une autre session (acquire)
#   2 = erreur (sess-id incorrect pour release, fichier introuvable)

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CMD="${1:-help}"
shift || true

python3 - "$BRAIN_ROOT" "$CMD" "$@" <<'PYEOF'
import sys
import os

brain_root = sys.argv[1]
cmd = sys.argv[2] if len(sys.argv) > 2 else "help"
args = sys.argv[3:]

sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db
# La frontière d'un verrou, écrite une fois dans le CORE — ce script en
# portait cinq copies.
from core.bsi import VERROU_ACTIF, VERROU_EXPIRE

import json
import urllib.error
import urllib.request

MOTEUR = "http://127.0.0.1:%s" % os.getenv("BRAIN_PORT", "7700")


def par_le_moteur(methode, chemin, corps=None, timeout=3):
    """(code, donnees) si le moteur repond ; None s'il ne repond pas.

    La distinction est le coeur du mecanisme : `None` veut dire « je n'ai pas
    pu demander », et c'est ce qui autorise le repli. Un code HTTP — meme 409 —
    veut dire « le moteur a repondu », et sa reponse fait autorite : elle tient
    compte des peers, ce que le repli ne peut pas faire.

    Les routes /bsi/ passent en localhost bypass : aucun jeton ici, et rien a
    lire dans MYSECRETS.
    """
    donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
    entetes = {"Content-Type": "application/json"} if donnees else {}
    requete = urllib.request.Request(MOTEUR + chemin, data=donnees,
                                     method=methode, headers=entetes)
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            brut = reponse.read()
            return reponse.status, (json.loads(brut) if brut else None)
    except urllib.error.HTTPError as exc:
        brut = exc.read()
        try:
            return exc.code, json.loads(brut) if brut else None
        except Exception:
            return exc.code, None
    except Exception:
        return None                      # injoignable — le repli est legitime


MANQUE = {
    "acquisition": "Le Dashboard n'a PAS ete notifie. Les verrous des autres\n"
                   "    machines ont ete lus dans la base commune.",
    "liberation":  "Le Dashboard n'a PAS ete notifie : il croira le verrou\n"
                   "    tenu jusqu'a son expiration.",
}


def avertir_repli(verbe):
    """Dire ce qui manque, pas seulement qu'on est en repli.

    « Mode degrade » ne renseigne personne. Ce qui compte est ce que le repli
    ne fait PAS — et ce n'est pas la meme chose selon le geste.
    """
    print(f"⚠️  moteur injoignable ({MOTEUR}) — {verbe} en repli LOCAL.")
    print(f"    {MANQUE[verbe]}")


def cmd_acquire():
    if len(args) < 2:
        print("❌ Usage: file-lock.sh acquire <filepath> <sess-id> [ttl_min]", file=sys.stderr)
        sys.exit(2)

    filepath = args[0]
    sess_id = args[1]
    ttl = int(args[2]) if len(args) > 2 else 60

    # ── Chemin gouverne : le moteur consulte les peers avant d'accorder ──────
    reponse = par_le_moteur("POST", "/bsi/locks",
                            {"filepath": filepath, "holder": sess_id,
                             "ttl_min": ttl})
    if reponse is not None:
        code, donnees = reponse
        if code == 409:
            motif = (donnees or {}).get("detail", "deja detenu")
            print(f"🔴 LOCK — {filepath}")
            print(f"   {motif}")
            print("")
            print("   Refus prononce par le moteur, sur les verrous de tout le reseau.")
            sys.exit(1)
        if 200 <= code < 300:
            print(f"✅ Lock acquis : {filepath}")
            print(f"   Session  : {sess_id}")
            print(f"   TTL      : {ttl} min")
            # 🔴 Cette ligne affirmait « peers consultes » sur TOUTE reponse
            # 2xx. Or le moteur avalait un peer injoignable en silence et
            # accordait quand meme : l affirmation venait d ici, le silence de
            # la-bas, et personne ne pouvait le savoir.
            #
            # Le moteur rend desormais `peers_injoignables`. Un moteur d avant
            # ce changement ne rend pas la cle du tout — on ne peut donc pas
            # distinguer « aucun peer muet » de « moteur qui ne sait pas le
            # dire ». Le `None` par defaut separe les deux cas, et le doute ne
            # s affiche pas comme une certitude.
            # Le moteur dit les bases qu il a lues (`reseau`) : main et chaque
            # branche satellite. Un moteur d avant ne le dit pas.
            reseau = (donnees or {}).get("reseau")
            if reseau:
                print(f"   Chemin   : moteur — verrous du reseau lus ({', '.join(reseau)}), Dashboard notifie")
                return
            muets = (donnees or {}).get("peers_injoignables")
            if muets:
                print(f"   ⚠️  Chemin : moteur — {len(muets)} peer(s) NON consulte(s) : "
                      f"{', '.join(muets)}")
                print("       Ce lock n engage pas les machines qui n ont pas repondu.")
            elif muets is None:
                print("   Chemin   : moteur — Dashboard notifie")
                print("   ⚠️  ce moteur ne dit pas s il a joint les peers.")
            else:
                print("   Chemin   : moteur — peers consultes, Dashboard notifie")
            return
        # Toute autre reponse est une VRAIE erreur du moteur, pas une absence :
        # se rabattre ici masquerait un defaut au lieu de le montrer.
        print(f"❌ le moteur refuse la demande (HTTP {code}) : "
              f"{(donnees or {}).get('detail', 'sans motif')}", file=sys.stderr)
        sys.exit(2)

    avertir_repli("acquisition")

    # Le verrou actif d un autre, sur n importe quelle machine du reseau : la
    # meme regle que le moteur, la meme fonction.
    existing = next((r for r in db.verrous_du_reseau("filepath = %s", (filepath,))
                     if r["holder"] != sess_id), None)

    if existing:
        print(f"🔴 LOCK — {filepath}")
        print(f"   Détenu par : {existing['holder']}")
        print(f"   Expire à   : {existing['expires_at']}")
        print(f"")
        print(f"   Attendre le release ou contacter : {existing['holder']}")
        sys.exit(1)

    # Delete old lock (expired or same holder) then insert fresh
    db.execute("DELETE FROM locks WHERE filepath = %s", (filepath,))
    db.execute("""
        INSERT INTO locks (filepath, holder, claimed_at, expires_at, ttl_min)
        VALUES (%s, %s, UTC_TIMESTAMP(), DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s MINUTE), %s)
    """, (filepath, sess_id, ttl, ttl))

    row = db.query_one("SELECT expires_at FROM locks WHERE filepath = %s", (filepath,))
    expires = row['expires_at'] if row else '?'

    print(f"✅ Lock acquis : {filepath}")
    print(f"   Session  : {sess_id}")
    print(f"   Expire   : {expires}")
    print(f"   Chemin   : repli — verrous du reseau lus ({', '.join(db.sources_des_verrous())})")


def cmd_release():
    if len(args) < 2:
        print("❌ Usage: file-lock.sh release <filepath> <sess-id>", file=sys.stderr)
        sys.exit(2)

    filepath = args[0]
    sess_id = args[1]

    # Meme regle qu'a l'acquisition : le moteur d'abord, parce qu'il diffuse la
    # liberation aux clients connectes. Le repli SQL, lui, relache un verrou que
    # le Dashboard croira tenu jusqu'a son expiration.
    import urllib.parse
    reponse = par_le_moteur(
        "DELETE",
        "/bsi/locks/%s?holder=%s" % (urllib.parse.quote(filepath),
                                     urllib.parse.quote(sess_id)))
    if reponse is not None:
        code, donnees = reponse
        if 200 <= code < 300:
            print(f"✅ Lock libere : {filepath}")
            print("   Chemin   : moteur — Dashboard notifie")
            return
        if code in (403, 404, 409):
            # Le moteur refuse : holder qui ne correspond pas, ou plus de lock.
            # Sa reponse fait autorite, on ne repasse pas derriere en SQL.
            print(f"🚨 Release refuse par le moteur : "
                  f"{(donnees or {}).get('detail', 'sans motif')}")
            sys.exit(2)
        print(f"❌ le moteur refuse la demande (HTTP {code})", file=sys.stderr)
        sys.exit(2)

    avertir_repli("liberation")

    row = db.query_one("SELECT holder FROM locks WHERE filepath = %s", (filepath,))

    if not row:
        print(f"ℹ️  Pas de lock actif sur : {filepath}")
        sys.exit(0)

    if row['holder'] != sess_id:
        print(f"🚨 Release refusé — lock détenu par : {row['holder']} (pas {sess_id})")
        sys.exit(2)

    db.execute("DELETE FROM locks WHERE filepath = %s AND holder = %s", (filepath, sess_id))
    print(f"✅ Lock libéré : {filepath}")
    print("   Chemin   : LOCAL — le Dashboard ne l'a pas appris")


def cmd_check():
    if len(args) < 1:
        print("❌ Usage: file-lock.sh check <filepath>", file=sys.stderr)
        sys.exit(2)

    filepath = args[0]

    row = db.query_one(f"""
        SELECT holder, expires_at,
               CASE WHEN {VERROU_ACTIF} THEN 'active' ELSE 'expired' END AS status
        FROM locks WHERE filepath = %s
    """, (filepath,))

    if not row:
        print(f"✅ Libre : {filepath}")
        sys.exit(0)

    if row['status'] == 'active':
        print(f"🔴 Locké : {filepath}")
        print(f"   Holder  : {row['holder']}")
        print(f"   Expire  : {row['expires_at']}")
    else:
        print(f"⚠️  Lock expiré (nettoyable) : {filepath}")
        print(f"   Ancien holder : {row['holder']}")


def cmd_list():
    rows = db.query(f"""
        SELECT filepath, holder, expires_at,
               CASE WHEN {VERROU_ACTIF} THEN 'actif' ELSE 'expiré' END AS status
        FROM locks ORDER BY claimed_at DESC
    """)

    if not rows:
        print("✅ Aucun lock actif")
        sys.exit(0)

    print("Locks actifs :")
    print("")
    for r in rows:
        icon = "🔴" if r['status'] == 'actif' else "⚠️ "
        print(f"  {icon} {r['status']} | {r['filepath']} | {r['holder']} | exp: {r['expires_at']}")


def cmd_cleanup():
    # Count expired locks
    row = db.query_one(f"SELECT COUNT(*) AS n FROM locks WHERE {VERROU_EXPIRE}")
    count = row['n'] if row else 0

    if count == 0:
        print("✅ Aucun lock expiré à nettoyer")
    else:
        # Un nettoyage est un événement : il se commite (sans `commit_msg`,
        # l'écriture restait dans le working set Dolt). Ignoré en SQLite.
        db.execute(f"DELETE FROM locks WHERE {VERROU_EXPIRE}",
                   commit_msg=f"bsi: {count} verrou(s) expire(s) nettoye(s)", tables=["locks"])
        print(f"✅ {count} lock(s) nettoyé(s)")


def cmd_help():
    print("Usage : file-lock.sh <acquire|release|check|list|cleanup>")
    print("")
    print("  acquire <filepath> <sess-id> [ttl_min]  → acquiert le lock (défaut: 60min)")
    print("  release <filepath> <sess-id>             → libère le lock")
    print("  check   <filepath>                       → état du lock")
    print("  list                                     → tous les locks actifs")
    print("  cleanup                                  → supprime les locks expirés")
    sys.exit(1)


commands = {
    "acquire": cmd_acquire,
    "release": cmd_release,
    "check": cmd_check,
    "list": cmd_list,
    "cleanup": cmd_cleanup,
    "help": cmd_help,
}

fn = commands.get(cmd, cmd_help)
fn()
PYEOF
