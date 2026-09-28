# BRAIN-INDEX.md — l'aiguillage des sessions

> Les sessions ne s'écrivent pas ici : elles vivent dans la base.

Chaque session ouvre un **claim** — un enregistrement dans la table `claims`
de la base Dolt, pas un fichier. Il n'y a rien à commiter, rien à pousser.

| Pour | Commande |
|---|---|
| ouvrir la session | `bash scripts/bsi-claim.sh open <sess_id> --type <type> --scope "<type>/<scope>"` |
| la fermer | `bash scripts/bsi-claim.sh close <sess_id> --result <success\|partial\|fail>` |
| voir les sessions ouvertes | `bash scripts/bsi-query.sh open` |
| les sessions des autres machines | `bash scripts/bsi-query.sh peers` |

Rien ne ferme un claim oublié tout seul : `bash scripts/bsi-claim.sh close-stale`
ferme ceux qui ont dépassé la durée de leur type de session.

Le détail : [docs/sessions.md](docs/sessions.md).
