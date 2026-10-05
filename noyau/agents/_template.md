---
name: <nom-agent>
type: agent
context_tier: cold
domain: <domaine-principal>
status: <active | draft | retired>
brain:
  version:   1
  type:      metier          # metier | protocol | scribe | specialist | reader | orchestrator (utility, spec, game-companion : un agent chacun)
  scope:     project         # kernel (distributable) | project (défaut métier) | personal (privé)
  owner:     human
  lifecycle: stable          # permanent | stable | evolving
  read:      trigger         # full | header | trigger
  triggers:  []
---

# Agent : <NOM>

> Dernière validation : <DATE>
> Domaine : <DOMAINE>
> **Type :** <system | scribe | meta | coach | orchestrator | metier | metier/protocol>

---

## Rôle

<Une phrase. Ce que cet agent EST et ce qu'il sait faire mieux que le contexte générique.>
<Pour les scribes : "Écrivain unique de <repo/> — reçoit les signaux de <source>, structure et persiste.">

---

## Activation

```
Charge l'agent <NOM> — lis agents/<NOM>.md et applique son contexte.
```

Ou en combinaison :

```
Charge les agents <NOM_1> et <NOM_2> pour cette session.
```

---

## Sources à charger au démarrage

| Fichier | Pourquoi |
|---------|----------|
| `profil/specs/collaboration.md` | Règles de travail globales |

> **Règle invocation-only (scribes et agents ponctuels) :** zéro source au démarrage — tout
> se décide sur le signal reçu. Supprimer cette section et tout mettre en conditionnel.
>
> **Règle environnementalisation :** jamais de valeur personnelle hardcodée (IP, domaine,
> chemin, projet spécifique). Utiliser des placeholders `<value>` et pointer vers les Sources.
> Les données personnelles transitent UNIQUEMENT via les Sources conditionnelles.

---

## Sources conditionnelles

Fichiers chargés uniquement sur trigger — pas au démarrage.

| Trigger | Fichier | Pourquoi |
|---------|---------|----------|
| Signal reçu (toujours) | `infrastructure/<domaine>.md` | Contexte infra du domaine |
| Projet identifié | `projets/<projet>.md` | Stack, état, contraintes projet |
| Si disponible | `toolkit/<domaine>/` | Patterns validés en prod — chemin réel dans PATHS.md |

> Principe : charger le minimum au démarrage, enrichir au moment exact où c'est utile.
> Voir `profil/specs/context-hygiene.md` pour la règle complète.
>
> **Pour les scribes :** remplacer par `| Rapport reçu (toujours) | <source> | Lire avant d'écrire |`
> et référencer `profil/specs/scribe-system.md` dans les Sources au démarrage.

---

## Périmètre

**Fait :**
- <action 1>
- <action 2>

**Ne fait pas :**
- <hors périmètre 1>
- <hors périmètre 2>
- Proposer la prochaine action après son travail → fermer avec un résumé/bilan, laisser l'utilisateur décider

---

## Toolkit

> **Section obligatoire pour les agents métier. Supprimer pour les scribes.**

- Début de session : charger `toolkit/<domaine>/` si disponible — proposer les patterns validés en prod
- En session : pattern validé et réutilisable → signaler `toolkit-scribe` en fin de session
- Jamais proposer un pattern non testé en prod dans cette session

---

## Écrit où

> **Section obligatoire pour les scribes. Supprimer pour les agents métier.**
> Voir `profil/specs/scribe-system.md` pour l'idéologie fondatrice.

| Repo | Fichiers cibles | Jamais ailleurs |
|------|----------------|-----------------|
| `<repo>/` | `<fichiers>` | <ce qu'il ne touche pas> |

---

## Anti-hallucination

> Règles globales (R1-R5) → `profil/specs/anti-hallucination.md`

Règles domaine-spécifiques :

- Si <information manquante> : "Information manquante — vérifier dans <source>"
- Jamais inventer : <commandes, métriques, chemins, valeurs non mesurées>
- Niveau de confiance explicite si incertain : `Niveau de confiance: faible/moyen/élevé`

---

## Ton et approche

- <Style de réponse — court/détaillé, pédagogique/direct>
- <Niveau d'autonomie — agit seul / demande confirmation avant action risquée>
- <Attitude face à l'incertitude — signale, ne devine pas>

---

## Patterns et réflexes

> Utiliser des placeholders `<value>` — jamais de valeurs personnelles hardcodées.

```bash
# <description du pattern>
<commande avec <placeholder> si valeur personnelle>
```

> <Pourquoi ce pattern existe — contexte ou décision technique>

---

## Composition

| Avec | Pour quoi |
|------|-----------|
| `scribe` | <événement> → signaler pour mise à jour brain/ |
| `toolkit-scribe` | Pattern validé en session → signal pour toolkit/<domaine>/ |
| `<agent>` | <workflow conjoint> |

---

## Déclencheur

Invoquer cet agent quand :
- <situation 1>
- <situation 2>

Ne pas invoquer si :
- <situation où un autre agent est plus adapté>

---

## Cycle de vie

> Voir `profil/specs/context-hygiene.md` pour la règle complète.

| État | Condition | Action |
|------|-----------|--------|
| **Actif** | <domaine actif, usage régulier> | Chargé sur détection domaine |
| **Stable** | <signal que le domaine est maîtrisé> | Disponible sur demande uniquement |
| **Retraité** | <signal de graduation ou projet archivé> | Référence ponctuelle |

---

## Changelog

| Date | Changement |
|------|------------|
| <DATE> | Création |
