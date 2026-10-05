#!/usr/bin/env python3
"""
brain-engine/focus_instantane.py — le focus, rendu, et son instantané.

Moteur éteint, une session n'avait aucun focus : `brain_focus` se repliait sur
`focus.md`, un fichier qui renvoie vers l'API — vers ce qui ne répond pas. Un
repli circulaire.

Désormais, à chaque passage de l'indexeur (`brain-engine.sh embed`, toutes les
2 h), le focus live est écrit dans `focus.instantane.md`, à la racine de la
data, avec sa date. Moteur éteint, `brain_focus` rend ce dernier instantané et
dit qu'il en est un.

    python3 brain-engine/focus_instantane.py      → écrit l'instantané

Le fichier est ignoré par git : réécrit toutes les 2 h, suivi, il salirait le
tronc partagé à chaque passage. `focus.md` reste le repli de dernier recours.

Moteur injoignable au moment d'écrire : rien n'est écrasé — l'instantané
précédent, daté, vaut mieux qu'un fichier vide — et la sortie le dit (code 0 :
le focus ne doit jamais faire échouer l'indexation).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NOM = 'focus.instantane.md'


def rendre(data: dict) -> str:
    """Le focus (la réponse de `GET /focus`) en markdown — le rendu de `brain_focus`."""
    lines = []

    cap = data.get('cap')
    if cap:
        lines.append('## Cap\n')
        lines.append(cap)
        lines.append('')

    en_cours = data.get('en_cours', [])
    if en_cours:
        lines.append('## En cours\n')
        lines.append('> Calculé : une PR fusionnée depuis moins de 7 jours porte la fiche.\n')
        for item in en_cours:
            lines.append(f"- **{item['fiche']}** [{item.get('projet', '')}] {item.get('titre', '')} "
                         f"— {item.get('prs', 0)} PR, la dernière le {item.get('derniere', '')[:10]}")
        lines.append('')

    last = data.get('last_session')
    if last:
        lines.append(f"Derniere session : **{last.get('sess_id', '?')}** — "
                     f"{last.get('duration_min', '?')}min, energy {last.get('energy', '?')}")

    return '\n'.join(lines) if lines else 'Focus vide.'


def lire_focus(api: str, delai: float = 5) -> dict:
    with urllib.request.urlopen(f'{api}/focus', timeout=delai) as resp:
        return json.loads(resp.read())


def ecrire(racine: Path, api: str) -> tuple[bool, str]:
    """Écrit l'instantané. (écrit ?, ce qui s'est passé)."""
    cible = racine / NOM
    try:
        data = lire_focus(api)
    except Exception as exc:                               # noqa: BLE001
        if cible.exists():
            date = datetime.fromtimestamp(cible.stat().st_mtime, timezone.utc)
            avant = f"l'instantané précédent reste ({date:%Y-%m-%d %H:%M} UTC)"
        else:
            avant = 'aucun instantané précédent'
        return False, f'moteur injoignable ({type(exc).__name__}) — rien écrit, {avant}'
    quand = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    texte = (f'<!-- instantané du focus, {quand} — écrit par brain-engine/focus_instantane.py -->\n'
             f'# Focus — instantané du {quand}\n\n' + rendre(data) + '\n')
    provisoire = cible.with_suffix('.md.tmp')
    provisoire.write_text(texte, encoding='utf-8')
    provisoire.replace(cible)                              # atomique : jamais à moitié écrit
    return True, f'instantané écrit : {cible} ({quand})'


def lire_instantane(racine: Path) -> str | None:
    """Le dernier instantané, annoncé comme un repli — `None` s'il n'y en a pas."""
    cible = racine / NOM
    if not cible.is_file():
        return None
    corps = cible.read_text(encoding='utf-8')
    return ('> ⚠️ **Repli — le moteur ne répond pas.** Ce qui suit est le dernier instantané '
            'du focus, écrit au passage de l\'indexeur : il peut avoir jusqu\'à 2 h de retard.\n\n'
            + corps)


def main() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from racines import DONNEES
    api = f"http://127.0.0.1:{int(os.getenv('BRAIN_PORT') or 7700)}"
    ecrit, message = ecrire(DONNEES, api)
    print(('✅ ' if ecrit else 'ⓘ ') + message)
    return 0


if __name__ == '__main__':
    sys.exit(main())
