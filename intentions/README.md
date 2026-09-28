# intentions/

> Objectifs mesurables — la couche "quoi" du systeme a 4 couches.

## Contenu attendu

Un fichier YAML par intention : `intentions/mon-intention.yml`

Chaque intention contient :
- Objectif mesurable
- Status (active / done / stasis)
- Dependances (depends_on, blocks)
- Sessions liees

## Pourquoi

Les intentions sont le lien entre la vision (pourquoi) et les todos (comment).
Elles persistent entre les sessions — une intention non terminee reste ouverte.
Le scribe met a jour le status et les sessions liees a chaque close de session.

> Voir `profil/collaboration.md` pour la convention des 4 couches.
