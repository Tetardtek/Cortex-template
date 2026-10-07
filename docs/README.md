<!-- Généré depuis docs/src/README.md par scripts/docs-generer.py — ne pas éditer ici. -->
# La doc du brain

> Kernel v3.4.3 — 58 agents, 6 types de session.

| Page | Pour |
|---|---|
| [Démarrer](demarrer.md) | installer un fork, du clone au premier `brain boot` |
| [Se mettre à jour](mettre-a-jour.md) | recevoir une nouvelle version du gabarit dans ton fork |
| [Sessions](sessions.md) | les types de session, ce qu'ils chargent, où ils écrivent |
| [Architecture](architecture.md) | le noyau, les satellites, l'instance, les zones |
| [Agents](agents.md) | les agents, groupés par ce qu'ils font |
| [Recettes](recettes.md) | quelle session, quels agents, pour quoi |
| [Brain-engine](moteur.md) | le moteur : commandes, modes, accès, recherche |
| [Satellites](satellites.md) | ta mémoire, à part du noyau |
| [Pulse](pulse.md) | où j'en suis, en un bloc |
| [Données](donnees.md) | la base Dolt |

---

## Comment cette doc reste vraie

Les pages s'écrivent dans `docs/src/`. `docs/` est **généré** — ne pas
l'éditer :

```bash
python3 scripts/docs-generer.py --ecrire   # docs/src → docs
python3 scripts/docs-generer.py --check    # 0 à jour · 1 en retard
python3 scripts/docs-verite.py --gabarit . # ce que la doc nomme existe-t-il ?
```

- **Ce qui se compte se calcule** : les nombres d'agents, de sessions, de
  tables sont mesurés dans le brain au moment de la génération.
- **Ce qui se liste se génère** : les types de session, les agents, les tables
  viennent des manifests, des agents et du schéma — pas d'une liste écrite.
- **Ce qui se nomme se vérifie** : `docs-verite.py` refuse une page qui cite
  un fichier, un agent, un type de session ou une commande qui n'existent pas,
  ou le vocabulaire de ce que le brain a supprimé.
- **Ce qui s'affiche ne s'invente pas** : pas de capture d'écran écrite à la
  main — une sortie décrite en mots ne ment pas le jour où elle change.
