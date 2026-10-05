---
name: PLAN-REVIEW-AGENTS
type: reference
context_tier: cold
---

# Plan de review des agents — conditions réelles

> ⚠️ Ce fichier concerne la qualité des AGENTS, pas les tests du code applicatif.
> Tests code → Jest/Vitest dans chaque projet.

---

## La boucle en une phrase

> Lancer → Capturer → Évaluer → Patcher → Documenter.

Chaque review laisse l'agent **meilleur qu'avant** et le brain **plus riche qu'à son départ**.

---

## Phrases d'invocation — copier-coller direct

### 1. Lancer la review (session projet)

```
Charge l'agent <nom>.
<Cas concret — voir "Use cases concrets" ci-dessous>
```

Exemple réel :
```
Charge l'agent monitoring.
Audite la couverture de surveillance actuelle sur Uptime Kuma.
Identifie ce qui manque et propose les sondes à créer.
```

### 2. Patcher avec le recruiter (après évaluation)

```
Charge l'agent recruiter.
Lis brain/agents/reviews/<Projet>/<agent>-v1.md.
Améliore l'agent <nom> en intégrant les gaps identifiés.
```

### 3. Fermer la boucle avec le scribe (fin de session)

```
Charge l'agent scribe.
On vient de faire la review de <agent> — mets le brain à jour.
```

### Phrase complète — session de review dédiée

```
On review l'agent <nom>.
Projet de test : <projet>.
Cas soumis : <description courte du problème à lui soumettre>.
Prépare le template, lance-le, évalue, patche avec recruiter, scribe en fin.
```

---

## Philosophie — progression hexagonale

Comme en architecture hexagonale : chaque couche doit être **solide avant d'en ajouter une autre**.

```
Review 1 (security)    → identifie les patterns manquants
Review 2 (code-review) → confirme le pattern → correction systématique
Review 3 (testing)     → le pattern est acquis, on cherche d'autres gaps
...
Review N (scribe)      → le scribe lui-même est reviewé avec les mêmes critères
```

**Ce que chaque review apporte :**
- Un agent testé en conditions réelles (pas en théorie)
- Un gap documenté = une règle qui ne sera plus oubliée
- Un pattern transversal détecté = tous les agents suivants en bénéficient
- Un changelog qui raconte l'histoire des améliorations

**Signal de progression réelle :** quand les gaps trouvés en v1 disparaissent en v2.
Pas parce qu'on les a ignorés — parce que l'agent a vraiment appris.

---

## Procédure complète — step by step

### Étape 1 — Préparer le fichier de capture

```bash
cp brain/agents/reviews/_template.md brain/agents/reviews/<Projet>/<agent>-v1.md
```

Remplir l'en-tête : agent reviewé, date, projet, cas soumis.

### Étape 2 — Lancer l'agent dans une session Claude Code

Ouvrir une session dans le projet concerné, charger l'agent, lui soumettre le cas.
→ Voir "Phrases d'invocation" + "Use cases concrets" ci-dessous.

### Étape 3 — Capturer l'output

Copier-coller l'intégralité de la réponse de l'agent dans `reviews/<Projet>/<agent>-v1.md`.
Section "Output brut de l'agent" du template.

### Étape 4 — Évaluer

Remplir les sections ✅ ❌ ⚠️ 📐 du template.
Identifier les gaps concrets : qu'est-ce qui manquait ? qu'a-t-il inventé ? a-t-il débordé ?

### Étape 5 — Améliorer l'agent (si gaps)

```
Charge l'agent recruiter.
Lis brain/agents/reviews/<Projet>/<agent>-v1.md.
Améliore l'agent <nom> en intégrant les gaps identifiés.
```

### Étape 6 — Scribe + re-tester

```
Charge l'agent scribe.
On vient de faire la review de <agent> — mets le brain à jour.
```

Répéter étapes 2-4 → sauvegarder dans `<agent>-v2.md`.
Comparer v1 / v2 — noter dans le changelog de l'agent.

---

## Use cases concrets — prompts exacts

### `orchestrator` — "Je ne sais pas par où commencer"

```
Charge l'agent orchestrator.
Je veux préparer mon-api pour un déploiement en production.
Je ne sais pas par où commencer ni quels agents charger.
Dis-moi ce qui doit être fait et dans quel ordre.
```

