---
label: Démarrer
groupe: Démarrer
ordre: 1
---

# Démarrer — du fork au premier `brain boot`

> Ce que fait l'installation, étape par étape, et ce qu'elle touche sur ta
> machine. Kernel v{{VERSION}}.

---

## Ce qu'il faut sur la machine

- **git**
- **Python 3** avec son module `venv` (sur Debian : le paquet `python3-venv`)
- **Node.js ^20.19 ou ≥ 22.12**, avec npm — le dashboard (vite 8) ne se construit pas avant
- **Claude Code** — `npm install -g @anthropic-ai/claude-code`
- **systemd en session utilisateur**, pour que la base démarre toute seule. Sans
  lui : `--sans-service`, et tu lances la base à la main.

Facultatif : **Ollama** et le modèle `nomic-embed-text`, pour la recherche
sémantique dans le brain. Sans eux, le brain tourne, mais ne retrouve rien par
le sens : le setup le vérifie (étape 10) et le dit, et
`bash scripts/ollama-setup.sh` tire le modèle quand Ollama est installé.

---

## 1. Forker et cloner

Forke le gabarit sur ta forge, puis :

```bash
git clone <URL_DE_TON_FORK> ~/Dev/Brain
cd ~/Dev/Brain
```

## 2. Installer

```bash
bash scripts/brain-setup.sh <nom-de-ton-brain>
```

Il installe le brain **où il est cloné** (un second argument choisit un autre
dossier). Le script est idempotent : relance-le si une étape a échoué. Ses onze étapes :

| Étape | Ce qu'elle fait |
|---|---|
| 1. Satellites | vérifie `profil/`, `todo/`, `toolkit/`, `progression/`, `reviews/` — les dossiers du gabarit. Rien n'est cloné. |
| 2. CLAUDE.md | **écrit `~/.claude/CLAUDE.md`** depuis `profil/CLAUDE.md.example`, s'il n'existe pas. S'il existe et diffère, il n'y touche pas : le modèle est posé à côté, en `CLAUDE.md.modele`. Relie aussi la skill `brain` dans `~/.claude/skills/brain` (jamais par-dessus un dossier existant, ni vers un autre brain). |
| 3. Configuration | crée `brain-compose.local.yml` (ta machine), remplit `PATHS.md` — tes projets y sont attendus à côté du brain, sauf `PROJECTS_ROOT=<dossier>` |
| 4. MYSECRETS | vérifie seulement — le brain fonctionne sans |
| 5. Outils | vérifie Claude Code, Node et Python |
| 6. brain-engine | crée `brain-engine/.venv` et y installe les dépendances |
| 7. Dolt | installe Dolt si besoin (sans root), crée la base `brain-dolt/` et le service utilisateur `dolt-server.service` |
| 8. brain-ui | installe et **construit** le dashboard |
| 9. Le moteur | installe le moteur et le serveur MCP en **services utilisateur** (`brain-engine`, `brain-mcp`) : ils survivent au reboot |
| 10. La recherche | **vérifie** Ollama et son modèle, et dit ce qui manque — rien n'est installé ; `scripts/ollama-setup.sh` tire le modèle et indexe |
| 11. Les hooks git | installe les hooks du brain dans `.git/hooks` : le claim d'une session reste en vie, la base suit les handoffs, et **un commit doit porter un type déclaré dans `KERNEL.md`** (`feat:`, `fix:`, `todo:`…) — un message libre est refusé, en le disant |

> **L'étape 2 ne remplace pas un `~/.claude/CLAUDE.md` qui existe déjà.** S'il
> diffère du modèle, elle pose le modèle à côté (`~/.claude/CLAUDE.md.modele`) :
> `diff -u ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.modele`, et tu fusionnes ce
> que tu veux. `--reecrire-claude-md` le remplace (l'ancien est sauvegardé en
> `CLAUDE.md.bak-<date>`). Relancer le setup est donc sans risque pour lui.

> Ton fork est à toi : le setup laisse le push vers `origin` ouvert. Il ne le
> verrouille (`write_mode: readonly_kernel`) que sur une machine de plus d'une
> instance qui déclare ses satellites (`satellites.yml`).

Sans systemd utilisateur (conteneur, machine partagée) :

```bash
bash scripts/brain-setup.sh <nom-de-ton-brain> --sans-service
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
intentions. Il se remplit en travaillant.

---

## Les ports

| Service | Port | Variable |
|---|---|---|
| API + dashboard | 7700 | `BRAIN_PORT` |
| serveur MCP | 7701 | `BRAIN_MCP_PORT` |
| base Dolt (127.0.0.1 seulement) | 3307 | `BRAIN_DOLT_PORT` |

## Mettre à jour depuis le gabarit

Une nouvelle version se fusionne dans ton fork, puis le moteur se relance et la
base suit le schéma : la page **Se mettre à jour** donne les sept étapes.

## MYSECRETS absent — c'est grave ?

Non. C'est le fichier de tes secrets de projets (jetons, mots de passe), dans
`brain-secrets/`. Le brain démarre sans ; `MYSECRETS.example` montre la forme.
