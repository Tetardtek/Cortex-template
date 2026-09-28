# brain-engine — le moteur local

> Ce fichier est **le README distribué avec le template**. Celui de l'instance
> — `brain-engine/README.md` — est un journal de bord : il porte des chemins, un
> vhost et un changelog qui n'ont de sens que sur la machine où ils ont été
> écrits. Les deux ne se confondent pas.

`brain-engine` est un moteur **local**. Il tourne sur votre machine, lit vos
fichiers, et n'appelle aucun service distant. Il n'y a ni compte, ni palier, ni
clé à demander : la validation par paliers commerciaux a été retirée en septembre
2026 et rien ne l'a remplacée.

---

## Ce qu'il fait

**Il indexe le contenu du brain et le rend cherchable par le sens.** Les
embeddings sont calculés en local par Ollama ; aucun texte ne quitte la machine.

Deux serveurs, deux rôles :

| | port par défaut | pour qui |
|---|---|---|
| **API HTTP** | `BRAIN_PORT` (7700) | scripts, outils, intégrations, le dashboard |
| **MCP** | `BRAIN_MCP_PORT` (7701) | un agent Claude Code |

Deux processus distincts, mais pas indépendants : plusieurs outils MCP
(`brain_state`, `brain_workflows`, `brain_agents`, `brain_focus`, `brain_write`,
`brain_intentions`) appellent l'API sur `BRAIN_PORT`. Le MCP sans l'API ne sait
faire que la recherche.

---

## Prérequis

```
Python 3        avec son module venv
Dolt            la base — installé par scripts/dolt-setup.sh s'il manque
Ollama          FACULTATIF — la recherche sémantique ; modèle réglé par EMBED_MODEL
```

`scripts/brain-setup.sh` fait tout : le venv (`brain-engine/.venv`), les
dépendances, la base. À la main :

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

`umap-learn` et `numpy` ne servent qu'à la visualisation (`umap-positions.py`,
`umap-edges.py`). Le moteur démarre sans eux si vous ne l'utilisez pas.

---

## Démarrage

```bash
bash scripts/brain-engine.sh start     # l'API ET le serveur MCP
bash scripts/brain-engine.sh embed     # indexer le corpus — Ollama doit tourner
bash scripts/brain-engine.sh stop
```

Le détail — modes, unités systemd utilisateur, diagnostics : `docs/moteur.md`.

### Brancher un agent Claude Code

```bash
claude mcp add --transport http brain http://127.0.0.1:7701/mcp
```

⚠️ **Pointez vers VOTRE instance.** Un MCP distant lit *son* brain, pas le vôtre :
une URL qui n'est pas la vôtre branche votre agent sur la mémoire de quelqu'un
d'autre. Si vous avez changé `BRAIN_MCP_PORT`, ajustez.

---

## Le backend — deux moteurs, un contrat

```
BRAIN_DB_BACKEND=dolt      (défaut)   MySQL-wire + historique versionné
BRAIN_DB_BACKEND=sqlite               un fichier, rien à installer — sans
                                      versionnement, le CORE refuse les purges
```

Tout passe par `db.py`, qui lit cette variable et traduit ce qu'il faut. **Un
script qui ouvre sa propre connexion écrit dans une base que personne ne lit** —
c'est arrivé, et ça a coûté des mois de registres invisibles.

Le schéma vit dans deux fichiers, un par moteur, et ils ne sont pas deux versions
du même :

```
schema.sql        SQLite
schema-dolt.sql   Dolt — généré, ne pas éditer à la main
views-dolt.sql    Dolt — les vues de surveillance
```

Aucun ne porte de données. La liste des tables : `docs/donnees.md`.

---

## Autorisation — par zone, pas par palier

Chaque chunk indexé porte une **zone**, dérivée de son chemin :

```
kernel      le contrat et les décisions
instance    la configuration de cette machine, les projets actifs
satellite   ce qui vit librement — notes, brouillons, apprentissage
public      ce qui se distribue
```

Un porteur de jeton reçoit un **rôle**, et le rôle donne accès à des zones :

```
owner   public · kernel · instance · satellite · work
mcp     public · work · instance · satellite
public  public
```

Les jetons se déclarent dans `brain-engine/.env.local` — `BRAIN_TOKEN_OWNER`,
`BRAIN_TOKEN_MCP`, `BRAIN_TOKEN_PUBLIC`. Avec `BRAIN_TOKEN_MCP`, le client MCP
doit envoyer l'en-tête `x-api-key: <jeton>` — sans lui, 401. Sans aucun jeton,
voir la section suivante.

---

## ⚠️ Posture réseau — à lire avant d'exposer quoi que ce soit

Les deux serveurs écoutent sur `0.0.0.0`, donc sur **toutes les interfaces**, y
compris le réseau local. Ce n'est pas un défaut à corriger dans votre coin, c'est
un choix par défaut qu'il faut connaître :

- **sans jeton configuré**, l'API et le MCP ne répondent qu'aux appels de la
  machine elle-même : une autre machine reçoit 403 (l'API) ou 401 (le MCP), et
  une requête relayée par un proxy (`X-Forwarded-For`) aussi ;
- **avec des jetons**, l'accès est filtré par rôle, et le port reste ouvert au
  réseau.

Pour joindre le moteur depuis une autre machine — un second poste, un proxy
vers Internet — configurez les jetons. L'adresse d'écoute (`0.0.0.0`) est écrite dans le code : la restreindre
demande aujourd'hui de le modifier.

---

## Les outils MCP

```
brain_boot              charge le contexte d'ouverture de session
brain_focus             direction active, projets, blocages
brain_search            recherche sémantique
brain_state             état dérivé du système
brain_workflows         sessions en cours
brain_agents            charge un agent en contexte
brain_decisions         les décisions récentes
brain_intentions        les intentions ouvertes
brain_content           lit un contenu
brain_content_promote   promeut un contenu
brain_write             écrit un fichier — soumis à l'autorisation par zone
```

---

## Ce qu'il n'y a pas

- **aucun appel réseau sortant** en fonctionnement normal ;
- **aucun palier, aucune licence, aucune clé à demander** ;
- **aucune télémétrie** ;
- **aucun service central** dont dépendrait votre instance.

Si vous trouvez le contraire, c'est un défaut — signalez-le.
