#!/usr/bin/env python3
"""Le niveau de chaque chose, et ce qui n'y correspond pas

`NIVEAUX.yml` déclare de quelle nature est chaque entrée de la racine. C'est une
source écrite à la main : rien ne la génère. Ce sont les cinq mécanismes qui
classent aujourd'hui — `.gitignore`, `PATH_SCOPES`, `CORPUS_PATHS`,
`sync-template.sh`, les zones d'écriture — qui devront s'y accorder.

    python3 tools/niveaux.py --brain ~/Dev/Brain            # l'inventaire
    python3 tools/niveaux.py --brain ~/Dev/Brain --check    # pour brain doctor

**Deux sens, sinon la déclaration dérive du disque comme tout le reste** :

    une entrée qui existe sans être déclarée   → refus
    une entrée déclarée qui n'existe pas       → refus

C'est le contrôle qui rend un déménagement vérifiable : après avoir bougé un
répertoire, il dit immédiatement si la déclaration a suivi.

**Les désaccords ne font pas échouer.** Un `etat` versionné ou une `donnee`
distribuée sont des faits à corriger, pas des dérives à surveiller — ils sont
comptés et nommés, et c'est l'ordre du jour de la session de ménage. Les
`niveau: '?'` aussi : un item non tranché n'est pas une panne.

Sortie 1 si une entrée manque d'un côté ou de l'autre.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Ce que chaque niveau interdit. Rien de plus : un désaccord est un fait mesuré,
# pas une opinion sur la bonne arborescence.
# Ce qui compte comme la FORME d'un répertoire et non son contenu : un fichier
# dont la seule fonction est que le répertoire existe chez celui qui clone.
SQUELETTES = {".gitkeep", ".gitignore", "README.md"}

INTERDITS = {
    "etat":      [("versionné", True)],
    "artefact":  [("versionné", True)],
    "satellite": [("versionné", True)],
    "donnee":    [("distribué", True)],
    "vestige":   [("distribué", True)],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = args.brain.expanduser().resolve()
    catalogue = root / "NIVEAUX.yml"
    if not catalogue.exists():
        print(f"\n  ❌ {catalogue.name} absent — rien ne déclare les niveaux.\n")
        return 1

    import yaml
    d = yaml.safe_load(catalogue.read_text(encoding="utf-8"))
    declare = d.get("entrees") or {}
    vocabulaire = set(d.get("niveaux") or {})

    def niveau_de(v):
        return v.get("niveau") if isinstance(v, dict) else v

    # Un `-wal` ou un `-shm` n'est pas une entrée du brain : c'est un état
    # transitoire de la base qui porte le même nom, créé et détruit par SQLite
    # au gré des ouvertures. Le déclarer ferait rougir dans l'autre sens dès
    # qu'il disparaît — et il disparaît tout le temps.
    #
    # Le rattachement est vérifié, pas supposé : un `-wal` orphelin, dont la
    # base n'existe pas ou n'est pas déclarée, reste une entrée non déclarée.
    # C'est ce qui empêche cette exemption de devenir une porte ouverte.
    def compagnon_sqlite(nom: str) -> bool:
        for suffixe in ("-wal", "-shm", "-journal"):
            if nom.endswith(suffixe):
                base = nom[: -len(suffixe)]
                return base in declare and (root / base).is_file()
        return False

    sur_disque = {p.name + ("/" if p.is_dir() else "")
                  for p in root.iterdir()
                  if not p.name.startswith(".") and not compagnon_sqlite(p.name)}
    declarees = set(declare)

    print(f"\nNIVEAUX — {len(declarees)} entrées déclarées, {len(sur_disque)} sur le disque\n")

    # ── Les deux sens ────────────────────────────────────────────────────────
    non_declarees = sorted(sur_disque - declarees)
    # Une entrée qui dit QUI la crée (`cree_par:` — le setup, l'indexeur, la
    # sauvegarde) peut manquer encore : chez un fork neuf, `brain-secrets/` ou
    # `focus.instantane.md` n'existent qu'après leur créateur. Sa déclaration
    # tient d'avance sa zone ; son absence n'est pas une dérive.
    a_venir = sorted(n for n in declarees - sur_disque
                     if isinstance(declare[n], dict) and declare[n].get("cree_par"))
    fantomes = sorted(declarees - sur_disque - set(a_venir))
    if a_venir:
        print(f"  ⏳ {len(a_venir)} déclarée(s), à venir — "
              + ", ".join(f"{n} ({declare[n]['cree_par']})" for n in a_venir))
    for libelle, lot, pourquoi in (
            ("sur le disque, non déclarées", non_declarees,
             "une chose qui apparaît sans se déclarer échappe à toutes les règles"),
            ("déclarées, absentes du disque", fantomes,
             "une déclaration qui ne désigne rien vieillit sans que personne le voie")):
        if lot:
            print(f"  ❌ {len(lot)} {libelle}")
            print(f"     {pourquoi}")
            for e in lot[:8]:
                print(f"       {e}")
            if len(lot) > 8:
                print(f"       … et {len(lot) - 8} autres")
        else:
            print(f"  ✅ aucune {libelle}")

    inconnus = sorted({niveau_de(v) for v in declare.values()}
                      - vocabulaire - {"?"} - {None})
    if inconnus:
        print(f"  ❌ niveaux hors vocabulaire : {inconnus}")

    # ── Comment chaque dépôt imbriqué est rattaché ───────────────────────────
    #
    # Le brain avait TROIS mécanismes de rattachement — dépôt core, satellites
    # gitignorés, et un dépôt imbriqué non déclaré. Le troisième n'était écrit
    # nulle part : `wiki/` était suivi en gitlink (mode 160000) sans
    # `.gitmodules`, donc un `git clone` rendait un répertoire vide. Le pointeur
    # existait, la source non.
    #
    # Il n'en reste que deux, et ce contrôle interdit qu'un troisième réapparaisse.
    imbriques = []
    for chemin in sorted(root.glob("*/.git")):
        imbriques.append(chemin.parent.name)
    declares = set()
    gitmodules = root / ".gitmodules"
    if gitmodules.exists():
        r = subprocess.run(["git", "config", "-f", ".gitmodules",
                            "--get-regexp", r"submodule\..*\.path"],
                           cwd=str(root), capture_output=True, text=True)
        declares = {l.split()[-1] for l in r.stdout.splitlines() if l.strip()}

    orphelins = []
    for nom in imbriques:
        if nom in declares:
            continue
        if subprocess.run(["git", "check-ignore", "-q", nom],
                          cwd=str(root)).returncode == 0:
            continue
        orphelins.append(nom)

    if orphelins:
        print(f"\n  ❌ {len(orphelins)} dépôt(s) imbriqué(s) ni déclaré(s) ni ignoré(s) : "
              f"{', '.join(orphelins)}")
        print("     Un dépôt suivi en gitlink sans `.gitmodules` rend un répertoire")
        print("     vide au clonage : le pointeur existe, la source non.")
    else:
        print(f"\n  ✅ {len(imbriques)} dépôts imbriqués, tous rattachés "
              f"({len(declares)} sous-module(s) déclaré(s), "
              f"{len(imbriques) - len(declares)} satellite(s) ignoré(s))")

    # ── L'état des lieux ─────────────────────────────────────────────────────
    compte = Counter(niveau_de(v) for v in declare.values())
    a_trancher = [e for e, v in declare.items() if niveau_de(v) == "?"]
    print(f"\n  répartition   " + " · ".join(
        f"{n} {c}" for n, c in sorted(compte.items(), key=lambda kv: -kv[1]) if n != "?"))
    print(f"  à trancher    {len(a_trancher)} entrée(s) — décision")
    vestiges = [e for e, v in declare.items() if niveau_de(v) == "vestige"]
    if vestiges:
        print(f"  vestiges      {len(vestiges)} entrée(s) — la décision est prise, "
              f"le geste reste à faire")
        print(f"                {' '.join(sorted(vestiges))}")

    # ── Les désaccords, comptés et nommés ────────────────────────────────────
    def fichiers_suivis(nom: str) -> list[str]:
        """Ce que git suit RÉELLEMENT sous cette entrée.

        `git check-ignore` répondait à une autre question : « est-ce ignoré ? ».
        Un fichier ni suivi ni ignoré n'est pas versionné pour autant — il attend
        seulement dans `git status`. Les deux états méritent des phrases
        différentes, et c'est l'index qui tranche.
        """
        r = subprocess.run(["git", "ls-files", "-z", "--", nom],
                           cwd=str(root), capture_output=True, text=True)
        return [x for x in r.stdout.split("\0") if x]

    def est_squelette(entree: str, suivis: list[str]) -> bool:
        """Vrai si tout ce que git suit sous cette entrée est de la forme.

        Un répertoire dont seul le `.gitkeep` est suivi distribue sa place, pas
        son contenu. Un fichier déclaré squelette est son propre gabarit. Cette
        exemption reste capable de rougir : dès qu'un fichier de contenu entre
        dans l'index, elle ne s'applique plus et le dit.
        """
        if not entree.endswith("/"):
            return suivis == [entree]
        return bool(suivis) and all(Path(f).name in SQUELETTES for f in suivis)

    sync = (root / "scripts" / "sync-template.sh")
    texte_sync = sync.read_text(encoding="utf-8", errors="replace") if sync.exists() else ""

    desaccords = []
    for entree, valeur in declare.items():
        n = niveau_de(valeur)
        attrs = valeur if isinstance(valeur, dict) else {}
        nu = entree.rstrip("/")
        for quoi, interdit in INTERDITS.get(n, []):
            if quoi == "versionné":
                suivis = fichiers_suivis(nu)
                if bool(suivis) is not interdit:
                    continue
                if attrs.get("squelette") == "versionné":
                    if est_squelette(entree, suivis):
                        continue
                    contenu = [f for f in suivis if Path(f).name not in SQUELETTES]
                    desaccords.append(
                        f"{entree} déclaré squelette versionné, mais git suit "
                        f"{len(contenu)} fichier(s) de contenu")
                    continue
                desaccords.append(f"{entree} déclaré `{n}` mais versionné "
                                  f"({len(suivis)} fichier(s) suivi(s))")
            if quoi == "distribué":
                # Déclarée partiellement distribuée : on vérifie que la liste et
                # le script disent la même chose. Limite assumée — on attrape ce
                # qui est déclaré et non copié, pas ce qui serait copié sans être
                # déclaré ; seul le script sait ce qu'il copie vraiment.
                nommes = attrs.get("distribue")
                if nommes:
                    absents = [f for f in nommes if f not in texte_sync]
                    if absents:
                        desaccords.append(
                            f"{entree} déclare distribuer {', '.join(absents)}, "
                            f"que sync-template.sh ne copie pas")
                    continue
                if (f'BRAIN_ROOT/{nu}/' in texte_sync) is interdit:
                    desaccords.append(f"{entree} déclaré `{n}` mais copié vers le template")

    if desaccords:
        print(f"\n  ⚠️  {len(desaccords)} désaccord(s) entre le niveau déclaré et ce que "
              f"les mécanismes font :")
        for x in desaccords:
            print(f"       {x}")
        print("     Ce sont des faits à corriger, pas des dérives à surveiller.")
    else:
        print("\n  ✅ aucun désaccord entre les niveaux déclarés et les mécanismes")

    manque = bool(non_declarees or fantomes or inconnus or orphelins)
    print()
    if manque:
        print("  ❌ la déclaration et le disque ne se recouvrent pas\n")
        return 1
    print("  ✅ tout ce qui existe est déclaré, tout ce qui est déclaré existe\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
