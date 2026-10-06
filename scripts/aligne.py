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

    1. `git fetch` du dépôt de la branche suivie — puis, si l'`aligne.py` qu'elle
       porte diffère de celui-ci, c'est lui qui prend la main, une fois (le
       relais, comme `brain maj`) : sans lui, ce que la version change dans
       `brain aligne` n'agissait qu'à l'alignement suivant. Mesuré le 5/10 : la
       déclaration de la version (6.) arrivée par la fusion n'a joué qu'au second
       `brain aligne` du laptop ;
    2. lève le verrou du noyau (`brain vue --deverrouiller`) ;
    3. `git merge --ff-only` de la branche suivie — jamais `git pull` : avec
       `pull.rebase=true`, il refuse dès qu'il reste des modifications locales,
       et le brain en a toujours ;
    4. reconstruit la vue, ce qui repose le verrou selon la posture — que la
       fusion ait réussi ou non ;
    5. signale tout fichier non suivi dans `noyau/` : un agent que le tronc a
       retiré et que rien n'a pu effacer ;
    6. déclare la version reçue — `kernel_version` de `brain-compose.local.yml`
       prend la `version` de `brain-compose.yml`, comme le fait `brain maj`. Sans
       elle, le laptop a dit 2.7.0 du 3/10 au 5/10, à travers trois versions, et
       son boot annonçait un « Kernel drift » faux. Seulement si la fusion a
       réussi : une version refusée n'est pas reçue.
    7. branche le garde de lecture (`garde-lecture.py brancher`) : son hook vit
       dans `.claude/settings.json`, que git ne suit pas chez un fork — une
       machine installée avant lui ne l'aurait jamais. Il n'ajoute que son
       entrée, une fois.

Sans `noyau/` (un brain à plat), il fait 1 et 3, rien d'autre.
Sortie 0 : aligné. 1 : la fusion a refusé, ou un fichier non suivi reste dans
`noyau/`. Ce qu'il ne fait jamais : forcer, réinitialiser, effacer.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def git(brain: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(brain), *args], capture_output=True, text=True)


def vue(brain: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(brain / "scripts" / "vue.py"), *args],
                          capture_output=True, text=True, env={**os.environ, "BRAIN_ROOT": str(brain)})


def relayer(brain: Path, suivie: str) -> int | None:
    """L'`aligne.py` de la branche suivie prend la main, s'il diffère de celui-ci.

    None : pas de relais (déjà relayé, pas d'`aligne.py` dans la branche, ou le même)."""
    if os.environ.get("BRAIN_ALIGNE_RELAIS"):
        return None
    r = git(brain, "show", f"{suivie}:scripts/aligne.py")
    if r.returncode != 0 or r.stdout == Path(__file__).read_text(encoding="utf-8"):
        return None
    import tempfile
    with tempfile.TemporaryDirectory(prefix="brain-aligne-relais-") as tmp:
        script = Path(tmp) / "aligne.py"
        script.write_text(r.stdout, encoding="utf-8")
        print(f"↪ relais : le brain aligne de {suivie} prend la main — il sait ce que la version apporte")
        env = {**os.environ, "BRAIN_ALIGNE_RELAIS": suivie, "BRAIN_ROOT": str(brain)}
        return subprocess.run([sys.executable, str(script)], env=env).returncode


def declarer(brain: Path) -> str:
    """`kernel_version` = la `version` de `brain-compose.yml` — l'expression de
    `declarer` dans `maj.py`. Rend la ligne à dire, vide s'il n'y a rien à dire."""
    compose, local = brain / "brain-compose.yml", brain / "brain-compose.local.yml"
    m = re.search(r'^version:\s*"?([0-9][^"\s]*)"?', compose.read_text(encoding="utf-8"), re.M) \
        if compose.is_file() else None
    if not m:
        return ""
    version = m.group(1)
    if not local.is_file():
        return f"  ⓘ pas de brain-compose.local.yml : kernel_version {version} à déclarer à la main"
    texte = local.read_text(encoding="utf-8")
    avant = re.search(r'^kernel_version:\s*"?([^"\s]*)"?', texte, re.M)
    if not avant:
        return f"  ⓘ kernel_version absent de brain-compose.local.yml : {version} à déclarer à la main"
    if avant.group(1) == version:
        return ""
    local.write_text(re.sub(r'^kernel_version:.*$', f'kernel_version: "{version}"', texte, count=1,
                            flags=re.M), encoding="utf-8")
    return f"  ✅ kernel_version : {avant.group(1)} → {version} (brain-compose.local.yml)"


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
    if (code := relayer(brain, suivie)) is not None:
        return code
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
    if (ligne := declarer(brain)):
        print(ligne)
    garde = brain / "scripts" / "garde-lecture.py"
    if garde.is_file():
        g = subprocess.run([sys.executable, str(garde), "brancher", "--brain", str(brain)],
                           capture_output=True, text=True, timeout=60)
        print((g.stdout or g.stderr).strip())
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
