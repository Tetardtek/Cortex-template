---
# Généré depuis docs/src/commandes.md par scripts/docs-generer.py — ne pas éditer ici.
label: Les commandes
groupe: Utiliser
ordre: 6.5
---

# Les commandes de `brain`

`brain` est le point d'entrée unique du brain. Installé par le paquet
`brain-cortex`, `pipx` le pose dans ton `PATH`. Dans un fork cloné par git,
c'est `scripts/brain`, et `brain-engine.sh install` le relie à `~/.local/bin/brain`.

## Toutes les commandes

La table vient de l'aide elle-même (`brain --help`) : une commande ajoutée à
l'aide apparaît ici à la génération suivante.

| Commande | Ce qu'elle fait |
|---|---|
| `brain init [nom] [dossier]` | créer un brain, ici ou dans ce dossier (les 13 étapes) ; relancé, il complète |
| `brain init --sans-service` | idem, sans systemd utilisateur (conteneur, essai) |
| `brain init --reecrire-claude-md` | idem, et remplacer ~/.claude/CLAUDE.md (l'ancien est sauvegardé) |
| `brain init --verifier` | les prérequis seulement — rien n'est écrit |
| `brain serve [http\|mcp]` | les portes réseau (HTTP + MCP), une seule déclaration |
| `brain serve --declaration` | ce qui serait lancé, sans rien lancer |
| `brain serve --ports` | les deux ports, en CLÉ=valeur — pour un script |
| `brain doctor` | ce qui se dégrade en silence — le brain se contrôle |
| `brain maj [version]` | un fork git : le plan vers la dernière version, ou celle-ci — rien ne bouge (le paquet : pipx upgrade) |
| `brain maj --appliquer` | recevoir la version : fusionner, régénérer, réinstaller |
| `brain maj --sans-unites` | avec --appliquer : sans réinstaller les unités systemd |
| `brain maj --sans-reseau` | sans relire les tags de l'amont |
| `brain vue [--construire]` | agents/ comme une vue du noyau et de l'instance |
| `brain vue --deverrouiller` | rendre le noyau modifiable le temps d'une mise à jour |
| `brain vue --satellites` | le .gitignore du dossier tait ses satellites (programme installé à part) |
| `brain aligne` | reprendre le tronc, le noyau verrouillé compris |
| `brain briefing [--projet P]` | le briefing du boot, calculé (helloWorld le lance) |
| `brain briefing --fiches P` | seulement les prochaines fiches d'un projet |
| `brain migrer [dossier]` | un brain git passe au paquet, une fois |
| `brain migrer --a-blanc` | dire ce qui serait fait — rien n'est touché |
| `brain migrer --annuler` | rendre le clone d'avant la migration |

## Ce que la table ne dit pas

- **`brain init`** se relance sans risque : il ne refait rien de ce qui est
  fait, et pose ce qui manque. Après un `pipx upgrade brain-cortex`, c'est lui
  qui met la version déclarée à jour — avec le même nom et le même dossier
  qu'à l'installation.
- **`brain doctor`** rend son verdict par son code de sortie : un script ou une
  CI peut s'y fier sans lire la sortie.
- **`brain maj`** reçoit une version du gabarit dans un fork cloné par git. Un
  brain servi par le paquet se met à jour par `pipx upgrade brain-cortex`, puis
  `brain init`. Les deux voies : [Se mettre à jour](mettre-a-jour.md).
- **`brain vue`** et **`brain aligne`** tiennent `agents/` comme une vue du
  noyau et de l'instance : [Architecture](architecture.md).
- **`brain migrer`** fait passer un brain cloné par git au paquet, une fois.
  `--a-blanc` d'abord.
