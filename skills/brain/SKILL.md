---
# Généré depuis skills/brain/src/SKILL.md par scripts/docs-generer.py — ne pas éditer ici.
name: brain
description: >
  REQUIRED when working inside a brain — a Claude Code memory system with
  KERNEL.md, agents/, contexts/session-*.yml, brain-engine/ and a Dolt base.
  Use when the task touches: session claims (bsi-claim.sh, claims, signals),
  session types or manifests (brain boot, contexts/), agents (agents/*.md,
  CATALOG.yml), the kernel and its gates (KERNEL.md, brain-constitution.md,
  profil/), brain-engine (API routes, MCP server, embeddings, brain-engine.sh),
  the Dolt base or db.py, the brain's docs (docs/, docs/src/), satellites
  (satellites.yml), publishing the template (sync-template.sh), or the daily
  work gestures inside a brain: committing, opening or merging a PR, testing
  in a worktree, running the doctor, keeping the backlog (fiches, kanban).
  Triggers: brain boot, claim, BSI, kernel, KERNEL.md, agent, brain-engine, MCP,
  Dolt, db.py, docs-generer, docs-verite, satellite, template, gabarit, commit,
  PR, merge, fusionner, worktree, doctor, backlog, fiche, kanban, tenir.
---

# Le brain — mode d'emploi pour l'agent

Kernel v3.5.0 — 58 agents, 6 types de session,
23 routes d'API, 10 outils MCP.

Un brain est une mémoire externe pour les sessions Claude Code : des agents
qui persistent, des types de session qui chargent ce qu'ils déclarent, et une
base Dolt versionnée. Cette skill dit comment y travailler sans le casser.

*Les nombres et les listes de ces pages sont **générés** depuis le brain
(`scripts/docs-generer.py`), et ce qu'elles nomment est **vérifié**
(`scripts/docs-verite.py`). Si une page contredit le code, c'est la page qui a
tort — et c'est un défaut à signaler, pas à contourner.*

## Quand l'utiliser

- ouvrir, fermer ou lire une session (claims, signaux) ;
- toucher un agent, un manifest de session, le noyau ;
- travailler sur `brain-engine/` — l'API, le serveur MCP, la recherche ;
- lire ou écrire la base ;
- écrire ou corriger la doc du brain ;
- publier le gabarit ;
- installer un brain sur une machine : `brain init` (`brain init --verifier` : les
  prérequis seulement, rien n'est écrit) ;
- savoir si le brain est sain : `brain doctor`.

## Les règles qui ne se discutent pas

1. **Le noyau ne change qu'avec une confirmation humaine explicite.**
   `KERNEL.md`, `brain-constitution.md`, les agents, la partie invariante de
   `profil/` : proposer la diff, attendre le oui. → [`noyau.md`](noyau.md)
2. **Une session a un claim.** Ouvert au début, fermé à la fin, par
   `scripts/bsi-claim.sh` — jamais un fichier, jamais une écriture directe en
   base. → [`sessions.md`](sessions.md)
3. **La base passe par `brain-engine/db.py`.** Un script qui ouvre sa propre
   connexion écrit dans une base que personne ne lit. → [`donnees.md`](donnees.md)
4. **`docs/` et les pages de cette skill sont générés.** On édite la source
   (`docs/src/`, `skills/brain/src/`), puis `python3 scripts/docs-generer.py --ecrire`.
   → [`doc.md`](doc.md)
5. **Les secrets ne se lisent pas.** `brain-secrets/MYSECRETS` n'est jamais
   affiché, ni cité, ni copié dans une commande.
6. **Chaque commit porte un type**, parmi `kernel:`, `feat:`, `fix:`, `bsi:`, `integrator:`, `scribe:`, `todo:`, `toolkit:`, `config:` — et aucun autre :
   le hook `commit-msg` refuse le reste. Il dit quel scribe possède le
   changement. Le tableau : `KERNEL.md`, « Commit types ».
7. **Ce qui tourne n'est pas une cible d'essai.** Le moteur, la base, les
   services de la machine : on les lit dans le code, on ne les sonde pas pour
   voir. Un essai se fait dans un bac à sable : HOME jetable, ports décalés, rien
   de la machine en commun.
8. **`agents/` est une vue de liens : la lire les suit, la fouiller non.**
   `grep -r`, `rg` et `find -type f` n'y voient que les quelques agents assemblés,
   et rendent « rien » sans le dire. `grep -R`, `rg -L`, `find -L` — ou chercher
   dans les cibles, `noyau/agents/` et `instance/agents/`. → [`noyau.md`](noyau.md)

## Le doctor : `brain doctor`

Après une PR, une mise à jour, ou avant de dire « fini » : `brain doctor`
(`bash scripts/brain doctor` sans la commande). Son **code de sortie** est le
verdict — 0, aucune dérive. Une ligne ❌ dit ce qu'elle laisserait passer et ce
qu'elle a constaté ; une ligne ⏭️ s'abstient, et dit pourquoi. **Un rouge se
corrige à sa cause, jamais dans le contrôle** — et un contrôle qui s'abstient ne
compte pas comme vert. Le détail : `docs/moteur.md`, « brain doctor ».

## Les pages

- [`sessions.md`](sessions.md) — les types, ce qu'ils chargent, le claim
- [`noyau.md`](noyau.md) — les zones, les gates, ce qu'on ne touche pas seul
- [`moteur.md`](moteur.md) — brain-engine : commandes, routes, outils MCP, accès
- [`donnees.md`](donnees.md) — la base Dolt, `db.py`, les tables
- [`doc.md`](doc.md) — écrire la doc sans qu'elle mente

Si un dossier `instance/` existe à côté de ce fichier, ses pages décrivent
**cette** instance (ses outils, sa méthode) : lis-les aussi. C'est un lien vers
`instance/skill/` du brain, posé par `brain vue`. Il n'est jamais
distribué.
