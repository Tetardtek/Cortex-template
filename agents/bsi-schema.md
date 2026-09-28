---
name: bsi-schema
type: reference
context_tier: cold
domain: brain
status: active
description: '**Source unique du schema claim BSI versionné dans git.**'
brain:
  version:   1
  type:      spec
  scope:     kernel
  owner:     human
  lifecycle: permanent
  read:      full
  triggers:  []
  ipc:
    # TODO: valider — bsi-schema est une spec/référence, pas un agent actif
    receives_from: []
    sends_to:      []
    zone_access:   [kernel]
    signals:       []
---

# BSI Schema — Claim v1.3

> **Source unique du schema claim BSI versionné dans git.**
> Protocole d'utilisation → `agents/satellite-boot.md`
> Spécification complète (contexte, TTL, signals) → `profil/specs/bsi-spec.md` (local, privé)
> Registre live → la base (`bsi-query.sh`) — `BRAIN-INDEX.md` n'est plus qu'un aiguillage

---

## Tous les champs d'un claim

```yaml
# ── Champs obligatoires ────────────────────────────────────────────
sess_id:       sess-YYYYMMDD-HHMM-<slug>   # Identifiant unique de session
type:          pilote | satellite | solo    # Rôle de la session
scope:         <chemin/>                   # Dossier ou fichier concerné (ex: agents/ ou agents/foo.md)
agent:         <nom-agent>                 # Agent principal chargé (ex: helloWorld, satellite-boot)
status:        open | closed | stale       # État courant
opened_at:     "YYYY-MM-DDTHH:MM"         # ISO 8601 local

# ── Champs optionnels — tous ───────────────────────────────────────
handoff_level: <int>                       # Profondeur de handoff (0 = session fraîche)
story_angle:   <texte court>               # Angle narratif / description de la tâche

# ── Champ multi-user (v2.3) — optionnel, prêt pour BaaS ───────────
# Absent = kerneluser implicite (brain owner, usage solo actuel).
# Présent = identité explicite — filtrage des claims, isolation zone:personal.
# Convention : identifiant stable, pas de PII (username ou uuid opaque).
#
# user_id: <username | uuid>   # ex: alice | client-42

# ── Champs optionnels — satellite uniquement (v1.3) ────────────────
satellite_type:  code | brain-write | test | deploy | search | domain
satellite_level: leaf | domain             # Absent = leaf par défaut
parent_satellite: <sess-id>               # Lien vers pilote ou coordinateur parent

# ── Champ calculé — close tier (v1.4, lecture seule) ───────────────
# close_tier est INFÉRÉ automatiquement — ne pas écrire dans le claim.
# Tier 1 Atomic      : leaf + satellite_type ∉ {code, test}
# Tier 2 Validated   : leaf + satellite_type ∈ {code, test}
# Tier 3 Orchestrated: satellite_level=domain OU type=pilote
# Protocole complet → agents/satellite-boot.md ## Close satellite — protocole tiered

# ── Champs workflow (v1.9) — générés par workflow-launch.sh ───────
# workflow:         <theme-name>     # nom du workflow source
# workflow_step:    <int>            # numéro du step dans la chaîne
# Ces champs permettent de tracer la position d'un satellite dans sa chaîne.
# Workflow schema → workflows/_template.yml
# Lancer le prochain step : bash scripts/workflow-launch.sh workflows/<theme>.yml

# ── Mode rendering — instance autonome projet (v2.0) ──────────────
# Déclaré dans le claim pilote pour activer le mode rendering de brain-compose.
# Active : scope_lock (zone:project uniquement), circuit_breaker (3 fails → BLOCKED_ON),
#          et mutex BSI-v3-7 (file-lock.sh) avant chaque écriture.
#
# mode: rendering
# scope: <repo-projet>/   ← seul périmètre autorisé — toute sortie = BLOCKED_ON immédiat
#
# Avant chaque écriture fichier :
#   bash scripts/file-lock.sh acquire "<filepath>" "$sess_id" 30
#   [écriture]
#   bash scripts/file-lock.sh release "<filepath>" "$sess_id"

# ── BSI-v3-7 — Mutex fichier (v2.0) ───────────────────────────────
# Empêche deux satellites d'écrire simultanément dans le même fichier.
# Registre : locks/<filepath-normalized>.lock
# Usage    : scripts/file-lock.sh acquire|release|check|list|cleanup
#
# Format lock :
#   file: <filepath>
#   holder: <sess_id>
#   claimed_at: YYYY-MM-DDTHH:MM
#   expires_at: YYYY-MM-DDTHH:MM
#   ttl_min: <N>   (défaut: 60)
#
# Exit codes : 0=ok, 1=déjà locké (attendre), 2=release refusé (mauvais holder)
# Comportement rendering : lock expiré → acquisition auto + log ⚠️

# ── Champ optionnel — theme branch (v1.8) ─────────────────────────
# Branche git sur laquelle tous les satellites de ce thème commitent.
# Convention : theme/<nom>  (ex: theme/brain-engine-be6)
# Créer la branche : bash scripts/theme-branch-open.sh <nom>
# Merger sur main  : bash scripts/theme-branch-merge.sh <nom>
#
# theme_branch: theme/<nom>   # absent = main (défaut)

# ── Champs optionnels — exit triggers (v1.7) ──────────────────────
# Déclarés au lancement du satellite — lus au close par le pilote (aujourd'hui)
# puis par kernel-orchestrator (BSI-v3-9).
#
# on_done:    <action>   # result.status = ok
# on_partial: <action>   # result.status = partial
# on_fail:    <action>   # result.status = failed
#
# Actions disponibles :
#   trigger → type:<satellite_type> scope:<scope>   # lancer le satellite suivant
#   signal  → <TYPE> <destinataire>                 # envoyer un signal BSI
#   gate:human → "<message>"                        # pause — confirmation humaine requise
#   notify  → <destinataire>                        # INFO signal, pas de blocage
#
# Exemples :
#   on_done:    trigger → type:test    scope:brain-engine/
#   on_partial: signal  → CHECKPOINT   pilote
#   on_fail:    signal  → BLOCKED_ON   pilote
#   on_done:    gate:human → "tests verts — deploy ?"
#
# Règles :
#   - on_done/on_partial/on_fail sont tous optionnels
#   - Si absent : comportement par défaut = signal CHECKPOINT pilote si pilote_id fourni
#   - gate:human suspend la chaîne — le pilote confirme avant que l'action suivante s'exécute
#   - Exécution actuelle : manuelle (pilote lit les triggers au close du satellite)
#   - Exécution future   : automatique (kernel-orchestrator, BSI-v3-9)

# ── Champ result — ajouté au close uniquement (v1.6) ──────────────
# Écrit par le satellite au moment du close — jamais au boot.
# Tier 1 Atomic :
#   result:
#     status:         ok | partial | failed
#     files_modified: [<chemin>, ...]
#     commit:         <hash 7 chars>
#     signal_id:      <sig-id> | null
#
# Tier 2 Validated (+ tests) :
#   result:
#     status:         ok | partial | failed
#     files_modified: [<chemin>, ...]
#     tests:
#       total:  <int>
#       passed: <int>
#       failed: <int>
#     commit:         <hash 7 chars>
#     signal_id:      <sig-id> | null
#
# Tier 3 Orchestrated (+ enfants agrégés) :
#   result:
#     status:         ok | partial | failed
#     children:       [<sess-id>, ...]
#     files_modified: [<chemin>, ...]
#     commit:         <hash 7 chars>
#     signal_id:      <sig-id> | null
#     notes:          <texte libre optionnel>
#
# status: partial = livrable sorti mais incomplet — le pilote route différemment de ok/failed

# ── Champ calculé — zone (v1.5, lecture seule) ─────────────────────
# zone est INFÉRÉ depuis scope — ne pas écrire dans le claim.
# zone: kernel   → agents/, profil/, scripts/, KERNEL.md, brain-constitution.md, brain-compose.yml
# zone: project  → todo/, projets/, workspace/, handoffs/, infrastructure/, <repo-projet>/
# zone: personal → profil/capital.md, profil/objectifs.md, progression/, MYSECRETS
# Règle d'autorisation → profil/decisions/014-zone-aware-bsi-kerneluser.md
```

