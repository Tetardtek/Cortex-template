#!/bin/bash
# brain-distribuable: oui
# brain-setup.sh — Setup complet brain sur une nouvelle machine
# Usage : [BRAIN_MACHINE=laptop] [PROJECTS_ROOT=~/Dev] bash brain-setup.sh [brain_name] [brain_root] [--sans-service] [--reecrire-claude-md]
# Ex    : bash brain-setup.sh my-brain ~/Dev/Brain
#
# Ce script est idempotent — safe à relancer si une étape a échoué.
# `--sans-service` : tout sauf les unités systemd (conteneur, essai).
# `--reecrire-claude-md` : remplacer un `~/.claude/CLAUDE.md` existant (sauvegardé).

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
# `--sans-service` peut se glisser n'importe où : il passe à `dolt-setup.sh`
# (conteneur, machine sans systemd, essai).
SANS_SERVICE=false
REECRIRE_CLAUDE_MD=false
POSITIONNELS=()
for a in "$@"; do
  case "$a" in
    --sans-service) SANS_SERVICE=true ;;
    --reecrire-claude-md) REECRIRE_CLAUDE_MD=true ;;
    *) POSITIONNELS+=("$a") ;;
  esac
done
BRAIN_NAME="${POSITIONNELS[0]:-my-brain}"
# Par défaut, le dépôt de CE script. `~/Dev/Brain` en dur visait le brain de
# l'owner depuis n'importe quel fork cloné ailleurs : verrou de push, CLAUDE.md,
# venv, Dolt et build lancés sur la prod (relecture du 28/09).
BRAIN_ROOT="${POSITIONNELS[1]:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# Le nom de la MACHINE (desktop, laptop…), distinct du nom de l'instance : les
# registres (`satellites.yml`, `secrets.yml`) déclarent par machine. Il valait
# le nom de l'instance, et un laptop se déclarait `prod-laptop` quand la liste
# attendait `laptop`.
BRAIN_MACHINE="${BRAIN_MACHINE:-$BRAIN_NAME}"
ETAPES=12

