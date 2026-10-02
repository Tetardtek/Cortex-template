#!/usr/bin/env python3
"""Un handoff actif est-il encore attendu ?

Tranché par l'owner le 2/10 : `handoffs/` est versionné, pour une AUTRE session
qui reprendra ; `scratch/` est volatile, à la session en cours. Un handoff vit
donc entre deux sessions — puis il est repris (`consumed`) ou rangé
(`archived`). Rien ne le disait : le 2/10, 43 handoffs sur 45 étaient `active`,
et trois des quatre gardés après le tri dataient de plus d'une semaine.

    un statut hors de l'énumération    active | consumed | archived
    un handoff `active` de plus de     reprendre, ou le passer consumed/archived
      14 jours (seuil tranché le 2/10)

L'âge est celui du dernier commit du fichier : un handoff réécrit redevient
frais. Non suivi par git : sa date de modification. `_template.md` et `LATEST.md`
(la carte des chantiers, pas une passation) ne sont pas jugés.

Les candidats de `scratch/` (`scripts/scratch-nettoyable.py`) sont AFFICHÉS, pas
jugés : tranché le 2/10, un rouge de ménage à solder chaque mois ne dit rien
d'une dérive.

    python3 tools/handoffs_vivants.py --brain ~/Dev/Brain [--jours 14]

Il s'éprouve avant de juger. Sortie 1 si un handoff ne tient pas.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATUTS = {"active", "consumed", "archived"}
HORS_JUGEMENT = {"LATEST.md"}
SEUIL_JOURS = 14


def _statut(fichier: Path) -> str | None:
    texte = fichier.read_text(encoding="utf-8")
    if not texte.startswith("---\n"):
        return None
    fin = texte.find("\n---", 4)
    if fin < 0:
        return None
    import yaml
    try:
        meta = yaml.safe_load(texte[4:fin]) or {}
    except yaml.YAMLError:
        return None
    s = meta.get("status")
    return str(s) if s is not None else None


def _age_jours(brain: Path, fichier: Path, maintenant: float) -> float:
    r = subprocess.run(["git", "-C", str(brain), "log", "-1", "--format=%ct", "--",
                        str(fichier.relative_to(brain))], capture_output=True, text=True)
    quand = float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else fichier.stat().st_mtime
    return (maintenant - quand) / 86400


def juger(brain: Path, jours: int = SEUIL_JOURS, maintenant: float | None = None) -> tuple[list[str], int]:
    """(les défauts, le nombre de handoffs jugés)."""
    maintenant = time.time() if maintenant is None else maintenant
    dossier = Path(brain) / "handoffs"
    defauts, n = [], 0
    for f in sorted(dossier.glob("*.md")):
        if f.name.startswith("_") or f.name in HORS_JUGEMENT or f.name.upper() == "README.MD":
            continue
        n += 1
        s = _statut(f)
        if s not in STATUTS:
            defauts.append(f"handoffs/{f.name} : statut « {s} » — attendu "
                           f"{' | '.join(sorted(STATUTS))}")
            continue
        if s == "active":
            age = _age_jours(Path(brain), f, maintenant)
            if age > jours:
                defauts.append(f"handoffs/{f.name} : actif depuis {int(age)} j (seuil {jours}) — "
                               f"le reprendre, ou le passer consumed / archived")
    return defauts, n


def auto_epreuve() -> list[str]:
    """Chaque défaut, dans un dépôt jetable aux commits datés, doit être vu."""
    rates = []
    with tempfile.TemporaryDirectory(prefix="handoffs-") as tmp:
        b = Path(tmp)
        (b / "handoffs").mkdir()
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "init", "-q"], cwd=b, env=env, capture_output=True)
        maintenant = time.time()

        def commit(nom: str, statut: str | None, il_y_a: int) -> None:
            tete = f"status: {statut}          # active | consumed | archived\n" if statut else ""
            (b / "handoffs" / nom).write_text(f"---\nname: {nom}\n{tete}---\n", encoding="utf-8")
            date = f"@{int(maintenant - il_y_a * 86400)} +0000"
            subprocess.run(["git", "add", f"handoffs/{nom}"], cwd=b, env=env, capture_output=True)
            subprocess.run(["git", "commit", "-qm", nom], cwd=b, capture_output=True,
                           env={**env, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})

        # le témoin négatif : ce qui tient ne rougit pas
        commit("frais.md", "active", 3)
        commit("repris.md", "consumed", 60)
        commit("range.md", "archived", 90)
        commit("_template.md", "active", 200)
        commit("LATEST.md", "active", 200)
        defauts, n = juger(b, maintenant=maintenant)
        if defauts:
            rates.append(f"témoin négatif : une zone saine rougit ({defauts[0]})")
        if n != 3:
            rates.append(f"témoin négatif : {n} handoffs jugés, 3 attendus (_template et LATEST exclus)")
        for nom, statut, il_y_a, quoi in (("vieux.md", "active", 20, "un actif de plus de 14 j"),
                                          ("muet.md", None, 1, "un statut absent"),
                                          ("faux.md", "fini", 1, "un statut hors énumération")):
            commit(nom, statut, il_y_a)
            if not any(nom in d for d in juger(b, maintenant=maintenant)[0]):
                rates.append(f"non vu : {quoi}")
            (b / "handoffs" / nom).unlink()
            subprocess.run(["git", "commit", "-qam", f"retire {nom}"], cwd=b, env=env,
                           capture_output=True)
    return rates


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--jours", type=int, default=SEUIL_JOURS)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()

    rates = auto_epreuve()
    if rates:
        print("\nLES HANDOFFS — l'auto-épreuve a échoué, rien n'est jugé :")
        for r in rates:
            print(f"  ❌ {r}")
        return 1
    if not (brain / "handoffs").is_dir():
        print(f"SKIP pas de `handoffs/` dans {brain}")
        return 0

    defauts, n = juger(brain, a.jours)
    print("\nLES HANDOFFS\n")
    print(f"  auto-épreuve         3 défauts vus, des handoffs sains ne rougissent pas")
    print(f"  handoffs jugés       {n} (seuil d'un actif : {a.jours} j)")
    nettoyable = brain / "scripts" / "scratch-nettoyable.py"
    if nettoyable.is_file():
        r = subprocess.run([sys.executable, str(nettoyable)], cwd=brain,
                           capture_output=True, text=True)
        tete = next((l for l in r.stdout.splitlines() if l.startswith("SCRATCH")), None)
        if tete:
            print(f"  ℹ️  {tete.strip()} — affiché, pas jugé")
    if not defauts:
        print("\n  ✅ chaque handoff a un statut, et aucun actif n'attend depuis trop longtemps")
        return 0
    print()
    for d in defauts:
        print(f"  ❌ {d}")
    print("\nVERDICT: un handoff ne dit plus s'il est attendu")
    return 1


if __name__ == "__main__":
    sys.exit(main())