---

## Valeurs valides par champ

### `type`

| Valeur | Description |
|--------|-------------|
| `pilote` | Session principale, contexte riche, décisions architecturales. Boot via `helloWorld`. |
| `satellite` | Session focalisée, scope unique, tâche déléguée. Boot via `satellite-boot`. |
| `solo` | Session autonome sans pilote — ni pilote ni satellite. |

### `status`

| Valeur | Condition | Transition |
|--------|-----------|------------|
| `open` | Session active | → `closed` (close propre) ou `stale` (TTL expiré) |
| `closed` | Fermée proprement | Terminal |
| `stale` | TTL expiré sans fermeture | → suppression après contrôle humain |

### `satellite_type`

| Valeur | Nature des modifications |
|--------|--------------------------|
| `code` | Code source d'un projet (hors brain/) |
| `brain-write` | Fichiers brain : agents/, projets/, profil/, todo/, wiki/ |
| `test` | Écriture ou exécution de tests |
| `deploy` | Déploiement, ops, VPS, CI/CD, infra |
| `search` | Audit, exploration, lecture seule ou quasi |
| `domain` | Coordinateur de sous-domaine — peut lancer des satellites leaf |

### `satellite_level`

| Valeur | Comportement |
|--------|-------------|
| `leaf` | *(défaut)* Tâche atomique. Ne lance pas de sous-satellites. |
| `domain` | Coordinateur. Peut déléguer à des satellites leaf via `parent_satellite`. |

