#!/usr/bin/env python3
"""Les contrôles savent-ils encore dire non ?

Un contrôle vert ne prouve rien tant que personne ne l'a vu rougir. La matinée
du 04/09 l'a montré deux fois : `contextes_de_session.py` calculait
`(racine / "todo/").parent` — la racine — et ne pouvait donc **pas** rougir sur
un template `L2` ; et `kernel-isolation-check.sh` mourait sur SIGPIPE deux fois
sur dix, en rendant un code de sortie qui ressemblait à un refus motivé.

Les deux ont été trouvés par des témoins posés à la main, qui ont disparu avec
la session. Ce fichier les rend permanents. Il construit des situations
**fausses** dans un brain jetable, et vérifie que chaque outil les refuse.

    python3 tools/test_controles_rougissent.py

Garanties :

    contextes / L1        un fichier déclaré et absent est signalé
    contextes / L2        un template dont le répertoire manque est signalé
    contextes / vrai      un brain cohérent passe au vert
    lock / version        lock et compose en désaccord ⇒ refus, quel que soit l'écart
    lock / seuil          onze fichiers inconnus ⇒ refus ; un seul ⇒ vert
    lock / ignorés        ce que .gitignore écarte ne compte pas (Ventoy, 27/09)
    lock / absent         pas de kernel.lock ⇒ refus, pas un vert par défaut
    niveaux / non déclaré une entrée qui apparaît sans se déclarer est signalée
    niveaux / fantôme     une entrée déclarée et absente est signalée
    registre / hors cat.  un agent que le catalogue ignore est signalé
    registre / en retard  un catalogue qui n'est pas ce que `--emit` produirait
                          (description, statut, classification) rougit en
                          nommant l'agent et le champ ; régénéré, il passe
    registre / orpheline  une entrée dont le fichier a disparu est nommée sous
                          ENTRÉES ORPHELINES
    registre / export     frontmatter et catalogue contraires sur `export` : l'agent
                          est nommé sous DÉSACCORD `export`
    manifests / clé       une clé hors contrat dans `L2` est signalée
    manifests / YAML      un manifest illisible est signalé, pas ignoré
    ancre / présente      un tag `programme/vX` qui existe passe
    ancre / manquante     une version déclarée sans tag est signalée
    claim / deux voix     un agent qui décrit la procédure abolie est signalé
    sauvegarde / absente  pas de dump du tout ⇒ refus, pas un vert par défaut
    isolation / règle     le bloc qui ÉNONCE les interdits ne les viole pas
    isolation / hors bloc le même motif écrit ailleurs rougit toujours
    isolation / chemin    un chemin machine dans KERNEL.md rougit, sans exemption
    clôture / titre       une fiche close en titre sans rapport rougit — l'incident
    clôture / formes      une puce à deux emoji est vue ; le rapport voisin ne compte pas
    clôture / reprise     une fiche reprise se lit dans sa dernière entrée
    clôture / nommée      une exemption nommée passe ; sans raison, ou périmée, rougit
    éclater / index       rien de perdu (bloc de code compris) ; l'index à jour ;
                          une fiche changée sans régénérer ⇒ rouge ; pas de second geste
    daemon / base         brain-watch-local survit à une base injoignable
    rattachement / corpus un appel depuis un venv ne rattache pas ; une source de
                          hook versionnée rattache
    hooks / worktree      l'installateur écrit les quatre ; en worktree, ni base ni
                          synchro ; la fusion synchronise ; un hook manquant ⇒ rouge
    lecteur / source      backlog retiré ⇒ clôture ET issues rougissent ; une fiche
                          éclatée seule les nourrit ; deux sources ⇒ rouge
    wiki / juste          un boot d'avant V2 ⇒ refus ; un CHANGELOG en retard ⇒ refus ;
                          un juge aveugle ⇒ refus, pas un vert
    vue / juste           un agent écrit dans la vue, un fichier réel, un lien absent,
                          faux ou orphelin, le catalogue absent, un replica au noyau
                          ouvert (noyau/ lui-même compris), un retrait resté dans
                          noyau/ ⇒ rouge ; la vue juste, un .gitkeep et un brain à plat
                          passent
    kanban / tenir        l'index absent se régénère ; à blanc rougit sans écrire ;
                          une clôture sans preuve arrête avant la forge (BRAIN-079)
    zone / projet         un préfixe déclaré se tient ; l'exemption d'un autre préfixe
                          ne le touche pas ; sans `prefixe:` ⇒ rouge
    naissance / projet    à blanc n'écrit rien ; slug ou préfixe pris ⇒ refus avant
                          d'écrire ; créé ⇒ la zone tient
    tous / listes         l'appel d'avant aveugle à l'autre liste ; `--tous` rougit
    mort / projet         à blanc n'écrit rien ; déjà archivé ⇒ refus ; archivé ⇒ les
                          ouvertes en pause, les closes intactes, la zone tient

Chaque garantie vérifie **le code de sortie**, pas le texte : c'est ce que les
appelants lisent, et c'était précisément le défaut d'origine.

**Ce qui n'est pas couvert, et pourquoi.** `normalize_status.py`,
`project_registry.py` et `index_purge.py` lisent la base : ils ne sont pas
isolables dans un brain jetable, et les faire pointer sur la vraie base ferait
d'un témoin un écrivain.

**Trois contrôles nés le 04/09 sont dans le même cas, et il faut le dire** —
`handoffs_en_base.py`, `bsi_etat.py`, `hits_hors_table.py`. Tous trois
interrogent la base vivante par construction : c'est l'écart entre ce qu'elle
porte et ce que le disque déclare qu'ils mesurent. Leurs témoins négatifs ont
été **éprouvés à la main le jour même** — une ligne de handoff retirée de la
base, le `touch` retiré du hook, un `+1` écrit dans la colonne gelée, et les
trois ont refusé avec leur motif. Mais ces témoins-là ont disparu avec la
séance, exactement comme ceux que ce fichier a été écrit pour rendre permanents.
Le 03/10, `bsi_etat.py` a encore été éprouvé à la main : dans un worktree (`.git`
y est un fichier), le hook n'était plus trouvé — rouge avant le correctif, vert après.
La couverture n'est donc pas complète, et ce paragraphe existe pour qu'on ne
croie pas le contraire. `test_index_corpus.py`, `test_cache_matrice.py`,
`test_conventions_temporelles.py` et `test_dolt_discipline.py` portent déjà
leur propre témoin négatif. Restent `brain-validate` et les routes vitales, qui
exercent le brain vivant par nature.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import importlib.util
import os
import tempfile
from pathlib import Path

OUTILS = Path(__file__).resolve().parent



def python_du_brain(brain: Path) -> str:
    """Le python du venv du brain : c'est lui qui importe `db` (le CORE, pymysql).
    Lancés avec le python du système, les outils qui lisent la base répondaient
    « SKIP base injoignable (ImportError) » — leurs témoins ne mesuraient plus
    rien depuis la migration vers le venv (vu le 28/09)."""
    venv = brain / "brain-engine" / ".venv" / "bin" / "python3"
    return str(venv) if venv.is_file() else sys.executable

def _outils_presents(*outils: str) -> bool:
    """Le doctor distribué n'emporte pas les outils d'instance que ce fichier
    éprouve aussi : leur section s'abstient, en le disant — elle ne rougit pas
    pour un outil qui n'a pas à être là."""
    return all((OUTILS / o).is_file() for o in outils)


def joue(outil: str, racine: Path, *extra: str) -> int:
    r = subprocess.run([sys.executable, str(OUTILS / outil), "--brain", str(racine),
                        *extra], capture_output=True, text=True)
    return r.returncode


# Le vrai brain, d'où les témoins COPIENT des scripts et des manifestes — ils ne
# l'écrivent jamais. Il vient de `--brain` ; le défaut suppose myeline rangé à
# côté (`~/Dev/Gitea/myeline` → `~/Dev/Brain`). Mesuré le 28/09 : depuis un
# worktree, ce défaut ne menait nulle part — trois garanties rougissaient en
# `code -1`, et trois autres (daemon, TTL, archivage) s'abstenaient en silence.
VRAI_BRAIN = Path(__file__).resolve().parents[3] / "Brain"


def joue_bash(script: str, base: Path) -> int:
    """Certains contrôles sont des scripts shell. Ils déduisent leur racine du
    dépôt qui les porte : il faut donc les copier DANS le brain jetable, pas les
    appeler depuis le vrai brain — sinon le témoin mesure le vrai brain."""
    src = VRAI_BRAIN / "scripts" / script
    if not src.exists():
        return -1
    cible = base / "scripts" / script
    cible.write_bytes(src.read_bytes())
    r = subprocess.run(["bash", str(cible)], cwd=base, capture_output=True, text=True)
    return r.returncode


def git_init(base: Path) -> None:
    """`niveaux.py` interroge l'index git : sans dépôt, il ne mesure rien."""
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t",
                 "commit", "-qm", "temoin"]):
        subprocess.run(["git", *cmd], cwd=base, capture_output=True)


def brain_jetable(base: Path) -> Path:
    """Le plus petit brain qui ait un sens pour ces contrôles."""
    (base / "contexts").mkdir(parents=True)
    (base / "agents").mkdir()
    (base / "scripts").mkdir()
    (base / "projets").mkdir()
    for f in ("KERNEL.md", "brain-constitution.md"):
        (base / f).write_text("# " + f, encoding="utf-8")
    (base / "brain-compose.yml").write_text('version: "1.0.0"\n', encoding="utf-8")
    (base / "agents" / "coach.md").write_text(
        "---\nname: coach\ntype: agent\nstatus: active\n"
        "brain:\n  version: 1\n  scope: kernel\n---\n", encoding="utf-8")
    # `bsi_coherence.py` exige que la procédure soit nommée à ces deux endroits
    # précis — c'est tout son propos : une seule description, et au bon endroit.
    (base / "agents" / "helloWorld.md").write_text(
        "---\nname: helloWorld\ntype: agent\nstatus: active\n"
        "brain:\n  version: 1\n  scope: kernel\n  hold: témoin\n---\n\n"
        "# Boot\n\n`bash scripts/bsi-claim.sh open <sess_id>` — brain.db est la\n"
        "source unique. Pas de commit git, pas de push.\n", encoding="utf-8")
    (base / "BRAIN-INDEX.md").write_text(
        "# Index\n\nOuvrir un claim : `bash scripts/bsi-claim.sh open <sess_id>`.\n",
        encoding="utf-8")
    (base / "agents" / "CATALOG.yml").write_text(
        "generated: true\ncounts:\n  programme: 1\nagents:\n"
        "- id: coach\n  classification: programme\n  scope: kernel\n"
        "  distributable: true\n  type: agent\n  status: active\n"
        "  description: temoin\n"
        "- id: helloWorld\n  classification: programme\n  scope: kernel\n"
        "  distributable: false\n  type: agent\n  status: active\n"
        "  hold: temoin\n  description: temoin\n", encoding="utf-8")
    # Les six types, parce que `session_manifests.py` vérifie qu'aucun ne
    # manque — et il a raison : un type sans manifest boote sur rien.
    for typ in ("work", "brain", "explore", "pilote", "chill", "learning"):
        (base / "contexts" / f"session-{typ}.yml").write_text(
            f'session_type: {typ}\n'
            'L0:\n  - KERNEL.md\n'
            'L1:\n  - agents/coach.md\n'
            'L2:\n  template: "projets/{project}.md"\n'
            '  extras: []\n  fallback: null\n',
            encoding="utf-8")
    return base


def lock_pour(base: Path, version: str = "1.0.0") -> None:
    """Un lock cohérent avec le brain jetable, écrit à la main."""
    import hashlib
    lignes = [f'kernel_version: "{version}"', "generated_at: \"2026-01-01T00:00\"",
              "files:"]
    for c in ("KERNEL.md", "brain-compose.yml", "brain-constitution.md",
              "agents/coach.md"):
        h = hashlib.sha256((base / c).read_bytes()).hexdigest()
        lignes.append(f"  {c}: {h}")
    (base / "kernel.lock").write_text("\n".join(lignes) + "\n", encoding="utf-8")


