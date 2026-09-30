# Brain

> Un contexte persistant pour Claude Code. Tu forkes, tu installes, tu bootes.

Le brain est une mémoire externe pour tes sessions Claude Code : des agents
spécialisés qui persistent d'une session à l'autre, des types de session qui
chargent seulement ce dont tu as besoin, et une base versionnée (Dolt) qui garde
ce qui s'est passé. Chaque session repart d'un état connu.

Le gabarit est **distribué tel quel** : tout ce qu'il contient est à toi, sans
clé ni palier.

---

## Démarrer

Il faut : git, Python 3 (avec `venv`), Node.js ^20.19 ou ≥ 22.12, et Claude Code.

```bash
git clone <URL_DE_TON_FORK> ~/Dev/Brain
cd ~/Dev/Brain
bash scripts/brain-setup.sh <nom-de-ton-brain>
bash scripts/brain-engine.sh start
claude mcp add --transport http brain http://127.0.0.1:7701/mcp
```

Puis `claude`, et tape `brain boot`.

> ⚠️ L'installation **remplace `~/.claude/CLAUDE.md`** — l'ancien est gardé en
> `CLAUDE.md.bak-<date>`. Le détail de chaque étape : [docs/demarrer.md](docs/demarrer.md).

---

## Ce que tu as

- **Des agents** — debug, review, sécurité, tests, perf, déploiement, coach,
  scribes… Ils se chargent selon la session, selon le domaine, ou à la demande.
- **Six types de session** — `work`, `brain`, `explore`, `pilote`, `chill`,
  `learning`. Chacun dit ce qu'il charge et où il peut écrire.
- **Des claims** — chaque session laisse une trace en base ; les sessions
  parallèles se voient.
- **Un noyau protégé** — les règles ne changent qu'avec ta confirmation.
- **brain-engine** — une API locale, la recherche sémantique, un dashboard, et
  un serveur MCP pour Claude Code.

---

## La documentation

Dans [docs/](docs/README.md), et dans le dashboard (`http://localhost:7700/ui/`,
onglet Docs) :

| | |
|---|---|
| [Démarrer](docs/demarrer.md) | l'installation, étape par étape |
| [Sessions](docs/sessions.md) | les types, ce qu'ils chargent, où ils écrivent |
| [Architecture](docs/architecture.md) | noyau, satellites, instance |
| [Agents](docs/agents.md) | la liste complète, générée depuis les agents |
| [Recettes](docs/recettes.md) | quelle session, quels agents, pour quoi |
| [Brain-engine](docs/moteur.md) | le moteur, ses commandes, ses accès |

Les décisions qui expliquent la forme du brain : [ARCHITECTURE.md](ARCHITECTURE.md).
La loi des zones : [KERNEL.md](KERNEL.md).

---

## Communauté

[Discord — Le Brain](https://discord.gg/BsRqKhNgq6) — support, showcase, discussions.

## Licence

[BSL 1.1](LICENSE.md) — Business Source License 1.1

Usage libre pour un usage personnel et interne.
Usage commercial de hosting/revente soumis à licence.
Conversion automatique en Apache 2.0 le 2028-04-01.
