---
# Généré depuis docs/src/architecture.md par scripts/docs-generer.py — ne pas éditer ici.
label: Architecture
groupe: Comprendre
ordre: 3
---

# Architecture

> Comment les pièces s'assemblent — la version humaine. La règle qui fait foi
> est dans `KERNEL.md`.

---

## Trois couches

**Le noyau — ce qui fait le brain.** Il est le même dans chaque fork.

- `KERNEL.md`, `brain-constitution.md` — les règles
- `brain-compose.yml` — la configuration du programme (version 3.4.2, kerneluser, postures)
- `noyau/agents/` — les 58 agents, lus par la vue `agents/`
- `contexts/` — un manifest par type de session
- `scripts/` — les outils : claims, base, synchronisation, installation
- `brain-engine/` — le moteur : API, recherche, serveur MCP

**Les satellites — ta mémoire.** `todo/`, `toolkit/`, `progression/`,
`reviews/`. Ils vivent à part du noyau, et se versionnent à part si tu le veux
— voir **Satellites**.

**`profil/` — entre les deux.** Il se versionne à part comme un satellite, mais
`KERNEL.md` le range dans le noyau : sa partie invariante (collaboration,
architecture) ne change qu'avec ta confirmation. Le gabarit en livre les specs
partagées, `profil/specs/`.

**L'instance — ta machine.** Jamais partagée, jamais versionnée avec le noyau :

- `brain-compose.local.yml` — le nom de ta machine, ton mode
- `brain-engine/.env.local` — le backend de la base, les ports, les jetons
- `brain-dolt/` — la base
- `brain-secrets/MYSECRETS` — tes secrets de projets

---

## La base — Dolt

Tout ce qui est structuré — claims, décisions, catalogue des agents, index de
recherche — vit dans **Dolt**, une base SQL versionnée comme git :
19 tables et 5 vues. Le narratif reste en Markdown.

La base écoute sur `127.0.0.1` seulement : elle n'est jamais exposée. Le
détail est sur la page **Données**.

SQLite reste possible (`BRAIN_DB_BACKEND=sqlite` dans `brain-engine/.env.local`),
mais sans versionnement : le moteur refuse alors les purges, et l'indexation
s'arrête le jour où un fichier sort du corpus. À choisir en connaissance de
cause.

---

## Les zones — qui écrit où

| Zone | Contient | Protection |
|---|---|---|
| **noyau** | `KERNEL.md`, `CLAUDE.md`, `PATHS.md`, `BRAIN-INDEX.md`, `brain-constitution.md`, `brain-compose.yml`, `noyau/agents/`, `profil/` | aucune modification sans décision humaine explicite |
| **satellites** | `todo/`, `toolkit/`, `progression/`, `reviews/`, `handoffs/`, `workspace/` | chaque satellite a son scribe |
| **instance** | `focus.md`, `projets/`, `brain-compose.local.yml`, `instance/` | propre à une machine |
| **work** | tes dépôts de projets | le brain documente, ne possède pas |

Le type de session décide lesquelles il peut écrire — voir **Sessions**.

---

## Les agents

Un agent est un fichier `agents/<nom>.md` : un en-tête qui déclare sa portée,
son rôle et ses déclencheurs, puis ce qu'il sait faire. Il arrive de trois
façons : le manifest de la session le charge (L1), son domaine est détecté, ou
tu le demandes — « charge l'agent security ». La liste complète : **Agents**.

`agents/` est une **vue** que `brain vue` construit : chaque `agents/<nom>.md` est un
lien vers ta version (`instance/agents/<nom>.md`) si tu en as une, sinon vers celle
du noyau livré (`noyau/agents/<nom>.md`). Un complément
(`instance/agents/<nom>.complement.md`) s'y ajoute : la vue écrit alors un fichier
assemblé — l'agent, puis le complément. Tu gardes tout : `brain maj` met le noyau à
jour sans toucher à tes surcharges ni à tes compléments.

**Ce que la vue sert au public.** Au jeton `public` du moteur, la vue ne sert que les
agents du noyau livré — ce qui se résout dans `noyau/agents/`. Tes surcharges, les
fichiers assemblés avec un complément, `instance/agents/` et tout fichier réel posé
dans `agents/` restent à toi : lisibles en owner et par le jeton `mcp`, jamais par
`public` — à la lecture comme dans l'index de recherche. Sans `noyau/agents/` (un
brain d'avant la vue), `agents/` reste public comme avant. L'index compte chaque agent
une fois, sous son nom de vue (`agents/<nom>.md`, jamais sa source), et un lien de la
vue vers la zone privée ou hors du brain n'est jamais indexé.

**Un fork lit son noyau.** Le setup déclare `noyau: lecture` dans l'instance active
de `brain-compose.local.yml` (à côté de `posture:`), et la vue pose alors `noyau/`
en lecture seule : tes retouches vont dans `instance/`, une surcharge ou un
complément. Le hook de posture, là où il est installé, refuse un commit qui touche
`noyau/` (`BRAIN_KERNEL_OVERRIDE=1` pour l'exception) ; `instance/` passe. Ce n'est
pas une posture : ni le mode du moteur ni tes sessions ne changent, et seul
`noyau/` est figé. `brain maj` lève le verrou le temps de la fusion, puis le
repose. `noyau: ouvert` garde le noyau modifiable ; sans la clé, rien ne change
(le brain d'origine ne la déclare pas, c'est là que le noyau se forge). Un
worktree n'est jamais verrouillé.

---

## Plusieurs machines

Chaque machine a **sa propre base** : rien ne la réplique. Le code et la doc
voyagent par git ; les sessions des autres machines se lisent par SSH, pour
les machines déclarées sous `peers:` dans `brain-compose.local.yml`
(`bash scripts/bsi-query.sh peers`).
