#!/usr/bin/env bash
# brain-distribuable: oui
# (Etait `brain-rattachement: ponctuel` jusqu'au 27/09 : « le jour ou le boot
#  appellera `inbox`, cette ligne pourra sauter ». helloWorld 9.6 l'appelle
#  desormais — l'etiquette l'excluait du lock pour rien. Retiree.)
# bsi-signal.sh — emettre, relever et accuser les signaux entre sessions.
#
# La table `signals` existe depuis mars 2026, avec ses types, ses etats et son
# accuse de livraison. Deux sessions d'un même projet s'en sont servies, puis
# plus personne : `brain-status.sh` sait les LIRE, `brain-conciergerie.sh` sait
# les ARCHIVER, et **rien ne savait en EMETTRE**. Aucun ne traversait les
# machines non plus. C'est la famille a — une capacite
# declaree qu'aucun mecanisme n'alimente.
#
#   bsi-signal.sh send <destinataire> --type TYPE [--projet X] --payload "..."
#   bsi-signal.sh inbox [<destinataire>]     → ce qui m'attend, ici ET chez les peers
#   bsi-signal.sh outbox                     → ce que j'ai emis et qui n'est pas relu
#   bsi-signal.sh ack <sig_id>               → marquer delivered, meme chez un peer
#
# TYPE : READY_FOR_REVIEW · REVIEWED · BLOCKED_ON · HANDOFF · CHECKPOINT · INFO
#
# ── Ou vit un signal, et pourquoi ────────────────────────────────────────────
#
# Un signal est ecrit dans la base de CELUI QUI L'EMET, jamais poussee chez le
# destinataire. Le destinataire vient le relever, chez lui et chez ses peers.
#
# C'est le modele deja en place pour les claims (`bsi-query.sh peers`), et il a
# une propriete que l'inverse n'aurait pas : **on peut ecrire a une machine
# eteinte**. Deposer chez le destinataire demanderait qu'il soit joignable au
# moment de l'envoi — c'est-a-dire precisement quand on a le moins de raisons de
# le supposer.
#
# Le prix : relever sa boite interroge les peers par SSH, donc un peer muet doit
# se distinguer d'un peer sans message. Il se distingue — voir `inbox`.
#
# ── Adressage ────────────────────────────────────────────────────────────────
#
# `to_sess` accepte deux formes, toutes deux presentes dans les donnees :
#
#     prod@desktop                       une INSTANCE — stable, survit aux sessions
#     sess-20260923-1027-pilote          une SESSION precise — ephemere
#
# Ecrire a une instance est presque toujours ce qu'on veut : la session qui
# lira n'existe pas encore au moment ou on ecrit.
#
# Il n'ecrit rien hors de la base, et ne joint personne sauf pour `inbox`/`ack`
# sur un peer.

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_LOCAL="$BRAIN_ROOT/brain-compose.local.yml"
CMD="${1:-help}"
shift || true

TYPES="READY_FOR_REVIEW REVIEWED BLOCKED_ON HANDOFF CHECKPOINT INFO"

# ── Identite de cette instance ───────────────────────────────────────────────
mon_instance() {
  # Une seule regle, dans scripts/lib/instance.py — puis :
  # elle se plaint au lieu de rendre `inconnue@inconnue`.
  python3 "$BRAIN_ROOT/scripts/lib/instance.py" "$COMPOSE_LOCAL"
}

