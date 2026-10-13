#!/usr/bin/env python3
"""L'index d'un backlog éclaté — généré, jamais écrit à la main.

Tranché par l'owner le 17/09 : la fiche porte le statut, un script reconstruit
l'index, un contrôle vérifie qu'ils s'accordent. **Un index généré ne périme
pas** — c'est tout ce que `LATEST.md` et `decisions-en-attente.md` n'étaient pas.

Le 27/09, l'index prend la place de `<projet>/backlog.md` (et non
`backlog-<projet>.md`, comme la consigne l'écrivait) : seize fichiers y
renvoient, et un renvoi qui aboutit vaut mieux qu'un renvoi réécrit.

    python3 tools/index_backlog.py --brain ~/Dev/Brain --projet <projet> --check
    python3 tools/index_backlog.py --brain ~/Dev/Brain --projet <projet> --ecrire
    python3 tools/index_backlog.py --brain ~/Dev/Brain --tous --check

Sans `--projet`, la seule liste du brain ; s'il en a plusieurs, il faut la nommer.

Il lit les fiches par `_fiches` — la seule définition — et leur `origine:`
dans leur frontmatter. Il n'écrit rien sans `--ecrire`.

Il part au gabarit avec le doctor (`brain-engine/doctor/`), sans y être un
contrôle : la commande que l'index écrit dans son en-tête est donc
celle de l'outil qui l'a généré, là où il vit — pas un chemin de l'instance
d'origine, faux chez un fork.

Sortie 1 si l'index ne dit plus ce que les fiches disent. **Abstention** (`SKIP`)
tant que le backlog n'est pas éclaté : un monolithe n'a pas d'index à tenir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fiches  # noqa: E402 — la seule définition d'une fiche

ETAT = {"livré": "✅", "pause": "⏸️", "ouvert": "·"}


def entete(texte: str) -> dict:
    """Le frontmatter d'une fiche éclatée — `{}` s'il n'y en a pas."""
    if not texte.startswith("---\n"):
        return {}
    fin = texte.find("\n---\n", 4)
    if fin < 0:
        return {}
    import yaml
    try:
        return yaml.safe_load(texte[4:fin]) or {}
    except yaml.YAMLError:
        return {}


def eclate(brain: Path, projet: str) -> bool:
    """Le backlog est-il éclaté ? Oui dès qu'une fiche `<PREFIXE>-x.md` existe."""
    dossier = Path(brain) / "workspace" / "backlog" / projet
    if not dossier.is_dir():
        return False
    try:
        motif = _fiches.motif_fiche_eclatee(_fiches.prefixe_de(brain, projet))
    except _fiches.Illisible:
        return False
    return any(motif.match(p.name) for p in dossier.iterdir())


def _court(p: Path) -> str:
    """Un chemin sous le HOME s'écrit `~/…` : l'en-tête ne nomme pas la machine."""
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)


def commande_ecrire(brain: Path, projet: str) -> str:
    """La commande qui régénère cet index, depuis l'outil qui tourne.

    Livré dans le brain (`brain-engine/doctor/`), il se lance depuis la racine
    du brain : un chemin relatif, juste chez tout fork. Les chemins se comparent
    résolus, puis tels qu'appelés : installé par le paquet, `brain-engine/` est
    un LIEN du dossier de données vers le programme. Ailleurs (un dépôt
    d'outils à part), les deux chemins, abrégés en `~/`."""
    ici, brain = Path(__file__), Path(brain)
    for outil, racine in ((ici.resolve(), brain.resolve()), (ici.absolute(), brain.absolute())):
        try:
            return f"python3 {outil.relative_to(racine)} --brain . --projet {projet} --ecrire"
        except ValueError:
            continue
    return f"python3 {_court(ici.resolve())} --brain {_court(brain.resolve())} --projet {projet} --ecrire"


ANNONCE = "> Cet index se RÉGÉNÈRE, il ne s'écrit pas :"
GENERE_PAR = "genere_par:"


def sans_commande(texte: str) -> list[str]:
    """Les lignes de l'index, moins la commande d'en-tête (la ligne qui suit
    `ANNONCE`). Elle dit où vit l'outil qui a ÉCRIT l'index : `--check`, lancé
    par une autre copie (un worktree, le dépôt d'outils), rougissait sur ce seul
    chemin alors que les fiches n'avaient pas bougé. `--check` juge ce que disent
    les fiches ; `--ecrire` écrit toujours la ligne."""
    lignes = texte.splitlines()
    if ANNONCE in lignes:
        i = lignes.index(ANNONCE) + 1
        del lignes[i:i + 1]
    # `genere_par:` nomme l'outil, pas les fiches : il disait le dépôt d'origine
    # (`<dépôt>/tools/…`), faux chez un fork. Le neutraliser ne doit pas rougir
    # un index écrit avant — il se compare donc comme la commande.
    return [l for l in lignes if not l.startswith(GENERE_PAR)]


