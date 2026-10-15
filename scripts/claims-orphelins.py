#!/usr/bin/env python3
# brain-distribuable: oui
"""Les claims ouverts dont la session Claude Code ne vit plus — NOMMÉS, jamais fermés.

Le BSI sait qui a un claim, pas qui lit encore. Le 29/09, un claim `explore`
restait ouvert, terminal fermé, et personne ne le voyait : le têtard du plugin
Quickshell le montrait, rien dans le brain ne s'en servait. Tranché par l'owner le
2/10 : les orphelins sont **signalés au boot, jamais fermés d'office** — une
session parquée peut revenir, et fermer le claim d'une session vivante est la
faute que le BSI existe pour empêcher.

    python3 scripts/claims-orphelins.py            → les orphelins, puis ce qui n'est pas jugé
    python3 scripts/claims-orphelins.py --quiet    → rien s'il n'y a rien (pour le boot)
    python3 scripts/claims-orphelins.py --sans-claim
                    → l'inverse : les sessions vivantes, dans le brain, SANS claim
                      (sortie 1 s'il y en a — un contrôle du doctor)

── Sans claim ──────────────────────────────────────────────────────────────

« Ouvrir le claim avant toute réponse de travail » est la loi du boot, et rien
ne la vérifiait : le doctor contrôlait que le TEXTE la nomme. Une session
vivante dont le répertoire est dans le brain, lancée depuis plus de
`SEUIL_SANS_CLAIM` minutes (le boot prend une minute), et dont ni elle ni sa
famille ne porte de claim ouvert, est nommée. La famille : celles qu'elle a
remplacées (parquée puis reprise), et celle qui l'a reprise — un terminal
parqué dans une session d'arrière-plan qui a son claim n'est pas sans claim.

── Vivant ? ────────────────────────────────────────────────────────────────

Une session est vivante si un fichier `~/.claude/sessions/<pid>.json` la porte
et que son processus existe. Un claim porté par une identité ANTÉRIEURE d'une
session vivante (parquée puis reprise) n'est pas orphelin : la filiation est
lue dans ces mêmes fichiers (`scripts/lib/filiation.py`).

── Ce qui ne se juge pas, et se dit ────────────────────────────────────────

- un claim sans `agent_session` (ancien, ou ouvert hors d'une session) ;
- un claim d'une autre machine (`sess_id` suffixé `.laptop`…) : ses processus
  ne sont pas ici ;
- le dossier des sessions illisible : rien n'est déclaré orphelin.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent   # le programme : ses `lib/`, son moteur
sys.path.insert(0, str(BRAIN / 'scripts' / 'lib'))


def _racine_des_donnees() -> Path:
    """Le dossier de données : là où les sessions travaillent. Un programme installé à part
    (`brain-engine/donnees.py`, la marque) n'est pas le brain — `--sans-claim` y cherchait les
    sessions, n'en trouvait aucune, et se disait vert. Sans `donnees.py` (un banc qui ne copie
    que ce script) : la position, comme avant."""
    src = BRAIN / 'brain-engine' / 'donnees.py'
    if not src.is_file():
        return BRAIN
    import importlib.util
    spec = importlib.util.spec_from_file_location('_brain_donnees', src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.trouver_donnees(BRAIN, env_d_abord=False)[0]
    except RuntimeError as exc:
        raise SystemExit(f'❌ {exc}')
from filiation import anciennes, lire, pid_vivant  # noqa: E402

AUTRE_MACHINE = re.compile(r'\.[a-z][a-z0-9-]*$')
SEUIL_SANS_CLAIM = 15        # minutes


def sans_claim(claims: list, sessions: list[dict], racine: Path, maintenant: float,
               vivant=pid_vivant, seuil_min: int = SEUIL_SANS_CLAIM) -> list[dict]:
    """Les sessions vivantes du brain, plus vieilles que le seuil, sans claim. Pur, à `vivant` près."""
    portees = {c.agent_session for c in claims if c.agent_session}
    vivantes_ici = [s for s in sessions if s.get('pid') is not None and vivant(s['pid'])]
    couvertes: set[str] = set()
    for s in vivantes_ici:
        famille = {s['sessionId'], *anciennes(s['sessionId'], sessions)}
        if famille & portees:
            couvertes |= famille
    racine = str(Path(racine).resolve())
    trouvees = []
    for s in vivantes_ici:
        cwd = str(s.get('cwd') or '')
        age_min = (maintenant - (s.get('startedAt') or 0) / 1000) / 60
        if (s['sessionId'] not in couvertes and age_min > seuil_min
                and (cwd == racine or cwd.startswith(racine + '/'))):
            trouvees.append(s)
    return trouvees


def vivantes(sessions: list[dict], vivant=pid_vivant) -> set[str]:
    """Les identités portées par un processus vivant — et leurs antérieures."""
    ids: set[str] = set()
    for s in sessions:
        if s.get('pid') is not None and vivant(s['pid']):
            ids.add(s['sessionId'])
            ids.update(anciennes(s['sessionId'], sessions))
    return ids


def juger(claims: list, sessions: list[dict] | None, vivant=pid_vivant) -> tuple[list, list]:
    """(orphelins, non jugés) — chacun (claim, raison). Pur, à `vivant` près."""
    if sessions is None:
        return [], [(c, 'sessions illisibles') for c in claims]
    ici = vivantes(sessions, vivant)
    orphelins, non_juges = [], []
    for c in claims:
        if AUTRE_MACHINE.search(c.sess_id):
            non_juges.append((c, 'autre machine'))
        elif not c.agent_session:
            non_juges.append((c, 'sans identité de session'))
        elif c.agent_session not in ici:
            orphelins.append((c, f'session {c.agent_session[:8]}… sans processus vivant'))
    return orphelins, non_juges


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--quiet', action='store_true', help='rien s\'il n\'y a pas d\'orphelin')
    p.add_argument('--sans-claim', action='store_true', dest='sans_claim',
                   help='les sessions vivantes du brain sans claim — sortie 1 s\'il y en a')
    a = p.parse_args()
    sys.path.insert(0, str(BRAIN / 'brain-engine'))
    import db
    from core.bsi import BSI
    claims = BSI(db.depot()).ouverts()
    dossier = Path(os.environ.get('CLAUDE_SESSIONS_DIR') or Path.home() / '.claude' / 'sessions')
    if a.sans_claim:
        import time
        sessions = lire(dossier)
        if sessions is None:
            print('⏭️  sessions illisibles — rien n\'est jugé')
            return 0
        trouvees = sans_claim(claims, sessions, _racine_des_donnees(), time.time())
        if not trouvees:
            print(f'✅ chaque session vivante du brain a son claim ({len(claims)} ouvert(s))')
            return 0
        print(f'❌ {len(trouvees)} session(s) vivante(s) dans le brain sans claim — '
              f'la loi du boot : ouvrir le claim avant toute réponse de travail')
        for s in trouvees:
            print(f'   {s["sessionId"][:8]}…  {s.get("kind", "?")}  pid {s.get("pid")}  '
                  f'« {(s.get("name") or "")[:40]} »')
        return 1
    orphelins, non_juges = juger(claims, lire(dossier))
    if a.quiet and not orphelins:
        return 0
    if orphelins:
        print(f'👻 {len(orphelins)} claim(s) ouvert(s) sans session vivante — à fermer par leur '
              f'session, ou par l\'humain (jamais d\'office) :')
        for c, raison in orphelins:
            print(f'   {c.sess_id}  [{c.scope}]  — {raison}')
    elif not a.quiet:
        print(f'✅ aucun claim orphelin ({len(claims)} ouvert(s))')
    if non_juges and not a.quiet:
        print('   non jugés : ' + ', '.join(f'{c.sess_id} ({r})' for c, r in non_juges))
    return 0


if __name__ == '__main__':
    sys.exit(main())
