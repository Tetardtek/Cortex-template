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

**Les dossiers sans fiche d'aujourd'hui ne se devinent pas** : ils se rattachent
un par un, avec l'humain. D'ici là, chacun est NOMMÉ, avec sa raison, dans
`workspace/.zone-projet-orphelins` (`<slug> <raison>`). Un dossier non nommé
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

EXEMPTIONS = Path("workspace") / ".zone-projet-orphelins"
PREFIXE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
FICHE = re.compile(r"^([A-Z][A-Z0-9]*)-\d+\.md$")
PALIERS = {"a", "b", "c"}
AUTO_EPREUVE_CAS = 0                    # compté par l'auto-épreuve, pas écrit à la main


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
    chemin = brain / EXEMPTIONS
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
    fiches = {p.stem: _meta(p) for p in sorted((brain / "projets").glob("*.md"))
              if not p.name.startswith("_")}
    racine = brain / "workspace" / "backlog"
    dossiers = sorted(p.name for p in racine.iterdir()
                      if p.is_dir() and not p.name.startswith("_")) if racine.is_dir() else []
    defauts = []

    # 1. un dossier de liste a sa fiche — ou il est nommé
    nommes, fautives = exemptions(brain)
    for l in fautives:
        defauts.append(f"{EXEMPTIONS} : « {l} » — sans raison, une exemption n'est qu'une porte")
    for d in dossiers:
        if d not in fiches and d not in nommes:
            defauts.append(f"workspace/backlog/{d}/ n'a pas de fiche projets/{d}.md "
                           f"— la créer, le rattacher, ou le nommer dans {EXEMPTIONS}")
    for d in nommes:
        if d not in dossiers or d in fiches:
            defauts.append(f"{EXEMPTIONS} nomme « {d} », qui n'est plus un dossier sans fiche "
                           f"— retirer la ligne")

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


def auto_epreuve() -> list[str]:
    """Chaque défaut, dans un brain jetable, doit être vu. Rend ce qui a échappé."""
    cas = {
        "dossier sans fiche": ({}, ["orphelin"], {}, ""),
        "exemption périmée": ({"nomme": "---\nname: nomme\n---\n"}, ["nomme"], {},
                              "nomme une raison\n"),
        "exemption sans raison": ({}, ["x"], {}, "x\n"),
        "préfixe double": ({"a": "---\nprefixe: ZZ\n---\n", "b": "---\nprefixe: ZZ\n---\n"},
                           [], {}, ""),
        "préfixe mal formé": ({"a": "---\nprefixe: zz\n---\n"}, [], {}, ""),
        "palier inconnu": ({"a": "---\nprefixe: AA\npalier: d\n---\n"}, [], {}, ""),
        "palier sans préfixe": ({"a": "---\npalier: a\n---\n"}, [], {}, ""),
        "dépôt illisible": ({"a": "---\nrepo: nulle-part\n---\n"}, [], {}, ""),
        "fiche au mauvais préfixe": ({"a": "---\nprefixe: AA\n---\n"}, ["a"],
                                     {"a": ["BB-1.md"]}, ""),
        "fiche sans préfixe de projet": ({"a": "---\nname: a\n---\n"}, ["a"],
                                         {"a": ["AA-1.md"]}, ""),
        "projet archivé, fiche ouverte": ({"a": "---\nstatus: archived\nprefixe: AA\n---\n"},
                                          ["a"], {"a": ["AA-1.md"]}, ""),
    }
    global AUTO_EPREUVE_CAS
    AUTO_EPREUVE_CAS = len(cas)
    rates = []
    for nom, (projets, dossiers, fiches, exempt) in cas.items():
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
            if not juger(b):
                rates.append(nom)
    # le témoin négatif : une zone saine ne rougit pas
    with tempfile.TemporaryDirectory(prefix="zone-projet-") as tmp:
        b = Path(tmp)
        (b / "projets").mkdir()
        (b / "workspace" / "backlog" / "sain").mkdir(parents=True)
        (b / "projets" / "sain.md").write_text(
            "---\nprefixe: SA\npalier: a\nrepo: forge.example/o/sain\n---\n", encoding="utf-8")
        (b / "workspace" / "backlog" / "sain" / "SA-1.md").write_text("x\n", encoding="utf-8")
        # un projet archivé dont la liste est gelée : une fiche close, une en pause
        (b / "workspace" / "backlog" / "fini").mkdir()
        (b / "projets" / "fini.md").write_text("---\nstatus: archived\nprefixe: FI\n---\n",
                                               encoding="utf-8")
        (b / "workspace" / "backlog" / "fini" / "FI-1.md").write_text(
            "### [FI-1] Close — ✅ livré le 1/10\n", encoding="utf-8")
        (b / "workspace" / "backlog" / "fini" / "FI-2.md").write_text(
            "### [FI-2] Ouverte\n\n### [FI-2] Ouverte — ⏸️ projet archivé le 2/10\n",
            encoding="utf-8")
        if juger(b):
            rates.append("témoin négatif : une zone saine rougit")
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
