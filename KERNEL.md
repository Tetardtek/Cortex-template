---
name: KERNEL
type: reference
context_tier: always
---

# KERNEL.md — Loi des zones

> **Type :** Invariant absolu — chargé Couche 0 par helloWorld, avant tout agent.
> Dernière révision : 2026-03-15
> Propriétaire : kernel (aucun agent ne modifie ce fichier seul — décision humaine requise)
> Complété par : `brain-constitution.md` — identité + protocoles Layer 0 (ne pas répéter, ne pas surcharger)

---

## Principe fondateur

Le brain est une **matrice à zones typées avec protection graduée**.
Chaque zone a une nature, une protection, et des scribes propriétaires.
Un agent qui sait dans quelle zone il opère sait automatiquement ce qu'il peut écrire — et ce qu'il ne peut pas.

**Règle d'or — non négociable :**
> Une feature grandit dans un satellite → elle peut être promue dans le kernel.
> Le kernel ne dérive jamais vers un satellite. Le flux est unidirectionnel.

---

## Les zones

### ZONE KERNEL — Protection maximale

```
Fichiers : KERNEL.md, CLAUDE.md, PATHS.md, brain-compose.yml, BRAIN-INDEX.md
           brain-constitution.md
           agents/   profil/
```

| Règle | Détail |
|-------|--------|
| **Protection** | Aucun agent ne modifie sans décision humaine explicite |
| **Versioning** | Chaque modification significative = tag semver |
| **Export** | brain-template = kernel sans couche instance/personnelle |
| **Commit type** | `kernel:` (contrat), `feat:` (nouvelle capacité), `bsi:` (claims/signals) |
| **Scribe** | `scribe` (agents/, profil/ état), `orchestrator-scribe` (BRAIN-INDEX.md) |

**Sous-zone PROFIL — l'âme**
```
profil/   →  Invariant (collaboration, kernel-zones, architecture) : jamais surchargé
              Contexte (session-types, agent-types, contexts/) : évolue sur signal validé
              Référence (bsi-spec, scribe-system) : mis à jour sur changement de spec
```
Le profil modèle la **personnalité** du brain. Un Invariant profil = valeur aussi dure que le kernel.

---

### ZONE SATELLITES — Vie libre, promotion possible

```
Repos : toolkit/   progression/   todo/   reviews/
        handoffs/  workspace/
```

| Règle | Détail |
|-------|--------|
| **Protection** | Chaque satellite a son scribe propriétaire — les autres ne touchent pas |
| **Versioning** | Rythme propre à chaque satellite |
| **Promotion** | Pattern validé dans toolkit/ → peut entrer dans profil/ ou agents/ via recruiter |
| **Commit type** | `scribe:` `todo:` `metabolism:` `toolkit:` selon le satellite |
| **Scribes** | toolkit-scribe, progression/metabolism-scribe, todo-scribe, coach-scribe |

---

### ZONE INSTANCE — Configuration machine

```
Fichiers : focus.md, projets/*, PATHS.md (valeurs réelles), brain-compose.local.yml
```

| Règle | Détail |
|-------|--------|
| **Protection** | Personnel à une machine — jamais dans brain-template |
| **Commit type** | `scribe:` (focus, projets), `config:` (PATHS, compose) |
| **Scribe** | `scribe` (focus, projets) |

---

### ZONE WORK — Externe

```
Repos projets : GitHub, Gitea projets clients/perso
```

| Règle | Détail |
|-------|--------|
| **Protection** | Aucune protection kernel — vit sa propre vie |
| **Interaction** | Le brain documente, ne possède pas |

---

## Commit types — propriété et zone

