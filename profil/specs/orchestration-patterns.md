---
name: orchestration-patterns
type: reference
context_tier: cold
---

# Patterns d'orchestration

> **Type :** Contexte — propriétaire : `orchestrator-scribe`
> Mis à jour en fin de session quand un pattern récurrent est identifié.

---

## Pattern 1 — Sessions parallèles sur une machine (session-as-identity)

**Problème :** plusieurs agents travaillent en parallèle sur la même machine → même `brain_name@machine` → orchestrator-scribe ne peut pas distinguer qui cibler.

**Solution :** le slug du session ID EST l'identité de routage. Pas besoin de forker un brain par rôle.

```
Format : sess-YYYYMMDD-HHMM-<role>        (sans @machine — l'identifiant suffit)

Exemples :
  sess-20260314-0900-build     → produit du code
  sess-20260314-0901-review    → review en parallèle
  sess-20260314-0902-test      → tests en parallèle
```

> Réécrit le 27/09 sur le BSI réel : claims et signaux sont en base, pas dans
> `BRAIN-INDEX.md` — voir `bsi-spec.md` v2.

**Procédure :**

```
1. Chaque session ouvre son claim au boot (helloWorld), rôle dans le slug :
   bsi-claim.sh open sess-20260314-0900-build --scope agents/ --type work

2. Envoyer un signal ciblé (pas broadcast) :
   bsi-signal.sh send sess-20260314-0901-review --type READY_FOR_REVIEW \
                 --payload "agents/security.md"

3. La session review le relève — au boot, et avant chaque message (hook) :
   bsi-signal.sh inbox → "READY_FOR_REVIEW de sess-…-build : agents/security.md"
```

**Règle de routage :**

| Cible de `send` | Comportement |
|---------------|-------------|
| `brain_name@machine` | Broadcast — toutes sessions actives de cette instance |
| `sess-YYYYMMDD-HHMM-<role>` | Message direct — une session précise |

**Anti-pattern :**
- ❌ Ne pas forker un nouveau brain pour chaque rôle → explosion de configs
- ❌ Ne pas cibler `brain_name@machine` quand on veut une session précise → broadcast non désiré
- ✅ Un brain par machine, N sessions nommées par rôle

---

## Pattern 2 — Cycle coworking inter-machines

**Problème :** une session produit du travail sur desktop, une autre doit le reviewer sur laptop sans communication manuelle.

**Solution :** signal READY_FOR_REVIEW (`bsi-signal.sh send`) → la session review le relève chez le peer qui l'a émis (`inbox`), au démarrage.

```
prod@desktop  →  travaille sur <fichier>
               →  ferme claim
               →  signal READY_FOR_REVIEW → template-test@laptop (ou sess-id précis)

template-test@laptop  →  démarre, bsi-signal.sh inbox (ici ET chez les peers)
                       →  relève le signal adressé à son instance
                       →  "Signal reçu : READY_FOR_REVIEW sur <fichier>"
                       →  ouvre claim review
                       →  audite → écrit dans reviews/<fichier>.md
                       →  ferme claim
                       →  signal REVIEWED → prod@desktop

prod@desktop  →  watchdog lit REVIEWED
               →  lit reviews/<fichier>.md
               →  intègre ou ignore → continue
```

**Quand l'utiliser :**
- Review de code sensible (sécurité, auth, archi)
- Validation d'un agent forgé avant de l'intégrer dans brain-template
- Tout workflow "produit → valide → intègre"

---

## Pattern 3 — HANDOFF — session longue découpée

**Problème :** session longue à couper (fin de journée, changement de machine) sans perdre le contexte.

**Solution :** signal HANDOFF avec payload précis → la session cible reprend exactement au bon endroit.

```
sess-20260314-1800-build@desktop  →  point d'arrêt naturel atteint
                                   →  signal HANDOFF → prod@laptop
                                   →  payload : "reprendre agents/security.md à ## Périmètre"

prod@laptop  →  watchdog détecte HANDOFF
              →  charge agents/security.md, position ## Périmètre
              →  continue sans perte de contexte
```

**Payload HANDOFF — format recommandé :**
```
"reprendre <fichier> à <## Section> — contexte : <1 ligne résumé>"
```

---

## Pattern 4 — Audit avant prod (triple-session)

**Problème :** feature sensible → besoin de review code + security + tests avant merge.

**Solution :** session build produit → 3 sessions d'audit en parallèle → résultats consolidés.

```
sess-YYYYMMDD-HHMM-build@desktop  →  feature terminée
  →  signal READY_FOR_REVIEW → sess-HHMM-review@desktop   (code quality)
  →  signal READY_FOR_REVIEW → sess-HHMM-security@desktop (OWASP, auth)
  →  signal READY_FOR_REVIEW → sess-HHMM-test@laptop       (coverage)

Chaque session audite, écrit dans reviews/
  →  signal REVIEWED → build@desktop

build@desktop reçoit 3× REVIEWED → consolide → merge
```

