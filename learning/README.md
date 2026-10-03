# learning/ — tes pistes d'apprentissage

> Ce dossier est un **satellite** : le `.gitignore` du noyau ignore son
> contenu, ce README mis à part. Ce que tu y écris ne se mélange jamais à
> l'historique du noyau.

## Ce qu'il garde

Ce qu'écrit une session `learning` (`brain boot learning/<piste>`) : une piste
par sujet, dans son dossier.

```
learning/
  README.md               cet index — la table des pistes y est générée
  <piste>/README.md       la fiche de la piste : son index et ses liens
  <piste>/m01-….md        ses modules — ses unités de progression
```

La **fiche** d'une piste dit ce qu'elle porte et ce qu'elle nourrit :

```yaml
---
name: <piste>
type: learning-track
status: exploring         # seed · exploring · active · pause · close
domain: [<sujet>, <sujet>]
feeds: [<projet>]         # ce qu'elle nourrit : un projet, une autre piste, ou vie/
liens: [https://…]        # optionnel — une URL, ou un chemin du brain
---
```

`feeds:` ne nomme que ce qui **existe** : un projet qui n'a pas encore sa fiche
y entre le jour où elle naît. Un projet sait quelles pistes le nourrissent sans
le déclarer : la vue se déduit (`zone_learning.py --projet <slug>`).

| Statut | Signifie |
|--------|----------|
| `seed` | posée, pas encore commencée |
| `exploring` | on découvre |
| `active` | on progresse avec méthode — des modules |
| `pause` | arrêtée, on y reviendra |
| `close` | finie, gardée |

## Les pistes

<!-- genere:tracks -->
| Track | Statut | Domaine | Nourrit |
|-------|--------|---------|---------|
<!-- /genere:tracks -->

La table se **génère** depuis les fiches :
`python3 brain-engine/doctor/zone_learning.py --brain . --ecrire`. `brain doctor`
la juge (« la zone learning »), avec les fiches, leurs statuts et leurs `feeds:`.

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
