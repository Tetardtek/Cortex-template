#!/usr/bin/env bash
# brain-distribuable: oui
# dolt-setup.sh — la base du brain en Dolt, installée et servie. Idempotent.
#
#   bash scripts/dolt-setup.sh                 installe ce qui manque, lance le service
#   bash scripts/dolt-setup.sh --sans-service  tout sauf l'unité systemd (conteneur, essai)
#
# Dolt est le socle de persistance (BRAIN-074). Le gabarit tournait pourtant en
# SQLite par défaut — un reste du palier « free » des tiers, retiré par BRAIN-072 —
# et `brain-setup.sh` ne savait rien de Dolt : un fork ne pouvait y passer qu'à la
# main. Sur SQLite, le CORE refuse une purge sans gel (`SansVersionnement`) : le
# jour où un fichier sort du corpus, l'indexation s'arrête. Ce script est ce qui
# manquait pour que le défaut puisse être Dolt.
#
# Chaque étape vérifie avant d'agir, et se relance sans rien casser :
#   1. dolt        celui du système s'il existe ; sinon la version épinglée,
#                  téléchargée dans ~/.local/bin — sans root
#   2. la base     brain-dolt/ : dolt init, schéma, vues, un premier commit
#   3. le serveur  config.yaml — 127.0.0.1 seulement, le port de BRAIN_DOLT_PORT
#   4. le service  une unité systemd UTILISATEUR, dolt-server.service
#   5. le moteur   brain-engine/.env.local : BRAIN_DB_BACKEND=dolt
#
# Variables : DOLT_VERSION (2.3.2), BRAIN_DOLT_PORT (3307), DOLT_PREFIX (~/.local),
#             XDG_CONFIG_HOME (~/.config).

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/premieres.sh"

BRAIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOLT_VERSION="${DOLT_VERSION:-2.3.2}"
PORT="${BRAIN_DOLT_PORT:-3307}"
PREFIX="${DOLT_PREFIX:-$HOME/.local}"
BASE="$BRAIN_ROOT/brain-dolt"
UNITES="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE=true
[[ "${1:-}" == "--sans-service" ]] && SERVICE=false

ok()   { echo "  ✅ $*"; }
info() { echo "  · $*"; }
ko()   { echo "  ❌ $*" >&2; exit 1; }

echo "── Dolt, la base du brain ──────────────────────"

# 1. dolt ─────────────────────────────────────────────────────────────────────
if ! command -v dolt >/dev/null 2>&1; then
  case "$(uname -m)" in
    x86_64)        arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) ko "architecture $(uname -m) non prise en charge — installer Dolt à la main (dolthub.com)" ;;
  esac
  # L'empreinte de l'archive, épinglée : un binaire qui ne correspond pas n'est
  # pas installé. DoltHub ne publie pas de fichier d'empreintes pour cette
  # version — celles-ci ont été calculées le 27/09 sur le téléchargement GitHub
  # (TLS) : une confiance au premier usage, dite. Une autre version demande
  # DOLT_SHA256 explicitement.
  case "${DOLT_VERSION}-${arch}" in
    2.3.2-amd64) attendu=7a2949fa2b2b3799ee1e57e6d64519a8d65d675fd832f6469d4e07e5a1c72b14 ;;
    2.3.2-arm64) attendu=b2231e84e06adf95ea81c6e889409ee7a72de5a96cb03bbf1bf3433ac763cf9c ;;
    *) attendu="${DOLT_SHA256:-}" ;;
  esac
  [[ -n "$attendu" ]] || ko "aucune empreinte connue pour Dolt ${DOLT_VERSION} (${arch}) — fournir DOLT_SHA256"
  url="https://github.com/dolthub/dolt/releases/download/v${DOLT_VERSION}/dolt-linux-${arch}.tar.gz"
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  info "téléchargement de Dolt ${DOLT_VERSION} (${arch})…"
  curl -fsSL "$url" -o "$tmp/dolt.tar.gz" || ko "téléchargement impossible : $url"
  obtenu=$(sha256sum "$tmp/dolt.tar.gz" | cut -d' ' -f1)
  [[ "$obtenu" == "$attendu" ]] || ko "empreinte de l'archive inattendue ($obtenu) — rien n'est installé"
  tar -xzf "$tmp/dolt.tar.gz" -C "$tmp"
  mkdir -p "$PREFIX/bin"
  install -m 0755 "$tmp/dolt-linux-${arch}/bin/dolt" "$PREFIX/bin/dolt"
  export PATH="$PREFIX/bin:$PATH"
  command -v dolt >/dev/null 2>&1 || ko "dolt installé dans $PREFIX/bin mais introuvable"
  info "ajouter $PREFIX/bin au PATH de la session si ce n'est pas déjà le cas"
