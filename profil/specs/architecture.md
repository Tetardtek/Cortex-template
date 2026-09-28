---
name: architecture
type: reference
context_tier: cold
---

# architecture.md — Mémoire des décisions fondatrices

> **Type :** Invariant — mémoire épisodique du brain
> Propriétaire : lecture seule — jamais modifié rétroactivement, uniquement enrichi
> Usage : brainstorm, content, compréhension du système par une nouvelle instance
>
> Rédigé : 2026-03-14 — pendant que c'est chaud.
> Les décisions non-évidentes, les pourquoi, les trade-offs assumés.
> Pour se souvenir dans 6 mois. Pour les gens qui fork.

---

## C'est quoi le brain

Un système de mémoire externe pour sessions Claude — persistent, versionné, multi-machine.

**Problème résolu :** Claude oublie entre les sessions. Le brain ne oublie pas.

**Ce que ça n'est pas :** un simple dossier de markdown. C'est un système avec des couches, des agents, des scribes, un protocole de coordination inter-sessions, et une logique de bootstrap.

---

## Les 3 couches — décision fondamentale

```
KERNEL      agents/, profil/
            Universel. Valable pour n'importe qui.
            Partagé entre toutes les instances via symlinks ou clone.
            → brain-template est le kernel exportable.

INSTANCE    focus.md, projets/, todo/, infrastructure/, PATHS.md
            Personnel à une machine / un contexte.
            Jamais dans le kernel. Jamais exporté tel quel.

PERSONNEL   progression/, capital.md
            Intime. Jamais partagé, jamais forké.
            Une personne, un repo, aucun export.
```

**Pourquoi 3 couches et pas 2 ?**
La ligne kernel/personnel est évidente. La couche instance est moins intuitive — elle existe parce qu'un même kernel peut tourner sur plusieurs machines avec des configs radicalement différentes (chemins, services, projets). Sans instance, on hardcode dans le kernel. Le kernel pollue. L'export devient impossible.

---

## Les repos satellites — décision architecture

Le brain n'est pas un monorepo. Chaque couche a son repo :

| Repo | Chemin local | Couche | Push vers |
|------|-------------|--------|-----------|
| `brain` | `brain/` — chemin réel dans `PATHS.md` | Kernel + instance | Gitea privé |
| `brain-profil` | `Docs/profil/` | Kernel (profil perso) | Gitea privé |
| `brain-todo` | `Docs/todo/` | Instance | Gitea privé |
| `brain-toolkit` | `Docs/toolkit/` | Instance (patterns) | Gitea privé |
| `brain-progression` | `Docs/progression/` | Personnel | Gitea privé |
| `brain-agent-review` | `Docs/reviews/` | Instance (audits) | Gitea privé |

Tous gitignorés dans `brain/` sauf leur propre `.git/`.

**Pourquoi des repos séparés ?**
- Rythme de commit différent : `todo/` change tous les jours, `profil/` change rarement
- Exportabilité granulaire : on peut partager `profil/` sans exposer `todo/` ou `progression/`
- Isolation des accès : un collaborateur peut avoir accès à `reviews/` sans voir `progression/`
- Chaque scribe commit dans son repo — responsabilité claire, historique lisible

---

## Le pattern `.env` du brain

Même logique qu'un projet dev :

```
brain-compose.yml          →  .env.example  (versionné, valeurs génériques)
brain-compose.local.yml    →  .env           (gitignored, valeurs machine réelles)
CLAUDE.md.example          →  .env.example  (versionné, template avec <PLACEHOLDERS>)
~/.claude/CLAUDE.md        →  .env           (non versionné, config live)
PATHS.md                   →  .env           (chemins réels de cette machine)
```

**La règle :** toute valeur qui change selon la machine vit dans un fichier gitignored ou dans le fichier local de la couche. Jamais hardcodée dans le kernel.

---

## Pourquoi helloWorld plutôt qu'un bootstrap statique

Le bootstrap statique (lire focus.md + tous les agents au démarrage) charge trop, charge à l'aveugle, ne s'adapte pas au contexte.

