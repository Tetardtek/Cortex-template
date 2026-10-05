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
l'instance), sinon vers `noyau/agents/<nom>.md` (le noyau livré).
`instance/agents/<nom>.complement.md` s'AJOUTE à l'agent : `agents/<nom>.md` devient
un fichier assemblé (l'agent, puis le complément, puis une marque d'empreinte) — c'est
là que va ce qui est propre à l'instance (l'owner, son niveau), jamais dans le noyau
distribué. Une ligne `<!-- carte: <dossier> [resume] -->` du complément y est remplacée
par la carte calculée depuis les tableaux de niveaux du dossier — de la donnée (nom et
niveau, jamais la preuve), qui calibre les réponses. On lit toujours `agents/<nom>.md` ; on écrit dans la couche voulue — jamais
dans un fichier assemblé —, puis `brain vue --construire`.
Un fichier réel dans `agents/` est une écriture que git ne voit pas : `brain vue`
le signale, ne le touche jamais. Un fork ne modifie pas `noyau/` — il surcharge
dans `instance/agents/`, et `brain maj` met le noyau à jour sans toucher à la
surcharge.

**Après un `brain maj`, la surcouche se relit.** Un complément suit tout seul : la
vue l'assemble avec le nouvel agent. Une **surcharge** remplace l'agent entier — ce
que le noyau y améliore ne lui arrive pas. Le plan nomme chaque surcharge que la
version change, et `--appliquer` en pose la liste, avec la commande de diff de
chacune, dans `workspace/scratch/brain-maj-<version>/surcharges.md`. Pour chacune :
lire le diff du noyau, puis **proposer** — reprendre dans la surcharge ce qui sert,
ou la réduire à un complément si ce qui est propre à l'instance tient en un ajout.
Jamais écraser la surcharge par le noyau, jamais décider seul : c'est la couche de
l'owner. Le plan dit aussi les fichiers que le dépôt suit encore et que la version
range en satellites (`projets/`, `handoffs/`…) : git ne les retire pas, l'owner les
versionne à part quand il veut (`docs/satellites.md`).

Les pages de la skill propres à l'instance vivent dans `instance/skill/` ; la vue
pose le lien `skills/brain/instance` qui les montre à la skill.

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
