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

## Les {{NB_ROUTES}} routes de l'API

<!-- genere:routes -->

*Lues dans `server.py` (arbre syntaxique, décorateurs `@app.<méthode>`). La
description est la première ligne de la docstring de chaque route.*

## Les {{NB_OUTILS}} outils MCP

<!-- genere:outils -->

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
