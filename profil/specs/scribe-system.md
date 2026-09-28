---
name: scribe-system
brain:
  version:   1
  type:      reference
  scope:     kernel
  owner:     human
  writer:    human
  lifecycle: stable
  read:      header
  triggers:  [on-demand]
  export:    true
---

# Scribe System — Cartographie officielle du Scribe Pattern

> **Type :** Référence
> Décision architecturale — session 2026-03-13
> Complémentaire de `memory-integrity.md` (règles d'écriture) et `context-hygiene.md` (chargement)

---

## Le Scribe Pattern

**Règle dure — un agent métier n'écrit jamais directement dans le brain.**

```
Agent métier (vps, ci-cd, debug...)
  → observe, produit, détecte
  → signale au scribe compétent
  → le scribe écrit, commite, maintient

Jamais : agent métier → write directement
Toujours : agent métier → signal → scribe compétent → write
```

Pourquoi : un agent qui écrit directement = scope indéfini = dérive mémoire garantie.
Le scribe est le seul responsable de la cohérence de son repo.

---

## Carte des scribes

| Scribe | Écrit où | Repo | Couche | Exportable | Cycle de vie |
|--------|----------|------|--------|------------|-------------|
| `scribe` | `focus.md`, `projets/`, `infrastructure/`, `agents/AGENTS.md`, `profil/objectifs.md` | `brain/` | Universel | ✅ | Permanent |
| `wiki-scribe` | `wiki/` (reference technique) + `docs/` (guides humains) | `brain/` | Universel | ✅ | Permanent |
| `todo-scribe` | `todo/` | `brain-todo/` | Universel | ✅ structure | Stable quand todo en régime |
| `toolkit-scribe` | `toolkit/` | `brain-toolkit/` | Universel | ✅ | Actif tant que nouveaux patterns |
| `orchestrator-scribe` | signaux en base (`bsi-signal.sh`) + `handoffs/feedback-tech-lead-*.md` | `brain/` | Universel | ✅ protocole | Permanent — multi-instance actif |
| `config-scribe` | `PATHS.md`, `infrastructure/` d'une instance | instance locale | Universel | ✅ structure | Invoqué sur `brain-compose new` |
| `git-analyst` | Commits git (narration sémantique) | Tous repos | Universel | ✅ | Ponctuel — invoqué sur demande |
| `coach-scribe` | `journal/`, `skills/`, `milestones/` | `brain-progression/` | Personnel | ❌ | Suit le coach — retraité ensemble |
| `capital-scribe` | `profil/capital.md` | `brain-profil/` | Personnel | ❌ strippé | Suit objectifs — veille quand CV stabilisé |

> `helloWorld` et `coach` ne sont **pas** des scribes — ils observent et rapportent, jamais n'écrivent.
> `orchestrator-scribe` n'émet QUE des signaux (`bsi-signal.sh`) et `handoffs/feedback-tech-lead-*` — jamais de claim : chaque session tient le sien (`bsi-claim.sh`).
> `integrator` est une **exception déclarée** : commit direct en zone WORK (repos projets) uniquement. Pour brain/ → signal à `orchestrator-scribe`.
> `tech-lead` n'écrit rien — cosigne les messages de commit via convention `tech-lead: overflow granted`.

---

## Ordre canonique de fin de session

Quand plusieurs scribes écrivent dans la même session :

```
1. todo-scribe         → commit brain-todo/       "todo(<domaine>): <intention>"
2. toolkit-scribe      → commit brain-toolkit/    "feat(toolkit): <pattern>"        si signal reçu
3. coach-scribe        → commit brain-progression/ "feat(progression): <bilan>"     si session coach
4. capital-scribe      → commit brain-profil/     "feat(capital): <milestone>"      si signal reçu
5. scribe              → commit brain/            "feat(brain): <bilan session>"    toujours en dernier sur brain/
6. orchestrator-scribe → commit brain/            "feat(signals): <signal posé>"    si inter-sessions actives
7. git-analyst         → valide cohérence sémantique des commits                    optionnel
```

**Règle :** `scribe` est toujours le dernier à commiter sur `brain/` — il a la vue complète de ce que les autres ont écrit.

**Un commit = un scribe = un repo.** Voir `memory-integrity.md`.

---

## Comment un agent métier signale

Format standard de signal en fin d'action :

```
→ Signal scribe : <ce qui a changé> dans <fichier cible>
  Ex: "Signal scribe : nouveau container mon-service ajouté — mettre à jour brain/infrastructure/vps.md"

→ Signal todo-scribe : <intention de session future>
  Ex: "Signal todo-scribe : ⬜ configurer monitoring pour mon-service"

→ Signal toolkit-scribe : <pattern validé en prod>
  Ex: "Signal toolkit-scribe : pattern vhost reverse proxy validé — candidat toolkit/apache/"
```

Le scribe reçoit le signal en fin de session et écrit. Il ne demande pas — il déduit du signal.

---

## Chargement conditionnel

Ce fichier est chargé sur trigger — jamais au démarrage.

| Agent | Trigger | Pourquoi |
|-------|---------|----------|
| `scribe` | Au démarrage | Connaître ses pairs scribes et l'ordre de commit |
| `recruiter` | Quand il forge un agent qui écrit | Vérifier la déclaration `## Écrit où` |
| `agent-review` | Review d'un scribe | Grille : scope déclaré ? ordre respecté ? |
| Tout agent métier | Avant de signaler | Savoir à quel scribe déléguer |

---

## Routing par audience — wiki/ vs docs/ (BRAIN-044)

Tout contenu documentaire produit par un scribe suit une regle de routing automatique basee sur l'audience cible.

```
Question : "Ce contenu est-il lisible sans contexte brain ?"

  OUI → docs/    (guide humain — onboarding, forks, explication sans jargon)
  NON → wiki/    (reference technique — agents, matrices, specs, BHP, lifecycle)
```

| Critere | wiki/ | docs/ |
|---------|-------|-------|
| **Audience** | Agents IA, brain interne | Humains, forks, onboarding |
| **Jargon BHP** | Autorise (L0/L1/L2, tier, claim, scribe) | Interdit — traduire en langage courant |
| **References croisees** | Vers agents/, profil/, contexts/ | Vers d'autres docs/ ou wiki/ en lien |
| **Format** | Machine-friendly, tables denses, specs | Lisible, FAQ, exemples concrets |
| **Exportable template** | Oui | Oui |

**Responsable** : `wiki-scribe` gere les deux territoires (wiki/ + docs/).
L'agent `doc` reste dedie aux repos projet (README, Swagger, API docs).

**Regle de signal :**
```
Tout scribe qui produit du contenu documentaire :
  → Signal wiki-scribe : "<contenu> — audience: technique|humain"
  → wiki-scribe route vers wiki/ ou docs/ selon l'audience
  → Si le contenu couvre les deux audiences : ecrire dans wiki/ (reference)
    ET signaler qu'un guide docs/ correspondant est necessaire
```

---

## Séparation universel / personnel — export

```
Template public (claude-brain-template) :
  ✅ scribe, todo-scribe, toolkit-scribe, git-analyst

Couche personnelle (strippée à l'export) :
  ❌ coach-scribe, capital-scribe
  ❌ progression/, profil/capital.md
```

Quelqu'un qui fork récupère le moteur d'écriture. Pas le cerveau, pas la progression, pas le CV.

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-13 | Création — émergé de la session agent-review + architecture multi-repos + Scribe Pattern |
| 2026-03-14 | Ajout orchestrator-scribe (## Signals) + config-scribe — 8 scribes, repos satellites mis à jour, ordre de commit v2 <!-- bsi-v1 --> |
