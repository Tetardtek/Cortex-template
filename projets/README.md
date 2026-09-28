# projets/

> Snapshots live de vos projets actifs — etat courant, intentions, blockers.

## Contenu attendu

Un fichier par projet : `projets/mon-projet.md`

Chaque fichier contient :
- Etat courant du projet
- Table des intentions liees
- Blockers actifs
- BYOKS (secrets requis)

## Pourquoi

Les agents chargent `projets/<projet>.md` en L2 quand vous faites `brain boot mode work/<projet>`.
C'est la couche "etat" du systeme a 4 couches (vision / intention / todo / projet).

> Voir `profil/collaboration.md` pour la convention des 4 couches.
