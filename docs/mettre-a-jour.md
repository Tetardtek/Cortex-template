---
# Généré depuis docs/src/mettre-a-jour.md par scripts/docs-generer.py — ne pas éditer ici.
label: Se mettre à jour
groupe: Démarrer
ordre: 1.5
---

# Se mettre à jour — recevoir une nouvelle version du gabarit

> Ton fork porte à la fois le programme (le gabarit) et ta mémoire (projets,
> sessions, config). Une mise à jour **fusionne** les deux : git fait ce
> travail. Kernel v3.2.0.

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

## En une commande : `brain maj`

```bash
brain maj                  # le plan : ta version, celle de l'amont, ce qui change — rien ne bouge
brain maj --appliquer      # la recevoir
```

`brain maj` joue les étapes ci-dessous d'un bout à l'autre : il fusionne le
tag, recalcule les fichiers que le brain génère, réinstalle les unités et
déclare la version. Il ne se lance jamais seul.

- **Ce que tu as créé ne bouge pas** : tes pistes, ton profil, tes todos
  (git ne les voit pas), tes projets et tes agents (l'amont n'a pas ces
  fichiers). Ce que tu as modifié du gabarit est fusionné, pas écrasé.
- **Un fichier généré ne se fusionne pas, il se recalcule** : le catalogue
  des agents, la table des pistes, les pages de la doc. L'amont gagne, puis le
  calcul est refait chez toi, et tes agents et tes pistes y reviennent. La
  version d'avant de chacun est gardée dans
  `workspace/scratch/brain-maj-<version>/`, avec les commandes pour comparer.
- **C'est le `brain maj` de la version reçue qui la reçoit** : le tien passe la
  main au `scripts/maj.py` de la version, s'il diffère. Ce qu'elle apprend à la
  mise à jour te sert dès cette fois, pas à la suivante. Il prend la main dès le
  plan : `brain maj` tout court fait déjà tourner le code de la version que tu
  suis — celui que `--appliquer` ferait tourner de toute façon. « Le plan ne
  bouge rien » est donc la promesse de la version reçue.
- **Ta surcouche d'agents se relit, elle ne s'écrase pas** : un complément
  (`instance/agents/<nom>.complement.md`) suit le nouvel agent tout seul ; une
  surcharge (`instance/agents/<nom>.md`) le remplace en entier, et ce que le
  noyau y change ne t'arrive pas. Le plan nomme chaque surcharge concernée, et
  la liste, avec le diff de chacune, est posée dans
  `workspace/scratch/brain-maj-<version>/surcharges.md` — à relire avec ton
  brain, qui te proposera de reprendre ou de réduire la surcharge en complément.
- **Ce que la version range en satellites et que ton dépôt suit encore** (des
  projets commités avant qu'ils soient des satellites) : le plan le dit. Git ne
  les retire pas — rien ne se perd ; versionne-les à part quand tu veux
  ([les satellites](satellites.md)).
- **Un fichier à toi, là où la version en livre un, l'arrête aussi** : git
  écraserait sans un mot un fichier qu'il ignore (ta donnée, dans un satellite)
  si la fusion apporte un fichier suivi au même chemin. Le plan le nomme ;
  déplace-le, puis relance.
- **Un conflit sur un fichier écrit à la main l'arrête avant toute fusion** :
  il le nomme, et le choix est le tien. Fusionne à la main (étape 3), puis
  relance `brain maj --appliquer` pour la suite.

Les étapes, pour les faire à la main ou comprendre ce qu'il fait :

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
le dépôt. Relancer `brain-setup.sh` pour une étape ne touche pas à ton
`~/.claude/CLAUDE.md` : s'il diffère du modèle, le modèle est posé à côté
(`CLAUDE.md.modele`), à comparer et fusionner à la main.

**7. Le déclarer** : dans `brain-compose.local.yml`, passe `kernel_version` à
la nouvelle version. C'est la trace que les étapes après la fusion sont faites :
au boot, un écart entre elle et la version du gabarit signale une mise à jour
pas terminée.

---

## Ce qui ne bouge pas

Une mise à jour ne touche ni ta config de machine (`brain-compose.local.yml`),
ni tes secrets (`brain-secrets/`), ni ta base : ils ne sont pas dans le dépôt.
La base ne change que par l'étape 5, et seulement si tu l'appliques.
