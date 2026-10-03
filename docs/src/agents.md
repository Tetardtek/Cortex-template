---
label: Agents
groupe: Comprendre
ordre: 4
---

# Les agents

> Des spécialistes qui persistent d'une session à l'autre. Chacun fait une
> chose, connaît ses limites, et passe la main quand ça sort de son domaine.

---

## Comment ils arrivent

- **Par la session** — le manifest du type de session en charge certains
  d'office (la colonne « Agents chargés d'office » de la page **Sessions**).
- **Par le domaine** — tu parles d'un bug, `debug` arrive.
- **Sur demande** — « charge l'agent testing », « charge les agents security
  et code-review ».

La plupart des agents chargent d'abord un résumé, puis leur détail quand ils
travaillent : le contexte reste disponible pour ce que tu fais.

---

## Les {{NB_AGENTS}} agents

*Liste générée depuis l'en-tête de chaque fichier `agents/*.md` — la portée
(`brain.scope`) et le rôle (`brain.type`) qu'il déclare, et sa description.
Un agent ajouté ou retiré change cette page à la génération suivante.*

<!-- genere:agents -->

---

## Créer le tien

`agents/_template.md` est le gabarit d'un agent, et `agents/_conventions.md`
ses conventions. Ton agent s'écrit dans `instance/agents/<nom>.md` — pas dans
`agents/`, qui est une vue — puis `brain vue --construire` le rend visible. Pour
modifier un agent du noyau, copie-le dans `instance/agents/` : ta version
l'emporte, et celle du noyau reste là pour comparer. `agent-review` audite un agent existant : ce qu'il promet,
ce qu'il fait, ce qui chevauche un autre.

Certains agents renvoient à des agents que ce brain n'a pas : ceux de l'instance
qui a publié le gabarit. Ces renvois portent « si présent », et un agent absent
ne se simule pas — l'agent qui devait lui passer la main te dit ce qui n'est
pas fait (`agents/_conventions.md`, convention 5).
