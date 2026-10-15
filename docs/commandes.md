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
| `brain servir [http\|mcp]` | les portes réseau (HTTP + MCP), une seule déclaration |
| `brain servir --declaration` | ce qui serait lancé, sans rien lancer |
| `brain servir --ports` | les deux ports, en CLÉ=valeur — pour un script |
| `brain doctor` | ce qui se dégrade en silence — le brain se contrôle |
| `brain maj [version]` | un fork git : le plan vers la dernière version, ou celle-ci — rien ne bouge (le paquet : pipx upgrade) |
| `brain maj --appliquer` | recevoir la version : fusionner, régénérer, réinstaller |
| `brain maj --sans-unites` | avec --appliquer : sans réinstaller les unités systemd |
| `brain maj --sans-reseau` | sans relire les tags de l'amont |
| `brain vue [--construire]` | agents/ comme une vue du noyau et de l'instance |
| `brain vue --deverrouiller` | rendre le noyau modifiable le temps d'une mise à jour |
| `brain satellites` | l'état des satellites de cette machine — rien ne bouge |
| `brain satellites --tirer` | avancer ce qui est derrière (avance rapide seulement) |
| `brain satellites --cloner` | cloner les satellites déclarés et absents |
| `brain satellites --taire` | le .gitignore du dossier tait ses satellites (programme installé à part) |
| `brain satellites --discret` | avec l'état ou --tirer : ne dire que ce qui ne va pas |
| `brain sessions` | les sessions ouvertes ici, et leurs claims — rien ne bouge |
| `brain sessions --toutes` | les sessions ouvertes sur toutes les machines |
| `brain sessions --vieilles` | ouvertes depuis plus que leur durée de vie |
| `brain sessions --orphelines` | ouvertes, mais la session Claude Code ne vit plus |
| `brain sessions --non-declarees` | vivantes dans le brain, sans claim qui les déclare |
| `brain sessions --ouvrir <id> --portee P --type T` | ouvrir le claim d'une session (les autres options : brain sessions --help) |
| `brain sessions --prolonger` | la session est vivante : repousser l'expiration |
| `brain sessions --fermer [<id>] --resultat R` | fermer le claim de cette session (une autre : <id> --pas-le-mien) |
| `brain sessions --fermer-vieilles` | fermer celles qui ont passé leur durée de vie |
| `brain sessions --rattacher` | reprendre le claim d'une identité remplacée |
| `brain sessions --discret` | avec --orphelines ou --prolonger : rien s'il n'y a rien |
| `brain signaux` | ce qui m'attend, ici et chez les peers — rien ne bouge |
| `brain signaux --pour <dest>` | la boîte d'un autre destinataire (une instance, une session) |
| `brain signaux --envoyes` | les 20 derniers signaux émis d'ici, et leur état |
| `brain signaux --envoyer <dest> --type T --message M [--projet P]` | émettre un signal |
| `brain signaux --accuser <sig_id>` | une fois traité — jamais d'office |
| `brain etat` | l'instant : les sessions ouvertes ici, les verrous, les signaux — rien ne bouge |
| `brain etat --verrous` | les verrous seulement |
| `brain schema` | la base suit-elle le schéma ? ce qu'une version a retiré — rien ne bouge |
| `brain schema --appliquer` | retirer ces tables ; refusé tout entier si une seule porte des lignes |
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

## La langue des commandes

Une convention, tenue partout — pour que la commande ne devienne pas un
mélange de deux langues. Un verbe ou une option qui s'ajoute la suit.

- **En français**, en minuscules, sans accents : un mot qui n'en a pas besoin
  de préférence (`--tirer` plutôt que « récupérer »), sinon l'accent tombe
  (`--deverrouiller`, `--reecrire-claude-md`).
- **Les mots communs aux deux langues** restent tels quels : `init`,
  `satellites`, `briefing`, `ports`, `http`, `mcp`.
- **L'exception** : `doctor` — un usage établi (`brew doctor`,
  `flutter doctor`), et le seul anglicisme de la commande.
- **Une action est une option** du verbe (`brain maj --appliquer`), pas un mot
  qui le suit ; `brain servir [http|mcp]` nomme une porte, pas une action.
- **Un nom renommé reste un alias**, hors de l'aide : `serve`, le nom d'avant,
  lance toujours `brain servir`, et `--pull` toujours `--tirer`. Rien ne casse
  chez un fork.

La forme (minuscules, sans accents, l'exception nommée ici) est vérifiée par
un test ; le français lui-même, par la relecture.
