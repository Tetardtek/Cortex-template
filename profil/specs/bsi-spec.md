---
name: bsi-spec
type: reference
context_tier: cold
---

# BSI — Brain Session Index

> **Type :** Contexte — spécification du BSI tel qu'il tourne
> Version 2.0 — réécrite le 2026-09-27 sur le code et la base
> Métier : `core/bsi.py` (CORE Myéline) · Portes : `scripts/bsi-claim.sh`,
> `scripts/bsi-query.sh`, `scripts/bsi-signal.sh`, route `/bsi/claims` du moteur
> Aiguillage : `BRAIN-INDEX.md`
>
> La v1 (14/03) décrivait un registre markdown tenu à la main par le scribe
> dans `BRAIN-INDEX.md` et un dossier `claims/` versionné. Les deux ont disparu
> le 19/03 (BRAIN-042) ; la v1 est restée six mois la seule description
> complète du BSI, d'un monde qui n'existait plus. Elle est dans l'historique
> git de ce fichier.

---

## Problème résolu

Plusieurs sessions en parallèle — sur une machine, ou sur plusieurs — peuvent
modifier les mêmes fichiers sans se voir. Le BSI ne résout pas les conflits git ;
il **rend les sessions visibles les unes des autres** avant qu'elles écrivent au
même endroit, et leur donne un canal pour se parler.

Deux objets :

| Objet | Dit | Table |
|---|---|---|
| **claim** | qui travaille, sur quoi, depuis quand, jusqu'à quand | `claims` → `claims_archive` |
| **signal** | un message d'une session ou instance à une autre | `signals` → `signals_archive` |

S'y ajoutent les **verrous de fichier** (`locks`), plus fins et plus courts.

---

## Où vit le BSI — la base, pas git

**La base est la source unique** (BRAIN-036, BRAIN-042) : `brain.db` en SQLite,
ou la base Dolt, selon `BRAIN_DB_BACKEND`. Ouvrir, fermer, émettre, relever :
**ni fichier, ni commit, ni push.**

`BRAIN-INDEX.md` n'est plus un registre : c'est un **aiguillage** vers les
commandes. Il n'a aucune section à scanner ni à remplir. Un texte qui demande
de « lire `## Claims actifs` », d'« écrire dans `## Signals` » ou de lire un <!-- bsi-v1 -->
`claims/<…>.yml` décrit la v1. <!-- bsi-v1 -->

Même chose pour `workspace/live-states.md` : il est **généré** par
`bsi-peer-poll.sh` (toutes les 5 minutes) depuis les claims, ceux d'ici et ceux
des peers. On ne l'édite jamais.

---

## Stratégie : optimiste + TTL

- **Optimiste** — on déclare son intention, on détecte les recouvrements, on
  alerte. On ne bloque qu'en zone `kernel`.
- **TTL** — une session morte ne doit pas occuper un scope indéfiniment. Mais le
  TTL n'est **pas une limite de travail** : il dit au bout de combien de temps
  **sans signe de vie** un claim devient suspect.

Jamais d'auto-libération sur une action destructive : l'humain tranche.

---

## Le claim

### Identifiant

```
sess-YYYYMMDD-HHMM-<slug>        ex. sess-20260927-0930-pilote-brain
```

Validé par le CORE : `^sess-[0-9A-Za-z][\w.-]*$`. Un identifiant non conforme
est **refusé** — un appel mal analysé avait enregistré des claims sous le nom de
leur option (`--type`, `pilote`).

Le slug porte le type et le scope de la session. **L'heure est en UTC**, comme
tout le BSI.

### Instance

```
<brain_name>@<machine>           ex. prod@desktop
```

Lue dans `brain-compose.local.yml` par `scripts/lib/instance.py`, qui **se
plaint** si elle ne peut pas la lire — plutôt que rendre `inconnue@inconnue` et
relever une boîte qui n'existe pas.

### Identité de session — BRAIN-077

Le claim porte `agent_session` : l'identifiant de la session d'agent qui l'a
ouvert (`CLAUDE_CODE_SESSION_ID` sous Claude Code ; nom neutre, un fork peut
tourner avec un autre agent). Il permet :

- `bsi-claim.sh close` **sans argument** : ferme le claim de CETTE session ;
- de **refuser** la fermeture du claim d'une autre session (code 409, ou
  `ClaimDUneAutreSession`) — sauf `--pas-le-mien`, levée nommée ;
- à la boîte de relever les signaux adressés à la session.

Le refus ne joue qu'entre deux identités **connues et différentes** : sans
identité (shell humain, cron, `close-stale`), rien ne change.

**Une session reprise garde son claim.** L'identité peut changer au cours
d'une même conversation : parquée puis reprise dans un autre processus (observé
avec un compactage), la session en reçoit une neuve, et son claim porte
l'ancienne — pour le BSI, « celui d'une autre session ». Claude Code écrit la
filiation : le fichier de l'ancienne session (`~/.claude/sessions/<pid>.json`)
porte `parkedJobId`, préfixe de la nouvelle identité. `scripts/lib/filiation.py`
la suit ; `BSI.rattache()` (CORE) fait passer les claims OUVERTS de l'ancienne
identité à la nouvelle. Le hook de la boîte le fait tout seul quand aucun claim
ne porte la session, et l'annonce ; `bsi-claim.sh rattacher` est le même geste
à la main. Sans filiation lisible, rien n'est rattaché — et c'est dit. Ces
fichiers sont internes à Claude Code : leur format peut changer.

