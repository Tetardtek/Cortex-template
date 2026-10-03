<!-- Généré depuis skills/brain/src/noyau.md par scripts/docs-generer.py — ne pas éditer ici. -->
# Le noyau — ce qu'on ne touche pas seul

La loi est `KERNEL.md` : la lire avant d'écrire dans une zone qu'on ne connaît
pas. Ce qui suit en est le résumé opérationnel.

## Les zones

| Zone | Contient | Qui écrit |
|---|---|---|
| **noyau** | `KERNEL.md`, `CLAUDE.md`, `PATHS.md`, `BRAIN-INDEX.md`, `brain-constitution.md`, `brain-compose.yml`, `noyau/agents/`, `profil/` | personne sans décision humaine explicite |
| **satellites** | `todo/`, `toolkit/`, `progression/`, `reviews/`, `handoffs/`, `workspace/` | le scribe propriétaire de chacun |
| **instance** | `focus.md`, `projets/`, `brain-compose.local.yml`, `PATHS.md`, `instance/` | propre à la machine |
| **work** | les dépôts de projets | le brain documente, ne possède pas |

## Les gates

- En session `brain`, écrire dans `KERNEL.md`, `CLAUDE.md`,
  `brain-constitution.md` ou la partie invariante de `profil/` demande une
  **confirmation humaine explicite** : proposer la diff, attendre le oui.
- `learning` n'écrit jamais dans le noyau.
- `pilote` exige l'owner du brain (`kerneluser_required`).

## Les agents

`agents/` est une **vue** : des liens, ignorés par git, construits par `brain vue`.
`agents/<nom>.md` pointe vers `instance/agents/<nom>.md` s'il existe (la surcharge de
l'instance), sinon vers `noyau/agents/<nom>.md` (le noyau livré). On lit toujours
`agents/<nom>.md` ; on écrit dans la couche voulue, puis `brain vue --construire`.
Un fichier réel dans `agents/` est une écriture que git ne voit pas : `brain vue`
le signale, ne le touche jamais. Un fork ne modifie pas `noyau/` — il surcharge
dans `instance/agents/`, et `brain maj` met le noyau à jour sans toucher à la
surcharge.

Un agent est `agents/<nom>.md` : un frontmatter (`description`, `brain.scope`,
`brain.type`, `brain.triggers`, `brain.ipc`), puis son texte — souvent un
`## boot-summary` court, chargé d'abord, et un `## detail`. Le gabarit d'un nouvel agent : `agents/_template.md` ; ses
conventions : `agents/_conventions.md`.

`agents/CATALOG.yml` est **calculé** dans la vue depuis les frontmatters, par
`brain vue --construire` — jamais suivi par git, jamais édité à la main. Un agent qu'il ne connaît
pas (créé dans un fork) compte quand même, s'il n'est pas `scope: personal`. Un agent `scope: personal` est privé : il ne part pas avec
le gabarit, et un agent distribué ne doit pas compter sur lui.

## Le principe des scribes

Un agent métier ne réécrit pas le brain lui-même : il signale, et le scribe du
territoire écrit. La carte : `profil/specs/scribe-system.md`.
