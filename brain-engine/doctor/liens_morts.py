#!/usr/bin/env python3
"""Les chemins cités existent-ils encore ?

Un déménagement de fichiers ne casse rien bruyamment : il laisse des chemins qui
ne mènent plus nulle part, dans des agents qu'on charge au boot. Rien ne lève
d'erreur — l'agent est lu, le lien est mort, et le contexte arrive amputé.

C'est le filet dont deux chantiers ont besoin pour être vérifiables : après
avoir bougé un répertoire, il dit immédiatement si les références ont suivi.

    python3 tools/liens_morts.py --brain ~/Dev/Brain
    python3 tools/liens_morts.py --brain ~/Dev/Brain --poser   # (re)pose le seuil

── Ce qu'il mesure, et pourquoi ainsi ──────────────────────────────────────

Il ne regarde que les **zones vivantes** — `agents/`, `contexts/`, `scripts/`,
`brain-engine/`, et les quatre fichiers de racine chargés au boot. Le backlog et
les handoffs citent des chemins par centaines, souvent des chemins passés qu'on
raconte : y chercher des liens morts fabriquerait un rouge permanent que
personne ne peut verdir, un piège déjà vu.

Il ne rougit pas non plus sur le nombre absolu. Mesuré le 05/09 avant tout
déménagement : **24 cibles introuvables**, dont des exemples de documentation —
`agents/X.md`, `agents/foo.md`, `agents/test.md`. Les traiter comme des défauts
serait confondre un placeholder avec une référence.

Il rougit sur l'**augmentation** : le seuil est enregistré dans
`.liens-morts-seuil`. Un déménagement qui casse trois liens le fait monter, et
c'est exactement ce qu'on veut savoir à ce moment-là.

Sortie 1 si le nombre de cibles introuvables dépasse le seuil enregistré.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config_instance import config_du_doctor  # noqa: E402 — instance/doctor/, l'ancien emplacement en repli

TEMOIN = ".liens-morts-seuil"
ZONES = ("agents", "contexts", "scripts", "brain-engine")

#: Les arbres qu on ne traverse pas. `registre_des_secrets.py` et
#: `template_autonome.py` portaient deja cette liste ; cet outil ne l avait pas,
#: et il est le seul des sept marcheurs sans exclusion a descendre reellement
#: dans un arbre tiers (`ZONES` contient `brain-engine`, les autres n y visent
#: que des fichiers nommes).
#:
#: Revele le 26/09 en donnant un venv au moteur [M09] : `pygments`, vendorise
#: par `pip`, cite ses propres scripts dans ses commentaires —
#: `scripts/get_vimkw.py`, `scripts/gen_mapfiles.py`… L outil les a lus comme
#: des chemins du brain et a rendu QUATRE liens morts qui n existent pas.
#:
#: Le seuil est passe de 37 a 40 sans qu une seule ligne du brain change. La
#: tentation etait de reposer le seuil ; ça aurait grave dans le marbre quatre
#: liens fantomes et masque les vrais qui seraient venus apres.
IGNORES = frozenset({".git", ".venv", ".venv-x11", "venv", "node_modules",
                     "__pycache__", "site-packages", "vendor", "dist", "build"})
RACINE_FICHIERS = ("CLAUDE.md", "KERNEL.md", "PATHS.md", "ENTRYPOINT.md")

#: Un fichier de TEST n'est chargé par personne au boot, et les chemins qu'il
#: cite sont des DONNÉES de test — `agents/a.md`, `wiki/page.md`, le chemin
#: d'un incident copié mot pour mot. Le 29/09, trois chemins d'un test
#: (`workspace/scratch/wt-v236/…`) sont devenus « morts » au retrait d'un
#: worktree, et deux autres avaient fait reposer le seuil la veille : c'est
#: exactement le « gravé dans le marbre » que la note d'IGNORES refuse.
def est_un_test(p: Path) -> bool:
    return p.name.startswith("test_") and p.suffix == ".py"


#: Une ARCHIVE est figée : ce qu'elle cite, c'était vrai le jour où on l'a
#: rangée, et personne ne la charge. Le 30/09, l'archivage de la machinerie des
#: sprints a rangé neuf agents et huit scripts qui se citent entre eux à leurs
#: anciens chemins : quarante « liens morts » d'un coup, sans qu'un seul
#: fichier vivant ait changé. Réécrire une archive pour le contrôle, ce serait
#: la falsifier ; reposer le seuil, graver ces liens dans le marbre. On ne lit
#: donc pas `archive/` ni `archive-*/` — ce que les fichiers VIVANTS citent
#: d'une archive, en revanche, compte toujours.
def est_une_archive(parties: tuple[str, ...]) -> bool:
    return any(x == "archive" or x.startswith("archive-") for x in parties[:-1])
SUFFIXES = (".md", ".py", ".sh", ".yml", ".sql")

#: Un chemin qui COMMENCE ici : pas la suite d'un autre. `\b` laissait lire
#: `instance/agents/coach.complement.md` comme `agents/coach.complement.md`, cherché
#: à la racine — un lien vivant compté mort (4/10, le complément de l'instance).
CHEMIN = re.compile(
    r"(?<![\w./-])((?:profil|agents|contexts|scripts|workspace|handoffs|wiki|toolkit|todo)"
    r"/[A-Za-z0-9_./-]+\.(?:md|py|sh|yml|sql))")


def cibles_mortes(racine: Path) -> dict[str, list[str]]:
    fichiers = [p for z in ZONES for p in (racine / z).rglob("*")
                if p.is_file() and p.suffix in SUFFIXES and not est_un_test(p)
                and not (IGNORES & set(p.relative_to(racine).parts))
                and not est_une_archive(p.relative_to(racine).parts)]
    fichiers += [racine / f for f in RACINE_FICHIERS if (racine / f).is_file()]
    morts: dict[str, list[str]] = {}
    for f in fichiers:
        try:
            texte = f.read_text(encoding="utf-8", errors="replace")
        except Exception:                                  # noqa: BLE001
            continue
        for cible in set(CHEMIN.findall(texte)):
            if not (racine / cible).exists():
                morts.setdefault(cible, []).append(
                    str(f.relative_to(racine)))
    return morts


# ── Auto-epreuve ───────────────────────────────────────────────────────────

_ok = _ko = 0


def _verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


def auto_epreuve() -> int:
    """Le premier cas est l incident du 26/09, copie mot pour mot.

    `pygments`, vendorise dans le venv du moteur, porte dans ses sources la
    ligne qui a tout declenche. On la reprend telle quelle.
    """
    import tempfile

    print("\nAUTO-ÉPREUVE — ce qu on traverse, et ce qu on laisse\n")
    # La ligne exacte trouvee dans pygments/lexers/_vim_builtins.py
    INCIDENT = "# Generated by scripts/get_vimkw.py -- do not edit\n"

    with tempfile.TemporaryDirectory() as tmp:
        r = Path(tmp)
        (r / "agents").mkdir()
        (r / "brain-engine").mkdir()

        # 1. Le MEME texte, dedans et dehors : seule la place change.
        vendor = r / "brain-engine" / ".venv" / "lib" / "python3.12" / "site-packages" / "pygments" / "lexers"
        vendor.mkdir(parents=True)
        (vendor / "_vim_builtins.py").write_text(INCIDENT, encoding="utf-8")
        morts = cibles_mortes(r)
        _verifie("l incident du 26/09 : un arbre vendorise n est pas traverse",
                 "scripts/get_vimkw.py" in morts, False)

        (r / "brain-engine" / "outil.py").write_text(INCIDENT, encoding="utf-8")
        morts = cibles_mortes(r)
        _verifie("… mais le MEME texte hors du venv est bien compte",
                 morts.get("scripts/get_vimkw.py"), ["brain-engine/outil.py"])

        # 2. Le temoin qui manquait : un lien VIVANT ne doit pas etre compte.
        (r / "scripts").mkdir()
        (r / "scripts" / "vrai.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (r / "agents" / "a.md").write_text("voir scripts/vrai.sh\n", encoding="utf-8")
        morts = cibles_mortes(r)
        _verifie("un lien qui MENE quelque part n est pas un lien mort",
                 "scripts/vrai.sh" in morts, False)

        # 2 bis. Un chemin au milieu d'un autre n'est pas un chemin de la racine.
        (r / "instance" / "agents").mkdir(parents=True)
        (r / "instance" / "agents" / "x.complement.md").write_text("x\n", encoding="utf-8")
        (r / "agents" / "b.md").write_text("voir instance/agents/x.complement.md\n", encoding="utf-8")
        morts = cibles_mortes(r)
        _verifie("instance/agents/… n est pas agents/… : un lien vivant",
                 "agents/x.complement.md" in morts, False)

        # 3. Les autres arbres de la liste.
        for nom in ("node_modules", "__pycache__", "vendor", "dist"):
            piege = r / "agents" / nom
            piege.mkdir()
            (piege / "p.py").write_text("agents/fantome-" + nom + ".md\n",
                                        encoding="utf-8")
        morts = cibles_mortes(r)
        restants = [c for c in morts if c.startswith("agents/fantome-")]
        _verifie("node_modules, __pycache__, vendor, dist : rien n en sort",
                 restants, [])

        # 4. Le 29/09 : un fichier de test cite des chemins qui sont des
        #    DONNEES. La ligne est celle du test, copiee mot pour mot.
        FIXTURE = "        f('workspace/scratch/wt-v236/workspace/papers/README.md')\n"
        (r / "brain-engine" / "test_brain_engine.py").write_text(FIXTURE, encoding="utf-8")
        (r / "brain-engine" / "outil2.py").write_text(FIXTURE, encoding="utf-8")
        morts = cibles_mortes(r)
        _verifie("un fichier de test n est pas lu, le meme texte ailleurs l est",
                 morts.get("workspace/scratch/wt-v236/workspace/papers/README.md"),
                 ["brain-engine/outil2.py"])

        # 5. Le 30/09 : une archive cite ses voisins à leurs anciens chemins.
        #    La ligne est celle de `agents/archive/kernel-orchestrator.md`.
        RANGE = "| `agents/satellite-boot.md` | Protocole BSI — tiered close, exit triggers |\n"
        (r / "agents" / "archive").mkdir()
        (r / "agents" / "archive" / "kernel-orchestrator.md").write_text(RANGE, encoding="utf-8")
        (r / "contexts" / "archive-v1").mkdir(parents=True)
        (r / "contexts" / "archive-v1" / "s.yml").write_text(RANGE, encoding="utf-8")
        (r / "agents" / "vivant.md").write_text(RANGE, encoding="utf-8")
        morts = cibles_mortes(r)
        _verifie("une archive n est pas lue, le meme texte dans un agent vivant l est",
                 morts.get("agents/satellite-boot.md"), ["agents/vivant.md"])

    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    return 1 if _ko else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--poser", action="store_true",
                   help="(re)pose le seuil sur la mesure courante")
    args = p.parse_args()
    racine = args.brain.expanduser().resolve()

    # L instrument s eprouve AVANT de mesurer : un outil qui vient de rater son
    # epreuve n a pas a rendre un chiffre, et surtout pas a reposer un seuil.
    if auto_epreuve():
        print("\nVERDICT: l'auto-épreuve a échoué — rien n'est mesuré")
        return 1

    morts = cibles_mortes(racine)
    n = len(morts)

    temoin = config_du_doctor(racine, TEMOIN.lstrip("."))
    if args.poser or not temoin.is_file():
        temoin.parent.mkdir(parents=True, exist_ok=True)
        temoin.write_text(f"{n}\n", encoding="utf-8")
        print(f"\nLIENS MORTS — seuil posé à {n}")
        print("  Les zones vivantes sont mesurées ; le backlog ne l'est pas.\n")
        return 0

    seuil = int(temoin.read_text(encoding="utf-8").strip() or 0)

    print(f"\nLIENS MORTS — zones vivantes\n")
    print(f"  cibles introuvables   {n}")
    print(f"  seuil enregistré      {seuil}")

    if n > seuil:
        print()
        for cible, sources in sorted(morts.items())[:10]:
            print(f"  ❌ {cible}")
            for s in sources[:2]:
                print(f"       cité par {s}")
        if n > 10:
            print(f"     … et {n - 10} autre(s)")
        # Verdict DECLARE. Sans lui, le doctor resumait ce controle par
        # sa derniere ligne `❌`, c est-a-dire par UN nom de fichier
        # (« agents/test.md ») au lieu de « 3 de plus qu au point de reference ».
        # Vu le 26/09 : le constat affiche etait le dixieme lien liste, sans
        # rapport avec ce qui avait change.
        print(f"\nVERDICT: {n - seuil} lien(s) mort(s) de plus qu'au point de "
              f"référence — {n} au total, seuil {seuil}")
        print(f"\n     {n - seuil} de plus qu'au dernier point de référence.")
        print("     Un chemin qui ne mène plus nulle part ne lève aucune erreur :")
        print("     l'agent est lu, le lien est mort, le contexte arrive amputé.")
        print("     Après un déménagement volontaire : --poser.\n")
        return 1

    if n < seuil:
        print(f"\n  ✅ {seuil - n} de moins qu'au seuil — pensez à `--poser`")
    print(f"\nVERDICT: aucun lien mort de plus qu'au point de référence — "
          f"{n} au total, seuil {seuil}")
    print(f"\n  ✅ aucun lien mort de plus qu'au point de référence\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