### Cycle de vie

| Statut écrit | Signifie |
|---|---|
| `open` | la session travaille |
| `closed` | fermée — le **résultat** dit comment (`success`, `partial`, `stale-auto-closed`, `transitioned-to-<type>`…) |

L'enum de la colonne déclare aussi `stale`, `paused`, `waiting_human` et
`failed` ; **aucun n'a jamais été écrit**. « Stale » est une **lecture**, pas
un état : un claim `open` dont l'expiration est dépassée.

```
ouvrir   bsi-claim.sh open <sess-id> --scope X --type T --zone Z --ttl H
vivre    chaque commit de la session repousse l'expiration de SES claims
         (post-commit → bsi-claim.sh touch, par l'identité de session) ;
         sans identité, rien n'est repoussé — on ne sait pas qui vit
fermer   bsi-claim.sh close [<sess-id>] --result R [--energy …] [--intention …]
```

- **Ouvrir** : helloWorld au boot. Une session = un claim ; elle naît avec lui
  (la ligne `sessions` est dérivée).
- **Fermer** : session-orchestrator à la clôture — même sur `/exit`.

### TTL

Le TTL vient du manifeste du type de session, `contexts/session-<type>.yml`
(`ttl_hours`) — jamais d'une valeur écrite ailleurs. Défaut du CORE : 4 h.

**L'expiration se mesure depuis `expires_at`, pas depuis l'ouverture** : une
session longue n'est pas un oubli. Et **en UTC des deux côtés** :
`opened_at` et `expires_at` sont écrits en UTC ; les comparer à `NOW()` (heure
locale du serveur sur Dolt) décale tout du fuseau.

### Périmés

```
bsi-query.sh stale                       lister — depuis l'expiration
bsi-claim.sh close-stale                 fermer ceux dont l'expiration est passée
bsi-claim.sh close-stale --min-hours 12  idem, 12 h au-delà — le timer quotidien
```

Le timer `brain-close-stale` (06:00) prend la marge de 12 h. À la main, fermer
le claim d'une autre session demande `--pas-le-mien` : **l'humain confirme**.

---

## Scope, zone, conflits

Le **scope** est une chaîne libre (`myeline`, `pilote/brain`, `agents/`…). Deux
claims **se recouvrent** si l'un des scopes est **préfixe** de l'autre —
c'est `recouvrements()` du CORE, rien de plus fin (la granularité « section de
fichier » de la v1 n'a jamais été implémentée).

| Zone | Recouvrement |
|---|---|
| `kernel` (de l'un OU de l'autre) | **refusé** — « SCOPE CONFLICT », fermer l'autre d'abord |
| toute autre | **averti** — « SCOPE OVERLAP, parallélisme autorisé » |

L'avertissement se relaie à l'humain ; il ne s'ignore pas.

**Le garde de zone** (`scripts/hooks/pre-commit-zone`) est l'autre
moitié : au commit, il lit le **type** du claim de la session et applique
`KERNEL.md ## Session type → zone access`. Il **ne juge que ce qu'il
comprend** : sans claim, avec un type absent du registre, ou quand plusieurs
types sont ouverts sans que l'identité en désigne un, il se tait **en le
disant** (« je n'ai pas pu regarder » n'est pas « aucun claim »).

---

## Verrous de fichier

Plus fins qu'un claim : un fichier, pour une écriture. `scripts/file-lock.sh`,
table `locks`, **TTL en minutes** — 60 par défaut dans le script (le CORE,
appelé sans valeur, en prend 30). Un verrou expiré ne bloque pas : il est
remplacé. Comparaison en UTC.

---

## Les signaux

### Où ils vivent

Un signal est écrit **dans la base de celui qui l'émet**, jamais poussé chez le
destinataire. Le destinataire vient le relever, chez lui **et chez ses peers**
(SSH, `bsi-query.sh peers`). Conséquence voulue : **on peut écrire à une
machine éteinte.**

```
bsi-signal.sh send <cible> --type TYPE [--projet X] --payload "..."
bsi-signal.sh inbox          ce qui m'attend — l'instance ET les sessions de mes claims
bsi-signal.sh outbox         ce que j'ai émis et qui n'est pas relu
bsi-signal.sh ack <sig_id>   accuser réception — même chez un peer
```

Un hook `UserPromptSubmit` relève la boîte de la session **avant chaque
message** ; le contenu d'un signal y est encadré comme **donnée**, jamais comme
instruction.

### Routage

| Cible | Atteint |
|---|---|
| `prod@desktop` | l'instance — toutes ses sessions (broadcast) |
| `sess-YYYYMMDD-HHMM-<slug>` | une session précise (sans `@machine`) |

