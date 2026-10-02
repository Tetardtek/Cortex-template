---
# Généré depuis docs/src/donnees.md par scripts/docs-generer.py — ne pas éditer ici.
label: Données
groupe: Comprendre
ordre: 6
---

# Les données — Dolt

> Tout ce qui est structuré vit dans Dolt. Tout ce qui se raconte reste en
> Markdown.

---

## Pourquoi Dolt

Dolt est une base SQL **versionnée comme git** : chaque changement se commite,
se compare, se retrouve. Ce que le brain structure — sessions, intentions,
todos, décisions, index de recherche — se requête en une ligne de SQL au lieu
d'être recoupé à la main entre des fichiers.

## Où elle vit

- la base : `brain-dolt/`, à la racine du brain — créée par `scripts/dolt-setup.sh`
- le serveur : `127.0.0.1:3307`, jamais exposé au réseau — le service
  utilisateur `dolt-server.service`, ou `bash scripts/brain-engine.sh start`
- le nom de la base : `brain-dolt`
- le choix du moteur : `BRAIN_DB_BACKEND` dans `brain-engine/.env.local`

Une base neuve est **vide** : elle a son schéma, pas de données. Elle se
remplit en travaillant.

---

## Ce qu'elle contient

**Tables (19)** — `agents`, `chantiers`, `claims`, `claims_archive`, `decisions`, `embedding_hits`, `embeddings`, `handoffs`, `handoffs_archive`, `intention_edges`, `intention_sessions`, `intention_tags`, `intentions`, `locks`, `projects`, `sessions`, `sessions_archive`, `signals`, `signals_archive`

**Vues (5)** — `v_open_claims`, `v_stale_claims`, `v_active_locks`, `v_cold_start_kpi`, `v_metabolism_`

*Liste générée depuis `brain-engine/schema-dolt.sql` et
`brain-engine/views-dolt.sql`.*

Chaque table appartient à un **module** (les sessions, le catalogue, la
recherche, les intentions…) : `brain-engine/modules.yml` les range, et la suite
de tests refuse une table que personne ne possède.

Les tables qui comptent au quotidien :

| Table | Ce qu'elle garde |
|---|---|
| `claims` | une ligne par session : type, périmètre, durée, résultat |
| `intentions` | les objectifs qui durent plusieurs sessions |
| `projects` | les projets et leur statut |
| `decisions` | les décisions d'architecture |
| `embeddings` | l'index de la recherche sémantique |

---

## Ce qui reste en fichiers

| Contenu | Pourquoi |
|---|---|
| les agents | des instructions longues, faites pour être lues |
| les projets | des récits, avec leurs sections chaudes et froides |
| le noyau (`KERNEL.md`, `PATHS.md`…) | les fondations se lisent sans serveur |
| les secrets | jamais dans une base |

---

## Requêter

Avec n'importe quel client MySQL, sur `127.0.0.1:3307`, base `brain-dolt` :

```sql
-- les projets par statut
SELECT status, COUNT(*) FROM projects GROUP BY status;

-- les intentions au front, dans l'ordre
SELECT id, title FROM intentions WHERE front = 1 ORDER BY front_order;

-- les sessions ouvertes, par type
SELECT type, COUNT(*) FROM claims WHERE status = 'open' GROUP BY type;

-- les dernières sessions
SELECT sess_id, type, result FROM claims ORDER BY opened_at DESC LIMIT 10;
```

---

## SQLite, le repli

`BRAIN_DB_BACKEND=sqlite` range tout dans un fichier, sans serveur. Le code
ne voit pas la différence — mais SQLite ne versionne rien : le moteur y refuse
les purges, et l'indexation s'arrête le jour où un fichier sort du corpus. Le
défaut est Dolt ; SQLite se déclare, en connaissance de cause.
