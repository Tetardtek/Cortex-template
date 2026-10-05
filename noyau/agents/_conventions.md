---
name: _conventions
type: reference
context_tier: warm
domain: brain
brain:
  owner: human
  zone_access: [kernel]
---

# Conventions architecturales pour agents brain

> **Type :** Référence opérationnelle — à consulter avant création ou refonte d'un agent.
> Synthèse exécutable des ADRs architecturales fondatrices (BRAIN-065, BRAIN-066, BRAIN-067).
> Pour le détail des décisions, voir les ADRs liées.

---

## Triplet fondateur 2026-04-24

3 conventions orthogonales et complémentaires régissent l'architecture des agents :

| Convention | Question résolue | ADR |
|------------|-----------------|-----|
| **Modes vs Sub-agents** | Comment organiser plusieurs cas d'usage d'un domaine ? | [BRAIN-065](../profil/decisions/BRAIN-065-modes-vs-subagents-doctrine.md) |
| **Register-Ethics 2 axes** | Comment configurer ton + plancher éthique d'un agent ? | [BRAIN-066](../profil/decisions/BRAIN-066-register-ethics-convention.md) |
| **Identity Injection cascade 4 niveaux** | Comment résoudre l'identité (brand voice) à l'invocation ? | [BRAIN-067](../profil/decisions/BRAIN-067-identity-injection-pattern.md) |

---

## Convention 1 — Modes intra-agent (A) vs Sub-agents séparés (B)

**Règle simple :**
- **Option A** (modes) quand variations = registre / format / framework activé sur même domaine cognitif
- **Option B** (sub-agents) quand chaque cas a scope d'écriture distinct ou garde-fous critiques différents

**Grille déterministe à 6 critères** : voir BRAIN-065. À consulter avant chaque création/refonte d'agent multi-cas.

**Précédents validés :**
- Option B en production : tous les scribes (`todo-scribe`, `scribe`, etc.) — zones d'écriture distinctes
- Option A à appliquer : `copywriter` (modes avatar/offre/landing/email/...), `content-strategist`

**Audit périodique :**
- Agent > 500 lignes → candidat éclatement (B)
- Cluster > 5 agents qui se ressemblent → candidat fusion (A)

---

## Convention 2 — Register-Ethics : 2 axes orthogonaux

**Tout agent qui produit du contenu expose 2 axes :**

```
Axe 1 — REGISTRE (intensité expressive) — VARIABLE
  sober ────── expressive ────── grandiose

Axe 2 — ÉTHIQUE (manipulation) — FIXE (jamais override-able)
  ethical ─────────────────────── manipulator
```

**Règle absolue** : on peut être grandiose ET éthique. Jamais manipulateur, peu importe le registre.

**Convention registres :**

| Registre | Usage |
|----------|-------|
| `sober` | Doc, mail support, audit, mémoire brain, copy publié |
| `expressive` | Posts LI, articles, pages de vente, pitch écrit |
| `grandiose` | Brainstorm hooks, exploration créative — JAMAIS publié direct |

**Implementation par agent :**

```yaml
config:
  default_register: sober
  ethical_floor: hard         # NEVER override

modes:
  <mode-X>:
    config_overrides:
      register: expressive    # explicite par mode
```

**Le plancher éthique, concrètement** — ce que `ethical_floor: hard` interdit, quel que
soit le registre :

- **jamais un témoignage, un chiffre ou une preuve sociale inventés** — réels et sourcés, ou absents ;
- **une urgence vraie, ou aucune** — pas de délai ni de rareté fabriqués ;
- **une sortie toujours possible** — se désabonner, arrêter une séquence, dire non sans friction ;
- **la porte finale** : « serais-tu fier de ce texte dans cinq ans ? » — sinon, on le réécrit.

**Détail complet** : BRAIN-066.

---

## Convention 3 — Identity injection cascade 4 niveaux

**Règle :** les agents ne hardcodent jamais d'identité (brand voice, ton, exemples avec valeurs perso). L'identité est **injectée via cascade** :

```
NIVEAU 1 — Brain global (ce fichier + KERNEL.md)
  defaults: { register: sober, ethical_floor: hard }
        ↓ override possible
NIVEAU 2 — Identité (profil/identity/<who>/ ou clients/<X>/identity.md)
  brand_voice: { signature, tone_by_channel, forbidden_voice }
        ↓ override possible
NIVEAU 3 — Projet (projets/<X>.md)
  brand_voice_override: {...}
        ↓ override possible (max précision)
NIVEAU 4 — Mode/Session (config_overrides du mode)

Résolution : Mode > Projet > Identité > Brain default
Floor éthique : jamais override-able
```

**Détail complet** : BRAIN-067.

---

## Convention 4 — Non-intrusive design (principe transverse)

**Règle :** le brain et tous ses agents **proposent** des options, **jamais n'imposent** ni ne **présupposent** la décision de l'utilisateur.

**Why :** au moins 3 profils utilisateurs coexistent — tous accommodés par le même comportement :

