#!/usr/bin/env python3
# brain-distribuable: oui
"""brain signaux — les signaux entre sessions : les relever, en émettre, les accuser.

    brain signaux                         ce qui m'attend, ici et chez les peers — rien ne bouge
    brain signaux --pour <dest>           la boîte d'un autre destinataire (une instance, une session)
    brain signaux --envoyes               les 20 derniers signaux émis d'ici, et leur état
    brain signaux --envoyer <dest> --type T --message "…" [--projet P]
    brain signaux --accuser <sig_id>      une fois TRAITÉ — jamais d'office

Une façade : le verbe parle français, `bsi-signal.sh` fait le travail et garde son
nom — le briefing, `brain etat` et `brain-status.sh` l'appellent. Son code de sortie traverse
tel quel. Le nom d'avant (`--payload`) reste un alias, hors de l'aide. Les types
(`READY_FOR_REVIEW`, `HANDOFF`…) sont des valeurs en base, pas des mots de la commande.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
TYPES = ("READY_FOR_REVIEW", "REVIEWED", "BLOCKED_ON", "HANDOFF", "CHECKPOINT", "INFO")


def analyseur() -> argparse.ArgumentParser:
    """Les options du verbe — lues aussi par le test qui juge les instructions des agents."""
    p = argparse.ArgumentParser(prog="brain signaux",
                                description="Les signaux entre sessions : les relever, en émettre, les accuser.")
    geste = p.add_mutually_exclusive_group()
    geste.add_argument("--pour", metavar="DEST", help="la boîte d'un autre destinataire (instance ou session)")
    geste.add_argument("--envoyes", action="store_true", help="les 20 derniers signaux émis d'ici, et leur état")
    geste.add_argument("--envoyer", metavar="DEST", help="émettre un signal vers une instance ou une session")
    geste.add_argument("--accuser", metavar="SIG_ID", help="accuser un signal une fois traité, même chez un peer")
    p.add_argument("--type", choices=TYPES, metavar="TYPE", help=f"avec --envoyer : {', '.join(TYPES)}")
    p.add_argument("--message", help="avec --envoyer : ce que le signal dit")
    p.add_argument("--payload", dest="message", help=argparse.SUPPRESS)
    p.add_argument("--projet", help="avec --envoyer : le projet concerné")
    return p


def main() -> int:
    p = analyseur()
    a = p.parse_args()
    if not a.envoyer and (a.type or a.message or a.projet):
        p.error("--type, --message et --projet vont avec --envoyer")
    if a.envoyer:
        cmd = ["send", a.envoyer]
        if a.type:
            cmd += ["--type", a.type]
        if a.projet:
            cmd += ["--projet", a.projet]
        if a.message is not None:
            cmd += ["--payload", a.message]
    elif a.accuser:
        cmd = ["ack", a.accuser]
    elif a.envoyes:
        cmd = ["outbox"]
    elif a.pour:
        cmd = ["inbox", a.pour]
    else:
        cmd = ["inbox"]
    return subprocess.run(["bash", str(ICI / "bsi-signal.sh"), *cmd]).returncode


if __name__ == "__main__":
    sys.exit(main())
