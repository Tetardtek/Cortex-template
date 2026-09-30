#!/usr/bin/env bash
# brain-distribuable: oui
# ollama-setup.sh — la recherche sémantique du brain : Ollama et son modèle.
#
#   bash scripts/ollama-setup.sh              vérifie, et tire le modèle s'il manque
#   bash scripts/ollama-setup.sh --verifier   vérifie seulement — rien n'est installé
#   bash scripts/ollama-setup.sh --indexer    … puis indexe le brain (brain-engine.sh embed)
#
# Sortie : 0 = la recherche peut tourner · 1 = il manque quelque chose (dit, avec la commande)
#
# ── Pourquoi ce script existe ───────────────────────────────────────────────
#
# Sans Ollama, le brain tourne — moteur, MCP, claims — mais n'a pas de mémoire
# sémantique. Et jusqu'au 28/09, rien ne le disait : un fork sans Ollama
# recevait « Aucun résultat » à chaque recherche, et croyait son brain vide.
# Le moteur dit désormais sa panne ; ce script dit ce qui manque, et le règle
# quand c'est possible sans root.
#
# ── Ce qu'il ne fait PAS ────────────────────────────────────────────────────
#
# Il n'installe pas Ollama : c'est un paquet du système, qui demande root et
# dépend des pilotes GPU. Il donne la commande de CE système, il ne la lance
# pas. Tranché par Kevin : déclarer, puis proposer.
#
# Le modèle, lui, se tire par l'API d'Ollama (`/api/pull`) : ni root, ni
# binaire local — un Ollama distant (`OLLAMA_URL`) marche aussi.

set -euo pipefail

BRAIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$BRAIN_ROOT/scripts/lib/python.sh"

MODE=installer
case "${1:-}" in
  "")          ;;
  --verifier)  MODE=verifier ;;
  --indexer)   MODE=indexer ;;
  *) echo "usage : ollama-setup.sh [--verifier | --indexer]" >&2; exit 2 ;;
esac

ok()   { echo "  ✅ $*"; }
info() { echo "  · $*"; }
ko()   { echo "  ❌ $*"; }

# La valeur que le MOTEUR lira : l'environnement, sinon `brain-engine/.env.local`,
# sinon son défaut — et une clé vide vaut le défaut, comme dans le moteur.
lire() {
  local cle="$1" defaut="$2" valeur="${!1:-}"
  if [[ -z "$valeur" && -f "$BRAIN_ROOT/brain-engine/.env.local" ]]; then
    valeur=$(grep -m1 "^${cle}=" "$BRAIN_ROOT/brain-engine/.env.local" | cut -d= -f2- || true)
  fi
  echo "${valeur:-$defaut}"
}
URL=$(lire OLLAMA_URL "http://localhost:11434")
MODELE=$(lire EMBED_MODEL "nomic-embed-text")
URL="${URL%/}"

echo "── la recherche sémantique — Ollama @ $URL, modèle « $MODELE »"

# ── 1. Le service répond-il ? ───────────────────────────────────────────────
# Le service d'abord, le binaire ensuite : un Ollama distant n'a pas de binaire
# ici, et un binaire présent ne dit pas que le service tourne.
tags=$(curl -fsS -m 5 "$URL/api/tags" 2>/dev/null || true)
if [[ -z "$tags" ]]; then
  if command -v ollama >/dev/null 2>&1; then
    ko "Ollama est installé, mais ne répond pas sur $URL"
    info "le démarrer : sudo systemctl enable --now ollama   (ou, sans service : ollama serve)"
  else
    ko "Ollama n'est pas installé — le brain tourne sans, mais sans recherche sémantique"
    id="" ; id_like=""
    if [[ -f /etc/os-release ]]; then
      id=$(. /etc/os-release && echo "${ID:-}")
      id_like=$(. /etc/os-release && echo "${ID_LIKE:-}")
    fi
    case " $id $id_like " in
      *" arch "*)
        info "l'installer : sudo pacman -S ollama   (ollama-cuda ou ollama-rocm pour un GPU)"
        info "puis :        sudo systemctl enable --now ollama" ;;
      *)
        if [[ "$(uname -s)" == Darwin ]]; then
          info "l'installer : brew install ollama   puis : brew services start ollama"
        else
          info "l'installer : voir https://ollama.com/download (paquet de ta distribution, ou script officiel)"
        fi ;;
    esac
  fi
  info "puis relancer : bash scripts/ollama-setup.sh"
  exit 1
fi
ok "Ollama répond"

# ── 2. Le modèle est-il là ? ────────────────────────────────────────────────
a_le_modele() {
  python3 - "$MODELE" "$1" <<'PY'
import json, sys
modele, brut = sys.argv[1], sys.argv[2]
noms = {m.get("name", "") for m in json.loads(brut).get("models", [])}
# « nomic-embed-text » est rangé « nomic-embed-text:latest »
sys.exit(0 if modele in noms or f"{modele}:latest" in noms else 1)
PY
}
if a_le_modele "$tags"; then
  ok "le modèle « $MODELE » est là"
elif [[ $MODE == verifier ]]; then
  ko "le modèle « $MODELE » manque"
  info "le tirer : bash scripts/ollama-setup.sh   (ou : ollama pull $MODELE)"
  exit 1
else
  info "tirage du modèle « $MODELE » — quelques centaines de Mo, une seule fois…"
  if ! curl -fsS -m 1800 "$URL/api/pull" -d "{\"name\": \"$MODELE\", \"stream\": false}" >/dev/null; then
    ko "le tirage a échoué — réessayer : ollama pull $MODELE"
    exit 1
  fi
  tags=$(curl -fsS -m 5 "$URL/api/tags" 2>/dev/null || true)
  a_le_modele "$tags" || { ko "le modèle n'apparaît pas après le tirage"; exit 1; }
  ok "le modèle « $MODELE » est tiré"
fi

# ── 3. Indexer ─────────────────────────────────────────────────────────────
if [[ $MODE == indexer ]]; then
  bash "$BRAIN_ROOT/scripts/brain-engine.sh" embed
else
  info "indexer le brain : bash scripts/brain-engine.sh embed   (ou ce script avec --indexer)"
fi