| Type | Zone | Scribe propriétaire | Déclencheur |
|------|------|--------------------|-|
| `kernel:` | KERNEL | Décision humaine | Modification contrat fondateur |
| `feat:` | KERNEL agents/ | recruiter + humain | Nouvel agent forgé, capacité ajoutée |
| `fix:` | KERNEL agents/ | debug / agent-review | Correction comportement |
| `bsi:` | KERNEL BRAIN-INDEX | orchestrator-scribe | Open/close claim, signal |
| `integrator:` | WORK (repos projets) | integrator | Commit d'absorption multi-agents, push sprint |
| `scribe:` | INSTANCE + KERNEL profil/ | scribe | brain update (focus, projets, profil) |
| `metabolism:` | SATELLITES progression/ | metabolism-scribe | Fin de session — métriques |
| `todo:` | SATELLITES todo/ | todo-scribe | Intentions fermées/ouvertes |
| `toolkit:` | SATELLITES toolkit/ | toolkit-scribe | Pattern validé en prod |
| `config:` | INSTANCE | config-scribe | PATHS, compose, machine config |

**Règle scribe :**
> Un agent métier ne commit jamais directement.
> Il signal → le scribe compétent écrit → dans sa zone uniquement.

**Exceptions explicites (comme `helloWorld` pour `bsi:`) :**
> `integrator` → commit direct en zone WORK uniquement (repos projets, hors brain/)
>                Pour brain/handoffs/ → signal à `orchestrator-scribe`
> `tech-lead`  → aucune écriture directe — cosigne les messages de commit uniquement

**Portée — tranché le 05/09 :**
> La convention porte sur **tout commit dans le dépôt `brain`**, quelle que
> soit la session qui l'écrit — `work`, `explore`, `chill` et `learning`
> comprises. Une session projet qui consigne dans le brain écrit dans le brain.
> Appliquée par le hook `commit-msg` (`scripts/install-brain-hooks.sh`), qui lit
> les types de ce tableau et refuse ce qui n'en porte pas.

**Fusions — tranché le 16/09 :**
> Un commit de **fusion pure** — deux parents ou plus, et **aucun changement
> propre** — ne déclare pas de type. Il ne possède rien : il coud. Lui demander
> quel scribe le possède n'a pas de réponse.
>
> 🔴 **L'exemption s'arrête là.** Un merge qui **résout un conflit** écrit du
> contenu, et doit dire quel scribe le possède comme n'importe quel commit.
> Sans cette restriction, l'exemption serait une porte : il suffirait de faire
> passer un changement dans une fusion pour échapper à la règle.
>
> Le critère est `git diff-tree --cc` — le diff *combiné*, qui ne montre que ce
> que la fusion a décidé elle-même. Vide = elle n'a rien décidé.
>
> **Pourquoi la règle manquait :** les fusions de PR sont écrites par Gitea,
> **côté serveur**. Le hook `commit-msg` ne les voit pas — la convention était
> donc appliquée d'un côté et pas de l'autre. Quatre fusions sont apparues d'un
> coup le 16/09 et l'ont révélé.

---

## Session type → zone access (Sessions V2 — BRAIN-047)

| Type session | Zones accessibles | Zones interdites | Notes |
|-------------|------------------|-----------------|-------|
| `work` | KERNEL (lecture) + INSTANCE + SATELLITES + WORK | KERNEL (écriture) | Produit — code, deploy, debug, infra, ops |
| `brain` | KERNEL (agents/, profil/) + INSTANCE + SATELLITES | WORK | Construit le systeme — gate humain sur kernel write |
| `explore` | Toutes (lecture) + todo/ | Écriture (sauf scope /audit → write-lock strict) | Reflechit — navigate, brainstorm, coach, audit |
| `pilote` | Toutes — gates architecturaux sur forks irréversibles | — | Orchestre — co-construction longue duree |
| `chill` | Toutes (lecture) + écriture on-demand | — | Présence — discussion libre, learning, pas de livrable |
| `learning` | Toutes (lecture) + learning/, todo/, repos projets | KERNEL (écriture) | Découvre — expérimentation, veille ; jamais de write kernel |

> Tags BSI (deploy, debug, infra, coach, audit...) capturent la granularite — le type porte la posture.
> V1 archivee dans contexts/archive-v1/ (15 types → 4). Migration : BRAIN-047.

---

## Protection graduée — niveaux

