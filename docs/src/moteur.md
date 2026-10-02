---
label: Brain-engine
groupe: Utiliser
ordre: 8
---

# Brain-engine — le moteur

> Le serveur local du brain : l'API, le dashboard, la recherche, et le serveur
> MCP par lequel Claude Code interroge ton brain.

---

## Ce qu'il sert

| | Adresse | Pour quoi |
|---|---|---|
| API | `http://localhost:7700/` | la recherche, les agents, les claims, la santé (`/health`) |
| Dashboard | `http://localhost:7700/ui/` | tes docs, tes workflows, ton corpus |
| Docs | `http://localhost:7700/docs` | la liste de ces pages, en JSON, lue en direct depuis `docs/` — le dashboard l'affiche |
| MCP | `http://127.0.0.1:7701/mcp` | l'interface de Claude Code |

`brain boot` n'a pas besoin du moteur : les claims passent directement par la
base. Le moteur apporte la recherche, le dashboard et le MCP.

---

## Les commandes

Tout passe par `bash scripts/brain-engine.sh <commande>` :

| Commande | Effet |
|---|---|
| `start` | démarre le moteur **et** le serveur MCP, en arrière-plan. Lance aussi la base si rien ne la sert déjà. `--fg` : au premier plan |
| `stop` | arrête ce que `start` a lancé — et seulement ça |
| `status` | PID, mode, port, `/health`, MCP — et si les unités systemd installées sont celles de cette version |
| `logs` | suit le journal |
| `embed` | indexe le corpus une fois (demande Ollama) |
| `install systemd` | des unités **utilisateur** qui démarrent avec ta session : `brain-engine` et `brain-mcp`, et le timer `brain-embed` (hors mode démo). Se rejoue sans risque : il réécrit les unités et les relance |
| `install pm2` | l'API et le serveur MCP sous pm2, par `brain serve`, relancés s'ils tombent — pas au démarrage de la session |

`stop` n'arrête jamais un moteur qu'il n'a pas lancé : si systemd ou pm2 le
fait tourner, il le dit, et c'est à eux de l'arrêter
(`systemctl --user stop brain-engine`).

Les journaux, hors systemd : `brain-engine.log` et `brain-mcp.log`, à la racine
du brain.

Pour que les unités systemd survivent à la déconnexion : `loginctl enable-linger $USER`.

## `brain serve` — les deux portes, une seule déclaration

`start` et les unités systemd lancent les serveurs par `brain serve` : leur
configuration se décide à **un** endroit, `brain-engine/serve.py`.

```bash
brain serve                  # les deux portes, au premier plan ; si l'une tombe, l'autre s'arrête
brain serve http             # l'API seule — ce que lance l'unité brain-engine
brain serve mcp              # le serveur MCP seul — l'unité brain-mcp
brain serve --declaration    # ce qui serait lancé (ports, mode, secrets), sans rien lancer
```

`install systemd` pose la commande `brain` dans `~/.local/bin`, en lien vers
`scripts/brain`. Sans elle : `bash scripts/brain serve`.

La déclaration se calcule dans cet ordre, la plus forte en dernier : les défauts
(7700, 7701, les scopes du MCP local), `brain-engine/.env.local`,
`brain-secrets/MYSECRETS` (sauf en démo), puis l'environnement déjà posé. Le
fichier de secrets se **lit** comme un `EnvironmentFile` de systemd — des lignes
`CLÉ=valeur` ; rien n'y est exécuté, et aucune valeur n'est jamais affichée.

---

## Les modes

Le mode vient de `BRAIN_MODE`, sinon du `mode:` de `brain-compose.local.yml`
(le setup écrit `prod`).

| Mode | Écriture par l'API |
|---|---|
| `owner`, `prod`, `dev` | oui |
| `template`, `demo` | non — lecture seule |

---

## Les accès

Les deux serveurs écoutent sur toutes les interfaces — donc sur ton réseau
local aussi. Sans jeton, l'API comme le serveur MCP ne répondent qu'à ta
machine elle-même : une autre machine est refusée, et une requête relayée par un
proxy (`X-Forwarded-For`) aussi.

Pour joindre le moteur depuis une autre machine, déclare les jetons dans
`brain-engine/.env.local` :

| Variable | Rôle |
|---|---|
| `BRAIN_TOKEN_OWNER` | tout, écriture comprise |
| `BRAIN_TOKEN_MCP` | la data du brain, pas son noyau — et Claude Code doit alors envoyer l'en-tête `x-api-key: <jeton>` |
| `BRAIN_TOKEN_PUBLIC` | la lecture publique |

Ce sont des **rôles**, pas des paliers : chacun ouvre une partie du brain.

---

## La recherche sémantique

Elle demande **Ollama** et le modèle `nomic-embed-text`. Le script vérifie
l'un, tire l'autre, puis indexe — et dit ce qui manque, avec la commande :

```bash
bash scripts/ollama-setup.sh --indexer
```

Sans Ollama, la recherche ne se tait pas : `brain_search` répond « Recherche
indisponible » et dit quoi faire, au lieu de « Aucun résultat ».

L'indexation est incrémentale : seuls les fichiers modifiés sont relus.
Installé en service, le timer `brain-embed` la relance 5 minutes après
l'ouverture de session, puis toutes les 2 heures. Un passage qui n'atteint pas
Ollama **échoue**, et se lit :

```bash
systemctl --user list-timers brain-embed   # le prochain passage
systemctl --user status brain-embed        # le dernier, et son échec éventuel
```

---

## Diagnostiquer

- **`/health` répond 503** : le moteur n'atteint pas la base. Son message dit
  laquelle ; `systemctl --user status dolt-server` dit si le service tourne.
- **`/ui/` répond 404** : le dashboard n'est pas construit —
  `cd brain-ui && npm run build`, puis relancer le moteur.
- **Le port est déjà pris** : `ss -tlnp | grep 7700` montre qui l'occupe.
