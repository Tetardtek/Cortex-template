#!/usr/bin/env python3
"""Un peer injoignable se distingue-t-il d'un peer sans rien ? — ne le 15/09.

Ce qui pourrirait en silence sans lui : **le Dashboard montre une machine en
ligne qui ne l'est pas.**

`_fetch_peer_claims` attrapait toute exception et rendait `[]`. `bsi_network`
testait pourtant :

    if peer_claims is not None and isinstance(peer_claims, list):
        status = 'online'
    else:
        status = 'offline'

Une liste vide passe les deux conditions. **La branche `offline` n'etait
atteignable par aucune valeur** que la fonction pouvait rendre. Un peer eteint
s'affichait `online, claims_open: 0` — trait pour trait comme un peer allume
sans session en cours. Les deux etats les plus differents du reseau BSI se
ressemblaient exactement.

C'est le motif deja ecrit dans `collaboration.md` :

    une metrique qui n'a jamais rien enregistre ressemble a une metrique a zero

    python3 tools/peer_muet_nest_pas_peer_vide.py --brain ~/Dev/Brain

── Ce qu'il eprouve ────────────────────────────────────────────────────────

Trois etats du reseau, contre un peer pointe sur un port mort et un faux peer
qui repond vraiment. Le controle exige que les trois se DISTINGUENT :

    peer muet          -> `offline`
    peer joignable     -> `online`
    peer sans claim    -> `online`, claims_open 0   (et non `offline`)

Le troisieme est le contre-controle : corriger le premier en declarant
`offline` tout peer a zero claim echangerait un defaut contre un autre.

── Il n'ecrit rien ─────────────────────────────────────────────────────────

Le serveur est monte par `TestClient` en memoire, `brain_db.query` capture,
`_load_peers` remplace. Le service qui tourne n'est pas touche, et la base non
plus.
"""

from __future__ import annotations

import argparse
import http.server
import json
import socket
import sys
import threading
from pathlib import Path

_ok = _ko = 0

PORT_MORT = "http://127.0.0.1:9"       # discard — refuse la connexion


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


