# BRAIN-INDEX.md — l'aiguillage des sessions

> Les sessions ne s'écrivent pas ici : elles vivent dans la base.

Chaque session ouvre un **claim** — un enregistrement dans la table `claims`
de la base Dolt, pas un fichier. Il n'y a rien à commiter, rien à pousser.

| Pour | Commande |
|---|---|
| ouvrir la session | `brain sessions --ouvrir <sess_id> --type <type> --portee "<type>/<scope>"` |
| la fermer | `brain sessions --fermer <sess_id> --resultat <success\|partial\|fail>` |
| voir les sessions ouvertes | `brain sessions` |
| les sessions des autres machines | `brain sessions --toutes` |

Rien ne ferme un claim oublié tout seul : `brain sessions --fermer-vieilles`
ferme ceux qui ont dépassé la durée de leur type de session.

Le détail : [docs/sessions.md](docs/sessions.md).
