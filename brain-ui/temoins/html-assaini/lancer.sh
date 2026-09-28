#!/usr/bin/env bash
# Témoin : la vue Documentation n'exécute pas le HTML actif d'une page de docs.
#   bash temoins/html-assaini/lancer.sh
# Construit brain-ui contre un FAUX moteur (18801) qui sert une page piégée
# (<img onerror>, <script>, lien javascript:), la sert (18803), ouvre la vue
# dans le Chromium du système (DevTools 18804) et lit le DOM. Aucun port de la
# prod (7700, 7701). Verdict : 0 assaini · 1 le piège passe · 2 pas mesurable.
# Rouge sur le DocsView d'avant le 28/09 (`{@html marked(texte)}` sans DOMPurify).
set -uo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"; UI="$(cd "$ICI/../.." && pwd)"
S=$(mktemp -d); PIDS=()
trap 'for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done; rm -rf "$S"' EXIT
command -v chromium >/dev/null || { echo "chromium absent — rien de mesuré"; exit 2; }
for p in 18801 18803 18804; do
  (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null && { echo "port $p déjà pris — rien de lancé"; exit 2; }
done
(cd "$UI" && VITE_BRAIN_API=http://127.0.0.1:18801 npx vite build --base=/ --outDir "$S/dist" >/dev/null 2>&1) \
  || { echo "build impossible"; exit 2; }
python3 "$ICI/faux_moteur.py" & PIDS+=($!)
python3 -m http.server 18803 --bind 127.0.0.1 --directory "$S/dist" >/dev/null 2>&1 & PIDS+=($!)
chromium --headless=new --no-sandbox --disable-gpu --user-data-dir="$S/chrome" \
  --remote-debugging-port=18804 about:blank >/dev/null 2>&1 & PIDS+=($!)
sleep 2
etat=$(timeout 30 node "$ICI/cdp.mjs" http://127.0.0.1:18803/) || { echo "mesure impossible"; exit 2; }
echo "$etat"
python3 - "$etat" <<'PYEOF'
import json, sys
e = json.loads(sys.argv[1])
if not (e["clic"] and e["texte"]):
    print("la page n'a pas été affichée — rien de mesuré"); sys.exit(2)
passe = [k for k in ("pwned", "img_onerror", "script", "lien_js") if e[k]]
print("✅ assaini" if not passe else f"❌ le piège passe : {', '.join(passe)}")
sys.exit(1 if passe else 0)
PYEOF