fi
ok "dolt $(dolt version | premieres 1 | awk '{print $3}') — $(command -v dolt)"

# 2. la base ──────────────────────────────────────────────────────────────────
if [[ -d "$BASE/.dolt" ]]; then
  ok "brain-dolt/ existe déjà — rien réinitialisé"
else
  mkdir -p "$BASE"
  nom=$(git config --get user.name 2>/dev/null || echo brain)
  mel=$(git config --get user.email 2>/dev/null || echo brain@localhost)
  (cd "$BASE" && dolt init --name "$nom" --email "$mel" >/dev/null)
  (cd "$BASE" && dolt sql < "$BRAIN_ROOT/brain-engine/schema-dolt.sql")
  [[ -f "$BRAIN_ROOT/brain-engine/views-dolt.sql" ]] && \
    (cd "$BASE" && dolt sql < "$BRAIN_ROOT/brain-engine/views-dolt.sql")
  (cd "$BASE" && dolt add -A && dolt commit -m "schema initial du brain" >/dev/null)
  tables=$(cd "$BASE" && dolt sql -q "show full tables" -r csv | tail -n +2 | grep -c BASE || true)
  ok "brain-dolt/ créée — ${tables} tables"
fi

# 3. le serveur ───────────────────────────────────────────────────────────────
if [[ -f "$BASE/config.yaml" ]]; then
  ok "config.yaml existe déjà — gardé tel quel"
else
  cat > "$BASE/config.yaml" <<EOF
# Le serveur Dolt du brain — localhost seulement : la base n'est jamais exposée.
listener:
  host: 127.0.0.1
  port: ${PORT}
EOF
  ok "config.yaml — 127.0.0.1:${PORT}"
fi

# 4. le service ───────────────────────────────────────────────────────────────
if $SERVICE; then
  command -v systemctl >/dev/null 2>&1 || ko "systemctl absent — relancer avec --sans-service et démarrer le serveur à la main"
  mkdir -p "$UNITES"
  unite="$UNITES/dolt-server.service"
  attendu=$(cat <<EOF
[Unit]
Description=Dolt SQL Server — la base du brain
After=default.target

[Service]
Type=simple
WorkingDirectory=${BASE}
ExecStart=/usr/bin/env dolt sql-server --config config.yaml
Environment=PATH=${PREFIX}/bin:/usr/local/bin:/usr/bin:/bin
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
)
  if [[ -f "$unite" && "$(cat "$unite")" != "$attendu" ]]; then
    # L'unité d'un AUTRE brain de la machine : la remplacer servirait, au
    # prochain démarrage, la base de CE brain à la place de la sienne — la prod
    # de l'owner remplacée par une base vide (relecture du 28/09). Refuser.
    autre=$(sed -n 's/^WorkingDirectory=//p' "$unite" | premieres 1)
    if [[ -n "$autre" && "$(readlink -f "$autre")" != "$(readlink -f "$BASE")" ]]; then
      ko "dolt-server.service sert déjà un AUTRE brain ($autre) — rien n'est remplacé. Relancer avec --sans-service, et servir cette base sur un autre port (BRAIN_DOLT_PORT)."
    fi
    mv "$unite" "$unite.avant-$(date +%Y%m%d%H%M%S)"
    info "une unité différente existait (même base) — sauvegardée à côté"
  fi
  printf '%s\n' "$attendu" > "$unite"
  systemctl --user daemon-reload
  systemctl --user enable --now dolt-server.service
  ok "dolt-server.service activé"
else
  info "sans service — démarrer : (cd brain-dolt && dolt sql-server --config config.yaml)"
fi

# 5. le moteur ────────────────────────────────────────────────────────────────
env_local="$BRAIN_ROOT/brain-engine/.env.local"
if [[ ! -f "$env_local" && -f "$BRAIN_ROOT/brain-engine/.env.local.example" ]]; then
  cp "$BRAIN_ROOT/brain-engine/.env.local.example" "$env_local"
fi
touch "$env_local"
if grep -q '^BRAIN_DB_BACKEND=' "$env_local"; then
  sed -i 's/^BRAIN_DB_BACKEND=.*/BRAIN_DB_BACKEND=dolt/' "$env_local"
else
  echo "BRAIN_DB_BACKEND=dolt" >> "$env_local"
fi
if [[ "$PORT" != "3307" ]]; then
  if grep -q '^BRAIN_DOLT_PORT=' "$env_local"; then
    sed -i "s/^BRAIN_DOLT_PORT=.*/BRAIN_DOLT_PORT=${PORT}/" "$env_local"
  else
    echo "BRAIN_DOLT_PORT=${PORT}" >> "$env_local"
  fi
fi
ok "brain-engine/.env.local — BRAIN_DB_BACKEND=dolt"