| Niveau | Fichiers | Peut modifier | Trigger |
|--------|----------|---------------|---------|
| **Absolu** | KERNEL.md, CLAUDE.md, bsi-spec.md, brain-constitution.md | Humain uniquement | Décision architecturale majeure |
| **Fort** | profil/ Invariant, agents/ system | Humain + confirmation | Session brain avec signal explicite |
| **Standard** | agents/ metier, profil/ Contexte | Scribe sur signal | Fin de session significative |
| **Libre** | Satellites, INSTANCE | Scribe propriétaire | En session, sur livrable |

---

## Mode rendering — instance autonome projet

```
Mode rendering = satellite autonome sur zone:project
  → scope_lock: true   — ne sort jamais du scope déclaré
  → zone_lock: project — zone:kernel = BLOCKED_ON immédiat
  → circuit_breaker    — 3 fails → arrêt + signal pilote
  → mutex BSI-v3-7     — vérifie le lock fichier avant chaque écriture

Ce mode NE PEUT PAS :
  - Modifier agents/, profil/, scripts/, KERNEL.md, brain-compose.yml
  - Prendre des décisions architecturales
  - Continuer après 3 échecs consécutifs
  - Écrire dans un fichier locké par une autre instance

Déclaration dans le claim pilote :
  mode: rendering
  scope: mon-api/           ← le seul périmètre autorisé
```

---

## Isolation kernel — règle de distribution

> Un agent kernel distributable doit fonctionner sur n'importe quel brain forké.
> Il ne peut pas dépendre de fichiers privés spécifiques à ce brain.

**Règles d'isolation — non négociables :**

```
INTERDIT dans agents/ distribuables :
  - Chemin machine absolu hardcodé (/home/<user>/..., /root/...)
  - toolkit/private/ — patterns privés non distribués
  - require:/load:/source: vers MYSECRETS ou tout fichier zone:personal

AUTORISÉ (références documentaires) :
  - Mention de MYSECRETS comme concept (l'agent décrit où chercher)
  - Référence à profil/capital.md, profil/objectifs.md — l'utilisateur fork a les siens
  - Référence à progression/ — même raison
  - brain-compose.local — c'est la convention machine, chaque fork a le sien
```

**Vérification avant chaque distribution :**
```bash
bash scripts/kernel-isolation-check.sh          # check standard
bash scripts/kernel-isolation-check.sh --strict  # zéro tolérance
```

**Version lock :**
```bash
bash scripts/kernel-lock-gen.sh    # régénère kernel.lock après chaque modification kernel
```
`kernel.lock` — 79 fichiers kernel checksumés en SHA-256. Permet à un fork de détecter les fichiers modifiés localement avant de puller une update upstream.

---

## Délégation kernel — BSI-v3 + BRAIN-014

> Connexion entre la protection graduée ci-dessus et le protocole BSI (claims, satellites, zones).

### Mapping zones KERNEL.md → zone BSI

| Zone KERNEL.md | zone BSI (claim) | Satellite autorisé |
|---------------|-----------------|-------------------|
| ZONE KERNEL (agents/, profil/, scripts/, KERNEL.md…) | `kernel` | Human-confirmed uniquement |
| ZONE INSTANCE + SATELLITES (todo/, projets/, workspace…) | `project` | Tout satellite autorisé |
| ZONE PERSONNELLE (profil/capital, progression/, MYSECRETS) | `personal` | Tier 2 Validated minimum + confirmation |

### Règle de délégation kernel — non négociable

```
PHASE ACTUELLE (BSI-v3, avant kernel-orchestrator) :
  zone:kernel write → session humaine uniquement
  Aucun satellite ne modifie une zone:kernel en autonomie
  Toute modification kernel = décision humaine explicite dans la session

PHASE FUTURE (après BSI-v3-9 kernel-orchestrator stable) :
  zone:kernel write → autorisé si kerneluser: true ET satellite lancé par owner
  Le satellite agit sous délégation explicite — jamais en auto-init
```

**Pourquoi human-only maintenant :**
Le kernel-orchestrator (BSI-v3-9) n'existe pas encore. Laisser des satellites écrire en zone kernel sans ce garde-fou = dérive garantie. La promotion se fait quand l'orchestrator est mature et auditable.

