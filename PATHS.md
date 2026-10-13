# PATHS.md — Résolution des chemins machine

> **Fichier de reference** — les agents utilisent les noms semantiques ci-dessous pour resoudre les chemins.
> Les marqueurs de chemin (la racine du brain, le home, le dossier des projets) sont remplis par `brain init`.
> Ce fichier reste avec des placeholders dans le template — c'est normal.
> Ne jamais hardcoder un chemin absolu dans les agents — toujours utiliser les noms semantiques.

---

## Chemins actifs

| Nom sémantique | Chemin réel | Remote | Gitignored dans brain |
|----------------|-------------|--------|----------------------|
| `brain/` | `<BRAIN_ROOT>` | ton fork, ou aucun (brain servi par le paquet) | — (repo racine) |
| `toolkit/` | `<BRAIN_ROOT>/toolkit/` | ton dépôt, si tu veux (`docs/satellites.md`) | ✅ |
| `progression/` | `<BRAIN_ROOT>/progression/` | ton dépôt, si tu veux (`docs/satellites.md`) | ✅ |
| `reviews/` | `<BRAIN_ROOT>/reviews/` | ton dépôt, si tu veux (`docs/satellites.md`) | ✅ |
| `profil/` | `<BRAIN_ROOT>/profil/` | ton dépôt, si tu veux (`docs/satellites.md`) | ✅ |
| `todo/` | `<BRAIN_ROOT>/todo/` | ton dépôt, si tu veux (`docs/satellites.md`) | ✅ |
| `learning/` | `<BRAIN_ROOT>/learning/` | ton dépôt, quand tu veux (`docs/satellites.md`) | ✅ |
| `projects/` | `<PROJECTS_ROOT>` | GitHub / Gitea | — |
| `home/` | `<HOME>` | — | — |

## Architecture satellite repos

Les repos gitignores dans `brain/` sont des **satellites autonomes** — chacun a son propre remote.
Chaque dossier satellite contient un README guide dans le template. Pour qu'un satellite ait son dépôt,
et pour les recloner sur une autre machine : déclare-les dans `satellites.yml` — `docs/satellites.md`.

---

## Règle anti-hallucination — obligatoire pour tous les agents

> Si un chemin n'est pas dans cette table → **ne pas deviner**.
> Écrire : `"Information manquante — vérifier PATHS.md"`

---

## Procédure — nouvelle machine

Le brain s'installe par `brain init`, qui remplit ce fichier. Deux façons :

- **le paquet** : `pipx install brain-cortex` (l'index et la version que donne celui qui le publie), puis
  `brain init <nom> <dossier>` — la procédure guidée : `docs/installer-avec-claude.md` ;
- **un fork cloné** : `git clone <URL_DE_TON_FORK> <BRAIN_ROOT>`, puis `bash scripts/brain init <nom>` —
  `docs/demarrer.md`.

Puis `brain doctor`, et `claude` dans le dossier du brain.

---

## Historique machines

| Machine | OS | `brain/` | Actif |
|---------|----|----------|-------|
| *(à remplir)* | | | |
