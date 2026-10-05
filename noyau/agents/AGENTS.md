---
name: AGENTS
type: index
context_tier: cold
---

# Agents spécialisés

> Index des agents disponibles.
> Charger un agent = lire son fichier en début de session pour injecter son contexte.
> Stratification Chaud/Froid — voir `profil/memory-architecture.md` Pillier 3.

---

## 🔴 Agents chauds — auto-détectés sur trigger domaine

> Chargés automatiquement quand le domaine est détecté.

| Agent | Domaine | Statut |
|-------|---------|--------|
| `coach` | Progression — tutorat, suivi, coaching code + agents | 🔄 permanent |
| `secrets-guardian` | Cycle de vie des secrets — MYSECRETS → .env, jamais dans le chat | 🧪 forgé 2026-03-14 |
| `vps` | Infra, Apache, Docker, SSL | 🔄 |
| `mail` | Stalwart, DNS, protocoles | 🔄 |
| `code-review` | Qualité, sécurité, dette technique | ✅ 2026-03-12 |
| `security` | Auth, tokens, OWASP | ✅ 2026-03-12 |
| `testing` | Jest, Vitest, DDD, coverage | ✅ 2026-03-12 |
| `debug` | Débogage local + prod | ✅ 2026-03-12 |
| `refacto` | Refactorisation — architecture + code | ✅ 2026-03-12 |
| `monitoring` | Observabilité — Gatus, logs VPS | ✅ 2026-03-12 |
| `ci-cd` | Pipelines GitHub Actions + Gitea CI | ✅ 2026-03-12 |
| `optimizer-backend` | Perf Node.js | ✅ 2026-03-12 |
| `optimizer-db` | Perf MySQL — N+1, index | ✅ 2026-03-12 |
| `optimizer-frontend` | Perf React — bundle, re-renders | ✅ 2026-03-12 |
| `pm2` | Process manager Node.js prod | 🧪 forgé 2026-03-13 |
| `migration` | TypeORM migrations — schéma, deploy safe | 🧪 forgé 2026-03-13 |
| `frontend-stack` | Architecture frontend — stack, libs UI, patterns pro | 🧪 forgé 2026-03-13 |
| `i18n` | Internationalisation — audit traductions, clés manquantes | 🧪 forgé 2026-03-13 |
| `doc` | Documentation — README, API Swagger, cohérence doc ↔ code | 🧪 forgé 2026-03-13 |
| `copywriter` | Stratégie de persuasion — Sinek × Halbert × Cialdini, structure avant rédaction | 🧪 forgé 2026-04-05 |
| `tech-lead` | Leadership technique — gate d'entrée sprint, contention map, overflow zones | 🧪 forgé 2026-03-14 |
| `game-designer` | Game design — mécanique, équilibrage, progression, systèmes de jeu | 🧪 forgé 2026-03-15 |
| `brain-ui-scribe` | Contexte brain-ui — stack, composants, Sprint 2, règles agents — chargé avant tout agent touchant brain-ui | 🧪 forgé 2026-03-17 |
| `audit` | Diagnostic brain — cohérence inter-couches, gaps sessions/agents/ADRs, références cassées | 🧪 forgé 2026-03-17 |
| `brain-guardian` | Auto-méfiance structurelle — assertions prouvées uniquement quand brain opère sur lui-même | 🧪 forgé 2026-03-18 |

---

## 🔵 Agents stables — invocation manuelle uniquement

> Ne se chargent pas automatiquement. Invoqués explicitement par l'utilisateur ou sur signal d'un agent chaud.

