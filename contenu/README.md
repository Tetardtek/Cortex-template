# contenu/ — ton satellite de production

> Ce dossier est **à toi**. Le noyau ne suit que ce README : tout ce que tu y
> écris est ignoré par son git.

## Ce qu'il garde

Ce que tu produis pour l'extérieur — posts, articles, scripts de vidéo — du
brouillon à la version publiée :

```
atelier/   ce qui se prépare
publie/    ce qui est sorti
archive/   les versions remplacées
```

## Ce que le moteur en fait

Le serveur MCP y lit et y écrit :

- `brain_content` dresse le pipeline (`atelier/` et `publie/`), d'après le
  frontmatter de chaque fichier — `status`, plateforme, dates ;
- `brain_content_promote` fait avancer un contenu : `draft → ready` dans
  `atelier/`, puis `ready → scheduled` le déplace dans `publie/`.

`archive/` est à toi : le MCP n'y touche pas. Le moteur n'indexe pas `contenu/`.

Sans ce dossier, le pipeline est simplement vide — rien ne casse.

## Le versionner à part — si tu veux

Comme tout satellite : fais-en ton dépôt, et déclare-le dans `satellites.yml`
pour l'avoir sur plusieurs machines — voir `docs/satellites.md`.