class _Peer(http.server.BaseHTTPRequestHandler):
    claims: list = []

    def do_GET(self):                                      # noqa: N802
        brut = json.dumps(type(self).claims).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def log_message(self, *a):
        pass


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def etat_du_peer(server, client, url: str) -> dict | None:
    vrai_query, vrai_peers = server.brain_db.query, server._load_peers
    try:
        server.brain_db.query = lambda sql, params=(): []
        server._load_peers = lambda: [{"name": "temoin-peer", "url": url}]
        r = client.get("/bsi/network")
    finally:
        server.brain_db.query = vrai_query
        server._load_peers = vrai_peers
    corps = r.json() if r.content else {}
    noeuds = corps.get("nodes", corps if isinstance(corps, list) else [])
    return next((n for n in noeuds if n.get("name") == "temoin-peer"), None)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default=str(Path.home() / "Dev/Brain"), type=Path)
    a = p.parse_args()
    moteur = a.brain.expanduser().resolve() / "brain-engine"
    if not (moteur / "server.py").is_file():
        print(f"❌ moteur introuvable sous {moteur}")
        return 1

    sys.path.insert(0, str(moteur))
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app, client=("127.0.0.1", 4242))
    print("RÉSEAU BSI — un peer muet se distingue-t-il d'un peer vide ?\n")

    # 1. Le peer muet
    muet = etat_du_peer(server, client, PORT_MORT)
    verifie("un peer injoignable est dit `offline`",
            (muet or {}).get("status"), "offline")

    # 2. Le peer qui repond, avec une session ouverte
    _Peer.claims = [{"sess_id": "sess-20260101-0000-temoin", "status": "open"}]
    srv = http.server.HTTPServer(("127.0.0.1", port_libre()), _Peer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        vivant = etat_du_peer(server, client, f"http://127.0.0.1:{srv.server_address[1]}")
    finally:
        srv.shutdown()
    verifie("un peer joignable est dit `online`",
            (vivant or {}).get("status"), "online")
    verifie("ses claims ouverts sont comptes",
            (vivant or {}).get("claims_open"), 1)

    # 3. Le contre-controle : un peer JOIGNABLE mais sans aucun claim doit
    #    rester `online`. Sans lui, on pourrait « corriger » le cas 1 en
    #    declarant offline tout peer a zero claim — un defaut pour un autre.
    _Peer.claims = []
    srv = http.server.HTTPServer(("127.0.0.1", port_libre()), _Peer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        vide = etat_du_peer(server, client, f"http://127.0.0.1:{srv.server_address[1]}")
    finally:
        srv.shutdown()
    verifie("un peer joignable SANS claim reste `online`",
            (vide or {}).get("status"), "online")

    # ── L'autre route qui agrege des peers ──────────────────────────────
    #
    # `GET /bsi/claims?include_peers=true` avait le meme angle mort, sous une
    # autre forme : sa reponse etait une LISTE plate de claims, sans place pour
    # « le laptop n'a pas repondu ». Un peer eteint et un peer sans session
    # rendaient exactement la meme chose. Corrige le 16/09 — elle rend un objet
    # dans ce mode.
    #
    # 🔴 Et la moitie qui compte autant : SANS le parametre, la reponse doit
    # rester une liste. Trois appelants consomment cette forme, dont
    # `Dashboard.tsx`, qui fait `Array.isArray(...) ? ... : []` — sur un objet
    # il n'echouerait pas, il afficherait zero claim EN SILENCE. Un
    # consommateur qui se degrade sans bruit ne signale pas la regression.
    vrai_query, vrai_peers = server.brain_db.query, server._load_peers
    try:
        server.brain_db.query = lambda sql, params=(): []
        server._load_peers = lambda: [{"name": "temoin-peer", "url": PORT_MORT}]
        sans = client.get("/bsi/claims").json()
        avec = client.get("/bsi/claims?include_peers=true").json()
    finally:
        server.brain_db.query = vrai_query
        server._load_peers = vrai_peers

    verifie("claims SANS include_peers : la forme LISTE est intacte",
            isinstance(sans, list), True)
    verifie("claims AVEC include_peers : un objet qui nomme le peer muet",
            (avec or {}).get("peers_injoignables") if isinstance(avec, dict) else None,
            ["temoin-peer"])

    # ── La cause, pas seulement l'effet ─────────────────────────────────
    #
    # Les trois cas ci-dessus mesurent ce que la ROUTE rend. Celui-ci mesure la
    # fonction qui la nourrit : c'est elle qui confondait les deux etats, et
    # c'est elle qu'on pourrait « simplifier » un jour en lui refaisant rendre
    # une liste vide sur echec — la route redeviendrait fausse sans qu'une
    # seule ligne de la route ait bouge.
    verifie("`_fetch_peer_claims` rend None sur un peer muet",
            server._fetch_peer_claims(PORT_MORT, timeout=1), None)

    # ── L'auto-epreuve ──────────────────────────────────────────────────
    #
    # Ce controle sait-il seulement rougir ? On rejoue le comportement D'AVANT
    # — la fonction rendant `[]` sur echec — et on verifie que le premier cas
    # bascule. Sans cette epreuve, un controle qui aurait cesse de mesurer
    # quoi que ce soit afficherait exactement les memes quatre ✅.
    vraie_fonction = server._fetch_peer_claims
    try:
        server._fetch_peer_claims = lambda url, timeout=2.0: []
        rejoue = etat_du_peer(server, client, PORT_MORT)
    finally:
        server._fetch_peer_claims = vraie_fonction
    verifie("auto-epreuve : l'ancien comportement redonne bien `online`",
            (rejoue or {}).get("status"), "online")

    print()
    if _ko:
        print(f"  ❌ {_ko} cas sur {_ok + _ko} — le reseau BSI confond deux etats")
        print("     qui n'ont rien a voir. Une machine eteinte et une machine")
        print("     au repos ne doivent pas se ressembler.")
        return 1
    print(f"  ✅ les {_ok} cas passent — muet, occupe et au repos se distinguent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
