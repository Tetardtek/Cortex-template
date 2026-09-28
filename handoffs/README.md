# handoffs/

> Briefs structures pour deleguer du travail entre sessions ou instances.

## Contenu attendu

Un fichier par handoff : `handoffs/brief-<scope>.md`

Chaque brief contient :
- Scope exact (fichiers/repertoires concernes)
- Tache a accomplir
- Contraintes et criteres de succes
- Session pilote de reference

## Pourquoi

Les handoffs permettent de deleguer du travail a une instance satellite
ou de reprendre le contexte dans une nouvelle session sans perte d'information.
L'agent `integrator` les consomme pour executer les taches deleguees.
