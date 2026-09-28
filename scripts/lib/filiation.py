#!/usr/bin/env python3
# brain-distribuable: oui  # bsi-claim.sh et claude-boite.py s'en servent
"""Les identités qu'une session d'agent a portées AVANT la sienne.

Une session Claude Code peut être parquée puis reprise dans un autre
processus : elle reçoit alors une identité neuve (`CLAUDE_CODE_SESSION_ID`),
et le claim qu'elle avait ouvert porte l'ancienne. Pour le BSI, c'est devenu
« le claim d'une autre session » : `close` sans argument ne le trouve plus,
`close <id>` est refusé.

La filiation est ÉCRITE, pas devinée. Chaque session a un fichier
`~/.claude/sessions/<pid>.json`. Celle qui a été parquée y porte
`parkedJobId`, qui est le PRÉFIXE de l'identité de celle qui l'a reprise :

    211351.json   sessionId da05c924-…   parkedJobId 5db52755
    586006.json   sessionId 5db52755-…   jobId       5db52755

Ce module suit ces liens à rebours, de proche en proche (une session reprise
peut l'être encore), et rend les identités antérieures, la plus proche d'abord.

⚠️ Ce sont des fichiers INTERNES de Claude Code : leur format peut changer.
Un fichier illisible est ignoré ; un dossier absent rend `None` — « je n'ai pas
pu regarder », que l'appelant doit dire, jamais « aucune ancienne identité ».

    python3 scripts/lib/filiation.py <session_id> [dossier]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROFONDEUR_MAX = 10   # une chaîne de reprises plus longue est une anomalie


def lire(dossier: Path) -> list[dict] | None:
    """Les fichiers de session lisibles du dossier. `None` s'il n'existe pas."""
    if not dossier.is_dir():
        return None
    sessions = []
    for f in sorted(dossier.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get("sessionId"), str):
            sessions.append(d)
    return sessions


def anciennes(courante: str, sessions: list[dict]) -> list[str]:
    """Les identités que `courante` a remplacées, la plus proche d'abord. Pur.

    Une session X est l'ancienne de C si X porte un `parkedJobId` non vide qui
    est un préfixe de C. Une filiation AMBIGUË (deux sessions parquées dans la
    même) est rendue entière : les deux ont été reprises ici.
    """
    trouvees: list[str] = []
    frontiere = [courante] if courante else []
    for _ in range(PROFONDEUR_MAX):
        suivante = []
        for c in frontiere:
            for s in sessions:
                job = s.get("parkedJobId")
                ident = s["sessionId"]
                if (isinstance(job, str) and job and c.startswith(job)
                        and ident != courante and ident not in trouvees):
                    trouvees.append(ident)
                    suivante.append(ident)
        if not suivante:
            break
        frontiere = suivante
    return trouvees


def pid_vivant(pid) -> bool:
    """Le processus existe-t-il ? `os.kill(pid, 0)` n'envoie rien, il demande."""
    import os
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def mortes(sessions: list[dict], vivant=pid_vivant) -> set[str]:
    """Les identités de session CONNUES ICI dont le processus est mort, et dont
    aucune session vivante ne descend. Pur si `vivant` l'est.

    « Connues ici » : on ne juge que ce qui a un fichier de session sur cette
    machine. Une identité sans fichier (une autre machine, un fichier nettoyé
    à la sortie) n'est jamais déclarée morte — l'expiration s'en charge.

    « Aucune descendante vivante » : une session parquée puis reprise laisse
    son ancien fichier ; si l'ancien processus est mort mais que la reprise
    vit, la session n'est pas plantée — le hook de la boîte rattachera.
    """
    vivantes = {s["sessionId"] for s in sessions if vivant(s.get("pid"))}
    # Les ancêtres d'une session vivante sont « continués », pas morts.
    continues: set[str] = set()
    for v in vivantes:
        continues.update(anciennes(v, sessions))
    return {s["sessionId"] for s in sessions
            if s["sessionId"] not in vivantes and s["sessionId"] not in continues}


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1]:
        print(__doc__)
        return 1
    dossier = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / ".claude" / "sessions"
    sessions = lire(dossier)
    if sessions is None:
        print(f"filiation illisible : {dossier} absent", file=sys.stderr)
        return 2
    for ident in anciennes(sys.argv[1], sessions):
        print(ident)
    return 0


if __name__ == "__main__":
    sys.exit(main())
