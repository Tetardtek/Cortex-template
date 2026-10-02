# vie/ — ton satellite privé

> Ce dossier est **à toi, et à toi seul**. Le noyau ne suit que ce README : tout
> ce que tu y écris est ignoré par son git.

## Ce qu'il garde

Ce qui relève de ta vie plutôt que de ton travail : démarches, papiers, emploi,
santé, notes personnelles.

## Ce que le moteur en fait — rien

`vie/` est une **zone privée** (`PRIVATE_PATHS`, `brain-engine/embed.py`) :

- le moteur ne l'**indexe jamais** — aucune recherche, aucun `brain_boot` n'en
  remonte une ligne ;
- `GET /brain/vie/…` ne répond qu'au propriétaire du brain : un jeton d'un autre
  rôle, même `mcp`, est refusé.

Une session y lit un fichier quand tu le lui demandes, comme n'importe quel
fichier sur ton disque — jamais d'elle-même par la recherche.

## Le versionner à part — si tu veux

Comme tout satellite : fais-en **ton** dépôt, de préférence **privé**, et
déclare-le dans `satellites.yml` pour l'avoir sur plusieurs machines — voir
`docs/satellites.md`.
