---
name: handoff-matrix
type: reference
context_tier: warm
version: "1.0.0"
---

# Handoff Matrix — session_type × scope → niveau de handoff

> Spec complète : BRAIN-009 (`profil/decisions/009-session-handoff-architecture-identitaire.md`)
> Appliquée par : `session-orchestrator` au boot
> Defaults déclarés dans : `manifest.yml ## handoff_defaults`

---

## Niveaux de handoff

```
NO    →  Layer 0 uniquement          identité pure, espace propre
SEMI  →  Layer 0 + Layer 1 partiel   position chargée (session type)
SEMI+ →  Layer 0 + Layer 1 complet   état projet chargé
FULL  →  Layer 0 + Layer 1 + Layer 2 continuité chirurgicale
```

---

## Matrice

| session_type | scope | Handoff | Raison |
|-------------|-------|---------|--------|
| `brainstorm` | architecture | **NO** | Pensée nette — pas de biais sprint |
| `brainstorm` | feature | **NO** | Idem — espace libre requis |
| `brain` | architecture | **NO** | Décision structurante — Layer 0 suffit |
| `brain` | agent-review | **SEMI** | Position review + agents index |
| `brain` | bhp / implementation | **SEMI+** | État du kernel + schema requis |
| `brain` | brainstorm | **NO** | Brainstorm brain = identité pure |
| `coach` | progression | **SEMI** | Position + dernière session metabolism |
| `coach` | bilan | **SEMI+** | État progression complet requis |
| `audit` | any | **SEMI** | Lecture seule — position suffit |
| `debug` | any | **SEMI** | Position + domaine du bug uniquement |
| `debug` | continuation (même session) | **FULL** | RAM critique — workspace bug actif |
| `work` | sprint (début de journée) | **SEMI+** | État sprint — Layer 2 périmé |
| `work` | sprint (continuation < 4h) | **FULL** | RAM active — workspace en cours |
| `work` | feature isolée | **SEMI+** | État projet sans RAM précédente |
| `work` | bug isolé | **SEMI** | Pas besoin de l'état sprint complet |
| `deploy` | infra | **SEMI+** | État infra requis — Layer 2 inutile |
| `deploy` | rollback / incident | **FULL** | Contexte complet critique |
| `capital` | cv / portfolio | **SEMI+** | État capital + objectifs |
| `capital` | recruteur | **SEMI+** | Idem + projets récents |
| `urgence` | prod-down | **SEMI** | Boot rapide — position urgence |
| `urgence` | incident critique | **FULL** | Tout le contexte disponible |

---

## Règles de surcharge

L'orchestrateur peut dégrader ou élever le niveau déclaré selon :

```
Élévation  (→ FULL)  : signal HANDOFF reçu dans BSI
                       continuation explicite demandée par l'utilisateur
                       workspace/ disponible et pertinent

Dégradation (→ NO)   : brainstorm explicite même si sprint actif
                       session audit (toujours SEMI max)
                       Layer 2 absent → auto-dégrade silencieusement

Interdit             : élever NO → FULL sans Layer 1 validé
                       bloquer une session sur layer manquant — toujours dégrader
```

---

## Gradient intelligent dans un sprint (exemple)

```
Lundi matin         →  SEMI+   reprendre l'état, Layer 2 périmé
Lundi soir          →  FULL    continuation directe < 4h
Mardi matin         →  SEMI+   reset Layer 2, état sprint suffit
Mercredi bug        →  SEMI    position debug uniquement
Mercredi bug suite  →  FULL    continuation même bug < 4h
Vendredi close      →  FULL    wrap complet — scribe, metabolism
```

---

## KPI de santé Layer 0

> `NO HANDOFF productif en < 2 minutes` → Layer 0 est suffisant.
> Si NON → enrichir `brain-constitution.md`, pas ajouter du contexte.

---

## Changelog

| Version | Date | Changement |
|---------|------|------------|
| 1.0.0 | 2026-03-15 | Création — matrice complète, règles surcharge, gradient sprint, KPI Layer 0 |