def main() -> int:
    # `--brain` ne désigne pas où l'on écrit : chaque témoin construit son brain
    # jetable. Il dit d'où COPIER les vrais scripts et manifestes (VRAI_BRAIN).
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, default=None,
                   help="le vrai brain, d'où copier scripts et manifestes — "
                        "jamais écrit ; les témoins travaillent dans des brains temporaires")
    args = p.parse_args()
    global VRAI_BRAIN
    if args.brain:
        VRAI_BRAIN = args.brain.expanduser().resolve()

    echecs: list[str] = []

    def garantie(nom: str, obtenu: int, attendu: int) -> None:
        etat = "✅" if obtenu == attendu else "❌"
        print(f"  {etat} {nom:34} code {obtenu} (attendu {attendu})")
        if obtenu != attendu:
            echecs.append(nom)

    with tempfile.TemporaryDirectory(prefix="temoin-controles-") as tmp:
        base = brain_jetable(Path(tmp))
        ctx = base / "contexts" / "session-work.yml"
        vrai = ctx.read_text(encoding="utf-8")

        print("\nCONTRÔLES — savent-ils encore dire non ?\n")

        garantie("contextes / brain cohérent",
                 joue("contextes_de_session.py", base), 0)

        ctx.write_text(vrai.replace("agents/coach.md", "agents/parti.md"),
                       encoding="utf-8")
        garantie("contextes / L1 absent",
                 joue("contextes_de_session.py", base), 1)

        # Le cas qui ne rougissait pas : le motif masquait un répertoire mort.
        ctx.write_text(vrai.replace("projets/{project}.md", "disparu/{project}.md"),
                       encoding="utf-8")
        garantie("contextes / L2 répertoire mort",
                 joue("contextes_de_session.py", base), 1)
        ctx.write_text(vrai, encoding="utf-8")

        garantie("lock / absent",
                 joue("derive_du_lock.py", base), 1)

        lock_pour(base)
        garantie("lock / cohérent",
                 joue("derive_du_lock.py", base), 0)

        # Un seul inconnu reste sous le seuil ; onze le franchissent.
        (base / "scripts" / "un.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        garantie("lock / un inconnu, sous le seuil",
                 joue("derive_du_lock.py", base), 0)
        for i in range(11):
            (base / "scripts" / f"n{i}.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        garantie("lock / douze inconnus, au-dessus",
                 joue("derive_du_lock.py", base), 1)

        # Ce que .gitignore écarte n'est pas du noyau : le générateur ne l'empreinte
        # pas, le contrôle ne doit pas le compter. L'incident du 27/09 : une
        # distribution Ventoy ignorée sous scripts/ventoy/ pesait 9 sur un seuil de 10.
        with tempfile.TemporaryDirectory(prefix="temoin-lock-git-") as tmp2:
            base2 = brain_jetable(Path(tmp2))
            lock_pour(base2)
            (base2 / ".gitignore").write_text("scripts/tiers-*/\n", encoding="utf-8")
            tiers = base2 / "scripts" / "tiers-1.0"
            tiers.mkdir()
            for i in range(12):
                (tiers / f"t{i}.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            git_init(base2)
            garantie("lock / douze ignorés par git ne comptent pas",
                     joue("derive_du_lock.py", base2), 0)

        # La version prime : un seul fichier d'écart et un désaccord de version.
        for f in base.glob("scripts/*.sh"):
            f.unlink()
        lock_pour(base, version="0.9.0")
        garantie("lock / version en désaccord",
                 joue("derive_du_lock.py", base), 1)

        # ── niveaux : les deux sens, et il faut un dépôt git ──────────────
        niveaux = base / "NIVEAUX.yml"
        # `NIVEAUX.yml` doit se déclarer lui-même — il n'existe pas encore quand
        # on liste. C'est le premier défaut que l'outil avait attrapé le 03/09,
        # sur le vrai brain : il s'était pris lui-même en défaut.
        entrees = sorted([p.name + ("/" if p.is_dir() else "")
                          for p in base.iterdir() if not p.name.startswith(".")]
                         + ["NIVEAUX.yml"])
        # Les deux-points ne sont pas décoratifs : sans eux YAML lit la chaîne
        # caractère par caractère, et le témoin accuse l'outil de son propre
        # défaut. Premier jet du 04/09 — 29 « entrées » pour 9 fichiers.
        declare = "\n".join(f'  "{e}": programme' for e in entrees)
        niveaux.write_text(
            "version: 1\nniveaux:\n  programme: \"conçu, versionné\"\n"
            f"entrees:\n{declare}\n", encoding="utf-8")
        git_init(base)
        garantie("niveaux / brain cohérent",
                 joue("niveaux.py", base, "--check"), 0)

        (base / "surprise.md").write_text("apparu sans se déclarer", encoding="utf-8")
        garantie("niveaux / entrée non déclarée",
                 joue("niveaux.py", base, "--check"), 1)
        (base / "surprise.md").unlink()

        vrai_niveaux = niveaux.read_text(encoding="utf-8")
        niveaux.write_text(vrai_niveaux + '  "fantome.md": programme\n',
                           encoding="utf-8")
        garantie("niveaux / entrée fantôme",
                 joue("niveaux.py", base, "--check"), 1)
        niveaux.write_text(vrai_niveaux, encoding="utf-8")

        # ── manifests : une clé inconnue est une dérive, pas une extension ─
        garantie("manifests / contrat respecté",
                 joue("session_manifests.py", base, "--check"), 0)

        ctx.write_text(vrai.replace("  extras: []",
                                    "  extras: []\n  template_optional: x"),
                       encoding="utf-8")
        garantie("manifests / clé hors contrat",
                 joue("session_manifests.py", base, "--check"), 1)

        # Un manifest illisible doit se plaindre, pas disparaître du décompte.
        ctx.write_text("session_type: work\nL2:\n  template: [ non ferme\n",
                       encoding="utf-8")
        garantie("manifests / YAML invalide",
                 joue("session_manifests.py", base, "--check"), 1)
        ctx.write_text(vrai, encoding="utf-8")

        # ── ancre : une version déclarée doit désigner un état du dépôt ────
        # `brain-compose.yml` dit 1.0.0 ; l'ancre attendue est `programme/v1.0.0`.
        if _outils_presents("overlay.py"):
            garantie("ancre / manquante",
                     joue("overlay.py", base, "--check"), 1)
            subprocess.run(["git", "tag", "programme/v1.0.0"], cwd=base,
                           capture_output=True)
            garantie("ancre / présente",
                     joue("overlay.py", base, "--check"), 0)
        else:
            print("  ⏭  ancre : une version déclarée doit désigner un état / outil d'instance absent de ce brain")

        # ── L'ombre d'un brain migré : la structure n'est pas une ombre — ──
        #
        # `agents/` devenu une vue de `noyau/agents/` : avant, l'ombre comptait chaque
        # agent « retiré par l'instance » (98 sur 98, mesuré le 3/10). Le déménagement
        # se nomme, il ne gonfle pas l'ombre ; les surcharges de `instance/` se comptent.
        if _outils_presents("overlay.py"):
            with tempfile.TemporaryDirectory(prefix="temoin-ombre-vue-") as tmp:
                b = brain_jetable(Path(tmp))
                git_init(b)
                subprocess.run(["git", "tag", "programme/v1.0.0"], cwd=b, capture_output=True)
                (b / "noyau").mkdir()
                subprocess.run(["git", "mv", "agents", "noyau/agents"], cwd=b, capture_output=True)
                (b / "instance" / "agents").mkdir(parents=True)
                (b / "instance" / "agents" / "coach.md").write_text("# surcharge\n", encoding="utf-8")
                git_init(b)
                r = subprocess.run([sys.executable, str(OUTILS / "overlay.py"), "--brain", str(b)],
                                   capture_output=True, text=True, timeout=120)
                ok = ("déménagés dans le noyau" in r.stdout and "retirés par l'instance" not in r.stdout
                      and "surcharges déclarées" in r.stdout)
                garantie("ombre / la structure n'est pas une ombre", 0 if ok else 1, 0)

        # ── claim : une seule description du mécanisme ─────────────────────
        garantie("claim / une seule voix",
                 joue("bsi_coherence.py", base), 0)

        (base / "agents" / "vieux-boot.md").write_text(
            "---\nname: vieux-boot\ntype: agent\nbrain:\n  scope: kernel\n---\n\n"
            "# Boot\n\nÉcrire `claims/sess-<id>.yml`, puis `git add claims/` et\n"
            "`git commit -m \"claim\"` avant de pousser.\n", encoding="utf-8")
        garantie("claim / la procédure abolie",
                 joue("bsi_coherence.py", base), 1)
        (base / "agents" / "vieux-boot.md").unlink()

        # ── sauvegarde : pas de dump n'est pas un vert ─────────────────────
        # Là où la sauvegarde existe (`brain-db-backup.sh`) : sans lui, le
        # contrôle s'abstient, et c'est voulu.
        if (VRAI_BRAIN / "scripts" / "brain-db-backup.sh").is_file():
            import shutil as _copie       # `shutil` est importé plus bas dans main()
            (base / "scripts").mkdir(exist_ok=True)
            _copie.copy2(VRAI_BRAIN / "scripts" / "brain-db-backup.sh",
                         base / "scripts" / "brain-db-backup.sh")
            garantie("sauvegarde / aucun dump",
                     joue("sauvegarde_restaurable.py", base), 1)
            (base / "scripts" / "brain-db-backup.sh").unlink()
        else:
            print("  ⏭  sauvegarde / pas de brain-db-backup.sh dans ce brain")

        # ── registre : le défaut d'origine, en permanence ─────────
        #
        # Le catalogue du brain jetable est écrit à la main : il n'est pas ce
        # que `--emit` produirait, et depuis le 29/09 `--check` le voit. On le
        # régénère pour ces garanties, puis on remet l'original — les témoins
        # qui suivent ont été écrits contre lui.
        catalogue = base / "agents" / "CATALOG.yml"
        catalogue_original = catalogue.read_text(encoding="utf-8")
        garantie("registre / catalogue écrit à la main",
                 joue("agent_registry.py", base, "--check"), 1)
        garantie("registre / --emit régénère",
                 joue("agent_registry.py", base, "--emit", str(catalogue)), 0)
        genere = catalogue.read_text(encoding="utf-8")
        garantie("registre / catalogue à jour",
                 joue("agent_registry.py", base, "--check"), 0)

        # ── registre en retard ────────────────────────────────────
        #
        # Le 29/09, deux descriptions périmées passaient sous « ✅ registre
        # cohérent » : `--check` ne comparait que la présence et `export`. Un
        # champ qui dérive doit rougir, ET être nommé — un rouge muet renvoie à
        # un diff à la main, c'est-à-dire à rien.
        def check() -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, str(OUTILS / "agent_registry.py"),
                                   "--brain", str(base), "--check"],
                                  capture_output=True, text=True)

        def section(sortie: str, titre: str) -> list[str]:
            """Les lignes d'une section du rapport, de son titre à la ligne vide."""
            lignes, dedans = [], False
            for l in sortie.splitlines():
                if l.startswith(titre):
                    dedans = True
                elif dedans and not l.strip():
                    break
                elif dedans:
                    lignes.append(l)
            return lignes

        def en_retard(agent: str, champ: str, avant: str, apres: str) -> int:
            assert avant in genere, f"témoin mal posé : {avant!r} absent du généré"
            catalogue.write_text(genere.replace(avant, apres, 1), encoding="utf-8")
            r = check()
            catalogue.write_text(genere, encoding="utf-8")
            nomme = any(agent in l and champ in l
                        for l in section(r.stdout, "CATALOGUE EN RETARD"))
            # Le code d'abord ; s'il rougit sans nommer, c'est un demi-contrôle.
            return r.returncode if nomme or r.returncode == 0 else 2

        garantie("registre / une description périmée",
                 en_retard("coach", "description",
                           "description: null", "description: ancienne"), 1)
        garantie("registre / un statut périmé",
                 en_retard("coach", "status", "status: active", "status: draft"), 1)
        garantie("registre / une classification périmée",
                 en_retard("coach", "classification",
                           "classification: programme", "classification: prive"), 1)
        garantie("registre / régénéré à l'identique",
                 joue("agent_registry.py", base, "--check"), 0)

        # Hors catalogue : contre le catalogue RÉGÉNÉRÉ, pas l'original. Écrit à
        # la main, l'original rend déjà 1 à lui seul depuis le 29/09 — la garantie
        # ne pouvait plus tomber : un mutant qui éteignait la section HORS
        # CATALOGUE la laissait verte (verdict de l'orchestrator, PR #86). Et le
        # nom doit sortir SOUS ce titre : ajouter `dofus` change aussi `counts`,
        # un rouge que l'en-tête suffirait à produire.
        (base / "agents" / "games").mkdir()
        (base / "agents" / "games" / "dofus.md").write_text(
            "---\nname: dofus\nbrain:\n  scope: personal\n---\n", encoding="utf-8")
        r = check()
        nomme = any("dofus" in l for l in section(r.stdout, "HORS CATALOGUE"))
        garantie("registre / agent hors catalogue",
                 r.returncode if nomme or r.returncode == 0 else 2, 1)
        import shutil
        shutil.rmtree(base / "agents" / "games")

        # Entrée orpheline et désaccord `export` : les deux autres refus de
        # `--check`, que rien n'éprouvait. Même exigence que ci-dessus :
        # le code 1 ne suffit pas — retirer un agent change `counts`, ajouter
        # `export` au catalogue est un champ en retard ; l'un ou l'autre rougit
        # sans la section. Le nom doit sortir SOUS le titre de la sienne.
        #
        # Orpheline : un agent réellement régénéré dans le catalogue, puis dont
        # le fichier disparaît — le catalogue le nomme encore.
        fantome = base / "agents" / "fantome.md"
        fantome.write_text("---\nname: fantome\ntype: agent\nstatus: active\n"
                           "brain:\n  scope: kernel\n---\n", encoding="utf-8")
        garantie("registre / --emit avec l'agent témoin",
                 joue("agent_registry.py", base, "--emit", str(catalogue)), 0)
        fantome.unlink()
        r = check()
        nomme = any("fantome" in l for l in section(r.stdout, "ENTRÉES ORPHELINES"))
        garantie("registre / entrée orpheline",
                 r.returncode if nomme or r.returncode == 0 else 2, 1)

        # Désaccord `export` : `diff_against_catalog` ne compare que si le
        # catalogue porte un BOOLÉEN, et le frontmatter aussi. On écrit les deux,
        # contraires, sur un agent présent des deux côtés.
        exporte = base / "agents" / "exporte.md"
        exporte.write_text("---\nname: exporte\ntype: agent\nstatus: active\n"
                           "brain:\n  scope: kernel\n---\n", encoding="utf-8")
        garantie("registre / --emit avec l'agent exporté",
                 joue("agent_registry.py", base, "--emit", str(catalogue)), 0)
        avec_exporte = catalogue.read_text(encoding="utf-8")
        assert "- id: exporte\n" in avec_exporte, "témoin mal posé : entrée absente"
        catalogue.write_text(avec_exporte.replace(
            "- id: exporte\n", "- id: exporte\n  export: true\n", 1), encoding="utf-8")
        exporte.write_text("---\nname: exporte\ntype: agent\nstatus: active\n"
                           "brain:\n  scope: kernel\n  export: false\n---\n",
                           encoding="utf-8")
        r = check()
        nomme = any("exporte" in l
                    for l in section(r.stdout, "DÉSACCORD `export`"))
        garantie("registre / désaccord export",
                 r.returncode if nomme or r.returncode == 0 else 2, 1)
        exporte.unlink()
        catalogue.write_text(catalogue_original, encoding="utf-8")

        # ── registre → base : un statut rangé n'arrête plus l'écriture ─────
        # Le 28/09, `--apply` s'est arrêté au milieu de la table sur
        # `status: retired` — une valeur que la colonne ENUM refuse.
        spec = importlib.util.spec_from_file_location("agent_registry", OUTILS / "agent_registry.py")
        ar = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ar)
        colonne = {"active", "stable", "draft", "deprecated"}
        garantie("registre / un statut rangé entre dans la colonne",
                 0 if not ar.hors_enum({"diagram-scribe": {"status": ar.statut_db("retired")}},
                                       colonne) else 1, 0)
        garantie("registre / un statut inconnu est refusé avant d'écrire",
                 1 if ar.hors_enum({"x": {"status": "abandonne"}}, colonne) else 0, 1)

        # ── isolation : l'exemption de KERNEL.md est-elle bornée ? ─────────
        #
        # KERNEL.md énonce les motifs interdits en exemple : le fichier qui
        # définit l'interdit contient l'interdit. Une exemption a été posée le
        # 04/09 pour ça — bornée aux lignes du bloc, jamais au fichier.
        # Une exemption qu'on ne vérifie pas devient un trou permanent : ces
        # trois garanties sont exactement ce qui l'en empêche.
        # Le contrôle ne regarde PAS `KERNEL.md` à la racine du brain : sa
        # portée est `agents/` plus `brain-template/`, c'est-à-dire ce qui part
        # réellement. Le témoin pose donc le fichier là où le scan passe — sinon
        # il mesurerait un chemin que personne n'emprunte. Mesuré le 04/09 : la
        # première version de ce témoin restait verte pour cette seule raison.
        (base / "brain-template").mkdir(exist_ok=True)
        kernel = base / "brain-template" / "KERNEL.md"
        kernel.write_text("# KERNEL.md\n", encoding="utf-8")
        vrai_kernel = kernel.read_text(encoding="utf-8")
        bloc = (
            "# KERNEL.md\n\n**Règles d'isolation :**\n\n"
            "```\n"
            "INTERDIT dans agents/ distribuables :\n"
            "  - Chemin machine absolu hardcodé (/home/<user>/..., /root/...)\n"
            "  - toolkit/private/ — patterns privés non distribués\n"
            "  - require:/load:/source: vers MYSECRETS ou zone:personal\n"
            "```\n"
        )
        kernel.write_text(bloc, encoding="utf-8")
        garantie("isolation / la règle n'est pas sa violation",
                 joue_bash("kernel-isolation-check.sh", base), 0)

        # Le même motif, hors du bloc : l'exemption ne doit pas le couvrir.
        kernel.write_text(bloc + "\nVoir toolkit/private/ pour le détail.\n",
                          encoding="utf-8")
        garantie("isolation / motif hors du bloc",
                 joue_bash("kernel-isolation-check.sh", base), 1)

        # Et le scan des chemins machine reste actif sur KERNEL.md, sans
        # exception : c'est la moitié de l'exemption qui n'a PAS été accordée.
        kernel.write_text(bloc + "\nLe brain vit dans " + "/home/" + "quelquun/Dev/Brain.\n",
                          encoding="utf-8")
        garantie("isolation / chemin machine dans KERNEL",
                 joue_bash("kernel-isolation-check.sh", base), 1)
        kernel.write_text(vrai_kernel, encoding="utf-8")

        # ── routes sous garde — ne au, 15/09 ────────────────────
        # `PATCH /bsi/claims/{sess_id}` etait la seule des huit routes
        # d'ecriture a ne pas appeler `_readonly_guard()`. Sur une instance
        # `prod` le garde laisse tout passer : le defaut ne se serait jamais
        # montre ici. Ces quatre garanties le rendent visible sans instance.
        moteur = base / "brain-engine"
        moteur.mkdir(exist_ok=True)
        serveur = moteur / "server.py"
        conforme = (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n\n"
            "def _readonly_guard():\n"
            "    raise RuntimeError('mode')\n\n"
            "@app.post('/ecrit')\n"
            "def ecrit():\n"
            "    _readonly_guard()\n"
            "    return 1\n\n"
            "@app.get('/lit')\n"
            "def lit():\n"
            "    return 2\n"
        )
        serveur.write_text(conforme, encoding="utf-8")
        garantie("routes / serveur conforme",
                 joue("routes_sous_garde.py", base), 0)

        # Une route d'ecriture qui oublie le garde — le defaut d'origine.
        serveur.write_text(conforme.replace("    _readonly_guard()\n", ""),
                           encoding="utf-8")
        garantie("routes / garde oubliee",
                 joue("routes_sous_garde.py", base), 1)

        # 🔴 Le garde SUPPRIME. Sans cette garantie, un serveur qui l'aurait
        # retire passerait au vert : zero route fautive, parce que la regle
        # n'existe plus. Un temoin pris la ou la chose ne peut pas exister
        # compte zero sur zero.
        serveur.write_text(
            conforme.replace("def _readonly_guard():\n"
                             "    raise RuntimeError('mode')\n\n", ""),
            encoding="utf-8")
        garantie("routes / garde disparu",
                 joue("routes_sous_garde.py", base), 1)

        # Le nom ecrit en COMMENTAIRE seulement. Un outil qui cherche le motif
        # dans du texte compterait cette route comme gardee — c'est la lecon
        # des quatre outils repris le 11/09, eprouvee ici au lieu d'etre crue.
        serveur.write_text(
            conforme.replace("    _readonly_guard()\n",
                             "    # _readonly_guard() : a rebrancher un jour\n"),
            encoding="utf-8")
        garantie("routes / garde en commentaire",
                 joue("routes_sous_garde.py", base), 1)

        # ── close-stale ferme-t-il sa liste ? — ne le 15/09 ──────────────
        # `cmd_close_stale` LISTE selon un critere et FERMAIT selon un autre :
        # le SELECT mesurait depuis l expiration, l UPDATE depuis l ouverture.
        # Une session touchee il y a cinq minutes n etait pas listee, et etait
        # fermee quand meme. Rien ne levait.
        bsi = base / "scripts" / "bsi-claim.sh"
        entete = "#!/usr/bin/env bash\npython3 - \"$@\" <<'PYEOF'\n"
        pied = "\nPYEOF\n"
        # 🔴 Le 16/09, le controle a ete etendu aux DEUX portes — le repli local
        # ET la route du moteur — et ce temoin est reste a l ancienne forme,
        # celle d une seule fonction portant tout le SQL. Resultat : la
        # garantie « ferme sa liste » attendait 0 et recevait 1, non parce que
        # le brain derivait, mais parce que le temoin decrivait un controle qui
        # n existait plus. Encore la famille des cinq defauts du 15-17/09 —
        # une bonne regle appliquee a un endroit et pas a son voisin immediat.
        # Le voisin, ici, c etait le temoin du controle lui-meme.
        repli = ("""def _fermer_stale_en_repli(ids):
    stale = db.query(\"\"\"
        SELECT sess_id FROM claims WHERE status = 'open'
          AND TIMESTAMPDIFF(HOUR, COALESCE(expires_at, opened_at), UTC_TIMESTAMP()) > 12
    \"\"\")
""")
        # La commande ne porte plus de SQL depuis la bascule : elle appelle.
        commande = ("""
def cmd_close_stale():
    r = par_le_moteur("POST", "/bsi/claims/close-stale", {})
    if r is None:
        _fermer_stale_en_repli([])
""")
        ferme_par_id = ("""    db.execute(\"\"\"
        UPDATE claims SET status = 'closed' WHERE status = 'open' AND sess_id IN (%s)
    \"\"\", tuple(ids))
""")
        ferme_par_horloge = ("""    db.execute(\"\"\"
        UPDATE claims SET status = 'closed' WHERE status = 'open'
          AND TIMESTAMPDIFF(HOUR, opened_at, UTC_TIMESTAMP()) > 12
    \"\"\")
""")

        def route(update: str, select: str | None = None) -> str:
            """La porte du moteur, montee separement du repli.

            Les deux portes se degradent independamment — c est tout l objet de
            l extension du 16/09. Les monter separement est ce qui permet de le
            prouver, deux cas plus bas.
            """
            s = select or """    stale = brain_db.query(\"\"\"
        SELECT sess_id FROM claims WHERE status = 'open'
          AND TIMESTAMPDIFF(HOUR, COALESCE(expires_at, opened_at), UTC_TIMESTAMP()) > 12
    \"\"\")
"""
            return ("def bsi_claims_close_stale():\n" + s
                    + update.replace("db.execute", "brain_db.execute"))

        def monte(bloc_repli: str, bloc_route: str) -> None:
            bsi.write_text(entete + bloc_repli + commande + pied, encoding="utf-8")
            serveur.write_text(bloc_route, encoding="utf-8")

        monte(repli + ferme_par_id, route(ferme_par_id))
        garantie("close-stale / ferme sa liste",
                 joue("close_stale_ferme_sa_liste.py", base), 0)

        # Le defaut d origine, cote repli : l UPDATE decide tout seul.
        monte(repli + ferme_par_horloge, route(ferme_par_id))
        garantie("close-stale / deux criteres",
                 joue("close_stale_ferme_sa_liste.py", base), 1)

        # 🔴 Le meme defaut, mais cote ROUTE — le repli restant sain. C est
        # exactement ce que le controle d avant le 16/09 laissait passer : la
        # regle etait tenue a la porte qu il regardait, et pas a l autre.
        monte(repli + ferme_par_id, route(ferme_par_horloge))
        garantie("close-stale / la route seule degrade",
                 joue("close_stale_ferme_sa_liste.py", base), 1)

        # 🔴 Et la porte du moteur ABSENTE. Sans cette garantie, supprimer la
        # route ferait passer le controle au vert : zero porte fautive, parce
        # qu il ne reste qu une porte. Un temoin pris la ou la chose ne peut
        # pas exister compte zero sur zero.
        monte(repli + ferme_par_id, "def rien():\n    pass\n")
        garantie("close-stale / la route disparue",
                 joue("close_stale_ferme_sa_liste.py", base), 1)

        # L autre facon d « accorder » les deux requetes : degrader la BONNE.
        # Un controle qui ne verifierait que l UPDATE laisserait passer ca, et
        # on aurait deux requetes d accord sur un critere faux.
        select_degrade = repli.replace("COALESCE(expires_at, opened_at)", "opened_at")
        monte(select_degrade + ferme_par_id, route(ferme_par_id))
        garantie("close-stale / le SELECT degrade",
                 joue("close_stale_ferme_sa_liste.py", base), 1)

        # 🔴 La commande qui reprend du SQL : la bascule defaite en silence.
        # Elle reecrirait en direct ce que la route est censee ecrire, et les
        # deux portes resteraient pourtant impeccables chacune de son cote.
        bsi.write_text(entete + repli + ferme_par_id + """
def cmd_close_stale():
    db.execute("UPDATE claims SET status = 'closed'")
""" + pied, encoding="utf-8")
        serveur.write_text(route(ferme_par_id), encoding="utf-8")
        garantie("close-stale / la commande reprend du SQL",
                 joue("close_stale_ferme_sa_liste.py", base), 1)

        # Et le heredoc introuvable : le motif d extraction ne mord plus.
        bsi.write_text("#!/usr/bin/env bash\necho rien\n", encoding="utf-8")
        garantie("close-stale / heredoc absent",
                 joue("close_stale_ferme_sa_liste.py", base), 1)

    # ── Les chiffres de la doc — ───────────────────────────────────
    #
    # Un brain jetable a UN doc, dans un depot git (l'outil ne relit que les
    # fichiers suivis). `--sans-programme` : le README de myeline ne doit pas
    # decider du verdict d'un brain fabrique.
    if _outils_presents("chiffres_de_la_doc.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-chiffres-") as tmp:
            base = Path(tmp)
            spec = importlib.util.spec_from_file_location(
                "chiffres", OUTILS / "chiffres_de_la_doc.py")
            chiffres = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(chiffres)
            reel = chiffres.MESURES["core.lignes_test"](base)

            doc = base / "NOTE.md"
            doc.write_text(f"{reel} lignes<!-- mesure: core.lignes_test -->\n",
                           encoding="utf-8")
            git_init(base)
            garantie("chiffres / juste",
                     joue("chiffres_de_la_doc.py", base, "--sans-programme"), 0)

            doc.write_text(f"{reel - 5} lignes<!-- mesure: core.lignes_test -->\n",
                           encoding="utf-8")
            garantie("chiffres / faux",
                     joue("chiffres_de_la_doc.py", base, "--sans-programme"), 1)

            doc.write_text("12 choses<!-- mesure: core.inventee -->\n", encoding="utf-8")
            garantie("chiffres / mesure inconnue",
                     joue("chiffres_de_la_doc.py", base, "--sans-programme"), 1)

            # Un depot que git ne sait pas lire : un ECHEC, pas une abstention.
            # Relu en PR (myeline#31) : la premiere version rendait `SKIP`.
            # ⚠️ HORS de tout depot : un sous-dossier de `base` heriterait du git
            # parent, et le temoin ne prouverait rien — c'est ce que la premiere
            # version de ce test faisait.
            with tempfile.TemporaryDirectory(prefix="temoin-sans-git-") as ailleurs:
                sans_git = Path(ailleurs)
                (sans_git / "NOTE.md").write_text(
                    "3 lignes<!-- mesure: core.lignes_test -->\n", encoding="utf-8")
                garantie("chiffres / git illisible ⇒ rouge",
                         joue("chiffres_de_la_doc.py", sans_git, "--sans-programme"), 1)

            # Un marqueur d'EXEMPLE, faux, ne doit pas faire rougir.
            doc.write_text("Exemple : `3 lignes<!-- mesure: core.lignes_test -->`\n",
                           encoding="utf-8")
            garantie("chiffres / un exemple ne juge rien",
                     joue("chiffres_de_la_doc.py", base, "--sans-programme"), 0)
    else:
        print("  ⏭  Les chiffres de la doc / outil d'instance absent de ce brain")

    # ── Une vue n'est pas un oubli de versionner — ────────────────
    #
    # `agents/` déclaré `programme` avec `vue_de` : quand `noyau/agents/` existe,
    # il est une vue de liens, et il DOIT être ignoré par git. L'ancien contrôle
    # rougissait sur une vue ignorée (« déclaré versionné, gitignoré ») et ne
    # voyait pas une vue suivie.
    with tempfile.TemporaryDirectory(prefix="temoin-niveaux-vue-") as tmp:
        b = Path(tmp)
        (b / "NIVEAUX.yml").write_text(
            "entrees:\n  agents/:\n    niveau: programme\n"
            "    vue_de: [noyau/agents/, instance/agents/]\n  noyau/: programme\n",
            encoding="utf-8")
        (b / "noyau" / "agents").mkdir(parents=True)
        (b / "noyau" / "agents" / "coach.md").write_text("# coach\n", encoding="utf-8")
        (b / "agents").mkdir()
        (b / "agents" / "coach.md").symlink_to("../noyau/agents/coach.md")
        (b / ".gitignore").write_text("/agents/\n", encoding="utf-8")
        git_init(b)
        garantie("niveaux→git / une vue ignorée passe",
                 joue("niveaux_vs_git.py", b), 0)
        (b / ".gitignore").write_text("", encoding="utf-8")
        git_init(b)
        garantie("niveaux→git / une vue suivie rougit",
                 joue("niveaux_vs_git.py", b), 1)

    # ── Le BSI d'avant BRAIN-042 — ────────────────────────────────
    #
    # Le premier cas est l'incident : l'etape 7 de session-orchestrator d'avant
    # brain#84, recopiee. Un depot git (l'outil ne relit que les fichiers
    # suivis), sans `profil/` : un fork n'en a pas toujours, ce n'est pas rouge.
    with tempfile.TemporaryDirectory(prefix="temoin-bsi-v1-") as tmp:
        base = brain_jetable(Path(tmp))
        agent = base / "agents" / "session-orchestrator.md"
        agent.write_text(
            "7. BSI close claim\n"
            "   → Modifier claims/<sess-id>.yml : status: open → closed\n"
            "   git -C $BRAIN_ROOT add BRAIN-INDEX.md claims/<sess-id>.yml\n",
            encoding="utf-8")
        git_init(base)
        garantie("bsi-v1 / l'incident de l'etape 7",
                 joue("bsi_d_avant_042.py", base), 1)

        agent.write_text("`claims/` a disparu le 19/03. <!-- bsi-v1 -->\n"
                         "   → bash scripts/bsi-claim.sh close\n", encoding="utf-8")
        git_init(base)
        garantie("bsi-v1 / la citation declaree passe",
                 joue("bsi_d_avant_042.py", base), 0)

        # Un `agents/` qui est une VUE (ignorée par git, des liens vers
        # `noyau/agents/`) : l'incident, posé dans le noyau, rougit toujours.
        # Avec `ls-files agents/` seul, il n'était plus relu du tout.
        agent.unlink()
        (base / "noyau" / "agents").mkdir(parents=True, exist_ok=True)
        (base / "noyau" / "agents" / "session-orchestrator.md").write_text(
            "7. BSI close claim\n"
            "   → Modifier claims/<sess-id>.yml : status: open → closed\n", encoding="utf-8")
        agent.symlink_to("../noyau/agents/session-orchestrator.md")
        (base / ".gitignore").write_text("/agents/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(base), "rm", "-rq", "--cached", "agents"], capture_output=True)
        git_init(base)
        garantie("bsi-v1 / l'incident dans le noyau d'une vue rougit",
                 joue("bsi_d_avant_042.py", base), 1)
        # Le brain jetable sert aux cas suivants : il est rendu tel qu'il était.
        agent.unlink()
        shutil.rmtree(base / "noyau")
        (base / ".gitignore").unlink()
        agent.write_text("`claims/` a disparu le 19/03. <!-- bsi-v1 -->\n", encoding="utf-8")
        git_init(base)

        # Hors de tout depot : un echec, pas une abstention.
        with tempfile.TemporaryDirectory(prefix="temoin-sans-git-") as ailleurs:
            garantie("bsi-v1 / git illisible ⇒ rouge",
                     joue("bsi_d_avant_042.py", Path(ailleurs)), 1)

        # La racine de `profil/` (27/09) : une procédure vivante qui reprend
        # l'ancien BSI rougit ; un instantané qui se DÉCLARE, non. Le cas est
        # celui de `multi-session-procedure.md`, recopié.
        profil = base / "profil"
        profil.mkdir()
        procedure = profil / "procedure.md"
        procedure.write_text("2. Écrire un signal dans BRAIN-INDEX.md ## Signals :\n",
                             encoding="utf-8")
        git_init(profil)
        garantie("bsi-v1 / une procédure de la racine de profil rougit",
                 joue("bsi_d_avant_042.py", base), 1)
        procedure.write_text("> ⚠️ **Instantané non maintenu — étiqueté.**\n"
                             "2. Écrire un signal dans BRAIN-INDEX.md ## Signals :\n",
                             encoding="utf-8")
        git_init(profil)
        garantie("bsi-v1 / un instantané déclaré passe",
                 joue("bsi_d_avant_042.py", base), 0)

    # ── Les rapports de clôture, toutes formes — ─────────────────
    #
    # Premier cas : l'incident, recopié — une fiche en titre close le 27/09,
    # avec sa section « Réalisé » et sans ligne « Clôture ». Le contrôle ne
    # cherchait que la forme en puce : il rendait vert, code 0.
    if _outils_presents("cloture_backlog.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-cloture-") as tmp:
            base = Path(tmp)
            backlog = base / "workspace" / "backlog" / "myeline" / "backlog.md"
            backlog.parent.mkdir(parents=True)
            exemptions = base / "workspace" / ".cloture-sans-rapport"
            rapport = "> **Clôture** — mesuré : 0 → 1 · tenu par : un contrôle\n"

            def cloture(texte: str, nommees: str = "") -> int:
                backlog.write_text(texte, encoding="utf-8")
                exemptions.write_text(nommees, encoding="utf-8")
                return joue("cloture_backlog.py", base)

            incident = ("### [MY" "-158] En cours de session, rien ne relève la boîte — 27/09 — ✅ livré le 27/09\n\n"
                        "#### Réalisé — 27/09\n\n- le hook relève la boîte\n")
            garantie("clôture / titre clos sans rapport",
                     cloture(incident), 1)
            garantie("clôture / titre clos avec rapport",
                     cloture(incident.replace("\n\n#### Réalisé", "\n\n" + rapport + "\n#### Réalisé")), 0)
            garantie("clôture / puce à deux emoji vue",
                     cloture("- 🔒 ✅ ~~**[MY" "-8] Corriger.**~~ — **soldé.**\n  texte\n"), 1)
            garantie("clôture / fiche nommée passe",
                     cloture(incident, "MY" "-158 close avant la liste nommée\n"), 0)
            # Une fiche POURVUE : seule la ligne d'exemption peut rougir ici. Avec
            # l'incident nu, le cas rougissait deux fois — et passait même si la
            # ligne fautive avait été ignorée en silence.
            pourvue = "### [MY" "-158] x — ✅\n" + rapport
            garantie("clôture / pourvue et liste vide passe",
                     cloture(pourvue), 0)
            garantie("clôture / ancien seuil numérique ⇒ rouge",
                     cloture(pourvue, "57\n"), 1)
            garantie("clôture / exemption sans raison ⇒ rouge",
                     cloture(pourvue, "MY" "-12\n"), 1)
            garantie("clôture / nommée et pourvue ⇒ rouge",
                     cloture(pourvue, "MY" "-158 raison\n"), 1)

            # Une fiche reprise se lit dans sa DERNIÈRE entrée, dans les deux sens.
            garantie("clôture / reprise rouverte ⇒ pas close",
                     cloture("- ✅ ~~**[MY" "-68] x**~~\n  texte\n\n## [MY" "-68] la suite\n\nrien de clos\n"), 0)
            garantie("clôture / reprise close sans rapport",
                     cloture("### [MY" "-54] x\n\n" + rapport + "\n### [MY" "-54] suite — ✅ soldé\n\ntexte\n"), 1)
            # Le rapport de la voisine ne couvre pas une fiche : c'est la frontière.
            garantie("clôture / le rapport voisin ne compte pas",
                     cloture("### [MY" "-58] x — ✅\n\ntexte\n\n- **[MY" "-86] voisine**\n" + rapport), 1)

            # ── La source retirée ROUGIT ─────────────────────────────
            # « Un outil qui lit un fichier disparu mesure zéro et passe au vert. »
            # `cloture_backlog` rendait « rien mesuré », code 0.
            if _outils_presents("backlog_issues.py", "cloture_backlog.py"):
                backlog.unlink()
                garantie("clôture / backlog retiré ⇒ rouge", joue("cloture_backlog.py", base), 1)
                garantie("issues / backlog retiré ⇒ rouge", joue("backlog_issues.py", base), 1)
                # … et une fiche ÉCLATÉE suffit à le nourrir : la bascule ne casse rien.
                (backlog.parent / "MY" "-158.md").write_text(pourvue, encoding="utf-8")
                exemptions.write_text("", encoding="utf-8")
                garantie("clôture / fiche éclatée seule, pourvue ⇒ vert",
                         joue("cloture_backlog.py", base), 0)
                backlog.write_text(pourvue, encoding="utf-8")
                garantie("clôture / une fiche dans deux sources ⇒ rouge",
                         joue("cloture_backlog.py", base), 1)
            else:
                print("  ⏭  La source retirée ROUGIT / outil d'instance absent de ce brain")
    else:
        print("  ⏭  Les rapports de clôture, toutes formes / outil d'instance absent de ce brain")

    # ── Tenir le backlog d'un geste — le palier a de BRAIN-079 ─────────────
    #
    # `kanban.py tenir` enchaîne index, clôtures, issues. Le cas qui compte :
    # une fiche close SANS preuve arrête tout AVANT la forge — sinon
    # `backlog_issues --apply` fermerait l'issue d'une clôture non prouvée.
    # La forge n'est jamais touchée ici (`--sans-forge`).
    if _outils_presents("kanban.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-kanban-") as tmp:
            base = Path(tmp)
            dossier = base / "workspace" / "backlog" / "myeline"
            dossier.mkdir(parents=True)
            (base / "workspace" / ".cloture-sans-rapport").write_text("", encoding="utf-8")
            tete = '---\nfiche: MY' '-1\norigine: "témoin"\n---\n\n'

            def tenir(*args: str) -> int:
                return subprocess.run([sys.executable, str(OUTILS / "kanban.py"), "tenir",
                                       "--brain", str(base), "--sans-forge", *args],
                                      capture_output=True).returncode

            (dossier / "MY" "-1.md").write_text(tete + "### [MY" "-1] Une fiche ouverte\n", encoding="utf-8")
            garantie("kanban / l'index absent se régénère", tenir(), 0)
            garantie("kanban / l'index est écrit", 0 if (dossier / "backlog.md").is_file() else 1, 0)
            (dossier / "MY" "-2.md").write_text(tete.replace("MY" "-1", "MY" "-2") + "### [MY" "-2] Une autre\n",
                                             encoding="utf-8")
            avant = (dossier / "backlog.md").read_bytes()
            garantie("kanban / à blanc, un index en retard rougit", tenir("--a-blanc"), 1)
            garantie("kanban / à blanc n'écrit rien",
                     0 if (dossier / "backlog.md").read_bytes() == avant else 1, 0)
            (dossier / "MY" "-1.md").write_text(tete + "### [MY" "-1] Une fiche close — ✅ livré le 29/09\n",
                                             encoding="utf-8")
            garantie("kanban / une clôture sans preuve arrête avant la forge", tenir(), 1)
            (dossier / "MY" "-1.md").write_text(
                tete + "### [MY" "-1] Une fiche close — ✅ livré le 29/09\n\n"
                "> **Clôture** — mesuré : 0 → 1 · tenu par : un contrôle\n", encoding="utf-8")
            garantie("kanban / une clôture prouvée passe", tenir(), 0)
    else:
        print("  ⏭  Tenir le backlog d'un geste / outil d'instance absent de ce brain")

    # ── La zone projet : un autre préfixe, lu dans la fiche projet — ─
    #
    # Les outils ne connaissaient que `MY-<n>`. Un projet déclare son préfixe
    # dans `projets/<slug>.md` ; les exemptions `MY` de la liste commune ne le
    # concernent pas ; un projet SANS préfixe ne se devine pas, il rougit.
    if _outils_presents("kanban.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-zone-projet-") as tmp:
            base = Path(tmp)
            (base / "projets").mkdir()
            (base / "projets" / "demo.md").write_text(
                "---\nname: demo\nprefixe: DX\npalier: a\n---\n\n# Demo\n", encoding="utf-8")
            (base / "projets" / "muet.md").write_text("---\nname: muet\n---\n\n# Muet\n",
                                                      encoding="utf-8")
            for slug in ("demo", "muet"):
                (base / "workspace" / "backlog" / slug).mkdir(parents=True)
            (base / "workspace" / ".cloture-sans-rapport").write_text(
                "MY" "-12 une exemption d'un autre projet\n", encoding="utf-8")
            demo = base / "workspace" / "backlog" / "demo"
            (demo / "DX-1.md").write_text('---\nfiche: DX-1\norigine: "témoin"\n---\n\n'
                                          "### [DX-1] Une fiche d'un autre projet\n", encoding="utf-8")
            (base / "workspace" / "backlog" / "muet" / "MU-1.md").write_text(
                "### [MU-1] Un projet sans préfixe déclaré\n", encoding="utf-8")

            def tenir_projet(slug: str) -> int:
                return subprocess.run([sys.executable, str(OUTILS / "kanban.py"), "tenir",
                                       "--brain", str(base), "--projet", slug, "--sans-forge"],
                                      capture_output=True).returncode

            garantie("zone projet / un préfixe déclaré se tient", tenir_projet("demo"), 0)
            garantie("zone projet / son index nomme ses fiches",
                     int("[DX-1](DX-1.md)" in (demo / "backlog.md").read_text(encoding="utf-8")), 1)
            (demo / "DX-1.md").write_text('---\nfiche: DX-1\norigine: "témoin"\n---\n\n'
                                          "### [DX-1] Close — ✅ livré le 29/09\n", encoding="utf-8")
            garantie("zone projet / une clôture sans preuve rougit, sous son préfixe",
                     tenir_projet("demo"), 1)
            (demo / "DX-1.md").write_text('---\nfiche: DX-1\norigine: "témoin"\n---\n\n'
                                          "### [DX-1] Close — ✅ livré le 29/09\n\n"
                                          "> **Clôture** — mesuré : 0 → 1 · tenu par : rien\n",
                                          encoding="utf-8")
            garantie("zone projet / l'exemption MY ne se dit pas périmée ici", tenir_projet("demo"), 0)
            garantie("zone projet / sans `prefixe:`, rien ne se devine", tenir_projet("muet"), 1)
    else:
        print("  ⏭  La zone projet : un autre préfixe, lu dans la fich / outil d'instance absent de ce brain")

    # ── `--tous` : chaque liste, pas seulement `myeline` — ───────
    #
    # Le doctor ne jugeait l'index et les clôtures que de `myeline` : sept listes
    # portées, une seule regardée. Un brain jetable porte `myeline`, sain, et un
    # second projet en défaut. L'appel d'avant (`--projet myeline`) reste vert —
    # c'est l'angle mort ; `--tous` rougit.
    if _outils_presents("index_backlog.py", "cloture_backlog.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-tous-") as tmp:
            base = Path(tmp)
            (base / "projets").mkdir()
            for slug, pre in (("myeline", "MY"), ("demo", "DX")):
                (base / "projets" / f"{slug}.md").write_text(
                    f"---\nname: {slug}\nprefixe: {pre}\n---\n", encoding="utf-8")
                (base / "workspace" / "backlog" / slug).mkdir(parents=True)
            (base / "workspace" / "backlog" / "myeline" / ("MY" "-1.md")).write_text(
                "### [MY" "-1] Close — ✅ livré le 1/10\n\n> **Clôture** — mesuré : x · tenu par : y\n",
                encoding="utf-8")
            demo = base / "workspace" / "backlog" / "demo" / "DX-1.md"
            demo.write_text("### [DX-1] Ouverte\n", encoding="utf-8")
            joue("index_backlog.py", base, "--tous", "--ecrire")
            garantie("tous / les index écrits tiennent", joue("index_backlog.py", base, "--tous", "--check"), 0)
            demo.write_text("### [DX-1] Close — ✅ livré le 1/10\n", encoding="utf-8")
            garantie("tous / l'appel d'avant ne voit pas l'autre liste (index)",
                     joue("index_backlog.py", base, "--projet", "myeline", "--check"), 0)
            garantie("tous / l'index de l'autre liste rougit",
                     joue("index_backlog.py", base, "--tous", "--check"), 1)
            garantie("tous / l'appel d'avant ne voit pas l'autre liste (clôtures)",
                     joue("cloture_backlog.py", base, "--projet", "myeline"), 0)
            garantie("tous / une clôture sans rapport dans l'autre liste rougit",
                     joue("cloture_backlog.py", base, "--tous"), 1)
    else:
        print("  ⏭  `--tous`, chaque liste / outil d'instance absent de ce brain")

    # ── Les doublons de projets — §5 ─────────────────────────────
    #
    # Né dans le générateur du menu d'une instance ; il mesure le brain. Le
    # premier cas est le motif réel : une fiche COPIÉE puis renommée, qui garde
    # le dépôt et le `name:` de l'autre.
    with tempfile.TemporaryDirectory(prefix="temoin-doublons-") as tmp:
        base = Path(tmp)
        (base / "projets").mkdir()
        (base / "projets" / "mon-api.md").write_text(
            "---\nname: mon-api\nrepo: forge.exemple/moi/mon-api\nstatus: dev\n---\n", encoding="utf-8")
        (base / "projets" / "outil-cli.md").write_text(
            "---\nname: outil-cli\nstatus: dev\n---\n", encoding="utf-8")
        (base / "projets" / "outil-web.md").write_text(
            "---\nname: outil-web\nstatus: dev\n---\n", encoding="utf-8")
        garantie("doublons / des fiches distinctes et une famille passent",
                 joue("doublons_de_projets.py", base), 0)
        (base / "projets" / "api-v2.md").write_text(
            "---\nname: mon-api\nrepo: https://forge.exemple/moi/mon-api.git\nstatus: dev\n---\n",
            encoding="utf-8")
        garantie("doublons / une fiche copiée puis renommée rougit",
                 joue("doublons_de_projets.py", base), 1)

    # ── La naissance d'un projet, d'un geste ─────────────────────
    #
    # Un brain jetable qui porte les deux gabarits (copiés du brain jugé) et pas
    # de forge : le dépôt ne se vérifie pas, le reste oui. À blanc n'écrit rien ;
    # un slug ou un préfixe déjà pris refuse AVANT d'écrire.
    # Le gabarit de liste est celui du brain jugé : un fork ne le reçoit pas
    # (`projet.py` est un outil d'instance). Sans lui, ce bloc s'abstient — en
    # le disant, et SANS la ligne `SKIP`, qui ferait passer tout ce contrôle
    # pour abstenu aux yeux du doctor.
    if _outils_presents("projet.py"):
        gabarit_de_liste = VRAI_BRAIN / "workspace" / "backlog" / "_template" / "vision.md"
        if not gabarit_de_liste.is_file():
            print("  ⏭  naissance / pas de gabarit de liste (workspace/backlog/_template/) dans ce brain")
        else:
            with tempfile.TemporaryDirectory(prefix="temoin-naissance-") as tmp:
                base = Path(tmp)
                (base / "projets").mkdir()
                (base / "workspace" / "backlog" / "_template").mkdir(parents=True)
                (base / "projets" / "_template.md").write_text(
                    (VRAI_BRAIN / "projets" / "_template.md").read_text(encoding="utf-8"), encoding="utf-8")
                (base / "workspace" / "backlog" / "_template" / "vision.md").write_text(
                    (VRAI_BRAIN / "workspace" / "backlog" / "_template" / "vision.md").read_text(encoding="utf-8"),
                    encoding="utf-8")
                (base / "projets" / "ancien.md").write_text("---\nname: ancien\ntype: projet\nstatus: dev\nprefixe: AN\n---\n",
                                                            encoding="utf-8")

                def naitre(*args: str) -> int:
                    return subprocess.run([sys.executable, str(OUTILS / "projet.py"), "nouveau",
                                           *args, "--brain", str(base)], capture_output=True).returncode

                garantie("naissance / à blanc répond", naitre("neuf", "--prefixe", "NE"), 0)
                garantie("naissance / à blanc n'écrit rien",
                         int((base / "projets" / "neuf.md").exists()), 0)
                garantie("naissance / un préfixe déjà pris refuse", naitre("neuf", "--prefixe", "AN"), 1)
                garantie("naissance / un slug mal formé refuse", naitre("Neuf_Projet"), 1)
                garantie("naissance / elle crée, et la zone tient",
                         naitre("neuf", "--prefixe", "NE", "--ecrire"), 0)
                garantie("naissance / la fiche porte son préfixe",
                         int("prefixe: NE" in (base / "projets" / "neuf.md").read_text(encoding="utf-8")), 1)
                garantie("naissance / le dossier de liste existe",
                         int((base / "workspace" / "backlog" / "neuf" / "vision.md").is_file()), 1)
                garantie("naissance / un slug déjà pris refuse", naitre("neuf", "--ecrire"), 1)
    else:
        print("  ⏭  La naissance d'un projet, d'un geste / outil d'instance absent de ce brain")

    # ── La mort d'un projet, d'un geste ──────────────────────────
    #
    # Règle 4 du 29/09 : `archived` gèle la liste. Un brain jetable porte un
    # projet vivant, une fiche ouverte et une close. L'archivage met l'ouverte en
    # pause en AJOUTANT une entrée, ne touche pas la close, et la zone tient.
    if _outils_presents("projet.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-mort-") as tmp:
            base = Path(tmp)
            (base / "projets").mkdir()
            liste = base / "workspace" / "backlog" / "vivant"
            liste.mkdir(parents=True)
            (base / "projets" / "vivant.md").write_text(
                "---\nname: vivant\ntype: projet\nstatus: dev\nprefixe: VI\npalier: a\n---\n\n# Vivant\n",
                encoding="utf-8")
            (liste / "VI-1.md").write_text("### [VI-1] Une fiche ouverte\n\nSon texte.\n",
                                          encoding="utf-8")
            close = ("### [VI-2] Une fiche close — ✅ livré le 1/10\n\n"
                     "> **Clôture** — mesuré : x · tenu par : y\n")
            (liste / "VI-2.md").write_text(close, encoding="utf-8")

            def mourir(*args: str) -> int:
                return subprocess.run([sys.executable, str(OUTILS / "projet.py"), "archiver",
                                       *args, "--brain", str(base)], capture_output=True).returncode

            def statut() -> str:
                return (base / "projets" / "vivant.md").read_text(encoding="utf-8")

            garantie("mort / à blanc répond", mourir("vivant"), 0)
            garantie("mort / à blanc n'écrit rien", int("status: dev" in statut()), 1)
            garantie("mort / un projet sans fiche refuse", mourir("fantome", "--ecrire"), 1)
            garantie("mort / elle archive, et la zone tient", mourir("vivant", "--ecrire"), 0)
            garantie("mort / la fiche projet dit archived", int("status: archived" in statut()), 1)
            garantie("mort / l'ouverte passe en pause",
                     int("⏸️ projet archivé" in (liste / "VI-1.md").read_text(encoding="utf-8")), 1)
            garantie("mort / l'ouverte garde son texte",
                     int("Son texte." in (liste / "VI-1.md").read_text(encoding="utf-8")), 1)
            garantie("mort / la close n'est pas touchée",
                     int((liste / "VI-2.md").read_text(encoding="utf-8") == close), 1)
            garantie("mort / déjà archivé refuse", mourir("vivant", "--ecrire"), 1)
            # Le contrôle de la zone voit ce qu'archiver répare : la même liste,
            # rouverte à la main sous un projet archivé, rougit.
            (liste / "VI-3.md").write_text("### [VI-3] Rouverte à la main\n", encoding="utf-8")
            garantie("mort / une fiche ouverte sous un projet archivé rougit la zone",
                     joue("zone_projet.py", base), 1)
    else:
        print("  ⏭  La mort d'un projet, d'un geste / outil d'instance absent de ce brain")

    # ── L'éclatement et son index — ───────────────────────────────
    #
    # Un backlog jetable qui porte les formes vraies : une puce close, un titre
    # ouvert dont un bloc de code contient un `#` (l'incident du 27/09), et du
    # récit entre les deux. L'éclatement ne doit RIEN perdre.
    if _outils_presents("eclater_backlog.py", "index_backlog.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-eclater-") as tmp:
            base = Path(tmp)
            dossier = base / "workspace" / "backlog" / "myeline"
            dossier.mkdir(parents=True)
            monolithe = ("# Myéline — Backlog\n\n## J-2 — Le CORE\n\n"
                         "- ✅ ~~**[MY" "-4] Câbler la primitive d'écriture.**~~ — soldé\n"
                         "  une mesure qui ne doit pas se perdre en chemin\n\n"
                         "## Émergé le 03/09 — un récit daté\n\n"
                         "Un paragraphe de récit, qui n'appartient à aucune fiche.\n\n"
                         "### [MY" "-148] Le garde de zone s'est éteint\n\n```\n"
                         "#   pre-commit  → refuse une écriture hors de la zone\n```\n\n"
                         "#### La suite de la fiche, après le bloc de code\n")
            (dossier / "backlog.md").write_text(monolithe, encoding="utf-8")
            garantie("index / monolithe ⇒ abstention",
                     joue("index_backlog.py", base, "--check"), 0)
            garantie("éclater / écrit", joue("eclater_backlog.py", base, "--ecrire"), 0)
            corpus = "\n".join(p.read_text(encoding="utf-8") for p in dossier.glob("*.md"))
            perdues = [l for l in monolithe.splitlines() if l.strip() and l not in corpus]
            garantie("éclater / aucune ligne perdue", len(perdues), 0)
            garantie("éclater / la fiche garde son bloc de code",
                     int("après le bloc de code" in (dossier / "MY" "-148.md").read_text(encoding="utf-8")), 1)
            garantie("index / à jour après l'éclatement",
                     joue("index_backlog.py", base, "--check"), 0)
            # Le lien vers `chronique.md` ne s'écrit que si elle existe — il
            # était écrit dans tous les index : 5 liens morts le 1/10.
            index = dossier / "backlog.md"
            (dossier / "chronique.md").rename(dossier / "chronique.bak")
            joue("index_backlog.py", base, "--ecrire")
            garantie("index / sans chronique, aucun lien vers elle",
                     int("](chronique.md)" in index.read_text(encoding="utf-8")), 0)
            (dossier / "chronique.bak").rename(dossier / "chronique.md")
            joue("index_backlog.py", base, "--ecrire")
            garantie("index / avec chronique, le lien",
                     int("](chronique.md)" in index.read_text(encoding="utf-8")), 1)
            fiche = dossier / "MY" "-148.md"
            fiche.write_text(fiche.read_text(encoding="utf-8").replace(
                "### [MY" "-148] Le garde", "### [MY" "-148] ✅ Le garde"), encoding="utf-8")
            garantie("index / fiche changée, index pas régénéré ⇒ rouge",
                     joue("index_backlog.py", base, "--check"), 1)
            garantie("éclater / ne se rejoue pas", joue("eclater_backlog.py", base, "--ecrire"), 1)
    else:
        print("  ⏭  L'éclatement et son index / outil d'instance absent de ce brain")

    # ── L'index des décisions se génère depuis les ADR — ───────────
    #
    # Écrit à la main, il s'était arrêté à 052 quand le répertoire allait à 079,
    # et disait « actives » trois ADR remplacées. Le cas qui compte : deux
    # fichiers portent le numéro 033 (`033` et `033a`) — les deux doivent sortir.
    if _outils_presents("index_decisions.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-decisions-") as tmp:
            base = Path(tmp)
            garantie("décisions / sans satellite profil ⇒ abstention",
                     joue("index_decisions.py", base, "--check"), 0)
            dossier = base / "profil" / "decisions"
            dossier.mkdir(parents=True)
            adr = lambda nom, corps: (dossier / nom).write_text(corps, encoding="utf-8")
            adr("BRAIN-033-langue.md", "---\nstatus: accepted\ndate: 2026-03-18\n---\n\n# BRAIN-033 — Langue\n")
            adr("BRAIN-033a-zones.md", "---\nstatus: accepted\ndate: 2026-03-18\ntitle: Zones\n---\n")
            adr("BRAIN-022-open-core.md", "---\nstatus: superseded\nsuperseded_by: BRAIN-072\ndate: 2026-03-17\n---\n# Open-core\n")
            index = dossier / "README.md"
            index.write_text("# decisions\n\n| 001 | écrit à la main |\n", encoding="utf-8")
            garantie("décisions / sans marqueurs ⇒ refus d'écrire",
                     joue("index_decisions.py", base, "--ecrire"), 2)
            index.write_text("# decisions\n\n<!-- index:debut (généré par myeline/tools/index_decisions.py "
                             "— ne pas éditer à la main) -->\n<!-- index:fin -->\n\nnote à la main\n", encoding="utf-8")
            garantie("décisions / table vide ⇒ rouge", joue("index_decisions.py", base, "--check"), 1)
            garantie("décisions / écrit", joue("index_decisions.py", base, "--ecrire"), 0)
            rendu = index.read_text(encoding="utf-8")
            garantie("décisions / 033 ET 033a sortent",
                     int("[033](BRAIN-033-langue.md)" in rendu and "[033a](BRAIN-033a-zones.md)" in rendu), 1)
            garantie("décisions / une remplacée dit par qui", int("superseded → BRAIN-072" in rendu), 1)
            garantie("décisions / la note à la main survit", int("note à la main" in rendu), 1)
            garantie("décisions / à jour après écriture", joue("index_decisions.py", base, "--check"), 0)
            adr("BRAIN-033a-zones.md", "---\nstatus: superseded\ndate: 2026-03-18\ntitle: Zones\n---\n")
            garantie("décisions / statut changé, index pas régénéré ⇒ rouge",
                     joue("index_decisions.py", base, "--check"), 1)
    else:
        print("  ⏭  L'index des décisions se génère depuis les ADR / outil d'instance absent de ce brain")

    # ── Le doctor lit UNE clé de MYSECRETS, sans jamais l'exécuter ─────────
    #
    # « fondation du CORE » a besoin du jeton owner, que la session ne voit pas.
    # Tranché par l'owner le 30/09 : le doctor le lit lui-même. Le piège : un
    # `source` exécuterait chaque ligne — une valeur en `$(…)` tournerait.
    spec = importlib.util.spec_from_file_location("doctor_temoin", OUTILS / "brain_doctor.py")
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    with tempfile.TemporaryDirectory(prefix="temoin-jeton-") as tmp:
        base = Path(tmp)
        garantie("jeton / sans MYSECRETS ⇒ rien",
                 int(doctor.cle_de_mysecrets(base, "BRAIN_TOKEN_OWNER") is None), 1)
        (base / "brain-secrets").mkdir()
        piege = base / "EXECUTE"
        (base / "brain-secrets" / "MYSECRETS").write_text(
            "# BRAIN_TOKEN_OWNER=commentaire-pas-la-valeur\n"
            f"PIEGE=$(touch {piege})\n"
            'export BRAIN_TOKEN_OWNER="valeur-de-temoin"\n'
            "AUTRE=autre\n", encoding="utf-8")
        garantie("jeton / la clé, sans export ni guillemets",
                 int(doctor.cle_de_mysecrets(base, "BRAIN_TOKEN_OWNER") == "valeur-de-temoin"), 1)
        garantie("jeton / le fichier n'est jamais exécuté", int(piege.exists()), 0)
        garantie("jeton / une clé absente ⇒ rien",
                 int(doctor.cle_de_mysecrets(base, "INEXISTANTE") is None), 1)

    # ── Le daemon survit à une base injoignable — ─────────────────
    #
    # L'incident du 27/09, recopié : au redémarrage du PC, `brain-watch-local`
    # a interrogé Dolt dans la seconde où il démarrait, et `set -euo pipefail`
    # l'a tué sur `n=$(… | tail -1)` — avant la ligne qui devait « ne rien
    # conclure ». Ici, la vraie base est rendue injoignable par un port mort :
    # rien ne peut l'atteindre, ni en lecture ni en écriture. Le daemon doit
    # être ENCORE VIVANT quand le délai le coupe (124), pas mort de lui-même.
    # La branche du correctif s'éprouve par `TEMOIN_DAEMON` ; par défaut, le vrai.
    daemon = Path(os.environ.get("TEMOIN_DAEMON") or
                  VRAI_BRAIN / "scripts" / "brain-watch-local.sh")
    if daemon.exists():
        with tempfile.TemporaryDirectory(prefix="temoin-daemon-") as tmp:
            env = {**os.environ, "BRAIN_DOLT_PORT": "1", "BRAIN_WATCH_POLL": "1",
                   "BRAIN_WATCH_SILENCE": "1", "XDG_STATE_HOME": tmp}
            r = subprocess.run(["timeout", "6", "bash", str(daemon)],
                               capture_output=True, text=True, env=env)
            garantie("daemon / base injoignable ⇒ il survit", r.returncode, 124)

    # ── Les hooks git : installés par l'installateur, sages dans un worktree ─
    #   
    #
    # Un dépôt jetable fait des VRAIS scripts du brain. L'identité de session
    # est retirée et le moteur pointé sur un port mort : ni `touch`, ni synchro
    # ne peuvent atteindre la vraie base. Les incidents du 27/09 : un commit en
    # worktree créait un `brain.db` et synchronisait sur place ; une fusion en
    # avance rapide ne synchronisait rien.
    # `TEMOIN_SCRIPTS` éprouve une autre version des scripts — une branche, ou
    # celle d'avant le correctif pour voir le témoin tomber.
    scripts_vrais = Path(os.environ.get("TEMOIN_SCRIPTS") or
                         VRAI_BRAIN / "scripts")
    if (scripts_vrais / "install-brain-hooks.sh").exists():
        with tempfile.TemporaryDirectory(prefix="temoin-hooks-") as tmp:
            principal, arbre = Path(tmp) / "main", Path(tmp) / "wt"
            (principal / "brain-engine").mkdir(parents=True)
            (principal / "handoffs").mkdir()
            shutil.copytree(scripts_vrais, principal / "scripts",
                            ignore=shutil.ignore_patterns("__pycache__", "archive"))
            shutil.copy(VRAI_BRAIN / "KERNEL.md",
                        principal / "KERNEL.md")
            (principal / "handoffs" / "a.md").write_text("x\n", encoding="utf-8")
            # Le worktree doit avoir un brain-engine/ : c'est là que l'ancien
            # post-commit synchronisait, et écrivait son journal.
            (principal / "brain-engine" / "LISEZ-MOI").write_text("témoin\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
            env.update(BRAIN_PORT="1", BRAIN_DOLT_PORT="1")

            def git(*a, cwd=principal):
                return subprocess.run(["git", *a], cwd=cwd, env=env,
                                      capture_output=True, text=True).returncode

            git("init", "-q", "-b", "main")
            git("config", "user.email", "t@t"); git("config", "user.name", "t")
            git("add", "-A"); git("commit", "-q", "--no-verify", "-m", "scribe: init")
            installer = ["bash", "scripts/install-brain-hooks.sh"]
            subprocess.run(installer, cwd=principal, env=env, capture_output=True)
            cinq = ("pre-commit", "commit-msg", "post-commit", "post-merge", "post-rewrite")
            garantie("hooks / l'installateur écrit les cinq",
                     sum((principal / ".git" / "hooks" / h).is_file() for h in cinq), 5)
            garantie("hooks / --check les voit",
                     subprocess.run(installer + ["--check"], cwd=principal, env=env, capture_output=True).returncode, 0)
            git("worktree", "add", "-q", "-b", "pr", str(arbre))
            (arbre / "handoffs" / "a.md").write_text("y\n", encoding="utf-8")
            git("commit", "-qam", "scribe: dans le worktree", cwd=arbre)
            journal = principal / "brain-engine" / "sync.log"
            garantie("hooks / un commit en worktree ne synchronise pas sur place",
                     int((arbre / "brain-engine" / "sync.log").exists()), 0)
            garantie("hooks / … ni dans le principal",
                     int(journal.exists()), 0)
            git("merge", "-q", "--ff-only", "pr")
            garantie("hooks / une fusion en avance rapide synchronise",
                     int(journal.exists()), 1)
            # `git diff HEAD~1` seul compare au DISQUE : un handoff modifié et
            # non commité — celui d'une autre session — déclenchait la synchro
            # pour un commit qui n'en touchait aucun.
            journal.unlink()
            (principal / "handoffs" / "a.md").write_text("en cours\n", encoding="utf-8")
            (principal / "autre.txt").write_text("z\n", encoding="utf-8")
            git("add", "autre.txt"); git("commit", "-q", "-m", "scribe: autre chose")
            garantie("hooks / un handoff non commité ne déclenche rien",
                     int(journal.exists()), 0)
            git("checkout", "-q", "--", "handoffs/a.md")
            # Avec `pull.rebase=true`, un `pull` DIVERGENT rebase : ni post-merge
            # ni post-commit ne voient l'amont. Le handoff d'une PR fusionnée
            # sur la forge restait hors de la base.
            amont, voisin = Path(tmp) / "amont.git", Path(tmp) / "voisin"
            subprocess.run(["git", "clone", "-q", "--bare", str(principal), str(amont)],
                           env=env, capture_output=True)
            git("remote", "add", "origin", str(amont)); git("fetch", "-q", "origin")
            git("branch", "-q", "-u", "origin/main"); git("config", "pull.rebase", "true")
            subprocess.run(["git", "clone", "-q", str(amont), str(voisin)], env=env, capture_output=True)
            (voisin / "handoffs" / "b.md").write_text("de la forge\n", encoding="utf-8")
            for c in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                      ["add", "handoffs/b.md"], ["commit", "-q", "--no-verify", "-m", "scribe: b"],
                      ["push", "-q"]):
                git(*c, cwd=voisin)
            (principal / "autre.txt").write_text("zz\n", encoding="utf-8")
            git("commit", "-qam", "scribe: local")
            if journal.exists():
                journal.unlink()
            git("pull", "-q")
            garantie("hooks / le pull divergent a bien rebasé",
                     int((principal / "handoffs" / "b.md").exists()), 1)
            garantie("hooks / un pull divergent synchronise l'amont",
                     int(journal.exists()), 1)
            (principal / ".git" / "hooks" / "commit-msg").unlink()
            garantie("hooks / un hook manquant ⇒ --check rouge",
                     subprocess.run(installer + ["--check"], cwd=principal, env=env,
                                    capture_output=True).returncode, 1)
            # Le jetable n'a pas de base : le garde y est aveugle, et le contrôle
            # doit le DIRE — même quand les hooks sont en place.
            subprocess.run(installer, cwd=principal, env=env, capture_output=True)
            # Seulement là où il y a un garde de zone : un fork ne le reçoit pas,
            # et `hooks_installes` dit alors, à juste titre, qu'il n'y a rien à
            # joindre.
            if (VRAI_BRAIN / "scripts" / "hooks" / "pre-commit-zone").is_file():
                garantie("hooks / garde aveugle ⇒ contrôle rouge",
                         joue("hooks_installes.py", principal), 1)
            else:
                print("  ⏭  hooks / garde aveugle : pas de garde de zone dans ce brain")

    # ── Les jetons du moteur en service — ───────────────────────────
    #
    # Le juge est pur : on lui donne ce que systemd a dû charger et les NOMS reçus.
    # Le cas rouge est le danger de la fiche ; le cas « absent et facultatif » est
    # le laptop réel, qu'un premier jet jugeait « ouvert » à tort (2/10).
    if _outils_presents("jetons_en_service.py"):
        import importlib.util as _iu
        _spec = _iu.spec_from_file_location("jetons_en_service", OUTILS / "jetons_en_service.py")
        _j = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(_j)
        garantie("jetons / MYSECRETS chargé, jeton reçu",
                 0 if _j.juger("brain-engine-local.service", True, {"BRAIN_TOKEN_OWNER"})[0] == "ok" else 1, 0)
        garantie("jetons / MYSECRETS présent, jeton absent : rouge",
                 1 if _j.juger("brain-engine-local.service", True, {"PATH"})[0] == "rouge" else 0, 1)
        garantie("jetons / le MCP se contente de BRAIN_TOKEN",
                 0 if _j.juger("brain-mcp.service", True, {"BRAIN_TOKEN"})[0] == "ok" else 1, 0)
    else:
        print("  ⏭  Les jetons du moteur en service / outil d'instance absent de ce brain")
    # ── Une abstention dit sa cause — ───────────────────────────────
    sys.path.insert(0, str(OUTILS.parent))
    from core.tests import pourquoi_abstenue as _pourquoi
    _p = _pourquoi(ModuleNotFoundError("No module named 'pymysql'", name="pymysql"))
    garantie("abstention / un module absent n'est pas un service injoignable",
             0 if ("pymysql" in _p and "injoignable" not in _p) else 1, 0)
    garantie("abstention / une connexion refusée, elle, est injoignable",
             0 if "injoignable" in _pourquoi(ConnectionRefusedError(111, "refused")) else 1, 0)
    garantie("abstention / une autre erreur se dit telle quelle, sans accuser le service",
             0 if _pourquoi(ValueError("syntaxe SQL")).startswith("ValueError : syntaxe SQL") else 1, 0)
    # Les autres garanties des jetons, écrites après celles de l'abstention :
    # même condition.
    if _outils_presents("jetons_en_service.py"):
        garantie("jetons / facultatif et absent (le laptop) : pas rouge",
                 0 if _j.juger("brain-engine.service", False, set())[0] == "info" else 1, 0)
        # `%h` : le chemin d'une unité tel que systemd le lit, pas tel qu'il est écrit.
        import tempfile as _tf
        with _tf.TemporaryDirectory() as _h:
            _home = Path(_h)
            (_home / "brain-secrets").mkdir()
            (_home / "brain-secrets" / "MYSECRETS").write_text("")
            # Facultatif ET présent : seul un %h vraiment résolu le voit (l'obligatoire
            # serait vu même non résolu — la prudence de la règle ; il ne prouve rien ici).
            garantie("jetons / %h résolu : le fichier facultatif présent est vu",
                     0 if _j.charge_mysecrets(["EnvironmentFile=-%h/brain-secrets/MYSECRETS"], _home) else 1, 0)
            garantie("jetons / facultatif et absent, avec %h : pas chargé",
                     0 if not _j.charge_mysecrets(["EnvironmentFile=-%h/autre/MYSECRETS"], _home) else 1, 0)
            garantie("jetons / spécificateur inconnu, obligatoire : on ne s'en contente pas",
                     0 if _j.charge_mysecrets(["EnvironmentFile=/run/%U/MYSECRETS"], _home) else 1, 0)
    else:
        print("  ⏭  jetons (suite) / outil d'instance absent de ce brain")

    # ── Ce qui partirait au gabarit : le rendu, jugé — ──────────────
    #
    # Le contrôle juge le RENDU de la synchro ; la synchro elle-même (le rendu,
    # le retrait des étiquettes, le filet avant le push) a ses témoins dans la
    # suite du moteur (`TestSyncTemplate`). Ici, des rendus fabriqués. Les
    # motifs sont construits à l'exécution : ce fichier ne doit pas les porter.
    if _outils_presents("marqueurs_distribuables.py"):
        renvoi = "MY" + "-2"
        domaine = "demo." + "tetard" + "tek" + ".com"   # construit : ce fichier part au gabarit
        with tempfile.TemporaryDirectory(prefix="temoin-rendu-") as tmp:
            rendu = Path(tmp)
            (rendu / "agents").mkdir()
            (rendu / "agents" / "propre.md").write_text("rien à dire\n", encoding="utf-8")

            def juge() -> int:
                return subprocess.run([sys.executable, str(OUTILS / "marqueurs_distribuables.py"),
                                       "--rendu", str(rendu)], capture_output=True).returncode

            garantie("gabarit / un rendu propre passe", juge(), 0)
            (rendu / "agents" / "a.md").write_text(f"comme avant {renvoi}\n", encoding="utf-8")
            garantie("gabarit / un renvoi dans la phrase refuse", juge(), 1)
            (rendu / "agents" / "a.md").unlink()
            (rendu / "brain-engine").mkdir()
            (rendu / "brain-engine" / "db.py").write_text(f"# voir https://{domaine}\n", encoding="utf-8")
            garantie("gabarit / un domaine dans brain-engine refuse", juge(), 1)
            (rendu / "brain-engine" / "db.py").unlink()
            (rendu / "brain-compose.yml").write_text(f"notes: {domaine}\n", encoding="utf-8")
            garantie("gabarit / une exclusion nommée reste exclue", juge(), 0)
            (rendu / "brain-compose.yml").unlink()

            # Les NOMS de l'instance (2/10) : le cas est l'incident — un test qui
            # nommait un projet de l'owner, vu seulement par la synchro de la v2.4.3.
            # Hors du rendu : la liste ne part pas, et elle se jugerait elle-même.
            ailleurs = tempfile.TemporaryDirectory(prefix="temoin-noms-")
            liste = Path(ailleurs.name) / "noms.txt"
            liste.write_text("# les noms de l'instance\nprojet-temoin\n", encoding="utf-8")

            def juge_noms(avec_liste=True):
                args = ["--rendu", str(rendu)] + (["--liste", str(liste)] if avec_liste else [])
                return subprocess.run([sys.executable, str(OUTILS / "marqueurs_distribuables.py"), *args],
                                      capture_output=True).returncode

            (rendu / "brain-engine" / "test_x.py").write_text("f('vie/Projet-Temoin.md')\n", encoding="utf-8")
            garantie("gabarit / un nom de l'instance refuse, casse comprise", juge_noms(), 1)
            garantie("gabarit / sans liste, les noms s'abstiennent", juge_noms(False), 0)
            (rendu / "brain-engine" / "test_x.py").unlink()
            (rendu / "LICENSE.md").write_text("Copyright projet-temoin\n", encoding="utf-8")
            garantie("gabarit / LICENSE.md reste exclu des noms", juge_noms(), 0)
            ailleurs.cleanup()
    else:
        print("  ⏭  Ce qui partirait au gabarit : le rendu, jugé / outil d'instance absent de ce brain")

    # ── La doc du gabarit dit-elle vrai ? — ─────────────────────────
    #
    # Les règles vivent dans le brain (`scripts/docs-verite.py`) : le contrôle
    # ne les copie pas. Le témoin prend donc le brain de la machine — et
    # s'abstient, en le disant, tant que ce brain ne porte pas les scripts.
    if _outils_presents("doc_du_gabarit.py"):
        brain_outils = Path(os.environ.get("BRAIN_TEMOIN", Path.home() / "Dev" / "Brain"))
        if (brain_outils / "scripts" / "docs-verite.py").is_file():
            with tempfile.TemporaryDirectory(prefix="temoin-doc-") as tmp:
                g = Path(tmp)
                for rel, contenu in {"agents/debug.md": "# debug\n",
                                     "contexts/session-work.yml": "session_type: work\n",
                                     "docs/page.md": "```\nbrain boot work/mon-site\n```\n"}.items():
                    (g / rel).parent.mkdir(parents=True, exist_ok=True)
                    (g / rel).write_text(contenu, encoding="utf-8")

                def juge_doc() -> int:
                    return subprocess.run([sys.executable, str(OUTILS / "doc_du_gabarit.py"),
                                           "--rendu", str(g), "--outils", str(brain_outils)],
                                          capture_output=True).returncode

                garantie("doc / une page vraie passe", juge_doc(), 0)
                # L'incident, mot pour mot : une ligne de la doc publiée en v2.2.1.
                # Tel qu'il était publié : dans un bloc de code. `docs-verite` ne juge
                # `brain boot` qu'en code — en prose, « tape brain boot puis… » n'est
                # pas une commande (brain, relecture du 28/09).
                (g / "docs" / "page.md").write_text("```\nbrain boot mode debug/mon-projet\n```\n", encoding="utf-8")
                garantie("doc / un boot d'avant les sessions V2 refuse", juge_doc(), 1)
        else:
            print("  ⏭  doc / les scripts de doc ne sont pas dans le brain de la machine")
    else:
        print("  ⏭  La doc du gabarit dit-elle vrai ? / outil d'instance absent de ce brain")

    # ── Le wiki dit-il vrai ? — ─────────────────────────────────────
    #
    # Mêmes règles que la doc, jugées sur le wiki (`--wiki`), plus le CHANGELOG
    # généré. Un brain jetable : le compose, un contexte, les deux scripts du
    # brain de la machine — et une page. Le juge aveugle est le cas qui compte :
    # un `docs-verite` qui dit toujours vrai doit faire rougir le contrôle, pas
    # le rendre vert.
    if _outils_presents("wiki_juste.py"):
        if all((brain_outils / "scripts" / s).is_file() for s in ("docs-verite.py", "wiki-changelog.py")):
            with tempfile.TemporaryDirectory(prefix="temoin-wiki-") as tmp:
                b = Path(tmp)
                for rel, contenu in {"agents/debug.md": "# debug\n",
                                     "contexts/session-work.yml": "session_type: work\n",
                                     "brain-compose.yml": 'version: "1.0.0"\nchangelog:\n'
                                                          '  - version: "1.0.0"\n    date: "2026-09-29"\n'
                                                          '    notes: "premiere"\n',
                                     "wiki/Home.md": "[Guide](guide)\n\n`brain boot work/mon-site`\n",
                                     "wiki/guide.md": "# Guide\n",
                                     # le CHANGELOG généré y renvoie
                                     "wiki/versioning.md": "# Versions\n"}.items():
                    (b / rel).parent.mkdir(parents=True, exist_ok=True)
                    (b / rel).write_text(contenu, encoding="utf-8")
                (b / "scripts").mkdir()
                for script in ("docs-verite.py", "wiki-changelog.py"):
                    shutil.copy(brain_outils / "scripts" / script, b / "scripts" / script)
                subprocess.run([sys.executable, str(b / "scripts" / "wiki-changelog.py"),
                                "--brain", str(b), "--ecrire"], capture_output=True)

                def juge_wiki() -> int:
                    return subprocess.run([sys.executable, str(OUTILS / "wiki_juste.py"),
                                           "--brain", str(b)], capture_output=True).returncode

                garantie("wiki / un wiki vrai passe", juge_wiki(), 0)
                # L'incident du 29/09 : la syntaxe de boot d'avant les sessions V2,
                # dans une page du wiki.
                (b / "wiki" / "guide.md").write_text("```\nbrain boot mode work\n```\n", encoding="utf-8")
                garantie("wiki / un boot d'avant les sessions V2 refuse", juge_wiki(), 1)
                (b / "wiki" / "guide.md").write_text("# Guide\n", encoding="utf-8")
                with open(b / "brain-compose.yml", "a", encoding="utf-8") as f:
                    f.write('  - version: "1.0.1"\n    date: "2026-09-30"\n    notes: "suite"\n')
                garantie("wiki / un CHANGELOG en retard refuse", juge_wiki(), 1)
                subprocess.run([sys.executable, str(b / "scripts" / "wiki-changelog.py"),
                                "--brain", str(b), "--ecrire"], capture_output=True)
                (b / "scripts" / "docs-verite.py").write_text(
                    "import sys\nprint('rien de faux')\nsys.exit(0)\n", encoding="utf-8")
                garantie("wiki / un juge aveugle refuse, il ne rend pas un vert", juge_wiki(), 1)
        else:
            print("  ⏭  wiki / docs-verite.py ou wiki-changelog.py absent du brain de la machine")
    else:
        print("  ⏭  Le wiki dit-il vrai ? / outil d'instance absent de ce brain")

    # ── Les pages d'instance de la skill disent-elles vrai ? — ──────
    #
    # Même jugement que le wiki, sur `skills/brain/instance/*.md`, contre le
    # brain lui-même. Un brain jetable : un agent, un contexte, le compose,
    # `docs-verite.py` du brain de la machine — et une page d'instance. Le juge
    # aveugle est le cas qui compte : il doit faire rougir le contrôle.
    if _outils_presents("skill_instance_juste.py"):
        if (brain_outils / "scripts" / "docs-verite.py").is_file():
            with tempfile.TemporaryDirectory(prefix="temoin-skill-instance-") as tmp:
                b = Path(tmp)
                for rel, contenu in {"agents/debug.md": "# debug\n",
                                     "contexts/session-work.yml": "session_type: work\n",
                                     "brain-compose.yml": 'version: "1.0.0"\n',
                                     "runbooks/publier.md": "# Publier\n"}.items():
                    (b / rel).parent.mkdir(parents=True, exist_ok=True)
                    (b / rel).write_text(contenu, encoding="utf-8")
                (b / "scripts").mkdir()
                shutil.copy(brain_outils / "scripts" / "docs-verite.py", b / "scripts" / "docs-verite.py")

                def juge_instance() -> subprocess.CompletedProcess:
                    return subprocess.run([sys.executable, str(OUTILS / "skill_instance_juste.py"),
                                           "--brain", str(b)], capture_output=True, text=True)

                r = juge_instance()
                garantie("instance / sans skills/brain/instance/ : SKIP, sortie 0",
                         r.returncode if r.stdout.startswith("SKIP") else 1, 0)
                page = b / "skills" / "brain" / "instance" / "outils.md"
                page.parent.mkdir(parents=True)
                page.write_text("# Outils\n\n`runbooks/publier.md` fait foi.\n", encoding="utf-8")
                garantie("instance / une page vraie passe", juge_instance().returncode, 0)
                # L'incident du 29/09 : une page d'instance qui nomme un fichier
                # déplacé. Le contrôle rougit ET nomme la page et le chemin.
                page.write_text("# Outils\n\n`runbooks/publier-le-gabarit.md` fait foi.\n",
                                encoding="utf-8")
                r = juge_instance()
                nomme = ("skills/brain/instance/outils.md" in r.stdout
                         and "runbooks/publier-le-gabarit.md" in r.stdout)
                garantie("instance / un chemin disparu refuse, page et chemin nommés",
                         r.returncode if nomme else 0, 1)
                page.write_text("# Outils\n\n`runbooks/publier.md` fait foi.\n", encoding="utf-8")
                (b / "scripts" / "docs-verite.py").write_text(
                    "import sys\nprint('rien de faux')\nsys.exit(0)\n", encoding="utf-8")
                garantie("instance / un juge aveugle refuse, il ne rend pas un vert",
                         juge_instance().returncode, 1)
                # Un juge qui rougit sur tout sans dire QUOI : sortie 1, mais ni page ni
                # chemin. C'est l'auto-épreuve qui doit le refuser — sinon le rouge du
                # contrôle ne désignerait rien à corriger.
                (b / "scripts" / "docs-verite.py").write_text(
                    "import sys\nprint('faux')\nsys.exit(1)\n", encoding="utf-8")
                r = juge_instance()
                garantie("instance / un juge qui ne nomme rien tombe à l'auto-épreuve",
                         r.returncode if "PAS vue" in r.stdout else 0, 1)
        else:
            print("  ⏭  instance / docs-verite.py absent du brain de la machine")
    else:
        print("  ⏭  Les pages d'instance de la skill disent-elles vrai / outil d'instance absent de ce brain")

    # ── Le rattachement : ni les venvs, et les sources des hooks — ─
    #
    # Un script appelé SEULEMENT depuis un venv n'est rattaché à rien : les
    # venvs portaient ~9 200 fichiers relus pour chaque script (561 s). Et un
    # script appelé SEULEMENT par une source de hook versionnée est un automate :
    # depuis que les hooks installés ne sont que des lanceurs, leur corps vit
    # dans scripts/hooks/, sans extension — l'ancien corpus ne le lisait pas.
    # ⚠️ Les noms se CONSTRUISENT : écrits en entier, ils apparaîtraient dans ce
    # fichier même — et `tools/` est la zone « outil » du contrôle. La première
    # version se rattachait ainsi à elle-même, et passait dans les deux sens.
    venv_seul = "seul-dans-" + "le-venv.sh"
    par_hook = "appele-par-" + "un-hook.sh"
    with tempfile.TemporaryDirectory(prefix="temoin-rattachement-") as tmp:
        base = Path(tmp)
        (base / "scripts" / "hooks").mkdir(parents=True)
        (base / "agents").mkdir()
        (base / "brain-engine" / ".venv" / "lib").mkdir(parents=True)
        (base / ".git" / "hooks").mkdir(parents=True)
        (base / "scripts" / venv_seul).write_text("#!/bin/bash\necho x\n")
        (base / "brain-engine" / ".venv" / "lib" / "outil.py").write_text(
            f'import subprocess\nsubprocess.run(["bash", "scripts/{venv_seul}"])\n')
        garantie("rattachement / un appel depuis un venv ne rattache pas",
                 joue("rattachement_scripts.py", base), 1)
        (base / "scripts" / venv_seul).unlink()
        (base / "scripts" / par_hook).write_text("#!/bin/bash\necho x\n")
        (base / "scripts" / "hooks" / "post-merge").write_text(
            f'#!/usr/bin/env bash\nbash "$BRAIN_MAIN/scripts/{par_hook}" --quiet\n')
        garantie("rattachement / une source de hook rattache",
                 joue("rattachement_scripts.py", base), 0)

    # ── Le TTL des claims suit leur type — ──────────────────────────
    #
    # Une base SQLite jetable, le vrai `db.py` dirigé vers elle, les VRAIS
    # manifestes du brain. Le premier cas est l'incident : un claim `pilote`
    # ouvert à 4 h, le défaut, au lieu de ses 12.
    vrai_ttl = VRAI_BRAIN
    if (vrai_ttl / "brain-engine" / "schema.sql").exists():
        import sqlite3
        with tempfile.TemporaryDirectory(prefix="temoin-ttl-") as tmp:
            chemin = Path(tmp) / "brain.db"
            with sqlite3.connect(chemin) as cx:
                cx.executescript((vrai_ttl / "brain-engine" / "schema.sql").read_text(encoding="utf-8"))
                cx.execute("INSERT INTO claims (sess_id, type, scope, status, opened_at, ttl_hours) "
                           "VALUES ('sess-20260925-pilote-temoin', 'pilote', 'pilote/x', 'open', "
                           "'2026-09-25 10:00:00', 4)")
            env_ttl = {**os.environ, "BRAIN_DB_BACKEND": "sqlite", "BRAIN_DB_PATH": str(chemin)}

            def ttl() -> int:
                return subprocess.run(
                    [python_du_brain(vrai_ttl), str(OUTILS / "ttl_des_claims.py"), "--brain", str(vrai_ttl)],
                    capture_output=True, text=True, env=env_ttl).returncode

            garantie("ttl / l'incident : un pilote ouvert à 4 h", ttl(), 1)
            with sqlite3.connect(chemin) as cx:
                cx.execute("UPDATE claims SET ttl_hours = 12")
            garantie("ttl / le même à 12 h passe", ttl(), 0)
            with sqlite3.connect(chemin) as cx:
                cx.execute("UPDATE claims SET ttl_hours = 4, status = 'closed'")
            garantie("ttl / un claim FERMÉ n'est pas jugé", ttl(), 0)

    # ── L'archivage a tourne — ────────────────────────────────────
    #
    # Une base SQLite jetable, creee depuis le `schema.sql` du vrai brain, et
    # le vrai `db.py` dirige vers elle par l'environnement. Un claim ferme
    # ancien reste en table vivante : c'est l'incident des trois dimanches.
    vrai = VRAI_BRAIN
    if (vrai / "brain-engine" / "schema.sql").exists():
        import sqlite3
        with tempfile.TemporaryDirectory(prefix="temoin-archivage-") as tmp:
            chemin = Path(tmp) / "brain.db"
            with sqlite3.connect(chemin) as cx:
                cx.executescript((vrai / "brain-engine" / "schema.sql").read_text(encoding="utf-8"))
            env = {**os.environ, "BRAIN_DB_BACKEND": "sqlite", "BRAIN_DB_PATH": str(chemin)}

            def archivage() -> int:
                return subprocess.run(
                    [python_du_brain(vrai), str(OUTILS / "archivage_a_tourne.py"), "--brain", str(vrai)],
                    capture_output=True, text=True, env=env).returncode

            garantie("archivage / base a jour", archivage(), 0)
            with sqlite3.connect(chemin) as cx:
                cx.execute("INSERT INTO claims (sess_id, type, scope, status, opened_at, closed_at) "
                           "VALUES ('sess-20260801-1000-temoin', 'work', 'x', 'closed', "
                           "'2026-08-01 10:00:00', '2026-08-01 11:00:00')")
            garantie("archivage / un claim ferme reste au-dela de 37 j", archivage(), 1)

    # ── La vue des agents — ───────────────────────────────────────
    #
    # Un brain migré jetable : le noyau, une surcharge, la vue construite à la main
    # comme `brain vue` la pose. Le cas qui a fait naître le contrôle (3/10) : un
    # agent écrit dans la vue, que ni git ni `brain vue` ne voyaient.
    if _outils_presents("vue_juste.py"):
        with tempfile.TemporaryDirectory(prefix="temoin-vue-") as tmp:
            b = Path(tmp)
            for rel, texte in {"noyau/agents/coach.md": "le noyau\n",
                               "noyau/agents/api.md": "le noyau\n",
                               "instance/agents/coach.md": "la surcharge\n",
                               "agents/CATALOG.yml": "calculé\n"}.items():
                (b / rel).parent.mkdir(parents=True, exist_ok=True)
                (b / rel).write_text(texte, encoding="utf-8")
            vue = b / "agents"

            def poser() -> None:
                for nom, couche in (("coach.md", "instance"), ("api.md", "noyau")):
                    lien = vue / nom
                    if lien.is_symlink() or lien.exists():
                        lien.unlink()
                    lien.symlink_to(f"../{couche}/agents/{nom}")

            poser()
            garantie("vue / juste", joue("vue_juste.py", b), 0)
            (b / "instance" / "agents" / ".gitkeep").write_text("", encoding="utf-8")
            garantie("vue / un .gitkeep n'est pas un agent", joue("vue_juste.py", b), 0)
            git_init(b)
            (b / "noyau" / "agents" / "reste.md").write_text("retiré par le tronc\n", encoding="utf-8")
            (vue / "reste.md").symlink_to("../noyau/agents/reste.md")
            garantie("vue / un retrait resté dans noyau/", joue("vue_juste.py", b), 1)
            (vue / "reste.md").unlink()
            (b / "noyau" / "agents" / "reste.md").unlink()
            garantie("vue / retiré, juste à nouveau", joue("vue_juste.py", b), 0)
            (vue / "reviews" / "Projet").mkdir(parents=True)
            (vue / "reviews" / "Projet" / "debug-v1.md").write_text("une revue\n", encoding="utf-8")
            garantie("vue / les revues de l'instance sont des données", joue("vue_juste.py", b), 0)
            (vue / "zz.md").write_text("écrit dans la vue\n", encoding="utf-8")
            garantie("vue / l'incident : rien ne le fournit", joue("vue_juste.py", b), 1)
            (vue / "zz.md").unlink()
            (vue / "api.md").unlink()
            (vue / "api.md").write_text("un sed -i\n", encoding="utf-8")
            garantie("vue / un fichier réel masque", joue("vue_juste.py", b), 1)
            (vue / "api.md").unlink()
            garantie("vue / un lien absent", joue("vue_juste.py", b), 1)
            poser()
            (vue / "coach.md").unlink()
            (vue / "coach.md").symlink_to("../noyau/agents/coach.md")
            garantie("vue / la surcharge perdue", joue("vue_juste.py", b), 1)
            poser()
            (vue / "parti.md").symlink_to("../noyau/agents/parti.md")
            garantie("vue / un lien orphelin", joue("vue_juste.py", b), 1)
            (vue / "parti.md").unlink()
            (vue / "CATALOG.yml").unlink()
            garantie("vue / sans catalogue", joue("vue_juste.py", b), 1)
            (vue / "CATALOG.yml").write_text("calculé\n", encoding="utf-8")
            serve = VRAI_BRAIN / "brain-engine" / "serve.py"
            if serve.is_file() and os.geteuid() != 0:
                (b / "brain-engine").mkdir()
                (b / "brain-engine" / "serve.py").write_bytes(serve.read_bytes())
                (b / "brain-compose.yml").write_text(
                    "postures:\n  master:\n    kernel_write: true\n"
                    "  replica-nomad:\n    kernel_write: false\n", encoding="utf-8")
                (b / "brain-compose.local.yml").write_text(
                    "instances:\n  ici:\n    active: true\n    posture: replica-nomad\n",
                    encoding="utf-8")
                garantie("vue / un replica au noyau ouvert", joue("vue_juste.py", b), 1)
                noyau = b / "noyau"
                for p in sorted([noyau, *noyau.rglob("*")], key=lambda p: len(p.parts), reverse=True):
                    p.chmod(p.stat().st_mode & ~0o222)
                garantie("vue / le même, verrouillé", joue("vue_juste.py", b), 0)
                noyau.chmod(noyau.stat().st_mode | 0o200)
                garantie("vue / noyau/ lui-même ouvert", joue("vue_juste.py", b), 1)
                for p in [noyau, *noyau.rglob("*")]:
                    p.chmod(p.stat().st_mode | 0o200)
            shutil.rmtree(b / "noyau")
            garantie("vue / un brain à plat s'abstient", joue("vue_juste.py", b), 0)

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} garantie(s) tombée(s) : {', '.join(echecs)}")
        print("     Un contrôle qui ne sait plus refuser laisse passer ce qu'il")
        print("     est censé arrêter, et personne ne s'en aperçoit.\n")
        return 1
    print("  ✅ tous les contrôles refusent ce qu'ils doivent refuser\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
