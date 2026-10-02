#!/usr/bin/env bash
# brain-distribuable: oui
# brain-engine.sh — CLI unifiée pour le lifecycle brain-engine
#
# @workflow: brain-engine
# @description: Lifecycle du brain-engine (start, embed, status, stop)
# @trigger: manuel
# @steps: start server → embed one-shot → status check → stop
# @args: start=Demarrer le serveur (background)|stop=Arreter proprement|status=PID, port, mode, uptime|embed=Embedding one-shot
#
# Usage :
#   brain-engine start [--fg]     Démarrer le moteur ET le serveur MCP (--fg = foreground)
#   brain-engine stop             Arrêter proprement ce que CE brain a lancé
#   brain-engine status           PID, port, mode, uptime
#   brain-engine embed            Lancer un embedding one-shot
#   brain-engine logs             Tail des logs (journald ou fichier)
#   brain-engine install pm2      Installer via pm2 (restart on crash)
#   brain-engine install systemd  Unités systemd UTILISATEUR (survit au reboot, sans sudo)
#
# Le mode (dev/prod/demo) est lu depuis BRAIN_MODE env var
# ou détecté depuis brain-compose.local.yml.
#
# Graduation :
#   Manuel  → brain-engine start        (je lance quand j'en ai besoin)
#   pm2     → brain-engine install pm2   (restart on crash, pas au reboot)
#   systemd → brain-engine install systemd (survit au reboot, logs journald)

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_DIR="$BRAIN_ROOT/brain-engine"

# Les ports déclarés dans `brain-engine/.env.local` — comme `db.py` les lit.
# `dolt-setup.sh` y écrit BRAIN_DOLT_PORT quand il n'est pas 3307 ; ce script ne
# lisait que l'environnement, et lançait alors Dolt sur 3307 pendant que `db.py`
# cherchait la base sur l'autre port (relecture du 28/09). L'environnement
# garde la priorité, comme dans `db.py`.
# Seul le port de Dolt se lit ici : ceux des deux portes viennent de `serve.py`
# (plus bas), qui les déclare une fois — les exporter d'ici les aurait fait
# passer pour « posés par l'environnement », devant MYSECRETS.
for _var in BRAIN_DOLT_PORT; do
  if [[ -z "${!_var:-}" && -f "$ENGINE_DIR/.env.local" ]]; then
    _val=$(grep -sE "^${_var}=" "$ENGINE_DIR/.env.local" | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)
    [[ -n "$_val" ]] && export "$_var=$_val"
  fi
done
unset _var _val
SERVER="$ENGINE_DIR/server.py"
PID_FILE="$BRAIN_ROOT/.brain-engine.pid"
LOG_FILE="$BRAIN_ROOT/brain-engine.log"
MCP_SERVER="$ENGINE_DIR/mcp_server.py"
# Les deux portes se lancent par `brain serve` : la déclaration (ports, mode,
# secrets, scopes du MCP local) se décide là, une fois. Ce script garde
# ce qui l'entoure — Dolt, les PID, les ports déjà tenus, l'installation.
SERVE="$ENGINE_DIR/serve.py"
# Les ports des deux portes : ceux que `brain serve` ouvrira. Une déclaration
# illisible (une BRAIN_ROOT qui n'est pas un dossier) ne doit pas empêcher
# `stop` ni `status` : les défauts, et on le dit.
if [[ -f "$SERVE" ]]; then
  if _ports=$(python3 "$SERVE" --ports 2>/dev/null); then
    while IFS='=' read -r _k _v; do
      case "$_k" in BRAIN_PORT|BRAIN_MCP_PORT) export "$_k=$_v" ;; esac
    done <<< "$_ports"
  else
    echo "⚠️  brain serve n'a pas pu lire sa déclaration — ports par défaut" >&2
  fi
  unset _ports _k _v
fi
MCP_PID_FILE="$BRAIN_ROOT/.brain-mcp.pid"
MCP_LOG_FILE="$BRAIN_ROOT/brain-mcp.log"
MCP_PORT="${BRAIN_MCP_PORT:-7701}"

# ── Couleurs ─────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
err()  { echo -e "${RED}❌ $1${NC}" >&2; }
info() { echo -e "   $1"; }

# ── Détection mode ───────────────────────────────────────────────────────────
detect_mode() {
  # 1. Env var explicite
  if [[ -n "${BRAIN_MODE:-}" ]]; then
    echo "$BRAIN_MODE"
    return
  fi

  # 2. brain-compose.local.yml
  local local_yml="$BRAIN_ROOT/brain-compose.local.yml"
  if [[ -f "$local_yml" ]]; then
    local mode
    mode=$(grep '^  *mode:' "$local_yml" 2>/dev/null | head -1 | awk '{print $2}' | tr -d '"' || true)
    if [[ -n "$mode" ]]; then
      echo "$mode"
      return
    fi
  fi

  # 3. Défaut
  echo "dev"
}