### `close_tier` (inféré — non écrit dans le claim)

| Tier | Condition | Comportement au close |
|------|-----------|-----------------------|
| **Tier 1 — Atomic** | leaf + satellite_type ∉ {code, test} | Commit + close claim + signal retour |
| **Tier 2 — Validated** | leaf + satellite_type ∈ {code, test} | Tests verts requis → commit + close + signal |
| **Tier 3 — Orchestrated** | satellite_level=domain OU type=pilote | Attendre enfants fermés → agréger → close |

---

## Matrice de conflit `satellite_type × satellite_type`

> Deux satellites concurrent sur le même scope. **Bloque** = le second doit attendre ou choisir un scope non-overlapping.

| ↓ actif \ entrant → | `code` | `brain-write` | `test` | `deploy` | `search` | `domain` |
|---------------------|--------|---------------|--------|----------|----------|----------|
| `code`              | ⚠️ Bloque | — | ⚠️ Bloque | ⚠️ Bloque | ✅ OK | ⚠️ Bloque |
| `brain-write`       | — | ⚠️ Bloque | — | — | ✅ OK | ⚠️ Bloque |
| `test`              | ⚠️ Bloque | — | ⚠️ Bloque | ⚠️ Bloque | ✅ OK | ⚠️ Bloque |
| `deploy`            | ⚠️ Bloque | — | ⚠️ Bloque | ⚠️ Bloque | ✅ OK | ⚠️ Bloque |
| `search`            | ✅ OK | ✅ OK | ✅ OK | ✅ OK | ✅ OK | ✅ OK |
| `domain`            | ⚠️ Bloque | ⚠️ Bloque | ⚠️ Bloque | ⚠️ Bloque | ✅ OK | ⚠️ Bloque |

**Règles :**
- `search` ne modifie pas les fichiers → jamais bloquant, jamais bloqué
- Deux `brain-write` sur des fichiers **différents** dans le même dossier → pas de conflit (granularité fichier)
- Deux `brain-write` sur le même fichier → conflit direct
- `domain` vs `domain` → conflit systématique (coordinateurs parallèles sur même scope = risque élevé)

