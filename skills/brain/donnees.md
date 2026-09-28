<!-- Généré depuis skills/brain/src/donnees.md par scripts/docs-generer.py — ne pas éditer ici. -->
# La base — Dolt

Dolt (base SQL versionnée) dans `brain-dolt/`, servie sur `127.0.0.1:3307`
(`BRAIN_DOLT_PORT`), base `brain-dolt`. Le backend se déclare dans
`brain-engine/.env.local` : `BRAIN_DB_BACKEND=dolt` (défaut) ou `sqlite`.

## La règle

**Tout passe par `brain-engine/db.py`.** Il lit le backend, traduit ce qu'il
faut, et c'est la base qu'il ouvre que tout le reste lit. Une connexion ouverte
à la main écrit dans une base que personne ne lit.

Dans un script bash, le python à utiliser est celui du venv :
`source scripts/lib/python.sh`.

## Ce qu'elle contient

**Tables (29)** — `agent_loads`, `agent_memory`, `agents`, `backlog_visions`, `chantiers`, `circuit_breaker`, `claims`, `claims_archive`, `cosmos_edges`, `decision_chantiers`, `decisions`, `embedding_hits`, `embeddings`, `handoffs`, `handoffs_archive`, `intention_edges`, `intention_sessions`, `intention_tags`, `intentions`, `learning_modules`, `learning_tracks`, `locks`, `projects`, `sessions`, `sessions_archive`, `signals`, `signals_archive`, `todo_items`, `todo_sections`

**Vues (6)** — `v_open_claims`, `v_stale_claims`, `v_active_locks`, `v_cold_start_kpi`, `v_graduation_candidates`, `v_metabolism_`

*Depuis `brain-engine/schema-dolt.sql` (généré — ne pas l'éditer à la main :
modifier la base, puis régénérer) et `brain-engine/views-dolt.sql`.*

## SQLite

Sans versionnement, le CORE refuse les purges : l'indexation s'arrête le jour
où un fichier sort du corpus. SQLite se **déclare**, il ne se suppose jamais.
