---
# Généré depuis docs/src/satellites.md par scripts/docs-generer.py — ne pas éditer ici.
label: Satellites
groupe: Comprendre
ordre: 5
---

# Les satellites — ta mémoire, à part du noyau

> Le noyau est le même dans chaque fork. Les satellites sont à toi : ce que tu
> fais, ce que tu apprends, ce que tu retiens.

---

## Les dossiers à part

| Dossier | Ce qu'il garde |
|---|---|
| `profil/` | ta façon de travailler, tes objectifs — et les specs que le noyau partage (`profil/specs/`). Il se versionne à part, mais sa partie invariante est du **noyau** (`KERNEL.md`) : elle ne change qu'avec ta confirmation |
| `todo/` | tes intentions et ce qui reste à faire |
| `toolkit/` | les patterns que tu as validés en production, réutilisables |
| `progression/` | ton parcours, tes compétences, ton métabolisme de sessions |
| `reviews/` | les revues d'agents |
| `learning/` | tes pistes d'apprentissage — ce qu'écrit une session `learning` |

Le gabarit les livre comme des **dossiers**, chacun avec un `README.md`. Le
`.gitignore` du noyau ignore leur contenu, README mis à part : ce que tu y
écris ne se mélange jamais à l'historique du noyau.

---

## Les versionner à part

Quand tu veux garder l'historique d'un satellite, ou le partager entre tes
machines, fais-en un dépôt :

```bash
cd ~/Dev/Brain/todo
git init
git add .
git commit -m "todo : premier état"
git remote add origin <URL_DE_TON_DEPOT>
git push -u origin main
```

Même geste pour les autres.

---

## Plusieurs machines — `satellites.yml`

Une instance qui tourne sur plusieurs machines déclare ses satellites dans
`satellites.yml`, à la racine : chaque dépôt, son chemin, les machines qui
l'ont. `scripts/brain-satellites.py` s'en sert :

| Commande | Effet |
|---|---|
| `python3 scripts/brain-satellites.py` | l'état de chaque dépôt, en lecture seule |
| `… --check` | idem, avec un code de sortie : 0 tout est à jour |
| `… --pull` | met à jour ce qui est en retard — en avance rapide seulement |
| `… --cloner` | clone ce qui est déclaré pour cette machine et absent |

Sans `satellites.yml`, il ne fait rien : les satellites restent des dossiers.
Avec lui, l'installation (`scripts/brain-setup.sh`) clone ceux de la machine.

---

## La règle

Le noyau ne dépend jamais d'un satellite. Un satellite absent ou vide ne casse
rien : les scribes qui y écrivent n'ont simplement nulle part où écrire.