# ── Détection port ───────────────────────────────────────────────────────────
detect_port() {
  echo "${BRAIN_PORT:-7700}"
}

# ── Prérequis ────────────────────────────────────────────────────────────────
check_prereqs() {
  if [[ ! -f "$SERVER" ]]; then
    err "brain-engine/server.py introuvable ($SERVER)"
    exit 1
  fi
  if ! command -v python3 &>/dev/null; then
    err "python3 non trouvé"
    exit 1
  fi
  if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
    err "Dépendances manquantes — pip3 install -r $ENGINE_DIR/requirements.txt"
    exit 1
  fi
}

# ── PID helpers ──────────────────────────────────────────────────────────────
#
# Deux questions distinctes, deux fonctions :
#
#   get_pid      ce que `start` a lancé — SON fichier de PID, rien d'autre.
#                C'est la seule chose que `stop` arrête.
#   pid_en_cours un moteur de CE brain tourne-t-il, lancé par qui que ce soit
#                (systemd, pm2, un terminal) ? Sert à ne pas en lancer un second.
#
# L'ancien repli de `get_pid` — `pgrep -f "python3.*brain-engine/server.py"` —
# attrapait le moteur de N'IMPORTE QUEL brain de la machine, et `stop` l'aurait
# tué : le 27/09, un essai de fork l'a appelé à côté de la prod, qui n'a survécu
# que parce qu'elle tourne en `.venv/bin/python`. Le chercher par chemin absolu
# ne suffit pas : il trouverait alors À COUP SÛR le moteur de ce brain géré par
# systemd, et `stop` l'arrêterait proprement — un arrêt que `Restart=on-failure`
# ne relance pas.
# Un fichier de PID ne vaut que si le processus est ENCORE le nôtre : après un
# redémarrage, le numéro peut désigner n'importe quel processus de l'utilisateur,
# et `kill -0` seul ferait tuer un inconnu par `stop` (relecture du 28/09).
#   pid_du_fichier <fichier> <motif> [<dossier courant attendu>]
pid_du_fichier() {
  local f="$1" motif="$2" cwd="${3:-}" pid
  [[ -f "$f" ]] || return 0
  pid=$(cat "$f" 2>/dev/null || true)
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null \
      && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qF -- "$motif" \
      && { [[ -z "$cwd" ]] || [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" == "$(readlink -f "$cwd")" ]]; }; then
    echo "$pid"
    return 0
  fi
  rm -f "$f"
}

get_pid() {
  pid_du_fichier "$PID_FILE" "$SERVER"
}

pid_en_cours() {
  local pid
  pid=$(get_pid)
  [[ -n "$pid" ]] && { echo "$pid"; return; }
  pgrep -f -- " $SERVER\$" 2>/dev/null | head -1 || true
}

# Un port local qui répond déjà — un service (dolt-server.service, une unité
# utilisateur) ou une autre instance. On ne lance pas un second serveur dessus.
port_servi() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

# QUI répond sur ce port : le PID à l'écoute (vide si invisible — un autre
# utilisateur, root). Un port qui répond n'est pas un port à NOUS : un second
# brain sur la machine se serait branché sur la base et le MCP de l'autre, en
# annonçant « réutilisé » (relecture du 28/09).
pid_a_l_ecoute() {
  ss -ltnpH "( sport = :$1 )" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true
}

ligne_de() {
  tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null || true
}

is_running() {
  [[ -n "$(pid_en_cours)" ]]
}

# ── Commandes ────────────────────────────────────────────────────────────────

DOLT_DIR="${BRAIN_ROOT}/brain-dolt"
DOLT_PORT="${BRAIN_DOLT_PORT:-3307}"
DOLT_PID_FILE="${BRAIN_ROOT}/.dolt-server.pid"
DOLT_LOG_FILE="${BRAIN_ROOT}/brain-engine/dolt-server.log"

start_dolt_server() {
  # Vérifie le backend dans .env.local
  local backend
  # Le défaut est `dolt`, comme dans db.py. `|| echo …` ne rattrapait
  # rien : dans `$(grep | cut)`, c'est `cut` qui répond, et il réussit sur une
  # entrée vide — le backend valait "" quand la ligne manquait.
  backend=$(grep -s '^BRAIN_DB_BACKEND=' "${BRAIN_ROOT}/brain-engine/.env.local" | cut -d= -f2)
  backend="${backend:-dolt}"
  if [[ "$backend" != "dolt" ]]; then
    return 0  # pas de dolt sql-server nécessaire
  fi

  if [[ ! -d "$DOLT_DIR" ]]; then
    warn "brain-dolt/ absent — dolt sql-server non démarré"
    return 0
  fi

  # Déjà en cours ?
  local deja
  deja=$(pid_du_fichier "$DOLT_PID_FILE" "sql-server" "$DOLT_DIR")
  if [[ -n "$deja" ]]; then
    info "dolt sql-server : déjà en cours (PID $deja)"
    return 0
  fi
  # Déjà servi — par dolt-server.service, que `dolt-setup.sh` pose sur ce port
  #. Mais seulement si c'est la base de CE brain : le serveur qui
  # écoute doit tourner dans `brain-dolt/` d'ici.
  if port_servi "$DOLT_PORT"; then
    local p
    p=$(pid_a_l_ecoute "$DOLT_PORT")
    if [[ -n "$p" && "$(readlink -f "/proc/$p/cwd" 2>/dev/null)" == "$(readlink -f "$DOLT_DIR")" ]]; then
      info "dolt : le port $DOLT_PORT sert déjà la base de ce brain (PID $p) — réutilisé"
      return 0
    fi
    err "le port $DOLT_PORT répond, mais pas avec la base de ce brain ($DOLT_DIR)"
    info "  servi par : ${p:+PID $p — $(readlink -f "/proc/$p/cwd" 2>/dev/null)}${p:-un processus invisible depuis ce compte}"
    info "  un autre brain ? choisir un port : BRAIN_DOLT_PORT=<port> dans brain-engine/.env.local"
    return 1
  fi

  cd "$DOLT_DIR"
  dolt sql-server -P "$DOLT_PORT" --host 127.0.0.1 >> "$DOLT_LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$DOLT_PID_FILE"
  sleep 1

  if kill -0 "$pid" 2>/dev/null; then
    ok "dolt sql-server démarré (PID $pid, port $DOLT_PORT)"
  else
    warn "dolt sql-server n'a pas démarré — voir $DOLT_LOG_FILE"
    rm -f "$DOLT_PID_FILE"
  fi
  cd "$BRAIN_ROOT"
}

stop_dolt_server() {
  local pid
  pid=$(pid_du_fichier "$DOLT_PID_FILE" "sql-server" "$DOLT_DIR")
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    ok "dolt sql-server arrêté (PID $pid)"
  fi
  rm -f "$DOLT_PID_FILE"
}

# ── Le serveur MCP — l'interface de Claude Code ─────────────────────────────
# Rien ne le lançait dans un fork : la doc disait d'ajouter une URL que personne
# ne servait.
start_mcp() {
  [[ -f "$MCP_SERVER" ]] || return 0
  local deja
  deja=$(pid_du_fichier "$MCP_PID_FILE" "$MCP_SERVER")
  if [[ -n "$deja" ]]; then
    info "mcp : déjà en cours (PID $deja)"
    return 0
  fi
  if port_servi "$MCP_PORT"; then
    local p
    p=$(pid_a_l_ecoute "$MCP_PORT")
    if [[ -n "$p" ]] && ligne_de "$p" | grep -qF -- "$MCP_SERVER"; then
      info "mcp : le serveur MCP de ce brain répond déjà (PID $p)"
    else
      warn "mcp : le port $MCP_PORT est tenu par un AUTRE processus — MCP de ce brain non lancé"
      info "  ${p:+$(ligne_de "$p")}${p:-processus invisible depuis ce compte} — choisir BRAIN_MCP_PORT=<port>"
    fi
    return 0
  fi
  # `serve.py mcp` remplace son processus par `mcp_server.py` : le PID noté est
  # celui du serveur.
  python3 "$SERVE" mcp >> "$MCP_LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$MCP_PID_FILE"
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    ok "serveur MCP démarré (PID $pid) — http://127.0.0.1:$MCP_PORT/mcp"
  else
    warn "le serveur MCP n'a pas démarré — voir $MCP_LOG_FILE"
    rm -f "$MCP_PID_FILE"
  fi
}

stop_mcp() {
  local pid
  pid=$(pid_du_fichier "$MCP_PID_FILE" "$MCP_SERVER")
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    ok "serveur MCP arrêté (PID $pid)"
  fi
  rm -f "$MCP_PID_FILE"
}

cmd_start() {
  local fg=false
  [[ "${1:-}" == "--fg" ]] && fg=true

  check_prereqs

  if is_running; then
    warn "brain-engine déjà en cours (PID $(pid_en_cours))"
    return 0
  fi

  # Démarrer dolt sql-server si backend=dolt — et refuser de démarrer le moteur
  # sur la base d'un autre brain.
  start_dolt_server || exit 1

  local port
  port=$(detect_port)

  # La déclaration — mode, ports, secrets — est celle de `brain serve` : on
  # l'affiche, on ne la recalcule pas. Les secrets ne sont plus `source`s (le
  # shell EXÉCUTAIT chaque ligne de MYSECRETS) : `serve.py` les lit comme
  # systemd lit un EnvironmentFile.
  echo "▶ brain-engine start"
  python3 "$SERVE" --declaration | sed 's/^/   /'

  start_mcp

  if $fg; then
    info "mode foreground — Ctrl+C pour arrêter"
    echo ""
    python3 "$SERVE" http
  else
    # Le processus en arrière-plan est python lui-même, puis le serveur : `serve.py
    # http` remplace son processus (execve). Le PID noté est celui que `stop`
    # doit tuer — un sous-shell intermédiaire l'aurait laissé tourner.
    python3 "$SERVE" http >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 1

    if kill -0 "$pid" 2>/dev/null; then
      ok "brain-engine démarré (PID $pid, port $port)"
      info "logs : tail -f $LOG_FILE"
    else
      err "brain-engine a crashé au démarrage — voir $LOG_FILE"
      rm -f "$PID_FILE"
      exit 1
    fi
  fi
}

cmd_stop() {
  local pid
  pid=$(get_pid)

  if [[ -z "$pid" ]]; then
    local autre
    autre=$(pid_en_cours)
    if [[ -n "$autre" ]]; then
      info "brain-engine tourne (PID $autre), mais pas lancé par ce script — non arrêté"
      info "  systemd : systemctl --user stop brain-engine · pm2 : pm2 stop brain-engine brain-mcp"
    else
      info "brain-engine n'est pas en cours"
    fi
    stop_mcp
    stop_dolt_server
    return 0
  fi

  echo "▶ brain-engine stop (PID $pid)"
  kill "$pid" 2>/dev/null || true
  local i=0
  while kill -0 "$pid" 2>/dev/null && [[ $i -lt 10 ]]; do
    sleep 0.5
    # `((i++))` rend 1 quand i vaut 0 : sous `set -e`, `stop` mourait après le
    # premier `kill`, laissant le fichier de PID, le MCP et Dolt.
    i=$((i + 1))
  done

  if kill -0 "$pid" 2>/dev/null; then
    warn "kill -9 (arrêt forcé)"
    kill -9 "$pid" 2>/dev/null || true
  fi

  rm -f "$PID_FILE"
  ok "brain-engine arrêté"

  # Ce que `start` a lancé avec lui — par leurs fichiers de PID, jamais par motif
  stop_mcp
  stop_dolt_server
}

cmd_status() {
  local pid mode port
  pid=$(pid_en_cours)
  mode=$(detect_mode)
  port=$(detect_port)

  echo "▶ brain-engine status"
  info "mode : $mode"
  info "port : $port"
  info "root : $BRAIN_ROOT"
  verifier_unites || true

  if [[ -z "$pid" ]]; then
    # Vérifier systemd
    if systemctl --user is-active --quiet brain-engine 2>/dev/null; then
      info "pid  : $(systemctl --user show brain-engine --property=MainPID --value)"
      info "via  : systemd"
      ok "en cours (systemd)"
      return 0
    fi
    # Vérifier pm2
    if command -v pm2 &>/dev/null && pm2 describe brain-engine &>/dev/null 2>&1; then
      local pm2_status
      pm2_status=$(pm2 describe brain-engine 2>/dev/null | grep status | awk '{print $4}')
      info "via  : pm2 ($pm2_status)"
      if [[ "$pm2_status" == "online" ]]; then
        ok "en cours (pm2)"
      else
        warn "pm2 status: $pm2_status"
      fi
      return 0
    fi
    warn "arrêté"
    return 1
  fi

  # Uptime
  local uptime_s
  uptime_s=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ' || echo "?")
  if [[ "$uptime_s" =~ ^[0-9]+$ ]]; then
    local h=$((uptime_s / 3600))
    local m=$(((uptime_s % 3600) / 60))
    info "pid  : $pid"
    info "up   : ${h}h ${m}m"
  else
    info "pid  : $pid"
  fi

  # Health check
  if curl -sf "http://localhost:$port/health" &>/dev/null; then
    ok "en cours — /health OK"
  else
    warn "process actif mais /health ne répond pas"
  fi
  if port_servi "$MCP_PORT"; then
    info "mcp  : http://127.0.0.1:$MCP_PORT/mcp"
  else
    warn "mcp  : le port $MCP_PORT ne répond pas"
  fi
}

cmd_embed() {
  local mode
  mode=$(detect_mode)

  if [[ "$mode" == "demo" ]]; then
    warn "embed désactivé en mode demo"
    return 0
  fi

  check_prereqs

  # L'instantané du focus, AVANT l'embedding : Ollama absent arrête l'embedding,
  # pas le focus. Moteur éteint, `brain_focus` rendra ce dernier instantané
  # au lieu de renvoyer vers l'API. Jamais une cause d'échec ici.
  python3 "$ENGINE_DIR/focus_instantane.py" || warn "instantané du focus non écrit"

  echo "▶ brain-engine embed (one-shot)"

  if ! command -v ollama &>/dev/null; then
    err "ollama non trouvé — requis pour l'embedding"
    exit 1
  fi

  local embed_script="$ENGINE_DIR/embed.py"
  if [[ ! -f "$embed_script" ]]; then
    err "brain-engine/embed.py introuvable"
    exit 1
  fi

  cd "$BRAIN_ROOT"
  # Le binaire présent ne dit pas que le SERVICE répond : embed.py sort en 2
  # quand Ollama est injoignable — les chunks sont gardés sans vecteur.
  local code=0
  BRAIN_MODE="$mode" python3 "$embed_script" || code=$?
  if (( code == 2 )); then
    err "embedding incomplet — Ollama injoignable : les chunks sont gardés sans vecteur, la recherche ne les trouvera pas"
    info "  vérifier : curl -s ${OLLAMA_URL:-http://localhost:11434}/api/tags · ollama pull ${EMBED_MODEL:-nomic-embed-text}"
    exit 2
  elif (( code != 0 )); then
    err "embedding interrompu (code $code)"
    exit "$code"
  fi
  ok "embedding terminé"
}

cmd_logs() {
  # systemd ?
  if systemctl --user is-active --quiet brain-engine 2>/dev/null; then
    info "source: journald"
    journalctl --user -u brain-engine -f --no-hostname
    return
  fi

  # pm2 ?
  if command -v pm2 &>/dev/null && pm2 describe brain-engine &>/dev/null 2>&1; then
    info "source: pm2"
    pm2 logs brain-engine
    return
  fi

  # fichier
  if [[ -f "$LOG_FILE" ]]; then
    info "source: $LOG_FILE"
    tail -f "$LOG_FILE"
  else
    warn "aucun log trouvé"
  fi
}

cmd_install() {
  local target="${1:-}"

  case "$target" in
    pm2)
      cmd_install_pm2
      ;;
    systemd)
      cmd_install_systemd
      ;;
    *)
      echo "Usage : brain-engine install <pm2|systemd>"
      echo ""
      echo "  pm2     — restart on crash (pas au reboot)"
      echo "  systemd — survit au reboot, logs journald"
      exit 1
      ;;
  esac
}

