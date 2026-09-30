#!/usr/bin/env python3
# brain-distribuable: oui
"""La doc du gabarit dit-elle vrai sur le gabarit ?

    docs-verite.py --gabarit <dossier>            juge, 0 vrai · 1 faux · 2 illisible
    docs-verite.py --gabarit <dossier> --brain <brain>
                                                  idem, et reconnaît aussi les agents
                                                  PRIVÉS du brain qui publie

Ce qui pourrirait en silence sans lui : **une doc qui décrit un produit qui
n'existe plus.** Le 27/09, la doc publiée vendait encore quatre paliers
commerciaux supprimés le 02/09 (BRAIN-072), des agents supprimés, une commande
de boot que le moteur ne connaît pas, un `ownership.sh` qui n'a jamais existé
— et la vitrine du gabarit comptait « 19 agents free, 48 pro ». Rien ne le
voyait : une doc n'échoue jamais, elle ment.

── Ce qu'il juge ────────────────────────────────────────────────────────────

Ce que la doc NOMME, contre le gabarit qu'on lui donne — jamais contre le
brain qui l'a écrite : un fichier qui existe chez l'auteur et ne part pas
avec le gabarit est un renvoi mort chez le fork.

    chemin        un fichier d'agents/, de scripts/… existe dans le gabarit
    lien          [texte](page.md) mène à une page qui existe
    boot          `brain boot <type>` : un type dont le manifest existe,
                  sans le `mode` d'avant les sessions V2
    commande      `<script>.sh <sous-commande>` : le script la connaît
    agent         `nom` d'agent : il part avec le gabarit
    retiré        le vocabulaire de ce que le brain a supprimé, avec sa raison
    gabarit       un {{PLACEHOLDER}} ou un ${var} resté tel quel
    version       une version `vN.N.N` écrite en dur qui n'est pas celle du
                  gabarit : juste le jour où on l'écrit, fausse à la suivante,
                  sans erreur (Cortex-Template#7)
    renvoi        (dans agents/, pas la doc) un agent distribué qui renvoie à
                  un agent absent du gabarit le dit conditionnel —
                  « si présent » sur la ligne

Il ne juge pas la prose : une phrase fausse sans nom propre lui échappe. Ce
qui se compte et ce qui se liste doit donc être GÉNÉRÉ depuis le code
(`docs-generer.py`), pas écrit : le jugement ne couvre que ce qui reste nommé.

Une ligne qui doit citer un nom retiré — pour dire qu'il l'est —, ou une
version passée donnée en exemple, le déclare : `<!-- docs-verite: permis -->`
en fin de ligne. Déclaré, jamais deviné.

Une page ENTIÈRE qui raconte — un journal, un changelog, des archives — le
déclare dans son frontmatter : `docs-verite: journal`. Elle cite par nature
des versions passées et des mécanismes retirés ; seuls ses liens et ses
variables restées telles quelles sont jugés.

`--wiki` : les pages sont celles d'un wiki Gitea, qui lie une page SANS
`.md` — `[texte](page)` mène à `page.md` à côté. Sans ce drapeau, un tel lien
est mort : dans un dépôt, il l'est.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── Ce qui est relu ────────────────────────────────────────────────────────

#: Les pages qu'un fork lit. `docs/src/` n'en fait pas partie : ce sont les
#: sources, jugées à travers `docs/` qu'elles produisent.
PAGES = ("README.md", "ARCHITECTURE.md", "BRAIN-INDEX.md", "docs/*.md", "brain-engine/README.md",
         "skills/brain/*.md",
         # Les modèles d'issue : la première chose qu'un inconnu remplit. Le
         # 28/09, `bug_report.md` demandait encore « Tier : [free / pro / full] »,
         # cinq semaines après BRAIN-072 — rien ne le lisait.
         ".github/**/*.md")

#: Les racines d'un chemin que la doc peut nommer.
RACINES = ("agents", "scripts", "contexts", "wiki", "docs", "profil",
           "brain-engine", "brain-ui", "runbooks", "modes", "projets",
           "handoffs", "workspace", "intentions", "infrastructure",
           "skills", "workflows", "todo", "toolkit", "progression", "reviews")

# ── Ce que le brain a supprimé ─────────────────────────────────────────────
#
# Chaque entrée porte sa raison : retirer une chose du brain, c'est ajouter
# une ligne ici. La liste grandit avec les suppressions, pas avec les envies.

RETIRES: tuple[tuple[str, str], ...] = (
    (r"[🟢🔵🟠🟣]\s*\*\*(free|featured|pro|full)\b",
     "badge de palier — les paliers commerciaux sont supprimés (BRAIN-072)"),
    # `(?<![\w-])` : `always-tier` ou `context-tier` (le budget de contexte)
    # ne sont pas des paliers. Et « des tiers » (des tierces parties) n'est
    # jugé que suivi d'un nom de palier.
    (r"(?<![\w-])tier(?![\w-])|\bTierGate\b|\bvue-tiers\b|\b(free|featured|pro|full)\s+tier\b"
     r"|\btiers?\s+(free|featured|pro|full)\b|\bbrain\s+free\b",
     "palier commercial — supprimé par BRAIN-072, le gabarit est distribué tel quel"),
    (r"\bBrain API Key\b|\bfeature[-_ ]gate\b|\bkey-guardian\b|\bfeature_set_schema\b",
     "mécanique des paliers — supprimée par BRAIN-072"),
    (r"\bbrain\.db\b",
     "le brain vit dans Dolt (brain-dolt/) ; SQLite n'est qu'un repli déclaré"),
    # `(?<![\w/-])` : `/bsi/claims/touch` est une ROUTE, pas le dossier.
    (r"(?<![\w/-])claims/",
     "les claims sont une table Dolt, il n'y a plus de dossier claims/"),
)

#: Agents qui ont existé et ne sont plus. Un nom ici n'a pas besoin du brain
#: pour être reconnu comme mort.
AGENTS_RETIRES = ("key-guardian", "feature-gate", "catalogist")

# ── Lecture ────────────────────────────────────────────────────────────────

PERMIS = "<!-- docs-verite: permis -->"
#: Une page qui raconte le déclare dans son frontmatter (voir l'en-tête).
RE_JOURNAL = re.compile(r"(?m)\A---\n(?:.*\n)*?docs-verite:\s*journal\s*\n(?:.*\n)*?---")
#: Une version à trois nombres. Ni collée à un mot ou à un point devant (la fin
#: d'une adresse `127.0.0.1`), ni suivie d'un chiffre (`1.2.3.4`) ; un point
#: final de phrase reste permis (« Kernel v2.3.6. »).
RE_VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+)(?!\.?\d)(?!\w)")
RE_CHEMIN = re.compile(r"(?<![\w./~-])((?:%s)/[\w./-]*[\w/])" % "|".join(RACINES))
# Tout lien relatif — pas seulement vers un `.md`, et même avec un titre
# `(page.md "titre")`. Les URL, les ancres seules et les chemins absolus
# (résolus par la forge, pas par le disque) ne sont pas jugés.
RE_LIEN = re.compile(r"\]\(([^)#\s]+)(?:#[^)\s]*)?(?:\s+\"[^\"]*\")?\)")
RE_BOOT = re.compile(r"\bbrain boot\s+(mode\s+)?([a-z][\w-]*)")
RE_COMMANDE = re.compile(r"([\w-]+\.sh)\s+([a-z][\w-]*)")
RE_BACKTICK = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)*)`")
# Un marqueur resté tel quel, bien ou mal formé (`{{ NB }}`, un bloc
# `genere:` que le générateur n'a pas pris) — jugé hors code : `${HOME}` dans un
# bloc shell est du shell, pas un gabarit oublié.
RE_GABARIT = re.compile(r"\{\{[^}]*\}\}|\$\{[a-zA-Z_]+\}|<!--\s*genere\s*:")


def version_du_gabarit(gabarit: Path) -> str | None:
    """`version:` de brain-compose.yml — None sans elle : la règle se tait."""
    try:
        texte = (gabarit / "brain-compose.yml").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^version:\s*"?([\d.]+)"?\s*$', texte, re.M)
    return m.group(1) if m else None


class Illisible(RuntimeError):
    """Le gabarit ne se laisse pas lire — jamais un « rien à signaler »."""


def pages(gabarit: Path, motifs: tuple[str, ...] = PAGES) -> list[Path]:
    trouvees = []
    for motif in motifs:
        trouvees += sorted(p for p in gabarit.glob(motif) if p.is_file())
    return trouvees


def types_de_session(gabarit: Path) -> set[str]:
    types = {p.stem.removeprefix("session-")
             for p in (gabarit / "contexts").glob("session-*.yml")}
    if not types:
        raise Illisible(f"aucun contexts/session-*.yml dans {gabarit}")
    return types


def agents(dossier: Path) -> set[str]:
    """Les agents d'un dossier — ni `reviews/` ni `archive/`, comme le catalogue :
    sans ça, des noms de revues (`echange`…) devenaient des « agents connus »."""
    racine = dossier / "agents"
    return {p.stem for p in racine.rglob("*.md")
            if not p.name.startswith("_") and p.name != "AGENTS.md"
            and p.relative_to(racine).parts[0] not in ("reviews", "archive")}


def sous_commandes(script: Path) -> str | None:
    """Le texte où chercher les sous-commandes — `None` si le script n'en a pas.

    Un script sans aiguillage sur son premier argument prend des VALEURS
    (`brain-setup.sh mon-brain`) : les juger comme des sous-commandes rougirait
    tout exemple d'appel."""
    texte = script.read_text(encoding="utf-8", errors="replace")
    usage = re.search(r"[Uu]sage\s*:.*?<([a-z][a-z|-]*\|[a-z|-]+)>", texte)
    if usage:
        # Un aiguillage fait AILLEURS qu'en bash (`bsi-claim.sh` aiguille en
        # Python) : la ligne d'usage dit les sous-commandes. Sans elle, le
        # script le plus cité de la doc n'était jamais jugé (relecture du 28/09).
        return "\n".join(f"{c})" for c in usage.group(1).split("|"))
    if not re.search(r'case\s+"?\$\{?(1|CMD|cmd|action|ACTION|commande|arg)\b', texte):
        return None
    return texte


