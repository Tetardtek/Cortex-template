#!/usr/bin/env python3
# brain-distribuable: oui  # le mutant du juge et du forgeron — éprouver un contrôle en
# cassant le code exprès, lancé à la main, jamais par un automate.
"""Casser le code exprès, et refuser de conclure si le sabotage n'a pas eu lieu.

    python3 scripts/saboter.py --motif "…" --par "…" <fichier> -- <commande>

⚠️ **Les options viennent AVANT le fichier.** `argparse.REMAINDER` avale tout
ce qui suit le premier argument positionnel, `--motif` compris : placées après,
elles finissent dans la commande et l'outil réclame des arguments pourtant
fournis.

Applique un remplacement dans un fichier, joue la commande, **rend toujours le
fichier à son état d'origine**, et dit si la commande a rougi comme elle
devait.

**Pourquoi cet outil existe.** Un test vert ne prouve rien tant qu'on ne l'a pas
cassé exprès — mesuré le 09/09 sur un projet : sur 112 sabotages, **sept tests
verts n'éprouvaient rien**, chacun pour une raison différente et aucune
trouvable en relisant.

⚠️ **Mais un sabotage qui n'a pas eu lieu ressemble exactement à un contrôle
solide.** Le même soir, en éprouvant un contrôle du CORE, j'ai injecté
`Path.home()` en remplaçant `from pathlib import Path` — sauf que le module
visé n'importe pas `pathlib`. Le remplacement n'a rien remplacé, le test est
resté vert, et j'ai failli conclure que mon contrôle était faible. Il était
juste ; c'est mon témoin qui n'existait pas.

D'où les gardes, reprises de l'outillage Rust de ce projet :

    🔴 MOTIF INTROUVABLE      le motif n'est pas dans le fichier → sortie 2
    🔴 SABOTAGE INERTE        le remplacement laisse le fichier identique → sortie 3
    🔴 ESSAI NON RESTAURÉ     l'abri d'un essai précédent est encore là → sortie 4
    🔴 COMMANDE INEXÉCUTABLE  la commande n'a pas démarré → sortie 5

Toutes rendent un code non nul : dans un enchaînement, rien ne conclut sur un
sabotage qui n'a pas eu lieu.

Le sabotage inerte se juge sur le texte APRÈS remplacement, pas sur la
présence de `--par` : retirer un élément d'une liste
(`--motif "'a', 'b'," --par "'a',"`) laisse un `--par` déjà présent, et c'est
pourtant un vrai sabotage.

**Ce que l'outil ne fait pas** : juger si le contrôle est bon. Il dit si la
commande a rougi, pas si elle a rougi *pour la bonne raison* — un test peut
tomber sur une erreur de syntaxe introduite par le sabotage lui-même. Lire la
sortie reste nécessaire ; `--montrer` l'affiche.

**Le `.pyc` d'à côté**. Python valide un `.pyc` par la taille et la
seconde de modification de sa source — et `-B` n'empêche que d'en ÉCRIRE, pas
d'en lire un périmé. Un sabotage de même taille écrit dans la même seconde que
le `.pyc` fait tourner l'ancien code : le mutant paraît survivre. Et `copy2`
rend à l'original son mtime : le `.pyc` du mutant, de même seconde, le
remplacerait au prochain import. L'outil efface donc les `.pyc` de la cible
(tous les interpréteurs) avant la commande et après la restauration.

**Le nom, Python le donne**. Toute cible, avec ou sans extension : un
fichier sans `.py` chargé par `SourceFileLoader` (`scripts/hooks/pre-commit-zone`)
a aussi son `.pyc` — `pre-commit-zonecpython-314.pyc`, sans point. Le nom vient de
`importlib.util.cache_from_source`, généralisé à tout interpréteur et tout
`opt-N` ; seuls les `.pyc` de CETTE cible sont effacés, jamais ceux d'un voisin
au nom proche. Avec `PYTHONPYCACHEPREFIX` (que la commande hérite), les `.pyc`
vivent sous ce préfixe : ils y sont cherchés aussi.

Le fichier est restauré même si la commande échoue, est interrompue, ou si
l'outil est tué (`try/finally` + copie de sauvegarde). Tué avant d'avoir rendu
le fichier, l'outil laisse son abri à côté : le lancement suivant le voit et
refuse (sortie 4) au lieu de l'écraser — c'est la seule copie de l'original.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# Les interpréteurs dont le `cache_tag` peut nommer un `.pyc` (`cpython-314`, `pypy310`…).
# Une liste fermée : sans elle, `zonex` + `cpython-314` ressemblerait à `zone` + un
# interpréteur `xcpython` — et un fichier voisin perdrait son `.pyc`.
INTERPRETES = ("cpython", "pypy", "graalpy", sys.implementation.name)


def pyc_de(cible: Path) -> list[Path]:
    """Les `.pyc` de `cible`, quel que soit l'interpréteur qui les a écrits
    (`jouet.cpython-312.pyc`, `-314`, `.opt-1`…), avec ou sans extension à la source,
    dans `__pycache__` d'à côté et sous `PYTHONPYCACHEPREFIX` s'il est posé : la
    commande éprouvée n'est pas forcément lancée par le même Python."""
    import importlib.util
    tag = sys.implementation.cache_tag
    if not tag:
        return []
    # Le nom que CE Python donnerait — on n'en garde que ce qui précède son `cache_tag`.
    nom = Path(importlib.util.cache_from_source(str(cible))).name
    prefixe = nom[:nom.index(tag)]
    motif = re.compile(re.escape(prefixe)
                       + "(?:" + "|".join(re.escape(i) for i in dict.fromkeys(INTERPRETES)) + r")-?\d+"
                       + r"(?:\.opt-\d+)?\.pyc")
    dossiers = [cible.parent / "__pycache__"]
    for racine in (os.environ.get("PYTHONPYCACHEPREFIX"), sys.pycache_prefix):
        if racine:
            dossiers.append(Path(racine).joinpath(*cible.parent.parts[1:]))
    trouves = []
    for dossier in dict.fromkeys(dossiers):
        if dossier.is_dir():
            trouves += [p for p in dossier.iterdir() if motif.fullmatch(p.name)]
    return trouves


