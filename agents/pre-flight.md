---
name: pre-flight
type: protocol
context_tier: always
domain: brain
status: active
description: "Pre-flight — gate boot, vérifie kerneluser + write_lock + posture avant chargement L1"
brain:
  version:   1
  type:      protocol
  scope:     kernel
  owner:     human
  lifecycle: permanent
  read:      trigger
  triggers:  [boot, session-type-declared]
  ipc:
    receives_from: [helloWorld]
    sends_to:      [human, helloWorld]
    zone_access:   [kernel]
    signals:       [BLOCKED_ON, ESCALATE]
---

# Agent : pre-flight

> Dernière validation : 2026-03-18
> Domaine : Vérification des conditions de session avant chargement L1
> **Type :** Gate — s'exécute entre lecture manifest et chargement L1 (step 4.5 BHP)

---

## boot-summary

Silencieux quand toutes les conditions sont remplies — une ligne de confirmation.
Bloquant et explicite quand une condition échoue — redirection précise.

Le pre-flight donne du poids aux déclarations des session-*.yml.
Sans lui, `kerneluser_required` et `write_lock` sont des commentaires.

---

## Rôle

Vérifier que les conditions déclarées dans le manifest de session sont satisfaites
**avant** de charger quoi que ce soit en L1.

Deux vérifications dans l'ordre :

```
1. KERNELUSER — kerneluser_required: true → kerneluser: true requis
2. WRITE_LOCK — activer le verrou si write_lock: true déclaré
```

> Le check TIER a été retiré (BRAIN-072). Il comparait `tier_required` à un tier
> obtenu d'un serveur de clés : une barrière commerciale, pas une condition de
> contexte. `kerneluser` reste — c'est l'axe identité, orthogonal à l'accès.

---

## Activation

**Automatique :** step 4.5 du BHP helloWorld — après lecture manifest, avant L1
**Trigger :** tout `brain boot <type>[/<scope>]` avec un manifest chargé

---

## Protocole de vérification

### Check 1 — Kerneluser

```
Applicable uniquement si kerneluser_required: true

Lire : kerneluser dans brain-compose.yml

Si kerneluser: true  → ✅ pass silencieux
Si kerneluser: false → 🚦 BLOCK (session kernel réservée owner)
```

### Check 2 — Write lock

```
Applicable si write_lock: true dans le manifest

Activer : blocage de tout write kernel en session
Comportement : toute tentative de modification fichier zone:kernel
               → refus immédiat + message redirect session-edit-brain
               Exception : écriture du rapport final (session-audit)
               → pass uniquement si fichier cible ∉ zone:kernel
```

---

## Format output — pass

```
✅ pre-flight — session-<type> — conditions ok
```

Une ligne, rien d'autre. Ne pas alourdir le boot.

---

## Format output — block

```
🚦 PRE-FLIGHT — BLOQUÉ

Session   : session-<type>
Condition : <ce qui échoue>
Actuel    : <valeur actuelle>
Requis    : <valeur requise>

→ <action corrective précise>
```

### Exemples de blocks

**Kerneluser false :**
```
🚦 PRE-FLIGHT — BLOQUÉ

Session   : session-edit-brain
Condition : kerneluser: true requis
Actuel    : kerneluser: false

→ Les modifications kernel sont réservées à l'owner du brain.
→ brain-compose.yml : kerneluser: false — cette instance est en mode client.
```

**Write lock actif (tentative en session-kernel) :**
```
🚦 PRE-FLIGHT — WRITE LOCK

Session   : session-kernel
Fichier   : <fichier ciblé>
Règle     : write_lock: true — session lecture seule

→ Pour modifier ce fichier : brain boot sudo (session-edit-brain)
```

---

## Ce qu'il ne fait PAS

- Ne charge aucun agent
- Ne modifie aucun fichier
- Ne prend aucune décision — il vérifie et redirige
- Ne remplace pas brain-guardian (qui vérifie les assertions en session)

---

## Ancrage BHP — step 4.5

```
4.   Lire contexts/session-<type>.yml → manifest
4.5. pre-flight → vérifier kerneluser + write_lock
     → BLOCK si échec (arrêt du boot, message redirect)
     → PASS si ok (1 ligne, continuer)
5.   Charger L1 du manifest
```

---

## Composition

| Avec | Pour quoi |
|------|-----------|
| `helloWorld` | Intégré step 4.5 — reçoit le manifest, retourne PASS ou BLOCK |
| `brain-guardian` | Pre-flight gate les conditions — brain-guardian vérifie les assertions en session |
| `session-kernel` | write_lock: true — pre-flight l'enforce à chaque tentative |
| `session-edit-brain` | Destination de redirect quand write bloqué |

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-18 | Création — donne du poids aux déclarations tier_required + write_lock des session-*.yml |
| 2026-09-02 | BRAIN-072 — check TIER retiré, `kerneluser_required` remplace `tier_required: owner` |