def generer(brain: Path, projet: str) -> str:
    brain = Path(brain)
    fiches = _fiches.lire(brain, projet)
    prefixe = _fiches.prefixe_de(brain, projet)
    lignes = [
        "---",
        # Pas `{projet}-backlog` : c'est le `name` du monolithe d'origine, que
        # `chronique.md` porte tel quel — deux fichiers, un nom.
        f"name: {projet}-backlog-index",
        "type: index",
        f"{GENERE_PAR} index_backlog.py — ne pas éditer à la main",
        "---",
        "",
        # Le nom du projet tel qu'il est écrit dans son dossier : `capitalize()`
        # rendait « Myeline » — l'accent n'est pas dans le nom du dossier.
        f"# Le backlog `{projet}` — index généré",
        "",
        f"> **Une fiche = un fichier** `{prefixe}-x.md`, dans ce dossier : c'est elle la source.",
        ANNONCE,
        f"> `{commande_ecrire(brain, projet)}`.",
        "> L'histoire d'une ligne d'avant l'éclatement : `git blame -C -C <fiche>` —",
        "> elle remonte dans l'ancien `backlog.md`.",
        "",
        "| Fiche | État | Titre | Origine |",
        "|---|---|---|---|",
    ]
    # la chronique n'existe que pour un backlog éclaté d'un monolithe
    # (Myéline) : le lien vers elle, écrit partout, faisait 5 liens morts.
    if (brain / "workspace" / "backlog" / projet / "chronique.md").is_file():
        i = lignes.index(ANNONCE) + 2
        lignes[i:i] = ["> Le texte qui n'est pas une fiche (doctrine, critère d'arrêt, changelog,",
                       "> récits datés) vit dans [`chronique.md`](chronique.md)."]
    def rang(cle: str) -> int:
        return int(cle.split("-")[1])
    for cle in sorted(fiches, key=rang):
        f = fiches[cle]
        source = brain / f.entrees[0].source
        origine = entete(source.read_text(encoding="utf-8")).get("origine", "")
        titre = f.principale.titre.replace("|", "\\|")
        marques = "".join(f.qualificatifs)
        lignes.append(f"| [{cle}]({Path(f.entrees[0].source).name}) | "
                      f"{ETAT[f.etat]}{(' ' + marques) if marques else ''} | "
                      f"{titre} | {str(origine).replace('|', '/')} |")
    ouvertes = sum(1 for f in fiches.values() if f.etat != "livré")
    lignes += ["", f"{len(fiches)} fiches · {ouvertes} non livrées.", ""]
    return "\n".join(lignes)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--projet", default=None,
                   help="la liste à tenir — sans lui, la seule du brain")
    p.add_argument("--check", action="store_true")
    p.add_argument("--ecrire", action="store_true")
    p.add_argument("--tous", action="store_true",
                   help="chaque projet qui déclare un `prefixe:`")
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()
    if not a.tous:
        try:
            projet = a.projet or _fiches.projet_par_defaut(brain)
        except _fiches.Illisible as exc:
            print(f"\n  ❌ {exc}\n")
            return 1
        rc = tenir(brain, projet, a.ecrire)
        return 0 if rc == MONOLITHE else rc
    codes = {}
    for slug in _fiches.projets_a_liste(brain):
        print(f"\n━━ {slug}")
        codes[slug] = tenir(brain, slug, a.ecrire)
    rouges = [s for s, c in codes.items() if c not in (0, MONOLITHE)]
    monolithes = [s for s, c in codes.items() if c == MONOLITHE]
    aussi = f" ; sans index (monolithe) : {', '.join(monolithes)}" if monolithes else ""
    print()
    if rouges:
        print(f"VERDICT: l'index ne dit plus ce que les fiches disent — {', '.join(rouges)}{aussi}")
        return 1
    if len(monolithes) == len(codes):
        print(f"SKIP aucune liste n'est éclatée ({', '.join(monolithes)})")
        return 0
    print(f"VERDICT: l'index dit ce que les fiches disent — "
          f"{len(codes) - len(monolithes)} liste(s){aussi}")
    return 0


MONOLITHE = 3   # interne : pas d'index à tenir, jamais rendu tel quel


def tenir(brain: Path, projet: str, ecrire: bool) -> int:
    if not eclate(brain, projet):
        print(f"SKIP {projet} n'est pas éclaté — un monolithe n'a pas d'index à tenir")
        return MONOLITHE
    try:
        attendu = generer(brain, projet)
    except _fiches.Illisible as exc:
        print(f"\n  ❌ {exc}\n")
        return 1
    index = brain / "workspace" / "backlog" / projet / "backlog.md"
    if ecrire:
        index.write_text(attendu, encoding="utf-8")
        print(f"  ✅ index écrit : {index.relative_to(brain)}")
        return 0
    actuel = index.read_text(encoding="utf-8") if index.is_file() else ""
    a_l, e_l = sans_commande(actuel), sans_commande(attendu)
    if a_l == e_l:
        print("VERDICT: l'index dit ce que les fiches disent")
        return 0
    ecarts = [l for l in e_l if l not in a_l][:5]
    print("VERDICT: l'index ne dit plus ce que les fiches disent — à régénérer")
    for l in ecarts:
        print(f"  ❌ attendu : {l[:100]}")
    print(f"\n     --ecrire pour le régénérer. Un index écrit à la main se périme.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
