<!-- Généré depuis skills/brain/src/moteur.md par scripts/docs-generer.py — ne pas éditer ici. -->
# brain-engine — le moteur

`brain-engine/` : l'API (`server.py`, port `BRAIN_PORT`, 7700), le serveur MCP
(`mcp_server.py`, port `BRAIN_MCP_PORT`, 7701), l'indexation (`embed.py`) et
la couche de données (`db.py`, et le CORE : livré dans `brain-engine/core/` dans un
fork, installé en paquet dans l'instance d'origine).

Deux racines, une seule source, `brain-engine/racines.py` : la **data** (le
brain servi) est reçue par `BRAIN_ROOT`, sinon c'est le parent du programme ; le
**programme** (`.env.local`, `schema.sql`) se sait où il est. Aucun module ne
déduit plus la racine de sa propre position — un test le vérifie dans l'AST.

## Les commandes

```bash
bash scripts/brain-engine.sh start     # l'API et le serveur MCP
bash scripts/brain-engine.sh stop      # seulement ce que start a lancé
bash scripts/brain-engine.sh status
bash scripts/brain-engine.sh embed     # indexer (Ollama + nomic-embed-text)
bash scripts/brain-engine.sh install systemd   # unités UTILISATEUR
```

`stop` n'arrête que ce que `start` a lancé, par son fichier de PID. Un moteur
lancé par systemd s'arrête par `systemctl --user stop brain-engine`.

**Les deux portes se lancent par `brain serve`** (`brain-engine/serve.py`) :
`start` et les unités systemd passent par lui. La déclaration — ports, mode,
secrets, scopes du MCP local — se décide là et nulle part ailleurs : pour
changer un port, `.env.local` ; jamais une ligne `Environment=` dans une unité.
`brain serve http` et `brain serve mcp` remplacent leur processus par le serveur
(le PID suivi est le sien) ; `brain serve` seul tient les deux au premier plan.
MYSECRETS est lu comme un `EnvironmentFile`, jamais exécuté.

## Les 23 routes de l'API

| Méthode | Route | Ce qu'elle fait |
|---|---|---|
| GET | `/agents` | Liste les agents, avec leur classification dérivée depuis agents/CATALOG.yml. |
| POST | `/ambient/notify` | Diffuse un évènement aux clients WebSocket — un compagnon de bureau qui écoute `/ws`, par exemple. |
| GET | `/boot` | — |
| GET | `/brain/{path:path}` | Lit un fichier brain. Localhost = owner, sinon auth requise. |
| PUT | `/brain/{path:path}` | Écrit ou met à jour un document brain. |
| GET | `/bsi/claims` | Liste les claims BSI depuis la base. |
| POST | `/bsi/claims` | Crée un claim BSI dans la base. |
| POST | `/bsi/claims/close-stale` | Ferme les claims restés ouverts au-delà de leur expiration. |
| POST | `/bsi/claims/touch` | Repousse l'expiration des claims ouverts — le signe de vie du BSI. |
| PATCH | `/bsi/claims/{sess_id}` | Met à jour un claim BSI (status, result, close). |
| GET | `/bsi/locks` | Liste les locks actifs depuis la base. |
| POST | `/bsi/locks` | Acquiert un lock fichier. Échoue si déjà tenu par un autre holder. |
| DELETE | `/bsi/locks/{filepath:path}` | Libère un lock fichier. Seul le holder peut libérer. |
| GET | `/bsi/network` | Vue réseau BSI — état de chaque peer + claims open agrégés. |
| GET | `/docs` | Les pages de docs/*.md, avec leur libellé, groupe et ordre déclarés. |
| GET | `/docs/{filename}` | Retourne le contenu brut d'un fichier docs/*.md. |
| GET | `/focus` | Le focus : le cap (à la main), les fiches en cours (calculées), la dernière session. |
| GET | `/health` | Sanity check — vérifie que le moteur répond. |
| GET | `/search` | — |
| GET | `/state` | Environnement fondamental dérivé — Layer 2 uniquement. |
| GET | `/visualize` | Retourne les coordonnées 3D UMAP des embeddings brain. Cache JSON regénéré si stale. |
| GET | `/workflows` | Ce qui avance EN AUTONOMIE — le résumé du palier b (BRAIN-079). |
| WS | `/ws` | WebSocket temps réel — les événements BSI (claims, verrous) et ceux de `/ambient/notify`. |

*Lues dans `server.py` (arbre syntaxique, décorateurs `@app.<méthode>`). La
description est la première ligne de la docstring de chaque route.*

## Les 10 outils MCP

- **`brain_search`** — Recherche sémantique dans le brain.
- **`brain_state`** — Environnement fondamental du brain — dérivé en temps réel, jamais stocké.
- **`brain_boot`** — Charge le contexte de boot du brain.
- **`brain_workflows`** — Retourne ce qui avance EN AUTONOMIE — le résumé du palier b (BRAIN-079).
- **`brain_agents`** — Retourne les agents disponibles dans le brain.
- **`brain_decisions`** — Retourne les dernières décisions architecturales (ADRs).
- **`brain_focus`** — Retourne le focus du brain : ce vers quoi on va, et ce qui est en cours.
- **`brain_write`** — Écrit un fichier dans le brain via PUT /brain/{path}.
- **`brain_content`** — Pipeline contenu du brain — vue unifiée atelier + publié.
- **`brain_content_promote`** — Promouvoir un contenu dans le pipeline.

Branchement de Claude Code, vers **cette** machine :
`claude mcp add --transport http brain http://127.0.0.1:7701/mcp`

## Les accès

Un porteur de jeton reçoit un **rôle** (`owner`, `mcp`, `public`), et le rôle
ouvre des zones — jamais un palier : il n'y en a plus (BRAIN-072). Jetons dans
`brain-engine/.env.local` : `BRAIN_TOKEN_OWNER`, `BRAIN_TOKEN_MCP`,
`BRAIN_TOKEN_PUBLIC`. Avec `BRAIN_TOKEN_MCP`, le client MCP doit envoyer
l'en-tête `x-api-key: <jeton>`.

Sans jeton, l'API et le MCP ne répondent qu'à la machine elle-même (une requête
relayée par `X-Forwarded-For` compte comme distante), bien que les deux serveurs
écoutent sur toutes les interfaces. Avec des jetons, le réseau passe, filtré par
rôle.