### kerneluser

```yaml
# Dans brain-compose.yml
kerneluser: true   → propriétaire de ce brain — sudo sur toutes les zones
kerneluser: false  → utilisateur invité (BaaS futur) — zone:kernel bloquée
```

`kerneluser: true` est le défaut sur tout brain forké. L'owner est toujours kerneluser.
La restriction `false` s'active uniquement en contexte multi-user / BaaS.

**Conséquences directes de kerneluser :**

```
kerneluser: true  →  identityShow: on  (défaut owner — présence visuelle complète des agents)
                     kernel write : autorisé (avec confirmation humaine)
                     agents : complets (coach, secrets-guardian, tous)

kerneluser: false →  identityShow: off (défaut client — mode clean/pro)
                     kernel write : BLOCKED_ON
                     agents : scoped (rendering mode)
```

> `identityShow` n'est pas une bascule UI arbitraire — c'est une conséquence de `kerneluser`.
> Deux couches orthogonales : `kerneluser` = identité/UX, les scopes du token = accès/données.
> Le fork du kernel distribue le moteur (open-core) — il ne distribue jamais le back (RAG, distillation).

---

## Règles d'inviolabilité

1. **KERNEL.md lui-même** — jamais modifié par un agent seul. Toujours décision humaine.
2. **Profil Invariant** — jamais surchargé par une session de travail. Signal explicite requis.
3. **Un scribe = un territoire** — toolkit-scribe ne touche pas progression/. Jamais.
4. **Flux unidirectionnel** — satellite → kernel possible (promotion). Kernel → satellite = contamination.
5. **Session audit** — lecture seule sur toutes les zones. Jamais d'écriture directe.

---

## Chargement

```
helloWorld Couche 0 — invariant [toujours, avant tout agent] :
  KERNEL.md                ← loi des zones
  brain-constitution.md    ← invariants identité + protocoles Layer 0
  PATHS.md                 ← chemins machine
  profil/specs/collaboration.md  ← règles de travail
```

---

## Conventions agents — référence opérationnelle

Pour création/refonte d'agent, consulter `agents/_conventions.md` qui synthétise les ADRs architecturales fondatrices en checklist pratique :

- **BRAIN-065** — Doctrine modes intra-agent (A) vs sub-agents séparés (B)
- **BRAIN-066** — Convention register-ethics : 2 axes orthogonaux (registre variable + plancher éthique fixe)
- **BRAIN-067** — Pattern identity injection : cascade 4 niveaux (brain → identité → projet → mode)

Toutes les conventions sont **orthogonales et complémentaires** — elles s'appliquent ensemble, pas isolément.

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-14 | Création — zones typées, protection graduée, commit ownership, session→zone access |
| 2026-03-15 | brain-constitution.md ajouté — zone KERNEL Absolu, Chargement Couche 0 |
| 2026-03-16 | BRAIN-014 ancré — mapping zones BSI, règle délégation kernel human-only phase actuelle, kerneluser |
| 2026-03-16 | Isolation kernel — règle distribution, scripts kernel-lock-gen + kernel-isolation-check |
| 2026-03-18 | kerneluser → identityShow ancré — deux couches orthogonales : identité/UX vs accès/données |
| 2026-03-20 | BRAIN-044 — § Session type → zone access complété (15 types, 8 ajoutés) |
| 2026-03-29 | BRAIN-047 — Sessions V2 : 15 types → 4 (work/brain/explore/pilote). Zone access simplifié. V1 archivée. |
| 2026-04-24 | Conventions agents ajoutées — pointer vers `agents/_conventions.md` (triplet BRAIN-065/066/067 émergé en session pilote `sess-20260424-1438-pilote-drift-memoire`) |
| 2026-04-01 | Sessions V2 extension — 5ème type "chill" : présence longue durée, wrap OFF, coach mode "présent", transition work→chill. |
| 2026-09-07 | `learning` entre au registre : 6ᵉ type déclaré dans `CLAUDE.md` et `contexts/session-learning.yml` depuis le 18/05, absent de ce tableau. Zones reprises de son contexte, non inventées. |
