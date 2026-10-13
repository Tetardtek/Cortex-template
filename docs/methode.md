---
# Généré depuis docs/src/methode.md par scripts/docs-generer.py — ne pas éditer ici.
label: La méthode
groupe: Utiliser
ordre: 7.5
---

# La méthode — une fiche, un worker, un juge

> Comment le travail avance : une tâche écrite, un agent qui la fait dans son
> coin, un autre qui vérifie, et toi qui décides. Ce que le gabarit livre pour
> la tenir, et ce qui reste à ton outil.

---

## La boucle

```
la fiche ──▶ composer ──▶ ton go ──▶ le worker ──▶ le juge ──▶ ta relecture ──▶ la fusion
 (backlog)  (orchestrator)          (son worktree)  (preuves     (la PR)
                                                     rejouées)
```

1. **La fiche.** Une tâche = un fichier, dans `workspace/backlog/<projet>/`,
   nommé `<XX>-<n>.md`. Le préfixe `<XX>` se déclare dans la fiche du projet,
   `projets/<projet>.md` (`prefixe:`). `todo-scribe` écrit les fiches ; une
   fiche porte ses **critères de fin** : ce qui sera mesuré, et ce qui
   l'empêchera de revenir.

   ```markdown
   #### Critères de fin

   - [ ] **mesuré** : <ce qui sera constaté, et par quoi> · **tenu par** : <un test, un contrôle — ou « rien »>
   ```

2. **Composer.** Avant qu'un worker parte, l'`orchestrator` lit la fiche et
   répond « prête » ou « pas prête ». Prête, c'est : ce qui est à faire, le
   contexte vérifié, les critères de fin, et l'agent qui fera le travail — un
   agent qui déclare ce qu'il a le droit d'écrire (`zone_write`). Sans cet
   agent, la fiche ne part pas.

3. **Ton go.** Rien ne démarre sans toi.

4. **Le worker.** Un sous-agent, avec un contexte neuf : il ne sait que ce que
   le brief lui dit. Il travaille dans **son propre worktree**, sur une branche
   tirée de `dev/autonome` — jamais dans ton dossier principal, jamais sur le
   tronc. Pour le programme du brain lui-même (scripts, moteur, mise à jour),
   c'est `forgeron`. Pour tes projets, ce sont les agents du domaine : `debug`,
   `refacto`, `testing`… Il livre une PR vers `dev/autonome`, avec, pour chaque
   critère, la commande qui le prouve. Il ne se juge pas.

5. **Le juge.** L'`orchestrator`, en mode juger, reprend chaque critère un par
   un. Il **rejoue** les preuves lui-même : le rapport du worker dit ce qu'il a
   tenté, pas ce qui est vrai. Deux règles de plus :
   - **le témoin négatif d'abord** : un test qui passe sur l'ancien code comme
     sur le nouveau ne prouve rien — il doit rougir avant le changement ;
   - **le mutant** : pour chaque garantie que la PR touche, on casse le code
     qu'elle protège, on relance, et la garantie doit tomber. Une garantie qui
     reste verte sous mutant ne mesure plus rien.
     `scripts/saboter.py` casse, joue la commande, rend toujours le fichier, et
     refuse de conclure si le motif est introuvable ou le remplacement inerte —
     les options avant le fichier :
     `python3 scripts/saboter.py --motif "<code>" --par "<cassé>" <fichier> -- <commande>`.

   Un seul critère sans preuve, et la PR n'est pas fusionnée : la fiche reste
   ouverte et dit ce qui manque.

6. **Ta relecture, puis la fusion.** Le verdict favorable fait entrer la PR
   dans `dev/autonome`. Toi seul portes `dev/autonome` au tronc. Après la
   fusion, `kanban-scribe` écrit la clôture de la fiche, depuis les critères
   remplis.

---

## Les paliers

Chaque projet déclare jusqu'où l'autonomie va, dans `projets/<projet>.md` :
`palier: a`, `b` ou `c` — **a** par défaut.