helloWorld fait mieux :

```
Bootstrap statique          helloWorld
─────────────────           ──────────────────────────
Charge tout au démarrage    Charge le minimum
Ignore le contexte          Détecte le type de session
Charge tout au démarrage    Charge ce que le type de session déclare
Ignore les signaux          Relève la boîte (CHECKPOINT) avant tout
Statique                    Adaptatif
```

**Trade-off assumé :** helloWorld est un agent comme les autres — il peut halluciner, rater un signal. Le bootstrap statique était déterministe. On a choisi l'adaptabilité sur la déterminisme, parce que le brain est devenu trop grand pour être chargé en entier à chaque session.

---

## BSI — Brain Session Index

Problème : plusieurs sessions en parallèle peuvent modifier les mêmes fichiers sans se voir.

Solution : des **claims** (qui travaille sur quoi, jusqu'à quand) et des **signaux** (messages entre sessions), **en base** — `claims`, `signals` et leurs archives (BRAIN-042). Ni fichier, ni commit : `BRAIN-INDEX.md` n'est plus qu'un aiguillage vers les commandes.

```
bsi-claim.sh   ouvrir / fermer / fermer les périmés    — chaque session tient le sien
bsi-query.sh   sessions ouvertes, périmées, peers
bsi-signal.sh  émettre, relever (inbox), accuser (ack)
```

**Optimiste + TTL :** on ne bloque pas, on déclare. Un recouvrement de scope est averti — refusé seulement en zone `kernel`. L'humain décide. Le TTL repoussé à chaque commit dit quand une session sans signe de vie devient suspecte.

**CHECKPOINT :** signal A→A. Une session se snapshote dans un handoff et se l'adresse ; après une coupure ou un compactage, la boîte le relève et la session reprend là où c'était. Spec complète : `bsi-spec.md` (v2).

---

## Session-as-identity — pourquoi pas de fork par rôle

Problème initial : plusieurs rôles en parallèle (build, review, test) → on forke un brain par rôle → explosion de configs.

Solution : le slug de session IS l'identité de routage.

```
sess-20260314-0900-build           →  rôle build
sess-20260314-0901-review          →  rôle review
sess-20260314-0902-test            →  rôle test
```

Un seul brain par machine. N sessions nommées. Les signaux se routent par `sess-id` (message direct) ou `brain_name@machine` (broadcast) — `bsi-signal.sh send`.

---

## Le Scribe Pattern — principe de non-contamination

Règle dure : un agent métier n'écrit jamais directement dans le brain.

```
Agent métier → signal → scribe compétent → write
```

Sans ça : chaque agent écrit partout → dérive garantie.
Avec ça : chaque scribe est le seul responsable de son territoire.

8 scribes, 8 territoires exclusifs. Voir `profil/specs/scribe-system.md` pour la carte complète.

---

## brain-template — le kernel exportable

`brain-template` = le kernel sans la couche instance et sans la couche personnelle.

```
brain-template/
  agents/       ← tous les agents universels (zéro valeur perso)
  profil/       ← profil universel (anti-hallucination, spec, patterns)
  BRAIN-INDEX.md ← aiguillage BSI (les données sont en base)
  brain-compose.yml ← spec versionnée
  PATHS.md      ← template avec <PLACEHOLDERS>
  focus.md      ← starter
  README.md     ← procédure d'installation complète
```

**Versioning :** semver `v0.x.x` — kernel en évolution. `v1.0.0` quand l'interface est contractuelle.
**Distribution :** repo Gitea privé aujourd'hui. GitHub public quand v1.0.0 validé.

---

## Ce qui n'est pas dans ce doc

- Comment créer un agent → `agents/_template.md`
- Comment les scribes fonctionnent → `profil/specs/scribe-system.md`
- La spec BSI complète → `profil/specs/bsi-spec.md`
- Les patterns d'orchestration → `profil/specs/orchestration-patterns.md`
- Les règles de collaboration → `profil/specs/collaboration.md`

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-14 | Création — première ARCHITECTURE.md du brain, décisions non-évidentes documentées pendant que c'est chaud |
