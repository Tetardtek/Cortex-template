---
# Généré depuis docs/src/agents.md par scripts/docs-generer.py — ne pas éditer ici.
label: Agents
groupe: Comprendre
ordre: 4
---

# Les agents

> Des spécialistes qui persistent d'une session à l'autre. Chacun fait une
> chose, connaît ses limites, et passe la main quand ça sort de son domaine.

---

## Comment ils arrivent

- **Par la session** — le manifest du type de session en charge certains
  d'office (la colonne « Agents chargés d'office » de la page **Sessions**).
- **Par le domaine** — tu parles d'un bug, `debug` arrive.
- **Sur demande** — « charge l'agent testing », « charge les agents security
  et code-review ».

La plupart des agents chargent d'abord un résumé, puis leur détail quand ils
travaillent : le contexte reste disponible pour ce que tu fais.

---

## Les 70 agents

*Liste générée depuis l'en-tête de chaque fichier `agents/*.md` — la portée
(`brain.scope`) et le rôle (`brain.type`) qu'il déclare, et sa description.
Un agent ajouté ou retiré change cette page à la génération suivante.*

### Sur ton projet — code, qualité, infra, contenu (28)

- **`api-designer`** — Design API — REST, GraphQL, OpenAPI, contrats, conventions
- **`chrome-pilot`** — Navigation web pilotée — veille, scraping, debug frontend, capture de doc
- **`ci-cd`** — CI/CD — GitHub Actions, Gitea CI, pipelines
- **`code-review`** — Review code — qualité, sécurité, dette technique
- **`content-writer`** — Création de contenu — blog, réseaux sociaux, copywriting, communication
- **`copywriter`** — Stratégie de persuasion — structure, psychologie, frameworks de vente
- **`database-architect`** — Architecture de base de données — schéma, modélisation, index, normalisation
- **`debug`** — Debug agent — bugs, crashes, comportements inattendus
- **`doc`** — Documentation — README, API Swagger, cohérence doc ↔ code
- **`frontend-stack`** — Frontend stack — shadcn, Tailwind, architecture UI, patterns
- **`game-designer`** — Game designer — mécanique, équilibrage, progression, systèmes de jeu
- **`i18n`** — i18n — internationalisation, audit traductions, clés manquantes
- **`learning-journal`** — Apprentissage — capture, structuration, rétrospective
- **`mail`** — Mail — Stalwart, DNS, SMTP, IMAP, SPF, DKIM
- **`migration`** — Migration TypeORM — schéma, deploy safe
- **`monitoring`** — Monitoring — Gatus, logs VPS, alertes
- **`optimizer-backend`** — Optimizer backend — Node.js perf, mémoire
- **`optimizer-db`** — Optimizer DB — MySQL, N+1, index, TypeORM
- **`optimizer-frontend`** — Optimizer frontend — bundle, re-renders, React
- **`optimizer`** — Performance — backend, frontend, base de données, profilage
- **`pm2`** — Process manager — pm2 Node.js prod
- **`product-strategist`** — Product strategist — business model, SaaS, monétisation, positionnement
- **`refacto`** — Refactorisation — architecture + code
- **`release-manager`** — Release management — changelog, semver, tags, notes de version
- **`security`** — Security — OWASP, JWT, OAuth, failles
- **`testing`** — Testing — Jest, Vitest, TDD, coverage
- **`vps`** — Infra VPS — Apache, Docker, SSL, vhosts, certbot
- **`watch`** — Observatoire — visionnage vidéo, extraction, rapport, persistance git

### Spécialistes contenu (4)

- **`content-strategist`** — Content strategist — stratégie YouTube, angle, audience, arc narratif
- **`scriptwriter`** — Scriptwriter — scripts vidéo short 60s + long 12min, timing par ligne
- **`seo-youtube`** — SEO YouTube + thumbnail brief — copy-pasteable dans YouTube Studio
- **`ux-architect`** — UX architect — hiérarchie info L0/L1/L2, WorkflowBuilder, vision UX

### Scribes de projet (1)

- **`brain-ui-scribe`** — Brain-UI scribe — contexte brain-ui, stack, composants, Sprint 2

### Le fonctionnement du brain (17)