| Palier | Ce que fait le brain | Ce que tu fais |
|---|---|---|
| **a — tenir** | l'index des fiches et les clôtures, à chaque changement | rien |
| **b — suivre** | le travail fait sans toi s'empile sur `dev/autonome`, chaque PR jugée | tu lis ses PR avec ton outil, tu portes `dev/autonome` au tronc |
| **c — lancer** | compose, lance les workers, juge, fusionne dans `dev/autonome` | tu donnes le go, tu relis `dev/autonome` |

`dev/autonome` est la branche où le travail fait sans toi s'empile. Ton tronc
reste à toi : protège-le sur ta forge, pour que personne d'autre n'y pousse.
Seul le palier **c** autorise un lancement — et même là, ton go vient avant
le worker.

---

## L'index et la clôture — livrés avec le doctor

Deux outils tiennent le backlog. Ils sont dans `brain-engine/doctor/`, et se
lancent depuis la racine de ton brain.

**L'index** — `workspace/backlog/<projet>/backlog.md`, **généré** depuis les
fiches. Ne l'édite pas : un index écrit à la main se périme.

```bash
python3 brain-engine/doctor/index_backlog.py --brain . --projet <projet> --ecrire  # le régénère
python3 brain-engine/doctor/index_backlog.py --brain . --projet <projet> --check   # 0 juste · 1 à régénérer
python3 brain-engine/doctor/index_backlog.py --brain . --tous --check              # chaque projet qui déclare un préfixe
```

Tant qu'un projet n'a aucune fiche `<XX>-<n>.md`, il n'a pas d'index à tenir :
l'outil s'abstient (`SKIP`), et le dit.

**La clôture sur preuve** — une fiche close (un ✅ dans son titre) porte, sous
son titre, son rapport :

```markdown
### [<XX>-<n>] Ce qui est livré — ✅ livré le <jj/mm>

> **Clôture** — mesuré : <ce qui a changé, chiffré> · tenu par : <ce qui l'empêche de revenir, ou « rien »>
```

```bash
python3 brain-engine/doctor/cloture_backlog.py --brain . --projet <projet>   # 0 · 1 une clôture sans rapport
python3 brain-engine/doctor/cloture_backlog.py --brain . --tous
```

« tenu par : rien » est une réponse honnête : une fiche soldée sans filet se
rouvrira sans prévenir. Des fiches closes avant que tu adoptes la règle peuvent
être exemptées, une par ligne avec sa raison (`<XX>-<n> <raison>`), dans
`instance/doctor/cloture-sans-rapport`. Une exemption qui ne sert plus rougit
aussi : elle se retire.

**Quand les lancer** : dans la branche qui porte la fiche, **avant** la PR —
l'index régénéré et la clôture vérifiée entrent dans la PR.

---

## La forge — GitHub par `gh`, ou ta forge déclarée

