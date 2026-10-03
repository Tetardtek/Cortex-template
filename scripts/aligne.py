#!/usr/bin/env python3
# brain-distribuable: oui
"""brain aligne — reprendre le tronc, le noyau verrouillé compris.

    brain aligne              fetch, puis fusion en avance rapide de la branche suivie

Une instance dont la posture refuse le kernel (un laptop `replica-nomad`) a son
`noyau/` en lecture seule. git ne peut alors ni réécrire ni retirer un agent du
noyau. Mesuré le 3/10 : une version qui MODIFIE un agent échoue (« unable to
unlink », sortie 1, rien ne bouge) ; une version qui en RETIRE un sort en 0 et
laisse le fichier en place, que la vue montrerait encore.

Il fait donc, dans l'ordre :

    1. `git fetch` du dépôt de la branche suivie ;
    2. lève le verrou du noyau (`brain vue --deverrouiller`) ;
    3. `git merge --ff-only` de la branche suivie — jamais `git pull` : avec
       `pull.rebase=true`, il refuse dès qu'il reste des modifications locales,
       et le brain en a toujours ;
    4. reconstruit la vue, ce qui repose le verrou selon la posture — que la
       fusion ait réussi ou non ;
    5. signale tout fichier non suivi dans `noyau/` : un agent que le tronc a
       retiré et que rien n'a pu effacer.

Sans `noyau/` (un brain à plat), il fait 1 et 3, rien d'autre.
Sortie 0 : aligné. 1 : la fusion a refusé, ou un fichier non suivi reste dans
`noyau/`. Ce qu'il ne fait jamais : forcer, réinitialiser, effacer.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def git(brain: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(brain), *args], capture_output=True, text=True)


def vue(brain: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(brain / "scripts" / "vue.py"), *args],
                          capture_output=True, text=True, env={**os.environ, "BRAIN_ROOT": str(brain)})


def main() -> int:
    brain = Path(os.environ.get("BRAIN_ROOT") or Path(__file__).resolve().parent.parent)
    amont = git(brain, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if amont.returncode != 0:
        print("brain aligne : la branche courante ne suit aucune branche distante — rien à aligner.")
        return 1
    suivie = amont.stdout.strip()
    distant = suivie.split("/", 1)[0]
    f = git(brain, "fetch", "-q", distant)
    if f.returncode != 0:
        print(f"brain aligne : `git fetch {distant}` a échoué — {f.stderr.strip()[-200:]}")
        return 1
    avant = git(brain, "rev-parse", "--short", "HEAD").stdout.strip()
    migre = (brain / "noyau" / "agents").is_dir()
    if migre:
        vue(brain, "--deverrouiller")
    m = git(brain, "merge", "--ff-only", suivie)
    if migre or (brain / "noyau" / "agents").is_dir():
        v = vue(brain, "--construire")                 # repose le verrou, réussite ou non
        verrou = next((l.strip() for l in v.stdout.splitlines() if "noyau/" in l), "")
        # Un catalogue qui ne se calcule pas se dit : tu le taisais, le jour J (3/10).
        verrou += "".join(f"\n  {l.strip()}" for l in v.stdout.splitlines() if "catalogue non calculé" in l)
    else:
        verrou = ""
    apres = git(brain, "rev-parse", "--short", "HEAD").stdout.strip()
    if m.returncode != 0:
        print(f"❌ brain aligne : la fusion de {suivie} refuse — {(m.stderr or m.stdout).strip()[-300:]}")
        if verrou:
            print(f"  {verrou}")
        return 1
    print(f"✅ aligné sur {suivie} — {avant} → {apres}" if avant != apres
          else f"✅ déjà aligné sur {suivie} ({apres})")
    if verrou:
        print(f"  {verrou}")
    restes = [l for l in git(brain, "ls-files", "--others", "--exclude-standard", "--", "noyau").stdout.splitlines() if l]
    if restes:
        print(f"⚠️ {len(restes)} fichier(s) non suivi(s) dans noyau/ — retirés par le tronc, ou écrits à la main :")
        for l in restes[:10]:
            print(f"    {l}")
        print("  Jamais effacés ici : les regarder, puis les retirer à la main (`brain vue --deverrouiller`).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
