# Écrire la doc sans qu'elle mente

Une doc n'échoue jamais : elle ment. Celle du brain — et les pages de cette
skill — suivent cinq règles.

1. **Une source.** On édite `docs/src/` et `skills/brain/src/` ; `docs/` et
   `skills/brain/` sont générés. La vitrine du gabarit a ses sources dans
   `gabarit/`.
2. **Ce qui se compte se calcule** : `{{NB_AGENTS}}`, jamais « 75 » écrit à la
   main. Valeurs : `VERSION`, `NB_AGENTS`, `NB_SESSIONS`, `NB_TABLES`,
   `NB_VUES`, `NB_ROUTES`, `NB_OUTILS`.
3. **Ce qui se liste se génère** : un bloc `<!-- genere:NOM -->` sur sa propre
   ligne — `sessions`, `agents`, `tables`, `routes`, `outils`.
4. **Ce qui se nomme se vérifie** : chaque fichier, agent, type de session et
   commande cité doit exister dans le gabarit ; le vocabulaire de ce que le
   brain a supprimé est refusé.
5. **Ce qui s'affiche ne s'invente pas** : pas de sortie d'écran écrite à la
   main ; la décrire en mots.

```bash
python3 scripts/docs-generer.py --ecrire          # sources → pages
python3 scripts/docs-generer.py --check           # 0 à jour · 1 en retard
python3 scripts/docs-verite.py --gabarit <rendu>  # 0 vrai · 1 faux
```

Une ligne qui doit citer un nom retiré — pour dire qu'il l'est — le déclare en
fin de ligne : `<!-- docs-verite: permis -->`. Même chose pour une version
passée donnée en exemple : une version `vN.N.N` écrite en dur qui n'est pas
celle du gabarit rougit (règle `version`) — une commande qui la nomme est juste
le jour où on l'écrit. Pour la version courante, laisser git la donner.

Avec `--brain <brain>`, les agents du gabarit sont jugés aussi, sur une seule
règle (`renvoi`) : un agent qui renvoie à un agent absent du gabarit l'écrit
« si présent » sur la ligne.

La publication (`sync-template.sh`) régénère la doc depuis le gabarit rendu et
**refuse de publier** si elle dit faux.
