---
name: memory-integrity
type: reference
context_tier: cold
---

# Memory Integrity — Règle fondamentale d'écriture

> **Type :** Invariant
> Décision architecturale — session 2026-03-13
> Complémentaire de `context-hygiene.md` (chargement) et `scribe-pattern.md` (qui écrit quoi)

---

## Principe fondateur

**`context-hygiene.md` governe ce qu'on CHARGE.**
**`memory-integrity.md` governe ce qu'on ÉCRIT.**

Un système dont la mémoire est corrompue est pire qu'un système sans mémoire.
Chaque entrée mémoire doit être atomique, attribuable, et réversible.

---

## Règle dure — Un commit = un agent = un scope

```
❌ Un commit qui touche brain/ + progression/ + toolkit/
   → impossible de savoir quel agent a écrit quoi
   → impossible de réverter un seul agent sans tout défaire

✅ Un commit par repo, par agent, par action
   → git blame = audit complet de provenance
   → réverter = chirurgical, sans dommage collatéral
```

---

## Déclaration de scope — obligatoire pour tout agent écrivant

Tout agent qui écrit dans le brain, le toolkit ou la progression doit déclarer explicitement :

```markdown
## Écrit où

| Repo | Fichiers cibles | Jamais ailleurs |
|------|----------------|-----------------|
| `brain/` | `focus.md`, `projets/<X>.md` | Pas `toolkit/`, pas `progression/` |
```

Sans cette déclaration → scope indéfini → dérive mémoire garantie.

---

## Chargement conditionnel — mémoire sélective

Un agent n'a pas besoin de tout savoir au démarrage.
Il charge ce dont il a besoin **au moment exact où il en a besoin**.

```
Trigger : "je m'apprête à écrire"
  → charger brain/profil/specs/memory-integrity.md
  → vérifier : est-ce que ce fichier est dans mon scope déclaré ?
  → OUI → écrire
  → NON → signal "hors scope — déléguer à <agent compétent>"
```

Ce pattern s'applique à tout fichier de référence qui n'est utile qu'à un moment précis — pas à toute la session.

---

## Validation avant commit — checklist git-analyst

Avant tout commit, valider :

```
□ Chaque fichier modifié appartient au scope déclaré de l'agent qui l'a écrit
□ Un seul repo par commit (brain/ OU progression/ OU toolkit/)
□ CLAUDE.md modifié → profil/CLAUDE.md.example mis à jour
□ Nouvel agent créé → AGENTS.md + CLAUDE.md mis à jour
□ Aucune entrée mémoire inventée — tout ce qui est écrit est prouvé ou signalé
```

---

## Empoisonnement mémoire — comment ça arrive

```
Agent hallucine → écrit une fausse info → commitée sans validation
  → la fausse info devient "vérité" dans le brain
  → les sessions suivantes se basent dessus
  → l'erreur se propage et se calcifie

Défenses :
1. Anti-hallucination dans chaque agent (niveau de confiance explicite)
2. Validation scope avant commit (git-analyst)
3. Commits atomiques (réversibilité chirurgicale si erreur détectée)
```

---

## Architecture des repos — frontières d'identité

| Repo | Nature | Exportable | Contenu |
|------|--------|-----------|---------|
| `toolkit/` | Universel | ✅ tel quel | Patterns validés en prod |
| `brain/agents/` | Universel | ✅ tel quel | Agents spécialisés |
| `brain/todo/` | Mixte | ⚠️ partiel | brain.md universel, projets personnels |
| `brain/profil/` | Personnel | ❌ strippé | Identité, objectifs, capital |
| `brain/projets/` | Personnel | ❌ strippé | Projets spécifiques |
| `progression/` | Personnel | ❌ jamais | Journal, skills, milestones |

Cette séparation est intentionnelle — elle rend le `claude-brain-template` générable par suppression des couches personnelles.

---

## Qui charge ce fichier

| Agent | Quand | Trigger |
|-------|-------|---------|
| `git-analyst` | Au démarrage | Toujours — c'est sa grille de validation |
| `recruiter` | Sur trigger | Quand il forge un agent qui écrit |
| `agent-review` | Sur trigger | Critère de review : "scope déclaré ?" |

Les scribes **n'ont pas besoin de charger ce fichier** — ils l'appliquent via leur section `## Écrit où`. Le principe vit dans leur structure.

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-13 | Création — émergé de la réflexion commit granulaire + mémoire sélective |