---

## Pattern 5 — CHECKPOINT — arrêt naturel et reprise sans perte

**Problème :** session longue → compactage LLM, coupure réseau, pause humaine → contexte perdu, reprise hasardeuse.

**Solution :** un handoff écrit dans `handoffs/` (persisté dans git) et un signal `CHECKPOINT` que la session s'adresse à elle-même (en base) — indépendant du contexte LLM.

**Déclencheurs :**
- Utilisateur : `checkpoint` / `/checkpoint` / `pose un checkpoint`
- Scribe (auto) : breakpoint naturel après un item important terminé en session longue
- Fin de session sans fermeture propre prévue

**Procédure — poser un checkpoint :**

```
User : "checkpoint"

orchestrator-scribe :
1. Collecter avec scribe :
   - Tâche en cours  : <ce qu'on faisait>
   - Fichiers touchés: <git diff --name-only depuis ouverture claim>
   - Commits         : <git log --oneline --since="<ouvert le>">
   - Prochaine étape : <actionnable, précis — "reprendre X à ## Section Y">
   - Contexte non-git: <décisions, intentions pas encore commitées>

2. Écrire le résumé structuré dans handoffs/<fichier>.md, puis :
   bsi-signal.sh send <sess-id de cette session> --type CHECKPOINT \
                 --payload "→ handoffs/<fichier>.md"

3. Confirmer : "Checkpoint posé — reprise depuis : <prochaine étape>"
4. L'utilisateur peut fermer la session proprement.
```

**Procédure — reprendre après un checkpoint :**

```
Nouvelle session démarre — watchdog scribe :
1. bsi-signal.sh inbox — les CHECKPOINT adressés à cette session ou instance
2. Afficher AVANT tout autre action :
   "Checkpoint détecté [date]
    Tâche en cours  : <...>
    Prochaine étape : <...>
    Commits posés   : <...>"
3. Demander : on reprend depuis ce point ?
4. Oui → bsi-signal.sh ack <sig_id> → continuer depuis <prochaine étape>
5. Non → ignorer, session normale
```

**Pourquoi c'est robuste :**
- Le handoff est dans git, le signal en base → survit au compactage LLM, au redémarrage, au changement de machine (le signal se relève chez le peer)
- Après un compactage, l'identité de session peut changer : le hook de la boîte rattache alors son claim à la nouvelle (filiation écrite par Claude Code), et les signaux adressés à la session sont de nouveau relevés
- Format structuré → le LLM relit un état propre, pas une mémoire dégradée
- `git log` dans le payload → audit trail complet de ce qui a été fait

---

## Ajout de patterns

Invoquer `orchestrator-scribe` en fin de session si un workflow récurrent a été identifié :
```
orchestrator-scribe, capture ce pattern dans orchestration-patterns.md
```

---

## Pattern 6 — HumanSupervisor — décision minimale

> 🗄️ **Archivé le 30/09 (BRAIN-079)** : ce pattern repose sur l'agent `supervisor`,
> archivé avec l'ancienne machinerie (`agents/archive/`) — elle n'a jamais tourné en base.
> Le lancement et la supervision d'agents passent par le palier c : l'`orchestrator`
> compose et juge, un worker travaille dans son worktree, `dev/autonome` accueille.

> Validé en prod : sess-20260314-1920-supervisor — 2026-03-14
> Contexte : sprint dual-agent d'un projet (back + front) supervisé depuis une fenêtre dédiée

**Principe : extraire la logique d'exécution pour ne laisser à l'humain que les bifurcations décisionnelles.**

```
Exécution déterministe   → agents autonomes (pas de remontée)
  bug connu + pattern    → fix direct
  signal BSI             → trigger automatique
  close session          → séquence scribe auto
  validation routes      → back lit le code front, pas la spec

Points de décision humaine (ce qui remonte au superviseur)
  → Priorisation        : "Sprint 2 ou fix d'abord ?"
  → Architecture        : "Ce choix a des conséquences long terme ?"
  → Arbitrage scope     : conflit entre deux sessions parallèles
  → Validation prod     : deploy = toujours humain
```

**Structure de la session supervisor :**

```
Fenêtre supervisor  →  claim BSI type supervisor
                        lit les signaux, pas le code
                        coach intervient sur les bifurcations
                        3 interventions max sur un sprint de 4h
                        ferme en dernier (après les sessions de travail)
```

**Ce que le sprint du 2026-03-14 a mesuré :**
- 3 interventions humaines sur ~4h de travail dual-agent
- Bug super_admin trouvé par le back en lisant le code front (audit externe)
- Ratio métabolisme 1.0 — équilibré build-brain / use-brain

**Règle : minimum viable human input**
```
Si une décision peut être prise sans connaître la stratégie globale → agent
Si une décision change la direction du projet ou l'architecture → humain
```

