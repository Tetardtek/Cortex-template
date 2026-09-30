# learning/ — tes pistes d'apprentissage

> Ce dossier est un **satellite** : le `.gitignore` du noyau ignore son
> contenu, ce README mis à part. Ce que tu y écris ne se mélange jamais à
> l'historique du noyau.

## Ce qu'il garde

Ce qu'écrit une session `learning` (`brain boot learning/<piste>`) : une piste
par sujet, son index et ses modules.

```
learning/
  <piste>.md            la piste : où tu en es, ce qui vient ensuite
  <piste>/m01-….md      ses modules
```

## Le versionner

Tant que tu n'en fais pas un dépôt, il n'a **pas de sauvegarde** : git ne le
voit pas. Pour le garder, ou le partager entre tes machines :

```bash
cd <BRAIN_ROOT>/learning
git init
git add .
git commit -m "learning : premier état"
git remote add origin <URL_DE_TON_DEPOT>
git push -u origin main
```

Les commits de ce dépôt sont les tiens : le noyau ne les voit pas, et ne leur
impose aucun type. Plusieurs machines : déclare-le dans `satellites.yml`
(`docs/satellites.md`).
