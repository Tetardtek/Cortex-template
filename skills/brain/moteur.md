<!-- Généré depuis skills/brain/src/moteur.md par scripts/docs-generer.py — ne pas éditer ici. -->
# brain-engine — le moteur

`brain-engine/` : l'API (`server.py`, port `BRAIN_PORT`, 7700), le serveur MCP
(`mcp_server.py`, port `BRAIN_MCP_PORT`, 7701), l'indexation (`embed.py`) et
la couche de données (`db.py`, et le CORE : livré dans `brain-engine/core/` dans un
fork, installé en paquet dans l'instance d'origine).

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

## Les 26 routes de l'API

| Méthode | Route | Ce qu'elle fait |
|---|---|---|
| GET | `/agents` | Liste les agents, avec leur classification dérivée depuis agents/CATALOG.yml. |
| POST | `/ambient/notify` | Reçoit un event du daemon Ambient Brain et le broadcast aux clients WebSocket. |
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
| GET | `/focus` | Focus généré depuis Dolt — remplace focus.md statique. Zéro drift. |
| GET | `/health` | Sanity check — vérifie que le moteur répond. |
| GET | `/intentions` | Liste les intentions depuis Dolt. Filtres optionnels par status, project, front. |
| GET | `/intentions/{intention_id}` | Détail d'une intention spécifique avec toutes les relations. |
| GET | `/search` | — |
| GET | `/state` | Environnement fondamental dérivé — Layer 2 uniquement. |
| GET | `/teams` | Liste toutes les teams parsées depuis teams/*.yml. |
| GET | `/visualize` | Retourne les coordonnées 3D UMAP des embeddings brain. Cache JSON regénéré si stale. |
| GET | `/workflows` | Ce qui avance EN AUTONOMIE — le résumé du palier b (BRAIN-079). |
| WS | `/ws` | WebSocket temps réel — les événements BSI (claims, verrous) et ambient. |

*Lues dans `server.py` (arbre syntaxique, décorateurs `@app.<méthode>`). La
description est la première ligne de la docstring de chaque route.*

## Les 11 outils MCP

- **`brain_search`** — Recherche sémantique dans le brain.
- **`brain_state`** — Environnement fondamental du brain — dérivé en temps réel, jamais stocké.
- **`brain_boot`** — Charge le contexte de boot du brain.
- **`brain_workflows`** — Retourne ce qui avance EN AUTONOMIE — le résumé du palier b (BRAIN-079).
- **`brain_agents`** — Retourne les agents disponibles dans le brain.
- **`brain_decisions`** — Retourne les dernières décisions architecturales (ADRs).
- **`brain_focus`** — Retourne le focus genere du brain depuis Dolt.
- **`brain_write`** — Écrit un fichier dans le brain via PUT /brain/{path}.
- **`brain_content`** — Pipeline contenu du brain — vue unifiée atelier + publié.
- **`brain_content_promote`** — Promouvoir un contenu dans le pipeline.
- **`brain_intentions`** — Retourne les intentions du brain depuis Dolt.

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