| Agent | Domaine | Statut |
|-------|---------|--------|
| `orchestrator` | Coordination — aiguiller, composer une fiche prête (critères de fin), juger le rendu (BRAIN-079) | ✅ 2026-03-12 |
| `scribe` | Maintenance du brain | ✅ 2026-03-12 |
| `mentor` | Pédagogie — explication, garde-fou | ✅ 2026-03-12 |
| `agent-review` | Audit du système d'agents — gaps, patches, vue système | ✅ 2026-03-13 |
| `brainstorm` | Exploration et structuration de décisions — avocat du diable | 🧪 forgé 2026-03-13 |
| `toolkit-scribe` | Persistance patterns — gardien du toolkit/ | 🧪 forgé 2026-03-13 |
| `todo-scribe` | La liste — une fiche par tâche, proposée à l'humain, créée seule en mode kanban (BRAIN-079) | 🧪 forgé 2026-03-13 |
| `kanban-scribe` | Le mouvement — fait avancer les fiches, clôt sur preuve, tient le backlog (BRAIN-079) | 🧪 forgé 2026-03-15 |
| `helloWorld` | Bootstrap intelligent — briefing + chargement sélectif | 🧪 forgé 2026-03-13 |
| `content-strategist` | Stratégie contenu YouTube — angle, audience, arc narratif, titres A/B | 🧪 forgé 2026-03-17 |
| `scriptwriter` | Scripts vidéo tournables — short 60s + long 12min, timing par ligne | 🧪 forgé 2026-03-17 |
| `seo-youtube` | SEO YouTube + thumbnail brief — copy-pasteable dans YouTube Studio | 🧪 forgé 2026-03-17 |
| `git-analyst` | Historique git sémantique — conventions, synthèse commits | 🧪 forgé 2026-03-13 |
| `config-scribe` | Configuration brain — wizard first run, hydration Sources | 🧪 forgé 2026-03-13 |
| `orchestrator-scribe` | Bus inter-sessions — Signals BSI, cycles coworking, HANDOFF | 🧪 forgé 2026-03-14 |
| `session-orchestrator` | Lifecycle de session — boot 4 couches, close séquencé, rapport coach | 🧪 forgé 2026-03-14 |
| `architecture-scribe` | Mémoire architecturale — git-analyst → ADR → profil/decisions/ | 🧪 forgé 2026-03-15 |
| `integrator` | Intégration multi-agents — absorption, validation critères, handoff next team | 🧪 forgé 2026-03-14 |
| `product-strategist` | Stratégie produit — business model, SaaS, monétisation, positionnement | 🧪 forgé 2026-03-15 |
| `conciergerie` | Chirurgie donnée cognitive — archivage par tier, nettoyage, audit embeddings | ✅ 2026-03-25 |
| `api-designer` | Design API — REST, GraphQL, OpenAPI, contracts, conventions | ✅ à la demande (4/10) |
| `database-architect` | Architecture base de données — schéma, modélisation, indexes, normalisation | ✅ à la demande (4/10) |
| `content-writer` | Création de contenu — blog, social media, copywriting, communication | ✅ active |
| `french-teacher` | Langue française — orthographe, grammaire, syntaxe, style | ✅ active |
| `guide` | Présentation système — onboarding, tour guide, "comment je fais X ?" | ✅ active |
| `learning-journal` | Apprentissage — capture, structuration, rétrospective | ✅ active |
| `pathfinder` | Routage intentionnel — comprend le besoin, oriente vers le bon workflow | ✅ active |
| `pulse` | Snapshot live du brain — passé/présent/futur, screenable, miroir CLI de la vue Pulse d'un dashboard | 🧪 forgé 2026-04-09 |
| `release-manager` | Release management — changelog, semver, tags, release notes | ✅ active |
| `secrets-manager` | Cycle de vie des secrets — expiry, rotation, audit, sync multi-machine | ✅ active |

---

## ⚙️ Agents kernel — protocole & supervision

> Agents de protocole système — scope:kernel, distribués dans brain-template.
> Invocation explicite. Ne se chargent pas automatiquement.

| Agent | Domaine | Statut |
|-------|---------|--------|
| `coach-boot` | Présence permanente — extrait boot-summary de coach.md, chargé L0 CLAUDE.md toutes sessions | 🧪 forgé 2026-03-12 |

---

