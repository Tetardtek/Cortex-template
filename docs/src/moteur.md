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
| `status` | PID, mode, port, `/health`, MCP |
| `logs` | suit le journal |
| `embed` | indexe le corpus une fois (demande Ollama) |
| `install systemd` | deux unités **utilisateur** qui démarrent avec ta session : `brain-engine` et `brain-mcp` |
| `install pm2` | l'API seule sous pm2, relancée si elle tombe — ni le MCP, ni au démarrage de la session |

`stop` n'arrête jamais un moteur qu'il n'a pas lancé : si systemd ou pm2 le
fait tourner, il le dit, et c'est à eux de l'arrêter
(`systemctl --user stop brain-engine`).

Les journaux, hors systemd : `brain-engine.log` et `brain-mcp.log`, à la racine
du brain.

Pour que les unités systemd survivent à la déconnexion : `loginctl enable-linger $USER`.

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

Elle demande **Ollama** et le modèle `nomic-embed-text` :

```bash
ollama pull nomic-embed-text
bash scripts/brain-engine.sh embed
```

L'indexation est incrémentale : seuls les fichiers modifiés sont relus.

---

## Diagnostiquer

- **`/health` répond 503** : le moteur n'atteint pas la base. Son message dit
  laquelle ; `systemctl --user status dolt-server` dit si le service tourne.
- **`/ui/` répond 404** : le dashboard n'est pas construit —
  `cd brain-ui && npm run build`, puis relancer le moteur.
- **Le port est déjà pris** : `ss -tlnp | grep 7700` montre qui l'occupe.