# ── Les peers declares, actifs seulement ─────────────────────────────────────
peers() {
  python3 - "$COMPOSE_LOCAL" "$BRAIN_ROOT" <<'PYEOF'
import os, sys, yaml
sys.path.insert(0, os.path.join(sys.argv[2], "scripts", "lib"))
from pair import racine_distante
try:
    c = yaml.safe_load(open(sys.argv[1])) or {}
except Exception:
    raise SystemExit
for nom, info in (c.get("peers") or {}).items():
    info = info or {}
    if not info.get("active"):
        continue
    hote = info.get("ssh_host") or (info.get("url", "").split("//")[-1].split(":")[0])
    # Le compte se lit dans la déclaration du peer, sinon le sien — il était
    # écrit en dur au nom de l'owner (la règle de bsi-peer-poll.sh).
    user = info.get("ssh_user") or os.environ.get("USER") or "root"
    try:
        racine = racine_distante(info, sys.argv[2])
    except ValueError as e:
        print(f"  ⚠️  {nom} sauté : {e}", file=sys.stderr)
        continue
    if hote:
        print(f"{nom}\t{user}\t{hote}\t{racine}")
PYEOF
}

# ── 🔴 Tout ce qui part vers un peer est encode, jamais interpole ────────────
#
# Trouve le 24/09 en essayant de casser mon propre script, quelques heures apres
# l'avoir ecrit :
#
#     bsi-signal.sh inbox "prod@desktop'; touch /tmp/PREUVE-INJECTION; echo '"
#     -> le fichier a ete cree SUR LE LAPTOP
#
# Le parametre etait interpole dans la commande SSH entre guillemets simples :
# une quote suffisait a en sortir et a executer n'importe quoi chez le peer.
# Et ca contredisait ce que venait d'affirmer — « si personne n'execute
# ce que l'autre envoie, le canal n'est pas une surface d'execution ». Il
# l'etait, par le parametre et non par le payload.
#
# Deux protections, et les deux servent :
#   valide()  refuse tot et en clair ce qui n'a pas la forme attendue ;
#   b64()     rend l'injection impossible meme si `valide()` evolue mal, car
#             base64 ne produit que [A-Za-z0-9+/=].
valide() {
  local quoi="$1" val="$2" motif="$3"
  [[ "$val" =~ $motif ]] || {
    echo "  ❌ $quoi invalide : « $val »" >&2
    echo "     attendu : $motif" >&2
    exit 1
  }
}

b64() { printf '%s' "$1" | base64 -w0; }

usage() {
  # 🔴 Extraction par MOTIF, pas par numero de ligne. La premiere version
  # faisait `sed -n '4,30p'` : ajouter six lignes d'en-tete a decale la fenetre,
  # et l'aide s'est mise a afficher la declaration de rattachement au lieu de
  # l'usage. Une fenetre figee casse a la premiere insertion — c'est la famille
  # de, une liste en dur qui ne suit pas ce qu'elle decrit.
  # 🔴 L'arret est teste AVANT le `sub`, et l'ordre n'est pas cosmetique :
  # `sub()` modifie `$0`. En retirant le `#`, il rendait la ligne suivante
  # « non commentaire » aux yeux de la regle d'apres, qui sortait des la
  # deuxieme ligne. L'aide n'affichait que son titre. Trouve en jouant l'awk
  # a la main, pas en le relisant.
  awk '/^# bsi-signal\.sh —/{p=1} p&&!/^#/{exit} p{sub(/^# ?/,""); print}' "$0"
  exit 1
}

case "$CMD" in

  # ── send ───────────────────────────────────────────────────────────────────
  send)
    DEST="${1:-}"; shift || true
    TYPE=""; PROJET=""; PAYLOAD=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --type)    TYPE="${2:-}"; shift 2 ;;
        --projet)  PROJET="${2:-}"; shift 2 ;;
        --payload) PAYLOAD="${2:-}"; shift 2 ;;
        *) echo "argument inconnu : $1" >&2; exit 1 ;;
      esac
    done
    [[ -n "$DEST" ]]    || { echo "destinataire manquant" >&2; usage; }
    [[ -n "$TYPE" ]]    || { echo "--type manquant (${TYPES// /, })" >&2; exit 1; }
    [[ -n "$PAYLOAD" ]] || { echo "--payload manquant" >&2; exit 1; }
    # Le destinataire est une instance (`prod@desktop`) ou une session
    # (`sess-...`). Le payload, lui, n'est PAS contraint : il ne part jamais
    # dans une commande, il transite par les parametres SQL de db.execute().
    valide "destinataire" "$DEST" '^[A-Za-z0-9._@-]+$'
    # 🔴 Le type est verifie ICI et pas seulement par l'enum de la base : un
    # type hors enum ferait rendre « 500 sans motif » au moteur, exactement le
    # defaut de. Mieux vaut refuser en clair avant d'ecrire.
    grep -qw -- "$TYPE" <<<"$TYPES" || { echo "type inconnu : $TYPE" >&2
      echo "  attendus : ${TYPES// /, }" >&2; exit 1; }

    SIG="sig-$(date -u +%Y%m%d-%H%M%S)-$$"
    FROM="$(mon_instance)"
    python3 - "$BRAIN_ROOT" "$SIG" "$FROM" "$DEST" "$TYPE" "$PROJET" "$PAYLOAD" <<'PYEOF'