## 🔒 Agent personnel — privé, non distribué

> scope:personal — ne sort jamais dans brain-template.

| Agent | Domaine | Statut |
|-------|---------|--------|

---

## 🗄️ Archivés — dans `agents/archive/`

> La machinerie de mars (workflows, satellites, supervision) : **jamais exercée
> en base** — 0 claim `workflow`, 0 `satellite_type`, 0 `parent_sess` sur 627
> (mesuré le 27/09). Archivée le 30/09 (BRAIN-079) : le lancement
> d'agents passe désormais par le palier c — l'`orchestrator` compose et juge,
> un worker (sous-agent) travaille dans son worktree, `dev/autonome` accueille.

| Agent | Ce qu'il était |
|---|---|

---

## Templates

| Template | Usage |
|----------|-------|
| `_template.md` | Agent standard — métier, scribe, coach, meta |
| `_template-orchestrator.md` | Orchestrateur — détecte des signaux, active des agents, ne produit pas |

> Règle de sélection : "est-ce qu'il produit quelque chose lui-même ?" → Oui = `_template.md` / Non = `_template-orchestrator.md`

---

## Workflows multi-agents connus

| Workflow | Agents | Description |
|----------|--------|-------------|
| Nouveau service VPS | `vps` | Deploy Docker + Apache + SSL |
| Audit infra + code | `vps` + `code-review` | Vérification complète avant mise en prod |
| Déploiement mail | `vps` + `mail` | Setup Stalwart depuis zéro |
| Audit perf full-stack | `optimizer-backend` + `optimizer-db` + `optimizer-frontend` | Riri Fifi Loulou |
| Audit perf backend | `optimizer-backend` + `optimizer-db` | API + DB — sans toucher au frontend |
| Validation avant prod | `code-review` + `ci-cd` | Review code + pipeline avant déploiement |
| Nouveau projet complet | `vps` + `ci-cd` | Déploiement serveur + pipeline CI/CD |
| Problème non identifié | `orchestrator` → agents détectés | Diagnostic + délégation automatique |
| Audit système d'agents | `agent-review` → `recruiter` (si présent) | Review + détection gaps → forge si besoin |
| Exploration / décision archi | `brainstorm` → `recruiter` (si présent) ou agent métier | Explorer + challenger → construire |
| Question hors-scope en session | `aside` (si présent) | /btw → 2-3 lignes → retour session |
| Coordination multi-instances | `orchestrator-scribe` | Signals BSI + cycles coworking inter-brains |
| Fin de session complète | `session-orchestrator` → `scribe` + `coach` | Séquence close : fiches → brain → rapport coach → BSI |
| Feature livrée en prod | `git-analyst` + `capital-scribe` (si présent) | Commits synthétisés + capital CV mis à jour |
| Projet multi-langue | `i18n` + `frontend-stack` | Audit traductions + intégration lib |
| Release / PR importante | `doc` + `code-review` | Doc à jour + code validé |
| Passe du palier c (BRAIN-079) | `orchestrator` (composer) → worker → `orchestrator` (juger) → `kanban-scribe` | Fiche prête → worker dans son worktree → PR vers `dev/autonome` → verdict, preuves rejouées, mutant → clôture 🤖 à la fusion humaine |
| Débordement de zone requis | agent demandeur → `tech-lead` | Overflow request validé par use case concret avant écriture hors zone |
| Audit complet avant prod | `security` + `code-review` + `testing` | Validation complète feature sensible |
| Bug prod complexe | `debug` + `vps` | Isolation + infra |
| Refacto sécurisée | `refacto` + `testing` + `code-review` | Tests avant, refacto, review après |
| Incident prod | `monitoring` + `vps` + `debug` | Alerte → diagnostic infra → debug applicatif |
| Nouveau déploiement | `ci-cd` + `monitoring` | Pipeline + sondes de surveillance |
| Dream team perf | `orchestrator` → `optimizer-*` | Audit perf full-stack via orchestrateur |
