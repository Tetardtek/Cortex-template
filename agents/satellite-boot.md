---
name: satellite-boot
type: agent
context_tier: cold
domain: [boot, satellite, sous-session]
status: active
origine: template
description: "Satellite boot — une sous-session à périmètre unique, sans le poids d'un boot complet"
brain:
  version:   1
  type:      protocol
  scope:     kernel
  owner:     human
  lifecycle: stable
  read:      trigger
  triggers:  [satellite, sous-session, parallele]
  ipc:
    receives_from: [human, orchestrator]
    sends_to:      [orchestrator, human]
    zone_access:   [project]
    signals:       [SPAWN, RETURN]
---

# Agent : satellite-boot

> Une session **satellite** est une sous-session ouverte à côté d'une session
> principale, sur un périmètre unique et étroit. Elle ne refait pas le boot
> complet : c'est tout son intérêt.

Écrit pour le template — générique, sans rien de l'instance qui l'a produit.

---

## Quand une satellite a du sens

Quand une tâche est **séparable** du fil principal : un correctif isolé, une
mesure longue, une exploration qui n'a pas besoin du contexte en cours.

Quand elle ne l'est pas — quand la tâche a besoin de ce que la session
principale sait — une satellite coûte plus qu'elle ne rapporte : il faut lui
réexpliquer ce que l'autre savait déjà.

---

## Ce qu'elle charge, et ce qu'elle ne charge pas

```
charge        le socle L0 · ce que son périmètre exige, et rien d'autre
ne charge pas les projets voisins · l'historique de la session principale
```

Une satellite qui charge autant qu'une session complète n'est pas une
satellite : c'est une seconde session, et il valait mieux le dire.

---

## Le claim, et pourquoi il compte plus ici qu'ailleurs

Deux sessions qui travaillent en parallèle **sur la même machine** peuvent
écrire dans les mêmes fichiers. Le claim est ce qui les rend visibles l'une à
l'autre.

```bash
bash scripts/bsi-claim.sh open <sess_id> \
  --scope "<perimetre>" --type <type> --parent <sess_id_du_parent>
```

Le lien au parent n'est pas décoratif : il dit **de qui** cette satellite
dépend, donc quoi fermer si le parent s'arrête.

**Avant d'écrire dans un fichier**, une satellite regarde s'il est déjà tenu :

```bash
bash scripts/bsi-query.sh open        # les sessions en cours et leur périmètre
```

Deux sessions sur le même fichier ne s'annulent pas mutuellement par magie. La
dernière qui écrit gagne, et la première ne l'apprend jamais.

---

## Fermer, et rendre

Une satellite se ferme **avant** son parent, et elle rend quelque chose :

```bash
bash scripts/bsi-claim.sh close <sess_id> --result <success|partial|fail> \
  --deliverables "<ce qui a bougé, en une ligne>"
```

Ce qu'elle rend n'est pas un résumé de ce qu'elle a fait — c'est **ce que le
parent doit savoir pour continuer**. Un fichier modifié, une décision prise, un
blocage rencontré. Le reste appartient à la satellite et meurt avec elle.

---

## Le piège, et il est courant

Une satellite qui s'allonge devient une session principale sans l'avoir décidé :
elle charge de plus en plus, touche à des périmètres voisins, et son claim ne
décrit plus ce qu'elle fait.

**Le signe qui ne trompe pas** : quand on commence à lui réexpliquer le contexte
général, elle a changé de nature. Il vaut mieux la fermer et ouvrir une vraie
session que de la laisser grossir sous un nom qui ne lui va plus.
