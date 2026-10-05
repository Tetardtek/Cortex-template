---
name: context-hygiene
type: reference
context_tier: cold
---

# Context Hygiene — Règle fondamentale du brain

> **Type :** Invariant
> Décision architecturale — session 2026-03-13
> Voir aussi `brain/profil/memory-architecture.md` — les trois pilliers (TTL, Sectionnarisation, Stratification)

---

## Règle dure

**Jamais charger tout le système au démarrage. Jamais.**

Le brain est conçu pour un chargement sélectif et progressif.
Charger tous les agents en début de session = dilution de l'attention + tokens gaspillés + réponses moins précises.

---

## Ce qui est chargé au démarrage — toujours

| Fichier | Taille cible | Pourquoi universel |
|---------|-------------|-------------------|
| `CLAUDE.md` | < 100 lignes | Bootstrap — instructions globales |
| `focus.md` | < 120 lignes | État actuel des projets |
| `profil/specs/collaboration.md` | < 100 lignes | Comment travailler ensemble |
| `agents/coach.md` | < 220 lignes | Présence permanente — observation en arrière-plan |

**Total cible démarrage : < 500 lignes (~8-10k tokens). Jamais dépasser.**

---

## Ce qui est chargé sur détection — jamais au démarrage

| Déclencheur | Ce qui est chargé |
|-------------|------------------|
| Domaine technique détecté | Agent métier correspondant (1-2 max) |
| Session prod / infra | `profil/objectifs.md` + agent vps ou ci-cd |
| Fin de session avec patterns | `agents/toolkit-scribe.md` |
| Fin de session avec bilan | `agents/coach-scribe.md` |
| Ambiguïté de scope | `agents/interprete.md` |
| Multi-domaines | `agents/orchestrator.md` → il délègue |

---

## Libération de contexte

Quand un domaine de travail est terminé dans la session, ses agents peuvent être libérés :

```
→ "on passe à autre chose" = l'agent précédent n'est plus actif
→ Charger le nouvel agent, ne pas cumuler sans raison
```

Le modèle n'oublie pas ce qui a été dit — mais moins de "présence permanente" d'agents
inutiles = meilleure précision sur le domaine actif.

---

## Cycle de vie d'un agent — 3 états

| État | Condition | Comportement |
|------|-----------|--------------|
| **Actif** | Domaine en cours d'acquisition | Chargé sur détection, intervient |
| **Stable** | Domaine maîtrisé — peu ou pas d'interventions en session | Disponible sur demande, plus chargé automatiquement |
| **Retraité / Collègue** | Domaine acquis — signal de graduation explicite | Référence ponctuelle, ne coache plus, ne persiste plus |

**Signal de graduation :** plusieurs sessions consécutives sans intervention de l'agent = domaine acquis.
Le documenter dans `progression/milestones/`.

---

## Règle de taille des fichiers

Pour que le système reste viable sur la durée :

| Fichier | Taille max recommandée |
|---------|----------------------|
| Agent standard | 200 lignes |
| Fichiers profil (collaboration, objectifs) | 100 lignes |
| focus.md | 120 lignes |
| CLAUDE.md | 100 lignes (bootstrap only) |
| Fichier toolkit pattern | 60 lignes |

Si un fichier dépasse → le scribe compétent le compresse à la prochaine session dédiée.

---

## Application au coach — exemple concret

| Phase | État coach | État coach-scribe |
|-------|-----------|-----------------|
| Acquisition | Actif — observe, intervient, rapporte | Actif — écrit journal/skills/milestones |
| Système stable | Stable — chargé sur demande uniquement | En veille — plus de journal actif |
| Collègue | Retraité → pair technique, référence | Archivé — `progression/` en lecture seule |

Le coach devient collègue quand il n'a plus rien à corriger.
C'est le meilleur signal de progression possible.

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-13 | Création — cycle de vie agents, règle démarrage minimal, libération contexte |
