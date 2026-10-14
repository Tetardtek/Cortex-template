---
# Généré depuis docs/src/demarrer.md par scripts/docs-generer.py — ne pas éditer ici.
label: Démarrer
groupe: Démarrer
ordre: 1
---

# Démarrer — du fork au premier `brain boot`

> Ce que fait l'installation, étape par étape, et ce qu'elle touche sur ta
> machine. Kernel v3.6.2.

---

## Ce qu'il faut sur la machine

- **git**
- **Python ≥ 3.12** avec son module `venv` (sur Debian : le paquet `python3-venv`)
- **Node.js ^20.19 ou ≥ 22.12**, avec npm — le dashboard (vite 8) ne se construit pas avant
- **Claude Code** — `npm install -g @anthropic-ai/claude-code`
- **systemd en session utilisateur**, pour que le brain démarre tout seul. Sans
  lui : `--sans-service`, et tu le démarres à la main — `bash scripts/brain-engine.sh
  start`, qui lance aussi la base (voir « Vérifier le moteur »).

Facultatif : **Ollama** et le modèle `nomic-embed-text`, pour la recherche
sémantique dans le brain. Sans eux, le brain tourne, mais ne retrouve rien par
le sens : le setup le vérifie (étape 10) et le dit, et
`bash scripts/ollama-setup.sh` tire le modèle quand Ollama est installé.

---

## Par le paquet — sans fork

Le programme s'installe aussi en paquet, `brain-cortex` : il pose la commande
`brain`, et ton brain est un dossier à toi qui ne garde que tes données (des liens
vers le programme). Il faut **pipx**, avec Python ≥ 3.12 et git ; pas de Node, le
dashboard est déjà construit dans le paquet.

```bash
pipx install --index-url <INDEX> --pip-args="--extra-index-url https://pypi.org/simple" "brain-cortex==<VERSION>"
brain init --verifier
brain init <nom-de-ton-brain> <dossier>       # --sans-service sans systemd utilisateur
cd <dossier> && brain doctor
```

La version s'écrit **exacte** (`==`), et aucun jeton n'est demandé pour installer.
Puis `claude` dans ton dossier : la première fois, **approuve le dossier** — le
programme vit hors de lui, et Claude Code n'en lit ni le noyau ni les agents
avant. La procédure pas à pas, à donner telle quelle à un Claude : la page
**Installer avec Claude**.

La suite de cette page décrit l'autre voie : un fork, cloné par git.

---

## 1. Forker et cloner

Forke le gabarit sur ta forge, puis :

```bash
git clone <URL_DE_TON_FORK> ~/Dev/Brain
cd ~/Dev/Brain
```

## 2. Installer

```bash
bash scripts/brain init --verifier          # les prérequis seulement — rien n'est écrit
bash scripts/brain init <nom-de-ton-brain>
```

`brain init` vérifie d'abord les prérequis : sans git, sans Python ≥ 3.12 ou sans
son module `venv`, il s'arrête **avant d'écrire quoi que ce soit** et dit comment
les installer ; Claude Code et Node manquants se signalent sans arrêter. Puis il
installe le brain **où il est cloné** (un second argument choisit un autre
dossier). Il est idempotent : relancé, il ne change rien ; relance-le si une étape
a échoué. L'ancien nom, `bash scripts/brain-setup.sh <nom>`, fait la même chose.
Ses 13 étapes :

