# workspace/

> L'espace de travail des sessions — ce qui se fait, pas ce qui se retient.

## Structure

```
workspace/
  backlog/<projet>/   la vision d'un projet et ses fiches — une tâche par fichier
  scratch/            brouillons et essais d'une session
  live-states.md      l'état des sessions actives
```

## Le backlog — ce que ce gabarit livre, et ce qu'il ne livre pas

La **convention** part avec le gabarit : une vision par projet
(`workspace/backlog/<projet>/vision.md`), une fiche par tâche, avec ses
critères de fin — voir `profil/specs/collaboration.md`, « 4 couches ».

L'**index** et la **clôture sur preuve** partent avec le doctor
(`brain-engine/doctor/`) : l'index de chaque projet se régénère depuis ses
fiches, et une fiche close porte son rapport. La **forge** (issues, PR) reste
à ton outil (`gh`, `tea`, l'interface web). Les commandes, et la boucle
entière — une fiche, un worker, un juge : `docs/methode.md`.
