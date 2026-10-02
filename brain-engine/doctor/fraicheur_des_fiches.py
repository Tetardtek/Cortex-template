#!/usr/bin/env python3
"""Une fiche projet a-t-elle ete relue depuis que son depot a bouge ?

Ce qui pourrirait en silence sans lui : **une fiche d'etat qu'on croit tenue
parce qu'elle a l'air recente.**

Le 23/09, trois fiches sur trois mentaient, et aucune ne le disait :

    projets/mon-jeu.md   « trois PR preparees, aucune fusionnee »
                             -> dix fusionnees, tag v0.6.5, zero PR ouverte
    projets/mon-site.md         « quatre commits locaux non pousses »
                             -> zero, et la journee du 11/09 ignoree
    projets/mon-app.md        « derniere vraie session : 2026-04-05 »
                             -> il y avait eu les 03, 04 et 05/09

`annonce_vs_forge.py` couvre deja `projets/*.md`, et n'a rien vu :
il juge **un seul type d'affirmation**, une PR annoncee ouverte. Aucune des
trois n'avait cette forme. Le controle etait vert, et il avait raison de
l'etre — sur sa question.

Celui-ci pose l'autre question, la seule que git puisse trancher sans lire le
francais : **le depot a-t-il bouge apres la derniere fois qu'on a ecrit cette
fiche ?**

    python3 tools/fraicheur_des_fiches.py --brain ~/Dev/Brain

── 🔴 Le verdict ne rougit jamais, et c'est voulu ──────────────────────────

Tranche avec l'owner le 23/09. Un depot qui bouge **ne prouve pas** que la fiche
ment : il prouve qu'elle n'a pas ete relue depuis. La difference n'est pas
rhetorique — `mon-addon` n'a pas bouge depuis le 07/08 et sa fiche est
parfaitement juste, tandis qu'un depot peut encaisser trente commits de typo
sans qu'une ligne de la fiche devienne fausse.

    le depot a bouge apres la fiche  ->  DOUTE, chiffre
    le depot n'a pas bouge           ->  rien a dire
    le depot est introuvable         ->  NON MESURABLE, nomme

Un controle qui tait ses angles morts est celui qui a produit : ils
sont donc tous imprimes, jamais tus.

── 🔴 Ce que « la derniere ecriture de la fiche » ne peut pas vouloir dire ──

Le premier jet prenait `git log -1 -- projets/X.md`. **Mesure faite avant
d'ecrire une ligne d'outil** : 20 fiches sur 23 paraissaient a jour grace au
meme commit.

    f5a2f71  2026-09-03   21 fiches   « le fichier fait foi, la table devient
                                        un cache regenere »
    b6033ab  2026-09-03   15 fiches   « `status:` redevient un etat »

Ces deux-la ont reecrit des frontmatters en masse. Ils n'ont rien dit de
l'etat d'aucun projet, et ils rajeunissaient tout le monde d'un coup. Le
controle aurait ete vert sur les trois fiches du 23/09 — c'est-a-dire vert
sur les seuls defauts au monde pour lesquels il existe. Exactement le piege
de, ou l'apaisement juge sur la section verdissait le defaut reel.

D'ou le **seuil de remaniement**. Un commit qui touche plus de
`SEUIL_REMANIEMENT` fiches est un remaniement de structure, pas une mise a
jour d'etat, et il ne compte pas comme une ecriture.

Le seuil vient de la distribution reelle, pas d'un choix esthetique : sur
tout l'historique de `projets/`, les mises a jour d'etat touchent 1 a 4
fiches, les douze remaniements en touchent 6 a 21. Il n'y a rien entre 4 et 6.

⚠️ Consequence assumee : une fiche que **seuls** des remaniements ont touchee
n'a pas de date d'ecriture d'etat. Elle est declaree non mesurable — pas
« tres en retard ». On ne sait pas, et on le dit.

── Les angles morts, mesures et non supposes ───────────────────────────────

    depot absent du disque    `ma-carte` vit dans `mon-serveur/mon-monde/`, un
                              depot imbrique dans un autre ; `mon-outil` et
                              `mon-portage` ne sont clones nulle part.
                              34 fiches sur 60 sont dans ce cas, et beaucoup
                              n'ont simplement aucun depot — `ma-formation`,
                              `mes-certificats`, `mon-admin`.

    clone en retard de fetch  on lit le depot local. S'il est en retard, on
                              **sous-estime** le retard de la fiche. Jamais
                              l'inverse : un doute manque vaut mieux qu'un
                              doute invente.

    un commit anodin          un typo dans un README fait bouger le depot et
                              produit un doute que rien ne justifie. C'est le
                              prix d'un verdict qui ne lit pas le francais.
                              Le chiffre attenue : un doute a 1 commit ne se
                              lit pas comme un doute a 699.

    les commits de fusion     `git log --name-only` ne liste AUCUN fichier pour
                              une fusion. Une fiche modifiee uniquement dans
                              une resolution de conflit serait donc invisible.
                              Portee mesuree le 23/09 : **une seule fusion
                              touche `projets/` dans tout l'historique**
                              (`a8f73b9`), et elle ne liste rien — le travail
                              arrive par les commits d'origine, qui sont vus.
                              Non corrige a dessein : developper les fusions
                              ferait compter toute la branche d'un coup, donc
                              franchir le seuil de remaniement a tort. Le sens
                              de l'erreur est le bon — on sous-estime la
                              fraicheur, donc on sur-signale le doute.

Il n'ecrit rien et ne joint personne : `git log` local suffit, aucun jeton,
aucun reseau.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fiches  # noqa: E402 — la table des alias vit dans le brain

# Un commit qui touche plus de fiches que ca remanie la structure, il ne met
# pas a jour un etat. Voir le bloc « ce que la derniere ecriture ne peut pas
# vouloir dire » : mesure sur l'historique, rien entre 4 et 6.
SEUIL_REMANIEMENT = 5

# Le nom ecrit dans la fiche n'est pas toujours celui du repertoire : les alias
# se lisent dans `projets/_alias-forge.yml` du brain (`_fiches.alias_forge`).

# Chaque racine, avec la PROFONDEUR a laquelle on y cherche un depot
#
# La version d avant lisait `racine.iterdir()`, un seul niveau, sur deux racines.
# Trois depots qui existent lui echappaient donc, et leurs fiches etaient
# declarees « non mesurables » :
#
#   mon-outil         ~/Dev/mon-outil                        hors des deux racines
#   mon-bot  ~/Dev/Brain/mon-bot           satellite DU brain
#   mon-monde    ~/Dev/Gitea/mon-serveur/mon-monde  imbrique a 2 niveaux
#
# La profondeur est par racine, et non globale, parce que chaque cas a une cause
# differente. Mesure du 26/09 qui la justifie : au niveau 2 de Gitea+Github il
# n existe que DEUX depots — `mon-serveur/mon-monde` et
# `mon-jeu/mon-extracteur`. Aucun vendor, aucun `node_modules` porteur de
# `.git`. La descente ne ramasse donc rien de parasite ; ce n est pas un filtre
# qui la rend sure, c est le terrain, et `IGNORES` n est qu une ceinture.
#
# ⚠️ `mon-serveur` EST lui-meme un depot. La borne « ne pas descendre dans un
# depot », qui aurait ete la plus simple, aurait donc rate precisement le cas
# qui motive cette fiche. Verifie avant de l ecrire.
RACINES = (("Dev/Gitea", 2), ("Dev/Github", 2), ("Dev/Brain", 1), ("Dev", 1))

# Ce qu on ne traverse jamais. Ceinture, pas mecanisme : la mesure ci-dessus dit
# qu aucun de ces repertoires ne porte de `.git` sur cette machine aujourd hui.
IGNORES = frozenset({"node_modules", "vendor", "__pycache__", "dist", "build",
                     "target", "venv", "site-packages"})

# Plafond de repertoires inspectes, toutes racines confondues. Mesure du 26/09 :
# ~330. Une racine qui le depasse n est PAS parcourue a moitie — le depassement
# est nomme, et les fiches concernees restent non mesurables. Un perimetre
# tronque en silence est pire qu un perimetre refuse.
PLAFOND = 3000

FRONT_REPO = re.compile(r"^(?:repo|repo_public|vitrine):\s*(\S+)", re.M)

_ok = _ko = 0


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


def noms_candidats(fiche: Path) -> list[str]:
    """Les noms sous lesquels le depot de cette fiche peut se presenter.

    Le nom du fichier d'abord — c'est la convention —, puis ce que le
    frontmatter declare. `ma-carte` illustre pourquoi les deux sont necessaires
    et pourquoi ils ne suffisent pas : sa fiche nomme bien `MaCarte`, mais le
    clone est imbrique dans `mon-serveur/`, ou on ne le cherche pas.
    """
    noms = [fiche.stem]
    try:
        texte = fiche.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return noms
    for m in FRONT_REPO.finditer(texte):
        noms.append(m.group(1).rstrip("/").split("/")[-1])
    return noms


def depots_atteignables(
        racines: list[tuple[Path, int]]
) -> tuple[dict[str, Path], list[tuple[bool, str]]]:
    """Les depots du disque, indexes par nom minuscule

    Construit UNE fois, au lieu d un `iterdir()` par fiche et par nom candidat.

    Le premier trouve gagne, dans l ordre des racines : c est exactement ce que
    faisait la version d avant, et le changer aurait deplace silencieusement des
    resolutions deja justes. Une collision — deux depots du meme nom sous deux
    racines — est RENDUE, jamais tranchee en silence.

    Retourne `(index, anomalies)`, chaque anomalie etant `(bloquant, texte)`.

    🔴 **`bloquant` veut dire que l index est INCOMPLET**, et donc qu aucune
    fiche non resolue ne peut etre declaree « depot introuvable ». Le premier jet
    de ce correctif rendait une anomalie disant « rien n est conclu des fiches
    non resolues » — et concluait ensuite 58 fois « depot introuvable sur le
    disque ». Le message affirmait une discipline que le code n appliquait pas,
    ce qui est pire qu un silence. C est un defaut deja vu, a l identique, commis dans le
    correctif meme qui la citait.
    """
    index: dict[str, Path] = {}
    anomalies: list[tuple[bool, str]] = []
    vus = 0
    for racine, profondeur in racines:
        if not racine.is_dir():
            continue
        niveau = [racine]
        for _ in range(profondeur):
            suivant = []
            for parent in niveau:
                try:
                    enfants = sorted(parent.iterdir())
                except OSError as exc:
                    # Un repertoire illisible ne rend pas l index faux : il le
                    # rend partiel a un endroit nomme. Non bloquant, mais dit.
                    anomalies.append(
                        (False, f"illisible : {parent} ({exc.strerror})"))
                    continue
                for d in enfants:
                    if not d.is_dir() or d.name.startswith(".") \
                            or d.name in IGNORES:
                        continue
                    vus += 1
                    if vus > PLAFOND:
                        anomalies.append(
                            (True, f"plafond de {PLAFOND} repertoires depasse "
                                   f"sous {racine} — l index est incomplet"))
                        return index, anomalies
                    if (d / ".git").exists():
                        cle = d.name.lower()
                        ancien = index.get(cle)
                        if ancien is None:
                            index[cle] = d
                        elif ancien != d:
                            # L index est complet : il est seulement ambigu sur
                            # ce nom-la. On peut conclure, en le disant.
                            anomalies.append(
                                (False, f"deux depots nommes `{cle}` : {ancien} "
                                        f"(retenu) et {d}"))
                    # On descend meme dans un depot : `mon-monde` vit a
                    # l interieur de `mon-serveur`, qui en est un.
                    suivant.append(d)
            niveau = suivant
    return index, anomalies


def resoudre(fiche: Path, brain: Path, index: dict[str, Path]) -> Path | None:
    """Du nom de la fiche au repertoire du depot, ou None s'il est introuvable.

    None veut dire « je n'ai pas pu regarder », jamais « rien a signaler ».
    """
    for nom in noms_candidats(fiche):
        cible = _fiches.alias_forge(brain).get(nom.lower(), nom).lower()   #
        if cible == "brain":
            return brain
        depot = index.get(cible)
        if depot is not None:
            return depot
    return None


def ecritures_d_etat(brain: Path) -> dict[str, int]:
    """Pour chaque fiche, l'horodatage de sa derniere ecriture D'ETAT.

    Une seule invocation de `git log` pour tout le repertoire : la version
    naive en lancait une par fiche, et par commit pour les compter.

    Le format `--name-only` donne, par commit, sa date puis ses fichiers. On
    compte les fiches touchees AVANT d'attribuer la date : un commit au-dela
    du seuil est un remaniement, il n'ecrit l'etat de personne.
    """
    sortie = _git(brain, "log", "--format=%x00%ct", "--name-only", "--", "projets/")
    dernier: dict[str, int] = {}
    for bloc in sortie.split("\x00"):
        if not bloc.strip():
            continue
        lignes = bloc.strip().splitlines()
        horodatage = int(lignes[0])
        fiches = [l.strip() for l in lignes[1:]
                  if l.strip().startswith("projets/") and l.strip().endswith(".md")]
        if len(fiches) > SEUIL_REMANIEMENT:
            continue                      # remaniement : ne rajeunit personne
        for f in fiches:
            # `git log` descend du plus recent au plus ancien : le premier vu
            # est le bon, on ne l'ecrase pas avec un commit plus vieux.
            dernier.setdefault(f, horodatage)
    return dernier


def commits_depuis(depot: Path, horodatage: int) -> int:
    """Combien de commits le depot a-t-il pris apres cette date, toutes branches.

    `--all` parce qu'un chantier vit sur sa branche avant d'etre fusionne :
    ne regarder que `main` ferait passer pour calme un depot en plein travail.
    """
    sortie = _git(depot, "rev-list", "--count", "--all", f"--since=@{horodatage}")
    try:
        return int(sortie.strip())
    except ValueError:
        return 0


def fiches_a_juger(brain: Path) -> list[Path]:
    """Les fiches du perimetre, et la SEULE definition de ce perimetre.

    Extraite le 26/09 : la ligne de synthese avait besoin du total, et le
    recompter a cote aurait ecrit deux fois la meme regle — ce que ce depot
    passe son temps a debusquer ailleurs.
    """
    dossier = brain / "projets"
    if not dossier.is_dir():
        return []
    return [p for p in sorted(dossier.glob("*.md")) if p.stem != "_template"]


def examiner(brain: Path,
             racines: list[tuple[Path, int]]) -> tuple[list, list, list]:
    """(doutes, non mesurables, anomalies). Le reste va bien.

    Les anomalies viennent du parcours du disque, pas des fiches : un plafond
    depasse, un repertoire illisible, deux depots de meme nom. Elles sont
    rendues a l appelant pour qu il les DISE — un perimetre qui se reduit sans
    le dire est le defaut meme que cet index corrige.
    """
    index, anomalies = depots_atteignables(racines)
    if any(bloquant for bloquant, _ in anomalies):
        # L index est incomplet : une fiche non resolue ne peut pas etre dite
        # « depot introuvable ». On ne rend AUCUN verdict de fiche —.
        return [], [], anomalies
    ecritures = ecritures_d_etat(brain)
    doutes, muets = [], []
    for fiche in fiches_a_juger(brain):
        depot = resoudre(fiche, brain, index)
        if depot is None:
            muets.append((fiche.name, "depot introuvable sur le disque"))
            continue
        horodatage = ecritures.get(f"projets/{fiche.name}")
        if horodatage is None:
            muets.append((fiche.name,
                          "aucune ecriture d'etat — que des remaniements"))
            continue
        n = commits_depuis(depot, horodatage)
        if n:
            doutes.append((fiche.name, depot.name, n))
    return doutes, muets, anomalies


# ── Auto-epreuve ───────────────────────────────────────────────────────────

def _depot(chemin: Path) -> None:
    chemin.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=chemin, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=chemin, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=chemin, check=True)


def _commit(depot: Path, fichiers: dict[str, str], message: str, date: str) -> None:
    for nom, contenu in fichiers.items():
        p = depot / nom
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenu, encoding="utf-8")
    subprocess.run(["git", "add", *fichiers], cwd=depot, check=True)
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=depot,
                   check=True, env=env)


def auto_epreuve() -> None:
    """Le premier cas est l'incident, copie mot pour mot.

    Le temoin negatif est pose AVANT les autres : sans lui, « aucun doute » ne
    se distingue pas de « l'outil ne mesure rien ».
    """
    print("\nAUTO-ÉPREUVE — sur un faux brain, en répertoire temporaire\n")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        brain, gitea = base / "Brain", base / "Gitea"
        _depot(brain)
        _depot(gitea / "mon-site")
        _depot(gitea / "calme")

        # ── témoin négatif : un dépôt figé avant la fiche ────────────────
        _commit(gitea / "calme", {"a.txt": "1"}, "travail", "2026-09-01T10:00:00")
        _commit(brain, {"projets/calme.md": "# calme\n"},
                "scribe: calme", "2026-09-10T10:00:00")

        # ── l'incident du 23/09, mot pour mot ────────────────────────────
        _commit(brain, {"projets/mon-site.md":
                        "# Mon site\n\n**quatre commits locaux non poussés**\n"},
                "scribe: mon-site au 10/09", "2026-09-10T11:00:00")
        _commit(gitea / "mon-site", {"a.txt": "1"}, "travail", "2026-09-09T10:00:00")
        _commit(gitea / "mon-site", {"b.txt": "2"},
                "ci: `check` pour Windows", "2026-09-11T10:00:00")

        racines = [(gitea, 1)]
        doutes, muets, _ = examiner(brain, racines)
        d = {nom: n for nom, _, n in doutes}

        verifie("témoin négatif : un dépôt figé avant la fiche ne doute pas",
                "calme.md" in d, False)
        verifie("témoin du défaut réel : la fiche du 10/09, le dépôt du 11/09",
                d.get("mon-site.md"), 1)

        # ── `vitrine:` nomme un dépôt, comme `repo:` (29/09) ─────
        seule = brain / "projets" / "vitrine-seule.md"
        seule.write_text("---\nname: x\nvitrine: github.com/o/Vitre\n---\n", encoding="utf-8")
        verifie("`vitrine:` nomme un dépôt, comme `repo:`",
                "Vitre" in noms_candidats(seule), True)

        # ── le cœur : un remaniement de masse ne rajeunit personne ───────
        # 🔴 Les nombres sont FIXES, jamais derives de `SEUIL_REMANIEMENT`.
        # La premiere version ecrivait `range(SEUIL_REMANIEMENT + 1)` : porte a
        # 9999 par sabotage, elle fabriquait 10 001 fiches et passait au vert.
        # Un temoin qui se recalibre sur la constante qu'il juge ne mesure
        # rien — il compte zero sur zero. Trouve en sabotant, pas en relisant.
        avant = ecritures_d_etat(brain)["projets/mon-site.md"]
        masse = {f"projets/p{i}.md": f"# p{i}\n" for i in range(6)}
        masse["projets/mon-site.md"] = "# Mon site\n\n**quatre commits non poussés**\n"
        _commit(brain, masse, "projets: `status:` redevient un etat",
                "2026-09-20T10:00:00")
        ecritures = ecritures_d_etat(brain)
        verifie("un remaniement de 6 fiches n'écrit l'état de personne",
                any(f"projets/p{i}.md" in ecritures for i in range(6)), False)
        # 🔴 Le test qui compte, et que la premiere version ratait en comparant
        # une valeur a elle-meme : le remaniement TOUCHE `mon-site.md`, dix jours
        # apres son ecriture. S'il la rajeunissait, le doute du 11/09
        # disparaitrait — le defaut du 23/09 redeviendrait invisible.
        verifie("… et il ne rajeunit pas la fiche qu'il touche au passage",
                ecritures.get("projets/mon-site.md"), avant)
        verifie("… donc le doute du témoin réel survit au remaniement",
                {n: c for n, _, c in examiner(brain, racines)[0]}.get("mon-site.md"), 1)

        _commit(brain, {"projets/p0.md": "# p0 v2\n"},
                "scribe: p0", "2026-09-21T10:00:00")
        verifie("une écriture isolée, elle, compte",
                "projets/p0.md" in ecritures_d_etat(brain), True)
        # Le pendant du temoin de masse : juste SOUS le seuil, ca compte. Sans
        # lui, un seuil a 0 passerait les deux — « rien ne compte » n'est pas
        # « les remaniements ne comptent pas ».
        _commit(brain, {f"projets/r{i}.md": f"# r{i}\n" for i in range(4)},
                "scribe: quatre fiches d'un coup", "2026-09-21T12:00:00")
        verifie("un commit de 4 fiches reste une écriture d'état",
                all(f"projets/r{i}.md" in ecritures_d_etat(brain)
                    for i in range(4)), True)

        # ── ce qu'on n'a pas pu mesurer est nommé, jamais tu ─────────────
        _commit(brain, {"projets/fantome.md": "# fantome\n"},
                "scribe: fantome", "2026-09-21T11:00:00")
        _, muets, _ = examiner(brain, racines)
        verifie("un dépôt absent est non mesurable, pas « à jour »",
                ("fantome.md", "depot introuvable sur le disque") in muets, True)

        masse2 = {f"projets/q{i}.md": f"# q{i}\n"
                  for i in range(SEUIL_REMANIEMENT + 1)}
        _depot(gitea / "q0")
        _commit(gitea / "q0", {"a.txt": "1"}, "travail", "2026-09-22T10:00:00")
        _commit(brain, masse2, "projets: menage", "2026-09-22T11:00:00")
        _, muets, _ = examiner(brain, racines)
        verifie("une fiche que seuls des remaniements ont touchée est non mesurable",
                ("q0.md", "aucune ecriture d'etat — que des remaniements") in muets,
                True)

        # ── un chantier vit sur sa branche avant d'être fusionné ─────────
        # 🔴 On REVIENT sur `main` apres avoir commite sur la branche. La
        # premiere version restait sur `chantier` : `HEAD` portait donc le
        # commit, et retirer `--all` par sabotage ne changeait rien. Le temoin
        # etait pose la ou la chose ne pouvait pas echouer.
        subprocess.run(["git", "checkout", "-q", "-b", "chantier"],
                       cwd=gitea / "calme", check=True)
        _commit(gitea / "calme", {"c.txt": "3"}, "travail", "2026-09-22T12:00:00")
        subprocess.run(["git", "checkout", "-q", "main"],
                       cwd=gitea / "calme", check=True)
        doutes, _, _ = examiner(brain, racines)
        verifie("un commit sur une branche que HEAD ne voit pas compte aussi",
                {nom: n for nom, _, n in doutes}.get("calme.md"), 1)

        # ── le frontmatter sert quand le nom du fichier ne suffit pas ────
        # L'alias se lit dans le brain (`projets/_alias-forge.yml`).
        _depot(gitea / "Mon-API")
        _commit(gitea / "Mon-API", {"a.txt": "1"}, "travail",
                "2026-09-22T13:00:00")
        _commit(brain, {"projets/monapi.md":
                        "---\nrepo: forge.exemple/moi/monapi\n---\n",
                        "projets/_alias-forge.yml": "monapi: Mon-API\n"},
                "scribe: monapi", "2026-09-21T09:00:00")
        doutes, _, _ = examiner(brain, racines)
        verifie("l'alias résout `monapi` vers `Mon-API`",
                "monapi.md" in {nom for nom, _, _ in doutes}, True)

        # ── un index incomplet n autorise AUCUN verdict de fiche ──────────
        # Le premier jet rendait une anomalie disant « rien n est conclu » puis
        # concluait 58 fois « depot introuvable ». Ce cas est cette regression.
        global PLAFOND
        garde = PLAFOND
        try:
            PLAFOND = 1
            d_p, m_p, a_p = examiner(brain, racines)
        finally:
            PLAFOND = garde
        verifie("index incomplet : aucune fiche n'est dite « introuvable »",
                (d_p, m_p), ([], []))
        verifie("… et l'empêchement est rendu, bloquant",
                [b for b, _ in a_p], [True])

    epreuve_du_parcours()


def _ancienne_resolution(cible: str, racines: list[Path]) -> Path | None:
    """La lecture d AVANT l index par racine, reimplementee telle quelle.

    `racine.iterdir()`, un seul niveau, sur les racines passees. Elle est ici
    pour que le temoin DISCRIMINE : des cas qui passeraient aussi avant le
    correctif ne temoigneraient de rien.
    """
    for racine in racines:
        if not racine.is_dir():
            continue
        for d in racine.iterdir():
            if (d.is_dir() and d.name.lower() == cible
                    and (d / ".git").exists()):
                return d
    return None


def epreuve_du_parcours() -> None:
    """Le parcours du disque. Les trois dépôts qui échappaient.

    Chaque cas est copié sur un vrai chemin de cette machine, mesuré le 26/09 :

        mon-outil         ~/Dev/mon-outil                        hors des racines
        mon-bot  ~/Dev/Brain/mon-bot           satellite DU brain
        mon-monde    ~/Dev/Gitea/mon-serveur/mon-monde  imbrique, dans un DEPOT
    """
    print("\nÉPREUVE DU PARCOURS — les racines et leur profondeur\n")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        gitea, brain_f, dev = base / "Gitea", base / "Brain", base

        # `conteneur` est lui-meme un depot : c est le piege de `mon-serveur`.
        _depot(gitea / "simple")
        _depot(gitea / "conteneur")
        _depot(gitea / "conteneur" / "imbrique")
        (gitea / "conteneur" / "sans-git").mkdir(parents=True)
        _depot(gitea / "conteneur" / "trop" / "profond")
        _depot(gitea / "simple" / "node_modules" / "piege")
        _depot(brain_f / "satellite")
        _depot(dev / "hors-racines")
        # Deux homonymes, a deux niveaux differents.
        _depot(gitea / "double")
        _depot(gitea / "conteneur" / "double")

        racines = [(gitea, 2), (brain_f, 1), (dev, 1)]
        index, anomalies = depots_atteignables(racines)

        verifie("un dépôt au niveau 1 est trouvé",
                index.get("simple") == gitea / "simple", True)
        verifie("un dépôt au niveau 2 est trouvé — le cas `mon-monde`",
                index.get("imbrique") == gitea / "conteneur" / "imbrique", True)
        verifie("témoin négatif : l'ancienne lecture ne le trouvait PAS",
                _ancienne_resolution("imbrique", [gitea]), None)
        verifie("on descend dans un dépôt — `conteneur` en est un",
                (gitea / "conteneur" / ".git").exists(), True)
        verifie("un répertoire sans `.git` n'est pas un dépôt",
                index.get("sans-git"), None)
        verifie("la borne tient : le niveau 3 n'est pas atteint",
                index.get("profond"), None)
        verifie("`node_modules` n'est pas traversé",
                index.get("piege"), None)
        verifie("une racine hors Gitea/Github — le cas `mon-bot`",
                index.get("satellite") == brain_f / "satellite", True)
        verifie("témoin négatif : hors des deux racines, l'ancienne était aveugle",
                _ancienne_resolution("satellite", [gitea]), None)
        verifie("un dépôt au niveau 1 de `~/Dev` — le cas `mon-outil`",
                index.get("hors-racines") == dev / "hors-racines", True)
        verifie("deux homonymes : le premier est retenu, comme avant",
                index.get("double") == gitea / "double", True)
        verifie("… et la collision est DITE, pas tranchée en silence",
                any("double" in x for _, x in anomalies), True)
        verifie("… et elle ne bloque pas : l'index est complet, juste ambigu",
                any(b for b, _ in anomalies), False)

        # ── le plafond : nomme, jamais un perimetre tronque en silence ────
        global PLAFOND
        garde = PLAFOND
        try:
            PLAFOND = 2
            _, anomalies_plafond = depots_atteignables(racines)
        finally:
            PLAFOND = garde
        verifie("un plafond dépassé est nommé",
                any("plafond" in x for _, x in anomalies_plafond), True)
        verifie("… et il est BLOQUANT : l'index est incomplet",
                any(b for b, _ in anomalies_plafond), True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", type=Path, default=Path.home() / "Dev/Brain")
    args = ap.parse_args()
    brain = args.brain.expanduser().resolve()

    print("FRAÎCHEUR DES FICHES — une fiche a-t-elle été relue "
          "depuis que son dépôt a bougé ?\n")

    if not (brain / "projets").is_dir():
        print("SKIP — pas de répertoire `projets/` sous", brain)
        return 0

    racines = [(Path.home() / r, p) for r, p in RACINES]
    doutes, muets, anomalies = examiner(brain, racines)

    # Le perimetre se declare AVANT les conclusions. Une recherche qui
    # s est reduite, ou qui a du choisir entre deux depots homonymes, change ce
    # que valent les lignes qui suivent.
    bloquantes = [x for b, x in anomalies if b]
    signalees = [x for b, x in anomalies if not b]

    if bloquantes:
        # Pas de verdict partiel : sans index complet, « introuvable » serait un
        # mensonge sur des fiches qu on n a pas cherchees —.
        print(f"SKIP le parcours du disque n'a pas abouti — rien n'est mesuré :")
        for x in bloquantes:
            print(f"     {x}")
        return 0

    if signalees:
        print(f"  🔎 {len(signalees)} anomalie(s) du parcours — elles portent "
              f"sur le périmètre, pas sur les fiches :")
        for x in signalees:
            print(f"     {x}")
        print()

    if muets:
        print(f"  ⚪ {len(muets)} fiche(s) non mesurable(s) — jamais comptées "
              f"comme à jour :")
        for nom, raison in muets[:8]:
            print(f"     {nom:<34} {raison}")
        if len(muets) > 8:
            print(f"     … et {len(muets) - 8} autre(s)")
        print()

    if doutes:
        print(f"  ⚠️  {len(doutes)} fiche(s) dont le dépôt a bougé depuis "
              f"la dernière écriture :")
        for nom, depot, n in sorted(doutes, key=lambda x: -x[2]):
            print(f"     {nom:<26} {depot:<20} {n:>4} commit(s) depuis")
        print()
        print("     Un dépôt qui bouge ne prouve pas que la fiche ment — il")
        print("     prouve qu'elle n'a pas été relue. Le chiffre fait la")
        print("     différence : 1 commit n'est pas 699.")
    else:
        print("  ✅ aucune fiche mesurable n'est en retard sur son dépôt")

    auto_epreuve()
    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    # 🔴 Cette ligne est la DERNIERE `✅` du script, et le doctor resume un
    # controle vert par sa derniere ligne `✅`. Sans elle, il affichait
    # « l'alias résout `monapi` vers `Mon-API` » — le dernier test de
    # l'auto-epreuve, c'est-a-dire rien de lisible. Meme defaut que,
    # trouve le 26/09 en relisant la sortie du doctor apres la fusion.
    if not _ko:
        total = len(fiches_a_juger(brain))
        # Les anomalies non bloquantes entrent dans la LIGNE DE VERDICT, pas
        # seulement dans le corps : le doctor n affiche qu une ligne par
        # controle, et une anomalie qu on ne voit qu en lançant l outil a la
        # main est invisible la ou on regarde. La collision `mon-extracteur`
        # existait au premier vrai passage et ne remontait pas.
        # Court exprès : le doctor tronque son resume a 96 caracteres, et
        # « de parcours » en toutes lettres faisait couper la ligne.
        suffixe = f" · {len(signalees)} anomalie(s)" if signalees else ""
        print(f"\n  ✅ {total} fiche(s) · {total - len(doutes) - len(muets)} à jour "
              f"· {len(doutes)} en retard sur leur dépôt "
              f"· {len(muets)} non mesurable(s){suffixe}")
    # Le verdict ne rougit jamais sur les fiches — c'est le contrat, tranché le
    # 23/09. Seule l'auto-épreuve peut rougir : un contrôle dont l'instrument
    # est casse doit le dire, sinon il rend un vert qui ne mesure rien.
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(main())
