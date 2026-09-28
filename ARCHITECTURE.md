# ARCHITECTURE — pourquoi le brain est fait comme ça

> Les décisions qui ne s'expliquent pas d'elles-mêmes, et leur raison. Comment
> les pièces s'assemblent : [docs/architecture.md](docs/architecture.md). La
> loi qui fait foi : [KERNEL.md](KERNEL.md).

---

## Trois couches, pas deux

```
noyau        les règles, les agents, les manifests de session, les scripts,
             le moteur — le même dans chaque fork
satellites   ta mémoire : todo/, toolkit/, progression/, reviews/
             (profil/ se versionne comme eux, mais sa partie invariante est du noyau)
instance     ta machine : brain-compose.local.yml, brain-engine/.env.local,
             la base brain-dolt/, tes secrets
```

La ligne entre le noyau et ce qui est à toi est évidente. La couche instance
l'est moins : elle existe parce qu'un même brain tourne sur plusieurs machines,
avec des chemins, des ports et des services différents. Sans elle, ces valeurs
finissent écrites dans le noyau — et le noyau ne se partage plus.

## Le patron `.env`

```
brain-compose.yml          versionné, le programme
brain-compose.local.yml    ignoré par git, cette machine
profil/CLAUDE.md.example   versionné, avec des <PLACEHOLDERS>
~/.claude/CLAUDE.md        hors du dépôt, la configuration vivante
```

Toute valeur qui change d'une machine à l'autre vit dans un fichier local.
Jamais dans le noyau.

## Des types de session plutôt qu'un chargement complet

Charger tout le brain au démarrage coûte le contexte dont la session aura
besoin plus tard. Chaque type de session a donc un manifest
(`contexts/session-<type>.yml`) qui dit ce qu'il charge d'office — le reste
arrive à la demande.

Le coût assumé : un chargement sélectif peut manquer quelque chose. On a
préféré un brain qui démarre léger et charge ce qu'on lui demande à un brain
qui démarre plein.

## Déclarer plutôt que verrouiller

Plusieurs sessions peuvent tourner en même temps. Aucune ne bloque les autres :
chacune **déclare** ce qu'elle fait — un claim, en base, avec une durée de vie.
Quand deux sessions se croisent, elles se voient ; l'humain décide. Un claim
oublié se ferme par `close-stale`, passé la durée de vie de son type.

## Une base versionnée

Ce qui est structuré — claims, intentions, todos, décisions, l'index de
recherche — vit dans Dolt, une base SQL versionnée comme git : chaque
changement se commite et se compare. Ce qui se raconte reste en Markdown, parce
qu'un récit se lit mieux qu'il ne se requête.

## Les scribes — chacun son territoire

Un agent métier ne réécrit pas le brain lui-même : il signale, et le scribe du
territoire écrit. Sans ça, chaque agent écrit partout et le brain dérive ; avec
ça, chaque fichier a un responsable. La carte des territoires :
`profil/specs/scribe-system.md`.

## Le noyau se protège

Les fichiers qui font la loi — `KERNEL.md`, `brain-constitution.md`, la partie
invariante du profil — ne changent qu'avec une confirmation humaine explicite ;
les agents, eux, se modifient sous la garde d'un scribe (`KERNEL.md`,
« Protection graduée »). Un brain qui peut réécrire ses propres règles sans qu'on le voie
n'a plus de règles.

## La doc se vérifie comme du code

Une doc n'échoue jamais : elle ment. Celle du brain est générée depuis ce que
le brain contient (`scripts/docs-generer.py`), et ce qu'elle nomme est vérifié
contre le gabarit avant chaque publication (`scripts/docs-verite.py`).

---

## Pour aller plus loin

- créer un agent → `agents/_template.md` et `agents/_conventions.md`
- les scribes → `profil/specs/scribe-system.md`
- le protocole des sessions → `profil/specs/bsi-spec.md`
- les règles de collaboration → `profil/specs/collaboration.md`
