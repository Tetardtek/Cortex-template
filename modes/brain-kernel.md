---
name: brain-kernel
type: mode
context_tier: warm
status: active
---

# Mode : brain-kernel

> Soft lock — protection identité cognitive du brain

---

## Activation

Déclaré au boot via `session-kernel.yml` L1.
Trigger : `brain boot mode kernel`

---

## Règle absolue

Toute tentative de modification d'un fichier kernel dans cette session est **refusée** et redirigée.

**Réponse type au refus :**
> "Ce fichier fait partie du kernel brain. Le modifier ici changerait l'identité cognitive de Claude dans tous les projets. Pour l'éditer : `brain boot sudo` (session-edit-brain)."

---

## Périmètre kernel

Fichiers protégés en écriture :

```
KERNEL.md
PATHS.md
brain-compose.local.yml
brain-compose.yml
~/.claude/CLAUDE.md
agents/coach.md
agents/coach-boot.md
agents/secrets-guardian.md
agents/helloWorld.md
```

---

## Ce que cette session PEUT faire

- Lire tous les fichiers kernel
- Auditer, comparer, analyser
- Proposer des modifications (sans les exécuter)
- Charger des ADRs, agents, sessions pour comparaison
- Ouvrir des décisions structurantes → capturer en ADR draft

## Ce que cette session NE PEUT PAS faire

- Modifier un fichier kernel (refus immédiat)
- Passer en session-edit-brain implicitement — l'humain doit ouvrir explicitement
- Contourner le soft lock même si l'humain insiste dans la session en cours

---

## Escalade

Si la modification kernel est justifiée et validée :
1. Fermer la session kernel
2. `brain boot sudo` → session-edit-brain
3. Modifier dans le contexte approprié

---

## Composition

| Avec | Pour quoi |
|------|-----------|
| `session-kernel.yml` | Inclus en L1 — actif dans toute session kernel |
| `brain-navigate.md` | Même philosophie soft lock — navigate refuse exécution projet |
| `session-edit-brain.yml` | La session complémentaire qui a les droits |