| Étape | Ce qu'elle fait |
|---|---|
| 1. Satellites | crée les dossiers de tes données s'ils manquent — `profil/`, `projets/`, `handoffs/`, `workspace/`, `todo/`… et `instance/agents/` pour tes surcharges ; ton dépôt les ignore. Rien n'est cloné, sauf si ton brain déclare ses dépôts dans `satellites.yml` : ils se clonent alors à l'étape 3 |
| 2. CLAUDE.md | **écrit `~/.claude/CLAUDE.md`** depuis `profil/CLAUDE.md.example`, s'il n'existe pas. S'il existe et diffère, il n'y touche pas : le modèle est posé à côté, en `CLAUDE.md.modele`. Relie aussi la skill `brain` dans `~/.claude/skills/brain` (jamais par-dessus un dossier existant, ni vers un autre brain), et branche la **statusline du brain** dans `~/.claude/settings.json` — le claim de la session, son scope et son âge, la branche, le modèle, le contexte — **seulement s'il n'y a pas de statusline** : une statusline à toi reste, et init te donne la ligne à poser. |
| 3. Configuration | crée `brain-compose.local.yml` (ta machine) — ton instance y déclare `noyau: lecture` : ton `noyau/` se lit, tes retouches vont dans `instance/` —, remplit `PATHS.md` — tes projets y sont attendus à côté du brain, sauf `PROJECTS_ROOT=<dossier>` —, et `focus.md` : le dossier, la date, le nom de ton instance ; ses projets d'exemple s'en vont (« aucun projet »). Ce que tu y as écrit reste |
| 4. MYSECRETS | vérifie le fichier de tes secrets — le brain fonctionne sans —, tait **`brain-secrets/` en entier** dans ton `.gitignore` (un brain déjà installé reçoit la ligne, rien d'autre ne change) et pose son inventaire vide, `brain-secrets/secrets.yml`, s'il manque — sauf quand `satellites.yml` déclare ce dossier comme satellite : c'est lui qui le porte |
| 5. Outils | vérifie Claude Code, Node et Python |
| 6. brain-engine | crée `brain-engine/.venv` et y installe les dépendances |
| 7. Dolt | installe Dolt si besoin (sans root), crée la base `brain-dolt/` et le service utilisateur `dolt-server.service`, et déclare la base au moteur : `brain-engine/.env.local` (`BRAIN_DB_BACKEND=dolt`), jamais réécrit s'il existe |
| 8. brain-ui | installe et **construit** le dashboard |
| 9. Le moteur | installe le moteur et le serveur MCP en **services utilisateur** (`brain-engine`, `brain-mcp`) : ils survivent au reboot |
| 10. La recherche | **vérifie** Ollama et son modèle, et dit ce qui manque — rien n'est installé ; `scripts/ollama-setup.sh` tire le modèle et indexe |
| 11. Les hooks git | installe les hooks du brain dans `.git/hooks` : le claim d'une session reste en vie, la base suit les handoffs, et **un commit doit porter un type déclaré dans `KERNEL.md`** (`feat:`, `fix:`, `todo:`…) — un message libre est refusé, en le disant |
| 12. La vue des agents | construit `agents/` : des liens vers `noyau/agents/`, ou vers `instance/agents/` quand tu surcharges un agent (`brain vue --construire`) |
| 13. Les gardes de Claude Code | ajoute à `.claude/settings.json` deux hooks. Le **garde de lecture** interdit à tout **sous-agent** de Claude Code (le worker de l'autonomie, un Explore…) de lire le personnel — `zone_personal` et `zone_aucune` de `NIVEAUX.yml` ; ta session lit librement. Le **garde des commandes** refuse, au moment où ils partent, cinq gestes qui ont chacun coûté un incident : `git add -A` dans le brain, ton fichier de secrets exécuté par le shell, `rm` par motif dans `workspace/scratch/`, une recherche qui ne suit pas les liens d'une vue, `sed -i` sur un lien. Chacun n'ajoute que son entrée : tes réglages et tes hooks restent. `brain maj` les pose aussi sur un fork déjà installé |

> **L'étape 2 ne remplace pas un `~/.claude/CLAUDE.md` qui existe déjà.** S'il
> diffère du modèle, elle pose le modèle à côté (`~/.claude/CLAUDE.md.modele`) :
> `diff -u ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.modele`, et tu fusionnes ce
> que tu veux. `--reecrire-claude-md` le remplace (l'ancien est sauvegardé en
> `CLAUDE.md.bak-<date>`). Relancer le setup est donc sans risque pour lui.

> Ton fork est à toi : le setup laisse le push vers `origin` ouvert. Il ne le
> verrouille (`write_mode: readonly_kernel`) que sur une machine de plus d'une
> instance qui déclare ses satellites (`satellites.yml`).

> Ton fork lit son noyau : le setup déclare `noyau: lecture` dans ton instance
> (`brain-compose.local.yml`), et `noyau/` est en lecture seule — comme le dossier
> d'un paquet installé. Tes retouches d'agents vont dans `instance/agents/` : une
> surcharge (`<nom>.md`) ou un complément (`<nom>.complement.md`). Ce n'est pas une
> posture : ton moteur, tes sessions et ton push ne changent pas. `noyau: ouvert`
> garde le noyau modifiable. Pas sur une machine qui a un `satellites.yml`.

Sans systemd utilisateur (conteneur, machine partagée) :

```bash
bash scripts/brain init <nom-de-ton-brain> --sans-service
```

## 3. Vérifier le moteur

```bash
bash scripts/brain-engine.sh status
```

L'étape 9 du setup a installé l'API et le dashboard (port 7700) et le serveur
MCP (port 7701) en services : ils tournent déjà, et repartent à chaque
démarrage.

Installé avec `--sans-service`, ou sans systemd : lance-les à la main, à
refaire après chaque reboot.

```bash
bash scripts/brain-engine.sh start
```

Si la base n'est pas servie par son service, `start` la lance aussi. Le
détail et les modes : la page **Brain-engine**.

Le dashboard : `http://localhost:7700/ui/`

## 4. Brancher Claude Code sur ton brain

```bash
claude mcp add --transport http brain http://127.0.0.1:7701/mcp
```

Vers **ta** machine, jamais une autre : un MCP lit le brain de celui qui le sert.
Si tu as posé `BRAIN_TOKEN_MCP`, le client doit envoyer l'en-tête
`x-api-key: <jeton>`.

## 5. Première session

```bash
claude
```

Puis tape `brain boot`, ou un type de session : `brain boot work/<projet>`.
Les six types sont sur la page **Sessions**.

C'est normal qu'un brain neuf soit vide : il n'a encore ni projets, ni
fiches. Il se remplit en travaillant.

---

## Les ports

| Service | Port | Variable |
|---|---|---|
| API + dashboard | 7700 | `BRAIN_PORT` |
| serveur MCP | 7701 | `BRAIN_MCP_PORT` |
| adresse d'écoute des deux (127.0.0.1 par défaut) | — | `BRAIN_BIND` |
| base Dolt (127.0.0.1 seulement) | 3307 | `BRAIN_DOLT_PORT` |

## Mettre à jour depuis le gabarit

Une nouvelle version se fusionne dans ton fork, puis le moteur se relance et la
base suit le schéma : la page **Se mettre à jour** donne les 8 étapes.

## MYSECRETS absent — c'est grave ?

Non. C'est le fichier de tes secrets de projets (jetons, mots de passe), dans
`brain-secrets/`. Le brain démarre sans ; `MYSECRETS.example` montre la forme.

À côté, `brain-secrets/secrets.yml` est leur **inventaire** : les noms des clés,
jamais une valeur. `brain init` le pose vide ; le doctor (« registre des
secrets ») compare les deux, et son outil `registre_des_secrets.py --bootstrap`
déclare d'un coup les clés qui manquent. Le dossier entier reste hors de ton
dépôt : ton `.gitignore` tait `/brain-secrets/`.
