#!/usr/bin/env python3
"""Les fiches du backlog comme issues de la forge — dérivées, jamais sources.

Idée de l'owner le 03/09 : pouvoir lire les chantiers à son rythme, depuis
n'importe où, et répondre dans un fil plutôt qu'en session.

**Le sens est tranché avant la première ligne de code**, parce que c'est le
piège de toute la journée — deux endroits qui décrivent la même chose finissent
par s'éloigner, comme `CATALOG.yml` et le frontmatter, les fiches et la
table `projects`, les agents :

    backlog.md reste la SOURCE. Les issues sont le DÉRIVÉ régénéré.

Et pas l'inverse, pour trois raisons qui ne sont pas des préférences : le
backlog est versionné avec les PR, il est **indexé par le RAG** — le brain peut
se relire — et il porte le raisonnement long. Une issue n'est dans aucun dépôt ;
en faire la source rendrait le brain aveugle à son propre backlog.

**L'asymétrie qui rend ça vivable** : *le corps descend, les commentaires
remontent.* Le corps de l'issue est régénéré et ne s'édite pas ; les
commentaires de l'humain sont l'entrée — ils redescendent dans le backlog et dans
la décision. Chacun écrit là où il est le plus à l'aise, et rien n'a deux
sources.

    python3 tools/backlog_issues.py --brain ~/Dev/Brain --projet <projet>           # inventaire
    python3 tools/backlog_issues.py --brain ~/Dev/Brain --projet <projet> --check   # pour brain doctor
    python3 tools/backlog_issues.py --brain ~/Dev/Brain --projet <projet> --apply   # écrit sur la forge
    python3 tools/backlog_issues.py --brain ~/Dev/Brain --tous --check   # chaque liste

Sans `--projet`, la seule liste du brain ; s'il en a plusieurs, il faut la nommer.

**La forge** se choisit par l'adresse du dépôt (`issues:`, sinon `repo:`, dans la
fiche projet) : GitHub par `gh`, une autre forge déclarée dans `satellites.yml`
(`forges:`) — voir `forge.py`.

**`--tous`** juge chaque projet qui déclare un `prefixe:` — archivés compris :
leurs issues doivent se fermer. Le doctor ne regardait qu'une liste ; mesuré
le 2/10, les quatre autres listes portées avaient 11 écarts que rien ne
disait.

**Rien n'est écrit sans `--apply`.** Et seuls les items **ouverts** deviennent
des issues : publier les cinquante livrés ferait du bruit là où on veut lire.

Ce que cet outil ne fait jamais : toucher à un commentaire, fermer une issue
qu'il n'a pas ouverte, ou lire une issue pour en tirer un fait. Le flux ne
remonte que par la main de l'humain.

**Un projet archivé gèle sa liste** (règle 4, tranchée le 29/09) :
plus aucune issue créée ni réécrite, et ses issues ouvertes se ferment, chacune
avec un commentaire qui renvoie à sa fiche. Une fiche en pause d'un projet
VIVANT garde son issue : la pause n'est pas la mort.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fiches  # noqa: E402 — la seule définition d'une fiche
import forge  # noqa: E402 — la forge, choisie par l'adresse du dépôt

# L'en-tête nomme la SOURCE RÉELLE de la fiche : `backlog.md` tant que le
# backlog est monolithique, `MY-x.md` une fois éclaté. Il disait
# `backlog.md` en dur : vrai jusqu'au 27/09, faux ensuite, sans que rien change.
def _marque(source: str) -> str:
    return f"<!-- dérivé de {source} — ne pas éditer ici -->"


def _entete(source: str) -> str:
    return ("> **Dérivé du backlog, régénéré.** Le corps de cette issue vient de\n"
            f"> `{source}` et sera écrasé à la prochaine\n"
            "> passe. **Les commentaires, eux, remontent** : écris ici, ça redescend\n"
            "> dans le backlog et dans la décision.\n\n---\n\n")
# Le backlog marque un item soldé de deux façons, et il fallait le mesurer pour
# le savoir : `- ✅ ~~**[AB-1] …**~~` le plus souvent, mais aussi
# `- ~~**[AB-3] …**~~ ✅` — le titre barré AVANT la coche. Le signal fiable est
# donc le BARRÉ, pas la position de la coche : un titre barré est un item livré.
# Mesuré en publiant une première issue et en la relisant : un item livré le
# 02/09 était parti dans les « ouverts ».
#
# 🔴 **Corrigé le 10/09 au soir — ce motif confondait un ÉTAT et un
# QUALIFICATIF, et il rendait invisibles les cinq items les plus signalés.**
#
#   `🔒` (prérequis homelab) était capté puis classé comme un état non-ouvert :
#        quatre items OUVERTS, jamais dérivés.
#   `🔴` n'était pas dans l'alternative du tout : `- 🔴 **[AB-58] …` ne matchait
#        pas, donc l'item était absent de l'inventaire ENTIER.
#
# L'outil annonçait « 15 ouvertes » là où la passe de vérité du 10/09 en a
# recompté **20** — et l'écart, ce sont exactement ces cinq-là. L'humain lit ses
# chantiers depuis la forge : il n'y aurait jamais vu les prérequis du homelab.
#
# C'est le MÊME défaut que le motif d'inventaire du backlog, corrigé le matin de
# ce jour-là. Une marque qui attire l'œil de l'humain aveugle la machine, parce
# qu'elle s'ajoute là où le motif attendait le début de la ligne.
#
# Depuis : `✅` et le barré disent LIVRÉ, `⏸️` dit EN PAUSE — ce sont des états.
# `🔒` et `🔴` sont des qualificatifs : ils voyagent à côté, dans `marque`, et
# l'item reste OUVERT.
#
# 🔴 **27/09 — la même leçon, une troisième fois** : ce motif ne lisait que les
# PUCES. Les fiches écrites en titre `### [AB-x]` depuis le 11/09 lui
# échappaient toutes — « 105 entrées » sur 166, et cinq fiches sans issue. La
# règle (états ≠ qualificatifs) vit désormais dans `_fiches.py`, la définition
# partagée par les trois lecteurs du backlog.
ETATS = {"livré": "✅", "pause": "⏸️", "ouvert": "ouvert"}


def items(fiches: dict) -> list[dict]:
    """Une ligne par fiche, lue par `_fiches` : l'état dans sa dernière entrée ;
    le titre dans la plus longue — un renvoi est court (mesuré le 10/09 :
    2 lignes contre 28) ; le corps, TOUTES ses entrées."""
    trouves = []
    for cle, f in fiches.items():
        p = f.principale
        trouves.append({
            "numero": cle,
            "etat": ETATS[f.etat],
            "marque": f.qualificatifs[0] if f.qualificatifs else None,
            "titre": p.titre,
            "corps": f.texte,
            "source": f.entrees[0].source,
        })
    return trouves


SENS = {
    "🔒": "🔒 **Prérequis du homelab** — bloquant le jour où le brain quitte le "
          "loopback, pas avant.",
    "🔴": "🔴 **Signalé urgent dans le backlog.**",
}


def plan(tous: list[dict], existantes: dict[str, dict], archive: bool):
    """(à créer, à mettre à jour, à fermer, à jour) — ce que la forge doit devenir.

    Le trou relevé le 1/10 : seule une fiche LIVRÉE fermait son issue. Un projet
    archivé, dont les fiches passent ⏸️, aurait gardé les siennes ouvertes."""
    ouverts = [i for i in tous if i["etat"] == "ouvert"]
    if archive:
        return [], [], [(n, e) for n, e in existantes.items() if e.get("state") == "open"], 0
    a_creer = [i for i in ouverts if i["numero"] not in existantes]
    a_majer, a_jour = [], 0
    for i in ouverts:
        issue = existantes.get(i["numero"])
        if issue is None:
            continue
        if (issue.get("body") or "").strip() != corps_issue(i).strip():
            a_majer.append((i, issue))
        else:
            a_jour += 1
    # Une issue ouverte dont l'item est livré : le dérivé a pris du retard.
    livres = {i["numero"] for i in tous if i["etat"] == "✅"}
    a_fermer = [(n, e) for n, e in existantes.items()
                if n in livres and e.get("state") == "open"]
    return a_creer, a_majer, a_fermer, a_jour


def renvoi_d_archive(projet: str, source: str | None) -> str:
    ou = f"`{source}`" if source else f"`workspace/backlog/{projet}/`"
    return (f"📦 **Projet archivé** — la liste de `{projet}` est gelée : aucune fiche "
            f"nouvelle, les ouvertes passent ⏸️. Cette issue se ferme ; sa fiche reste "
            f"dans {ou}.")


def corps_issue(item: dict) -> str:
    # Le qualificatif est porté dans le corps : sur la forge, le titre seul ne
    # dit pas qu'un item est un prerequis homelab, et c'est justement ce que
    # l'humain vient y lire.
    tete = SENS.get(item.get("marque") or "", "")
    tete = f"{tete}\n\n" if tete else ""
    source = item.get("source", "workspace/backlog/")
    return f"{_entete(source)}{tete}{item['corps']}\n\n{_marque(source)}\n"


PAGES_MAX = 10
PAR_PAGE = 50


def issues_existantes(fg, repo: str, prefixe: str) -> tuple[dict[str, dict], str | None]:
    """Les issues déjà là, indexées par leur clé (`AB-12`). Ouvertes ET fermées.

    Retourne `(index, empechement)`. `empechement` non nul veut dire **« je n ai
    pas pu regarder »** — jamais « il n y a rien ».

    🔴 **Le defaut du 26/09.** La version d avant faisait :

        if code >= 300 or not d:
            break

    Une erreur HTTP et une page vide prenaient la meme sortie, et l index restait
    vide. Avec un jeton en `read:repository` — ou expire, ou un depot renomme —
    l outil concluait donc **« 20 items a creer »** alors que les 20 issues
    existaient sur la forge depuis le 10/09, seize jours plus tot. J ai rapporte
    cette derive a l owner comme reelle ; elle etait un artefact du jeton.

    Un echec de mesure rendu comme une mesure : c est exactement ce que le doctor
    refuse partout ailleurs (« un vert qui ne mesure rien est pire qu un
    rouge »). Ici c etait un ROUGE qui ne mesurait rien, ce qui coute autant —
    on agit sur un chiffre faux.
    """
    par_numero: dict[str, dict] = {}
    page = 1
    while page <= PAGES_MAX:
        # `type=issues` : sans lui, Gitea rend aussi les PULL REQUESTS. Mesuré le
        # 2/10 sur le dépôt du brain : 122 issues, plus de 580 PR — le plafond de
        # 500 était atteint, et ce contrôle s'abstenait sur l'instance.
        code, d = fg.call("GET",
                          f"/repos/{repo}/issues?state=all&type=issues&limit={PAR_PAGE}"
                          f"&page={page}")
        if code >= 300:
            return par_numero, (f"HTTP {code} en lisant la page {page} des "
                                f"issues de {repo}")
        if not d:
            break
        for issue in d:
            m = re.match(r"\[(" + re.escape(prefixe) + r"-\d+)\]", issue.get("title") or "")
            if m:
                par_numero[m.group(1)] = issue
        if len(d) < PAR_PAGE:
            break
        page += 1
    else:
        # La boucle s est epuisee sans rencontrer de page incomplete : il reste
        # probablement des issues non lues. Tronquer en silence reviendrait a
        # inventer des « a creer » — le meme defaut, par un autre chemin.
        # ⚠️ On ne sait PAS s il y en a davantage : la page 11 n a pas ete lue.
        # Dire « plus de 500 issues » serait affirmer ce qu on n a pas mesure —
        # exactement le travers que cette fonction vient de corriger. Avec 500
        # issues pile et rien apres, l abstention est donc un faux negatif
        # assume : mieux vaut s abstenir a tort que conclure a tort.
        return par_numero, (f"{PAGES_MAX * PAR_PAGE} issues lues sur {repo} "
                            f"sans atteindre la fin de la liste — le reste n a "
                            f"pas ete regarde")
    return par_numero, None


# ── Auto-epreuve ───────────────────────────────────────────────────────────

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


class _FausseForge:
    """Rend des reponses HTTP scriptees. Aucun reseau, aucun jeton."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.chemins = []

    def call(self, method, path, payload=None):
        self.chemins.append(path)
        return self.reponses.pop(0) if self.reponses else (200, [])


