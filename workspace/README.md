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

L'**outillage** du backlog, lui, ne part pas : l'index généré, le kanban, la
clôture sur preuve et les contrôles de `brain doctor` vivent dans un dépôt à
part, encore en construction et non publié. Les agents `kanban-scribe` et
`todo-scribe` le supposent. Sans lui, un backlog se tient à la main : des
fiches en Markdown, que tu ranges toi-même.