import sys, os
brain_root, sig, frm, to, typ, projet, payload = sys.argv[1:8]
sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db
db.execute(
    "INSERT INTO signals (sig_id, from_sess, to_sess, type, projet, payload, state, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, 'pending', UTC_TIMESTAMP())",
    (sig, frm, to, typ, projet or None, payload),
)
print(f"  ✅ signal emis : {sig}")
print(f"     {frm}  →  {to}   [{typ}]" + (f"   projet: {projet}" if projet else ""))
print("     Il reste chez l'emetteur : le destinataire le relevera par `inbox`.")
PYEOF
    ;;

  # ── inbox ──────────────────────────────────────────────────────────────────
  #
  # 🔴, 27/09. `inbox` ne relevait QUE l'instance. Deux signaux
  # adresses a une session par son identifiant — un HANDOFF et un INFO de la
  # session `learning/omarchy` — n'ont jamais ete montres : trouves parce que
  # Kevin a dit « je pense que tu as des messages ».
  #
  # On releve desormais l'instance ET des sessions :
  #   dans une session d'agent  → les claims ouverts de CETTE session, retrouves
  #                               par CLAUDE_CODE_SESSION_ID (BRAIN-077) ;
  #   dans un shell humain      → tous les claims ouverts de l'instance : c'est
  #                               l'humain qui regarde, il doit tout voir.
  # Un destinataire passe en argument garde l'ancien sens : lui, et lui seul.
  inbox)
    INSTANCE="$(mon_instance)"        # une affectation : `set -e` arrete ici si elle echoue
    if [[ -n "${1:-}" ]]; then
      DESTS="$1"
    else
      DESTS="$(python3 - "$BRAIN_ROOT" "$INSTANCE" "${CLAUDE_CODE_SESSION_ID:-}" <<'PYEOF'
import sys, os
brain_root, instance, agent = sys.argv[1:4]
sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db
from core.bsi import BSI
bsi = BSI(db.depot())
if agent and bsi.porte_identite:
    sessions = [c.sess_id for c in bsi.de_la_session(agent)]
    if not sessions:
        # Le dire : sans claim identifie, seule l'instance est relevee.
        print("ⓘ aucun claim ouvert ne porte cette session (ouvert avant BRAIN-077, "
              "ou sans identite) — seuls les signaux de l'instance sont releves.",
              file=sys.stderr)
else:
    sessions = [c.sess_id for c in bsi.ouverts()]
for d in [instance] + sessions:
    print(d)
PYEOF
)"
    fi
    echo "📬 signaux en attente pour : $(echo "$DESTS" | paste -sd' ' | sed 's/ / · /g')"
    echo
    echo "🖥  ici ($INSTANCE)"
    python3 - "$BRAIN_ROOT" "$DESTS" <<'PYEOF'
import sys, os
brain_root, dests = sys.argv[1], [d for d in sys.argv[2].splitlines() if d]
sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db
place = ", ".join(["%s"] * len(dests))
rows = db.query(
    "SELECT sig_id, from_sess, to_sess, type, projet, payload, created_at FROM signals "
    f"WHERE state = 'pending' AND to_sess IN ({place}) ORDER BY created_at", tuple(dests))
