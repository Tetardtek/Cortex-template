#!/usr/bin/env python3
"""Deux fiches parlent-elles du même projet ? — §5.

Ce qui pourrirait en silence sans lui : **un projet écrit à deux endroits**, une
fiche copiée puis renommée, une faute de frappe devenue une seconde fiche. Les
deux vivent leur vie, et la moitié des décisions finit dans la mauvaise.

Né dans le générateur du menu d'une instance, le 25/09, qui le portait sans
qu'aucun contrôle ne le sache : il mesure le BRAIN, pas le menu. Ses critères et
son seuil sont repris tels quels — calibrés sur 57 projets, zéro fausse alerte
sur l'existant, cinq alertes justes sur des faux injectés.

    python3 tools/doublons_de_projets.py --brain ~/Dev/Brain

── Ce qu'il juge (projets/*.md, et les tracks de learning/ s'il existe) ────

    deux fiches déclarent le même repo / repo_public / url_prod    ROUGE
    deux noms ne diffèrent que par la ponctuation                   ROUGE
    l'en-tête dit `name:` autre que le nom du fichier               ROUGE
    deux noms se ressemblent à 0,85 ou plus                         ⚠️  (une faute ?)

── Le seuil, et pourquoi pas plus bas ──────────────────────────────────────

Entre 0,6 et 0,85 de ressemblance, c'est une FAMILLE, pas un doublon : à la
calibration, les familles réelles plafonnaient à 0,75 (`outil-web`/`outil-cli`
mesurent 0,67, `mon-projet-api`/`mon-projet-web` 0,79). Un seuil naïf hurlerait
sur chaque famille ; 0,85 attrape la faute de frappe (`projet`/`projett`, 0,92)
et laisse les familles tranquilles. Le vrai signal est
ailleurs : deux fiches qui déclarent le même dépôt parlent du même projet,
quel que soit leur nom.

Une fiche sans `status:` n'est pas jugée ici : c'est `statuts_conformes`.

── Il n'écrit rien ─────────────────────────────────────────────────────────

Il avertit, il ne fusionne ni ne renomme : décider lequel des deux est le vrai
demande de lire les deux.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

SEUIL = 0.85
CHAMPS_ADRESSE = ("repo", "repo_public", "url_prod")

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def entete(chemin: Path, yaml) -> dict:
    """Le frontmatter d'une fiche, ou {} s'il n'y en a pas, ou s'il est illisible."""
    try:
        texte = chemin.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not texte.startswith("---"):
        return {}
    fin = texte.find("\n---", 3)
    if fin < 0:
        return {}
    try:
        lu = yaml.safe_load(texte[3:fin])
    except yaml.YAMLError:
        return {}
    return lu if isinstance(lu, dict) else {}


def sans_separateurs(nom: str) -> str:
    return re.sub(r"[^a-z0-9]", "", nom.lower())


def adresse(valeur) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", str(valeur).strip().lower()).rstrip("/").removesuffix(".git")


def doublons(fiches: dict[str, dict], quoi: str) -> tuple[list[str], list[str]]:
    """(rouges, avertissements). Pur : `fiches` = {nom: en-tête}. Les modèles
    (`_…`) sont ignorés."""
    fiches = {n: fm for n, fm in fiches.items() if not n.startswith("_")}
    rouges, avertissements = [], []
    for champ in CHAMPS_ADRESSE:
        vus: dict[str, list[str]] = {}
        for nom, fm in sorted(fiches.items()):
            if fm.get(champ):
                vus.setdefault(adresse(fm[champ]), []).append(nom)
        rouges += [f"{quoi}s {' et '.join(noms)} déclarent le même {champ} ({valeur})"
                   for valeur, noms in vus.items() if len(noms) > 1]
    noms = sorted(fiches)
    for i, a in enumerate(noms):
        for b in noms[i + 1:]:
            if sans_separateurs(a) == sans_separateurs(b):
                rouges.append(f"{quoi}s {a} et {b} ne diffèrent que par la ponctuation")
            elif difflib.SequenceMatcher(None, a, b).ratio() >= SEUIL:
                avertissements.append(f"{quoi}s {a} et {b} se ressemblent beaucoup — doublon ou faute de frappe ?")
    for nom, fm in sorted(fiches.items()):
        if fm.get("name") and str(fm["name"]) != nom:
            rouges.append(f"{quoi} {nom} : l'en-tête dit name: {fm['name']} — fichier copié ou renommé ?")
    return rouges, avertissements


def projets(brain: Path, yaml) -> dict[str, dict]:
    dossier = brain / "projets"
    return {f.stem: entete(f, yaml) for f in sorted(dossier.glob("*.md"))} if dossier.is_dir() else {}


def tracks(brain: Path, yaml) -> dict[str, dict]:
    """Les tracks de learning/ — `type: learning-track` —, si le satellite est là."""
    learning = brain / "learning"
    if not learning.is_dir():
        return {}
    lues = {d.name: entete(d / "README.md", yaml) for d in sorted(learning.iterdir())
            if (d / "README.md").is_file()}
    lues |= {f.stem: entete(f, yaml) for f in sorted(learning.glob("*.md")) if f.name != "README.md"}
    return {n: fm for n, fm in lues.items() if fm.get("type") == "learning-track"}


def auto_epreuve() -> None:
    """Les cas que l'outil doit savoir juger — les témoins de sa calibration."""
    print("AUTO-ÉPREUVE\n")
    r, a = doublons({"mon-api": {"repo": "https://forge.exemple/moi/mon-api.git"},
                     "api-v2": {"repo": "forge.exemple/moi/mon-api/"}}, "projet")
    verifie("le même dépôt sous deux écritures → rouge", len(r), 1)
    r, _ = doublons({"mon-projet": {}, "mon_projet": {}}, "projet")
    verifie("ne différer que par la ponctuation → rouge", len(r), 1)
    r, _ = doublons({"nouveau": {"name": "ancien"}}, "projet")
    verifie("name: autre que le fichier → rouge", len(r), 1)
    r, a = doublons({"projet": {}, "projett": {}}, "projet")
    verifie("une faute de frappe (≥ 0,85) → avertissement, pas rouge", (len(r), len(a)), (0, 1))
    r, a = doublons({"outil-web": {}, "outil-cli": {}, "mon-projet-api": {}, "mon-projet-web": {}}, "projet")
    verifie("une famille (0,67 et 0,79) → rien", (len(r), len(a)), (0, 0))
    r, a = doublons({"_template": {"name": "autre"}, "x": {}}, "projet")
    verifie("un modèle (`_…`) n'est pas jugé", (len(r), len(a)), (0, 0))
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", type=Path, default=Path.home() / "Dev/Brain")
    args = ap.parse_args()
    brain = args.brain.expanduser().resolve()

    print("DOUBLONS DE PROJETS — deux fiches parlent-elles du même projet ?\n")
    auto_epreuve()
    if _ko:
        print(f"VERDICT: ❌ auto-épreuve : {_ko} cas sur {_ok + _ko} — l'outil ne mesure plus ce qu'il annonce")
        return 1

    try:
        import yaml
    except ImportError:
        print(f"SKIP — ce Python n'a pas le module « yaml » ({sys.executable})")
        return 0

    fiches_p, fiches_t = projets(brain, yaml), tracks(brain, yaml)
    if not fiches_p:
        print(f"SKIP — aucune fiche dans {brain / 'projets'}")
        return 0
    rouges, avert = doublons(fiches_p, "projet")
    r2, a2 = doublons(fiches_t, "track")
    rouges, avert = rouges + r2, avert + a2
    for ligne in rouges:
        print(f"  ❌ {ligne}")
    for ligne in avert:
        print(f"  ⚠️  {ligne}")
    jugees = f"{len(fiches_p)} projets" + (f", {len(fiches_t)} tracks" if fiches_t else "")
    if rouges:
        print(f"\nVERDICT: ❌ {len(rouges)} doublon(s) probable(s) sur {jugees}")
        return 1
    print(f"\nVERDICT: ✅ aucun doublon sur {jugees}"
          + (f" — {len(avert)} ressemblance(s) à relire" if avert else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
