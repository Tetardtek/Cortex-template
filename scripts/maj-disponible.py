#!/usr/bin/env python3
# brain-distribuable: oui
"""maj-disponible.py — une version plus récente existe-t-elle chez l'amont ?

Usage :
    maj-disponible.py            lit les tags de l'amont, écrit l'état (le timer)
    maj-disponible.py --lire     ce que le briefing affiche — sans réseau

Sortie de `--lire` : 0 = rien à dire (à jour, ou pas d'amont) ; 1 = une ligne à
afficher (une version plus récente, ou une vérification impossible depuis
longtemps).

── Une information, pas une injonction ────────────────────────────────────

Le fork va lire les tags de son amont, à son rythme ; la forge ne pousse rien.
Quand une version plus récente existe, le briefing le dit en UNE ligne : la
version disponible, la sienne, la page à lire. Pas de rouge, pas d'insistance :
chacun reste libre de mettre à jour, ou non (Kevin, 30/09).

L'amont est le remote que la page « Se mettre à jour » fait déclarer :

    git remote add upstream <URL_DU_GABARIT>
    git remote set-url --push upstream DISABLED

Sans lui — le brain source, ou un fork qui ne suit pas l'amont — rien ne
s'affiche. La vérification le dit dans son journal, le briefing se tait.

── Jamais sur le chemin du boot ───────────────────────────────────────────

`--lire` n'appelle jamais git ni le réseau : il lit l'état qu'un passage
quotidien (brain-maj.timer) a écrit. Une forge injoignable ne se lit pas comme
« à jour » : l'état garde la date du dernier succès, et le briefing le dit au
bout de sept jours sans vérification réussie.

`git ls-remote --tags` ne demande aucun jeton pour un dépôt public et n'écrit
rien dans le dépôt : on lit les tags, on ne les rapatrie pas.

Variables : BRAIN_ROOT (défaut : le brain de ce script),
            BRAIN_MAJ_REMOTE (défaut `upstream`),
            BRAIN_MAJ_ETAT (défaut $XDG_STATE_HOME/brain/maj-disponible.json).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")
VERSION = re.compile(r'^version:\s*"?(\d+)\.(\d+)\.(\d+)"?\s*$', re.M)
DELAI = 30                         # secondes pour joindre l'amont
SANS_NOUVELLES = timedelta(days=7)
PAGE = "docs/mettre-a-jour.md"


def racines() -> tuple[Path, str, Path]:
    brain = Path(os.environ.get("BRAIN_ROOT") or Path(__file__).resolve().parent.parent)
    remote = os.environ.get("BRAIN_MAJ_REMOTE") or "upstream"
    etat = os.environ.get("BRAIN_MAJ_ETAT")
    if not etat:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
        etat = base / "brain" / "maj-disponible.json"
    return brain, remote, Path(etat)


def version_locale(brain: Path) -> tuple[int, int, int] | None:
    try:
        m = VERSION.search((brain / "brain-compose.yml").read_text(encoding="utf-8"))
    except OSError:
        return None
    return tuple(int(x) for x in m.groups()) if m else None


def texte(v) -> str:
    return ".".join(str(x) for x in v) if v else "?"


def verifier(brain: Path, remote: str, maintenant: datetime) -> dict:
    """Le passage du timer : lit les tags, ne touche pas au dépôt."""
    locale = version_locale(brain)
    etat = {"date": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), "locale": texte(locale)}
    connu = subprocess.run(["git", "-C", str(brain), "remote", "get-url", remote],
                           capture_output=True, text=True)
    if connu.returncode != 0:
        return {**etat, "resultat": "sans amont"}
    try:
        r = subprocess.run(["git", "-C", str(brain), "ls-remote", "--tags", remote],
                           capture_output=True, text=True, timeout=DELAI,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0",
                                # jamais de question interactive : un timer n'a
                                # personne pour répondre
                                "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND")
                                or "ssh -o BatchMode=yes -o ConnectTimeout=10"})
    except subprocess.TimeoutExpired:
        return {**etat, "resultat": "injoignable", "detail": f"délai dépassé ({DELAI} s)"}
    if r.returncode != 0:
        return {**etat, "resultat": "injoignable", "detail": (r.stderr or "").strip()[:200]}
    versions = [tuple(int(x) for x in m.groups())
                for m in (TAG.search(l) for l in r.stdout.splitlines()) if m]
    if not versions:
        return {**etat, "resultat": "sans version", "succes": etat["date"]}
    derniere = max(versions)
    return {**etat, "succes": etat["date"], "amont": texte(derniere),
            "resultat": "plus récente" if locale and derniere > locale else "à jour"}


def ecrire(chemin: Path, etat: dict, precedent: dict | None) -> None:
    # Un échec garde la date du DERNIER succès : c'est elle qui dit depuis
    # quand on ne sait plus.
    if "succes" not in etat and precedent and precedent.get("succes"):
        etat["succes"] = precedent["succes"]
        if precedent.get("amont"):
            etat["amont_connu"] = precedent["amont"]
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_suffix(".json.part")
    provisoire.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
    provisoire.replace(chemin)


def lire_etat(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lire(chemin: Path, maintenant: datetime) -> tuple[int, str]:
    """Le briefing : aucun appel à git, aucun réseau."""
    etat = lire_etat(chemin)
    if not etat or etat.get("resultat") in (None, "sans amont"):
        return 0, ""
    if etat["resultat"] == "plus récente":
        return 1, (f"🆕 v{etat['amont']} est disponible (tu es en {etat['locale']}) — "
                   f"quand tu veux : {PAGE}")
    succes = etat.get("succes")
    if succes:
        vu = datetime.strptime(succes, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if maintenant - vu <= SANS_NOUVELLES:
            return 0, ""
        return 1, (f"🆕 mises à jour : pas de vérification réussie depuis le "
                   f"{vu.strftime('%d/%m')} ({etat['resultat']})")
    return 1, f"🆕 mises à jour : l'amont n'a jamais répondu ({etat['resultat']})"


def main() -> int:
    brain, remote, chemin = racines()
    maintenant = datetime.now(timezone.utc)
    if "--lire" in sys.argv[1:]:
        code, ligne = lire(chemin, maintenant)
        if ligne:
            print(ligne)
        return code
    etat = verifier(brain, remote, maintenant)
    ecrire(chemin, etat, lire_etat(chemin))
    dit = {
        "sans amont": f"pas de remote `{remote}` — rien à comparer (le brain source, ou un fork qui ne suit pas l'amont)",
        "injoignable": f"amont injoignable : {etat.get('detail', '')}",
        "sans version": "l'amont ne porte aucun tag vX.Y.Z",
        "à jour": f"à jour : {etat['locale']} (amont {etat.get('amont')})",
        "plus récente": f"v{etat.get('amont')} disponible — tu es en {etat['locale']}",
    }[etat["resultat"]]
    print(dit)
    # Le timer ne rougit que s'il n'a pas pu lire l'amont.
    return 1 if etat["resultat"] == "injoignable" else 0


if __name__ == "__main__":
    sys.exit(main())