---

## Exemples de claims complets

### Claim pilote

```yaml
sess_id:       sess-20260316-2036-pilote-be5-wrap
type:          pilote
scope:         brain-engine/
agent:         helloWorld
status:        open
opened_at:     "2026-03-16T20:36"
handoff_level: 0
story_angle:   "Pilote BE-5 wrap — claim close, README commit, suite satellite-boot-loader + BE-5e"
```

### Claim satellite leaf

```yaml
sess_id:          sess-20260316-2046-bsi-v3-1
type:             satellite
scope:            agents/
agent:            satellite-boot
status:           closed
opened_at:        "2026-03-16T20:46"
handoff_level:    0
story_angle:      "BSI-v3-1 — ajouter satellite_type, satellite_level, parent_satellite dans le schema BSI claim"
satellite_type:   brain-write
satellite_level:  leaf
parent_satellite: sess-20260316-2036-pilote-be5-wrap
```

### Claim satellite avec exit triggers (v1.7)

```yaml
sess_id:          sess-20260316-2145-brain-engine-code
type:             satellite
scope:            brain-engine/
agent:            satellite-boot
status:           open
opened_at:        "2026-03-16T21:45"
story_angle:      "Implémenter BE-6 feature X"
satellite_type:   code
satellite_level:  leaf
parent_satellite: sess-20260316-2036-pilote-be5-wrap
on_done:          trigger → type:test scope:brain-engine/
on_partial:       signal  → CHECKPOINT pilote
on_fail:          signal  → BLOCKED_ON pilote
```

*Au close, si result.status=ok → lance automatiquement un satellite test sur brain-engine/.*
*Si failed → signal BLOCKED_ON vers le pilote, chaîne suspendue.*

### Claim satellite domain (coordinateur)

```yaml
sess_id:          sess-20260316-2100-mon-api-domain
type:             satellite
scope:            mon-api/
agent:            satellite-boot
status:           open
opened_at:        "2026-03-16T21:00"
handoff_level:    0
story_angle:      "Coordonne les satellites leaf mon-api (audit + tests + deploy)"
satellite_type:   domain
satellite_level:  domain
parent_satellite: sess-20260316-2036-pilote-be5-wrap
```

*Un satellite leaf lancé par ce domain déclare `parent_satellite: sess-20260316-2100-mon-api-domain`.*

---

## Changelog

| Date | Version | Changement |
|------|---------|------------|
| 2026-03-16 | 1.3 | Création — schema complet, matrice de conflit, exemples pilote + leaf + domain |
| 2026-03-16 | 1.4 | BSI-v3-5 — close_tier inféré (Atomic/Validated/Orchestrated) documenté dans schema |
| 2026-03-16 | 1.5 | BRAIN-014 — zone inféré (kernel/project/personal) + modèle kerneluser |
| 2026-03-16 | 1.6 | BSI-v3-2 — champ result: au close (status, files, tests, children, signal_id) |
| 2026-03-16 | 1.7 | BSI-v3-3 — exit triggers : on_done/on_partial/on_fail + actions trigger/signal/gate:human/notify |
| 2026-03-16 | 1.8 | BSI-v3-6 — theme_branch : theme/<nom>, scripts theme-branch-open/merge |
| 2026-03-16 | 1.9 | BSI-v3-4 — workflow_step + workflow : champs claim générés par workflow-launch.sh |
| 2026-03-16 | 2.0 | BSI-v3-7 — mutex fichier + mode:rendering : file-lock.sh, locks/, rendering mode claim |
| 2026-03-16 | 2.1 | BSI-v3-8 — pre-flight check : 6 conditions (claim/scope/zone/lock/circuit-breaker/branch), kerneluser bypass |
| 2026-03-16 | 2.2 | BSI-v3-5 — statuts waiting_human/paused, cascade pause/resume/abort, gate_history dans claim |
| 2026-03-16 | 2.3 | Multi-user BaaS — champ user_id optionnel ancré (absent = kerneluser implicite) |
