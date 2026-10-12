#!/usr/bin/env python3
"""Chaque satellite du brain se lit-il depuis sa forge ?

    python3 tools/satellites_se_lisent.py --brain ~/Dev/Brain

Ce qui pourrirait en silence sans lui : **une machine qui ne tire plus ses
satellites.** Le 12/10, le laptop ne pouvait plus lire aucun de ses onze satellites
depuis une semaine — des remotes HTTPS sans identifiants (dépôts privés : 403), et
SSH qui frappait le mauvais port — et aucun contrôle ne le disait : celui des
satellites à jour range un refus parmi les « injoignables », et quand aucun dépôt
ne répond, il s'abstient. Un refus n'est pas une absence de réseau.

── Ce qu'il juge, par satellite ───────────────────────────────────────────

Les satellites : chaque dépôt git sous le brain (premier niveau, et `instance/*`),
et ceux que `satellites.yml` déclare hors du brain (`chemin:`) — présents sur le
disque. Pour chacun, l'amont qu'il suit (sinon `origin`) est interrogé par
`git ls-remote`, borné par un délai, sans jamais demander de mot de passe
(`GIT_TERMINAL_PROMPT=0`, ssh en `BatchMode`) et sans rien écrire : ni `fetch`,
ni référence distante réécrite.

    se lit          ✅
    ne se lit pas   ❌ la forge répond et refuse : 403, identifiants absents,
                    clé refusée, dépôt introuvable, connexion refusée
    bloqué          ❌ l'amont a avancé ET des commits locaux n'y sont pas :
                    en retard sans pouvoir avancer en avance rapide
    derrière        ⓘ l'amont a avancé, l'avance rapide suffit (`git pull --ff-only`)
    sans amont      ⓘ aucun remote : rien à lire, rien de jugé
    hors réseau     ⏭ nom introuvable, réseau inaccessible, délai dépassé

Si aucun satellite interrogé ne répond pour une raison de réseau, le contrôle
s'abstient (SKIP) : un vert qui n'a rien mesuré est pire qu'un rouge. Sans
satellite, il s'abstient aussi.

Sortie 0 : chaque satellite se lit. 1 : un satellite ne se lit pas, ou ne peut
pas avancer — nommé, avec la raison.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DELAI = 20

#: Jamais une question : ni l'invite du terminal, ni un `askpass`, ni ssh qui demande
#: (sa commande en `BatchMode`, et aucun terminal de contrôle : `start_new_session`).
SANS_QUESTION = {
    "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "", "GCM_INTERACTIVE": "never",
    "LC_ALL": "C", "LANGUAGE": "",
}

#: Ce qui dit « pas de réseau », et seulement ça : la forge n'a pas été atteinte.
HORS_RESEAU = re.compile(
    r"Could not resolve host|Could not resolve hostname|Temporary failure in name resolution|"
    r"Name or service not known|Network is unreachable|No route to host|"
    r"Connection timed out|Operation timed out|timed out after", re.I)

#: Un identifiant dans une URL ne s'affiche jamais.
_IDENTIFIANT = re.compile(r"(//)[^/@\s]+@")


def git(depot: Path, *args: str, delai: int = DELAI, ssh: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **SANS_QUESTION, **({"GIT_SSH_COMMAND": ssh} if ssh else {})}
    return subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True,
                          timeout=delai, stdin=subprocess.DEVNULL, start_new_session=True, env=env)


def commande_ssh(depot: Path) -> str:
    """La commande ssh que git prendrait (la variable, sinon `core.sshCommand` du dépôt —
    un port, une clé réglés), en `BatchMode` : elle ne demande jamais rien."""
    base = (os.environ.get("GIT_SSH_COMMAND")
            or git(depot, "config", "--get", "core.sshCommand").stdout.strip() or "ssh")
    return f"{base} -o BatchMode=yes -o ConnectTimeout=10"


def satellites(brain: Path) -> list[tuple[str, Path]]:
    """(nom, dossier) de chaque satellite présent : les dépôts sous le brain (premier
    niveau, `instance/*`) et ceux que `satellites.yml` déclare ailleurs (`chemin:`)."""
    trouves: dict[str, Path] = {}
    for motif in ("*/.git", "instance/*/.git"):
        for g in sorted(brain.glob(motif)):
            d = g.parent
            if not any(p.is_symlink() for p in (d, *d.parents) if brain in p.parents):
                trouves[str(d.relative_to(brain))] = d
    f = brain / "satellites.yml"
    if f.is_file():
        try:
            import yaml
            decl = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("satellites") or {}
        except Exception:                                    # noqa: BLE001 — illisible : le disque seul
            decl = {}
        for cle, val in decl.items():
            chemin = val.get("chemin") if isinstance(val, dict) else None
            if chemin:
                d = Path(os.path.expanduser(str(chemin)))
                if d.is_absolute() and (d / ".git").exists():
                    trouves.setdefault(str(cle), d)
    return sorted(trouves.items())


def juger(depot: Path) -> tuple[str, str]:
    """(état, détail). Ne récupère rien."""
    u = git(depot, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if u.returncode == 0 and "/" in u.stdout.strip():
        distant, _, branche = u.stdout.strip().partition("/")
        ref = f"refs/heads/{branche}"
    else:
        distants = git(depot, "remote").stdout.split()
        if not distants:
            return "sans amont", "aucun remote"
        distant, branche, ref = ("origin" if "origin" in distants else distants[0]), None, "HEAD"
    try:
        r = git(depot, "ls-remote", distant, ref, ssh=commande_ssh(depot))
    except subprocess.TimeoutExpired:
        return "hors réseau", f"{distant} — délai dépassé ({DELAI} s)"
    if r.returncode != 0:
        lignes = [l.strip() for l in r.stderr.splitlines() if l.strip()]
        raison = _IDENTIFIANT.sub(r"\1***@", next((l for l in lignes if l.startswith("fatal")),
                                                  lignes[-1] if lignes else f"code {r.returncode}"))
        if HORS_RESEAU.search(r.stderr):
            return "hors réseau", raison[:140]
        return "ne se lit pas", raison[:140]
    if branche is None:
        return "se lit", f"{distant} (aucune branche suivie)"
    if not r.stdout.strip():
        return "ne se lit pas", f"{distant}/{branche} : la branche n'existe pas sur la forge"
    amont = r.stdout.split()[0]
    tete = git(depot, "rev-parse", "HEAD").stdout.strip()
    if amont == tete:
        return "se lit", f"{distant}/{branche} à jour"
    connu = git(depot, "cat-file", "-e", f"{amont}^{{commit}}").returncode == 0
    if connu:
        devant = int(git(depot, "rev-list", "--count", f"{amont}..HEAD").stdout or 0)
        derriere = int(git(depot, "rev-list", "--count", f"HEAD..{amont}").stdout or 0)
    else:
        # L'amont a des commits jamais récupérés : ce qui est local au-delà de la dernière
        # référence connue de l'amont n'y est pas.
        devant = int(git(depot, "rev-list", "--count", "@{u}..HEAD").stdout or 0)
        derriere = 1
    if derriere and devant:
        return "bloqué", (f"{distant}/{branche} a avancé et {devant} commit(s) local(aux) n'y sont "
                          "pas : l'avance rapide est impossible")
    if derriere:
        return "derrière", f"{distant}/{branche} a avancé — l'avance rapide suffit (`git pull --ff-only`)"
    return "se lit", f"{distant}/{branche} — {devant} commit(s) local(aux) à pousser"


SIGNES = {"se lit": "✅", "derrière": "ⓘ", "sans amont": "ⓘ", "hors réseau": "⏭",
          "ne se lit pas": "❌", "bloqué": "❌"}
ROUGES = ("ne se lit pas", "bloqué")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    brain = p.parse_args().brain.expanduser().resolve()

    liste = satellites(brain)
    if not liste:
        print("SKIP aucun satellite (aucun dépôt git sous le brain, aucun déclaré ailleurs).")
        return 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        etats = list(ex.map(lambda s: juger(s[1]), liste))

    interroges = [e for e, _ in etats if e != "sans amont"]
    hors = sum(e == "hors réseau" for e in interroges)
    if interroges and hors == len(interroges):
        print(f"SKIP hors réseau — {hors} satellite(s) sans réponse de la forge, rien mesuré.")
        return 0
    if not interroges:
        print(f"SKIP {len(etats)} satellite(s), aucun avec un remote — rien à lire.")
        return 0

    for (nom, _), (e, d) in zip(liste, etats):
        print(f"  {SIGNES[e]} {nom:<18} {e:<14} {d}")
    rouges = [nom for (nom, _), (e, _) in zip(liste, etats) if e in ROUGES]
    if rouges:
        print(f"❌ {len(rouges)} satellite(s) sur {len(interroges)} ne se lisent pas ou ne peuvent pas "
              f"avancer : {', '.join(rouges)}" + (f" ({hors} hors réseau)" if hors else ""))
        return 1
    print(f"✅ les {len(interroges) - hors} satellite(s) interrogé(s) se lisent"
          + (f" — {hors} hors réseau, non mesuré(s)" if hors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
