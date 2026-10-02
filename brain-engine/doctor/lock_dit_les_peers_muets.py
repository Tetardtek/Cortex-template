#!/usr/bin/env python3
"""`file-lock.sh acquire` dit-il quand un peer n'a PAS ete consulte ?

Ce qui pourrirait en silence sans lui : **un mutex distribue qui se croit
global alors qu'il n'a joint personne.**

`POST /bsi/locks` interroge chaque peer actif avant d'accorder. Un peer
injoignable etait attrape par `except Exception: pass` — delibere, commente
« mode degrade » — et la route repondait 200 sans rien en dire. `file-lock.sh`
affichait alors, sur cette meme reponse :

    Chemin   : moteur — peers consultes, Dashboard notifie

L'affirmation venait du script, le silence du moteur, et personne ne pouvait le
savoir. Le cas n'etait pas theorique : `laptop` est declare `active` dans
`brain-compose.local.yml` et ne repondait pas (mesure du 15/09).

    python3 tools/lock_dit_les_peers_muets.py --brain ~/Dev/Brain

── Ce qu'il eprouve, et pourquoi les QUATRE cas ─────────────────────────────

    reseau           les bases lues          -> le script les NOMME, sans
                                                affirmer de peers
    peers muets      la reponse les nomme    -> le script AVERTIT
    aucun peer muet  liste vide              -> le script affirme, et il a raison
    cle absente      vieux moteur            -> le script DOUTE, il n affirme pas

Le troisieme est celui qu'on oublie. Un champ qui n'apparait que dans le
mauvais cas ne permet pas de distinguer « tout va bien » de « mon interlocuteur
ne sait pas repondre a la question ». C'est exactement l'ambiguite qui a laisse
le message mentir : `peers_injoignables` est donc TOUJOURS present cote route,
et son absence signifie un moteur d'avant le 15/09 — un doute, pas un feu vert.

── Il n'ecrit rien ─────────────────────────────────────────────────────────

Le script est lance contre un **serveur factice** qui rend le corps qu'on lui
demande, dans un faux brain temporaire dont le `db.py` capture au lieu
d'ecrire. Aucune ligne ne part vers `locks`, et le controle est rejouable.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_ok = _ko = 0

FAUX_DB = '''
import json, os
BACKEND = "dolt"
def query(sql, params=()):
    return []
def query_one(sql, params=()):
    return None
def execute(sql, params=(), commit_msg=None, tables=None):
    return 1
def count(table, where="1=1"):
    return 0
'''


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


class _Factice(http.server.BaseHTTPRequestHandler):
    corps: dict = {}

    def do_POST(self):                                     # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        brut = json.dumps(type(self).corps).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def log_message(self, *a):                             # silence
        pass


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def faux_brain(base: Path, vrai: Path) -> Path:
    """Le plus petit brain qui permette de lancer `file-lock.sh`.

    Le script source `lib/python.sh` et importe `core.bsi` (depuis le
    1/10). Le faux brain les recoit, sinon le temoin meurt avant la premiere
    ligne qu il juge — rouge du 1/10 au 2/10 pour cette seule raison, vu en
    mesurant le doctor sur un fork.

    - `.venv/bin/python3` relaie vers le Python de ce controle, qui a le CORE
      (installe en editable sur l instance). Un lien direct ne suffirait pas :
      sans `pyvenv.cfg` a cote de lui, Python perdrait les paquets du venv.
    - `brain-engine/core/` est relie quand le brain le livre (un fork).
    """
    (base / "scripts" / "lib").mkdir(parents=True)
    (base / "brain-engine" / ".venv" / "bin").mkdir(parents=True)
    shutil.copy2(vrai / "scripts" / "file-lock.sh", base / "scripts" / "file-lock.sh")
    shutil.copy2(vrai / "scripts" / "lib" / "python.sh", base / "scripts" / "lib" / "python.sh")
    (base / "brain-engine" / "db.py").write_text(FAUX_DB, encoding="utf-8")
    relais = base / "brain-engine" / ".venv" / "bin" / "python3"
    relais.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    relais.chmod(0o755)
    if (vrai / "brain-engine" / "core").is_dir():
        (base / "brain-engine" / "core").symlink_to(vrai / "brain-engine" / "core")
    return base


def joue(base: Path, port: int) -> str:
    env = dict(os.environ, BRAIN_PORT=str(port))
    r = subprocess.run(
        ["bash", str(base / "scripts" / "file-lock.sh"),
         "acquire", "temoin/fichier.md", "sess-20260101-0000-temoin", "5"],
        capture_output=True, text=True, env=env, timeout=30)
    return (r.stdout or "") + (r.stderr or "")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    a = p.parse_args()
    vrai = a.brain.expanduser().resolve()
    if not (vrai / "scripts" / "file-lock.sh").is_file():
        print(f"❌ file-lock.sh introuvable sous {vrai}")
        return 1

    print("LOCK — le message dit-il ce que le moteur a vraiment fait ?\n")

    with tempfile.TemporaryDirectory(prefix="temoin-lock-") as tmp:
        base = faux_brain(Path(tmp) / "brain", vrai)
        socle = {"ok": True, "filepath": "temoin/fichier.md",
                 "holder": "sess-20260101-0000-temoin"}

        cas = [
            # Le contrat d aujourd hui : le moteur lit les verrous la ou ils
            # sont ecrits et nomme les bases lues — il ne consulte plus aucun
            # peer, le script ne doit donc pas l affirmer.
            ("les bases lues sont NOMMEES",
             dict(socle, reseau=["main", "laptop"]),
             lambda s: "verrous du reseau lus (main, laptop)" in s
             and "peers consultes" not in s),
            # Les trois suivants : un moteur d avant la lecture du reseau, que le script
            # sait encore lire.
            ("un peer muet est NOMME",
             dict(socle, peers_injoignables=["laptop"]),
             lambda s: "NON consulte" in s and "laptop" in s),
            ("aucun peer muet : l affirmation est permise",
             dict(socle, peers_injoignables=[]),
             lambda s: "peers consultes" in s and "NON consulte" not in s),
            ("cle absente : le script DOUTE au lieu d affirmer",
             dict(socle),
             lambda s: "ne dit pas s il a joint" in s and "peers consultes" not in s),
        ]

        for nom, corps, attendu in cas:
            _Factice.corps = corps
            srv = http.server.HTTPServer(("127.0.0.1", port_libre()), _Factice)
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                sortie = joue(base, port)
            finally:
                srv.shutdown()
            verifie(nom, attendu(sortie), True)
            if not attendu(sortie):
                print(f"     sortie : {sortie.strip()[:300]}")

    print()
    if _ko:
        print(f"  ❌ {_ko} cas sur {_ok + _ko} — le message ne suit plus ce que")
        print("     le moteur rapporte. Un mutex qui affirme ce qu'il n'a pas")
        print("     verifie vaut moins qu'un mutex qui se tait.")
        return 1
    print(f"  ✅ les {_ok} cas passent — le message dit ce que le moteur a fait")
    return 0


if __name__ == "__main__":
    sys.exit(main())
