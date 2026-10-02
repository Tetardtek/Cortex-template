#!/usr/bin/env python3
"""brain serve — les portes réseau du brain, une seule déclaration.

    brain serve                  les deux portes, au premier plan, surveillées
    brain serve http             le moteur seul (`server.py`)
    brain serve mcp              le serveur MCP seul (`mcp_server.py`)
    brain serve --declaration    ce qui serait lancé — rien n'est lancé
    brain serve --ports          les deux ports, en `CLÉ=valeur` — pour un script

`brain serve` LANCE les serveurs, il ne les remplace pas : `server.py` et
`mcp_server.py` portent les routes éprouvées, rien n'y est réécrit. Ce qui
change, c'est que leur configuration se décide à UN endroit.

── La déclaration ──────────────────────────────────────────────────────────

Avant, elle était écrite trois fois : dans chaque unité systemd
(`Environment=BRAIN_PORT=…`), dans `brain-engine.sh` (sa lecture de
`.env.local`, son `detect_mode`, son `source` des secrets), et en dur dans les
serveurs (7700, 7701). Elle se calcule ici, dans cet ordre — le plus fort en
dernier :

    les défauts          7700, 7701, les scopes du MCP local
    `.env.local`         du programme (`brain-engine/.env.local`)
    MYSECRETS            `brain-secrets/MYSECRETS` de la data — sauf en démo
    l'environnement      ce qui est déjà posé gagne toujours (une unité
                         systemd, un `BRAIN_PORT=… brain serve` à la main)

Le mode : `BRAIN_MODE`, sinon le premier `mode:` de `brain-compose.local.yml`,
sinon `dev` — la règle de `brain-engine.sh`, reprise telle quelle.

── Les secrets ne s'exécutent pas ──────────────────────────────────────────

`brain-engine.sh` faisait `source MYSECRETS` : chaque ligne du fichier était
EXÉCUTÉE par le shell. Ici il se lit comme systemd lit un `EnvironmentFile=` :
des lignes `CLÉ=valeur`, rien d'autre. Aucune valeur n'est jamais affichée —
`--declaration` dit « chargés », « absents » ou « non requis ».

── Un seul processus par porte ─────────────────────────────────────────────

`brain serve http` et `brain serve mcp` REMPLACENT leur processus par le
serveur (`os.execve`) : le PID que voient systemd et le fichier de PID de
`brain-engine.sh` est celui du serveur lui-même. Un enfant intermédiaire l'aurait
cassé : `stop` aurait tué l'intermédiaire et laissé le serveur tourner.

Sans argument, les deux portes tournent en enfants surveillés : si l'une
s'arrête, l'autre est arrêtée, et `brain serve` sort en erreur.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ICI = Path(__file__).resolve().parent

DEFAUTS = {
    'BRAIN_PORT': '7700',
    'BRAIN_MCP_PORT': '7701',
    # Le MCP lancé ici est LOCAL : il voit ce que voit le rôle `mcp` de
    # `server.py`. Sans cette ligne, il tombait sur le défaut étroit de
    # `mcp_server.py`, prévu pour un MCP exposé (Cortex-Template#9).
    'BRAIN_MCP_SCOPES': 'public,work,instance,satellite',
}

SERVEURS = {
    'http': 'server.py',
    'mcp': 'mcp_server.py',
}

ARRET_GRACIEUX = 10      # secondes laissées à une porte pour s'arrêter


# ── Lire ─────────────────────────────────────────────────────────────────────

def lire_fichier_env(chemin: Path) -> dict[str, str]:
    """Les `CLÉ=valeur` d'un fichier, comme systemd lit un `EnvironmentFile=`.
    Rien n'est exécuté : une ligne `$(…)` reste du texte. Pur, sauf la lecture."""
    valeurs: dict[str, str] = {}
    try:
        texte = chemin.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return valeurs
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith('#'):
            continue
        if ligne.startswith('export '):
            ligne = ligne[len('export '):].lstrip()
        cle, egal, valeur = ligne.partition('=')
        cle = cle.strip()
        if not egal or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cle):
            continue
        valeur = valeur.strip()
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in '"\'':
            valeur = valeur[1:-1]
        valeurs[cle] = valeur
    return valeurs


def mode_de(environ: dict[str, str], donnees: Path) -> str:
    """`BRAIN_MODE`, sinon le premier `mode:` indenté de `brain-compose.local.yml`,
    sinon `dev` — la règle de `brain-engine.sh` (`detect_mode`)."""
    if environ.get('BRAIN_MODE'):
        return environ['BRAIN_MODE']
    try:
        texte = (donnees / 'brain-compose.local.yml').read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return 'dev'
    for ligne in texte.splitlines():
        m = re.match(r'^ +mode:\s*(\S+)', ligne)
        if m:
            return m.group(1).strip('"\'')
    return 'dev'


@dataclass
class Declaration:
    mode: str
    secrets: str                      # 'chargés' | 'absents' | 'non requis (demo)'
    environ: dict[str, str] = field(repr=False)

    @property
    def port_http(self) -> str:
        return self.environ['BRAIN_PORT']

    @property
    def port_mcp(self) -> str:
        return self.environ['BRAIN_MCP_PORT']