Identifiant : `sig-YYYYMMDD-HHMMSS-<pid>` (UTC), fabriqué par `send`.

### Types

| Type | Sens | Ce que fait la cible |
|---|---|---|
| `READY_FOR_REVIEW` | A → B | B relit (`reviews/` ou PR) |
| `REVIEWED` | B → A | A lit la revue, continue |
| `BLOCKED_ON` | A → B | B libère le scope, **puis `ack`** |
| `HANDOFF` | A → B | B charge le handoff et reprend |
| `CHECKPOINT` | A → A | la même session, après une coupure, reprend du point posé |
| `INFO` | A → B | rien à faire |

**La levée d'un blocage, c'est l'`ack`.** Quand B accuse le `BLOCKED_ON`, le
signal sort de l'`outbox` de A : c'est la réponse. Il n'y a pas de type
`UNBLOCK` — il n'a jamais existé, et aucun `BLOCKED_ON` n'avait été émis quand <!-- bsi-v1 -->
la règle a été posée (27/09).

Ne pas confondre avec le bloc `ipc.signals` des frontmatters d'agents
(`SPAWN`, `RETURN`, `ESCALATE`…) : c'est le paquet de contexte **entre agents
d'une même session** (BRAIN-026), pas le BSI. Trois noms sont communs.

### Payload

| Type | Payload |
|---|---|
| `CHECKPOINT`, `HANDOFF` | `→ handoffs/<fichier>.md` — créé depuis `handoffs/_template.md` |
| `BLOCKED_ON` | le scope attendu |
| `READY_FOR_REVIEW` | `→ reviews/<fichier>` ou l'URL de la PR |
| `INFO` | texte court |

### Cycle de vie

```
pending    émis, pas encore relu
delivered  accusé par la cible (ack)
archived   rangé dans signals_archive par la conciergerie : relu, et émis il y a plus de 7 jours
```

---

## Archivage

La conciergerie (`brain-conciergerie.sh archive`, hebdomadaire) déplace :

| Quoi | Quand | Où |
|---|---|---|
| claims fermés | ouverts il y a plus de 30 jours | `claims_archive` |
| sessions | plus de 30 jours | `sessions_archive` |
| signaux relus (`delivered`) | émis il y a plus de 7 jours | `signals_archive` |

L'archivage **nomme ses colonnes** (une copie par position perdait des lignes
quand le schéma divergeait) et fige ses limites une seule fois, en UTC.

---

## Ce qui est déclaré mais n'a jamais servi

Dit ici pour qu'on ne le prenne pas pour un mécanisme vivant :

- **Champs satellite** — `parent_sess`, `satellite_type`, `satellite_level`,
  `workflow`, `workflow_step`, `theme_branch` existent en base ; `bsi-claim.sh
  open` ne sait pas les poser (seule la route `POST /bsi/claims` les accepte),
  et aucun claim ne les a jamais portés. Les agents qui les décrivent
  (`kernel-orchestrator`, `satellite-boot`, `supervisor`) sont sous bandeau.
- **Statuts** `stale`, `paused`, `waiting_human`, `failed` — voir Cycle de vie.

---

## Règles absolues

1. **La base est la source** — pas de fichier de claim, pas de table markdown.
2. **Chaque session tient son claim** — l'ouvre au boot, le ferme à la clôture.
3. **Jamais d'auto-libération sur action destructive** — l'humain valide.
4. **Conflit → alerte**, jamais résolu en silence ; refus en zone `kernel`.
5. **Stale ≠ libéré** — fermer le claim d'une autre session se confirme.
6. **UTC partout**, et l'expiration se mesure depuis `expires_at`.
7. **« Je n'ai pas pu regarder » n'est pas « rien »** — une base ou un peer
   injoignable se dit, il ne vaut jamais « aucun claim » ni « aucun signal ».

---

## Décisions

BRAIN-001 (locking optimiste) · BRAIN-002 (la session comme identité) ·
BRAIN-014 (zones) · BRAIN-036 (hors git) · BRAIN-042 (base source unique) ·
BRAIN-046 (métriques de session) · BRAIN-077 (un claim connaît sa session).

---

## Changelog

| Date | Version | Changement |
|------|---------|------------|
| 2026-03-14 | 1.0 | Création — optimiste + TTL, 4 niveaux, workflow scribe complet |
| 2026-03-14 | 1.1 | Slug = rôle fonctionnel — session comme identité de routage |
| 2026-03-14 | 1.2 | Signal payload schema — CHECKPOINT/HANDOFF → handoffs/_template.md |
| 2026-03-16 | 1.3 | Champs satellite optionnels |
| 2026-09-27 | 2.0 | **Réécrite sur le BSI réel** : la base (BRAIN-042), l'identité de session (BRAIN-077), les signaux par `bsi-signal.sh`, la levée d'un `BLOCKED_ON` par `ack`, les zones, les verrous, l'archivage ; ce qui n'a jamais servi, nommé. La v1 décrivait le registre markdown et `claims/` disparus le 19/03. |