def ecrit_par_un_script(gabarit: Path, chemin: str) -> bool:
    """Un fichier que le gabarit ne porte pas mais qu'un de ses scripts CRÉE
    (`brain-engine/.env.local`) : le nommer n'est pas un renvoi mort. Le chemin
    ENTIER, jamais le nom seul : n'importe quel script cite « README.md », et
    tout `…/README.md` mort serait passé."""
    motif = re.compile(r"(?<![\w/.-])" + re.escape(chemin) + r"(?![\w/.-])")
    for s in (gabarit / "scripts").glob("*"):
        # Le chemin EXACT, borné : `scripts/brain-eng` n'est pas écrit par un
        # script parce que `scripts/brain-engine.sh` y figure.
        # Et dans le CODE seulement : un commentaire qui cite un fichier ne le
        # crée pas. Mesuré le 28/09 — `brain-engine/modules.yml`, retiré d'un
        # gabarit, passait parce qu'un commentaire de `schema-retraits.sh` le
        # nommait.
        if s.is_file() and motif.search(sans_commentaires(
                s.read_text(encoding="utf-8", errors="replace"))):
            return True
    return False


def sans_commentaires(texte: str) -> str:
    """Le texte d'un script sans ses lignes de commentaire (`#` en tête)."""
    return "\n".join(l for l in texte.splitlines() if not l.lstrip().startswith("#"))


