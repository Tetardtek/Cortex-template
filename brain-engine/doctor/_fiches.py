"""Une fiche du backlog, lue une seule fois pour tous

Jusqu'au 27/09, trois outils lisaient `workspace/backlog/myeline/backlog.md`, et
chacun avec SA définition de « une fiche » — donc son angle mort :

    cloture_backlog.py        la puce `- ✅ ~~**` seulement : 26 fiches closes invisibles
    backlog_issues.py         une puce à UN emoji d'une liste fixe : aveugle aux titres
                              `###` — « 105 entrées » sur 166
    eclatement_sans_perte.py  `####` pris pour une fiche ; `🔒 ✅` manqué ; et les récits,
                              53 % du fichier, vérifiés par rien

Ce module est la seule définition. Les trois l'importent ; une forme nouvelle
s'apprend ici, une fois, et les trois la voient.

── Ce qu'est une ENTRÉE ────────────────────────────────────────────────────

Une ligne qui ouvre une fiche, ou la reprend plus bas :

    ## / ### [MY-x] …                    un titre
    - [0 à 2 emoji] [~~]**[MY-x] …        une puce de premier niveau

Une fiche peut avoir plusieurs entrées : une suite l'instruit ou la clôt plus
bas. Son ÉTAT se lit dans sa DERNIÈRE entrée ; son
titre, dans la plus longue ; son texte, c'est toutes ses entrées.

── Où finit une entrée ─────────────────────────────────────────────────────

À l'entrée suivante, ou au prochain titre `#` / `##`. Une puce finit aussi à la
prochaine puce de premier niveau : mesuré le 27/09, un seul cas, et c'était un
récit (« Corrigé au passage, sans item », après une fiche close). Un titre
`###` ne finit PAS une fiche : certaines portent leurs sous-sections en `###`.

── États et qualificatifs — la leçon du 10/09 (backlog_issues.py) ─────────

    ✅, ou le titre barré (`~~**`)    livré — `- ~~**[AB-3] …**~~ ✅` a la coche APRÈS
    ⏸️                               en pause
    🔒, 🔴                            des QUALIFICATIFS : la fiche reste ouverte

Une marque qui attire l'œil de l'humain aveugle la machine quand elle se glisse
là où le motif attendait le début de la ligne : cinq fiches ont été
invisibles un temps pour cette seule raison.

── Les blocs de code ne sont pas du texte — corrigé le 27/09 ───────────────

Une ligne `#   pre-commit → …` dans un bloc ```` ``` ```` est un commentaire de
shell, pas un titre de section. Le lecteur la prenait pour un `#` et coupait la
fiche : l'une coupée à 42 lignes sur 124, une autre à 13 sur 186, une
troisième à 6 sur 76 — 325 lignes de fiches comptées comme récit, et une issue
tronquée. Trouvé parce qu'un ajout à une fiche n'arrivait pas dans son issue. À l'intérieur d'un
bloc de code, rien n'ouvre ni ne ferme une fiche.

── Les sources, et l'absence ───────────────────────────────────────────────

Le monolithe `<projet>/backlog.md` ET les fiches éclatées `<projet>/AB-9.md`
(nommage tranché le 27/09). `AB-9-amont.md` est une ANNEXE, pas une fiche. Une
fiche présente dans deux sources est illisible : deux vérités, aucune.

**Aucune source → `Illisible`, jamais une liste vide.** Un outil qui lit un
fichier disparu mesure zéro et passe au vert : c'est le piège qu'une consigne
du backlog nommait, et `cloture_backlog.py` y tombait (« rien mesuré »,
code 0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

def motif_entree(prefixe: str) -> re.Pattern:
    """L'entrée d'une fiche `<PREFIXE>-<n>` — la même forme pour tout projet."""
    return re.compile(r"^(?:(#{2,3}) |- (?:[^\w\s*~\[]{1,3} ){0,2}(?:~~)?\*\*)\[("
                      + re.escape(prefixe) + r"-\d+)\]")


def motif_fiche_eclatee(prefixe: str) -> re.Pattern:
    return re.compile(r"^" + re.escape(prefixe) + r"-\d+\.md$")


# Le backlog d'origine — `MY`, celui de Myéline. Gardés tels quels pour les
# lecteurs qui ne passent pas de projet.
ENTREE = motif_entree("MY")
SECTION = re.compile(r"^#{1,2} ")
PUCE = re.compile(r"^- ")
FICHE_ECLATEE = motif_fiche_eclatee("MY")
# Un identifiant de fiche, quel que soit le projet : `AB-12`, `DC-90`, `SO-7`.
CLE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
BARRE = re.compile(r"^- (?:\S+ ){0,2}~~\*\*")
QUALIFICATIFS = ("🔒", "🔴")


class Illisible(Exception):
    """La source manque ou se contredit : rien n'est mesuré, et il faut le dire."""