**Ce qu'on vérifie :** identifie-t-il les bons domaines ? Propose-t-il un ordre logique ?
Reste-t-il coordinateur (ne code pas, ne déploie pas) ?
**Statut :** ✅ Testé 2026-03-12 — RÉUSSI

---

### `security` — Audit avant prod

```
Charge l'agent security.
Audite la branche feature/security-hardening de mon-api.
Focus sur : JWT blacklist Redis, CSRF, CSP nonce, device fingerprinting.
Dis-moi si l'implémentation est correcte et ce qui manque.
```

**Ce qu'on vérifie :** connaît-il les mécanismes déjà en place (ne les re-propose pas) ?
Trouve-t-il de vrais gaps ? Respecte-t-il les priorités d'audit dans l'ordre ?

---

### `code-review` — Review d'un fichier

```
Charge l'agent code-review.
Review ce fichier : [coller le contenu ou donner le chemin]
Projet : mon-api, architecture DDD.
```

**Ce qu'on vérifie :** format adapté (inline si court, rapport si long) ?
Explique-t-il le *pourquoi* de chaque finding ? Respecte-t-il le périmètre ?

---

### `testing` — Stratégie coverage

```
Charge l'agent testing.
Analyse la couverture actuelle de mon-api.
Identifie les zones critiques non couvertes (priorité : couches DDD auth flows).
Propose une stratégie pour atteindre une couverture suffisante avant prod.
```

**Ce qu'on vérifie :** connaît-il la structure DDD par couche ?
Distingue-t-il les tests unitaires des tests d'intégration ? Propose-t-il TDD ou rétroactif selon le contexte ?

---

### `debug` — Diagnostic d'une erreur

```
Charge l'agent debug.
J'ai cette erreur : [coller la stack trace ou décrire le symptôme]
Projet : mon-api, stack Express + TypeORM + Redis.
Aide-moi à isoler la cause.
```

**Ce qu'on vérifie :** suit-il la méthode en 5 étapes (reproduire → isoler → hypothèses → vérifier → corriger) ?
Formule-t-il des hypothèses ordonnées par probabilité ?

---

### `ci-cd` — Créer un pipeline

```
Charge l'agent ci-cd.
Je veux créer le pipeline de déploiement prod pour mon-api.
CI actuel : tests seulement (ci.yml). À ajouter : build + SSH deploy + migration TypeORM.
Stack : Node.js 22, TypeScript, Docker.
```

**Ce qu'on vérifie :** adapte-t-il au type de projet (Node.js + Docker) ?
Connaît-il les secrets VPS ? Propose-t-il d'ajouter le template dans toolkit/ ?

---

### `monitoring` — Audit couverture Kuma

```
Charge l'agent monitoring.
Audite la couverture de surveillance actuelle sur Uptime Kuma.
Identifie ce qui manque et propose les sondes à créer.
```

**Ce qu'on vérifie :** connaît-il l'infra réelle (containers, sous-domaines, monitoring.md) ?
Détecte-t-il les gaps entre ce qui est surveillé et ce qui devrait l'être ?

---

### `scribe` — Bilan de session

```
Charge l'agent scribe.
Fais le bilan de cette session et mets le brain à jour.
```

**Ce qu'on vérifie :** identifie-t-il les bons fichiers à mettre à jour ?
Propose-t-il validation avant les changements importants ?

---

### `mentor` — Interpréter un plan

```
Charge l'agent mentor.
L'orchestrator vient de proposer ce plan : [coller l'output].
Explique-moi pourquoi security passe avant code-review.
Vérifie que j'ai bien compris la logique avant qu'on continue.
```

**Ce qu'on vérifie :** explique-t-il le *pourquoi* (pas juste le *quoi*) ?
Pose-t-il une question de vérification sans surcharger ?

---

### `refacto` — Audit dette technique

```
Charge l'agent refacto.
Audite mon-projet — identifie la dette technique principale.
Propose un plan de refacto en étapes atomiques.
Règle absolue : aucune logique métier ne doit disparaître.
```

**Ce qu'on vérifie :** produit-il un plan en étapes, du moins risqué au plus risqué ?
Demande-t-il validation avant de passer à l'exécution ?

---

## Ordre recommandé