def oublier_pyc(cible: Path) -> None:
    """Efface les `.pyc` de `cible` (`pyc_de`)."""
    for pyc in pyc_de(cible):
        # Appelée aussi dans le `finally` : une erreur ici ne doit pas empêcher de
        # juger la restauration. Elle se dit — un `.pyc` resté peut servir le mauvais code.
        try:
            pyc.unlink(missing_ok=True)
        except OSError as exc:
            print(f"  ⚠️  {pyc.name} non effacé ({type(exc).__name__}) : un import "
                  f"peut servir le mauvais code — effacer le `__pycache__` à la main")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("fichier", type=Path)
    p.add_argument("--motif", required=True, help="le texte à remplacer")
    p.add_argument("--par", required=True, help="ce qui le remplace")
    p.add_argument("--montrer", action="store_true",
                   help="afficher la sortie de la commande")
    p.add_argument("commande", nargs=argparse.REMAINDER,
                   help="après « -- », la commande qui doit rougir")
    args = p.parse_args()

    commande = [a for a in args.commande if a != "--"]
    if not commande:
        print("  Il faut une commande après « -- » : sans elle, rien n'est éprouvé.")
        return 2

    cible = args.fichier.expanduser().resolve()
    if not cible.is_file():
        print(f"  🔴 {cible} n'existe pas.")
        return 2

    source = cible.read_text(encoding="utf-8")

    # ⚠️ L'abri va À CÔTÉ du fichier, pas dans /tmp : le 09/09 la partition
    # système était pleine à 0 octet, et un abri sur /tmp aurait échoué au pire
    # moment — juste avant de rendre le fichier. Le même disque que la cible
    # garantit qu'on peut toujours la restaurer.
    abri = cible.with_name(cible.name + ".saboter-abri")

    # ── Garde de l'abri : un essai précédent a-t-il été tué avant de rendre
    # le fichier ? Son abri est la seule copie de l'original : l'écraser le
    # perdrait, et le fichier resté saboté passerait pour l'original.
    if abri.exists():
        print(f"\n  🔴 ESSAI NON RESTAURÉ : {abri.name} existe déjà\n")
        print("     Un essai précédent n'a pas rendu le fichier : il est peut-être")
        print("     resté saboté. Comparer, remettre l'abri à sa place, puis")
        print("     relancer. Rien n'a été touché.\n")
        return 4

    # ── Garde 1 : le motif est-il seulement là ?
    if args.motif not in source:
        print(f"\n  🔴 MOTIF INTROUVABLE dans {cible.name}\n")
        print(f"     « {args.motif[:70]} »")
        print("\n     Le sabotage n'aurait rien remplacé, et le test serait resté")
        print("     vert — pour une raison qui n'a rien à voir avec le contrôle.")
        print("     Rien n'a été touché.\n")
        return 2

    # ⚠️ Variante du même piège, vécue le 09/10/09 par une autre session :
    # asserter la présence d'un motif COURT, puis remplacer un motif PLUS LONG
    # construit à partir de lui. Le court était présent, le long non.
    # L'assertion est passée, le remplacement n'a rien fait, et le script a
    # répondu « README complété ». **Vérifier autre chose que ce qu'on fait.**
    #
    # Ici la garde porte sur `--motif` lui-même, celui qui sera remplacé — il
    # n'y a pas deux motifs, donc pas d'écart possible entre le vérifié et le
    # remplacé. C'est la raison d'être de cet outil.

    # ── Garde 2 : le remplacement change-t-il quelque chose ?
    # On juge le texte APRÈS remplacement, pas la présence de `--par` : un
    # retrait d'élément de liste laisse un `--par` déjà présent, et c'est un
    # vrai sabotage. Un fichier resté saboté, lui, se reconnaît à son abri.
    sabote = source.replace(args.motif, args.par, 1)
    if sabote == source:
        print(f"\n  🔴 SABOTAGE INERTE dans {cible.name}\n")
        print(f"     « {args.par[:70]} »")
        print("\n     Le remplacement laisse le fichier identique : le test")
        print("     resterait vert sans rien éprouver. Rien n'a été touché.\n")
        return 3

    occurrences = source.count(args.motif)
    shutil.copy2(cible, abri)

    # Pas de `return` dans le `finally` : il prendrait le pas sur ceux du `try`
    # et avalerait une exception en vol. Le `try` note son verdict, le
    # `finally` rend le fichier, on juge après.
    verdict = None
    try:
        cible.write_text(sabote, encoding="utf-8")
        oublier_pyc(cible)

        # Vérification a posteriori : le fichier a-t-il VRAIMENT changé ?
        if cible.read_text(encoding="utf-8") == source:
            print("\n  🔴 Le fichier est inchangé après écriture — rien conclu.\n")
            verdict = 3
        else:
            print(f"\n  ✂️  {cible.name} saboté "
                  f"({occurrences} occurrence(s) du motif, la première remplacée)")
            # ⚠️ Troisième garde, ajoutée après s'être fait prendre. Une commande
            # qui n'a pas pu DÉMARRER ne dit rien du contrôle — mais sans ce
            # `try`, l'outil sortait en erreur et le code non nul se lisait comme
            # « a rougi ». Un instrument qui confond « le test est tombé » et « le
            # test n'a pas tourné » est pire qu'absent : il rassure.
            try:
                r = subprocess.run(commande, capture_output=True, text=True)
            except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
                print(f"\n  🔴 COMMANDE INEXÉCUTABLE : {type(exc).__name__}")
                print(f"     {' '.join(commande)[:90]}")
                print("\n     Rien n'a été mesuré. Les mots de la commande doivent être")
                print("     séparés — sous zsh, `$VAR` ne se découpe PAS toute seule.\n")
                verdict = 5
            else:
                if args.montrer:
                    print("\n" + (r.stdout or "")[-3000:])
                    if r.stderr:
                        print(r.stderr[-1500:])
    finally:
        shutil.copy2(abri, cible)
        oublier_pyc(cible)
        rendu = cible.read_text(encoding="utf-8") == source
        if rendu:
            abri.unlink(missing_ok=True)
        print(f"  ↩️  {cible.name} {'rendu à son état d’origine' if rendu else '🔴 NON RESTAURÉ'}")
        if not rendu:
            print(f"     Copie de sauvegarde CONSERVÉE : {abri}")

    if not rendu:
        return 4  # prime sur tout autre verdict, comme avant
    if verdict is not None:
        return verdict

    print()
    if r.returncode != 0:
        print(f"  ✅ la commande a rougi (code {r.returncode}) — le contrôle éprouve\n")
        return 0
    print("  ❌ la commande est restée VERTE malgré le sabotage.\n")
    print("     Soit le contrôle ne mesure pas ce qu'on croit, soit le sabotage")
    print("     ne touche pas ce qu'il mesure. Lire la sortie avec --montrer")
    print("     avant de conclure : les deux se ressemblent.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