if not rows:
    print("   (aucun)")
for r in rows:
    print(f"   {r['sig_id']}  [{r['type']}]  de {r['from_sess']}  → {r['to_sess']}"
          + (f"  projet {r['projet']}" if r.get('projet') else ""))
    for ligne in (r['payload'] or "").splitlines() or [""]:
        print(f"       {ligne}")
PYEOF
    # 🔴 Un peer muet n'est pas un peer sans message — la confusion que
    # nomme, et que `bsi-query.sh peers` a mis six jours a corriger.
    # Le `bash -lc` est obligatoire : `ssh hote "commande"` lance un shell non
    # interactif ET non-login, qui ne lit ni .bashrc ni .bash_profile — le peer
    # travaillerait sans son environnement.
    #
    # UN appel par destinataire, et la forme d'appel d'avant : un peer qui n'a
    # pas encore cette version repond toujours juste pour l'instance, au lieu de
    # ne plus rien reconnaitre.
    while IFS=$'\t' read -r nom user hote racine; do
      [[ -n "${nom:-}" ]] || continue
      echo
      echo "💻 $nom ($hote)"
      trouve=0; muet=0
      while IFS= read -r dest; do
        [[ -n "$dest" ]] || continue
        err=$(mktemp); code=0
        out=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$user@$hote" \
              "bash -lc \"cd $racine && bash scripts/bsi-signal.sh inbox-local-b64 '$(b64 "$dest")'\"" \
              2>"$err") || code=$?
        if [[ $code -ne 0 ]]; then
          echo "   ⚠️  injoignable ou en erreur (code $code) — ce n'est PAS « aucun signal »"
          sed 's/^/      /' "$err" | tail -2
          rm -f "$err"; muet=1; break
        fi
        rm -f "$err"
        if [[ -n "${out// }" ]]; then
          echo "   → $dest"
          echo "$out"
          trouve=1
        fi
      done <<< "$DESTS"
      if [[ $trouve -eq 0 && $muet -eq 0 ]]; then
        echo "   (aucun — le peer a repondu)"
      fi
    done < <(peers)

    # ── Les orphelins — ─────────────────────────────────────────────
    # Un signal adresse a une session DEJA FERMEE reste `pending` pour toujours :
    # plus personne ne le relevera. On le montre, on ne l'acquitte pas —
    # l'accuse dit « j'en fais quelque chose », c'est a un humain de le dire.
    python3 - "$BRAIN_ROOT" <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], "brain-engine"))
import db
rows = db.query(
    "SELECT s.sig_id, s.to_sess, s.type, s.created_at FROM signals s "
    "WHERE s.state = 'pending' AND s.to_sess LIKE %s "
    "AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.sess_id = s.to_sess "
    "                AND c.status = 'open') ORDER BY s.created_at", ("sess-%",))
if rows:
    print()
    print(f"🕳  {len(rows)} signal(aux) orphelin(s) ici — adresses a une session "
          "fermee, que plus personne ne relevera :")
    for r in rows:
        print(f"   {r['sig_id']}  [{r['type']}]  → {r['to_sess']}  ({r['created_at']})")
    print("   → le lire, le transmettre a l'instance, puis l'accuser : bsi-signal.sh ack <sig_id>")
PYEOF
    ;;

  # ── inbox-local-b64 : ce que le peer execute pour nous, sans recursion ─────
  # Le destinataire arrive en base64 : c'est ce qui rend l'injection impossible.
  # `inbox-local` reste accepte pour un appel a la main, mais rien ne l'emet.
  inbox-local-b64|inbox-local)
    MOI="${1:-}"
    [[ -n "$MOI" ]] || { echo "destinataire manquant" >&2; exit 1; }
    if [[ "$CMD" == "inbox-local-b64" ]]; then
      MOI="$(printf '%s' "$MOI" | base64 -d 2>/dev/null)" || {
        echo "destinataire illisible" >&2; exit 1; }
    fi
    python3 - "$BRAIN_ROOT" "$MOI" <<'PYEOF'
