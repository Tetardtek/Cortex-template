---
label: Satellites
groupe: Comprendre
ordre: 5
---

# Les satellites — ta mémoire, à part du noyau

> Le noyau est le même dans chaque fork. Les satellites sont à toi : ce que tu
> fais, ce que tu apprends, ce que tu retiens.

---

## Les dossiers à part

Le gabarit les livre **vides**, chacun avec son `README.md` :

| Dossier | Ce qu'il garde |
|---|---|
| `projets/` | l'état de tes projets — un fichier par projet, à partir de `_template.md` |
| `handoffs/` | ce qu'une session laisse à la suivante |
| `infrastructure/` | la description de tes machines et services |
| `workspace/` | le travail en cours : le backlog (sa convention, son index et sa clôture — voir [La méthode](methode.md)), les brouillons |
| `todo/` | tes intentions et ce qui reste à faire |
| `toolkit/` | les patterns que tu as validés en production, réutilisables |
| `progression/` | ton parcours, tes compétences, ton métabolisme de sessions |
| `reviews/` | les revues d'agents |
| `learning/` | tes pistes d'apprentissage — ce qu'écrit une session `learning` |
| `vie/` | ce qui relève de ta vie plutôt que de ton travail — **privé : jamais indexé** |
| `contenu/` | ce que tu produis pour l'extérieur : atelier · publié · archive, lus par le MCP |

Le `.gitignore` du noyau ignore leur contenu, README mis à part : ce que tu y
écris ne se mélange jamais à l'historique du noyau.

`profil/` est à part : il arrive **avec** du contenu — les specs que le noyau
partage (`profil/specs/`), la forme de l'identité (`profil/identity.exemple/`),
`CLAUDE.md.example`. Il se versionne à part, mais sa partie invariante est du
**noyau** (`KERNEL.md`) : elle ne change qu'avec ta confirmation.

---

## Les versionner à part

Quand tu veux garder l'historique d'un satellite, ou le partager entre tes
machines, fais-en un dépôt :

```bash
cd ~/Dev/Brain/todo
git init
git add .
git commit -m "todo : premier état"
git remote add origin <URL_DE_TON_DEPOT>
git push -u origin main
```

Même geste pour les autres. Puis, depuis le dossier du brain :

```bash
bash scripts/install-brain-hooks.sh   # les hooks du satellite devenu dépôt
```

Trois satellites ont leurs propres hooks quand ils sont un dépôt — `handoffs/`
(la base suit les handoffs), `instance/agents/` et `progression/` (la vue suit
ta couche) : sans eux, le doctor rougit « hooks git installés ». L'installateur
les pose, et ne touche à rien d'autre.

Un brain **servi par le paquet** fait les deux en une commande :
`brain satellites --taire`. Elle tait le satellite en entier dans le `.gitignore`
du dossier, pose ses hooks, et **désuit** ce que le dossier suivait encore de lui
— les modèles de son premier commit (`README.md`, `_template.md`, `.gitkeep`) :
`git rm --cached`, jamais un fichier retiré du disque. Le dossier le dit ; la
suppression est à commiter (`git commit`). Sans ça, deux dépôts suivaient les
mêmes fichiers, et une retouche du `README.md` se voyait dans les deux.

---

## Plusieurs machines — `satellites.yml`

Une instance qui tourne sur plusieurs machines déclare ses satellites dans
`satellites.yml`, à la racine : chaque dépôt, son chemin, les machines qui
l'ont. `brain satellites` s'en sert :

| Commande | Effet |
|---|---|
| `brain satellites` | l'état de chaque dépôt, en lecture seule ; sortie 0 si tout est à jour |
| `brain satellites --tirer` | met à jour ce qui est en retard — en avance rapide seulement |
| `brain satellites --cloner` | clone ce qui est déclaré pour cette machine et absent |
| `brain satellites --discret` | avec l'état ou `--tirer` : ne dit que ce qui ne va pas |

Un dépôt dont le brain dépend sans le contenir se déclare avec un `chemin:`
absolu ou en `~/…` : il est suivi et cloné là, et sa clé n'est plus qu'un nom.

`--cloner` dérive l'URL d'un satellite de celle du brain (son remote `origin`, sans
le nom du dépôt). Un brain sans `origin` — celui que sert le paquet est un dépôt à
lui, souvent sans amont — déclare sa forge en tête de la liste :

```yaml
forge: git@ma-forge.example:moi      # l'URL de la forge, sans le nom du dépôt
satellites:
  profil: {depot: brain-profil, machines: [fixe, portable]}
```

Un satellite qui vit sur une **autre forge** que le brain (le brain sur une
forge publique, ses satellites sur la tienne) déclare son adresse entière,
`url:`. Elle passe avant tout le reste, `depot:` et `forge:` compris :

```yaml
satellites:
  profil: {url: git@ma-forge.example:moi/brain-profil.git, machines: [fixe, portable]}
  todo:   {depot: brain-todo, machines: [fixe]}   # la forge du brain, comme avant
```

Rien ne manque : `--cloner` réussit sans rien dire, `origin` ou pas. Il en manque et
aucune forge n'est connue : il nomme les manquants qui n'ont pas d'`url:`, et les
trois moyens (`git remote add origin <URL du brain>`, `forge:`, ou une `url:` par
satellite).

Sans `satellites.yml`, il ne fait rien : les satellites restent des dossiers.
Avec lui, l'installation (`brain init`) clone ceux de la machine.

### Un brain servi par le paquet

Installé par le paquet `brain-cortex` (pipx, avec son index : `installer-avec-claude.md`), le programme vit à part et ton dossier
ne garde que tes données — c'est un dépôt git à lui. `brain init` y fait le
ménage des satellites :

- son `.gitignore` tait **chaque satellite en entier** : les dossiers qui sont
  des dépôts git, et ceux que `satellites.yml` déclare (un dépôt ne s'embarque
  pas dans un autre) ;
- un satellite **à toi**, que le gabarit ne connaît pas, se déclare dans
  `satellites.yml` — le doctor (« niveaux déclarés ») le compte alors comme une
  entrée du brain ;
- les modèles du gabarit (`README.md`, `_template.md`, `.gitkeep`) ne se posent
  que dans un dossier absent ou vide, jamais dans un satellite qui a déjà ses
  données ;
- un dossier qui arrive avec ses handoffs : la base neuve les reçoit.

Ici, `satellites.yml` ne verrouille rien : il n'y a pas de noyau dans ton
dossier.

Partout, le doctor (« chaque satellite se lit ») interroge la forge de chaque
satellite par `git ls-remote`, sans rien écrire ni demander de mot de passe : il
rougit quand elle refuse (identifiants absents, clé refusée, dépôt introuvable) ou
quand un satellite est en retard sans pouvoir avancer en avance rapide ; hors
réseau, il s'abstient.

---

## La règle

Le noyau ne dépend jamais d'un satellite. Un satellite absent ou vide ne casse
rien : les scribes qui y écrivent n'ont simplement nulle part où écrire.