cmd_install_pm2() {
  if ! command -v pm2 &>/dev/null; then
    err "pm2 non trouvé — npm install -g pm2"
    exit 1
  fi

  check_prereqs

  local mode port
  mode=$(detect_mode)
  port=$(detect_port)

  # Générer ecosystem.config.js template-ready
  # Le python du venv, comme `lib/python.sh` : celui du système n'a pas les
  # dépendances quand le setup les installe dans le venv.
  local PY_VENV="$ENGINE_DIR/.venv/bin/python3"
  [[ -x "$PY_VENV" ]] || PY_VENV=$(command -v python3)
  local eco="$BRAIN_ROOT/ecosystem.config.js"
  cat > "$eco" << JSEOF
// ecosystem.config.js — généré par brain-engine.sh install pm2
// Usage : pm2 start ecosystem.config.js
//
// Les deux portes passent par \`brain serve\` (brain-engine/serve.py) : ports,
// mode, secrets et scopes du MCP local se déclarent là, une fois. Ce fichier
// ne lit plus MYSECRETS et ne recopie plus aucun port. Avant, pm2 ne lançait
// que l'API : un brain sous pm2 n'avait pas de serveur MCP.
module.exports = {
  apps: [
    {
      name: 'brain-engine',
      script: 'brain-engine/serve.py',
      args: 'http',
      interpreter: '${PY_VENV}',
      cwd: __dirname,
      watch: false,
      autorestart: true,
    },
    {
      name: 'brain-mcp',
      script: 'brain-engine/serve.py',
      args: 'mcp',
      interpreter: '${PY_VENV}',
      cwd: __dirname,
      watch: false,
      autorestart: true,
    },
  ],
}
JSEOF

  # Arrêter l'instance manuelle si elle tourne
  if is_running; then
    info "Arrêt de l'instance manuelle..."
    cmd_stop
  fi

  pm2 start "$eco"
  pm2 save
  ok "brain-engine et brain-mcp installés via pm2 (mode: $mode, port: $port · mcp : $MCP_PORT)"
  info "pm2 logs brain-engine · pm2 logs brain-mcp — pour voir les logs"
  info "pm2 stop brain-engine brain-mcp — pour arrêter"
  info "Prochaine étape : brain-engine install systemd (quand tu es prêt)"
}

