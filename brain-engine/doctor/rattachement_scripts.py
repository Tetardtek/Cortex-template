#!/usr/bin/env python3
"""Qui appelle quoi, dans scripts/ ?

On veut savoir lesquels des scripts deviennent des sous-commandes du
binaire. Le backlog le dit lui-même : *« c'est littéralement, on ne peut
pas le faire sans savoir lesquels »*. Le binaire n'existe pas ; **savoir
lesquels**, si.

Le seul critère qui dise quelque chose sur le sort d'un script, c'est **ce qui
l'appelle**. Un script qu'aucun agent n'invoque n'a pas besoin d'interface
humaine ; un script qu'un cron déclenche n'en a jamais eu.

    python3 tools/rattachement_scripts.py --brain ~/Dev/Brain
    python3 tools/rattachement_scripts.py --brain ~/Dev/Brain --liste agent

── Ce que « appeler » veut dire, et pourquoi ça a demandé trois essais ──────

Le premier instrument cherchait le NOM du script dans les fichiers. Il a rendu
cinq scripts « appelés » qui ne l'étaient pas :

    ascension-challenges.py   cité dans viz_cache_*.json — un cache du RAG
    kernel-lock-gen.sh        cité dans « lancer d'abord : bash … » — un conseil
    wow-dbc-dump.py           cité dans un commentaire

Un nom dans un cache, un message d'aide ou un commentaire n'est pas un appel.
Le second essai a donc cherché une **invocation** — un interprète, un chemin
exécuté — en ignorant commentaires, `echo` et caches.

Le troisième a corrigé un angle mort inverse : `dolt-schema-gen.sh` paraissait
orphelin, alors que `brain_doctor.py` l'appelle. Le corpus s'arrêtait au dépôt
brain ; les outils de `myeline/tools/` en sont des appelants légitimes.

**Trois fois le même défaut, dans les deux sens** : un instrument qui répond à
côté de la question qu'on croit lui poser.

── Les catégories ──────────────────────────────────────────────────────────

    agent       un agent l'invoque          → candidat sous-commande
    outil       un contrôle myeline l'invoque
    automate    cron, hook git ou systemd   → pas d'interface humaine à prévoir
    script      un autre script l'invoque   → bibliothèque de fait
    programme   le moteur ou un contexte
    orphelin    personne                    → `ponctuel` si c'est voulu

Sortie 1 si un script orphelin ne se déclare pas `ponctuel` : c'est le seul cas
où la mesure ne peut pas trancher seule. Un orphelin a TROIS issues, pas deux :

    assumé    outillage personnel, voulu          → le déclarer `ponctuel`
    mort      plus rien ne l'appelle, plus utile  → le supprimer
    périmé    son besoin a disparu, et le lancer  → le supprimer — après avoir
              aujourd'hui NUIRAIT                   mesuré ce qu'il ferait

La troisième ne se voit pas dans le code : le 09/09, `codex-reset-userdb.sh`
aurait ramené une base de 16 tables à 6, et son propre garde-fou ne contrôlait
que les deux tables qui ne bougeaient pas. Déclarer `ponctuel` l'aurait gardé.
Un orphelin s'OUVRE avant de se déclarer.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Les venvs ne sont pas du brain : `.venv` et `.venv.popos` portaient ~9 200
# fichiers .py/.sh sous brain-engine/, relus pour chaque script — 1149 s pendant
# la migration Omarchy, 561 s au doctor du 27/09.
EXCLUS = re.compile(r"viz_cache|\.json$|/archive/|/__pycache__/|/\.git/"
                    r"|/\.?venv[^/]*/|/node_modules/")
SUFFIXES = (".sh", ".py", ".md", ".yml")
ORDRE = ("agent", "outil", "automate", "script", "programme", "orphelin")


def motif_appel(nom: str) -> re.Pattern:
    """Une INVOCATION, pas une mention : un interprète, ou un chemin exécuté."""
    n = re.escape(nom)
    return re.compile(
        rf"(?:^|[;&|]|\$\(|`|\bexec\s|\bbash\s|\bsh\s+|\bpython3?\s+|\bnohup\s)"
        rf"[^\n#]{{0,60}}?(?:scripts/)?{n}\b"
        rf"|[\"']scripts/{n}[\"']|[\"']{n}[\"']|\./{n}\b")


def sans_prose(texte: str) -> str:
    """Un commentaire ou un message à l'écran n'appelle rien."""
    return "\n".join(
        l for l in texte.splitlines()
        if not l.strip().startswith(("#", "//"))
        and not re.match(r"^\s*(echo|print|log|printf)\b", l.strip()))


def classer(brain: Path, outils: Path) -> list[tuple[str, int, str, bool]]:
    scripts = sorted(list((brain / "scripts").glob("*.sh"))
                     + list((brain / "scripts").glob("*.py")))
    cron = subprocess.run(["crontab", "-l"], capture_output=True,
                          text=True).stdout
    hooks = "".join(h.read_text(errors="replace")
                    for h in (brain / ".git" / "hooks").glob("*")
                    if h.is_file() and not h.name.endswith(".sample"))
    # Depuis le 27/09 un hook installé n'est qu'un LANCEUR : son corps vit dans
    # scripts/hooks/, versionné, sans extension — hors du corpus. Sans ces
    # lignes, tout ce qu'un hook appelle (brain-db-sync.sh, docs-inject.sh…)
    # serait devenu « orphelin » le jour où les hooks sont devenus versionnés.
    hooks += "".join(h.read_text(errors="replace")
                     for h in (brain / "scripts" / "hooks").glob("*")
                     if h.is_file() and not h.suffix and not h.name.startswith("."))
    timers = "".join(t.read_text(errors="replace") for t in
                     Path.home().glob(".config/systemd/user/*.service"))

    zones = {"agent": [brain / "agents"], "outil": [outils],
             "script": [brain / "scripts"],
             "programme": [brain / "brain-engine", brain / "contexts"]}
    corpus: dict[str, list[Path]] = {}
    for cat, chemins in zones.items():
        for z in chemins:
            if z.exists():
                corpus.setdefault(cat, []).extend(
                    p for p in z.rglob("*")
                    if p.is_file() and p.suffix in SUFFIXES
                    and not EXCLUS.search(str(p)))

    # Le corpus est LU UNE FOIS — il l'était une fois par script (~95).
    textes = {c: [(p, sans_prose(p.read_text(errors="replace"))) for p in ps]
              for c, ps in corpus.items()}

    resultat = []
    for s in scripts:
        texte = s.read_text(errors="replace")
        motif = motif_appel(s.name)
        cat = "orphelin"
        if any(motif.search(x) for x in (cron, hooks, timers)):
            cat = "automate"
        else:
            for c in ("agent", "outil", "script", "programme"):
                for p, contenu in textes.get(c, []):
                    if p.name == s.name:
                        continue
                    if motif.search(contenu):
                        cat = c
                        break
                if cat != "orphelin":
                    break
        resultat.append((cat, len(texte.splitlines()), s.name,
                         "brain-rattachement: ponctuel" in texte))
    return resultat


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--liste", choices=ORDRE, help="détaille une catégorie")
    args = p.parse_args()
    brain = args.brain.expanduser().resolve()
    outils = Path(__file__).resolve().parent

    lignes = classer(brain, outils)
    n, t = Counter(), Counter()
    for cat, taille, _, _ in lignes:
        n[cat] += 1
        t[cat] += taille

    print(f"\nRATTACHEMENT DES SCRIPTS — {len(lignes)} scripts · "
          f"{sum(t.values())} lignes\n")
    for cat in ORDRE:
        if n[cat]:
            marque = "  ← candidats sous-commandes" if cat == "agent" else ""
            print(f"  {cat:<11} {n[cat]:>3} · {t[cat]:>6} lignes{marque}")

    if args.liste:
        print(f"\n  ── {args.liste} ──")
        for cat, taille, nom, decl in sorted(lignes, key=lambda x: -x[1]):
            if cat == args.liste:
                print(f"     {nom:<36} {taille:>5} lignes"
                      f"{'  · déclaré ponctuel' if decl else ''}")

    nus = [(taille, nom) for cat, taille, nom, decl in lignes
           if cat == "orphelin" and not decl]
    if nus:
        print(f"\n  ❌ {len(nus)} orphelin(s) sans déclaration :")
        for taille, nom in sorted(nus, reverse=True):
            print(f"     {nom:<36} {taille:>5} lignes")
        print("\n     La mesure ne peut pas trancher seule. OUVRIR chaque script,")
        print("     et mesurer ce qu'il ferait AUJOURD'HUI — puis l'une des trois :")
        print("       assumé   outillage voulu  → en-tête :")
        print("                # brain-rattachement: ponctuel  # <pourquoi>")
        print("       mort     plus utile       → le supprimer")
        print("       périmé   son besoin a disparu et il NUIRAIT → le supprimer")
        print("     Déclarer sans ouvrir, c'est garder un périmé. Détail —,,.\n")
        return 1

    print(f"\n  ✅ tout orphelin se déclare — {sum(1 for c, _, _, d in lignes if d)}"
          f" `ponctuel`\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
