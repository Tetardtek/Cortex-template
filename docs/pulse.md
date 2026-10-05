---
# Généré depuis docs/src/pulse.md par scripts/docs-generer.py — ne pas éditer ici.
label: Pulse
groupe: Utiliser
ordre: 9
---

# Pulse — où j'en suis

> Tu reviens après trois jours. Quels chantiers sont ouverts, qu'est-ce qui a
> bougé, c'est quoi la suite ? Pulse répond en un bloc.

---

## Trois façons de l'appeler

```
pulse              tous les chantiers, les dernières sessions, les derniers commits
pulse <projet>     le même zoom, sur un seul projet
brain boot explore     pulse s'intègre au briefing de la session
```

L'agent `pulse` lit le focus (les fiches en cours, calculées des PR
fusionnées), la base — claims, sessions — et le journal git. Il n'invente rien : une donnée absente s'affiche comme absente.

Il est chargé d'office en session `explore` ; partout ailleurs, dis simplement
« pulse ».

---

## Quand la base ne répond pas

Pulse se rabat sur le journal git seul, et le dit : le bloc porte
« Dolt offline — pulse partiel ». Tu vois les derniers commits, pas les
sessions.

---

## Pourquoi il existe

Sans lui, reprendre un chantier c'est relire la fiche du projet, les todos, le
journal git, et se rappeler où on s'était arrêté. Le brain sait déjà tout ça :
pulse le dit.
