"""Faux moteur pour le témoin du {@html} de brain-ui — port 18801, jamais la prod.
Sert UNE page de docs piégée : les trois formes d'HTML actif qu'un .md peut porter."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PIEGE = """# Page piégée

<img src="x" onerror="document.body.setAttribute('data-pwned','onerror')">

<script>document.body.setAttribute('data-pwned-script','1')</script>

[clic](javascript:alert(1))

Texte **normal** qui doit rester.
"""

class H(BaseHTTPRequestHandler):
    def _json(self, obj):
        corps = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        if self.path == "/docs":
            self._json({"docs": [{"name": "piege", "label": "Piège", "groupe": "t", "ordre": 1, "path": "/docs/piege.md"}]})
        elif self.path == "/docs/piege.md":
            self._json({"name": "piege", "content": PIEGE})
        else:
            self._json({})

    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", 18801), H).serve_forever()
