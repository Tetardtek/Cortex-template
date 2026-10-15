---
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

<!-- genere:commandes -->

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
