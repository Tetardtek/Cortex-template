#!/usr/bin/env python3
"""Le contrôle du contrat refuse-t-il vraiment ? —.

Dix cas : six dérives refusées, trois choses légitimes laissées passer, et un
témoin sur l'instrument lui-même. Sur des fixtures jetables — **le moteur
vivant n'est jamais touché**, ni lu autrement que par le contrôle en conditions
réelles.

    python3 tools/test_parite_capacites.py

── Ce que les trois derniers cas ont appris, le 10/09 ──────────────────────

Les sept premiers cas n'employaient que `get` et `post`. Ni le banc ni le
contrôle ne lisaient `@app.patch`, et personne ne pouvait s'en apercevoir :
`PATCH /bsi/claims/{sess_id}` — une **écriture** sur la table des claims —
n'était ni comptée dans les routes, ni refusée comme non déclarée. Elle
n'existait pour aucun des deux.

Vérifié par sabotage, en retirant `patch` de `VERBES` : les deux cas PATCH
tombent. Et le troisième cas révèle mieux que ça — **c'est le témoin sur
l'instrument qui rougit en premier**, « verbe inconnu du banc », sans qu'on ait
eu besoin de deviner quel verbe manquait. Une liste blanche qui ignore en
silence ce qu'elle ne connaît pas ne contrôle rien ; celle qui refuse l'inconnu
se répare toute seule.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

OUTIL = Path(__file__).resolve().parent / "parite_capacites.py"

SERVEUR = """
@app.get('/search')
def s(): ...
@app.get('/health')
def h(): ...
"""

MCP = """
@mcp.tool()
def brain_search():
    results = run_single_query(q)
@mcp.tool()
def brain_version():
    ...
"""

CONTRAT_JUSTE = """
capacites:
  brain_search:
    nature: core
    brique: recherche
    http: ["GET /search"]
    mcp: brain_search
    mecanisme: memoire
  health:
    nature: diagnostic
    brique: ~
    http: ["GET /health"]
    mcp: ~
"""


def faux_brain(racine: Path, serveur: str, mcp: str) -> Path:
    brain = racine / "brain"
    (brain / "brain-engine").mkdir(parents=True)
    (brain / "brain-engine" / "server.py").write_text(serveur, encoding="utf-8")
    (brain / "brain-engine" / "mcp_server.py").write_text(mcp, encoding="utf-8")
    return brain


def jouer(brain: Path, contrat: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False,
                                     encoding="utf-8") as f:
        f.write(contrat)
        chemin = f.name
    r = subprocess.run([sys.executable, str(OUTIL), "--brain", str(brain),
                        "--contrat", chemin], capture_output=True, text=True)
    Path(chemin).unlink(missing_ok=True)
    return r.returncode, r.stdout + r.stderr


CAS = [
    ("l'accord parfait — ne doit PAS rougir",
     SERVEUR, MCP, CONTRAT_JUSTE, False, None),

    ("une route ajoutee au serveur, absente du contrat",
     SERVEUR + "\n@app.post('/nouvelle')\ndef n(): ...\n", MCP, CONTRAT_JUSTE,
     True, "absente(s) du contrat"),

    ("une route declaree qui n'existe plus",
     "@app.get('/health')\ndef h(): ...\n", MCP, CONTRAT_JUSTE,
     True, "absente(s) du serveur"),

    ("un outil MCP ajoute, absent du contrat",
     SERVEUR, MCP + "\ndef brain_nouveau():\n    ...\n", CONTRAT_JUSTE,
     True, "absent(s) du contrat"),

    ("un outil declare qui n'existe plus",
     SERVEUR, "def brain_version():\n    ...\n", CONTRAT_JUSTE,
     True, "absent(s) du MCP"),

    # Le mecanisme d'acces declare a tort. `brain_search` importe le moteur en
    # memoire ; un contrat qui le dirait `http` mentirait sur le CHEMIN, sans
    # qu'aucune surface ne bouge. C'est la derive qui a echappe trois fois.
    ("un mecanisme d'acces declare a tort",
     SERVEUR, MCP, CONTRAT_JUSTE.replace("mecanisme: memoire", "mecanisme: http"),
     True, "déclaré(s) à tort"),

    # Temoin negatif : l'asymetrie DECLAREE ne doit pas rougir. C'est la
    # difference entre « exiger la parite » et « exiger qu'elle soit dite ».
    ("une asymetrie declaree — ne doit PAS rougir",
     SERVEUR + "\n@app.get('/docs')\ndef d(): ...\n", MCP,
     CONTRAT_JUSTE + """  docs:
    nature: instance
    brique: ~
    http: ["GET /docs"]
    mcp: ~
""", False, None),

    # ── Les trois cas ajoutes le 10/09 ──────────────────────────────────────
    #
    # Le controle ignorait le verbe `patch` : ni le banc ni lui ne le lisaient.
    # `PATCH /bsi/claims/{sess_id}` — une ECRITURE sur la table des claims —
    # etait donc invisible aux deux, depuis toujours. Aucun des sept cas
    # ci-dessus ne pouvait l'attraper : ils n'employaient que get et post.
    #
    # Ce qui a manque n'est pas un verbe, c'est un TEMOIN SUR L'INSTRUMENT.
    # D'ou le troisieme cas : un verbe que le banc ne connait pas doit faire
    # rougir, pas disparaitre.

    ("une route PATCH non declaree — le trou du 10/09",
     SERVEUR + "\n@app.patch('/nouvelle/{id}')\ndef n(): ...\n", MCP, CONTRAT_JUSTE,
     True, "absente(s) du contrat"),

    ("une route PATCH declaree — ne doit PAS rougir",
     SERVEUR + "\n@app.patch('/nouvelle')\ndef n(): ...\n", MCP,
     CONTRAT_JUSTE + """  nouvelle:
    nature: instance
    brique: ~
    http: ["PATCH /nouvelle"]
    mecanisme_http: ~
    mcp: ~
""", False, None),

    ("un verbe HTTP que le banc ne sait pas lire",
     SERVEUR + "\n@app.head('/sonde')\ndef s(): ...\n", MCP, CONTRAT_JUSTE,
     True, "inconnu(s) du banc"),
]


def main() -> int:
    echecs = 0
    for nom, serveur, mcp, contrat, doit_rougir, motif in CAS:
        with tempfile.TemporaryDirectory() as d:
            brain = faux_brain(Path(d), serveur, mcp)
            code, sortie = jouer(brain, contrat)
        rouge = code != 0
        ok = rouge == doit_rougir
        detail = ""
        if ok and motif and motif not in sortie:
            ok, detail = False, f"rougit, mais sans dire « {motif} »"
        elif not ok:
            detail = "a laisse passer" if doit_rougir else "rougit a tort"
        print(f"  {'✅' if ok else '❌'} {nom}" + (f"  — {detail}" if detail else ""))
        if not ok:
            echecs += 1

    print()
    if echecs:
        print(f"❌ {echecs} cas sur {len(CAS)} — le controle ne fait pas ce qu'il dit")
        return 1
    print(f"✅ {len(CAS)} cas — il refuse les six derives, laisse passer "
          f"l'asymetrie DECLAREE, et se plaint d'un verbe qu'il ne sait pas lire")
    return 0


if __name__ == "__main__":
    sys.exit(main())
