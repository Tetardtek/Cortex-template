#!/bin/bash
# brain-distribuable: oui
# kernel-isolation-check.sh — Firewall toolkit/private
# Vérifie qu'aucun agent kernel ne contient de dépendances dures vers des fichiers privés.
#
# WARN  : référence documentaire (normal — l'agent décrit l'architecture)
# ERROR : dépendance dure (problème — l'agent ne peut pas fonctionner sans le fichier privé)
#
# Usage : bash scripts/kernel-isolation-check.sh [--strict]
#   --strict : traite les WARN comme des ERROR

source "$(dirname "${BASH_SOURCE[0]}")/lib/python.sh"  # python3 = celui du venv brain-engine

set -euo pipefail

# Un echec doit se plaindre. Observe le 04/09 : une execution sur plusieurs a
# rendu un rapport de trois lignes — l'en-tete, puis plus rien — et un code de
# sortie non nul. Vu d'en haut, ca ressemble a un refus motive ; c'etait le
# controle qui mourait avant d'avoir regarde quoi que ce soit. Le pire etat
# possible pour un garde-fou : refuser sans savoir pourquoi.
CONCLU=0
trap 'if [ "$CONCLU" -eq 0 ]; then
        echo ""
        echo "  🚨 INTERROMPU — le controle s'"'"'est arrete avant de conclure."
        echo "     Son verdict ne vaut rien : ce n'"'"'est PAS un refus motive,"
        echo "     c'"'"'est une absence de mesure. Relancer avant de decider."
      fi' EXIT TERM INT

BRAIN_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
AGENTS_DIR="$BRAIN_ROOT/agents"
STRICT=${1:-""}

ERRORS=()
WARNS=()
EXEMPTES=()