def _ancienne_lecture(fg, repo: str) -> dict:
    """La lecture d AVANT, reimplementee telle quelle.

    Elle est ici pour que le temoin DISCRIMINE : elle rend le MEME resultat
    pour « HTTP 403 » et pour « aucune issue », et c est tout le defaut.
    """
    par_numero, page = {}, 1
    while page <= 10:
        code, d = fg.call("GET", f"/repos/{repo}/issues?page={page}")
        if code >= 300 or not d:
            break
        for issue in d:
            m = re.match(r"\[(AB-\d+)\]", issue.get("title") or "")
            if m:
                par_numero[m.group(1)] = issue
        if len(d) < 50:
            break
        page += 1
    return par_numero


def _issue(n: int) -> dict:
    return {"title": f"[AB-{n}] titre", "body": "corps", "state": "open",
            "number": n}


def auto_epreuve() -> int:
    """Le premier cas est l incident du 26/09, copie mot pour mot."""
    print("\nAUTO-ÉPREUVE — lire la forge, ou dire qu on n a pas pu\n")

    # ── l incident : jeton en read:repository, 403 sur les issues ─────────
    refus = [(403, {"message": "token does not have at least one of required "
                               "scope(s), required=[write:repository]"})]
    index, emp = issues_existantes(_FausseForge(refus), "o/brain", "AB")
    verifie("l'incident du 26/09 : un 403 est un empêchement, pas une absence",
            (index, emp is not None), ({}, True))
    verifie("témoin négatif : l'ancienne lecture rendait un index VIDE",
            _ancienne_lecture(_FausseForge(refus), "o/brain"), {})

    # ── et une vraie absence, qui doit rester distinguable ────────────────
    index, emp = issues_existantes(_FausseForge([(200, [])]), "r", "AB")
    verifie("une forge réellement vide n'est PAS un empêchement", (index, emp),
            ({}, None))
    verifie("… et l'ancienne lecture ne distinguait pas les deux",
            _ancienne_lecture(_FausseForge([(200, [])]), "r"),
            _ancienne_lecture(_FausseForge(refus), "r"))

    # ── le cas nominal ───────────────────────────────────────────────────
    index, emp = issues_existantes(
        _FausseForge([(200, [_issue(5), _issue(11)])]), "r", "AB")
    verifie("deux issues lues, aucun empêchement",
            (sorted(index), emp), (["AB-11", "AB-5"], None))

    index, emp = issues_existantes(
        _FausseForge([(200, [_issue(i) for i in range(1, 51)]),
                      (200, [_issue(99)])]), "r", "AB")
    verifie("la pagination suit : 50 puis 1", (len(index), emp), (51, None))

    # ── une erreur EN COURS de pagination ────────────────────────────────
    index, emp = issues_existantes(
        _FausseForge([(200, [_issue(i) for i in range(1, 51)]),
                      (502, None)]), "r", "AB")
    verifie("un 502 à la page 2 empêche, malgré 50 issues déjà lues",
            (len(index), emp is not None), (50, True))

    # ── le plafond de pages ──────────────────────────────────────────────
    pleines = [(200, [_issue(i + p * 50) for i in range(1, 51)])
               for p in range(PAGES_MAX)]
    index, emp = issues_existantes(_FausseForge(pleines), "r", "AB")
    verifie("le plafond de pages atteint : l'outil s'abstient",
            (len(index), emp is not None), (PAGES_MAX * PAR_PAGE, True))
    verifie("… et il ne prétend pas savoir combien il en reste",
            "plus de" in (emp or ""), False)
    verifie("… et l'ancienne tronquait là sans rien dire",
            len(_ancienne_lecture(_FausseForge(pleines), "r")),
            PAGES_MAX * PAR_PAGE)

    # Le bord d en face : la derniere page est courte, donc la liste est
    # COMPLETE — meme si on a lu le maximum de pages.
    presque = [(200, [_issue(i + p * 50) for i in range(1, 51)])
               for p in range(PAGES_MAX - 1)] + [(200, [_issue(9999)])]
    index, emp = issues_existantes(_FausseForge(presque), "r", "AB")
    verifie("une derniere page courte : la liste est complète, pas d'abstention",
            (len(index), emp), ((PAGES_MAX - 1) * PAR_PAGE + 1, None))

    # ── les PR ne sont pas des issues — l'abstention du 2/10 ──────────────
    fausse = _FausseForge([(200, [_issue(1)])])
    issues_existantes(fausse, "r", "AB")
    verifie("la lecture ne demande que les issues, pas les PR",
            all("type=issues" in c for c in fausse.chemins), True)

    # ── un titre hors convention ─────────────────────────────────────────
    index, emp = issues_existantes(
        _FausseForge([(200, [{"title": "Handoff du 15/09"}, _issue(7)])]), "r", "AB")
    verifie("un titre sans `[AB-xx]` est ignoré", sorted(index), ["AB-7"])

    # ── un projet archivé gèle sa liste — le trou du 1/10 ────────
    def item(n, etat):
        return {"numero": f"AB-{n}", "etat": etat, "marque": None, "titre": "t",
                "corps": "c", "source": f"AB-{n}.md"}
    tous = [item(1, "ouvert"), item(2, "⏸️"), item(3, "✅"), item(4, "ouvert")]
    existantes = {"AB-1": _issue(1), "AB-2": _issue(2), "AB-3": _issue(3),
                  "AB-9": {**_issue(9), "state": "closed"}}
    creer, majer, fermer, _ = plan(tous, existantes, archive=False)
    verifie("projet vivant : une fiche en pause garde son issue",
            sorted(n for n, _ in fermer), ["AB-3"])
    verifie("projet vivant : une fiche ouverte sans issue se crée",
            [i["numero"] for i in creer], ["AB-4"])
    creer, majer, fermer, _ = plan(tous, existantes, archive=True)
    verifie("projet archivé : rien ne se crée ni ne se réécrit",
            (creer, majer), ([], []))
    verifie("projet archivé : toute issue ouverte se ferme, la fermée reste",
            sorted(n for n, _ in fermer), ["AB-1", "AB-2", "AB-3"])
    verifie("projet archivé : le renvoi nomme la fiche",
            "`AB-2.md`" in renvoi_d_archive("demo", "AB-2.md"), True)

    # ── `--tous` : chaque projet qui a une liste, et lui seulement ─
    import tempfile
    with tempfile.TemporaryDirectory(prefix="listes-") as tmp:
        r = Path(tmp)
        (r / "projets").mkdir()
        verifie("aucune fiche ne déclare de préfixe : `myeline` seul", listes(r), ["myeline"])
        for nom, tete in (("liste", "prefixe: LI"), ("sans-liste", "status: dev"),
                          ("_template", "prefixe: <XX>"), ("archive", "status: archived\nprefixe: AR")):
            (r / "projets" / f"{nom}.md").write_text(f"---\n{tete}\n---\n", encoding="utf-8")
        verifie("chaque projet à préfixe, archivés compris ; ni gabarit ni projet sans liste",
                listes(r), ["archive", "liste"])

    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    return 1 if _ko else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--projet", default=None,
                   help="la liste à tenir — sans lui, la seule du brain")
    # Le dépôt vient de la fiche projet (`issues:`, sinon `repo:`). `--repo` le
    # force, pour éprouver sur un dépôt jetable : `<hôte>/o/d`, ou `o/d` sur la
    # seule forge déclarée.
    p.add_argument("--repo", default=None)
    p.add_argument("--check", action="store_true",
                   help="sortie 1 si le dérivé a pris du retard")
    p.add_argument("--apply", action="store_true",
                   help="écrit sur la forge — sans lui, rien ne bouge")
    p.add_argument("--tous", action="store_true",
                   help="chaque projet qui déclare un `prefixe:`")
    p.add_argument("--limite", type=int, default=0,
                   help="n'en créer que N — pour éprouver le rendu avant de "
                        "publier vingt-trois pages d'un coup")
    args = p.parse_args()

    # L instrument s eprouve AVANT de mesurer. Un outil qui vient de rater son
    # auto-epreuve n a pas a rendre un chiffre sur la forge : c est ce qui s est
    # passe le 26/09, en plus petit — un resultat plausible, pris pour vrai.
    if auto_epreuve():
        print("\nVERDICT: l'auto-épreuve a échoué — rien n'est mesuré")
        return 1

    racine = args.brain.expanduser().resolve()
    if not args.tous:
        rc = un_projet(racine, args)
        return 0 if rc == ABSTENU else rc
    if args.repo:
        print("\n  ❌ `--repo` force UN dépôt : il n'a pas de sens avec `--tous`\n")
        return 1
    slugs = listes(racine)
    codes = {}
    for slug in slugs:
        print(f"\n━━ {slug}")
        codes[slug] = un_projet(racine, argparse.Namespace(**{**vars(args),
                                                              "projet": slug, "repo": None}))
    rouges = [s for s, c in codes.items() if c not in (0, ABSTENU)]
    abstenus = [s for s, c in codes.items() if c == ABSTENU]
    nonmesures = f" ; non mesuré(s) : {', '.join(abstenus)}" if abstenus else ""
    print()
    if rouges:
        print(f"VERDICT: les issues ne disent plus ce que le backlog dit — "
              f"{', '.join(rouges)}{nonmesures}")
        return 1
    if abstenus and len(abstenus) == len(slugs):
        print(f"SKIP aucune liste n'a pu être mesurée ({', '.join(abstenus)})")
        return 0
    print(f"VERDICT: les issues disent ce que le backlog dit — "
          f"{len(slugs) - len(abstenus)} liste(s){nonmesures}")
    print(f"\n  ✅ les issues de chaque liste disent ce que son backlog dit")
    return 0