def connait(texte_script: str, sous: str) -> bool:
    # Une étiquette de `case` : `start)`, `start|restart)`, `|start)`, `"start")`.
    return re.search(r'(?m)^\s*(?:[\w|"-]*\|)?"?%s"?\s*(?:\|[\w|"-]*)?\)' % re.escape(sous),
                     texte_script) is not None


# ── Juger ──────────────────────────────────────────────────────────────────

#: Un renvoi conditionnel : la ligne dit ce qui se passe si l'agent manque.
RE_CONDITION = re.compile(r"\bsi\s+(?:\S+\s+)?(?:présent|presente?|disponible|absent)", re.IGNORECASE)
#: Une ligne d'historique (`| 2026-03-12 | …`) raconte, elle ne délègue pas.
RE_HISTORIQUE = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\b")


def renvois(gabarit: Path, brain: Path) -> list[tuple[str, int, str, str]]:
    """Les agents distribués qui renvoient, sans condition, à un agent absent.

    Chez un fork, la délégation tombait dans le vide EN SILENCE : `agent-review`
    envoyait tout son signal au `recruiter`, `coach` écrivait via `coach-scribe`
    — deux agents privés. `agents/_conventions.md` pose la règle (un
    agent absent ne se simule pas, il se dit) ; ce jugement tient que chaque
    renvoi vers un absent l'écrive sur sa ligne.

    Absent = un agent du brain qui publie (`--brain`) qui n'est pas dans le
    gabarit. Hors jugement : le frontmatter (`sends_to` est une liste de
    données) et les lignes d'historique. Les blocs de code, eux, comptent :
    dans un agent, c'est le pseudo-code d'une délégation (`→ coach-scribe`)."""
    # `archive/` compte ici : un agent archivé chez l'auteur n'est pas chez le fork.
    def tous(d: Path) -> set[str]:
        r = d / "agents"
        return {p.stem for p in r.rglob("*.md") if not p.name.startswith("_")
                and p.name != "AGENTS.md" and p.relative_to(r).parts[0] != "reviews"}
    absents = tous(brain) - tous(gabarit)
    if not absents:
        return []
    motif = re.compile(r"(?<![\w/-])(%s)(?![\w-])" % "|".join(
        re.escape(a) for a in sorted(absents, key=len, reverse=True)))
    faux = []
    for page in sorted((gabarit / "agents").glob("*.md")):
        rel = str(page.relative_to(gabarit))
        lignes = page.read_text(encoding="utf-8").splitlines()
        entete = bool(lignes) and lignes[0].strip() == "---"
        for n, ligne in enumerate(lignes, 1):
            if entete:
                if n > 1 and ligne.strip() == "---":
                    entete = False
                continue
            if PERMIS in ligne or RE_HISTORIQUE.match(ligne) or RE_CONDITION.search(ligne):
                continue
            for nom in sorted(set(motif.findall(ligne))):
                faux.append((rel, n, "renvoi",
                             f"`{nom}` ne part pas avec le gabarit — renvoi sans « si présent »"))
    return faux