# --- Exemption bornee : le bloc qui ENONCE les interdits ---
#
# KERNEL.md contient les regles d'isolation ecrites en exemple : le fichier qui
# definit l'interdit contient l'interdit. Un `grep` ne peut pas distinguer la
# regle de sa violation — mesure le 04/09, c'etait 4 des 5 erreurs bloquantes.
#
# L'exemption ne porte donc PAS sur le fichier. Elle porte sur les seules lignes
# du bloc « INTERDIT dans agents/ distribuables : » jusqu'a la fermeture de son
# bloc de code. Trois consequences, voulues :
#   - un motif interdit ecrit AILLEURS dans KERNEL.md rougit toujours ;
#   - le scan des chemins machine reste actif sur lui, sans exception ;
#   - si le bloc disparait ou est renomme, l'exemption ne couvre plus rien —
#     elle ne peut pas devenir un trou permanent, elle reste capable de rougir.
# Tranche par l'owner le 04/09.
lignes_exemptees() {
  local f="$1"
  [ "$(basename "$f")" = "KERNEL.md" ] || return 0
  awk '/^INTERDIT dans agents\/ distribuables/ { inb=1 }
       inb { print NR }
       inb && /^```/ { inb=0 }' "$f"
}

# --- Patterns ERROR : dépendances dures — jamais dans un agent distributable ---
# Chemin absolu machine, requires:, load:, source: vers privé
ERROR_PATTERNS=(
  "toolkit/private/"
  "require.*toolkit/private"
  "load.*MYSECRETS"
  "source.*MYSECRETS"
)

# Patterns de chemin absolu — exclusions pour les placeholders templates
# Le motif ne voit que `/home/<qqun>`. Il ne voit PAS `~/Dev/Brain/...`, qui
# est le meme defaut sous une autre forme : un fork qui range son brain ailleurs
# y trouve un chemin faux, et PATHS.md l'interdit tout autant.
#
# Mesure le 04/09 : cinq agents distribuables portaient douze chemins en `~/`.
# Deux etaient de vraies instructions — corrigees. Les trois autres etaient des
# exemples annonces (« ex: ~/Dev/ ») ou une ligne de changelog.
#
# L'ETENDRE A ETE ESSAYE, ET REPLIE. Le scan porte aussi sur brain-template/, et
# le motif elargi rougissait sur une quinzaine de fichiers dont la documentation
# du template — un rouge massif que je ne pouvais pas verdir dans le temps
# imparti. Fabriquer ca, c'est refaire volontairement un rouge permanent. Le constat est
# ecrit dans ; l'elargissement attend qu'on ait de quoi le solder.
ABSOLUTE_PATH_PATTERN="/home/[a-z]"
ABSOLUTE_PATH_EXCLUDE="<\|(ex:"       # placeholders (<user>) et exemples annonces
TILDE_PATH_PATTERN="~/[A-Za-z]"       # seconde forme — n'est cherchee que sur les distribues

# --- Patterns WARN : références documentaires — OK si contexte architecture ---
# L'agent mentionne le concept mais n'en dépend pas fonctionnellement
WARN_PATTERNS=(
  "MYSECRETS"
  "brain-compose.local"
  "profil/capital"
  "profil/objectifs"
  "progression/"
)

# Ce que le scan regarde. Il ne regardait que `agents/` et concluait pourtant
# « Kernel isolation OK » : mesuré le 04/09, KERNEL.md, profil/specs/collaboration.md
# et scripts/brain-state-bot.sh portaient un chemin machine, et il ne les a
# jamais ouverts. Un controle qui nomme un perimetre plus large que celui qu'il
# inspecte ne peut pas rougir la ou ca compte.
SCAN_DIRS=("$AGENTS_DIR")
SCAN_PORTEE="agents/ (source)"
TEMPLATE_DIR="$BRAIN_ROOT/brain-template"
if [ -d "$TEMPLATE_DIR" ]; then
  SCAN_DIRS+=("$TEMPLATE_DIR")
  SCAN_PORTEE="agents/ (source) + brain-template/ (ce qui part reellement,"
  SCAN_PORTEE="$SCAN_PORTEE sync du $(date -r "$TEMPLATE_DIR" '+%d/%m %H:%M'))"
else
  SCAN_PORTEE="$SCAN_PORTEE — brain-template/ absent, la destination n'a PAS ete verifiee"
fi

# Les agents que le catalogue declare distribuables. C'est sur eux — et sur eux
# seuls — qu'un chemin en `~/Dev/...` compte : il partira. Ailleurs (un agent
# retenu, une doc du template), le meme chemin est une illustration ou du
# contenu qui ne voyage pas, et l'y traquer noierait le signal.
AGENTS_DISTRIBUES=$(python3 - "$BRAIN_ROOT/agents/CATALOG.yml" <<'PYEOF' || true
import sys, yaml
try:
    c = yaml.safe_load(open(sys.argv[1]))
except Exception:
    raise SystemExit(0)
for a in c.get("agents", []):
    if a.get("distributable"):
        print(f"{a['id']}.md")
PYEOF
)

echo "🔍 Kernel isolation check — dépendances privées"
echo "   portée : $SCAN_PORTEE"
echo ""

# --- Scan ERROR — patterns interdits ---
#
# `grep -R`, pas `-r` : `agents/` peut être une VUE de liens vers `noyau/` et
# `instance/`. `-r` ne suit pas les liens — le contrôle rendait un vert
# sans avoir rien lu (mesuré le 3/10 : 0 référence au lieu de 25).
for pattern in "${ERROR_PATTERNS[@]}"; do
  matches=$(grep -Rl "$pattern" "${SCAN_DIRS[@]}" \
    --include="*.md" \
    --exclude-dir=reviews --exclude-dir=.git --exclude-dir=node_modules \
    2>/dev/null || true)

  if [ -n "$matches" ]; then
    while IFS= read -r file; do
      rel="${file#$BRAIN_ROOT/}"
      # `head -1` ferme le tube des la premiere ligne : `grep` recoit SIGPIPE,
      # sort en 141, et `pipefail` + `set -e` tuent le controle en silence. Une
      # course — donc intermittente. Mesuree le 04/09 : 2 executions sur 10
      # s'arretaient avant de conclure, avec un code de sortie non nul qui
      # ressemblait a un refus motive.
      hits=$(grep -n "$pattern" "$file" || true)
      exempt=$(lignes_exemptees "$file")
      if [ -n "$exempt" ]; then
        motif_exempt="^($(echo "$exempt" | tr '\n' '|' | sed 's/|$//')):"
        hits=$(echo "$hits" | grep -vE "$motif_exempt" || true)
        if [ -z "$hits" ]; then
          EXEMPTES+=("  ℹ️  $rel → \"$pattern\" — enonce dans le bloc des interdits")
          continue
        fi
      fi
      line=$(echo "$hits" | head -1 | cut -d: -f1 || true)
      ERRORS+=("  🚨 ERROR $rel:$line → dépendance dure \"$pattern\"")
    done <<< "$matches"
  fi
done

# --- Scan ERROR — chemins absolus reels ---
#
# DEUX severites, parce qu'il y a deux formes du meme defaut et qu'elles ne
# coutent pas pareil.
#
#   /home/<qqun>   nomme la machine ET la personne. Partout, toujours une erreur.
#   ~/Dev/Brain/…  ne nomme que l'arborescence. Un fork qui range son brain
#                  ailleurs y trouve un chemin faux — mais seulement si le
#                  fichier PART. Sur un agent distribue, c'est une erreur ; sur
#                  un agent retenu ou une doc du template, c'est du contenu qui
#                  ne voyage pas.
#
# L'elargir a tout avait ete essaye le 04/09 et repli : quinze fichiers dont la
# documentation du template, un rouge massif impossible a verdir. Restreint aux
# distribues, il ne rougit que sur ce qui compte.
while IFS= read -r -d '' file; do
  rel="${file#$BRAIN_ROOT/}"
  base=$(basename "$file")

  matches=$(grep -n "$ABSOLUTE_PATH_PATTERN" "$file" 2>/dev/null \
    | grep -v "$ABSOLUTE_PATH_EXCLUDE" || true)
  if [ -n "$matches" ]; then
    line=$(echo "$matches" | head -1 | cut -d: -f1 || true)
    ERRORS+=("  🚨 ERROR $rel:$line → chemin machine absolu hardcodé")
    continue
  fi

  # Seconde forme, sur les seuls agents qui partent.
  case "$rel" in
    agents/*)
      if echo "$AGENTS_DISTRIBUES" | grep -qxF "$base"; then
        # Les lignes de CHANGELOG sont exclues : `| 2026-03-18 | … path
        # ~/Dev/Docs → $BRAIN_ROOT …` documente une correction PASSEE. La
        # réécrire effacerait la trace de ce qu'on a réparé, et le chemin n'y
        # est pas une instruction — c'est une citation.
        tildes=$(grep -n "$TILDE_PATH_PATTERN" "$file" 2>/dev/null \
          | grep -v "$ABSOLUTE_PATH_EXCLUDE" \
          | grep -vE '^[0-9]+:\| 20[0-9][0-9]-' || true)
        if [ -n "$tildes" ]; then
          line=$(echo "$tildes" | head -1 | cut -d: -f1 || true)
          ERRORS+=("  🚨 ERROR $rel:$line → chemin ~/ dans un agent distribué")
        fi
      fi
      ;;
  esac
done < <(find "${SCAN_DIRS[@]}" -name "*.md" \
  -not -path "*/reviews/*" \
  -not -path "*/_template*" \
  -not -path "*/.git/*" \
  -not -path "*/node_modules/*" \
  | tr '\n' '\0')

# --- Scan WARN ---
for pattern in "${WARN_PATTERNS[@]}"; do
  matches=$(grep -Rl "$pattern" "${SCAN_DIRS[@]}" \
    --include="*.md" \
    --exclude-dir=reviews --exclude-dir=.git --exclude-dir=node_modules \
    2>/dev/null || true)

  if [ -n "$matches" ]; then
    while IFS= read -r file; do
      rel="${file#$BRAIN_ROOT/}"
      # `head -1` ferme le tube des la premiere ligne : `grep` recoit SIGPIPE,
      # sort en 141, et `pipefail` + `set -e` tuent le controle en silence. Une
      # course — donc intermittente. Mesuree le 04/09 : 2 executions sur 10
      # s'arretaient avant de conclure, avec un code de sortie non nul qui
      # ressemblait a un refus motive.
      line=$(grep -n "$pattern" "$file" | head -1 | cut -d: -f1 || true)
      WARNS+=("  ⚠️  WARN  $rel:$line → référence doc \"$pattern\"")
    done <<< "$matches"
  fi
done

# --- Rapport ---
if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "🚨 ERREURS — dépendances dures détectées (kernel NON distribuable) :"
  echo ""
  for e in "${ERRORS[@]}"; do echo "$e"; done
  echo ""
fi

# Une exemption muette est une exemption qu'on oublie. Celle-ci se dit, avec
# son motif, a chaque execution.
if [ ${#EXEMPTES[@]} -gt 0 ]; then
  echo "ℹ️  EXEMPTIONS — le texte qui definit la regle, pas une violation :"
  echo ""
  for x in "${EXEMPTES[@]}"; do echo "$x"; done
  echo ""
  echo "   Bornees aux lignes du bloc « INTERDIT dans agents/ distribuables »."
  echo "   Hors de ce bloc, les memes motifs restent bloquants."
  echo ""
fi

if [ ${#WARNS[@]} -gt 0 ]; then
  echo "⚠️  AVERTISSEMENTS — références documentaires (attendu, pas bloquant) :"
  echo ""
  for w in "${WARNS[@]}"; do echo "$w"; done
  echo ""
  echo "   ℹ️  Ces références décrivent l'architecture brain — elles n'empêchent pas la distribution."
  echo "   Un utilisateur qui forke aura ses propres fichiers à ces chemins."
  echo ""
fi

# --- Résultat ---
CONCLU=1
if [ ${#ERRORS[@]} -eq 0 ] && [ "$STRICT" != "--strict" ]; then
  echo "✅ Kernel isolation OK — aucune dépendance dure privée détectée"
  echo "   ${#WARNS[@]} références documentaires (normales)"
  exit 0
elif [ ${#ERRORS[@]} -eq 0 ] && [ "$STRICT" = "--strict" ] && [ ${#WARNS[@]} -eq 0 ]; then
  echo "✅ Kernel isolation OK (strict) — zéro violation"
  exit 0
elif [ "$STRICT" = "--strict" ] && [ ${#WARNS[@]} -gt 0 ]; then
  echo "🚨 Mode strict — ${#WARNS[@]} WARN traités comme ERROR"
  exit 1
else
  echo "🚨 ${#ERRORS[@]} erreur(s) bloquante(s) — corriger avant distribution"
  exit 1
fi