# La sauvegarde prise avant l'écriture d'une unité : gardée si l'unité a
# changé (et dite), retirée si elle est identique.
garder_si_changee() {
  local unite="$1" avant="$1.avant-$2"
  [[ -f "$avant" ]] || return 0
  if cmp -s "$avant" "$unite"; then
    rm -f "$avant"
  else
    info "$(basename "$unite") a changé — l'ancienne gardée à côté : $(basename "$avant")"
  fi
}

# Le timer d'embed se pose-t-il ? Pas en démo, et pas sur une instance
# `replica-nomad` : les vecteurs appartiennent au master, et la base refuse au
# laptop d'écrire `embeddings` — le timer y échouerait toutes les deux heures
# (BRAIN-078, point 5 ; trouvé en auditant le laptop le 29/09). La posture se
# lit par posture-gate-check.sh ; un fork ne l'a pas, et reste `master`.
pose_l_embed() {
  local mode="$1" posture=master g="$BRAIN_ROOT/scripts/posture-gate-check.sh"
  [[ "$mode" == "demo" ]] && return 1
  [[ -f "$g" ]] && posture=$(bash "$g" --posture 2>/dev/null || echo master)
  [[ "$posture" != "replica-nomad" ]]
}

# Le python que les unités lancent : celui du venv, sinon celui du système.
py_des_unites() {
  local py="$ENGINE_DIR/.venv/bin/python3"
  [[ -x "$py" ]] || py=$(command -v python3)
  echo "$py"
}