def juger(gabarit: Path, brain: Path | None = None,
          motifs: tuple[str, ...] = PAGES, wiki: bool = False) -> list[tuple[str, int, str, str]]:
    """(page, ligne, règle, message) pour chaque affirmation fausse. Pur sur le disque."""
    if not (gabarit / "agents").is_dir():
        raise Illisible(f"{gabarit} n'a pas de agents/ — ce n'est pas un gabarit")
    types = types_de_session(gabarit)
    publies = agents(gabarit)
    connus = publies | set(AGENTS_RETIRES) | (agents(brain) if brain else set())
    retires = [(re.compile(m, re.IGNORECASE), r) for m, r in RETIRES]
    courante = version_du_gabarit(gabarit)
    faux: list[tuple[str, int, str, str]] = []

    for page in pages(gabarit, motifs):
        rel = str(page.relative_to(gabarit))
        try:
            texte = page.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            raise Illisible(f"{rel} : {e}") from e
        lignes = texte.splitlines()
        journal = RE_JOURNAL.match(texte) is not None
        dans_bloc = False
        for n, ligne in enumerate(lignes, 1):
            if ligne.lstrip().startswith(("```", "~~~")):
                dans_bloc = not dans_bloc
                continue
            if PERMIS in ligne:
                continue
            # Ce qui est écrit EN CODE (bloc ``` ou `span`) est une commande ;
            # le reste est de la prose. `brain boot` et `<script>.sh <mot>` ne
            # se jugent qu'en code : « Tape brain boot puis choisis » n'est pas
            # une commande dont « puis » serait le type (relecture du 28/09).
            # Chaque span de code se juge SEUL : recollés, deux noms voisins
            # faisaient une commande — « `scripts/bsi-claim.sh` | lit
            # `ttl_hours` » devenait `bsi-claim.sh ttl_hours` (wiki, 29/09).
            codes = [ligne] if dans_bloc else re.findall(r"`([^`]*)`", ligne)
            prose = "" if dans_bloc else re.sub(r"`[^`]*`", " ", ligne)

            def dire(regle: str, msg: str) -> None:
                # Un journal raconte : il ne répond que de ses liens et de ses
                # variables restées telles quelles.
                if journal and regle not in ("lien", "gabarit"):
                    return
                faux.append((rel, n, regle, msg))

            for m in RE_CHEMIN.finditer(ligne):
                # Un MOTIF n'est pas un chemin : `contexts/session-*.yml`,
                # `contexts/session-<type>.yml`, `agents/{nom}.md` — la capture
                # s'arrête juste avant `*`, `<` ou `{`.
                suite = ligne[m.end():m.end() + 2]
                if suite[:1] in ("*", "<", "{") or (suite[:1] == "-" and suite[1:2] in ("*", "<", "{")):
                    continue
                chemin = m.group(1).rstrip("/.")
                if not (gabarit / chemin).exists() and not ecrit_par_un_script(gabarit, chemin):
                    dire("chemin", f"`{chemin}` n'existe pas dans le gabarit")

            for m in RE_LIEN.finditer(prose):
                cible = m.group(1)
                if "://" in cible or cible.startswith(("/", "mailto:")):
                    continue
                if (page.parent / cible).exists():
                    continue
                if wiki and not Path(cible).suffix and (page.parent / f"{cible}.md").exists():
                    continue
                dire("lien", f"({cible}) ne mène à aucune page")

            for m in (m for c in codes for m in RE_BOOT.finditer(c)):
                if m.group(1):
                    dire("boot", "`brain boot mode …` : la syntaxe est `brain boot <type>[/<scope>]`")
                if m.group(2) not in types:
                    dire("boot", f"`{m.group(2)}` n'est pas un type de session "
                                 f"({', '.join(sorted(types))})")

            for m in (m for c in codes for m in RE_COMMANDE.finditer(c)):
                script, sous = m.group(1), m.group(2)
                chemin = gabarit / "scripts" / script
                if not chemin.is_file():
                    dire("commande", f"`{script}` n'est pas un script du gabarit")
                elif (texte := sous_commandes(chemin)) is not None and not connait(texte, sous):
                    dire("commande", f"`{script}` ne connaît pas `{sous}`")

            for m in RE_BACKTICK.finditer(ligne):
                nom = m.group(1)
                if nom in connus and nom not in publies:
                    dire("agent", f"`{nom}` ne part pas avec le gabarit")

            for motif, raison in retires:
                if motif.search(ligne):
                    dire("retiré", raison)

            # Une version écrite en dur est juste le jour où on l'écrit : la page
            # « Se mettre à jour » disait `git merge v2.3.4`, fausse dès la
            # v2.3.5 (Cortex-Template#7). Blocs de code COMPRIS — c'est là
            # qu'était l'incident.
            if courante:
                for m in RE_VERSION.finditer(ligne):
                    if m.group(1) != courante:
                        dire("version", f"`{m.group(0)}` écrit en dur — le gabarit est en "
                                        f"{courante} ; un exemple voulu se déclare : {PERMIS}")

            if RE_GABARIT.search(prose):
                dire("gabarit", "variable restée telle quelle")
    # Les agents ne sont pas de la doc — ils ne passent que ce jugement-là, et
    # seulement quand on juge LE gabarit (pas d'autres pages via --pages).
    if brain and motifs == PAGES:
        faux += renvois(gabarit, brain)
    return faux


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gabarit", required=True, type=Path)
    ap.add_argument("--brain", type=Path)
    ap.add_argument("--pages", nargs="+", metavar="MOTIF",
                    help="d'autres pages que celles du gabarit — ex. skills/brain/instance/*.md, "
                         "jugées contre le brain passé en --gabarit")
    ap.add_argument("--wiki", action="store_true",
                    help="les pages sont un wiki Gitea : [texte](page) mène à page.md")
    a = ap.parse_args()
    motifs = tuple(a.pages) if a.pages else PAGES
    try:
        faux = juger(a.gabarit.resolve(), a.brain.resolve() if a.brain else None, motifs,
                     wiki=a.wiki)
    except Illisible as e:
        print(f"docs-verite: illisible — {e}", file=sys.stderr)
        return 2
    except Exception as e:  # 1 veut dire « faux » : un plantage n'est pas un verdict
        print(f"docs-verite: illisible — {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    for page, n, regle, msg in faux:
        print(f"{page}:{n}: [{regle}] {msg}")
    nb_pages = len(pages(a.gabarit, motifs))
    if faux:
        print(f"\n✗ {len(faux)} affirmation(s) fausse(s) sur {nb_pages} pages")
        return 1
    print(f"✓ {nb_pages} pages, rien de faux parmi ce qui est nommé")
    return 0


if __name__ == "__main__":
    sys.exit(main())
