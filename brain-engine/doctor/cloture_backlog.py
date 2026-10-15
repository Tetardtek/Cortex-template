#!/usr/bin/env python3
"""Un item soldé dit-il ce qu'il a mesuré, et ce qui le tient ?

Demande de l'owner le 05/09 : *« on doit trouver un garde-fou pour marquer quand
c'est clos absolument, c'est une perte de temps sinon — peut-être qu'il faudrait
un rapport de clôture »*.

Le défaut est symétrique, et les deux moitiés ont été commises le même jour :

    clos sans marqueur     4 items livrés le matin, comptés ouverts l'après-midi
    marqué sans preuve    42 items sur 61 ne portent aucune date de clôture

La seconde moitié coûte plus cher que la première. Un item marqué ✅ sans dire ce
qu'il a mesuré oblige à rouvrir le dossier pour savoir si c'est vrai — et c'est
exactement le temps que la clôture devait faire gagner.

    python3 tools/cloture_backlog.py --brain ~/Dev/Brain --projet <projet>
    python3 tools/cloture_backlog.py --brain ~/Dev/Brain --tous

Sans `--projet`, la seule liste du brain ; s'il en a plusieurs, il faut la nommer.

── Le format attendu ───────────────────────────────────────────────────────

    - ✅ ~~**[MY-xx] Titre**~~ — **soldé le 05/09.**

      > **Clôture** — mesuré : 681 Mo → 41 Go libres · tenu par : `brain doctor`
      > contrôle « niveaux vs scopes »

Deux champs, et le second est le plus utile. **`mesuré`** dit ce qui a changé,
avec des chiffres. **`tenu par`** dit ce qui empêche le retour — un contrôle, un
hook, ou franchement `rien`, ce qui est une information en soi : un item soldé
sans filet est un item qui se rouvrira sans prévenir.

── Ce qu'il ne fait pas ────────────────────────────────────────────────────

Il ne juge pas les items clos avant la règle. Les réécrire demanderait de
rouvrir des dizaines de dossiers pour reconstituer des mesures d'il y a des
semaines — un rouge que personne ne peut verdir, le piège de et.
Ils sont **nommés** dans `instance/doctor/cloture-sans-rapport`, une ligne par fiche :

    <PREFIXE>-12 <raison>

Jusqu'au 27/09 ce fichier portait un NOMBRE, et le contrôle rougissait sur
l'augmentation : un rapport ajouté à une vieille fiche et une fiche close sans
rapport s'annulaient, sans rien dire. La liste ne s'annule pas. Une fiche close
sans rapport qu'elle ne nomme pas rougit ; une ligne sans raison, une fiche
nommée qui n'est plus close sans rapport (rapport ajouté, fiche rouverte ou
disparue) rougissent aussi — une exemption qui ne sert plus se retire, sinon
elle couvrira la prochaine.

── Les formes qu'il lit ────────────────────────────────────────────────────

Jusqu'au 27/09 il ne cherchait que `- ✅ ~~**[MY-x]`. Depuis le 11/09 les fiches
s'écrivent en titre `### [MY-x]`, et se closent en portant `✅` dans le titre :
26 fiches closes lui étaient invisibles, et il rendait vert sur les autres.
Il lit maintenant toutes les ENTRÉES, les règles de l'audit :

    ## / ### [MY-x] …                  un titre ; close s'il porte ✅
    - [0 à 2 emoji] [~~]**[MY-x] …      une puce ; close si la ligne porte ✅

Une fiche peut être REPRISE plus bas (une seconde entrée l'instruit ou la
clôt) : son statut et son rapport se lisent dans sa **dernière** entrée. Le
rapport d'une fiche en titre s'écrit de la même façon, sous le titre.

Il ne devine pas non plus qu'un item ouvert est en fait clos : aucune mesure ne
distingue « pas fait » de « fait, pas marqué ». Cette moitié-là reste humaine.

Sortie 1 si une fiche close sans rapport n'est pas nommée, ou si la liste
nomme ce qui ne l'est plus.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fiches  # noqa: E402 — la seule définition d'une fiche
from _config_instance import config_du_doctor  # noqa: E402 — instance/doctor/, l'ancien emplacement en repli

TEMOIN = ".cloture-sans-rapport"

# Ce qu'est une fiche, où elle finit, ce qui la dit close : `_fiches.py` — la
# définition partagée par les trois lecteurs du backlog depuis le 27/09.
EXEMPTION = re.compile(r"^([A-Z][A-Z0-9]*-\d+)\s+(\S.*)$")
# La fenêtre valait SIX lignes. Les deux premiers rapports détaillés n'y
# entraient pas : `mesuré :` en ligne 3, `tenu par :` en ligne 9.
# Le contrôle les comptait « sans rapport » alors qu'ils en portaient un plus
# complet que ce qu'il exigeait. Un instrument qui punit la précision qu'il
# réclame est un instrument mal réglé.
FENETRE = 25
#: Les caractères qu'un champ du rapport peut porter avant ses deux-points.
CHAMP = 80


def fiches_closes(fiches: dict) -> dict[str, str]:
    """{MY-x: le texte qui suit l'entrée qui la DIT close}, pour les fiches livrées.

    L'entrée s'arrête à la suivante : le rapport d'une fiche ne se lit jamais
    dans la voisine — c'est la frontière que l'audit a vue franchir
    (un « ✅ Soldé » d'une fiche lu sous sa voisine).
    """
    return {cle: "\n".join(f.declarante.lignes[1:1 + FENETRE])
            for cle, f in fiches.items() if f.etat == "livré"}


def a_son_rapport(suite: str) -> bool:
    # Le champ se cherche sans sa MISE EN PAGE, en deux temps — chacun
    # trouvé par un rapport réel qui échouait :
    #
    #   `**tenu par** :`   du gras légitime, cherché comme chaîne nue
    #   `**tenu\n  > par**`  le même, coupé par un retour à la ligne
    #
    # Un contrôle qui exige un champ doit le reconnaître quelle que soit la
    # façon dont il est écrit. Les deux premiers rapports détaillés étaient
    # comptés « sans rapport » alors qu'ils en portaient un plus complet que
    # ce que le contrôle demandait.
    #
    # Et le champ peut porter quelques mots avant ses deux-points : « mesuré sur le runner
    # (PR #83, fermée) : … » — le rapport de BS-32, complet, compté « sans rapport » faute
    # de la chaîne `mesuré :` (15/10). Jusqu'à ses deux-points, sans franchir un `·` (le
    # séparateur des champs) ni d'autres deux-points, et pas plus loin que CHAMP.
    nu = re.sub(r"\s+", " ", suite.replace("**", "").replace("`", "")
                                  .replace("\n", " ").replace(">", " "))
    return "Clôture" in nu and all(re.search(rf"{champ}\b[^:·]{{0,{CHAMP}}}:", nu)
                                   for champ in ("mesuré", "tenu par"))


def sans_rapport(fiches: dict) -> list[str]:
    """Les fiches closes dont l'entrée de clôture ne porte pas de rapport."""
    return [cle for cle, suite in fiches_closes(fiches).items()
            if not a_son_rapport(suite)]


def lire_exemptions(chemin: Path) -> tuple[dict[str, str], list[str]]:
    """({MY-x: raison}, [lignes fautives]). Absent = aucune exemption."""
    if not chemin.is_file():
        return {}, []
    nommees, fautives = {}, []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        brut = ligne.strip()
        if not brut or brut.startswith("#"):
            continue
        m = EXEMPTION.match(brut)
        if m:
            nommees[m.group(1)] = m.group(2)
        else:
            fautives.append(brut)
    return nommees, fautives


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--projet", default=None,
                   help="la liste à juger — sans lui, la seule du brain")
    p.add_argument("--tous", action="store_true",
                   help="chaque projet qui déclare un `prefixe:`")
    args = p.parse_args()
    racine = args.brain.expanduser().resolve()
    if not args.tous:
        try:
            projet = args.projet or _fiches.projet_par_defaut(racine)
        except _fiches.Illisible as exc:
            print(f"\n  ❌ {exc}\n")
            return 1
        return juger(racine, projet)
    codes = {}
    for slug in _fiches.projets_a_liste(racine):
        print(f"\n━━ {slug}")
        codes[slug] = juger(racine, slug)
    rouges = [s for s, c in codes.items() if c]
    if rouges:
        print(f"VERDICT: une clôture sans rapport, ou une exemption fausse — {', '.join(rouges)}")
        return 1
    print(f"VERDICT: toute fiche close porte son rapport — {len(codes)} liste(s)")
    print("\n  ✅ toute fiche close de chaque liste porte son rapport, ou est nommée\n")
    return 0


def juger(racine: Path, projet: str) -> int:

    # Une source absente ROUGIT. Jusqu'au 27/09 : « backlog introuvable — rien
    # mesuré », code 0 — le vert d'un contrôle qui n'a rien lu, le piège que la
    # consigne de l'éclatement nommait.
    try:
        fiches = _fiches.lire(racine, projet)
        prefixe = _fiches.prefixe_de(racine, projet)
    except _fiches.Illisible as exc:
        print(f"\n  ❌ {exc}\n")
        return 1
    closes = fiches_closes(fiches)
    nus = [cle for cle, suite in closes.items() if not a_son_rapport(suite)]
    nommees, fautives = lire_exemptions(config_du_doctor(racine, TEMOIN.lstrip(".")))
    # La liste des exemptions est commune à tous les projets : chacun ne juge
    # que les SIENNES. Sans ce filtre, les exemptions `MY` se diraient périmées
    # dès qu'on tient un autre projet.
    nommees = {c: r for c, r in nommees.items() if c.startswith(f"{prefixe}-")}

    non_nommees = [c for c in nus if c not in nommees]
    perimees = [c for c in nommees if c not in nus]

    print("\nRAPPORTS DE CLÔTURE\n")
    print(f"  fiches closes         {len(closes)}")
    print(f"  avec rapport          {len(closes) - len(nus)}")
    print(f"  sans rapport          {len(nus)}   (nommées : {len(nus) - len(non_nommees)})")

    rouge = False
    if fautives:
        rouge = True
        print()
        for ligne in fautives[:8]:
            print(f"  ❌ ligne illisible dans {TEMOIN} : {ligne[:60]}")
        if len(fautives) > 8:
            print(f"     … et {len(fautives) - 8} autre(s)")
        print("     Une exemption s'écrit `<PREFIXE>-x <raison>` — sans raison, elle")
        print("     n'est qu'une porte.")
    if non_nommees:
        rouge = True
        print()
        for cle in non_nommees[-8:]:
            print(f"  ❌ {cle} — close sans rapport")
        if len(non_nommees) > 8:
            print(f"     … et {len(non_nommees) - 8} autre(s)")
        print("\n     Une fiche soldée sans dire ce qu'elle a mesuré oblige à rouvrir")
        print("     le dossier — le temps que la clôture devait faire gagner.")
        print()
        print("     > **Clôture** — mesuré : <avant> → <après> · tenu par : <quoi>")
        print()
        print("     `tenu par : rien` est une réponse valable, et utile : une fiche")
        print("     soldée sans filet se rouvrira sans prévenir.")
    if perimees:
        rouge = True
        print()
        for cle in perimees[:8]:
            print(f"  ❌ {cle} — nommée dans {TEMOIN}, et n'est plus close sans rapport")
        if len(perimees) > 8:
            print(f"     … et {len(perimees) - 8} autre(s)")
        print("     Retirer la ligne : une exemption qui ne sert plus couvrira la")
        print("     prochaine.")

    if rouge:
        print()
        return 1
    print("\n  ✅ toute fiche close porte son rapport, ou est nommée\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
