---
name: file-types
type: reference
context_tier: cold
---

# File Types — Taxonomie officielle des fichiers brain

> **Type :** Invariant
> Décision architecturale — session 2026-03-14
> Gardien : `scribe` — modification soumise au protocole d'inviolabilité

---

## Les 4 types

### Invariant

**Définition :** Règle fondamentale du système. Si elle est violée, le brain entier est impacté — pas un agent, pas un domaine : tout le monde.

**Propriétés :**
- Chargée par tous les agents ou en bootstrap global
- Évolue rarement — chaque changement est une décision architecturale
- Protégée par le protocole d'inviolabilité (voir ci-dessous)

**Exemples :**
```
anti-hallucination.md
context-hygiene.md
memory-integrity.md
scribe-pattern.md
project-conventions.md
```

---

### Contexte

**Définition :** Référence pairée à un agent ou orchestrateur spécifique. Chargée conditionnellement par cet agent uniquement. Si elle est corrompue, un agent est impacté — pas le système entier.

**Propriétés :**
- Un contexte = un agent propriétaire déclaré
- Évolue avec son agent
- Claim BSI scopé à la session de l'agent propriétaire

**Exemples :**
```
orchestration-patterns.md  → orchestrator-scribe
bootstrap-spec.md          → helloWorld
bsi-spec.md                → scribe
```

---

### Référence

**Définition :** Document consulté — cartographie, spec technique, pitch. Pas de règle d'impact direct. Aucun agent n'est cassé si elle est incomplète — mais le système devient flou.

**Propriétés :**
- Consultée par plusieurs agents selon les besoins
- Pas de propriétaire unique
- Claim BSI standard

**Exemples :**
```
scribe-system.md
memory-architecture.md
brain-pitch.md
CLAUDE.md.example
```

---

### Personnel

**Définition :** Données appartenant à l'utilisateur. Jamais exportées, jamais partagées. Hors scope de tout audit universel.

**Propriétés :**
- Jamais dans le kernel exportable
- Pas de contrainte de format ou d'impact système
- Peut avoir un `.example` côté template (jamais le contenu réel)

**Exemples :**
```
capital.md
objectifs.md
collaboration.md   → collaboration.md.example dans le template
stack.md
```

---

## Protocole d'inviolabilité — Invariants

Un Invariant ne peut jamais être modifié comme un fichier ordinaire.

```
Claim standard (Contexte / Référence / Personnel)
  scribe ouvre le claim → écrit → ferme le claim

Claim Invariant
  1. scribe identifie la modification nécessaire
  2. scribe PROPOSE la modification + justification explicite
  3. confirmation humaine obligatoire avant toute écriture
  4. scribe écrit uniquement après confirmation
  5. signal BSI → toutes sessions actives notifiées
  6. commit atomique avec mention "invariant modifié : <fichier>"
```

**Règle absolue :** aucun agent ne peut écrire seul sur un Invariant. Sans confirmation humaine, pas d'écriture.

---

## Convention header — non négociable

Chaque fichier `profil/` commence par son type déclaré en deuxième ligne :

```markdown
# Titre du fichier

> **Type :** Invariant | Contexte | Référence | Personnel
```

**Pourquoi :** le type est visible au premier coup d'œil — par un agent, par un humain, par le BSI. Pas de déduction, pas d'ambiguïté.

---

## Intégration BSI — niveaux de claim par type

| Type | Niveau claim | Règle |
|------|-------------|-------|
| Invariant | 🔴 Critique | Confirmation humaine obligatoire + signal global |
| Contexte | 🟡 Standard | Claim scopé à l'agent propriétaire |
| Référence | 🟢 Standard | Claim standard, pas de restriction |
| Personnel | 🔵 Privé | Aucune contrainte cross-session |

---

## Intégration modes session

Le type d'un fichier informe ce qui est autorisé selon le mode actif.
Matrice complète → `⏸ todo/brain.md — Brainstorm système de modes`.

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-14 | Création — 4 types (Invariant/Contexte/Référence/Personnel), protocole inviolabilité, convention header, intégration BSI |
