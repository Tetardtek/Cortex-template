#!/usr/bin/env python3
"""Un document d'etat annonce-t-il encore ouvert ce que la forge a fusionne ?

Ce qui pourrirait en silence sans lui : **une carte qui ment plus vite qu'elle
ne se corrige.**

Le 17/09, `handoffs/LATEST.md` annoncait toujours :

    **neuf PR ouvertes**, et un ordre de fusion qui n'est pas libre.
    brain#56  brain#57  brain#58  myeline#2
    ⚠️ `brain#56` **AVANT** `myeline#2` (sinon le doctor rougit en permanence)

Les quatre etaient fusionnees depuis la veille. Le document ne se trompait pas
sur un detail : il reclamait un travail deja fait, dans un ordre devenu sans
objet. Et c'etait la quatrieme fois en douze jours qu'un document d'etat
decrivait un monde revolu — l'ecart se resserrant a chaque fois : quatre jours,
puis deux semaines, puis une demi-journee, puis quelques heures.

`cloture_backlog.py` garde l'autre moitie du probleme — un item **clos** porte
t-il son rapport. Il dit lui-meme ne pas savoir faire celle-ci :

    Il ne devine pas non plus qu'un item ouvert est en fait clos.
    Cette moitie-la reste humaine.

Elle ne l'est plus pour les PR, parce qu'une PR fusionnee laisse une trace
verifiable. Pour le reste — un chantier « en cours » qui ne l'est plus — elle
le demeure, et ce controle ne pretend pas y toucher.

    python3 tools/annonce_vs_forge.py --brain ~/Dev/Brain

── Le perimetre, et pourquoi il est etroit ─────────────────────────────────

Tranche avec l'owner le 17/09 : seuls les documents qui **pretendent dire l'etat
courant** sont juges.

    handoffs/LATEST.md · projets/*.md · workspace/live-states.md

Un handoff **date** est un instantane : `myeline-soiree-20260915.md` a raison
d'ecrire « neuf PR ouvertes », c'etait vrai ce soir-la. Le juger perime
demanderait de reecrire l'histoire pour verdir un rouge — le piege de
et. Le menteur n'est pas l'archive, c'est `LATEST` qui en recopie le
bloc et le presente comme aujourd'hui.

Le frontmatter ne sert a rien pour trancher : **22 handoffs sur 30 portent
`status: active`**, dont un clos depuis quinze jours. Un champ que rien ne
tient — une famille de defauts deja vue. Le discriminant honnete est
le nom du fichier : un handoff date EST une archive.

── 🔴 Le verdict est asymetrique, et c'est la mesure qui l'impose ──────────

    la forge prouve la fusion   ->  FAIT      — on peut rougir
    la forge ne prouve rien     ->  DOUTE     — jamais « ouverte »

Trois angles morts **mesures**, pas supposes :

    fusion en rebase   ne laisse AUCUN commit de fusion. `mon-site` en a zero,
                       et annonce pourtant « PR #4 fusionnee en rebase ».
    clone en retard    `mon-site` : dernier fetch le 11/09, six jours avant.
    depot tiers        mon-portage (#3 #4 #5), mon-outil (#28) vivent sur GitHub
                       et ne sont clones nulle part ici.

Affirmer « cette PR est ouverte » sur un clone vieux de six jours, ce serait
exactement : confondre **un depot muet** avec **un depot sans
fusion**. Le controle ne le fait jamais — et il **nomme** ce qu'il n'a pas pu
mesurer, au lieu de le taire. Un controle qui tait ses angles morts est celui
qui a produit.

── Deux detecteurs, parce qu'un seul voit un mode de fusion sur trois ──────

    1. `Merge pull request ... (#N)`   la fusion en mode `merge`, sur --all :
                                      un commit de fusion est une preuve ou
                                      qu'il soit.
    2. un commit suffixe `(#N)`        rebase et squash, que Gitea suffixe du
       sur une branche d'integration  numero de PR. Restreint a main/master/
                                      dev-* : ailleurs le suffixe pourrait
                                      preceder la fusion.

── Il n'ecrit rien, et ne joint personne ──────────────────────────────────

Aucun reseau, aucun jeton : `git log` local suffit. L'auto-epreuve travaille
dans un repertoire temporaire, sur de faux depots qu'elle cree et detruit.

Sortie 1 si un document d'etat reclame un travail que la forge dit fait.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fiches  # noqa: E402 — la table des alias vit dans le brain

_ok = _ko = 0

# ── Le vocabulaire, tire des documents reels, pas invente ──────────────────
#
# Chaque motif a ete releve dans un document du perimetre. Les garder lisibles
# ici est deliberer : la liste est la partie faillible du controle, elle doit
# pouvoir etre discutee sans lire le code.
ATTENTE = re.compile(
    r"PR\s+ouvertes?"
    r"|\bouvertes?\b(?![^.]{0,40}\bfusionn)"
    r"|\ba\s+relire\b|\bà\s+relire\b"
    r"|\battend(?:ent)?\b"
    r"|\bne\s+pas\s+fusionner\b"
    r"|\ba\s+fusionner\b|\bà\s+fusionner\b"
    r"|\bnon\s+fusionn|\bpas\s+merg|\bPAS\s+merg"
    r"|\bordre\s+de\s+fusion\b",
    re.I)

# 🔴 `AVANT` vit a part, et SANS `re.I` — trouve en relisant le diff avec l'owner.
# Sous `re.I` il captait n'importe quel « avant » : mesure sur le perimetre,
# 237 minuscules contre 22 majuscules. « contacter avant le 12 aout » n'est pas
# un ordre de fusion. Aucun faux rouge n'en etait encore sorti, parce que le
# rouge exige AUSSI une PR fusionnee sans apaisement dans la meme section —
# mais c'etait de la chance, pas de la conception.
ATTENTE_CASSE = re.compile(r"\*\*AVANT\*\*|\bAVANT\b")

# 🔴 Deux resserrements de plus, mesures le 26/09 sur `projets/mon-app.md`.
#
# Le controle rougissait sur `mon-app#44` et la section disait mot pour mot
# l'inverse : « sept PR fusionnees, toutes vertes … #38 a #44. **Aucune PR
# ouverte.** » Deux declencheurs, tous deux faux :
#
#     l.43  « Aucune PR ouverte. »            -> `PR ouverte` dans une NEGATION
#     l.53  « Plus une question ouverte : … » -> « ouverte » attache a une
#                                                QUESTION, pas a une PR
#
# L'audit du 24/09 avait accuse `APAISEMENT` — il manquerait le substantif
# « fusion », puisque ma ligne disait « (fusion de la PR #44) ». C'etait le
# mauvais coupable : elargir l'apaisement aurait apaise « en attente de fusion
# de la PR #44 », qui est exactement le defaut retire plus haut.
#
# On ne touche donc pas aux motifs : on FILTRE leurs occurrences.
# 🔴 Relu en juge le 26/09 : la premiere version ancrait la negation juste avant
# le motif (`\s*$`). Quatre contournements, tous plausibles dans un brain ecrit
# en gras :
#
#     « **Aucune** PR ouverte »        le gras s intercale
#     « *aucune* / `aucune` »          idem, italique et code
#     « Aucune des trois PR ouvertes » deux mots s intercalent
#
# On tolere donc la ponctuation markdown et AU PLUS DEUX mots entre les deux —
# pas davantage, et aucune ponctuation autre. Sans cette borne, chercher la
# negation n importe ou dans les 24 caracteres ferait taire de vraies annonces :
# « on a fusionne sans probleme, PR ouverte : #56 » deviendrait une negation.
MOT_NIANT = r"aucune?|pas[\s*_`~]+d[eu]|plus[\s*_`~]+de|sans|z[ée]ro|nulle"
NEGATION = re.compile(r"\b(" + MOT_NIANT + r")"
                      r"[\s*_`~]*(?:\w+[\s*_`~]+){0,2}$", re.I)
OUVERTE_NUE = re.compile(r"^ouvertes?$", re.I)
JETON_PR = re.compile(r"\bPR\b|#\d+", re.I)


def phrase_autour(texte: str, debut: int, fin: int) -> str:
    """La phrase qui porte le motif — bornee par . ! ? ou un saut de ligne."""
    g = max((texte.rfind(c, 0, debut) for c in ".!?\n"), default=-1)
    bornes = [texte.find(c, fin) for c in ".!?\n"]
    d = min((b for b in bornes if b != -1), default=len(texte))
    return texte[g + 1:d]


def annonce_attente(section: str) -> bool:
    """La section annonce-t-elle vraiment un travail EN ATTENTE ?

    Chaque occurrence est examinee, et deux la disqualifient :

      · elle est NIEE — « Aucune PR ouverte », « plus de PR ouverte » ;
      · c'est « ouverte » nu, et sa phrase ne parle d'aucune PR — « une question
        ouverte », « la porte reste ouverte ».

    Un motif dans du texte mesure ce qui est ecrit, pas ce qui est dit : sans ce
    filtre, une phrase qui affirme qu'il ne reste RIEN a fusionner declenchait le
    controle.
    """
    for m in ATTENTE.finditer(section):
        avant = section[max(0, m.start() - 24):m.start()]
        if NEGATION.search(avant):
            continue
        if OUVERTE_NUE.match(m.group(0)) and not JETON_PR.search(
                phrase_autour(section, m.start(), m.end())):
            continue
        return True
    return bool(ATTENTE_CASSE.search(section))

# 🔴 L'apaisement se juge sur LA LIGNE de la reference, pas sur la section — et
# la premiere version faisait l'inverse. Elle rendait vert sur `LATEST.md`,
# c'est-a-dire sur le seul defaut au monde qu'elle existait pour attraper :
#
#     l.80  « brain#58  la fiche projet — 4 liens morts, 3 etapes soldees »
#     l.87  « `brain#56` n'active rien : la bascule vient apres son merge »
#
# « soldees » parle des etapes du chantier. « merge » est un substantif dans une
# explication. Aucun des deux ne dit qu'une PR est fusionnee, et les deux
# eteignaient le rouge de toute la section. C'est le motif deja ecrit quatre
# fois en memoire : **un motif dans du texte mesure ce qui est ecrit**.
#
# D'ou deux resserrements. L'apaisement ne vaut que sur la ligne qui porte la
# reference — un constat de fusion est attache a SA PR, tandis qu'une annonce
# d'attente porte sur un bloc entier. Et il se limite aux formes qui ne peuvent
# parler que d'une PR : `sold[ée]` et `merge` nu en sont sortis.
#
# Note : « fusionner » n'apaise pas — la frontiere de mot echoue devant le `r`,
# ce qui laisse « ne pas fusionner » du cote de l'attente, ou il doit etre.
APAISEMENT = re.compile(r"✅|fusionn[ée]e?s?\b|merg[ée]es?\b", re.I)

REF_NOMMEE = re.compile(r"\b([A-Za-z][\w-]{1,20})#(\d+)\b")
REF_NUE = re.compile(r"\bPR\s+#(\d+)\b")
TITRE = re.compile(r"^#{1,6}\s")



def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


def _git(depot: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=depot, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def fusionnees(depot: Path) -> set[int] | None:
    """Les PR dont la fusion est PROUVEE localement, ou None si le depot manque.

    None n'est pas l'ensemble vide : c'est « je n'ai pas pu regarder ». Les
    deux se ressemblaient dans, et un peer eteint s'affichait en
    ligne. La distinction se paie ici d'un `is None` a chaque appel.
    """
    if not (depot / ".git").exists() and not (depot / "HEAD").exists():
        return None
    vues: set[int] = set()
    # 1. les fusions en mode `merge` — un commit de fusion, ou qu'il soit
    for m in re.finditer(r"Merge pull request .*?\(#(\d+)\)",
                         _git(depot, "log", "--merges", "--format=%s", "--all")):
        vues.add(int(m.group(1)))
    # 2. rebase et squash — Gitea suffixe le message du numero de PR. Restreint
    #    aux branches d'integration : sur une branche de travail, le suffixe
    #    pourrait exister avant que la fusion ait eu lieu.
    branches = [b.strip().lstrip("* ") for b in
                _git(depot, "branch", "--format=%(refname:short)").splitlines()]
    integration = [b for b in branches
                   if b in ("main", "master") or b.startswith("dev/")]
    for b in integration:
        for m in re.finditer(r"\(#(\d+)\)\s*$",
                             _git(depot, "log", "--format=%s", b), re.M):
            vues.add(int(m.group(1)))
    return vues


def resoudre(nom: str, brain: Path, gitea: Path) -> Path | None:
    """Du nom ecrit dans le document au repertoire du depot, ou None."""
    n = nom.lower()
    if n == "brain":
        return brain
    n = _fiches.alias_forge(brain).get(n, n)   # projets/_alias-forge.yml
    for d in (gitea / n, gitea / nom):
        if d.is_dir():
            return d
    if gitea.is_dir():                      # casse libre : `Mon-API` pour `mon-api`
        for d in gitea.iterdir():
            if d.is_dir() and d.name.lower() == n.lower():
                return d
    return None


def sections(texte: str) -> list[tuple[int, str]]:
    """Decoupe en sections markdown. Rend (ligne du debut, contenu).

    La section est l'unite semantique d'un document d'etat : un projet, une
    session. Une fenetre de N lignes aurait coupe entre la phrase « neuf PR
    ouvertes » et le bloc de code qui les liste, trois lignes plus bas.
    """
    debut, courant, sorties = 1, [], []
    for i, l in enumerate(texte.splitlines(), 1):
        if TITRE.match(l) and courant:
            sorties.append((debut, "\n".join(courant)))
            debut, courant = i, [l]
        else:
            courant.append(l)
    if courant:
        sorties.append((debut, "\n".join(courant)))
    return sorties


def refs_de(section: str, defaut: str | None) -> list[tuple[str | None, int, str, int]]:
    """Rend (depot, numero, la ligne qui porte la reference).

    La ligne voyage avec la reference parce que c'est sur elle que se juge
    l'apaisement — et la premiere version, qui le jugeait sur la section, ne
    voyait pas le defaut de `LATEST.md`. Son rang voyage aussi : pointer la
    section (`LATEST.md:65`) quand la mention est douze lignes plus bas oblige
    a la chercher a l'oeil, et c'est ce genre de frottement qui fait qu'on ne
    corrige pas.
    """
    trouvees, vues = [], set()
    for rang, ligne in enumerate(section.splitlines()):
        for d, n in REF_NOMMEE.findall(ligne):
            trouvees.append((d, int(n), ligne, rang))
            vues.add(int(n))
    for rang, ligne in enumerate(section.splitlines()):
        for n in REF_NUE.findall(ligne):
            if int(n) not in vues:              # defaut None = depot inconnu
                trouvees.append((defaut, int(n), ligne, rang))
    return trouvees


def examiner(brain: Path, gitea: Path, cibles: list[Path]) -> tuple[list, list]:
    """Rend (contradictions prouvees, mentions non mesurables)."""
    cache: dict[str, set[int] | None] = {}
    rouges, doutes, vus = [], [], set()
    for f in cibles:
        if not f.is_file():
            continue
        # `projets/mon-site.md` parle du depot `mon-site` : un `PR #4` nu y trouve
        # son depot. `LATEST.md` ne parle d'aucun projet en particulier —
        # une reference nue y reste sans depot, donc non mesurable.
        defaut = f.stem if f.parent.name == "projets" else None
        for debut, sec in sections(f.read_text(encoding="utf-8")):
            if not annonce_attente(sec):
                continue
            for depot, num, ligne, rang in refs_de(sec, defaut):
                if APAISEMENT.search(ligne):
                    continue
                ou = f"{f.name}:{debut + rang}"
                if (ou, depot, num) in vus:      # la meme PR citee trois fois
                    continue                      # dans une section est UN fait
                vus.add((ou, depot, num))
                if depot is None:
                    doutes.append((ou, f"#{num}", "aucun depot nomme"))
                    continue
                if depot not in cache:
                    d = resoudre(depot, brain, gitea)
                    cache[depot] = fusionnees(d) if d else None
                connues = cache[depot]
                if connues is None:
                    doutes.append((ou, f"{depot}#{num}", "depot absent du disque"))
                elif num in connues:
                    rouges.append((ou, f"{depot}#{num}"))
                else:
                    doutes.append((ou, f"{depot}#{num}", "fusion non prouvee en local"))
    return rouges, doutes


# ── L'auto-epreuve ─────────────────────────────────────────────────────────
#
# Ce controle sait-il rougir ? Un controle qui a cesse de mesurer quoi que ce
# soit affiche exactement les memes ✅ qu'un controle qui passe. On lui donne
# donc six documents dont on connait la reponse, sur un faux depot qu'on
# fabrique — jamais sur le vrai brain, jamais sur la vraie forge.

def faux_depot(racine: Path) -> Path:
    d = racine / "faux"
    d.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    def g(*a):
        subprocess.run(["git", *a], cwd=d, capture_output=True, env={**env, "PATH": "/usr/bin:/bin"})
    g("init", "-q", "-b", "main")
    (d / "a.txt").write_text("1")
    g("add", "."); g("commit", "-qm", "socle")
    # une PR fusionnee en mode `merge`
    g("checkout", "-qb", "f1")
    (d / "b.txt").write_text("1"); g("add", "."); g("commit", "-qm", "b")
    g("checkout", "-q", "main")
    g("merge", "--no-ff", "-q", "f1", "-m", "Merge pull request 'x' (#10) from f1 into main")
    # les trois numeros du defaut reel du 17/09, pour le temoin plus bas
    for n in (56, 57, 58):
        g("checkout", "-qb", f"r{n}")
        (d / f"r{n}.txt").write_text("1"); g("add", "."); g("commit", "-qm", f"r{n}")
        g("checkout", "-q", "main")
        g("merge", "--no-ff", "-q", f"r{n}", "-m",
          f"Merge pull request 'x' (#{n}) from r{n} into main")
    # une PR fusionnee en rebase — aucun commit de fusion, juste le suffixe
    (d / "c.txt").write_text("1"); g("add", "."); g("commit", "-qm", "c (#11)")
    # un suffixe hors branche d'integration : ne doit PAS compter
    g("checkout", "-qb", "travail")
    (d / "e.txt").write_text("1"); g("add", "."); g("commit", "-qm", "e (#12)")
    g("checkout", "-q", "main")
    return d


def auto_epreuve() -> None:
    print("\nAUTO-ÉPREUVE — sur un faux dépôt, en répertoire temporaire\n")
    with tempfile.TemporaryDirectory() as tmp:
        racine = Path(tmp)
        depot = faux_depot(racine)
        vues = fusionnees(depot)
        verifie("une fusion en mode `merge` est vue", 10 in (vues or ()), True)
        verifie("une fusion en `rebase` est vue par son suffixe", 11 in (vues or ()), True)
        verifie("un suffixe hors branche d'intégration ne compte pas",
                12 in (vues or ()), False)
        verifie("un dépôt absent rend `None`, pas un ensemble vide",
                fusionnees(racine / "nexistepas"), None)

        proj = racine / "projets"; proj.mkdir()
        cas = {
            "faux.md": "## S\n\nDeux **PR ouvertes** : faux#10 et faux#11.\n",
            "faux2.md": "## S\n\n✅ **faux#10 fusionnée** le 16/09 — soldé.\n",
            "faux3.md": "## S\n\n**PR ouvertes** : faux#99, à relire.\n",
            "faux4.md": "## S\n\nRien à signaler ici, faux#10 pour mémoire.\n",
            # 🔴 « avant » minuscule : une phrase banale, pas un ordre de
            # fusion. Sous `re.I`, `\bAVANT\b` la prenait — 237 fois sur le
            # perimetre reel contre 22 vraies majuscules.
            "faux5.md": "## S\n\nIl faudra le relire avant la fin du mois, faux#10.\n",
            "faux6.md": "## S\n\nfaux#10 **AVANT** faux#11, sinon le doctor rougit.\n",
        }
        for n, c in cas.items():
            (proj / n).write_text(c, encoding="utf-8")
        # le nom de fichier sert de dépôt par défaut : on le neutralise en
        # nommant le dépôt explicitement dans chaque cas.
        r, d = examiner(racine, racine, [proj / n for n in cas])
        verifie("une attente + une fusion prouvée = rouge",
                sorted({x[1] for x in r}), ["faux#10", "faux#11"])
        verifie("un apaisement sur la ligne de la référence éteint le rouge",
                any("faux2.md" in x[0] for x in r), False)
        verifie("une attente sans fusion prouvée = doute, pas rouge",
                [x[1] for x in d if "faux3" in x[0]], ["faux#99"])
        verifie("une section sans vocabulaire d'attente est ignorée",
                any("faux4.md" in x[0] for x in r + [(a, b) for a, b, _ in d]), False)
        verifie("un « avant » minuscule n'est pas un ordre de fusion",
                any("faux5.md" in x[0] for x in r), False)
        verifie("un « AVANT » majuscule en est un",
                sorted({x[1] for x in r if "faux6" in x[0]}), ["faux#10", "faux#11"])

        # ── Les deux resserrements du 26/09, et leurs contre-temoins ──────
        #
        # Reconstitue mot pour mot depuis `projets/mon-app.md`, section « Etat
        # courant » : le controle rougissait sur `faux#10` alors que le texte
        # dit qu'il ne reste RIEN a fusionner.
        nie = racine / "nie"; nie.mkdir()
        (nie / "a.md").write_text(
            "## Etat courant\n\n"
            "**Ce qu'a produit la session du 05/09** : **sept PR fusionnees**,\n"
            "toutes vertes — faux#10 a faux#11. Aucune PR ouverte.\n", encoding="utf-8")
        (nie / "b.md").write_text(
            "## Etat courant\n\n"
            "Reste au registre : A6, A9, D2 (le limiteur).\n"
            "Plus une question ouverte : montre-t-on les abandons ? Voir faux#10.\n",
            encoding="utf-8")
        # 🔴 LE contre-temoin : une negation ET une vraie annonce dans la MEME
        # section. Le filtre examine chaque occurrence, pas la section — s'il
        # devenait « une negation quelque part eteint tout », ce cas passerait
        # au vert et le filtre serait devenu un trou.
        (nie / "c.md").write_text(
            "## Etat courant\n\n"
            "Aucune PR ouverte sur le back.\n"
            "Cote front en revanche : **PR ouvertes** faux#10, a relire.\n",
            encoding="utf-8")
        # « ouverte » nu, mais sa phrase parle bien d'une PR : reste une annonce.
        (nie / "d.md").write_text(
            "## Etat courant\n\n"
            "faux#10 est encore ouverte, personne ne l'a relue.\n", encoding="utf-8")

        rn, _dn = examiner(depot, racine, [nie / n for n in ("a.md", "b.md",
                                                            "c.md", "d.md")])
        verifie("« Aucune PR ouverte » est une négation, pas une annonce",
                any("a.md" in x[0] for x in rn), False)
        verifie("« une question ouverte » ne parle pas d'une PR",
                any("b.md" in x[0] for x in rn), False)
        verifie("contre-témoin : une négation n'éteint pas une VRAIE annonce "
                "de la même section",
                sorted({x[1] for x in rn if "c.md" in x[0]}), ["faux#10"])
        verifie("… et « ouverte » nu reste une annonce si sa phrase cite la PR",
                sorted({x[1] for x in rn if "d.md" in x[0]}), ["faux#10"])
        verifie("le filtre ne juge pas la section mais chaque occurrence",
                annonce_attente("Aucune PR ouverte. Mais faux#10 est a relire."),
                True)
        verifie("… et une section entierement niee ne declenche rien",
                annonce_attente("Aucune PR ouverte, plus de PR ouverte."), False)
        # Le SECOND cas reel, trouve en comparant le perimetre avant/apres :
        # `projets/mon-portage.md` ligne 475, dont le seul declencheur
        # etait « sans PR ouverte ». Son doute etait un faux positif de plus,
        # dans la colonne des non mesurables au lieu du rouge.
        verifie("« sans PR ouverte » est une négation aussi — cas réel du 26/09",
                annonce_attente("Resultats de mesure sur une branche "
                                "**sans PR ouverte**. Voir PR #5."), False)

        # ── Les quatre contournements trouves en relisant la PR #20 en juge ───
        #
        # Le brain est ecrit en gras partout : ancrer la negation juste avant le
        # motif la rendait triviale a contourner.
        for texte, nom in (
                ("**Aucune** PR ouverte.", "la négation en **gras**"),
                ("*aucune* PR ouverte.", "… en *italique*"),
                ("`aucune` PR ouverte.", "… en `code`"),
                ("Il n'y a **pas** de PR ouverte.", "« pas de » coupé par du gras"),
                ("Aucune des trois PR ouvertes.", "deux mots intercalés")):
            verifie(f"contournement fermé : {nom}", annonce_attente(texte), False)

        # 🔴 LE temoin qui BORNE la tolerance. Chercher la negation n'importe ou
        # dans les 24 caracteres aurait ete plus simple et aurait fait taire
        # celui-ci — une vraie annonce, ou « sans » ne nie pas le motif mais un
        # autre mot de la phrase. Sans ce temoin, le filtre serait un trou.
        verifie("… mais « fusionné sans problème, PR ouverte » RESTE une annonce",
                annonce_attente("On a fusionne sans probleme, PR ouverte : #56."),
                True)

        # 🔴 Le témoin du défaut RÉEL, reconstitué mot pour mot.
        #
        # Ce bloc est celui que `LATEST.md` portait le 17/09. La première
        # version de ce contrôle le laissait passer en vert, parce que
        # « 3 etapes soldees » et « apres son merge » éteignaient toute la
        # section. Un contrôle qui ne rougit pas sur le défaut qui l'a fait
        # naître ne mesure rien — et rien, dans les huit cas ci-dessus, ne
        # l'aurait dit : ils passaient tous.
        reel = racine / "reel"; reel.mkdir()
        (reel / "LATEST.md").write_text(
            "## 📍 Myéline — la soirée du 15/09, en autonomie\n\n"
            "**[myeline-soiree-20260915.md](x.md)** — **neuf PR\n"
            "ouvertes**, et un ordre de fusion qui n'est pas libre.\n\n"
            "```\n"
            "brain#56    MY" "-117 — la route de fermeture ecrit ce qu une fermeture porte\n"
            "brain#57    l audit des 23 ouvertes, remesurees\n"
            "brain#58    la fiche projet — 4 liens morts, 3 etapes soldees   (empilee sur #57)\n"
            "```\n\n"
            "⚠️ `brain#56` **AVANT** `myeline#2` (sinon le doctor rougit en permanence), et\n"
            "`#57` avant `#58`. La première contrainte a été éprouvée dans les deux sens.\n\n"
            "⚠️ **`brain#56` n'active rien** : la bascule de `cmd_close` vient après son merge\n"
            "**et** un redémarrage du service.\n", encoding="utf-8")
        # `depot` tient lieu de dépôt `brain` : `resoudre('brain', …)` rend son
        # premier argument, qui est ici le faux dépôt portant #56, #57 et #58.
        rr, _ = examiner(depot, racine, [reel / "LATEST.md"])
        verifie("témoin du défaut réel : le bloc du 17/09 rougit",
                sorted({x[1] for x in rr}), ["brain#56", "brain#57", "brain#58"])

        # 🔴 Le témoin négatif de l'asymétrie : si un jour quelqu'un « simplifie »
        # `fusionnees` en rendant un ensemble vide au lieu de None, un dépôt
        # absent redeviendrait un dépôt sans fusion — et le doute se tairait.
        globals()["fusionnees"] = lambda d: set()
        try:
            _, d2 = examiner(racine, racine, [proj / "faux3.md"])
            verifie("témoin : un dépôt muet rendu vide fait disparaître le doute",
                    [x[2] for x in d2], ["fusion non prouvee en local"])
        finally:
            globals()["fusionnees"] = fusionnees_vraie


fusionnees_vraie = fusionnees


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    p.add_argument("--gitea", default=str(Path.home() / "Dev/Gitea"), type=Path)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()
    if not (brain / "handoffs").is_dir():
        print(f"❌ brain introuvable sous {brain}")
        return 1

    cibles = [brain / "handoffs/LATEST.md", brain / "workspace/live-states.md"]
    cibles += sorted((brain / "projets").glob("*.md"))

    print("ÉTAT ANNONCÉ vs FORGE — un document réclame-t-il un travail déjà fait ?\n")
    # 🔴 `examiner()` saute silencieusement les cibles absentes. Compter `cibles`
    # ferait donc annoncer « 63 documents relus » sur un depot ou il en manque —
    # un nombre qui decrit l intention, pas le fait. Relu en juge le 26/09.
    lus = [c for c in cibles if c.is_file()]
    manquants = [c for c in cibles if not c.is_file()]
    if manquants:
        print(f"  ⚪ {len(manquants)} cible(s) absente(s) — non relue(s), donc "
              f"jamais comptee(s) comme saines :")
        for c in manquants[:6]:
            print(f"     {c.relative_to(brain)}")
        if len(manquants) > 6:
            print(f"     … et {len(manquants) - 6} autre(s)")
        print()
    rouges, doutes = examiner(brain, a.gitea.expanduser().resolve(), cibles)

    # Ce que le contrôle N'A PAS pu mesurer se dit, il ne se tait pas.
    if doutes:
        print(f"  ⚪ {len(doutes)} mention(s) non mesurable(s) en local — "
              f"jamais comptées comme ouvertes :")
        for ou, ref, pourquoi in doutes[:8]:
            print(f"     {ou:<34} {ref:<18} {pourquoi}")
        if len(doutes) > 8:
            print(f"     … et {len(doutes) - 8} autre(s)")
        print()

    if rouges:
        print(f"  ❌ {len(rouges)} mention(s) réclament un travail que la forge dit fait :")
        for ou, ref in rouges:
            print(f"     {ou:<34} {ref}")
        print("\n     Le document annonce cette PR en attente, et un commit prouve")
        print("     sa fusion. Corriger le document, ou retirer la mention.")
        auto_epreuve()
        return 1

    print("  ✅ aucun document d'état ne réclame un travail déjà fusionné")
    auto_epreuve()
    print()
    if _ko:
        print(f"  ❌ auto-épreuve : {_ko} cas sur {_ok + _ko} — le contrôle ne mesure")
        print("     plus ce qu'il annonce mesurer.")
        return 1
    print(f"  ✅ auto-épreuve : les {_ok} cas passent")
    # 🔴 Cette ligne est la DERNIERE `✅` du script, et le doctor resume un
    # controle vert par sa derniere ligne `✅`. Sans elle il affichait
    # « auto-epreuve : les 25 cas passent » — un nom de test, pas un verdict.
    # Le defaut etait INVISIBLE tant que ce controle etait rouge : il ne s est
    # montre qu en le faisant verdir, le 26/09. Meme famille qu'un defaut deja vu et que
    # la synthese de `fraicheur_des_fiches.py`.
    print(f"\n  ✅ {len(lus)} document(s) relus — aucun ne réclame un travail "
          f"que la forge dit fait"
          + (f", et {len(doutes)} mention(s) restent non mesurables" if doutes
             else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