# Les unités qu'écrit `install systemd`, dans le dossier donné. Une SEULE
# source : `install` les écrit dans ~/.config/systemd/user, `status` les rend
# dans un dossier jetable pour les comparer aux installées — deux copies du
# texte d'une unité finiraient par se contredire (Cortex-Template#10, piste 3).
# Le service dont la base dépend, s'il y en a un. `dolt-server` quand ce brain
# sert SA base (brain-dolt/.dolt) ; le tunnel quand la base est celle d'une
# autre machine (BRAIN-078 : le laptop écrit sur sa branche de la base du
# fixe) ; rien sinon (SQLite). Toujours lu dans le VRAI dossier des unités :
# `status` rend les unités dans un dossier jetable, où le tunnel n'est pas.
service_de_la_base() {
  if [[ -d "$BRAIN_ROOT/brain-dolt/.dolt" ]]; then
    echo dolt-server.service
  elif [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/brain-tunnel-dolt.service" ]]; then
    echo brain-tunnel-dolt.service
  fi
}

ecrire_unites() {
  local unites="$1" mode="$2" port="$3" py="$4"
  # `-` : un fichier absent n'empêche pas le démarrage.
  local env_file="EnvironmentFile=-$BRAIN_ROOT/brain-secrets/MYSECRETS"
  # Le moteur attend le service de sa base — et aucun quand il n'y en a pas :
  # sur le laptop, il attendait un dolt-server qui n'existe pas, et ne
  # connaissait pas le tunnel dont il dépend (trouvé en l'y installant, 29/09).
  local base_svc dependance=""
  base_svc=$(service_de_la_base)
  [[ -n "$base_svc" ]] && dependance=$'\n'"Wants=$base_svc"$'\n'"After=$base_svc"

  cat > "$unites/brain-engine.service" << SVCEOF
[Unit]
Description=Brain — brain-engine ($mode)$dependance

[Service]
Type=simple
WorkingDirectory=$BRAIN_ROOT
$env_file
Environment=BRAIN_ROOT=$BRAIN_ROOT
ExecStart=$py $SERVE http
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF

  # Le service LOCAL voit ce que le rôle `mcp` de server.py voit — public, work,
  # instance, satellite — comme le MCP local de la prod. Sans ces scopes,
  # le MCP d'un fork tombait sur le défaut ÉTROIT de mcp_server.py (prévu pour un
  # MCP exposé) : ni projets, ni focus, ni todo, ni learning dans brain_search,
  # sans aucun signal (Cortex-Template#9, tranché par l'owner le 28/09).
  # Ils sont déclarés dans `serve.py` (DEFAUTS), plus ici ; MYSECRETS
  # (EnvironmentFile) l'emporte toujours s'il déclare BRAIN_MCP_SCOPES.
  cat > "$unites/brain-mcp.service" << SVCEOF
[Unit]
Description=Brain — serveur MCP
After=brain-engine.service

[Service]
Type=simple
WorkingDirectory=$BRAIN_ROOT
$env_file
Environment=BRAIN_ROOT=$BRAIN_ROOT
ExecStart=$py $SERVE mcp
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF

  # Le timer d'embed — ni en démo, ni sur une instance replica-nomad.
  if pose_l_embed "$mode"; then
    cat > "$unites/brain-embed.service" << SVCEOF
[Unit]
Description=Brain — indexation sémantique incrémentale (embed)
After=brain-engine.service

[Service]
Type=oneshot
WorkingDirectory=$BRAIN_ROOT
$env_file
Environment=BRAIN_ROOT=$BRAIN_ROOT
ExecStart=/usr/bin/env bash $BRAIN_ROOT/scripts/brain-engine.sh embed
Nice=10
SVCEOF
    cat > "$unites/brain-embed.timer" << SVCEOF
[Unit]
Description=Brain — embed 5 min après l'ouverture de session, puis toutes les 2 h

[Timer]
OnStartupSec=5min
OnUnitActiveSec=2h

[Install]
WantedBy=timers.target
SVCEOF
  fi

  # Une version plus récente chez l'amont ? Le timer lit les tags ; le briefing
  # lit son état, sans réseau. Une information, jamais une injonction.
  # Sans remote `upstream` (le brain source), il le dit dans son journal et le
  # briefing se tait. Pas en démo.
  if [[ "$mode" != "demo" ]]; then
    cat > "$unites/brain-maj.service" << SVCEOF
[Unit]
Description=Brain — une version plus récente existe-t-elle chez l'amont ?

[Service]
Type=oneshot
WorkingDirectory=$BRAIN_ROOT
Environment=BRAIN_ROOT=$BRAIN_ROOT
ExecStart=$py $BRAIN_ROOT/scripts/maj-disponible.py
Nice=10
SVCEOF
    cat > "$unites/brain-maj.timer" << SVCEOF
[Unit]
Description=Brain — vérifier les versions de l'amont, une fois par jour

[Timer]
OnStartupSec=10min
OnUnitActiveSec=1d
Persistent=true

[Install]
WantedBy=timers.target
SVCEOF
  fi
}

# Les unités installées sont-elles celles qu'écrirait `install systemd` ?
# Une version peut changer une unité, et `systemctl restart` relance celle du
# DISQUE : un fork qui saute l'étape « réinstaller les unités » garde l'unité
# d'une version passée, sans signal (Cortex-Template#10, piste 3).
verifier_unites() {
  local unites="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  # Pas installées par `install systemd`, ou celles d'un AUTRE brain de la
  # machine : rien à comparer.
  [[ -f "$unites/brain-engine.service" ]] || return 0
  grep -qxF "WorkingDirectory=$BRAIN_ROOT" "$unites/brain-engine.service" || return 0
  local rendu u ecarts=()
  rendu=$(mktemp -d)
  ecrire_unites "$rendu" "$(detect_mode)" "$(detect_port)" "$(py_des_unites)"
  for u in "$rendu"/*; do
    u=$(basename "$u")
    cmp -s "$rendu/$u" "$unites/$u" || ecarts+=("$u")
  done
  rm -rf "$rendu"
  if (( ${#ecarts[@]} )); then
    warn "unités d'une autre version, ou installées avec d'autres réglages : ${ecarts[*]}"
    info "  les réécrire et les relancer : bash scripts/brain-engine.sh install systemd"
    return 1
  fi
  info "unités : celles de cette version"
}

# La commande `brain` dans ~/.local/bin, en LIEN vers `scripts/brain` de ce
# brain. Un lien déjà là est remplacé (un autre brain, une version
# d'avant) ; un VRAI fichier ne l'est jamais : il n'est pas à nous.
poser_la_commande_brain() {
  local bin="$HOME/.local/bin" cible="$BRAIN_ROOT/scripts/brain"
  [[ -x "$cible" ]] || return 0
  mkdir -p "$bin"
  if [[ -e "$bin/brain" && ! -L "$bin/brain" ]]; then
    warn "$bin/brain existe et n'est pas un lien — laissé tel quel"
    info "  la commande reste joignable : $cible"
    return 0
  fi
  ln -sfn "$cible" "$bin/brain"
  info "commande : $bin/brain → $cible"
}

cmd_install_systemd() {
  # Des unités UTILISATEUR, comme dolt-server.service : ni sudo, ni unité
  # système. L'ancienne version écrivait /etc/systemd/system/brain-engine.service
  # avec `/usr/bin/python3` (sans les dépendances du venv) et un `ExecStartPre`
  # qui tuait (`fuser -k`) tout ce qui tenait le port.
  command -v systemctl >/dev/null 2>&1 || { err "systemctl absent — rester en manuel (start/stop)"; exit 1; }
  check_prereqs

  local mode port unites py
  mode=$(detect_mode)
  port=$(detect_port)
  unites="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  py=$(py_des_unites)

  # Des ports tenus par un AUTRE processus que ce brain : les unités
  # redémarreraient sans fin (`Restart=on-failure`), puis se disputeraient les
  # ports au prochain démarrage de session — avec la prod d'un autre brain de la
  # machine, par exemple (relecture du 28/09).
  local pt pp cible
  for pt in "$port:$SERVER" "$MCP_PORT:$MCP_SERVER"; do
    cible="${pt#*:}"; pt="${pt%%:*}"
    if port_servi "$pt"; then
      pp=$(pid_a_l_ecoute "$pt")
      if [[ -z "$pp" ]] || ! ligne_de "$pp" | grep -qF -- "$cible"; then
        err "le port $pt est tenu par un autre processus — rien n'est installé"
        info "  ${pp:+$(ligne_de "$pp")}${pp:-processus invisible depuis ce compte}"
        info "  choisir BRAIN_PORT / BRAIN_MCP_PORT, ou arrêter ce qui tient le port"
        exit 1
      fi
    fi
  done

  echo "▶ brain-engine install systemd (utilisateur)"
  info "mode : $mode"
  info "port : $port · mcp : $MCP_PORT"
  mkdir -p "$unites"

  # Une unité différente déjà là est SAUVEGARDÉE à côté, comme dolt-setup.sh le
  # fait — jamais écrasée sans trace. Copiée avant, gardée seulement si elle
  # DIFFÈRE de la nouvelle (`garder_si_changee`, après l'écriture) : la page
  # « Se mettre à jour » fait rejouer `install systemd` à chaque version, et une
  # copie par passage empilerait des sauvegardes identiques.
  local u horodate
  horodate=$(date +%Y%m%d%H%M%S)
  for u in brain-engine.service brain-mcp.service brain-embed.service brain-embed.timer brain-maj.service brain-maj.timer; do
    [[ -f "$unites/$u" ]] && cp "$unites/$u" "$unites/$u.avant-$horodate"
  done
  case "$(service_de_la_base)" in
    dolt-server.service)
      if ! systemctl --user cat dolt-server.service >/dev/null 2>&1; then
        warn "pas de dolt-server.service : rien ne relancera la base au démarrage"
        info "  bash scripts/dolt-setup.sh   (sans --sans-service) pour la servir"
      fi ;;
    brain-tunnel-dolt.service)
      info "base : celle d'une autre machine, par brain-tunnel-dolt.service — pas de dolt-server ici" ;;
    *)
      info "pas de base Dolt locale (brain-dolt/) — pas de dolt-server à attendre" ;;
  esac

  ecrire_unites "$unites" "$mode" "$port" "$py"
  poser_la_commande_brain

  for u in brain-engine.service brain-mcp.service brain-embed.service brain-embed.timer brain-maj.service brain-maj.timer; do
    garder_si_changee "$unites/$u" "$horodate"
  done

  # Arrêter l'instance manuelle ou pm2 — celles de CE brain. « Manuelle » veut
  # dire lancée par `start`, donc un fichier de PID : une instance de systemd
  # n'en a pas, et `cmd_stop` répondait « pas lancé par ce script » juste après
  # « Arrêt de l'instance manuelle » (Cortex-Template#10).
  if [[ -n "$(get_pid)" ]]; then
    info "Arrêt de l'instance manuelle..."
    cmd_stop
  elif is_running; then
    info "brain-engine tourne déjà (systemd ?) — relancé plus bas sur les nouvelles unités"
  fi
  if command -v pm2 &>/dev/null && pm2 describe brain-engine &>/dev/null 2>&1; then
    info "Arrêt de l'instance pm2..."
    pm2 stop brain-engine 2>/dev/null || true
    pm2 delete brain-engine 2>/dev/null || true
  fi

  systemctl --user daemon-reload
  # `restart`, pas `enable --now` : sur une unité déjà active, `start` ne fait
  # rien, et les processus gardaient l'environnement de l'ANCIENNE unité — les
  # scopes du MCP d'une v2.3.5 n'arrivaient pas (Cortex-Template#10).
  systemctl --user enable brain-engine.service brain-mcp.service
  systemctl --user restart brain-engine.service brain-mcp.service

  sleep 2
  if curl -sf "http://localhost:$port/health" &>/dev/null; then
    ok "brain-engine opérationnel (port $port) — unités brain-engine + brain-mcp"
  else
    warn "/health ne répond pas — vérifier : journalctl --user -u brain-engine -n 30"
  fi
  info "Survivre à la déconnexion : loginctl enable-linger \$USER"

  # L'embed périodique : un timer, plus une ligne `crontab` à copier. Arch n'a
  # pas de cron par défaut, et un cron toutes les 6 h ne tourne presque jamais
  # sur un poste rarement allumé 6 h d'affilée. Le timer rattrape au démarrage,
  # et il passe par `embed` : un Ollama injoignable sort en 2, et l'échec se
  # lit dans `systemctl --user status brain-embed` au lieu d'un journal que
  # personne n'ouvre. Proposé par le premier fork (echanges, 28/09).
  if pose_l_embed "$mode"; then
    systemctl --user enable --now brain-embed.timer
    ok "embed périodique : brain-embed.timer (5 min après l'ouverture, puis toutes les 2 h)"
    info "  état : systemctl --user list-timers brain-embed · échec : systemctl --user status brain-embed"
  elif [[ "$mode" != "demo" ]]; then
    info "pas de timer d'embed : instance replica-nomad — les vecteurs appartiennent au master (BRAIN-078)"
  fi

  if [[ "$mode" != "demo" ]]; then
    systemctl --user enable --now brain-maj.timer
    ok "versions de l'amont : brain-maj.timer (une fois par jour) — le briefing dit quand une version plus récente existe"
    info "  suivre l'amont : git remote add upstream <URL_DU_GABARIT> (voir docs/mettre-a-jour.md)"
  fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

cmd="${1:-}"
shift || true

case "$cmd" in
  start)   cmd_start "$@" ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  embed)   cmd_embed ;;
  logs)    cmd_logs ;;
  install) cmd_install "$@" ;;
  *)
    echo "brain-engine — CLI lifecycle"
    echo ""
    echo "Usage : bash scripts/brain-engine.sh <commande>"
    echo ""
    echo "Commandes :"
    echo "  start [--fg]       Démarrer (background par défaut)"
    echo "  stop               Arrêter proprement"
    echo "  status             PID, port, mode, uptime"
    echo "  embed              Embedding one-shot"
    echo "  logs               Tail des logs"
    echo "  install pm2        Installer via pm2"
    echo "  install systemd    Installer via systemd"
    echo ""
    echo "Mode détecté : $(detect_mode)"
    echo "Port détecté : $(detect_port)"
    exit 1
    ;;
esac