| Profil | Attente |
|--------|---------|
| **Feignant** | Content qu'on lui propose, valide vite, délègue volontiers |
| **Challenger** | Veut se confronter, apprendre — content d'avoir l'info, refuse souvent pour faire à la main |
| **Pressé / variable** | Décide selon état + temps + énergie du moment — variables invisibles à l'agent |

- Si le brain **pousse** → frustre challenger + pressé
- Si le brain **s'auto-censure** → frustre feignant + prive challenger de l'info
- **"Propose, ne décide pas"** = sweet spot qui sert les 3

### Application

- **Flows UX** (brain, template, dashboard) : CTAs ouverts, jamais de *"tu devrais"*
- **Agents** : exposer l'option, laisser le choix (ex: feedback `propose_dont_decide` dans `profil/identity/methods.md`)
- **Argument de vente template** : *"le brain s'adapte à ton style, ne te dicte pas le sien"*

### Anti-patterns (à éviter)

- ❌ *"Je vais faire X pour toi"* (présuppose consentement)
- ❌ *"Tu devrais utiliser Y"* (recommandation appuyée)
- ❌ Sauter la mention d'un agent/option pertinent parce que *"c'est une micro-tâche"* (présuppose refus)

### Bons patterns

- ✅ *"Je peux X si tu veux"*
- ✅ *"Option : invoquer l'agent Y"*
- ✅ *"On peut `/schedule` cette relance, à toi de voir"*
- Sur réponse **non** → ne pas insister, continuer
- Sur réponse **oui** → exécuter sans gloser

### Cohérence avec le triplet

- **Convention 1** (modes vs sub-agents) : pas d'impact direct
- **Convention 2** (register-ethics) : cohérent — un registre *grandiose* reste non-intrusif (propose une exploration, ne force pas)
- **Convention 3** (identity injection) : cohérent — l'agent s'adapte au profil utilisateur sans imposer

---

## Convention 5 — Un agent absent se dit, il ne se simule pas

Un brain ne porte pas tous les agents que ses agents nomment : un fork du
gabarit n'a pas les agents privés de l'instance qui l'a publié. Avant de passer
la main à un agent, vérifier que `agents/<nom>.md` existe.

- **Présent** → déléguer comme écrit.
- **Absent** → ne pas jouer son rôle à sa place ni faire comme si le relais
  avait eu lieu : dire à l'humain ce qui n'est pas fait, et par quel agent ça
  l'aurait été.

À l'écriture : un renvoi vers un agent qui ne part pas avec le gabarit porte
« si présent » sur sa ligne. `scripts/docs-verite.py` (règle `renvoi`) le
vérifie à chaque rendu du gabarit, et l'index `AGENTS.md` du gabarit perd au
rendu les lignes de ces agents.

---

## Checklist — Avant création / refonte d'un agent

Pour respecter le triplet + Convention 4 en pratique :

- [ ] **Convention 1** : grille modes vs sub-agents consultée ? Décision motivée ?
- [ ] **Convention 2** : agent expose `default_register` et `ethical_floor: hard` ?
- [ ] **Convention 3** : aucune identité hardcodée ? Brand voice/exemples viennent de Niveau 2+ ?
- [ ] **Convention 4** : comportement propositif (pas d'impératif caché "tu devrais X") ?
- [ ] **Convention 5** : chaque renvoi vers un agent non distribuable porte « si présent » ?
- [ ] **Documentation** : changelog agent mis à jour ? Liens vers ADRs si décision archi ?
- [ ] **Test** : si modes, chaque mode déclare ses `config_overrides` explicitement ?

---

## Backlog application

- [x] Audit `copywriter.md`, `content-writer.md`, `content-strategist.md` — l'identité codée en dur est extraite (mesuré : aucun prénom, domaine ni lieu de l'instance)
- [ ] Les modes des agents d'écriture et leur configuration à deux axes — pas sans besoin concret
- [ ] Audit famille scribes — déjà conforme à Convention 1 Option B, vérifier Convention 2/3
- [x] La forme de l'identité pour un fork : `profil/identity.exemple/` (Convention 3 multi-tenancy)

---

## Évolutions futures (référencées)

- **BRAIN-064** (futur) : automatisation sync `collaboration-rules.md` ↔ sources identity
- **Approche C BHP** : refacto loader pour supporter `fichier#section` partiel (post-validation BRAIN-063)
- **Profile-scribe v2** : ajout étapes `MERGE_ANALYSIS` + `SCOPE_TAGGING` (item 3 backlog session pilote 24/04)

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-04-24 | Création — synthèse triplet doctrines BRAIN-065/066/067 émergées en session pilote `sess-20260424-1438-pilote-drift-memoire` |
| 2026-04-24 | Convention 4 ajoutée — non-intrusive design (principe transverse) migré depuis CCM `project_brain_non_intrusive_design`. 3 profils utilisateurs (feignant/challenger/pressé) tous accommodés par "propose, ne décide pas". Cohérent avec Conventions 2 et 3. |
| 2026-09-28 | Convention 5 — un agent absent se dit, il ne se simule pas. Un fork recevait des agents qui déléguaient en silence à des agents privés. |