- **`brain-compose`** — Brain-compose — multi-instances, symlinks kernel, registre machine
- **`brain-guardian`** — Brain guardian — auto-méfiance structurelle, assertions prouvées uniquement quand brain opère sur lui-même
- **`brainstorm`** — Exploration et structuration de décisions — avocat du diable
- **`coach-boot`** — Coach boot — extrait coach.md boot-summary, chargé en L0 pour toutes les sessions
- **`coach`** — Coach permanent — présence, progression, feedback
- **`conciergerie`** — Archivage et hygiène de la donnée cognitive
- **`helloWorld`** — Bootstrap — ouvrir la session, charger ce qui est déclaré, dire où on en est
- **`integrator`** — Intégration multi-agents — absorption, validation critères, handoff
- **`interprete`** — Clarification d'intention — demandes ambiguës, scope drift
- **`mentor`** — Mentor — pédagogie, explication, garde-fou
- **`metabolism-scribe`** — Metabolism scribe — métriques session, health_score, prix par agent
- **`pre-flight`** — Pre-flight — gate boot, vérifie kerneluser + write_lock + posture avant chargement L1
- **`pulse`** — Snapshot live du brain — passé, présent, futur
- **`scribe`** — Scribe — maintenance du brain, structuration
- **`secrets-guardian`** — Secrets guardian — les valeurs ne passent jamais par la conversation
- **`secrets-manager`** — Secrets manager — poser, faire tourner, propager, sans jamais afficher
- **`tech-lead`** — Tech lead — gate sprint, contention map, overflow zones

### Orchestration (2)

- **`orchestrator`** — Coordination — aiguiller vers les agents, composer une fiche prête à agir, juger le rendu contre ses critères de fin
- **`session-orchestrator`** — Session orchestrator — lifecycle boot 4 couches, close séquencé

### Scribes du brain — ce qui s'écrit, et où (10)

- **`architecture-scribe`** — Architecture scribe — mémoire architecturale, git-analyst → ADR
- **`config-scribe`** — Config scribe — wizard first run, hydration Sources
- **`content-scribe`** — Content scribe — persistance content layer, drafts, content-logs
- **`decision-scribe`** — Decision scribe — registre connaissance structurelle, gate:human.DEFINE
- **`infra-scribe`** — Infra scribe — registre infra, DB, deploy paths, runtime
- **`kanban-scribe`** — Le mouvement du backlog — états des fiches, clôture sur preuve, gestes mécaniques (palier a)
- **`orchestrator-scribe`** — Bus inter-sessions — Signals BSI, cycles coworking, HANDOFF
- **`pattern-scribe`** — Pattern scribe — détection patterns récurrents inter-sessions, registre drift contextualisation
- **`todo-scribe`** — La liste du backlog — une fiche par tâche, par projet ; proposée à l'humain, créée seule en mode kanban
- **`toolkit-scribe`** — Toolkit scribe — persistance patterns, gardien toolkit/

### Sur le brain lui-même (5)

- **`agent-review`** — Audit du système d'agents — gaps, patches, vue système
- **`audit`** — Audit brain — cohérence inter-couches, gaps sessions/agents/ADRs, références cassées
- **`french-teacher`** — Langue française — orthographe, grammaire, syntaxe, style
- **`git-analyst`** — Git analyst — historique sémantique, conventions, synthèse commits
- **`onboarding-guide`** — Onboarding — premier boot, découverte, orientation

### Orientation (2)

- **`guide`** — Présentation du système — onboarding, visite guidée, « comment je fais X ? »
- **`pathfinder`** — Routage d'intention — comprend le besoin, oriente vers le bon type de session

### Utilitaires (1)

- **`secrets-injector`** — Secrets injector — injection credentials dans prompts subagents

---

## Créer le tien

`agents/_template.md` est le gabarit d'un agent, et `agents/_conventions.md`
ses conventions. Ton agent s'écrit dans `instance/agents/<nom>.md` — pas dans
`agents/`, qui est une vue — puis `brain vue --construire` le rend visible. Pour
modifier un agent du noyau, copie-le dans `instance/agents/` : ta version
l'emporte, et celle du noyau reste là pour comparer. `agent-review` audite un agent existant : ce qu'il promet,
ce qu'il fait, ce qui chevauche un autre.

Certains agents renvoient à des agents que ce brain n'a pas : ceux de l'instance
qui a publié le gabarit. Ces renvois portent « si présent », et un agent absent
ne se simule pas — l'agent qui devait lui passer la main te dit ce qui n'est
pas fait (`agents/_conventions.md`, convention 5).
