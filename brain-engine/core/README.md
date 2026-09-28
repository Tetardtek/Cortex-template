# `core/` — le programme

> Construit dans ce dépôt et **pas dans `brain/`**, tranché le 06/09 : le CORE
> est un programme, `brain/` est de la data. Les mettre au même endroit
> reproduirait ce que Myéline sépare.
>
> En **Python**, tranché le 06/09 après mesure : Rust ne porte aucune des six
> capacités du CORE. Le coût — un artefact plus lourd — et la condition de
> réouverture sont écrits dans `vision.md`.

## Ce qui est là

| module | capacité | lignes | état |
|---|---|---|---|
| `persistance.py` | persistance — le pont vers la base | 291 | **24 garanties**, dont 3 sur la base vivante |
| `modele.py` | le pont vers le modèle d'embedding | 55 | sorti de `recherche.py` par le test de la fondation |
| `traces.py` | traces + écriture gouvernée | 188 | **17 garanties** · gel et commit confiné non couverts ici |
| `bsi.py` | BSI — claims **et verrous** | 328 | **39 garanties**, cycle complet sur base jetable |
| `recherche.py` | index+recherche — chercher | 227 | **17 garanties**, dont l'index réel : 6 057 chunks |
| `indexation.py` | index+recherche — construire | 270 | **34 garanties**, sans modèle ni service |
| `zones.py` | identité et zones | 122 | **25 garanties**, dont le registre réel |

```bash
python3 core/tests.py                      # tout ce qui ne demande aucun service
python3 core/tests.py --brain ~/Dev/Brain  # + la base et le modèle réels
```

⚠️ **Le test de la fondation** (`test_briques.py`) applique la règle de la
vision : *« retirer n'importe quelle brique doit laisser un système qui
démarre »*. Il a trouvé, dès son premier passage, que `indexation` tenait
`recherche` — pour un encodeur qui n'appartenait à aucune des deux. D'où
`modele.py`. Le **socle** est désormais un ensemble : les deux ponts vers
l'extérieur, la base et le modèle.

Et un test qui les enchaîne :

| | |
|---|---|
| `test_boucle.py` | **11 garanties** — de vrais fichiers du brain, indexés dans une base jetable, puis retrouvés |

```
5 fichiers → 68 chunks → 68 encodés en 1,5 s → les 3 requêtes retrouvent
le bon fichier dans les trois premiers résultats
```

C'est le seul test qui prouve que le CORE **fonctionne**, par opposition à
« chaque morceau tient ses promesses ». Six modules peuvent être justes
séparément et ne pas s'emboîter.

```bash
python3 core/test_persistance.py                      # 21 garanties, aucun disque touché
python3 core/test_persistance.py --dolt ~/Dev/Brain   # + lecture réelle, 35 tables
```

**174 garanties tenues, 0 manquée — les six capacités de sont là, et elles s'emboîtent.**

✅ **La dernière a été débloquée le 07/09**, non par du code mais par une
décision de Kevin : la zone d'écriture se dérive du niveau — `invariant` et
`programme` sont kernel — avec une exception déclarée, `profil/`, qui est
donnée souveraine **et** zone d'autorité. Écrite dans `NIVEAUX.yml`.

⚠️ **La politique de corpus n'est PAS dans le CORE, et c'est délibéré.**
`embed.py` porte `CORPUS_PATHS` et `EXCLUDE_PATTERNS` en dur — des listes qui
décrivent l'arborescence d'un brain précis. Quels fichiers indexer, sous quel
scope, avec quel TTL : c'est une décision **d'instance**. Le CORE reçoit des
chemins, il ne parcourt rien.

⚠️ Le **gel** et le **commit confiné** ne s'éprouvent qu'en écrivant dans une
base versionnée. Le brain est de la data : ces tests n'y écrivent rien.
`tools/test_dolt_discipline.py` les couvre sur une branche jetable, et
c'est lui qui fait foi pour ces deux garanties.

## La règle qui gouverne tout le reste

**Le CORE reçoit sa configuration, il ne la devine pas.** Aucun module n'a le
droit de déduire un chemin de sa propre position, de lire l'environnement à
l'import, ni de supposer qu'un fichier existe à côté de lui.

Ce n'est pas du purisme : `brain-engine/db.py` fait les trois, et c'est
pourquoi il est impossible de le faire tourner ailleurs que dans le brain qui
l'héberge — ni de le tester sans toucher la vraie base.

## Ce qu'on rapatrie, et ce qu'on relit

L'ancien moteur sert de **référence**, jamais de source de copie. Chaque module
est relu et redécidé. Ce qui est éprouvé — la traduction SQL portable, la
discipline d'écriture Dolt — est repris tel quel, avec sa raison ; ce qui tient
à l'installation est refait.
