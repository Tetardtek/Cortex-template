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

<!-- genere:tables -->

*Depuis `brain-engine/schema-dolt.sql` (généré — ne pas l'éditer à la main :
modifier la base, puis régénérer) et `brain-engine/views-dolt.sql`.*

## SQLite

Sans versionnement, le CORE refuse les purges : l'indexation s'arrête le jour
où un fichier sort du corpus. SQLite se **déclare**, il ne se suppose jamais.