import sys, os
brain_root, moi = sys.argv[1:3]
sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db
for r in db.query(
        "SELECT sig_id, from_sess, type, projet, payload FROM signals "
        "WHERE state = 'pending' AND to_sess = %s ORDER BY created_at", (moi,)):
    print(f"   {r['sig_id']}  [{r['type']}]  de {r['from_sess']}"
          + (f"  projet {r['projet']}" if r.get('projet') else ""))
    for ligne in (r['payload'] or "").splitlines() or [""]:
        print(f"       {ligne}")
PYEOF
    ;;

  # ── outbox ─────────────────────────────────────────────────────────────────
  outbox)
    INSTANCE="$(mon_instance)"        # affectation : `set -e` arrete si elle echoue
    python3 - "$BRAIN_ROOT" "$INSTANCE" <<'PYEOF'
import sys, os
brain_root, moi = sys.argv[1:3]
sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db
rows = db.query(
    "SELECT sig_id, to_sess, type, state, created_at, delivered_at FROM signals "
    "WHERE from_sess = %s ORDER BY created_at DESC LIMIT 20", (moi,))
if not rows:
    print("  (rien emis depuis cette instance)")
for r in rows:
    etat = "relu" if r['state'] == 'delivered' else "EN ATTENTE"
    print(f"  {r['sig_id']}  →  {r['to_sess']}  [{r['type']}]  {etat}")
PYEOF
    ;;

  # ── ack ────────────────────────────────────────────────────────────────────
  ack)
    SIG="${1:-}"
    [[ -n "$SIG" ]] || { echo "sig_id manquant" >&2; exit 1; }
    # Un sig_id part vers le peer dans une commande SSH. Il n'a aucune raison de
    # contenir une quote, un espace ou un point-virgule : on refuse tout le
    # reste plutot que d'esperer l'echapper correctement sur deux niveaux de
    # shell. L'encodage protege `inbox` ; ici la forme est assez stricte pour
    # que la validation suffise, et elle dit clairement ce qu'elle refuse.
    valide "sig_id" "$SIG" '^[A-Za-z0-9._-]+$'
    fait=0
    # D'abord ici. Le signal vit chez SON EMETTEUR, donc l'accuse doit souvent
    # voyager — c'est le prix du choix « on ecrit chez soi », assume plus haut.
    if python3 - "$BRAIN_ROOT" "$SIG" <<'PYEOF'
import sys, os
brain_root, sig = sys.argv[1:3]
sys.path.insert(0, os.path.join(brain_root, "brain-engine"))
import db
r = db.query("SELECT sig_id FROM signals WHERE sig_id = %s AND state = 'pending'", (sig,))
if not r:
    raise SystemExit(1)
db.execute("UPDATE signals SET state = 'delivered', delivered_at = UTC_TIMESTAMP() "
           "WHERE sig_id = %s", (sig,))
raise SystemExit(0)
PYEOF
    then
      echo "  ✅ $SIG accuse ici"
      fait=1
    else
      while IFS=$'\t' read -r nom user hote racine; do
        [[ -n "${nom:-}" ]] || continue
        code=0
        ssh -o BatchMode=yes -o ConnectTimeout=5 "$user@$hote" \
          "bash -lc \"cd $racine && bash scripts/bsi-signal.sh ack '$SIG'\"" \
          >/dev/null 2>&1 || code=$?
        if [[ $code -eq 0 ]]; then
          echo "  ✅ $SIG accuse chez $nom"
          fait=1
          break
        fi
      done < <(peers)
    fi
    [[ $fait -eq 1 ]] || { echo "  ❌ $SIG introuvable en attente, ici ni chez les peers" >&2; exit 1; }
    ;;

  *) usage ;;
esac
