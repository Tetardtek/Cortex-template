#!/usr/bin/env python3
"""`bsi-claim.sh open` passe-t-il vraiment par le moteur ?

Ce qui pourrirait en silence sans lui : **un repli qui réussit sans le dire.**
Depuis le 11/09, `cmd_open` appelle `POST /bsi/claims` et ne retombe sur
l'écriture locale que si le moteur ne répond pas. Un repli muet recréerait
exactement le trou qu'on vient de boucher — deux portes, deux comportements.

    python3 tools/eprouver_porte_bsi_claim.py --brain ~/Dev/Brain

── Il n'écrit RIEN, et c'est une contrainte, pas un confort ────────────────

`scripts/file-lock.sh` a rencontré le même besoin et l'a documenté : un témoin
qui ouvre un vrai claim à chaque passe de `brain doctor` **devient un
écrivain**. Ici le script est lancé contre un **faux brain** — un arbre
temporaire dont le `brain-engine/db.py` capture au lieu d'écrire — et contre un
**serveur factice** qui rend le code qu'on lui demande.

Aucune ligne ne part vers `claims`, et le contrôle est donc rejouable autant de
fois qu'on veut.

── Ce qu'il éprouve ────────────────────────────────────────────────────────

    statique    `cmd_open` appelle le moteur, et n'écrit pas lui-même
    2xx         succès, et le script n'écrit RIEN en local
    overlap     un chevauchement rapporté par la route est AFFICHÉ
    409         refus, exit 1, aucune écriture
    422         refus, exit 1, aucune écriture
    500         exit 2 — on ne se rabat PAS sur une vraie erreur du moteur
    injoignable repli local, avec l'avertissement, et l'écriture COMPLÈTE

Le dernier est le cœur : en repli, le script doit écrire **tout** ce que la
route écrirait — story, handoff, projet, dérivation de session. Un repli qui
écrit moins est une perte silencieuse.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}",
              file=sys.stderr)


FAUX_DB = '''
import json, os
SORTIE = os.environ["TEMOIN_SORTIE"]
BACKEND = "dolt"
def _note(e):
    with open(SORTIE, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, default=str) + "\\n")
CLAIMS = json.loads(os.environ.get("TEMOIN_CLAIMS", "[]"))
def query(sql, params=()):
    s = " ".join(sql.split())
    if "SHOW COLUMNS FROM claims LIKE 'handoff_level'" in s:
        return [{"Field": "handoff_level", "Type": "enum('NO','SEMI','SEMI+','FULL')"}]
    # `cmd_close` lit `opened_at` pour calculer la duree. Sans cette branche il
    # recoit [], conclut « claim deja ferme » et n'ecrit RIEN — l'epreuve
    # mesurerait alors une porte muette et la prendrait pour un succes.
    # Avec l'identite (BRAIN-077), `cmd_close` lit aussi `agent_session` : la
    # requete porte alors une colonne de plus. Les deux formes sont reconnues.
    if s.startswith("SELECT sess_id, opened_at") and "FROM claims WHERE sess_id" in s:
        return [c for c in CLAIMS
                if c.get("sess_id") == params[0] and c.get("status") == "open"]
    if "FROM claims WHERE status = 'open'" in s:
        return CLAIMS
    return []
def query_one(sql, params=()):
    r = query(sql, params)
    return r[0] if r else None
# Depuis BRAIN-078, le repli lit les claims ouverts du RÉSEAU (la base et les
# branches des machines satellites) : `db.claims_du_reseau`. Le faux rend le
# même monde que `query` — sans branche, comme une instance d'une seule machine.
# Sans elle, le repli plantait sur une fonction absente et l'épreuve tombait
# (29/09) : le faux doit suivre l'interface du vrai, encore.
def claims_du_reseau(where="1=1", params=(), colonnes="*"):
    return [dict(c, _branche=None) for c in CLAIMS]
def execute(sql, params=(), commit_msg=None, tables=None):
    _note({"quoi": "execute", "sql": " ".join(sql.split()), "params": list(params)})
    return 1
def count(table, where="1=1"):
    return 0
# Ce que le code reel appelle depuis BRAIN-077 : `BSI(db.depot())` demande si
# la base porte l'identite. Sans ces trois fonctions, le faux `db` imitait une
# interface qui n'existait plus — l'epreuve est tombee le 26/09 sans que rien ne
# la relance.
IDENTITE = os.environ.get("TEMOIN_IDENTITE", "1") == "1"
def colonne_existe(table, colonne):
    return IDENTITE if colonne == "agent_session" else True
def table_existe(table):
    return True
def depot():
    import sys
    return sys.modules[__name__]
'''

FAUX_MIGRATE = '''
import json, os
def migrate_sessions_backend():
    with open(os.environ["TEMOIN_SORTIE"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"quoi": "deriver_session"}) + "\\n")
    return 1
'''


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Factice(http.server.BaseHTTPRequestHandler):
    code = 200
    corps: dict = {}

    recu: dict = {}

    def do_POST(self):                                     # noqa: N802
        self._repondre()

    def do_PATCH(self):                                    # noqa: N802
        self._repondre()

    def _repondre(self):
        lu = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        # Le corps RECU est garde : c'est lui qui dit si la bascule de `close`
        # envoie bien les huit champs, ou si elle en a perdu en route.
        type(self).recu = json.loads(lu) if lu else {}
        type(self).recu["_chemin"] = self.path
        brut = json.dumps(type(self).corps).encode()
        self.send_response(type(self).code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def log_message(self, *a):                             # silence
        pass


def lance_factice(code: int, corps: dict):
    _Factice.code, _Factice.corps = code, corps
    port = port_libre()
    srv = http.server.HTTPServer(("127.0.0.1", port), _Factice)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def joue(faux: Path, port: int, argv: list[str],
         claims: list | None = None, agent: str | None = None) -> tuple[int, list[dict], str]:
    """Lance le script contre `port`, rend (exit, ecritures, sortie).

    `claims` est le monde que le faux `db` rendra en lecture — necessaire pour
    `close`, qui lit avant d'ecrire. `open` n'en a pas besoin : il n'attend
    rien en base.
    """
    sortie = faux / "capture.jsonl"
    sortie.unlink(missing_ok=True)
    env = dict(os.environ, TEMOIN_SORTIE=str(sortie), BRAIN_PORT=str(port),
               TEMOIN_CLAIMS=json.dumps(claims or []))
    # 🔴 L'identite de session ne s'HERITE pas : lance depuis une session
    # Claude, l'epreuve prenait le chemin de l'identite ; depuis un shell, non —
    # le verdict du doctor dependait de qui le lancait (27/09). Chaque cas la
    # pose lui-meme.
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    if agent:
        env["CLAUDE_CODE_SESSION_ID"] = agent
    # Ni le répertoire courant : `python3 -` met `''` en tête de `sys.path`, et
    # lancé depuis le dépôt myeline, le `core/` du répertoire suffisait au
    # repli — l'épreuve passait là, tombait depuis `~/Dev/Brain`.
    r = subprocess.run(["bash", str(faux / "scripts" / "bsi-claim.sh")] + argv,
                       capture_output=True, text=True, env=env, timeout=30,
                       cwd=faux)
    evts = ([json.loads(l) for l in sortie.read_text().splitlines()]
            if sortie.exists() else [])
    return r.returncode, evts, (r.stdout or "") + (r.stderr or "")


def corps_de(texte: str, nom: str) -> str:
    """Le corps d une fonction du heredoc Python, delimite par l AST.

    ⚠️ Delimitait par `texte.find("def suivante():")` jusqu au 16/09. C est
    fragile d une facon precise : toute fonction inseree ENTRE les deux se
    retrouve comptee dans la premiere. C est arrive en basculant `close` —
    `_fermer_en_repli` s est glissee entre `cmd_open` et `cmd_close`, son
    `db.execute` a ete attribue a `cmd_open`, et la garantie « cmd_open
    n ecrit pas lui-meme » est tombee sur un code parfaitement sain.

    Un faux positif d un controle coute autant qu un faux negatif : on apprend
    a l ignorer. On parse.
    """
    import ast as _ast
    m = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF", texte, re.S)
    source = m.group(1) if m else texte
    try:
        arbre = _ast.parse(source)
    except SyntaxError:
        return ""
    for n in _ast.walk(arbre):
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and n.name == nom:
            return _ast.get_source_segment(source, n) or ""
    return ""


def main() -> int:
    p = argparse.ArgumentParser(description="La porte BSI passe-t-elle par le moteur ?")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()
    script = brain / "scripts" / "bsi-claim.sh"
    if not script.is_file():
        print("⏭️  SKIP scripts/bsi-claim.sh introuvable.", file=sys.stderr)
        return 0

    texte = script.read_text(encoding="utf-8")

    # ── 1. Statique : la porte appelle le moteur ────────────────────────────
    corps_open = corps_de(texte, "cmd_open")
    verifie("cmd_open appelle le moteur",
            "par_le_moteur(" in corps_open, True)
    verifie("cmd_open n'écrit pas lui-même (le repli s'en charge)",
            "db.execute(" in corps_open, False)

    with tempfile.TemporaryDirectory(prefix="temoin-bsi-") as tmp:
        faux = Path(tmp)
        (faux / "scripts").mkdir()
        (faux / "brain-engine").mkdir()
        shutil.copy(script, faux / "scripts" / "bsi-claim.sh")
        # 🔴 L'interpréteur de la prod, pas celui de qui lance l'épreuve. Le
        # script source `lib/python.sh`, qui met le venv de `brain-engine` en
        # tête du PATH : sans lui, le faux brain prenait le `python3` hérité —
        # et le repli avec identité, qui passe par le CORE (`import core`),
        # tombait ou passait selon ce PATH (6 garanties, 27/09).
        # Le venv ne donne que l'interpréteur : le faux `db.py` reste le seul
        # écrivain. Un brain sans venv n'en reçoit pas — comme en prod.
        (faux / "scripts" / "lib").mkdir()
        if (brain / "scripts" / "lib" / "python.sh").is_file():
            shutil.copy(brain / "scripts" / "lib" / "python.sh",
                        faux / "scripts" / "lib" / "python.sh")
        if (brain / "brain-engine" / ".venv").is_dir():
            (faux / "brain-engine" / ".venv").symlink_to(brain / "brain-engine" / ".venv")
        # Le CORE, quand le brain le LIVRE (un fork : `brain-engine/core/`). Sur
        # l'instance, il vient du venv (installation éditable) ; chez un fork,
        # le venv ne l'a pas, et le repli avec identité tombait sur
        # `import core` — 7 garanties, alors que le vrai repli du fork écrit
        # bien (éprouvé le 2/10 sur un fork installé, moteur éteint).
        if (brain / "brain-engine" / "core").is_dir():
            (faux / "brain-engine" / "core").symlink_to(brain / "brain-engine" / "core")
        (faux / "brain-engine" / "db.py").write_text(FAUX_DB)
        (faux / "brain-engine" / "migrate.py").write_text(FAUX_MIGRATE)

        base = ["open", "sess-20260911-1200-temoin", "--scope", "zzz/temoin",
                "--type", "explore", "--story", "un angle", "--handoff", "SEMI"]

        # ── 2. Le moteur accepte : le script n'écrit RIEN en local ──────────
        srv, port = lance_factice(200, {"ok": True, "sess_id": "sess-20260911-1200-temoin",
                                        "project": "zzz", "overlap": []})
        code, evts, sortie = joue(faux, port, base)
        srv.shutdown()
        verifie("2xx — exit 0", code, 0)
        verifie("2xx — aucune écriture locale",
                [e for e in evts if e["quoi"] == "execute"], [])
        verifie("2xx — le claim est annoncé ouvert", "Claim ouvert" in sortie, True)

        # ── 3. Un chevauchement rapporté doit être AFFICHÉ ──────────────────
        #
        # Le shell l'affichait, la route se taisait : basculer aurait perdu
        # l'avertissement sans qu'aucune comparaison d'écritures ne le montre.
        srv, port = lance_factice(200, {
            "ok": True, "sess_id": "sess-20260911-1200-temoin", "project": "zzz",
            "overlap": [{"sess_id": "sess-20260101-0000-autre", "scope": "zzz"}]})
        code, evts, sortie = joue(faux, port, base)
        srv.shutdown()
        verifie("overlap — le chevauchement est dit", "SCOPE OVERLAP" in sortie, True)
        verifie("overlap — l'autre claim est nommé",
                "sess-20260101-0000-autre" in sortie, True)

        # ── 4. Les refus du moteur font autorité ────────────────────────────
        for http_code, exit_attendu, quoi in ((409, 1, "scope verrouillé"),
                                              (422, 1, "validation refusée")):
            srv, port = lance_factice(http_code, {"detail": quoi})
            code, evts, sortie = joue(faux, port, base)
            srv.shutdown()
            verifie(f"{http_code} — exit {exit_attendu}", code, exit_attendu)
            verifie(f"{http_code} — aucune écriture",
                    [e for e in evts if e["quoi"] == "execute"], [])

        # ── 5. 🔴 Une vraie erreur du moteur n'autorise PAS le repli ────────
        srv, port = lance_factice(500, {"detail": "boum"})
        code, evts, sortie = joue(faux, port, base)
        srv.shutdown()
        verifie("500 — exit 2, et non un repli silencieux", code, 2)
        verifie("500 — aucune écriture : se rabattre masquerait le défaut",
                [e for e in evts if e["quoi"] == "execute"], [])

        # ── 6. Le moteur injoignable : repli COMPLET, et annoncé ────────────
        mort = port_libre()          # personne n'écoute dessus
        code, evts, sortie = joue(faux, mort, base)
        verifie("injoignable — exit 0", code, 0)
        verifie("injoignable — le repli est ANNONCÉ",
                "repli LOCAL" in sortie, True)
        verifie("injoignable — l'avertissement dit ce qui manque",
                "n'engage que cette machine" in sortie, True)
        ecritures = [e for e in evts if e["quoi"] == "execute"]
        verifie("injoignable — le claim est écrit localement",
                len(ecritures), 1)
        if ecritures:
            params = [str(x) for x in ecritures[0]["params"]]
            for valeur, quoi in (("un angle", "story_angle"),
                                 ("SEMI", "handoff_level"),
                                 ("zzz", "project auto-extrait"),
                                 ("explore", "type")):
                verifie(f"repli — {quoi} n'est pas perdu", valeur in params, True)
        verifie("injoignable — la session est dérivée aussi",
                any(e["quoi"] == "deriver_session" for e in evts), True)

        # ── 6 bis. Le même repli, lancé DEPUIS une session d'agent ──────────
        # Le chemin que le doctor prenait sans le savoir quand on le lançait
        # depuis Claude Code : l'identité doit être écrite, dans le même REPLACE.
        code, evts, sortie = joue(faux, mort, base, agent="claude-temoin-repli")
        verifie("injoignable, avec identité — exit 0", code, 0)
        ecritures = [e for e in evts if e["quoi"] == "execute"]
        verifie("injoignable, avec identité — une seule écriture", len(ecritures), 1)
        verifie("injoignable, avec identité — l'identité est écrite",
                bool(ecritures) and "claude-temoin-repli" in [str(x) for x in ecritures[0]["params"]],
                True)

        # ── Le témoin négatif ───────────────────────────────────────────────
        #
        # ── 7. `close` passe aussi par le moteur ─────────────────
        #
        # `cmd_open` a bascule le 11/09, `cmd_close` le 16/09. Cet outil
        # n'eprouvait QUE l'ouverture, et le declarait vert : une paire
        # basculee a moitie ne se voyait donc pas — c'est exactement ce que ce
        # defaut a coute a trouver.
        #
        # 🔴 Ce qui compte ici n'est pas que le script appelle : c'est qu'il
        # envoie les HUIT champs. La route en accepte treize ; en perdre un
        # ne leverait rien, le claim se fermerait « correctement », et la
        # metabolisation de fin de session disparaitrait en silence. C'est ce
        # qui s'est produit le 22/08, 43 claims sur 43 sans duree.
        (faux / "scripts" / "bsi-claim.sh").write_text(texte)

        corps_close = corps_de(texte, "cmd_close")
        verifie("cmd_close appelle le moteur",
                "par_le_moteur(" in corps_close, True)
        verifie("cmd_close n'écrit pas lui-même (le repli s'en charge)",
                "db.execute(" in corps_close, False)

        fermer = ["close", "sess-20260911-1200-temoin", "--result", "success",
                  "--energy", "high", "--intention", "my-117", "--tags", "a,b",
                  "--deliverables", "un texte"]
        monde = [{"sess_id": "sess-20260911-1200-temoin", "scope": "zzz/temoin",
                  "type": "explore", "zone": "project", "status": "open",
                  "opened_at": "2026-01-01 00:00:00"}]

        srv, port = lance_factice(200, {"ok": True})
        _Factice.recu = {}
        code, evts, _ = joue(faux, port, fermer, claims=monde)
        recu = dict(_Factice.recu)
        srv.shutdown()

        verifie("close 2xx — aucune écriture locale",
                len([e for e in evts if e["quoi"] == "execute"]), 0)
        verifie("close 2xx — la route visée porte le sess_id",
                recu.get("_chemin"), "/bsi/claims/sess-20260911-1200-temoin")
        # Les SEPT champs que le script possede. `duration_min` n'est
        # deliberement PAS de la partie : depuis que `cmd_close` ne lit plus
        # rien en local, il ne peut plus la calculer — c'est la route qui la
        # derive de l'`opened_at` qu'elle lit elle-meme.
        envoyes = {"status", "closed_at", "result",
                   "energy", "intention", "tags", "deliverables"}
        verifie("close 2xx — les SEPT champs du script sont envoyés",
                envoyes - set(recu), set())
        # 🔴 Et la contrepartie, sans laquelle la garantie ci-dessus
        # s'affaiblirait : le script ne doit PAS envoyer `duration_min`. S'il
        # s'y remettait, il aurait re-lu en local — la bascule serait defaite
        # sans qu'une seule garantie tombe.
        verifie("close 2xx — `duration_min` n'est PAS envoyé (la route la calcule)",
                "duration_min" in recu, False)
        # Et le repli, lui, l'ecrit toujours : c'est LUI qui lit en local.
        attendus = envoyes | {"duration_min"}

        # 404 : le moteur dit que le claim n'existe pas. On le rapporte, on
        # n'ecrit pas, et on ne se rabat pas — sa reponse fait autorite.
        srv, port = lance_factice(404, {"detail": "Claim introuvable"})
        code, evts, _ = joue(faux, port, fermer, claims=monde)
        srv.shutdown()
        verifie("close 404 — aucune écriture locale",
                len([e for e in evts if e["quoi"] == "execute"]), 0)

        # 409 : deja ferme. Une fermeture ne se rejoue pas.
        srv, port = lance_factice(409, {"detail": "déjà closed"})
        code, evts, _ = joue(faux, port, fermer, claims=monde)
        srv.shutdown()
        verifie("close 409 — refus, exit 1, aucune écriture",
                (code, len([e for e in evts if e["quoi"] == "execute"])), (1, 0))

        # 500 : une VRAIE erreur du moteur. Se rabattre ici masquerait un
        # defaut au lieu de le montrer.
        srv, port = lance_factice(500, {"detail": "boom"})
        code, evts, _ = joue(faux, port, fermer, claims=monde)
        srv.shutdown()
        verifie("close 500 — exit 2, on ne se rabat PAS sur une vraie erreur",
                (code, len([e for e in evts if e["quoi"] == "execute"])), (2, 0))

        # Injoignable : le repli ecrit, et il ecrit COMPLET. Un repli qui
        # ecrirait moins serait la perte silencieuse que la bascule evite.
        code, evts, sortie = joue(faux, 9, fermer, claims=monde)
        ecr = [e for e in evts if e["quoi"] == "execute"]
        verifie("close injoignable — le repli écrit", len(ecr), 1)
        if ecr:
            sql = " ".join(ecr[0]["sql"].split())
            champs = {c.split("=")[0].strip()
                      for c in sql.split(" SET ", 1)[1].split(" WHERE ")[0].split(",")}
            verifie("close injoignable — le repli écrit les HUIT champs",
                    attendus - champs, set())
        verifie("close injoignable — le repli dit que le Dashboard ignore",
                "Dashboard" in sortie, True)

        # Ce contrôle voit-il seulement quelque chose ? On lui donne un script
        # amputé de son appel au moteur : il DOIT rougir sur le cas 2xx.
        ampute = texte.replace("reponse = par_le_moteur(\"POST\", \"/bsi/claims\", corps)",
                               "reponse = None")
        verifie("témoin — le script a bien pu être amputé", ampute != texte, True)
        (faux / "scripts" / "bsi-claim.sh").write_text(ampute)
        srv, port = lance_factice(200, {"ok": True, "project": "zzz", "overlap": []})
        code, evts, _ = joue(faux, port, base)
        srv.shutdown()
        verifie("témoin — sans l'appel, le script écrit en local (le contrôle "
                "sait donc voir la différence)",
                len([e for e in evts if e["quoi"] == "execute"]), 1)

        # Le meme temoin pour `close`. `open` avait le sien depuis le 11/09 ;
        # `close` n'en avait pas, et c'est precisement l'asymetrie qui a laisse
        # le defaut invisible : un outil qui n'eprouve qu'une moitie d'une paire
        # declare la paire verte.
        ampute_c = texte.replace(
            'reponse = par_le_moteur("PATCH", f"/bsi/claims/{sess_id}", corps)',
            "reponse = None")
        verifie("témoin close — le script a bien pu être amputé",
                ampute_c != texte, True)
        (faux / "scripts" / "bsi-claim.sh").write_text(ampute_c)
        srv, port = lance_factice(200, {"ok": True})
        code, evts, _ = joue(faux, port, fermer, claims=monde)
        srv.shutdown()
        verifie("témoin close — sans l'appel, le script ferme en local",
                len([e for e in evts if e["quoi"] == "execute"]), 1)
        (faux / "scripts" / "bsi-claim.sh").write_text(texte)

        # ── 8. `touch` : un signe de vie ne vaut que pour celui qui le donne ─
        #
        # L'incident du 27/09 : le hook `post-commit` appelle `touch`
        # sans cible, et « sans cible » repoussait TOUS les claims ouverts —
        # une session morte n'expirait jamais tant qu'une autre commitait.
        srv, port = lance_factice(200, {"ok": True, "touches": []})
        _Factice.recu = {}
        code, evts, _ = joue(faux, port, ["touch", "--quiet"], agent="session-x")
        verifie("touch, avec identité — exit 0", code, 0)
        verifie("touch, avec identité — le moteur reçoit la SESSION, pas « tous »",
                {k: v for k, v in _Factice.recu.items() if k != "_chemin"},
                {"agent_session": "session-x"})

        _Factice.recu = {}
        code, evts, sortie = joue(faux, port, ["touch"])
        verifie("touch, sans identité — exit 0", code, 0)
        verifie("touch, sans identité — AUCUNE requête (on ne sait pas qui vit)",
                _Factice.recu, {})
        verifie("touch, sans identité — aucune écriture",
                [e for e in evts if e["quoi"] == "execute"], [])
        verifie("touch, sans identité — il le dit", "rien n est repousse" in sortie, True)

        _Factice.recu = {}
        code, evts, _ = joue(faux, port, ["touch", "sess-20260911-1200-temoin"])
        verifie("touch <sess_id> — le moteur reçoit le claim nommé",
                _Factice.recu.get("sess_id"), "sess-20260911-1200-temoin")
        srv.shutdown()

        code, evts, _ = joue(faux, port_libre(), ["touch", "--quiet"], agent="session-x",
                             claims=[{"sess_id": "sess-x", "status": "open", "ttl_hours": 4}])
        ecr = [e for e in evts if e["quoi"] == "execute"]
        verifie("touch en repli, avec identité — l'écriture vise la session",
                bool(ecr) and "session-x" in [str(p) for p in ecr[0]["params"]], True)

    print()
    if _ko:
        print(f"❌ {_ko} garantie(s) tombée(s) — la porte BSI ne passe plus par "
              f"le moteur, ou son repli a maigri.\n", file=sys.stderr)
        return 1
    print(f"✅ {_ok} garanties — la porte passe par le moteur, et son repli dit "
          f"ce qu'il ne fait pas\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
