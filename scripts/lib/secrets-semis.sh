#!/usr/bin/env bash
# brain-distribuable: oui  # brain-init.sh le source
# secrets-semis.sh — le dossier des secrets d'un brain : tu par git, et son inventaire posé
#
# Usage :
#   source "$PROGRAMME/scripts/lib/secrets-semis.sh"
#   brain_secrets_taire <racine du brain>        → 0 et dit ce qu'il a ajouté, 1 rien à faire
#   brain_secrets_inventaire <racine du brain>   → 0 et dit le chemin posé, 1 rien à faire,
#                                                  2 refusé (git le verrait), 3 porté par le
#                                                  satellite déclaré, 4 satellites.yml illisible
#
# Le `.gitignore` livré ne taisait que le nom du fichier de secrets (`MYSECRETS`) :
# l'inventaire posé à côté (`brain-secrets/secrets.yml`) était vu par git, et un `git add`
# large l'envoyait sur la forge (issue #24). Le gabarit tait désormais le dossier entier ;
# un brain DÉJÀ semé reçoit la ligne ici, quand `brain init` est relancé.
#
# `brain_secrets_taire` AJOUTE une ligne au `.gitignore` — rien d'autre n'est réécrit — si
# git ne tait pas déjà le dossier (une règle à soi, le bloc d'une instance, le gabarit neuf).
#
# `brain_secrets_inventaire` pose `secrets.yml` s'il est absent : l'en-tête du schéma et une
# liste vide. Sans lui, le doctor rougissait « registre absent » dès que `MYSECRETS`
# existait. Un fichier présent n'est jamais touché. Dans un dépôt git qui le verrait, il
# refuse : un inventaire ne se pose pas là où il partirait sur la forge.
#
# Ni l'un ni l'autre ne LIT un fichier du dossier des secrets : ils testent une présence.

BRAIN_SECRETS_REGLE="/brain-secrets/"

_brain_secrets_tu() {  # <racine> → 0 si git tait le dossier des secrets
  git -C "$1" rev-parse --git-dir >/dev/null 2>&1 || return 1
  git -C "$1" check-ignore -q --no-index "brain-secrets/secrets.yml" 2>/dev/null
}

brain_secrets_taire() {
  local brain="$1" gi="$1/.gitignore"
  if git -C "$brain" rev-parse --git-dir >/dev/null 2>&1; then
    _brain_secrets_tu "$brain" && return 1
  elif [[ -f "$gi" ]] && grep -qxF "$BRAIN_SECRETS_REGLE" "$gi"; then
    return 1
  fi
  # Une ligne, à la fin ; un fichier sans saut de ligne final en reçoit un d'abord.
  if [[ -s "$gi" && -n "$(tail -c1 "$gi")" ]]; then printf '\n' >> "$gi"; fi
  printf '%s\n' "" "# tes secrets et leur inventaire (brain-secrets/) — jamais dans ce dépôt" \
    "$BRAIN_SECRETS_REGLE" >> "$gi"
  printf '%s\n' "$gi"
}

_brain_secrets_satellite() {  # <racine> → 0 déclaré satellite · 1 non · 2 satellites.yml illisible
  # La clé du satellite, lue en YAML — pour QUELQUE machine que ce soit : un coffre déclaré
  # pour le fixe seulement laisse le portable sans coffre, et c'est voulu.
  [[ -f "$1/satellites.yml" ]] || return 1
  python3 - "$1/satellites.yml" 2>/dev/null <<'PY'
import sys
try:
    import yaml
    d = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
    sats = d.get("satellites") or {}
    if not isinstance(sats, dict):
        raise ValueError
except Exception:
    sys.exit(2)
sys.exit(0 if any(str(k).strip().rstrip("/") == "brain-secrets" for k in sats) else 1)
PY
}

brain_secrets_inventaire() {
  local brain="$1" d="$1/brain-secrets" f="$1/brain-secrets/secrets.yml" sat=0
  [[ -e "$f" || -L "$f" ]] && return 1
  # Le coffre déclaré comme satellite : c'est LUI qui porte l'inventaire. Posé ici, il
  # créerait le dossier — et un `--cloner` relancé après un clone raté refuserait un
  # dossier non vide. Sortie 3 ; illisible, on s'abstient aussi (4).
  _brain_secrets_satellite "$brain" || sat=$?
  (( sat == 0 )) && return 3
  (( sat == 2 )) && return 4
  if git -C "$brain" rev-parse --git-dir >/dev/null 2>&1 && ! _brain_secrets_tu "$brain"; then
    return 2
  fi
  mkdir -p "$d"
  cat > "$f" <<'EOF'
# secrets.yml — l'inventaire de tes secrets : des NOMS de clés, jamais une valeur.
# Les valeurs vivent dans MYSECRETS, à côté. Le doctor (« registre des secrets ») compare
# les deux : une clé de MYSECRETS absente d'ici, une clé déclarée et absente de MYSECRETS
# sur cette machine, un doublon, une rotation due.
#
# Une entrée par clé, sous `secrets:` :
#
#   NOM_DE_LA_CLE:
#     scope: nom                    # le préfixe du nom, en minuscules
#     created_at: AAAA-MM-JJ        # la date de déclaration
#     declared_modified_at: AAAA-MM-JJ
#     expires_at: null              # une date passée : rotation due, le doctor rougit
#     rotated_at: null
#     machines: [ma-machine]        # les machines dont MYSECRETS porte la clé
#     required: false
#     description: ''
#
# Les clés de MYSECRETS qui manquent ici se déclarent d'un coup par l'outil du doctor,
# `registre_des_secrets.py --bootstrap` (des noms, aucune valeur lue ni écrite).
secrets:
EOF
  printf '%s\n' "$f"
}
