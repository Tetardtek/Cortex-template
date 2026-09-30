---
# Généré depuis docs/src/mettre-a-jour.md par scripts/docs-generer.py — ne pas éditer ici.
label: Se mettre à jour
groupe: Démarrer
ordre: 1.5
---

# Se mettre à jour — recevoir une nouvelle version du gabarit

> Ton fork porte à la fois le programme (le gabarit) et ta mémoire (projets,
> sessions, config). Une mise à jour **fusionne** les deux : git fait ce
> travail. Kernel v2.4.2.

Cette page décrit la méthode tant que le gabarit se distribue comme un dépôt
git : chaque version est un **tag** (`v2.3.3`…), posé par-dessus la précédente. <!-- docs-verite: permis -->

---

## Une seule fois : l'amont, en lecture seule

```bash
git remote add upstream <URL_DU_GABARIT>
git remote set-url --push upstream DISABLED   # ton fork porte ta mémoire : elle ne remonte jamais
```

Une fois l'amont déclaré, le briefing te dit quand une version plus récente
existe : une ligne, sans insister. Le timer `brain-maj` (posé par
`bash scripts/brain-engine.sh install systemd`) lit les tags de l'amont une fois
par jour, sans rien rapatrier ; le démarrage, lui, ne touche jamais au réseau.
Tu restes libre de mettre à jour, ou non.

## À chaque version

**1. Partir d'un état propre** : committer ton propre travail d'abord.

```bash
git status
```

**2. Récupérer, et regarder avant de fusionner**

```bash
git fetch upstream --tags
v=$(git tag -l 'v*' --sort=-v:refname | head -1)   # la version la plus récente
echo "$v"
git diff --stat HEAD..."$v"                        # ce qu'elle change depuis ton point de départ
```

La page ne nomme aucune version : c'est git qui la donne, et la commande reste
juste à la suivante.

**3. Fusionner le tag** : un tag plutôt que `main`, pour recevoir une version
publiée et non un état intermédiaire.

```bash
git merge "$v"
```

Git fait une fusion **à trois** : ce que tu avais reçu, ce que tu as changé,
ce que l'amont a changé. Un conflit n'arrive que sur un fichier que vous avez
modifié tous les deux. Garde tes ajouts, et prends ceux de l'amont.

**4. Réinstaller les unités et relancer le moteur** : il doit charger le
nouveau code, et une version peut changer ses unités systemd.

```bash
bash scripts/brain-engine.sh install systemd   # réécrit les unités, puis les relance
bash scripts/brain-engine.sh status
```

Un simple `systemctl --user restart` relancerait les unités **restées sur le
disque**, celles de ta version précédente : ce qu'une version change dans
l'environnement du moteur ne t'arriverait pas. `install systemd` sauvegarde à
côté une unité qu'il remplace, et `status` dit si les unités installées sont
restées celles d'une autre version.

Installé avec `--sans-service` : `bash scripts/brain-engine.sh stop`, puis `start`.

**5. Suivre le schéma de la base**

Le schéma sait ajouter une table chez toi, jamais en retirer une. Quand une
version retire des tables, ce script les retire de ta base :

```bash
bash scripts/schema-retraits.sh              # à blanc : la base visée, et ce qui partirait
bash scripts/schema-retraits.sh --appliquer
```

Il refuse tout si une seule de ces tables contient des lignes : ce sont
peut-être les tiennes. Exporte-les, vide la table, puis relance.

**6. Lire les notes de version** : elles disent ce qui se fait à la main, par
exemple une ligne à corriger dans ton `~/.claude/CLAUDE.md`, qui n'est pas dans
le dépôt.

**7. Le déclarer** : dans `brain-compose.local.yml`, passe `kernel_version` à
la nouvelle version. C'est la trace que les étapes après la fusion sont faites :
au boot, un écart entre elle et la version du gabarit signale une mise à jour
pas terminée.

---

## Ce qui ne bouge pas

Une mise à jour ne touche ni ta config de machine (`brain-compose.local.yml`),
ni tes secrets (`brain-secrets/`), ni ta base : ils ne sont pas dans le dépôt.
La base ne change que par l'étape 5, et seulement si tu l'appliques.
