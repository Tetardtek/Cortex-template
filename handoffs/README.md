# handoffs/

> Ce qu'une **autre** session doit pouvoir reprendre. Versionné.

## `handoffs/` ou `workspace/scratch/` ?

| | `workspace/scratch/` | `handoffs/` |
|---|---|---|
| pour qui | la session **en cours** — ne pas perdre le fil, même après une compaction | une **autre** session, qui reprendra |
| versionné | non — volatile, jamais une source de vérité | oui |
| rangement | un dossier par chantier : `scratch/<projet>-<chantier>/` | un fichier par passation |

**Le passage se fait en fin de session**, quand un chantier continue ailleurs :
ce qui doit être repris passe de `scratch/` à un handoff (ou au backlog, à la
fiche du projet). Une compaction garde la même session : elle n'appelle pas de
handoff. La skill `brain` (`sessions.md`, « Où écrire ») le dit aussi.

## Écrire un handoff

Copier [`_template.md`](_template.md) en `handoffs/<sujet>-<AAAAMMJJ>.md`, et le
remplir : ce qui a été fait, l'état, **la prochaine étape concrète**, les
fichiers clés. C'est aussi le modèle d'un `/checkpoint`.

## Sa vie : `status:`

| statut | quand |
|---|---|
| `active` | écrit, attendu par une autre session |
| `consumed` | repris — `consumed_by:` dit par quelle session |
| `archived` | rangé dans `handoffs/archive/`, gardé pour l'histoire |

`brain doctor` le tient (« les handoffs disent s'ils sont attendus ») : un statut
hors de ces trois rougit, et un handoff `active` de plus de **14 jours** aussi —
le reprendre, ou le passer `consumed` ou `archived`.