@dataclass(frozen=True)
class Entree:
    cle: str
    source: str           # chemin relatif au brain
    debut: int            # numéro de la ligne d'entrée, à partir de 1
    lignes: tuple         # l'entrée et son bloc

    @property
    def tete(self) -> str:
        return self.lignes[0]

    @property
    def forme(self) -> str:
        return "titre" if self.tete.startswith("#") else "puce"

    @property
    def etat(self) -> str | None:
        """`livré`, `pause`, ou None si l'entrée n'en déclare aucun."""
        if "✅" in self.tete or BARRE.match(self.tete):
            return "livré"
        if "⏸" in self.tete:
            return "pause"
        return None

    @property
    def qualificatifs(self) -> tuple:
        return tuple(q for q in QUALIFICATIFS if q in self.tete)

    @property
    def titre(self) -> str:
        if self.forme == "titre":
            brut = self.tete.split("]", 1)[1]
        else:
            m = re.search(r"\*\*\[[A-Z][A-Z0-9]*-\d+\]\s*(.+?)\*\*", "\n".join(self.lignes), re.S)
            brut = m.group(1) if m else self.tete.split("]", 1)[1]
        return " ".join(brut.replace("~~", "").split()).strip(" —").rstrip(".")

    @property
    def texte(self) -> str:
        return "\n".join(self.lignes).rstrip()


@dataclass
class Fiche:
    cle: str
    entrees: list = field(default_factory=list)

    @property
    def declarante(self) -> Entree:
        """La DERNIÈRE entrée, qu'elle déclare un état ou non.

        Pas « la dernière qui en déclare un » : essayé le 27/09, le témoin l'a
        refusé. Une suite sans marque après une entrée close se lit alors close —
        et c'est exactement ainsi qu'une fiche ouverte se cachait derrière le
        numéro d'une fiche soldée. Une suite non marquée rouvre ; si elle ne le
        devait pas, qu'elle porte sa marque.
        """
        return self.entrees[-1]

    @property
    def etat(self) -> str:
        return self.declarante.etat or "ouvert"

    @property
    def principale(self) -> Entree:
        """L'entrée qui porte le contenu : la plus longue (un renvoi est court)."""
        return max(self.entrees, key=lambda e: len(e.texte))

    @property
    def texte(self) -> str:
        """Toute la fiche, ses entrées dans l'ordre : une suite de 114 lignes
        n'est pas moins la fiche que sa puce d'origine, de 35."""
        return "\n\n---\n\n".join(e.texte for e in self.entrees)

    @property
    def qualificatifs(self) -> tuple:
        vus = []
        for e in self.entrees:
            vus += [q for q in e.qualificatifs if q not in vus]
        return tuple(vus)

    @property
    def sources(self) -> set:
        return {e.source for e in self.entrees}


def entrees(texte: str, source: str = "",
            prefixe: str = "MY") -> tuple[list[Entree], list[tuple[int, list[str]]]]:
    """(les entrées, les RÉCITS) d'un texte. Un récit est ce qu'aucune entrée ne
    couvre : les sections « Émergé le … », les tableaux, les changelogs. Il est
    rendu pour que l'éclatement le vérifie aussi."""
    lignes = texte.split("\n")
    code, dans = [], False
    for l in lignes:
        borne = l.lstrip().startswith("```")
        code.append(dans or borne)
        if borne:
            dans = not dans
    motif = ENTREE if prefixe == "MY" else motif_entree(prefixe)
    debuts = [i for i, l in enumerate(lignes) if not code[i] and motif.match(l)]
    trouvees, couvert = [], [False] * len(lignes)
    for k, i in enumerate(debuts):
        fin = debuts[k + 1] if k + 1 < len(debuts) else len(lignes)
        puce = not lignes[i].startswith("#")
        for j in range(i + 1, fin):
            if code[j]:
                continue
            if SECTION.match(lignes[j]) or (puce and PUCE.match(lignes[j])):
                fin = j
                break
        cle = motif.match(lignes[i]).group(2)
        trouvees.append(Entree(cle, source, i + 1, tuple(lignes[i:fin])))
        for j in range(i, fin):
            couvert[j] = True
    recits, cur = [], None
    for i, l in enumerate(lignes):
        if couvert[i]:
            cur = None
            continue
        if cur is None:
            cur = (i + 1, [])
            recits.append(cur)
        cur[1].append(l)
    return trouvees, recits


@dataclass(frozen=True)
class Projet:
    """Ce que la fiche `projets/<slug>.md` déclare pour sa liste —.

    Le slug est la clé (tranché le 29/09) : la fiche, le dossier
    `workspace/backlog/<slug>/`, le préfixe et le dépôt des issues se retrouvent
    par lui."""
    slug: str
    prefixe: str | None
    issues: str | None      # `owner/depot` — `issues:` s'il est déclaré, sinon `repo:`
    palier: str
    depot: str | None = None  # `owner/depot` du CODE (`repo:`) — où vit `dev/autonome`
    statut: str | None = None  # `status:` — `archived` gèle la liste (règle 4, 29/09)


def _depot(valeur) -> str | None:
    """`forge.exemple/o/d`, `https://…/o/d(.git)` → `o/d`."""
    if not valeur:
        return None
    morceaux = str(valeur).strip().rstrip("/").removesuffix(".git").split("/")
    return "/".join(morceaux[-2:]) if len(morceaux) >= 2 else None