**Anti-pattern :**
- ❌ Supervisor qui relit chaque ligne de code — c'est du micro-management
- ❌ Agents qui remontent chaque étape pour validation — ça annule le gain
- ✅ Agents qui remontent uniquement les blocages ou les ambiguïtés réelles
- ✅ Supervisor qui répond en 1 phrase, pas en spec complète

**Connexion brain :**
→ `brain-compose.yml` : mode `human-supervisor` à créer (todo capturé)
→ `motor-spec.md` : motor_level définit ce qui est autonome vs ce qui remonte
→ `session-orchestrator` : close sequence = exemple d'exécution déterministe

---

## Pattern 7 — Todo → KANBAN Sprint Setup

> 🗄️ **Archivé le 30/09 (BRAIN-079)** : ce pattern repose sur l'agent `supervisor`,
> archivé avec l'ancienne machinerie (`agents/archive/`) — elle n'a jamais tourné en base.
> Le lancement et la supervision d'agents passent par le palier c : l'`orchestrator`
> compose et juge, un worker travaille dans son worktree, `dev/autonome` accueille.

> Forgé : 2026-03-15
> Contexte : audit d'un projet — première application

**Problème :** un todo structuré existe, mais passer du todo à l'exécution demande de reformuler à la main les prompts de chaque agent à chaque sprint.

**Solution :** le supervisor lit le todo, extrait les tâches, génère un KANBAN dans `workspace/<sprint>/kanban.md` — chaque carte a un **prompt prêt à coller** dans une session agent.

---

### Convention todo "supervisor-parseable"

Pour qu'un todo soit lisible par le supervisor, chaque tâche doit avoir :

```markdown
## ⬜ Titre de la tâche

> Agents : agent-lead (lead) + agent2
> Input  : <chemin ou référence>
> Output : <fichier de sortie>
> Prérequis : <tâche précédente ou "aucun">

Description courte de l'intention.
```

---

### Format KANBAN — workspace/<sprint>/kanban.md

```markdown
# KANBAN — <sprint-id>

## TODO
- [ ] **Carte** — Agent: X
  Input  : Y
  Output : Z
  Prompt : `Charge l'agent X — [brief complet prêt à coller]`

## IN PROGRESS
...

## DONE
...
```

---

### Rôle du supervisor en sprint setup

```
1. Lire le fichier todo (structuré)
2. Extraire les tâches : agent, input, output, prérequis
3. Trier par dépendances (ordre topologique)
4. Générer une carte KANBAN par tâche avec prompt complet
5. Créer workspace/<sprint-id>/kanban.md
6. Ouvrir le claim BSI type supervisor
7. Human envoie les prompts carte par carte (ou en parallèle si pas de dépendance)
```

### Règles

```
Prompt de carte  → suffisant pour démarrer la session sans relire le todo
Parallélisme     → cartes sans dépendance communes peuvent être envoyées en même temps
Avancement       → [ ] → [x] au fil des sessions, commit kanban.md après chaque carte
Close sprint     → integrator consolide les outputs → rapport final
```

**Anti-pattern :**
- ❌ Prompt de carte trop court ("audite le projet") → agent manque de contexte
- ❌ Tout en parallèle sans vérifier les dépendances → résultats incohérents
- ✅ Prompt autonome : l'agent peut démarrer sans rien relire d'autre
- ✅ Output explicite : chaque carte sait où écrire son résultat

---

## Pattern 8 — Context Compact Checkpoint

> Forgé : 2026-03-15
> Problème : bootstrap complet (~1000 lignes) requis après compactage ou reprise.
> Spec complète : `toolkit/brain/checkpoint-pattern.md`

**Commande :** l'humain dit `/checkpoint` → Claude écrit `handoffs/<fichier>.md` (depuis `handoffs/_template.md`) et envoie un signal `CHECKPOINT` qui pointe ce fichier — corrigé le 30/09 : l'ancienne adresse, `workspace/<sprint>/checkpoint.md`, est morte avec les sprints

```
Cold bootstrap  →  5 fichiers + brain complet  →  ~1000 lignes  →  2-3 min
Warm restart    →  1 fichier checkpoint         →  ~30-50 lignes →  < 30 sec
```

**Template minimal :**
```markdown
## Focus         — ce qu'on fait (1 ligne)
## Dernier livrable — ce qui vient d'être fait (1-2 lignes)
## Prochain step — action exacte à reprendre (1 ligne)
## Fichiers actifs — seulement ce qui est nécessaire
## Contexte compact — ≤ 8 lignes, tout ce que Claude doit savoir
```

**Warm restart prompt :**
```
Lis brain/handoffs/<fichier>.md et reprends — pas de bootstrap complet.
```

**Règles :**
- Un point de reprise par travail en cours (mis à jour à chaque `/checkpoint`)
- Prochain step doit être assez précis pour agir sans relire
- Contexte compact ≤ 8 lignes — si ça dépasse, c'est trop
- Le checkpoint ne remplace pas le claim BSI (locking ≠ contenu)