ABSTENU = 3   # interne : « je n'ai pas pu regarder », jamais rendu tel quel


listes = _fiches.projets_a_liste


def un_projet(racine: Path, args) -> int:
    """Un projet : 0 à jour (ou écrit), 1 écart sous `--check`, ABSTENU."""
    try:
        args.projet = args.projet or _fiches.projet_par_defaut(racine)
        prefixe = _fiches.prefixe_de(racine, args.projet)
        tous = items(_fiches.lire(racine, args.projet, prefixe))
    except _fiches.Illisible as exc:
        print(f"\n  ❌ {exc}\n")
        return 1
    # Un projet sans dépôt déclaré ne devine pas : le dépôt écrit en dur pour la
    # liste d'origine est parti avec le reste de l'instance.
    adresse = args.repo or _fiches.projet(racine, args.projet).adresse_issues
    lue = forge.adresse(adresse)
    args.repo = lue[1] if lue else None
    if not args.repo:
        print(f"\n  ❌ le projet « {args.projet} » ne déclare ni `issues:` ni `repo:` "
              f"— ses issues n'ont pas de maison\n")
        return 1
    ouverts = [i for i in tous if i["etat"] == "ouvert"]
    archive = _fiches.projet(racine, args.projet).statut == "archived"
    print(f"\nBACKLOG → ISSUES — {len(tous)} entrées, {len(ouverts)} ouvertes"
          + (" — projet archivé, liste gelée" if archive else ""))

    # Une forge qui ne se choisit pas (non déclarée, jeton absent) est un ROUGE
    # qui dit quoi déclarer ; une forge qui ne répond pas, une abstention.
    try:
        fg = forge.pour(adresse, racine)
    except forge.ForgeRefus as exc:
        print(f"\n  ❌ {exc}\n")
        print(f"VERDICT: la forge de {adresse} ne se choisit pas — rien n'est mesuré")
        return 1
    try:
        existantes, empechement = issues_existantes(fg, args.repo, prefixe)
    except Exception as exc:                              # noqa: BLE001
        print(f"\n  SKIP forge injoignable : {type(exc).__name__} — {exc}\n")
        return ABSTENU

    # Ne pas pouvoir lire la forge n est pas une derive : c est l absence de
    # mesure. Le doctor l affichera « abstenu », pas « rouge ».
    if empechement is not None:
        print(f"\nSKIP {empechement}")
        print("     Sans la liste des issues, tout item ouvert semblerait "
              "« a creer ».\n")
        return ABSTENU

    a_creer, a_majer, a_fermer, a_jour = plan(tous, existantes, archive)

    print(f"\n  à créer     {len(a_creer)}")
    print(f"  à mettre à jour {len(a_majer)}")
    print(f"  à fermer    {len(a_fermer)}   "
          + ("(projet archivé, issue encore ouverte)" if archive
             else "(item livré, issue encore ouverte)"))
    print(f"  à jour      {a_jour}")

    ecart = len(a_creer) + len(a_majer) + len(a_fermer)
    if not args.apply:
        for i in a_creer[:6]:
            print(f"       créer   [{i['numero']}] {i['titre'][:56]}")
        if len(a_creer) > 6:
            print(f"       …       et {len(a_creer) - 6} autres")
        # Le verdict est DECLARE, pas devine. Sans cette ligne, le
        # doctor resumait ce controle par « Rien n'a ete ecrit. `--apply` pour
        # deriver vraiment » : un mode d emploi la ou il attendait une derive.
        # Cet outil n imprime aucun ❌ et sort pourtant en 1, donc l heuristique
        # du doctor tombait sur sa derniere ligne, quelle qu elle soit.
        if ecart:
            detail = ", ".join(x for x in (
                f"{len(a_creer)} à créer" if a_creer else "",
                f"{len(a_majer)} à mettre à jour" if a_majer else "",
                f"{len(a_fermer)} à fermer" if a_fermer else "") if x)
            print(f"\nVERDICT: les issues ne disent plus ce que le backlog dit — {detail}")
            print("\n     Rien n'a été écrit. `--apply` pour dériver vraiment.\n")
        else:
            print("\nVERDICT: les issues disent ce que le backlog dit — "
                  f"{a_jour} à jour, aucun écart")
            print("\n  ✅ les issues disent ce que le backlog dit\n")
        return 1 if (args.check and ecart) else 0

    for i in (a_creer[:args.limite] if args.limite else a_creer):
        code, d = fg.call("POST", f"/repos/{args.repo}/issues",
                          {"title": f"[{i['numero']}] {i['titre']}",
                           "body": corps_issue(i)})
        print(f"  {'✅' if code < 300 else '❌'} créé   [{i['numero']}] "
              f"#{(d or {}).get('number', '?')}")
    for i, issue in a_majer:
        code, _ = fg.call("PATCH", f"/repos/{args.repo}/issues/{issue['number']}",
                          {"body": corps_issue(i)})
        print(f"  {'✅' if code < 300 else '❌'} maj    [{i['numero']}] "
              f"#{issue['number']}")
    sources = {i["numero"]: i.get("source") for i in tous}
    for numero, issue in a_fermer:
        if archive:
            code, _ = fg.call("POST", f"/repos/{args.repo}/issues/{issue['number']}/comments",
                              {"body": renvoi_d_archive(args.projet, sources.get(numero))})
            if code >= 300:
                print(f"  ❌ renvoi [{numero}] #{issue['number']} — HTTP {code}, "
                      f"l'issue reste ouverte")
                continue
        code, _ = fg.call("PATCH", f"/repos/{args.repo}/issues/{issue['number']}",
                          {"state": "closed"})
        print(f"  {'✅' if code < 300 else '❌'} fermé  [{numero}] #{issue['number']}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
