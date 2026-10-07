#!/usr/bin/env python3
"""La zone projet tient-elle ?

Tranché par l'owner le 29/09 : **le slug est la clé**. Une fiche
`projets/<slug>.md`, son dossier de liste `workspace/backlog/<slug>/`, et —
pour un projet qui a une liste — un `prefixe:` et un `palier:`. Les outils du
backlog lisent ces déclarations (lot 2) ; ce contrôle vérifie qu'elles tiennent
ensemble. Ce qui pourrirait en silence sans lui :

    un dossier de liste sans fiche     personne ne sait à quel projet il appartient
    deux projets, un même préfixe      deux listes qui se lisent l'une l'autre
    une fiche au mauvais préfixe       `DC-3.md` dans le dossier d'un autre projet
    un palier sans liste, ou inconnu   un lancement autonome sur rien (BRAIN-079)
    un dépôt illisible                 des issues sans maison
    un projet archivé, une fiche       une liste qu'on dit gelée, et qui ne l'est pas
      encore ouverte                   (règle 4 du 29/09 : les ouvertes passent ⏸️)
    une fiche sans statut, ou un       un projet dont personne ne sait s'il vit ; une
      fichier qui n'est pas une fiche  annexe à plat, qui se fait passer pour un projet
      à la racine de projets/          (elle vit dans projets/<slug>/)
    une clé `discord:` mal formée      une publication que personne n'a voulue : un
                                       serveur `On:` lu `True`, une valeur `no` lue
                                       `False`, un serveur nommé `scope`, une fiche
                                       d'un autre préfixe ou absente de la liste

**Les dossiers sans fiche d'aujourd'hui ne se devinent pas** : ils se rattachent
un par un, avec l'humain. D'ici là, chacun est NOMMÉ, avec sa raison, dans
`instance/doctor/zone-projet-orphelins` (`<slug> <raison>`). Un dossier non nommé
rougit ; une ligne qui ne sert plus rougit aussi — une exemption périmée
couvrirait le prochain.

    python3 tools/zone_projet.py --brain ~/Dev/Brain

**Il s'éprouve avant de juger** : un brain jetable reçoit chaque défaut ; si un
seul passe inaperçu, le contrôle rougit au lieu de rendre un vert qui ne prouve
rien. Sortie 1 si la zone ne tient pas.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fiches  # noqa: E402 — la déclaration d'un projet s'y lit
from _config_instance import config_du_doctor  # noqa: E402 — instance/doctor/, l'ancien emplacement en repli

EXEMPTIONS = Path("workspace") / ".zone-projet-orphelins"   # l'ancien emplacement, lu en repli
EXEMPTIONS_DIT = "instance/doctor/zone-projet-orphelins"
PREFIXE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
FICHE = re.compile(r"^([A-Z][A-Z0-9]*)-\d+\.md$")
PALIERS = {"a", "b", "c"}
STATUTS = ("planned", "cadrage", "dev", "active", "prod", "pause", "archived")
AUTO_EPREUVE_CAS = 0                    # compté par l'auto-épreuve, pas écrit à la main

# Les formes de `discord:` que le contrôle refuse, et le motif qu'il doit nommer
# pour chacune. YAML 1.1 lit `no` comme `False`, `On:` comme `True` : la forme
# écrite n'est pas la valeur lue.
CAS_DISCORD = {
    "discord : pas une table": ("discord: tout\n", "`discord:` attend une table"),
    "discord : un serveur qui n'est pas du texte (`On:`)": ("discord:\n  On: tout\n",
                                                           "n'est pas du texte"),
    "discord : un serveur nommé scope": ("discord:\n  scope: tout\n", "« scope »"),
    "discord : ni `tout` ni une liste (`no`)": ("discord:\n  Un-serveur: no\n",
                                               "ni `tout` ni une liste"),
    "discord : un identifiant d'un autre préfixe": ("discord:\n  Un-serveur: [BB-1]\n",
                                                   "pas du préfixe AA"),
    "discord : une fiche absente de la liste": ("discord:\n  Un-serveur: [AA-2]\n",
                                               "absente de workspace/backlog/a/"),
}


def _meta(fiche: Path) -> dict:
    texte = fiche.read_text(encoding="utf-8")
    if not texte.startswith("---\n"):
        return {}
    fin = texte.find("\n---", 4)
    if fin < 0:
        return {}
    import yaml
    try:
        return yaml.safe_load(texte[4:fin]) or {}
    except yaml.YAMLError:
        return {}


def exemptions(brain: Path) -> tuple[dict[str, str], list[str]]:
    chemin = config_du_doctor(brain, EXEMPTIONS.name.lstrip("."))
    if not chemin.is_file():
        return {}, []
    nommes, fautives = {}, []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        brut = ligne.strip()
        if not brut or brut.startswith("#"):
            continue
        morceaux = brut.split(None, 1)
        if len(morceaux) == 2:
            nommes[morceaux[0]] = morceaux[1]
        else:
            fautives.append(brut)
    return nommes, fautives


def juger(brain: Path) -> list[str]:
    """Les défauts de la zone, un par ligne. Vide = elle tient."""
    brain = Path(brain)
    # Ni le modèle (`_template.md`), ni le README que le gabarit livre dans le
    # satellite : ce ne sont pas des fiches. Un fork neuf rougissait sur
    # `projets/README.md` — « `type: None` ».
    fiches = {p.stem: _meta(p) for p in sorted((brain / "projets").glob("*.md"))
              if not p.name.startswith("_") and p.name != "README.md"}
    racine = brain / "workspace" / "backlog"
    dossiers = sorted(p.name for p in racine.iterdir()
                      if p.is_dir() and not p.name.startswith("_")) if racine.is_dir() else []
    defauts = []

    # 1. un dossier de liste a sa fiche — ou il est nommé
    nommes, fautives = exemptions(brain)
    for l in fautives:
        defauts.append(f"{EXEMPTIONS_DIT} : « {l} » — sans raison, une exemption n'est qu'une porte")
    for d in dossiers:
        if d not in fiches and d not in nommes:
            defauts.append(f"workspace/backlog/{d}/ n'a pas de fiche projets/{d}.md "
                           f"— la créer, le rattacher, ou le nommer dans {EXEMPTIONS_DIT}")
    for d in nommes:
        if d not in dossiers or d in fiches:
            defauts.append(f"{EXEMPTIONS_DIT} nomme « {d} », qui n'est plus un dossier sans fiche "
                           f"— retirer la ligne")

    # 7. chaque fichier de projets/ est une fiche de projet, avec un statut
    for slug, m in fiches.items():
        if str(m.get("type")) != "projet":
            defauts.append(f"projets/{slug}.md : `type: {m.get('type')}` — une fiche de projet est "
                           f"`type: projet` ; une annexe se range dans projets/<slug>/")
        elif str(m.get("status")) not in STATUTS:
            defauts.append(f"projets/{slug}.md : `status: {m.get('status')}` — attendu "
                           f"{' | '.join(STATUTS)}")

    # 2-3. préfixe et palier
    vus: dict[str, str] = {}
    for slug, m in fiches.items():
        prefixe, palier = m.get("prefixe"), m.get("palier")
        if prefixe is not None:
            prefixe = str(prefixe)
            if not PREFIXE.match(prefixe):
                defauts.append(f"projets/{slug}.md : préfixe « {prefixe} » mal formé "
                               f"(des majuscules, puis chiffres, 6 au plus)")
            elif prefixe in vus:
                defauts.append(f"préfixe « {prefixe} » déclaré deux fois : "
                               f"{vus[prefixe]} et {slug}")
            else:
                vus[prefixe] = slug
        if palier is not None and str(palier) not in PALIERS:
            defauts.append(f"projets/{slug}.md : palier « {palier} » inconnu (a, b ou c)")
        if palier is not None and prefixe is None:
            defauts.append(f"projets/{slug}.md : un palier sans préfixe — pas de liste, "
                           f"rien à faire avancer")
        # 5. les dépôts déclarés se lisent
        for cle in ("repo", "issues", "vitrine"):
            if m.get(cle) is not None and not _fiches._depot(m.get(cle)):
                defauts.append(f"projets/{slug}.md : `{cle}: {m.get(cle)}` ne désigne pas "
                               f"un dépôt (<hôte>/<owner>/<dépôt>)")

    # 4. chaque fichier de fiche porte le préfixe de son projet
    for d in dossiers:
        try:
            attendu = _fiches.prefixe_de(brain, d)
        except _fiches.Illisible:
            attendu = None
        for f in sorted((racine / d).iterdir()):
            m = FICHE.match(f.name)
            if not m:
                continue
            if attendu is None:
                defauts.append(f"workspace/backlog/{d}/{f.name} : une fiche dans un projet "
                               f"qui ne déclare pas de préfixe")
                break
            if m.group(1) != attendu:
                defauts.append(f"workspace/backlog/{d}/{f.name} : préfixe {m.group(1)}, "
                               f"le projet déclare {attendu}")

    # 8. `discord:` — où la liste se publie, par serveur
    for slug, m in fiches.items():
        if "discord" in m:
            defauts += _juger_discord(brain, slug, m)

    # 6. un projet archivé a gelé sa liste : plus aucune fiche ouverte
    for slug, m in fiches.items():
        if str(m.get("status")) != "archived" or m.get("prefixe") is None or slug not in dossiers:
            continue
        try:
            liste = _fiches.lire(brain, slug, str(m["prefixe"]))
        except _fiches.Illisible:
            continue                    # rien à geler, ou déjà dit par une autre règle
        ouvertes = sorted((c for c, f in liste.items() if f.etat == "ouvert"),
                          key=lambda c: int(c.rsplit("-", 1)[1]))
        if ouvertes:
            defauts.append(f"projets/{slug}.md est archivé, et {len(ouvertes)} fiche(s) "
                           f"restent ouvertes ({', '.join(ouvertes[:4])}) — "
                           f"`projet.py archiver {slug}` les met en pause")
    return defauts


def _juger_discord(brain: Path, slug: str, m: dict) -> list[str]:
    """`discord: {<serveur>: tout | [<PREFIXE>-n, …]}`. Pas de clé : non publié.

    Ce que la lecture YAML ferait en silence, et que ce contrôle refuse :

        `On:`, `Yes:` comme nom      lus `True` — deux tels serveurs s'écrasent
        `no`, `off` comme valeur      lus `False` — ni `tout` ni une liste
        un serveur nommé `scope`      sa ligne `  scope: …` détournerait le scope
                                      d'indexation, lu ligne à ligne dans le frontmatter
        une fiche d'un autre préfixe, ou absente de la liste du projet
    """
    ici = f"projets/{slug}.md"
    table = m.get("discord")
    if not isinstance(table, dict):
        return [f"{ici} : `discord: {table}` — `discord:` attend une table "
                f"`{{<serveur>: tout | [<PREFIXE>-n, …]}}` ; sans publication, retirer la clé"]
    defauts = []
    prefixe = str(m["prefixe"]) if m.get("prefixe") is not None else None
    connues = None
    for serveur, valeur in table.items():
        if not isinstance(serveur, str) or not serveur.strip():
            defauts.append(f"{ici} : le serveur « {serveur!r} » de `discord:` n'est pas du texte "
                           f"— YAML lit On, Yes, No… comme booléens : citer le nom (\"On\":)")
            continue
        if serveur.strip() == "scope":
            defauts.append(f"{ici} : un serveur nommé « scope » dans `discord:` — sa ligne "
                           f"`  scope:` se lirait comme le scope d'indexation de la fiche")
            continue
        if valeur == "tout":
            continue
        if not isinstance(valeur, list):
            defauts.append(f"{ici} : `discord:` « {serveur} » vaut {valeur!r} — ni `tout` ni une "
                           f"liste de fiches (YAML lit no, off… comme booléens)")
            continue
        for ident in valeur:
            if not isinstance(ident, str) or not _fiches.CLE.match(ident):
                defauts.append(f"{ici} : `discord:` « {serveur} » nomme {ident!r}, "
                               f"qui n'est pas un identifiant de fiche (<PREFIXE>-n)")
            elif prefixe is None or ident.rsplit("-", 1)[0] != prefixe:
                defauts.append(f"{ici} : `discord:` « {serveur} » nomme {ident}, pas du préfixe "
                               f"{prefixe or '(aucun déclaré)'} du projet")
            else:
                if connues is None:
                    try:
                        connues = set(_fiches.lire(brain, slug, prefixe))
                    except _fiches.Illisible:
                        connues = set()
                if ident not in connues:
                    defauts.append(f"{ici} : `discord:` « {serveur} » nomme {ident}, "
                                   f"absente de workspace/backlog/{slug}/")
    return defauts


def auto_epreuve() -> list[str]:
    """Chaque défaut, dans un brain jetable, doit être vu. Rend ce qui a échappé."""
    cas = {
        "dossier sans fiche": ({}, ["orphelin"], {}, ""),
        "exemption périmée": ({"nomme": "---\ntype: projet\nstatus: dev\nname: nomme\n---\n"}, ["nomme"], {},
                              "nomme une raison\n"),
        "exemption sans raison": ({}, ["x"], {}, "x\n"),
        "préfixe double": ({"a": "---\ntype: projet\nstatus: dev\nprefixe: ZZ\n---\n", "b": "---\ntype: projet\nstatus: dev\nprefixe: ZZ\n---\n"},
                           [], {}, ""),
        "préfixe mal formé": ({"a": "---\ntype: projet\nstatus: dev\nprefixe: zz\n---\n"}, [], {}, ""),
        "palier inconnu": ({"a": "---\ntype: projet\nstatus: dev\nprefixe: AA\npalier: d\n---\n"}, [], {}, ""),
        "palier sans préfixe": ({"a": "---\ntype: projet\nstatus: dev\npalier: a\n---\n"}, [], {}, ""),
        "dépôt illisible": ({"a": "---\ntype: projet\nstatus: dev\nrepo: nulle-part\n---\n"}, [], {}, ""),
        "fiche au mauvais préfixe": ({"a": "---\ntype: projet\nstatus: dev\nprefixe: AA\n---\n"}, ["a"],
                                     {"a": ["BB-1.md"]}, ""),
        "fiche sans préfixe de projet": ({"a": "---\ntype: projet\nstatus: dev\nname: a\n---\n"}, ["a"],
                                         {"a": ["AA-1.md"]}, ""),
        "fiche sans statut": ({"a": "---\ntype: projet\n---\n"}, [], {}, ""),
        "annexe à plat dans projets/": ({"a": "---\ntype: reference\nstatus: dev\n---\n"}, [], {}, ""),
        "projet archivé, fiche ouverte": ({"a": "---\ntype: projet\nstatus: dev\nstatus: archived\nprefixe: AA\n---\n"},
                                          ["a"], {"a": ["AA-1.md"]}, ""),
    }
    # La clé `discord:` — chaque refus vu PAR SON MOTIF, pas par un autre défaut
    # qui rougirait à sa place. Une liste `AA` avec sa fiche `AA-1`, saine hors la clé.
    for nom, (cle, motif) in CAS_DISCORD.items():
        cas[nom] = ({"a": "---\ntype: projet\nstatus: dev\nprefixe: AA\n" + cle + "---\n"},
                    ["a"], {"a": ["AA-1.md"]}, "", motif)
    global AUTO_EPREUVE_CAS
    AUTO_EPREUVE_CAS = len(cas)
    rates = []
    for nom, (projets, dossiers, fiches, exempt, *motif) in cas.items():
        with tempfile.TemporaryDirectory(prefix="zone-projet-") as tmp:
            b = Path(tmp)
            (b / "projets").mkdir()
            (b / "workspace" / "backlog").mkdir(parents=True)
            for slug, contenu in projets.items():
                (b / "projets" / f"{slug}.md").write_text(contenu, encoding="utf-8")
            for d in dossiers:
                (b / "workspace" / "backlog" / d).mkdir()
            for d, noms in fiches.items():
                for n in noms:
                    (b / "workspace" / "backlog" / d / n).write_text(
                        f"### [{n[:-3]}] Une fiche\n", encoding="utf-8")
            if exempt:
                (b / EXEMPTIONS).write_text(exempt, encoding="utf-8")
            vus = juger(b)
            if not vus or (motif and not any(motif[0] in v for v in vus)):
                rates.append(nom)
    # le témoin négatif : une zone saine ne rougit pas
    with tempfile.TemporaryDirectory(prefix="zone-projet-") as tmp:
        b = Path(tmp)
        (b / "projets").mkdir()
        (b / "workspace" / "backlog" / "sain").mkdir(parents=True)
        (b / "projets" / "sain.md").write_text(
            "---\ntype: projet\nstatus: dev\nprefixe: SA\npalier: a\nrepo: forge.example/o/sain\n---\n", encoding="utf-8")
        (b / "workspace" / "backlog" / "sain" / "SA-1.md").write_text("### [SA-1] Une fiche\n",
                                                                      encoding="utf-8")
        # la clé `discord:` bien formée : un serveur publie tout, un autre une fiche
        (b / "projets" / "sain.md").write_text(
            (b / "projets" / "sain.md").read_text(encoding="utf-8").replace(
                "\n---\n", "\ndiscord:\n  Un-serveur: tout\n  Autre serveur: [SA-1]\n---\n", 1),
            encoding="utf-8")
        # un projet archivé dont la liste est gelée : une fiche close, une en pause
        (b / "workspace" / "backlog" / "fini").mkdir()
        (b / "projets" / "fini.md").write_text("---\ntype: projet\nstatus: dev\nstatus: archived\nprefixe: FI\n---\n",
                                               encoding="utf-8")
        (b / "workspace" / "backlog" / "fini" / "FI-1.md").write_text(
            "### [FI-1] Close — ✅ livré le 1/10\n", encoding="utf-8")
        (b / "workspace" / "backlog" / "fini" / "FI-2.md").write_text(
            "### [FI-2] Ouverte\n\n### [FI-2] Ouverte — ⏸️ projet archivé le 2/10\n",
            encoding="utf-8")
        if juger(b):
            rates.append("témoin négatif : une zone saine rougit")
        # `_fiches.projet` rend la table déclarée, et `{}` sans la clé
        try:
            lus = (_fiches.projet(b, "sain").discord, _fiches.projet(b, "fini").discord)
        except AttributeError:
            lus = None
        if lus != ({"Un-serveur": "tout", "Autre serveur": ["SA-1"]}, {}):
            rates.append(f"_fiches.projet ne rend pas la clé `discord:` déclarée (lu : {lus!r})")
        # … et un `Projet` reste hachable : la table est hors du hash
        try:
            hash(_fiches.projet(b, "sain"))
        except TypeError as e:
            rates.append(f"_fiches.Projet n'est plus hachable avec sa clé `discord:` ({e})")
    return rates


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    brain = p.parse_args().brain.expanduser().resolve()

    rates = auto_epreuve()
    n_cas = AUTO_EPREUVE_CAS
    if rates:
        print("\nLA ZONE PROJET — l'auto-épreuve a échoué, rien n'est jugé :")
        for r in rates:
            print(f"  ❌ non vu : {r}")
        return 1
    if not (brain / "projets").is_dir():
        print(f"SKIP pas de `projets/` dans {brain} — pas de zone projet à juger")
        return 0

    defauts = juger(brain)
    nommes, _ = exemptions(brain)
    print("\nLA ZONE PROJET\n")
    print(f"  auto-épreuve         {n_cas} défauts vus, une zone saine ne rougit pas")
    print(f"  dossiers nommés      {len(nommes)} sans fiche, chacun avec sa raison")
    if not defauts:
        print("\n  ✅ fiches, dossiers, préfixes, paliers et dépôts tiennent ensemble")
        return 0
    for d in defauts[:12]:
        print(f"  ❌ {d}")
    if len(defauts) > 12:
        print(f"     … et {len(defauts) - 12} autre(s)")
    print("\nVERDICT: la zone projet ne tient pas")
    return 1


if __name__ == "__main__":
    sys.exit(main())
