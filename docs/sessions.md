---
# Généré depuis docs/src/sessions.md par scripts/docs-generer.py — ne pas éditer ici.
label: Sessions
groupe: Comprendre
ordre: 2
---

# Les sessions

> Une session, c'est une conversation avec le brain, du `brain boot` à la
> fermeture de son claim. Son **type** dit ce qu'elle charge et où elle a le
> droit d'écrire.

---

## Les 6 types

| Type | Posture | Se lance par | Claim | Contexte au boot | Agents chargés d'office |
|---|---|---|---|---|---|
| **brain** | je construis le système | `brain boot brain[/<scope>]` | 4 h | ~22% | `coach-boot` · `coach` · `brain-guardian` · `scribe` |
| **chill** | je suis là | `brain boot chill` | 12 h | ~12% | `coach-boot` · `learning-journal` |
| **explore** | je réfléchis / je navigue | `brain boot explore[/<scope>]` | 8 h | ~18% | `coach-boot` · `coach` · `pulse` |
| **learning** | je découvre / j'expérimente | `brain boot learning[/<track>]` | 4 h | ~15% | `coach-boot` · `coach` |
| **pilote** (owner) | j'orchestre (long, multi-scope) | `brain boot pilote[/<project>]` | 12 h | ~35% | `coach` · `helloWorld` · `secrets-guardian` |
| **work** | je produis | `brain boot work[/<project>]` | 4 h | ~25% | `coach-boot` · `coach` · `debug` · `code-review` · `security` |

*Généré depuis `contexts/session-*.yml` : chaque type y a son manifest. « Claim »
est la durée de vie déclarée d'une session : au-delà, `close-stale` peut la
fermer. « Contexte au boot » est une **cible déclarée** par le manifest, pas une
mesure.*

La syntaxe est toujours la même : `brain boot <type>[/<scope>]`. Le scope est un
projet (`brain boot work/mon-site`), un thème (`brain boot explore/brainstorm`)
ou une piste d'apprentissage (`brain boot learning/rust`).

---

## Ce qui se charge — quatre couches

```
L0   le socle, identique pour tous les types : KERNEL.md, PATHS.md,
     brain-compose.local.yml
L1   ce que CE type charge toujours — dont les agents du tableau ci-dessus
L2   ce qui dépend du scope : projets/<projet>.md s'il existe
     (learning/<piste>.md en session learning)
L3   tout le reste, à la demande : « charge l'agent testing »
```

Le fichier d'instructions global (`~/.claude/CLAUDE.md`) est lu à chaque
session, quel que soit le type, et charge sa propre liste : elle **s'ajoute**
à L0.

---

## Où chaque type peut écrire

| Type | Écrit | N'écrit pas |
|---|---|---|
| **work** | ton projet, l'instance, les satellites | le noyau |
| **brain** | le noyau (`agents/`, `profil/`), l'instance, les satellites | ton projet |
| **explore** | `todo/` | le reste — et rien du tout en `explore/audit`, sauf le rapport |
| **pilote** | tout, avec une confirmation sur les décisions irréversibles | — |
| **chill** | à la demande | — |
| **learning** | `learning/`, `todo/`, tes projets | le noyau |

En session `brain`, écrire dans `KERNEL.md`, `CLAUDE.md`, `brain-constitution.md`
ou la partie invariante de `profil/` demande **ta confirmation explicite**.
La règle complète est dans `KERNEL.md`.

---

## Le claim — la trace d'une session

Chaque session ouvre un **claim** : un enregistrement dans la base (table
`claims`), pas un fichier. Il dit qu'une session existe, sur quel périmètre,
depuis quand — deux sessions parallèles se voient ainsi.

```bash
bash scripts/bsi-claim.sh open <sess_id> --scope "<type>/<scope>" --type <type>
bash scripts/bsi-claim.sh close <sess_id> --result <success|partial|fail>
```

À la fermeture, `--energy`, `--intention`, `--tags` et `--deliverables`
racontent la session ; la durée se calcule seule. Rien ne ferme
un claim oublié tout seul : `bash scripts/bsi-claim.sh close-stale` ferme ceux
qui ont dépassé la durée de leur type — mieux vaut fermer soi-même, avec le
résultat qu'on est seul à connaître.

---

## Fermer une session

Dis-le simplement — « on ferme », « c'est bon pour aujourd'hui ». Le brain
met à jour ce qui doit l'être (todos, projets, décisions) puis ferme le claim.
En `chill`, il ne propose jamais de fermer : c'est toi qui le dis.