# ── Couleurs ─────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
info() { echo -e "   $1"; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     brain-setup.sh — nouvelle machine        ║"
echo "║     brain_name : $BRAIN_NAME"
echo "║     brain_root : $BRAIN_ROOT"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Étape 1 — Les satellites ─────────────────────────────────────────────────
#
# Jusqu'au 27/09, cette étape vérifiait une clé SSH GitHub (en attendant une
# touche : sans terminal, le script s'arrêtait là), puis CLONAIT cinq dépôts de
# l'organisation de l'auteur dans `profil/`, `todo/`, `toolkit/`,
# `progression/` et `reviews/` — des dossiers que le gabarit PORTE déjà, avec
# un README chacun. git refuse de cloner dans un dossier non vide : sous
# `set -e`, l'installation d'un fork ne dépassait jamais l'étape 1.
#
# Un fork a déjà ses satellites : ce sont ces dossiers-là. Il les versionne à
# part quand il le veut (docs/satellites.md). Seule une instance qui DÉCLARE
# ses dépôts (`satellites.yml`) les clone — par machine, à l'étape 3.
echo "[ 1/$ETAPES ] Satellites..."
if [[ -f "$BRAIN_ROOT/satellites.yml" ]]; then
  info "satellites.yml présent — clonage à l'étape 3, par machine"
else
  # La liste suit `gabarit/couches.yml` (part: readme, et profil/) ; le .gitignore
  # du gabarit les tient tous hors du dépôt programme.
  for d in profil projets handoffs infrastructure workspace learning todo toolkit \
           progression reviews vie contenu instance/agents; do
    mkdir -p "$BRAIN_ROOT/$d"
  done
  ok "satellites : tes données (projets/, handoffs/, workspace/, profil/…) et tes surcharges d'agents (instance/agents/)"
  info "ton dépôt les ignore — versionne chacun à part, comme un satellite : docs/satellites.md"
fi

# ── Étape 2 — CLAUDE.md ──────────────────────────────────────────────────────
echo ""
echo "[ 2/$ETAPES ] Configuration CLAUDE.md..."
CLAUDE_TARGET="$HOME/.claude/CLAUDE.md"
CLAUDE_EXAMPLE="$BRAIN_ROOT/profil/CLAUDE.md.example"

mkdir -p "$HOME/.claude"

# Le setup se dit idempotent : l'étape 2 le devient. Elle remplaçait le
# `CLAUDE.md` à CHAQUE passage — sauvegardé, mais ce que l'utilisateur y avait
# ajouté disparaissait de la session suivante (2/10 : 90 lignes sur la machine
# de l'owner). Tranché par l'owner le 2/10 : un fichier existant n'est plus
# touché ; le modèle rendu est posé à côté.
CLAUDE_RENDU="$(mktemp)"
sed -e "s|<BRAIN_ROOT>|$BRAIN_ROOT|g" -e "s|<BRAIN_NAME>|$BRAIN_NAME|g" \
  "$CLAUDE_EXAMPLE" > "$CLAUDE_RENDU"
if [[ -L "$CLAUDE_TARGET" ]]; then
  # Un lien — vers un dépôt de dotfiles, souvent. `cp` le SUIT : il écraserait
  # le fichier du dépôt, et un lien cassé passe `! -f`. Rien ne s'écrit à
  # travers un lien, même avec --reecrire-claude-md.
  cp "$CLAUDE_RENDU" "$CLAUDE_TARGET.modele"
  warn "~/.claude/CLAUDE.md est un lien (→ $(readlink "$CLAUDE_TARGET")) — rien n'est écrit à travers."
  warn "  le modèle rendu : ~/.claude/CLAUDE.md.modele — à reporter dans le fichier que le lien désigne"
elif [[ ! -f "$CLAUDE_TARGET" ]]; then
  cp "$CLAUDE_RENDU" "$CLAUDE_TARGET"
  ok "~/.claude/CLAUDE.md écrit (brain_name=$BRAIN_NAME, brain_root=$BRAIN_ROOT)"
elif cmp -s "$CLAUDE_RENDU" "$CLAUDE_TARGET"; then
  ok "~/.claude/CLAUDE.md déjà à jour"
elif [[ "$REECRIRE_CLAUDE_MD" == true ]]; then
  # Une sauvegarde par passage : un `.bak` unique était écrasé au second
  # lancement par le fichier généré au premier — l'original perdu.
  SAUVEGARDE="$CLAUDE_TARGET.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$CLAUDE_TARGET" "$SAUVEGARDE"
  cp "$CLAUDE_RENDU" "$CLAUDE_TARGET"
  warn "~/.claude/CLAUDE.md remplacé (--reecrire-claude-md) — l'ancien : $SAUVEGARDE"
else
  cp "$CLAUDE_RENDU" "$CLAUDE_TARGET.modele"
  warn "~/.claude/CLAUDE.md existe et diffère du modèle — laissé intact."
  warn "  le modèle rendu : ~/.claude/CLAUDE.md.modele — comparer :"
  warn "  diff -u ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.modele"
  warn "  (ou relancer avec --reecrire-claude-md pour le remplacer, l'ancien sauvegardé)"
fi
rm -f "$CLAUDE_RENDU"

# La skill `brain` — le mode d'emploi du brain pour l'agent, relié dans
# ~/.claude/skills/. Un dossier `brain` déjà là n'est jamais écrasé.
SKILL_CIBLE="$HOME/.claude/skills/brain"
if [[ -d "$BRAIN_ROOT/skills/brain" ]]; then
  mkdir -p "$HOME/.claude/skills"
  if [[ -L "$SKILL_CIBLE" && "$(readlink -f "$SKILL_CIBLE")" != "$(readlink -f "$BRAIN_ROOT/skills/brain")" ]]; then
    warn "~/.claude/skills/brain désigne déjà un AUTRE brain ($(readlink -f "$SKILL_CIBLE")) — laissé tel quel"
  elif [[ -L "$SKILL_CIBLE" || ! -e "$SKILL_CIBLE" ]]; then
    ln -sfn "$BRAIN_ROOT/skills/brain" "$SKILL_CIBLE"
    ok "skill brain reliée (~/.claude/skills/brain)"
  else
    warn "~/.claude/skills/brain existe déjà et n'est pas un lien — laissé tel quel"
  fi
fi

# ── Étape 3 — brain-compose.local.yml ────────────────────────────────────────
echo ""
echo "[ 3/$ETAPES ] brain-compose.local.yml..."
LOCAL_COMPOSE="$BRAIN_ROOT/brain-compose.local.yml"
KERNEL_VERSION=$(grep '^version:' "$BRAIN_ROOT/brain-compose.yml" | awk '{print $2}' | tr -d '"')
# `write_mode: readonly_kernel` ne se déclare que là où le push sera VRAIMENT
# verrouillé — une machine de plus d'une instance, qui a un `satellites.yml`
# (voir le verrou plus bas). Écrit partout, il mentait à chaque fork.
WRITE_MODE=""
[[ -f "$BRAIN_ROOT/satellites.yml" ]] && WRITE_MODE="write_mode: readonly_kernel   # machine de plus d'une instance : son noyau se lit, il ne se pousse pas"

if [[ -f "$LOCAL_COMPOSE" ]]; then
  warn "brain-compose.local.yml existe déjà — skip"
else
  cat > "$LOCAL_COMPOSE" << EOF
# brain-compose.local.yml — Registre machine ($BRAIN_NAME)
# NON VERSIONNÉ — gitignored.

kernel_path: $BRAIN_ROOT
kernel_version: "$KERNEL_VERSION"
last_kernel_sync: "$(date +%Y-%m-%d)"
machine: $BRAIN_MACHINE
${WRITE_MODE}

instances:
  $BRAIN_NAME:
    path: $BRAIN_ROOT
    brain_name: $BRAIN_NAME
    mode: prod
    docs_fetch: ask
    config_status: hydrated
    active: true
EOF
  ok "brain-compose.local.yml créé"
fi

# ── Étape 3 (suite) — les satellites déclarés pour cette machine ────────────────────
if [[ -f "$BRAIN_ROOT/satellites.yml" ]]; then
  python3 "$BRAIN_ROOT/scripts/brain-satellites.py" --brain "$BRAIN_ROOT" --cloner \
    || warn "satellites incomplets — relancer : python3 scripts/brain-satellites.py --cloner"
fi

# ── Étape 3.1 — PATHS.md (remplacer les placeholders) ─────────────────────────
#
# Chaque marqueur se remplace pour lui-même. `<PROJECTS_ROOT>` ne l'était jamais,
# et tout dépendait de `<BRAIN_ROOT>` : un fork gardait `projects/ →
# <PROJECTS_ROOT>`, que le doctor voyait « déclaré et absent » (mesuré le 2/10
# sur un fork installé). Indépendants, un fork déjà installé se
# corrige en relançant le setup.
#
# Les projets : par défaut le dossier où le brain a été cloné (il existe
# forcément) ; `PROJECTS_ROOT=<dossier>` en choisit un autre.
PROJECTS_ROOT="${PROJECTS_ROOT:-$(dirname "$BRAIN_ROOT")}"
_remplaces=()
for _paire in "<BRAIN_ROOT>|$BRAIN_ROOT" "<HOME>|$HOME" "<PROJECTS_ROOT>|$PROJECTS_ROOT"; do
  _m="${_paire%%|*}"; _v="${_paire#*|}"
  if grep -qF "$_m" "$BRAIN_ROOT/PATHS.md" 2>/dev/null; then
    sed -i "s|$_m|$_v|g" "$BRAIN_ROOT/PATHS.md"
    _remplaces+=("$_m")
  fi
done
if [[ ${#_remplaces[@]} -gt 0 ]]; then
  ok "PATHS.md configuré — ${_remplaces[*]} (projets : $PROJECTS_ROOT)"
  [[ " ${_remplaces[*]} " == *" <PROJECTS_ROOT> "* ]] && \
    info "  tes projets vivent ailleurs ? corrige la ligne projects/ de PATHS.md"
else
  info "PATHS.md déjà configuré — skip"
fi

# ── Lock kernel push (nouvelle machine d'une instance = readonly) ────────────
# Le verrou vise une MACHINE DE PLUS d'une instance existante : son noyau se
# lit, il ne se pousse pas. Il était posé partout — et un fork qui avait cloné
# SON dépôt ne pouvait plus pousser son propre brain. Une instance à plusieurs
# machines se reconnaît à son `satellites.yml` ; un fork neuf n'en a pas.
# Tranché par l'owner le 28/09.
PUSH_VERROUILLE=false
if [[ ! -f "$BRAIN_ROOT/satellites.yml" ]]; then
  info "pas de satellites.yml — brain autonome, push laissé ouvert"
elif git -C "$BRAIN_ROOT" remote get-url origin >/dev/null 2>&1; then
  git -C "$BRAIN_ROOT" remote set-url --push origin no_push
  PUSH_VERROUILLE=true
  ok "Kernel push lockée (write_mode: readonly_kernel)"
else
  warn "pas de remote origin — rien à verrouiller"
fi

# ── Étape 3.5 — RETIRÉE le 11/09 ─────────────────────────────────────────────
#
# Elle demandait une « Brain API Key » au format `bk_live_…`, la validait, puis
# faisait :
#
#     sed -i "s|^brain_api_key:.*|brain_api_key: $api_key|" brain-compose.yml
#     ok "Clé enregistrée dans brain-compose.yml"
#
# 🔴 **Le champ `brain_api_key` n'existe plus** — supprimé par [BRAIN-072] avec
# tout le TierGate. Le `sed` ne trouvait donc aucune ligne à remplacer, ne
# changeait rien, et le script annonçait quand même « Clé enregistrée ».
# Mesuré le 11/09 sur une copie : empreinte identique avant et après.
#
# Un installateur qui réclame une clé pour un mécanisme supprimé, puis confirme
# un enregistrement qui n'a pas eu lieu — et ce script est
# `brain-distribuable: oui`, donc c'est ce que voit quelqu'un qui installe un
# fork.
#
# Il n'y a plus de tiers, plus de clé, plus de barrière : BRAIN-072 distribue le
# brain « sans aucune barrière ». Les RÔLES (`_TOKEN_MAP` owner/mcp/public →
# scopes) restent, mais ils ne se configurent pas ici — ils vivent dans
# MYSECRETS, étape suivante.

# ── Étape 4 — MYSECRETS ──────────────────────────────────────────────────────
echo ""
echo "[ 4/$ETAPES ] MYSECRETS..."
SECRETS_DIR="$BRAIN_ROOT/brain-secrets"
MYSECRETS="$SECRETS_DIR/MYSECRETS"

if [[ -f "$MYSECRETS" ]]; then
  ok "MYSECRETS présent ($MYSECRETS)"
else
  warn "MYSECRETS absent — fichier de secrets personnels."
  info ""
  info "Créer le dossier et le fichier :"
  info "  mkdir -p $SECRETS_DIR"
  info "  cp $BRAIN_ROOT/MYSECRETS.example $MYSECRETS"
  info "  → Remplir les valeurs (DB_PASSWORD, JWT_SECRET, etc.)"
  info ""
  warn "Le brain fonctionne sans MYSECRETS mais les sessions secrets seront bloquées."
fi

# ── Étape 5 — Les outils ─────────────────────────────────────────────────────
echo ""
echo "[ 5/$ETAPES ] Outils..."
if command -v claude &>/dev/null; then
  ok "Claude Code installé ($(claude --version 2>/dev/null || echo 'version inconnue'))"
else
  warn "Claude Code non installé — npm install -g @anthropic-ai/claude-code"
fi
# vite 8 (brain-ui) exige Node ^20.19 ou >= 22.12. La doc annonçait « 18+ » :
# le build échouait sur une version qu'elle déclarait suffisante.
NODE_OK=false
if command -v node &>/dev/null && command -v npm &>/dev/null; then
  nv=$(node --version | tr -d v)
  IFS=. read -r nmaj nmin _ <<< "$nv"
  if (( nmaj > 22 || (nmaj == 22 && nmin >= 12) || (nmaj == 20 && nmin >= 19) )); then
    ok "Node.js $nv / npm $(npm --version)"
    NODE_OK=true
  else
    warn "Node.js $nv — brain-ui demande ^20.19 ou >= 22.12 (nvm install --lts)"
  fi
else
  warn "Node.js ou npm absent — brain-ui ne sera pas construit (nvm install --lts)"
fi
PY_OK=false
if command -v python3 &>/dev/null; then
  ok "Python $(python3 --version 2>&1 | awk '{print $2}')"
  PY_OK=true
else
  warn "python3 absent — brain-engine ne sera pas installé"
fi

# ── Étape 6 — brain-engine, dans son venv ───────────────────────────────────
#
# Un venv, pas `pip3 install --break-system-packages` : c'est lui que les
# scripts cherchent (`lib/python.sh`), et lui que le timer d'indexation appelle.
# Installées dans le système, les dépendances n'étaient vues par aucun des deux
#.
echo ""
echo "[ 6/$ETAPES ] brain-engine..."
VENV="$BRAIN_ROOT/brain-engine/.venv"
if $PY_OK; then
  if [[ ! -x "$VENV/bin/python3" ]]; then
    python3 -m venv "$VENV" || warn "python3 -m venv a échoué — installer le module venv (Debian : python3-venv)"
  fi
  if [[ -x "$VENV/bin/python3" ]]; then
    info "Installation des dépendances (brain-engine/requirements.txt)..."
    if "$VENV/bin/python3" -m pip install -q -r "$BRAIN_ROOT/brain-engine/requirements.txt"; then
      ok "brain-engine/.venv prêt"
    else
      warn "pip install a échoué — relancer : brain-engine/.venv/bin/pip install -r brain-engine/requirements.txt"
    fi
  fi
fi

# ── Étape 7 — Dolt, la base du brain ────────────────────────────────────────
# Dolt est le socle de persistance (BRAIN-074). `dolt-setup.sh` installe Dolt
# sans root si besoin, crée la base, pose le service utilisateur et écrit
# `.env.local`. Idempotent : on peut le relancer seul.
echo ""
echo "[ 7/$ETAPES ] Dolt — la base du brain..."
DOLT_OPTS=()
$SANS_SERVICE && DOLT_OPTS+=(--sans-service)
if [[ -f "$BRAIN_ROOT/scripts/dolt-setup.sh" ]]; then
  bash "$BRAIN_ROOT/scripts/dolt-setup.sh" ${DOLT_OPTS[@]+"${DOLT_OPTS[@]}"} \
    || warn "Dolt : l'installation a échoué — relancer : bash scripts/dolt-setup.sh"
else
  warn "scripts/dolt-setup.sh absent — la base reste à installer"
fi

# ── Étape 8 — brain-ui, construit ───────────────────────────────────────────
#
# Le moteur ne sert `/ui/` que si `brain-ui/dist/` existe (server.py). Le setup
# faisait `npm install` sans construire : le dashboard annoncé à la fin
# répondait 404. Et il posait `VITE_USE_MOCK=true` — un dashboard de
# données inventées, servi par un moteur qui avait les vraies.
echo ""
echo "[ 8/$ETAPES ] brain-ui..."
BRAIN_UI="$BRAIN_ROOT/brain-ui"
ENV_UI="$BRAIN_UI/.env.local"
ENV_UI_ANCIEN=$'VITE_USE_MOCK=true\nVITE_BRAIN_API='
if [[ ! -f "$BRAIN_UI/package.json" ]]; then
  warn "brain-ui/package.json absent — skip"
elif ! $NODE_OK; then
  warn "brain-ui non construit — Node manquant ou trop ancien (étape 5)"
else
  # Le moteur sert l'UI : même origine, API relative, vraies données.
  if [[ ! -f "$ENV_UI" || "$(cat "$ENV_UI")" == "$ENV_UI_ANCIEN" ]]; then
    printf 'VITE_USE_MOCK=false\nVITE_BRAIN_API=\n' > "$ENV_UI"
    ok "brain-ui/.env.local — données du moteur local"
  fi
  if [[ ! -d "$BRAIN_UI/node_modules" ]]; then
    info "Installation des dépendances brain-ui..."
    (cd "$BRAIN_UI" && npm ci --silent --no-audit --no-fund) \
      || warn "npm ci a échoué — relancer dans brain-ui/ : npm ci"
  fi
  if (cd "$BRAIN_UI" && npm run build --silent >/dev/null 2>&1); then
    ok "brain-ui construit (brain-ui/dist/)"
  else
    warn "le build a échoué — relancer dans brain-ui/ : npm run build"
  fi
fi

# ── Étape 9 — le moteur, en service ─────────────────────────────────────────
#
# La base était posée en service (étape 7) et le moteur non : le setup finissait
# en conseillant `brain-engine.sh start`, un lancement par fichier de PID qui ne
# survit pas au reboot. Au premier redémarrage, la base tournait, l'API (7700)
# et le MCP (7701) non — MCP en ECONNREFUSED, claims ouverts en repli local, et
# rien ne disait que c'était attendu (Cortex-Template#2, premier fork réel).
# Même règle que pour la base : un service, sauf `--sans-service`.
# Après le build de l'étape 8 : le moteur ne sert `/ui/` que si `dist/` existe.
echo ""
echo "[ 9/$ETAPES ] Le moteur et le serveur MCP..."
MOTEUR_SERVICE=false
if $SANS_SERVICE; then
  info "sans service — le moteur se lance à la main (voir ci-dessous)"
elif ! command -v systemctl >/dev/null 2>&1; then
  warn "systemctl absent — le moteur se lance à la main (voir ci-dessous)"
elif bash "$BRAIN_ROOT/scripts/brain-engine.sh" install systemd; then
  MOTEUR_SERVICE=true
else
  warn "le moteur n'est pas installé en service — relancer : bash scripts/brain-engine.sh install systemd"
fi

# ── Étape 10 — la recherche sémantique (Ollama) ─────────────────────────────
#
# Facultative — le brain tourne sans — mais jusqu'au 28/09 personne ne le
# savait : un fork sans Ollama recevait « Aucun résultat » et croyait son brain
# vide. Le setup le DÉCLARE ; il n'installe rien (Ollama est un paquet
# du système). `ollama-setup.sh` sans option tire le modèle quand Ollama est là.
echo ""
echo "[10/$ETAPES] La recherche sémantique (Ollama)..."
RECHERCHE_PRETE=false
if bash "$BRAIN_ROOT/scripts/ollama-setup.sh" --verifier; then
  RECHERCHE_PRETE=true
else
  warn "recherche sémantique indisponible — le brain tourne sans ; voir ci-dessus pour l'activer"
fi

# ── Étape 11 — les hooks git ────────────────────────────────────────────────
#
# Ils tiennent le claim d'une session en vie (post-commit), refusent un commit
# sans type déclaré dans KERNEL.md (commit-msg), et gardent la base au rythme
# des handoffs (post-merge, post-rewrite). Livrés avec le gabarit, mais rien ne
# les posait : un fork qui suivait le README n'en avait aucun, et le doctor le
# disait — « hooks à réinstaller », « le hook post-commit touche le claim :
# ABSENT » (mesuré le 2/10 sur un fork installé). En dernier : ils
# appellent le venv et la base, posés aux étapes 6 et 7.
echo ""
echo "[11/$ETAPES] Les hooks git..."
if git -C "$BRAIN_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  if bash "$BRAIN_ROOT/scripts/install-brain-hooks.sh" >/dev/null; then
    ok "hooks git installés — un commit porte un type déclaré dans KERNEL.md (feat:, fix:…)"
  else
    warn "les hooks ne se sont pas installés — relancer : bash scripts/install-brain-hooks.sh"
  fi
else
  warn "$BRAIN_ROOT n'est pas un dépôt git — pas de hooks (un clone du gabarit en est un)"
fi

# ── Étape 12 — la vue des agents ────────────────────────────────────────────
#
# Quand le gabarit livre ses agents dans `noyau/agents/`, `agents/` est une VUE :
# des liens vers le noyau, ou vers `instance/agents/` quand l'instance surcharge un
# agent. git ne la versionne pas — un clone neuf n'a donc aucun `agents/`, et le
# boot n'aurait rien à lire. `brain vue` la construit ; les hooks la tiennent
# ensuite à jour (un checkout, une fusion). En dernier : elle calcule le catalogue
# avec le venv de l'étape 6. Sans `noyau/`, rien à faire.
echo ""
echo "[12/$ETAPES] La vue des agents..."
if [[ -d "$BRAIN_ROOT/noyau/agents" ]]; then
  _py="$BRAIN_ROOT/brain-engine/.venv/bin/python3"
  [[ -x "$_py" ]] || _py=python3
  if BRAIN_ROOT="$BRAIN_ROOT" "$_py" "$BRAIN_ROOT/scripts/vue.py" --construire >/dev/null; then
    ok "agents/ construit — tes surcharges vont dans instance/agents/, le noyau reste tel que livré"
  else
    warn "la vue ne s'est pas construite — relancer : bash scripts/brain vue --construire"
  fi
else
  info "pas de noyau/agents/ — agents/ est un dossier ordinaire, rien à construire"
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║              Setup terminé                   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  brain_name : $BRAIN_NAME"
echo "  brain_root : $BRAIN_ROOT"
echo ""
echo "  Prochaines étapes :"
if $SANS_SERVICE; then
  echo "  → Démarrer la base (sans service) :"
  echo "      (cd $BRAIN_ROOT/brain-dolt && dolt sql-server --config config.yaml &)"
fi
if $MOTEUR_SERVICE; then
  echo "  → Le moteur et le serveur MCP tournent en service (brain-engine, brain-mcp) :"
  echo "      bash $BRAIN_ROOT/scripts/brain-engine.sh status"
else
  echo "  → Démarrer le moteur et le serveur MCP (à relancer après chaque reboot) :"
  echo "      bash $BRAIN_ROOT/scripts/brain-engine.sh start"
  echo "    ou, pour qu'ils survivent au reboot :"
  echo "      bash $BRAIN_ROOT/scripts/brain-engine.sh install systemd"
fi
if $RECHERCHE_PRETE; then
  echo "  → Indexer le brain pour la recherche sémantique :"
  echo "      bash $BRAIN_ROOT/scripts/brain-engine.sh embed"
else
  echo "  → La recherche sémantique (facultative) : installer Ollama, puis"
  echo "      bash $BRAIN_ROOT/scripts/ollama-setup.sh --indexer"
fi
echo "  → Le dashboard :"
echo "      http://localhost:${BRAIN_PORT:-7700}/ui/"
echo "  → Brancher Claude Code sur le brain :"
echo "      claude mcp add --transport http brain http://127.0.0.1:${BRAIN_MCP_PORT:-7701}/mcp"
echo "  → Une session :"
echo "      claude → brain boot"
echo ""
# Le résumé dit ce que le setup a FAIT : ce message était inconditionnel, et
# chaque fork lisait « verrouillé » alors que son push était ouvert.
if $PUSH_VERROUILLE; then
  info "Le push vers origin est verrouillé (write_mode: readonly_kernel) : cette machine lit le noyau de l'instance."
  info "Pour pousser quand même : git remote set-url --push origin <url>"
else
  info "Ton fork est à toi : le push vers origin est ouvert."
fi
echo ""
