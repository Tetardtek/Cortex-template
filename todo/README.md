# todo/ — ton satellite

> Ce dossier est **à toi**. Le noyau ne suit que ce README : tout ce que tu y
> écris est ignoré par son git, et ne se mélange jamais à son historique.

## Ce qu'il garde

Tes intentions et ce qui reste à faire.

## Le versionner à part — si tu veux

Rien ne l'exige. Pour garder son historique, ou le partager entre tes machines,
fais-en **ton** dépôt :

```bash
cd <BRAIN_ROOT>/todo
git init
git add .
git commit -m "todo : premier état"
git remote add origin <URL_DE_TON_DEPOT>
git push -u origin main
```

Sur plusieurs machines, déclare-le dans `satellites.yml` : voir
`docs/satellites.md`.
