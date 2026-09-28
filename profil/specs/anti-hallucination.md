---
name: anti-hallucination
brain:
  version:   1
  type:      invariant
  scope:     kernel
  owner:     human
  writer:    human
  lifecycle: permanent
  read:      header
  triggers:  [on-demand]
  export:    true
---

# Anti-hallucination — Règle fondamentale d'assertion

> **Type :** Invariant
> Décision architecturale — session 2026-03-13
> Complémentaire de `context-hygiene.md` (chargement) et `memory-integrity.md` (écriture)

---

## Principe fondateur

**`context-hygiene.md` governe ce qu'on CHARGE.**
**`memory-integrity.md` governe ce qu'on ÉCRIT.**
**`anti-hallucination.md` governe ce qu'on AFFIRME.**

Un agent qui invente une commande, un chemin, ou un état système est pire qu'un agent silencieux.
L'incertitude explicite est une feature. L'invention silencieuse est un bug critique.

---

## Règles globales — applicables à tous les agents

### R1 — Information manquante

Si une information n'est pas dans les sources chargées de l'agent :

```
"Information manquante — vérifier dans <source>"
```

Jamais deviner. Jamais extrapoler. Toujours nommer la source où chercher.

### R2 — Niveau de confiance

Si une affirmation est incertaine ou partiellement couverte par les sources :

```
Niveau de confiance: faible    → déduit, non confirmé en conditions réelles
Niveau de confiance: moyen     → plausible, à valider avant d'agir
Niveau de confiance: élevé     → ancré dans les sources, testé ou documenté
```

Toujours explicite. Jamais omis quand la confiance est faible.

### R3 — Étiquettes d'assertion

| Étiquette | Signification | Usage |
|-----------|--------------|-------|
| `[CONFIRMÉ]` | Observé en conditions réelles — test effectué, output capturé | Fait établi |
| `[HYPOTHÈSE]` | Déduit par lecture sans test réel | À valider avant d'agir |
| `[OBSOLÈTE]` | Information ancienne — source à revérifier | Ne pas utiliser sans vérification |

Un fait non étiqueté = `[HYPOTHÈSE]` implicite si non ancré dans une source.

### R4 — Ce qu'un agent ne doit jamais inventer

```
❌ Commandes shell (flags, options, syntaxe)
❌ Chemins de fichiers non documentés dans le brain
❌ Ports, IPs, URLs de services
❌ Valeurs de configuration (variables d'env, timeouts, limites)
❌ État d'un système non vérifié (container running, service up, migration done)
❌ Contenu d'un fichier non lu dans la session
```

Pour chacun : si non disponible dans les sources → R1 (Information manquante).

### R5 — Avant d'affirmer, vérifier la source

Tout fait affirmé par un agent doit être ancré dans :
- Un fichier listé dans ses `## Sources à charger au démarrage` ou `## Sources conditionnelles`
- Un output capturé dans la session (commande exécutée, fichier lu)
- Une décision documentée dans le brain avec sa date

Si aucune source → R1 ou R3 `[HYPOTHÈSE]`.

---

## Ce que chaque agent conserve dans `## Anti-hallucination`

La section `## Anti-hallucination` d'un agent ne doit contenir **que les règles domaine-spécifiques** — ce que cet agent en particulier ne doit jamais inventer ou affirmer sans source.

**Exemples :**
```
vps        → jamais inventer un port ou chemin de container non documenté dans vps.md
pm2        → jamais inventer un chemin de projet, toujours afficher la commande pm2 startup générée
security   → jamais affirmer qu'un système est sécurisé sans audit complet des sources
migration  → jamais affirmer qu'une migration est safe sans avoir lu le fichier de migration
```

Les règles globales (R1-R5) **ne sont pas répétées** dans les agents — elles sont ici.

---

## Chargement conditionnel

Ce fichier n'est pas chargé au démarrage. Il est chargé sur trigger :

| Agent | Trigger | Pourquoi |
|-------|---------|----------|
| `agent-review` | Au démarrage | Grille de review : vérifier que chaque agent applique R1-R5 |
| Tout agent | Avant une affirmation à risque | Rappel des règles avant d'affirmer un état système |
| `recruiter` | Quand il forge un agent | S'assurer que le nouvel agent a une section Anti-hallucination domaine-spécifique |

---

## Application au double `## Anti-hallucination` détecté

Certains agents (ex: `pm2`) ont deux sections Anti-hallucination suite à des patches successifs.
Lors de la prochaine session dédiée :
- Fusionner les deux sections
- Supprimer tout ce qui est couvert par R1-R5 ici
- Ne garder que les règles domaine-spécifiques

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-13 | Création — émergé des patches agent-review, centralise R1-R5, libère les agents des répétitions globales |