Les PR et leur fusion se font avec ton outil (`gh`, `tea`, l'interface web) : le
worker ouvre sa PR vers `dev/autonome`, tu la relis et tu fusionnes.

Le reste de la boucle est livré avec le doctor (`brain-engine/doctor/`) :

```bash
python3 brain-engine/doctor/kanban.py tenir --brain . --projet <projet>   # index, clôtures, puis issues
python3 brain-engine/doctor/kanban.py resume --brain .                    # ce que dev/autonome porte
python3 brain-engine/doctor/kanban.py repartir --brain . --projet <projet>  # dev/autonome repart du tronc
```

La forge d'un projet se lit dans l'adresse de son dépôt (`repo:` de sa fiche,
`<hôte>/<owner>/<nom>`) :

- **GitHub** (`github.com/…`) passe par `gh` et son authentification
  (`gh auth login`) : le brain ne lit aucun jeton.
- **Une forge Gitea à toi** se déclare dans `satellites.yml` — sans elle, rien
  ne t'est demandé :

  ```yaml
  forges:
    git.exemple.org:
      type: gitea
      url: https://git.exemple.org
      jeton: GITEA_TOKEN                     # le NOM de la clé dans MYSECRETS
      jeton_autonome: GITEA_TOKEN_AUTONOME   # facultatif : le compte des agents
  ```

**Le mode autonome** (`BRAIN_FORGE_AUTONOME=1`) : sur GitHub, il ouvre les PR et
refuse toute fusion — c'est toi qui fusionnes. Sur une Gitea déclarée, il prend
le jeton de `jeton_autonome:`, et sans lui il refuse : il ne se rabat jamais sur
le tien.

Le résumé de `dev/autonome` est aussi ce que le moteur sert sur `/workflows`
(et `brain_workflows`) : rien à déclarer, il lance ce kanban.

---

## Les gardes qui tiennent les workers

Un worker travaille sans que tu voies chaque geste. Trois gardes livrés posent
la règle au moment où il agit, ou au moment où on le juge.

**Le garde de lecture** (`scripts/garde-lecture.py`) — un hook de Claude Code,
avant chaque outil. Un sous-agent ne lit pas ce qui est personnel : les chemins
`zone_personal` et `zone_aucune` de `NIVEAUX.yml`. Il refuse un `Read` d'un
de ces fichiers et une recherche (`Grep`, `Glob`) qui y mène. Pour une commande
du shell, il ne juge pas le texte mais **où mènent ses chemins** : il suit les
`cd`, résout les liens, développe les globs et les accolades comme le shell, et
juge un `$(…)` comme une commande. Un chemin qui tombe dans le personnel est
refusé, qu'il le nomme ou non ; un chemin qui mène ailleurs passe. Un motif de
`grep`, un message de commit, un heredoc écrit dans un fichier hors du
personnel passent aussi. Ce qu'il ne peut pas trancher — une variable, le code
de `python -c` ou de `bash -c` qui nomme le personnel, une commande qu'il ne
sait pas découper — est refusé, et il le dit. Ta session, elle, n'est pas
concernée : c'est toi, présent.
`brain init` et `brain maj` le posent dans `.claude/settings.json` ; `brain doctor`
dit s'il manque.

```bash
python3 scripts/garde-lecture.py etat   # posé ? 0 oui · 1 non
```

**Le garde des commandes** (`scripts/garde-commandes.py`) — un hook avant
chaque commande du shell. Il refuse cinq gestes qui ont déjà coûté cher : `rm`
avec un motif dans `workspace/scratch/` (les brouillons d'autres sessions),
`git add -A` dans le brain (l'index de git est partagé entre les sessions), le
fichier des secrets lu par `source`, une recherche qui ne suit pas les liens
dans un dossier fait de liens (`agents/` : « rien trouvé », sans le dire), et
`sed -i` sur un lien (il le remplace par un fichier).

```bash
python3 scripts/garde-commandes.py juger "<commande>"   # ce qu'il en dirait
```

**La zone du diff** (`scripts/zone-du-diff.py`) — rejouée par le juge sur la
PR du worker. Chaque chemin touché, contre ce que l'agent du worker a le droit
d'écrire. Un seul chemin hors de sa zone, et le verdict est défavorable — même
si tous les critères sont remplis.

```bash
python3 scripts/zone-du-diff.py --agent <agent> --depot <dépôt> --git <le clone de la PR> --base origin/dev/autonome
# 0 dans la zone · 1 un chemin hors zone · 2 rien à juger
```

Aucun n'est un pare-feu. Le garde de lecture ne voit pas un script qui lit à
la place de la commande, le code de `python -c` ou de `bash -c` qui ne nomme
rien du personnel, ni ce que lancent `find -exec` ou `xargs` ; le garde des
commandes ne voit que ses cinq gestes. Ce sont des règles présentes au moment
du geste — le juge et ta relecture restent.