def alias_forge(brain: Path) -> dict[str, str]:
    """Le nom écrit dans un document → le dossier du dépôt sur la forge.

    `monapi#44` dans une fiche, `Mon-API/` sur le disque : la casse et les
    tirets ne se devinent pas toujours, et un alias comme `jeu` → `mon-jeu`
    encore moins. La table vivait EN DUR dans deux outils, avec
    les projets de l'instance d'origine ; elle vit maintenant dans le brain,
    `projets/_alias-forge.yml` (`nom: Dossier`), et un fork part sans.

    Absent : aucun alias. Illisible : l'erreur remonte — un alias perdu en
    silence fausserait tous les verdicts qui en dépendent.
    """
    f = brain / "projets" / "_alias-forge.yml"
    if not f.is_file():
        return {}
    import yaml
    d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    if not isinstance(d, dict):
        raise ValueError(f"{f} : une table `nom: Dossier` attendue")
    return {str(k).lower(): str(v) for k, v in d.items()}


def projet(brain: Path, slug: str) -> Projet:
    """La déclaration du projet. Sans fiche, ou sans frontmatter lisible : tout à
    None — c'est à l'appelant de dire ce qu'il en fait, pas à ce module de
    deviner."""
    fiche = Path(brain) / "projets" / f"{slug}.md"
    meta = {}
    if fiche.is_file():
        texte = fiche.read_text(encoding="utf-8")
        if texte.startswith("---\n"):
            fin = texte.find("\n---", 4)
            if fin > 0:
                import yaml
                try:
                    meta = yaml.safe_load(texte[4:fin]) or {}
                except yaml.YAMLError:
                    meta = {}
    prefixe = meta.get("prefixe")
    return Projet(slug=slug,
                  prefixe=str(prefixe) if prefixe else None,
                  issues=_depot(meta.get("issues") or meta.get("repo")),
                  palier=str(meta.get("palier") or "a"),
                  depot=_depot(meta.get("repo")),
                  statut=str(meta["status"]) if meta.get("status") else None)


def projets_a_liste(brain: Path) -> list[str]:
    """Les projets qui ont une liste : ceux dont la fiche déclare `prefixe:`,
    archivés compris. Ni le gabarit (`_template`), ni un projet sans liste.
    Un brain d'avant la zone projet n'en déclare aucun : `myeline` seul.
    La seule définition — `--tous` des trois outils du backlog la lit."""
    brain = Path(brain)
    slugs = [f.stem for f in sorted((brain / "projets").glob("*.md"))
             if not f.name.startswith("_") and projet(brain, f.stem).prefixe]
    return slugs or ["myeline"]


def prefixe_de(brain: Path, slug: str) -> str:
    """Le préfixe des fiches d'un projet, lu dans sa fiche projet.

    Un seul repli, et il est nommé : `myeline` sans fiche projet garde `MY` —
    les brains d'avant la zone projet, et les brains jetables des témoins, qui
    ne portent qu'un dossier de backlog. Tout autre projet sans `prefixe:` est
    `Illisible` : deviner un préfixe, c'est lire les fiches d'un autre."""
    declare = projet(brain, slug).prefixe
    if declare:
        return declare
    if slug == "myeline":
        return "MY"
    raise Illisible(f"le projet « {slug} » ne déclare pas de `prefixe:` dans "
                    f"projets/{slug}.md — ses fiches ne se lisent pas sans lui")


def lire(brain: Path, projet: str = "myeline", prefixe: str | None = None) -> dict[str, Fiche]:
    """Toutes les fiches d'un projet, monolithe et fiches éclatées. `Illisible`
    si aucune source n'existe, ou si une fiche vit dans deux sources. Le préfixe
    vient de la fiche projet quand il n'est pas donné."""
    brain = Path(brain)
    prefixe = prefixe or prefixe_de(brain, projet)
    eclatee = FICHE_ECLATEE if prefixe == "MY" else motif_fiche_eclatee(prefixe)
    dossier = brain / "workspace" / "backlog" / projet
    sources = []
    monolithe = dossier / "backlog.md"
    if monolithe.is_file():
        sources.append(monolithe)
    if dossier.is_dir():
        sources += sorted(p for p in dossier.iterdir() if eclatee.match(p.name))
    if not sources:
        raise Illisible(f"aucun backlog pour « {projet} » : ni {monolithe.relative_to(brain)}, "
                        f"ni fiche {prefixe}-x.md — rien n'est mesuré, ce n'est pas « zéro fiche »")
    fiches: dict[str, Fiche] = {}
    for chemin in sources:
        rel = str(chemin.relative_to(brain))
        for e in entrees(chemin.read_text(encoding="utf-8"), rel, prefixe)[0]:
            fiches.setdefault(e.cle, Fiche(e.cle)).entrees.append(e)
    doubles = sorted(c for c, f in fiches.items() if len(f.sources) > 1)
    if doubles:
        raise Illisible(f"{len(doubles)} fiche(s) dans deux sources à la fois "
                        f"({', '.join(doubles[:5])}) — deux vérités, aucune")
    return fiches