def declarer(environ: dict[str, str], donnees: Path, programme: Path) -> Declaration:
    """La déclaration des deux portes. Pur au sens où tout lui est passé :
    l'environnement de départ, la racine des données, celle du programme."""
    mode = mode_de(environ, donnees)
    final = dict(DEFAUTS)
    final.update(lire_fichier_env(programme / '.env.local'))
    secrets_chemin = donnees / 'brain-secrets' / 'MYSECRETS'
    if mode == 'demo':
        secrets = 'non requis (demo)'
    elif secrets_chemin.is_file():
        final.update(lire_fichier_env(secrets_chemin))
        secrets = 'chargés'
    else:
        secrets = 'absents'
    final.update(environ)             # ce qui est posé gagne toujours
    final['BRAIN_MODE'] = mode
    final.setdefault('BRAIN_ROOT', str(donnees))
    return Declaration(mode=mode, secrets=secrets, environ=final)


def commande(porte: str, programme: Path, python: str = sys.executable) -> list[str]:
    return [python, str(programme / SERVEURS[porte])]


def resume(decl: Declaration, programme: Path) -> list[str]:
    """Ce que `--declaration` affiche. Jamais une valeur de secret : les ports,
    le mode, la racine, et l'état des secrets en un mot."""
    return [
        f"mode     : {decl.mode}",
        f"racine   : {decl.environ['BRAIN_ROOT']}",
        f"http     : {decl.port_http}  ({programme / SERVEURS['http']})",
        f"mcp      : {decl.port_mcp}  ({programme / SERVEURS['mcp']})",
        f"secrets  : {decl.secrets}",
    ]


# ── Lancer ───────────────────────────────────────────────────────────────────

def lancer_une(porte: str, decl: Declaration, programme: Path) -> None:
    """Remplace CE processus par le serveur — ne revient pas."""
    cmd = commande(porte, programme)
    os.chdir(decl.environ['BRAIN_ROOT'])
    os.execve(cmd[0], cmd, decl.environ)


def surveiller(enfants: dict[str, subprocess.Popen], dire=print) -> int:
    """Attend que l'une des portes s'arrête, arrête l'autre, rend un code de
    sortie non nul. Ctrl+C ou SIGTERM arrêtent les deux, et rendent 0."""
    arret_demande = False

    def demander_arret(signum, _frame):
        nonlocal arret_demande
        arret_demande = True

    anciens = {s: signal.signal(s, demander_arret) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        tombee = None
        while not arret_demande and tombee is None:
            for nom, p in enfants.items():
                if p.poll() is not None:
                    tombee = nom
                    break
            else:
                time.sleep(0.2)
        if tombee:
            dire(f"❌ la porte {tombee} s'est arrêtée (code {enfants[tombee].returncode}) "
                 f"— arrêt de l'autre")
        for nom, p in enfants.items():
            if p.poll() is None:
                p.terminate()
        limite = time.monotonic() + ARRET_GRACIEUX
        for p in enfants.values():
            try:
                p.wait(timeout=max(0.1, limite - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        return 0 if arret_demande and tombee is None else 1
    finally:
        for s, h in anciens.items():
            signal.signal(s, h)


def lancer_les_deux(decl: Declaration, programme: Path) -> int:
    enfants = {
        porte: subprocess.Popen(commande(porte, programme), env=decl.environ,
                                cwd=decl.environ['BRAIN_ROOT'])
        for porte in ('http', 'mcp')
    }
    print(f"▶ brain serve — http :{decl.port_http} · mcp :{decl.port_mcp} "
          f"— Ctrl+C pour arrêter")
    return surveiller(enfants)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog='brain serve', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('porte', nargs='?', choices=sorted(SERVEURS),
                   help='une seule porte (sans : les deux, surveillées)')
    p.add_argument('--declaration', action='store_true',
                   help='afficher ce qui serait lancé, sans rien lancer')
    p.add_argument('--ports', action='store_true',
                   help='les deux ports, en CLÉ=valeur — ce que brain-engine.sh lit')
    args = p.parse_args(argv)

    sys.path.insert(0, str(ICI))
    from racines import DONNEES, PROGRAMME       # BRAIN_ROOT reçue, ou déduite

    decl = declarer(dict(os.environ), DONNEES, PROGRAMME)
    if args.declaration:
        print('\n'.join(resume(decl, PROGRAMME)))
        return 0
    if args.ports:
        # Les ports que `brain-engine.sh` vérifie (« déjà tenu ? ») sont ceux que
        # les serveurs ouvriront : une seule lecture, celle-ci. Rien d'autre ne
        # sort — ni le mode, ni une valeur de MYSECRETS.
        print(f"BRAIN_PORT={decl.port_http}\nBRAIN_MCP_PORT={decl.port_mcp}")
        return 0
    if args.porte:
        lancer_une(args.porte, decl, PROGRAMME)
        return 1                                  # jamais atteint : execve
    return lancer_les_deux(decl, PROGRAMME)


if __name__ == '__main__':
    sys.exit(main())
