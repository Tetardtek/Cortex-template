#!/usr/bin/env python3
"""La convention de commit est-elle appliquée ?

`KERNEL.md ## Commit types` déclare dix types, chacun rattaché à une zone et à
un scribe propriétaire. Les six manifests de session chargent `KERNEL.md`. La
convention est donc **dans le contexte de chaque session**, depuis toujours.

Et pourtant, mesuré le 05/09 sur tout l'historique :

    2026-03   892 commits · 85 % conformes
    2026-04   133 · 42 %      2026-05    86 · 75 %
    2026-06    30 · 30 %      2026-07    11 ·  0 %
    2026-08   145 · 35 %      2026-09   245 ·  0 %

**Septembre, c'est le rework Myéline — c'est moi.** J'ai écrit 245 commits en
`zone : description` (`backlog :`, `handoff :`, `agents :`) au lieu de
`type: description`. J'ai suivi le motif que je voyais dans l'historique récent
plutôt que la table que je chargeais à chaque boot.

Une règle chargée que rien ne vérifie s'éteint sans bruit. C'est le cinquième
défaut de contrôle de la série : **celui qui n'existe pas.**

    python3 tools/convention_commits.py --brain ~/Dev/Brain

── Ce qu'il mesure, et pourquoi ainsi ──────────────────────────────────────

Il ne juge que les commits **postérieurs à son point de référence**, enregistré
dans `.convention-commits-depuis`. Faire rougir sur l'historique fabriquerait un
rouge permanent que personne ne peut verdir — on ne réécrit pas six mois de
messages, et c'est un piège dans lequel je suis déjà tombé
deux fois cette semaine.

🔴 **« Postérieur » voulait dire deux choses, et l'outil lisait la mauvaise** —
mesuré le 26/09. La plage `<ancre>..HEAD` ne veut pas dire
« écrits après l'ancre » : elle veut dire **« non atteignables depuis l'ancre »**.

Fusionner `main` dans `dev/myeline` a fait apparaître **20 commits datés des 3 et
4 septembre**, écrits AVANT que la règle existe — l'ancre `39e261c` est elle-même
datée du 05/09 et porte le message « la convention de commit parle AVANT le
commit ». Ces commits vivaient sur une branche jamais fusionnée : ils ne sont
ancêtres de rien, donc la plage les prenait. **Une référence de graphe employée
comme une référence de temps.**

Le plancher corrige ça : la date de l'ancre borne le jugement. Un commit dont la
date d'AUTEUR précède ce plancher est compté à part — « antérieur à la règle » —
et jamais comme conforme. L'abstention reste visible.

⚠️ **Le plancher est contournable et il faut le dire** : un `GIT_AUTHOR_DATE`
antidaté y échapperait. Ce contrôle mesure ce qui est écrit dans l'historique,
pas une intention ; et l'échappement propre existe déjà (`--no-verify`, qui se
voit). Un plancher franchissable sciemment reste préférable à un rouge permanent
que personne ne peut verdir.

Les types sont lus dans `KERNEL.md`, jamais recopiés ici : c'est la source
vivante, et un contrôle qui duplique sa référence dérive avec elle.

Sortie 1 si un commit postérieur au point de référence ne porte pas de type
déclaré.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TEMOIN = ".convention-commits-depuis"
EXEMPTIONS = ".convention-commits-exemptions"
SHA_COMPLET = re.compile(r"^[0-9a-f]{40}$")
TYPE_LIGNE = re.compile(r"^\|\s*`([a-z]+):`\s*\|")


def types_declares(kernel: Path) -> set[str]:
    """Les types que `KERNEL.md ## Commit types` déclare — la source vivante."""
    if not kernel.is_file():
        return set()
    dans_section = False
    trouves = set()
    for ligne in kernel.read_text(encoding="utf-8", errors="replace").splitlines():
        if ligne.startswith("## "):
            dans_section = "commit type" in ligne.lower()
            continue
        if dans_section:
            m = TYPE_LIGNE.match(ligne)
            if m:
                trouves.add(m.group(1))
    return trouves


def git(racine: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(racine), *args],
                       capture_output=True, text=True)
    return r.stdout.strip()


def fusion_pure(racine: Path, sha: str, parents: str) -> bool:
    """Un commit de fusion qui n'apporte AUCUN changement propre.

    Decide le 16/09 par l'owner. Les fusions de PR sont ecrites par Gitea, cote
    serveur : le hook `pre-commit` ne les voit pas, et leur message est
    `Merge pull request '<titre>' (#n) from ...`. Quatre sont apparues d'un
    coup en fusionnant le travail de la nuit, et le controle avait raison de
    les signaler — il mesurait ce qui est ecrit dans l'historique.

    **Mais une fusion pure ne porte pas de changement : elle coud.** Lui
    demander quel scribe la possede n'a pas de reponse, puisqu'elle ne possede
    rien. C'est exactement ce que la convention veut dire par « un type est une
    PROPRIETE ».

    🔴 L'exemption s'arrete la, et c'est le point : un merge qui RESOUT un
    conflit ecrit du contenu. Celui-la doit dire quel scribe le possede, comme
    n'importe quel autre commit. On le distingue en comparant l'arbre du merge
    a celui de CHACUN de ses parents — `git diff-tree` sans option de fusion ne
    montre rien pour une fusion triviale, et montre la resolution sinon.

    Sans cette restriction, l'exemption deviendrait une porte : il suffirait de
    faire passer un changement dans un commit de fusion pour echapper a la
    regle.
    """
    if len(parents.split()) < 2:
        return False
    # `--cc` est le diff COMBINE : il ne montre que ce que la fusion a decide
    # elle-meme, c'est-a-dire la resolution de conflit. Vide = elle n'a rien
    # decide, elle a cousu.
    #
    # ⚠️ Premier jet : `git diff <parent> <sha>` pour chaque parent. C'est faux
    # et ca ne mord jamais — le diff contre le premier parent porte TOUT ce que
    # la branche apporte, donc il n'est jamais vide. Le commentaire annoncait
    # deja `diff-tree`, l'implementation faisait autre chose. Verifie dans les
    # deux sens avant de le croire : 0 fichier sur nos fusions triviales,
    # 1 fichier sur `8ede95d` qui a resolu un conflit.
    return not git(racine, "diff-tree", "--cc", "--name-only",
                   "--no-commit-id", sha).strip()


_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


def plancher(racine: Path, depuis: str) -> int | None:
    """L'horodatage de l'ancre, ou `None` si elle n'est pas lisible.

    On prend la date de COMMIT de l'ancre : le moment ou la regle est entree
    dans le depot. Et on la compare a la date d'AUTEUR de chaque commit : le
    moment ou son message a ete ecrit. Un commit redige avant que la regle
    existe n'a pas a la respecter, meme s'il entre plus tard.

    🔴 Rendait `0` quand l'ancre etait illisible — relu en juge le 26/09. Zero
    est un plancher que tout franchit : aucun commit n'etait plus compte
    anterieur, et le controle redevenait silencieusement celui d'avant. `None`
    veut dire « je n'ai pas pu regarder », et l'appelant doit s'abstenir.
    """
    v = git(racine, "show", "-s", "--format=%ct", depuis)
    return int(v) if v.isdigit() else None


def plancher_lisible(racine: Path, depuis: str) -> str:
    return git(racine, "show", "-s", "--format=%ad", "--date=short", depuis) \
        or "date inconnue"


def exemptions(racine: Path, fichier: Path) -> tuple[dict[str, str], list[str]]:
    """(sha complet → raison, erreurs) — les exemptions NOMMÉES. Pur à git près.

    Tranché par l'owner le 27/09, pour la fusion #86 : l'historique partagé ne se
    réécrit pas, et un rouge permanent se ignore — une exemption nommée est
    « plus élégante et moins rigide ». Pour qu'elle ne devienne pas une porte,
    trois refus : un SHA qui n'est pas complet (40 caractères — un préfixe
    pourrait finir par en désigner un autre), une ligne sans raison, un commit
    introuvable dans ce dépôt (une exemption périmée ne doit pas dormir).

    Format, une ligne par commit : `<sha complet> <raison>` ; `#` commente.
    """
    nommees: dict[str, str] = {}
    erreurs: list[str] = []
    if not fichier.is_file():
        return nommees, erreurs
    for n, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        sha, _, raison = ligne.partition(" ")
        if not SHA_COMPLET.match(sha):
            erreurs.append(f"ligne {n} : « {sha[:16]} » n'est pas un SHA complet")
            continue
        if not raison.strip():
            erreurs.append(f"ligne {n} : {sha[:8]} sans raison — une exemption se justifie")
            continue
        r = subprocess.run(["git", "-C", str(racine), "cat-file", "-e", f"{sha}^{{commit}}"],
                           capture_output=True)
        if r.returncode != 0:
            erreurs.append(f"ligne {n} : {sha[:8]} introuvable dans ce dépôt")
            continue
        nommees[sha] = raison.strip()
    return nommees, erreurs


def juger(racine: Path, depuis: str, types: set[str], borne: int,
          nommees: dict[str, str] | None = None
          ) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """(juges, fautifs, fusions pures, anterieurs a la regle, exemptes nommement).

    Separe de l'affichage pour etre eprouve sur un depot fabrique — un controle
    qui ne peut se mesurer que sur le vrai depot ne se mesure jamais.

    `borne` est PASSEE et non calculee ici : l'appelant doit avoir verifie
    qu'elle existe. Une fonction qui se rabat sur un plancher par defaut cache
    le cas ou l'ancre est illisible.
    """
    # `%P` donne les parents (deux ou plus = fusion), `%at` la date d'auteur.
    lignes = [s for s in git(racine, "log", f"{depuis}..HEAD",
                             "--format=%h|%H|%P|%at|%s").splitlines() if s]
    motif = re.compile(r"^(" + "|".join(sorted(types)) + r")(\([a-z0-9/-]+\))?: ")

    juges, fautifs, exemptes, anterieurs, nommes = [], [], [], [], []
    for ligne in lignes:
        sha, complet, parents, at, sujet = ligne.split("|", 4)
        s = f"{sha}|{parents}|{sujet}"
        if at.isdigit() and int(at) < borne:
            anterieurs.append(s)
            continue
        juges.append(s)
        if motif.match(sujet):
            continue
        if nommees and complet in nommees:
            nommes.append(s)
            continue
        if fusion_pure(racine, sha, parents):
            exemptes.append(s)
        else:
            fautifs.append(s)
    return juges, fautifs, exemptes, anterieurs, nommes


def auto_epreuve() -> None:
    """Le plancher fait-il ce qu'il dit — et ne tait-il QUE ce qu'il doit ?

    Deux temoins, et le second est celui qui compte : un plancher de date pourrait
    tout taire et paraitre vert. Il faut prouver qu'un commit posterieur sans type
    rougit toujours.
    """
    import os
    import tempfile

    print("\nAUTO-ÉPREUVE — sur un dépôt fabriqué\n")
    types = {"scribe", "fix"}

    with tempfile.TemporaryDirectory(prefix="temoin-convention-") as tmp:
        r = Path(tmp)

        def commit(sujet: str, quand: str, fichier: str) -> None:
            (r / fichier).write_text(quand, encoding="utf-8")
            env = dict(os.environ, GIT_AUTHOR_DATE=quand, GIT_COMMITTER_DATE=quand,
                       GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.run(["git", "-C", str(r), "add", fichier], check=True, env=env)
            subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", sujet],
                           check=True, env=env)

        subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
        commit("scribe: la base", "2026-09-01T10:00:00", "a.md")
        # L ANCRE, datee du 05/09 comme la vraie (39e261c).
        commit("fix: la convention parle AVANT le commit", "2026-09-05T10:00:00",
               "b.md")
        ancre = git(r, "rev-parse", "HEAD")

        # Une branche partie AVANT l ancre, avec un message sans type, fusionnee
        # APRES : c est exactement la situation des 20 commits du 26/09.
        subprocess.run(["git", "-C", str(r), "checkout", "-q", "-b", "vieille",
                        "HEAD~1"], check=True)
        commit("notes : ecrit le 03/09, avant que la regle existe",
               "2026-09-03T10:00:00", "c.md")
        subprocess.run(["git", "-C", str(r), "checkout", "-q", "main"], check=True)
        subprocess.run(["git", "-C", str(r), "merge", "-q", "--no-ff", "vieille",
                        "-m", "scribe: la vieille branche rejoint main"],
                       check=True,
                       env=dict(os.environ, GIT_AUTHOR_DATE="2026-09-26T10:00:00",
                                GIT_COMMITTER_DATE="2026-09-26T10:00:00",
                                GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))

        _j, fautifs, _e, anterieurs, _n = juger(r, ancre, types, plancher(r, ancre))
        verifie("le commit du 03/09, non atteignable, est compté ANTÉRIEUR",
                [s.split("|", 2)[2] for s in anterieurs],
                ["notes : ecrit le 03/09, avant que la regle existe"])
        verifie("… et il ne compte pas comme non conforme", fautifs, [])

        # 🔴 LE temoin qui compte : le plancher ne doit pas TOUT taire.
        commit("notes : ecrit le 26/09, apres la regle", "2026-09-26T11:00:00",
               "d.md")
        _j, fautifs, _e, anterieurs, _n = juger(r, ancre, types, plancher(r, ancre))
        verifie("un commit POSTÉRIEUR sans type rougit toujours",
                [s.split("|", 2)[2] for s in fautifs],
                ["notes : ecrit le 26/09, apres la regle"])
        verifie("… et l'antérieur reste à part, il n'a pas bougé de colonne",
                len(anterieurs), 1)

        commit("scribe: ecrit le 26/09, avec son type", "2026-09-26T12:00:00",
               "e.md")
        _j, fautifs, _e, _a, _n = juger(r, ancre, types, plancher(r, ancre))
        verifie("un commit postérieur AVEC son type passe",
                len(fautifs), 1)

        verifie("le plancher est bien la date de l'ancre, pas celle du jour",
                plancher_lisible(r, ancre), "2026-09-05")

        # 🔴 Les deux defauts trouves en relisant en JUGE, le 26/09.
        verifie("une ancre illisible rend None, JAMAIS 0",
                plancher(r, "deadbeefdeadbeef"), None)
        verifie("… car 0 est un plancher que tout franchit",
                [s.split("|", 2)[2] for s in juger(r, ancre, types, 0)[3]], [])
        verifie("… et avec le vrai plancher, l'antérieur est bien vu",
                len(juger(r, ancre, types, plancher(r, ancre))[3]), 1)

        # ── L'exemption NOMMÉE — tranchée le 27/09 pour la fusion #86 ────────
        fautif = git(r, "log", "-1", "--format=%H", "--grep", "apres la regle").strip()
        fichier = r / "exemptions"
        fichier.write_text(f"# un commentaire\n{fautif} la raison, écrite\n",
                           encoding="utf-8")
        nommees, erreurs = exemptions(r, fichier)
        _j, fautifs, _e, _a, nommes = juger(r, ancre, types, plancher(r, ancre), nommees)
        verifie("un commit exempté NOMMÉMENT ne rougit plus", fautifs, [])
        verifie("… il est compté à part, pas perdu", len(nommes), 1)
        verifie("… et sans le fichier, il rougit à nouveau",
                len(juger(r, ancre, types, plancher(r, ancre))[1]), 1)
        fichier.write_text(f"{fautif[:12]} un prefixe\n", encoding="utf-8")
        verifie("un SHA abrégé est refusé", len(exemptions(r, fichier)[1]), 1)
        fichier.write_text(f"{fautif}\n", encoding="utf-8")
        verifie("une exemption sans raison est refusée", len(exemptions(r, fichier)[1]), 1)
        fichier.write_text("0" * 40 + " un commit qui n'existe pas\n", encoding="utf-8")
        verifie("une exemption vers un commit introuvable est refusée",
                len(exemptions(r, fichier)[1]), 1)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--poser", action="store_true",
                   help="(re)pose le point de référence sur HEAD")
    args = p.parse_args()
    racine = args.brain.expanduser().resolve()

    types = types_declares(racine / "KERNEL.md")
    if not types:
        print("\n  ❌ aucun type lisible dans `KERNEL.md ## Commit types`.")
        print("     Le contrôle refuse de juger sans sa source — un contrôle qui")
        print("     invente sa référence ne mesure plus rien.\n")
        return 1

    temoin = racine / "workspace" / TEMOIN
    if args.poser or not temoin.is_file():
        head = git(racine, "rev-parse", "HEAD")
        temoin.parent.mkdir(parents=True, exist_ok=True)
        temoin.write_text(head + "\n", encoding="utf-8")
        print(f"\nCONVENTION DE COMMIT — point de référence posé sur {head[:8]}")
        print(f"  {len(types)} types déclarés : {', '.join(sorted(types))}")
        print("  Les commits qui suivent seront mesurés.\n")
        return 0

    depuis = temoin.read_text(encoding="utf-8").strip()
    borne = plancher(racine, depuis)
    if borne is None:
        # 🔴 Une reference invalide rendait un VERT — relu en juge le 26/09.
        # `git log <bidon>..HEAD` echoue, la liste est vide, et le controle
        # imprimait « ✅ aucun commit a juger ». Le defaut precede le plancher :
        # il vient du premier jet. Une abstention DECLAREE (« SKIP » en debut de
        # ligne) devient ⏭️ au doctor ; un vert qui ne mesure rien y devient ✅.
        print(f"\nSKIP: le point de référence `{depuis[:12]}` n'est pas un commit "
              f"de ce dépôt.")
        print(f"  Fichier : workspace/{TEMOIN}")
        print("  Rien n'est jugé — et surtout pas déclaré conforme : `git log")
        print("  <invalide>..HEAD` rend une liste VIDE, ce qui ressemble à")
        print("  « aucun commit fautif ».")
        print("  Reposer la référence : --poser\n")
        auto_epreuve()
        print(f"  {_ok} vérification(s), {_ko} échec(s)\n")
        return 1 if _ko else 0

    nommees, erreurs = exemptions(racine, racine / "workspace" / EXEMPTIONS)
    juges, fautifs, exemptes, anterieurs, nommes = juger(racine, depuis, types, borne,
                                                         nommees)

    print(f"\nCONVENTION DE COMMIT — depuis {depuis[:8]}"
          f" ({plancher_lisible(racine, depuis)})\n")
    print(f"  types déclarés dans KERNEL.md   {len(types)}")
    print(f"  commits mesurés                 {len(juges)}")
    print(f"  fusions pures exemptées         {len(exemptes)}")
    print(f"  exemptés nommément              {len(nommes)}")
    print(f"  antérieurs à la règle           {len(anterieurs)}")
    print(f"  non conformes                   {len(fautifs)}")

    for s in nommes:
        sha, _p, sujet = s.split("|", 2)
        raison = next((v for k, v in nommees.items() if k.startswith(sha)), "")
        print(f"\n  ⚪ {sha}  exempté nommément — {raison}")
        print(f"     {sujet[:70]}")
    if erreurs:
        print(f"\n  ❌ {len(erreurs)} exemption(s) refusée(s) — workspace/{EXEMPTIONS} :")
        for e in erreurs:
            print(f"     {e}")

    if anterieurs:
        print(f"\n  ⚪ {len(anterieurs)} commit(s) écrits AVANT l'ancre et non "
              f"atteignables depuis elle —")
        print("     jamais comptés comme conformes, jamais jugés non conformes :")
        for s in anterieurs[:4]:
            sha, _p, sujet = s.split("|", 2)
            print(f"     {sha}  {sujet[:60]}")
        if len(anterieurs) > 4:
            print(f"     … et {len(anterieurs) - 4} autre(s)")
        print("     La plage `<ancre>..HEAD` dit « non atteignable », pas")
        print("     « posterieur ». Ceux-ci vivaient sur une branche jamais")
        print("     fusionnee — ils ne sont ancetres de rien.")

    if not juges:
        print("\n  ✅ aucun commit à juger depuis le point de référence\n")
        auto_epreuve()
        print(f"  {_ok} vérification(s), {_ko} échec(s)\n")
        return 1 if _ko else 0

    if fautifs:
        print()
        for s in fautifs[:8]:
            sha, _parents, sujet = s.split("|", 2)
            print(f"  ❌ {sha}  {sujet[:64]}")
        if len(fautifs) > 8:
            print(f"     … et {len(fautifs) - 8} autre(s)")
        print(f"\n     Types attendus : {', '.join(sorted(types))}")
        print("     Un type est une PROPRIÉTÉ — il dit quel scribe possède le")
        print("     changement et dans quelle zone. Ce n'est pas un préfixe")
        print("     décoratif. Détail — `KERNEL.md ## Commit types`.\n")
        auto_epreuve()
        print(f"  {_ok} vérification(s), {_ko} échec(s)\n")
        return 1

    if erreurs:
        # Une exemption refusée ROUGIT : elle ne devient jamais une porte.
        auto_epreuve()
        print(f"  {_ok} vérification(s), {_ko} échec(s)\n")
        return 1

    taux = 100 * (len(juges) - len(fautifs)) / len(juges)
    auto_epreuve()
    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    if not _ko:
        print(f"\n  ✅ {taux:.0f} % conformes sur {len(juges)} commit(s) jugé(s) — "
              f"la convention tient\n")
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(main())