| # | Agent | Projet | Statut |
|---|-------|--------|--------|
| 1 | `orchestrator` | mon-api | ✅ 2026-03-12 |
| 2 | `security` | mon-api | ✅ 2026-03-12 |
| 3 | `code-review` | mon-api | ✅ 2026-03-12 |
| 4 | `testing` | mon-api | ✅ 2026-03-12 |
| 5 | `debug` | mon-api | ✅ 2026-03-12 |
| 6 | `ci-cd` | mon-api | ✅ 2026-03-12 |
| 7 | `monitoring` | Infra | ✅ 2026-03-12 |
| 8 | `scribe` | Brain | ✅ 2026-03-12 |
| 9 | `mentor` | mon-api | ✅ 2026-03-12 |
| 10 | `optimizer-db` | mon-api | ✅ 2026-03-12 |
| 11 | `refacto` | mon-api | ✅ 2026-03-12 |
| 12 | `optimizer-backend` | mon-api | ✅ 2026-03-12 |
| 13 | `optimizer-frontend` | mon-site | ✅ 2026-03-12 |

---

## Critères de validation d'un agent (solo)

- ✅ Output utile et ancré dans la réalité (pas d'invention)
- ✅ Anti-hallucination : dit "Information manquante" quand nécessaire
- ✅ Périmètre respecté : ne déborde pas, délègue ce qui ne le concerne pas
- ✅ Format adapté au cas soumis

---

## Critères swarm-ready (en plus des critères solo)

> Source : BACT `agentic.swarm-ready-gate` — BRAIN-032

- ✅ Exécuté dans un workflow en mode 1 (manual) au moins une fois
- ✅ Exécuté dans un workflow en mode 2 (assisted) au moins une fois
- ✅ Output structuré + consommable sans reformat humain (status / findings / next_step_input)
- ✅ Composition validée avec les agents partenaires du workflow

Quand les 4 critères sont remplis → déclarer `swarm_ready: true` dans le workflow concerné.

---

## Ordre recommandé — 74 agents, 3 priorités

### Batch A — Backbone swarm (13 validés + 8 à faire en premier)

> Ces agents seront dans presque tous les workflows futurs.
> Les passer en mode 2 en priorité = débloquer le reste.

| # | Agent | Projet test suggéré | Statut |
|---|-------|---------------------|--------|
| 1 | `orchestrator` | mon-api | ✅ 2026-03-12 |
| 2 | `security` | mon-api | ✅ 2026-03-12 |
| 3 | `code-review` | mon-api | ✅ 2026-03-12 |
| 4 | `testing` | mon-api | ✅ 2026-03-12 |
| 5 | `debug` | mon-api | ✅ 2026-03-12 |
| 6 | `ci-cd` | mon-api | ✅ 2026-03-12 |
| 7 | `monitoring` | Infra | ✅ 2026-03-12 |
| 8 | `scribe` | Brain | ✅ 2026-03-12 |
| 9 | `mentor` | mon-api | ✅ 2026-03-12 |
| 10 | `optimizer-db` | mon-api | ✅ 2026-03-12 |
| 11 | `refacto` | mon-api | ✅ 2026-03-12 |
| 12 | `optimizer-backend` | mon-api | ✅ 2026-03-12 |
| 13 | `optimizer-frontend` | mon-site | ✅ 2026-03-12 |
| 14 | `supervisor` | Brain multi-session | 🗄️ archivé le 30/09 |
| 15 | `brain-hypervisor` | Brain workflow | 🗄️ archivé le 30/09 |
| 16 | `kernel-orchestrator` | Brain workflow | 🗄️ archivé le 30/09 |
| 17 | `session-orchestrator` | Brain session | 🧪 à reviewer |
| 18 | `tech-lead` | mon-api sprint | 🧪 à reviewer |
| 19 | `integrator` | Brain multi-agent | 🧪 à reviewer |
| 20 | `context-broker` | Brain sprint cycle | 🗄️ archivé le 30/09 |
| 21 | `pre-flight` | Brain boot | 🧪 à reviewer |

### Batch B — Agents métier haute fréquence

> Agents utilisés dans les workflows projet courants.
> Review en conditions réelles sur les projets actifs.

| # | Agent | Projet test suggéré | Statut |
|---|-------|---------------------|--------|
| 22 | `vps` | Infra deploy | 🧪 à reviewer |
| 23 | `migration` | mon-api | 🧪 à reviewer |
| 24 | `pm2` | Infra | 🧪 à reviewer |
| 25 | `frontend-stack` | brain-ui | 🧪 à reviewer |
| 26 | `doc` | mon-api | 🧪 à reviewer |
| 27 | `brainstorm` | Brain décision | 🧪 à reviewer |
| 28 | `interprete` | Brain session | 🧪 à reviewer |
| 29 | `agent-review` | Brain agents | 🧪 à reviewer |
| 30 | `recruiter` | Brain forge | 🧪 à reviewer |
| 31 | `helloWorld` | Brain boot | 🧪 à reviewer |
| 32 | `aside` | Brain session | 🧪 à reviewer |
| 33 | `coach` | Brain progression | 🧪 à reviewer |
| 34 | `brain-guardian` | Brain self-audit | 🧪 à reviewer |
| 35 | `audit` | Brain health | 🧪 à reviewer |
| 36 | `mail` | Infra Stalwart | 🧪 à reviewer |
| 37 | `i18n` | mon-api | 🧪 à reviewer |
| 38 | `ux-architect` | brain-ui | 🧪 à reviewer |
| 39 | `brain-ui-scribe` | brain-ui | 🧪 à reviewer |
| 40 | `satellite-boot` | Brain satellite | 🗄️ archivé le 30/09 |

### Batch C — Scribes + agents spécialisés

> Review en mode autonome (agent-review lit + simule) — pas besoin de session dédiée.
> Capturer dans reviews/ Brain/.

| # | Agent | Statut |
|---|-------|--------|
| 41 | `decision-scribe` | 🧪 à reviewer (autonome) |
| 42 | `architecture-scribe` | 🧪 à reviewer (autonome) |
| 43 | `spec-scribe` | 🧪 à reviewer (autonome) |
| 44 | `wiki-scribe` | 🧪 à reviewer (autonome) |
| 45 | `todo-scribe` | 🧪 à reviewer (autonome) |
| 46 | `coach-scribe` | 🧪 à reviewer (autonome) |
| 47 | `toolkit-scribe` | 🧪 à reviewer (autonome) |
| 48 | `kanban-scribe` | 🧪 à reviewer (autonome) |
| 49 | `metabolism-scribe` | 🧪 à reviewer (autonome) |
| 50 | `orchestrator-scribe` | 🧪 à reviewer (autonome) |
| 51 | `content-scribe` | 🧪 à reviewer (autonome) |
| 52 | `infra-scribe` | 🧪 à reviewer (autonome) |
| 53 | `bact-scribe` | 🗄️ archivé le 30/09 |
| 54 | `diagram-scribe` | 🧪 à reviewer (autonome) |
| 55 | `pattern-scribe` | 🧪 à reviewer (autonome) |
| 56 | `git-analyst` | 🧪 à reviewer (autonome) |
| 57 | `content-orchestrator` | 🧪 à reviewer (autonome) |
| 58 | `content-strategist` | 🧪 à reviewer (autonome) |
| 59 | `storyteller` | 🧪 à reviewer (autonome) |
| 60 | `scriptwriter` | 🧪 à reviewer (autonome) |
| 61 | `seo-youtube` | 🧪 à reviewer (autonome) |
| 62 | `product-strategist` | 🧪 à reviewer (autonome) |
| 63 | `workflow-auditor` | 🗄️ archivé le 30/09 |
| 64 | `key-guardian` | 🧪 à reviewer (autonome) |
| 65 | `feature-gate` | 🧪 à reviewer (autonome) |
| 66 | `secrets-guardian` | 🧪 à reviewer (autonome) |
| 67 | `secrets-injector` | 🧪 à reviewer (autonome) |
| 68 | `bsi-schema` | 🗄️ archivé le 30/09 |
| 69 | `game-designer` | 🧪 à reviewer (autonome) |
| 70 | `capital-scribe` | 🧪 à reviewer (autonome) |
| 71 | `config-scribe` | 🧪 à reviewer (autonome) |
| 72 | `brain-compose` | 🧪 à reviewer (autonome) |
| 73 | `time-anchor` | 🧪 à reviewer (autonome) |
| 74 | `coach-boot` | invariant boot — review par observation |

---

## Notation changelog après review

```
| 2026-XX-XX | Review réelle — <Projet> : ✅ <ce qui a marché> / ❌ <gap identifié> / 🔧 <correction appliquée> |
```
