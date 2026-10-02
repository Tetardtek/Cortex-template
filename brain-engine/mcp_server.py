#!/usr/bin/env python3
"""
brain-engine/mcp_server.py — BE-4 MCP Server
Expose le brain comme source de contexte native pour Claude.

Transport : StreamableHTTP (MCP 1.x)
Port      : 7701 (défaut) — distinct du BaaS HTTP (7700)
Auth      : BRAIN_TOKEN_MCP dans MYSECRETS → passé via header x-api-key

Outils exposés :
  brain_search(query, top)  → recherche sémantique (zones public + work)
  brain_boot()              → contexte de boot (3 queries ciblées)
  brain_workflows()         → ce qui avance en autonomie (palier b)
  brain_agents(name)        → liste des agents ou contenu d'un agent
  brain_decisions(last)     → dernières décisions architecturales (ADRs)
  brain_focus()             → focus actuel du brain (direction + projets + blockers)
  brain_write(path, content)→ écrire un fichier dans le brain via PUT /brain/{path}
  brain_content(filter)     → pipeline contenu (contenu/atelier + contenu/publie)
  brain_content_promote()   → promouvoir un contenu (draft→ready→scheduled→published)

Usage :
  python3 brain-engine/mcp_server.py                 → port 7701 (défaut)
  BRAIN_MCP_PORT=8000 python3 brain-engine/mcp_server.py

Connexion Claude Code :
  claude mcp add --transport http brain http://127.0.0.1:7701/mcp
  Le chemin est /mcp : c'est là que le serveur répond (mesuré sur un fork
  neuf le 27/09).

  ⚠️ Vers CETTE instance, jamais une autre. Un MCP distant lit SON brain, pas
     le vôtre : une URL qui n'est pas la vôtre branche l'agent sur la mémoire
     de quelqu'un d'autre. Cette ligne portait un domaine, et le template la
     distribuait telle quelle — corrigé le 05/09.

Auth dans Claude Code :
  Settings → MCP → brain → Headers → x-api-key: <BRAIN_TOKEN_MCP>
"""

import hmac
import json
import os
import sys
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parent))
from rag import run_boot_queries, run_single_query, format_compact, format_full
from search import requete_faible, RechercheIndisponible

# ── Config ─────────────────────────────────────────────────────────────────────

BRAIN_MCP_PORT  = int(os.getenv('BRAIN_MCP_PORT') or 7701)
# Le moteur de CE brain : son port vient de BRAIN_PORT. Écrit 7700 en dur, un MCP
# lancé sur un autre port (un second brain, un bac d'essai) appelait le moteur de
# la PROD — `brain_write` y aurait écrit (relecture du 28/09).
BRAIN_API       = f"http://127.0.0.1:{int(os.getenv('BRAIN_PORT') or 7700)}"
BRAIN_TOKEN_MCP = os.getenv('BRAIN_TOKEN_MCP') or os.getenv('BRAIN_TOKEN')

# Scopes autorisés pour le token MCP.
# Défaut restreint = public+work : un MCP EXPOSÉ ne doit rien montrer d'autre.
# Le service LOCAL (7701) élargit via BRAIN_MCP_SCOPES — posé par l'unité
# `brain-mcp` que génère `brain-engine.sh install systemd` (le rôle `mcp` de
# server.py), comme le brain-mcp-local de la prod (Cortex-Template#9).
MCP_SCOPES = [s.strip() for s in (os.getenv('BRAIN_MCP_SCOPES') or 'public,work').split(',') if s.strip()]

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('brain-mcp')

# ── MCP Server ─────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name='brain',
    instructions=(
        'Brain-as-a-Service — mémoire sémantique de ce brain. '
        'Utilise brain_search pour trouver du contexte précis sur un sujet. '
        'Utilise brain_boot au démarrage d\'une session pour charger le contexte actif. '
        'Les résultats sont des chunks de fichiers markdown classés par pertinence. '
        'Zones accessibles : focus, todos, projets, agents, infrastructure.'
    ),
)


# ── Auth middleware ─────────────────────────────────────────────────────────────

# ── Confinement des chemins ────────────────────────────────────────────────────

# La data, reçue ou déduite par `racines.py` — résolue ici, pour la
# raison que dit le bloc « Content pipeline » plus bas.
from racines import DONNEES as _DONNEES, annonce as _annonce_racines
_BRAIN_ROOT = _DONNEES.resolve()


def _resolve_under(base: Path, *parts: str) -> Path:
    """Résout un chemin et garantit qu'il reste sous `base`.

    `BRAIN_ROOT / 'agents' / f'{name}.md'` sans contrôle laissait `../KERNEL`
    sortir du dossier : les scopes MCP excluent la zone kernel, la construction
    du chemin l'y ramenait. `is_relative_to` compare les composants — un
    `startswith` textuel accepterait un frère de même préfixe.
    """
    base   = base.resolve()
    target = base.joinpath(*parts).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f'chemin hors de {base.name}/')
    return target


_LOCALHOSTS = frozenset({'127.0.0.1', '::1', 'localhost'})


class BrainAuthMiddleware:
    """
    Wrapper ASGI — vérifie x-api-key avant chaque requête MCP.
    Note : les dunders Python (__call__) sont résolus sur la classe, pas l'instance.
    Un vrai wrapper ASGI est requis (monkey-patch d'instance ne fonctionne pas).

    Sans token configuré, le serveur ne répond QU'EN LOOPBACK. Auparavant
    l'absence de token désactivait le contrôle entièrement (`and self._token`) :
    le MCP, qui écoute sur 0.0.0.0, était alors ouvert à tout le réseau local.
    Une installation neuve n'a pas de token — c'était donc le comportement par
    défaut, pas un cas limite.
    """
    def __init__(self, app, token: str | None):
        self._app  = app
        self._token = token

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            client = (scope.get('client') or ('', 0))[0]
            # Un `X-Forwarded-For` : la requête a traversé un proxy, ou le
            # prétend. uvicorn réécrit `client` d'après cet en-tête, et
            # `X-Forwarded-For: 127.0.0.1` + `Host: 127.0.0.1` faisaient passer
            # une machine du réseau pour la machine elle-même — mesuré le 28/09
            # dans un réseau isolé : 200 sans jeton depuis 192.0.2.1. Même règle
            # que `_is_localhost` du moteur : pas de confiance locale.
            relaye = any(k == b'x-forwarded-for' for k, _ in scope.get('headers', []))
            if not self._token:
                if client not in _LOCALHOSTS or relaye:
                    log.warning('MCP sans token : requete non-loopback refusee (%s)', client)
                    await self._deny(send, 'aucun token configure — acces loopback uniquement')
                    return
            else:
                headers = dict(scope.get('headers', []))
                api_key = headers.get(b'x-api-key', b'').decode()
                if not hmac.compare_digest(api_key, self._token):
                    await self._deny(send, 'Unauthorized')
                    return
        await self._app(scope, receive, send)

    @staticmethod
    async def _deny(send, reason: str) -> None:
        await send({'type': 'http.response.start', 'status': 401,
                    'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body',
                    'body': json.dumps({'error': reason}).encode(), 'more_body': False})


mcp_app = BrainAuthMiddleware(mcp.streamable_http_app(), BRAIN_TOKEN_MCP)


# ── Outils MCP ─────────────────────────────────────────────────────────────────

@mcp.tool()
def brain_search(query: str, top: int = 5, full: bool = False) -> str:
    """
    Recherche sémantique dans le brain.

    Args:
        query : Question en langage naturel (ex: "comment fonctionne le BSI v2 ?")
        top   : Nombre de résultats (défaut: 5, max recommandé: 10)
        full  : True = chunks complets, False = extraits 120 chars (défaut)

    Returns:
        Bloc markdown avec les chunks les plus pertinents, triés par score.
        Chaque résultat indique le filepath source et un extrait du contenu.
    """
    log.info('brain_search query=%r top=%d full=%s', query, top, full)
    try:
        results = run_single_query(query, top_k=top, allowed_scopes=MCP_SCOPES)
    except RechercheIndisponible as panne:
        # Pas « Aucun résultat » : la recherche n'a pas eu lieu.
        return f"⚠️ Recherche indisponible — {panne}.\n{panne.conseil()}"
    if not results:
        return f'Aucun résultat pour : {query!r}'
    label = f'brain_search — {query}'
    # Un résultat de recherche ne dit jamais qu'il est du bruit : le score d'un
    # mauvais résultat peut dépasser celui d'un bon. L'avertissement porte donc
    # sur la requête, là où il est vérifiable.
    #
    # L'avertissement se place APRÈS le bloc, jamais dans le label :
    # `format_compact` insère le label entre parenthèses — `## Brain context (…)`
    # — et un saut de ligne l'y coupait en deux. Vu en lançant l'outil pour de
    # vrai après le redémarrage du service, pas en relisant le code.
    bloc = format_full(results, label=label) if full else format_compact(results, label=label)
    faible = requete_faible(query)
    if faible:
        bloc += f'\n> ⚠️  requête faible : {faible}\n'
    return bloc


@mcp.tool()
def brain_state() -> str:
    """
    Environnement fondamental du brain — dérivé en temps réel, jamais stocké.

    Retourne les unités systemd du brain (et pm2 s'il sert), la version brain
    (git), et les ports configurés. Layer 2 uniquement (localhost).

    À appeler en début de session pour connaître l'état de l'infrastructure
    sans avoir à demander "quel port ? quel service tourne ?".

    Returns:
        Bloc markdown structuré avec hostname, version, services, ports.
        "Indisponible" si brain-engine hors ligne.
    """
    import json
    import urllib.request
    log.info('brain_state')
    try:
        with urllib.request.urlopen(f'{BRAIN_API}/state', timeout=3) as resp:
            data = json.loads(resp.read())
        lines = [f'## Environnement fondamental\n']
        lines.append(f"**Machine** : {data.get('hostname', '?')}")
        lines.append(f"**Brain** : {data.get('brain_version', '?')}\n")
        unites = data.get('systemd', [])
        if unites:
            lines.append('**Services (systemd)**')
            lines.append('| Unité | État |')
            lines.append('|-------|------|')
            for u in unites:
                icon = '🔴' if u.get('active') == 'failed' else ('🟢' if u.get('active') == 'active' else '⚪')
                lines.append(f"| {u['name']} | {icon} {u.get('active','?')} ({u.get('sub','?')}) |")
        pm2 = data.get('pm2', [])
        if pm2:
            lines.append('**Services (pm2)**')
            lines.append('| Nom | Status | Restarts |')
            lines.append('|-----|--------|---------|')
            for p in pm2:
                icon = '🟢' if p.get('status') == 'online' else '🔴'
                lines.append(f"| {p['name']} | {icon} {p.get('status','?')} | {p.get('restarts',0)} |")
        ports = data.get('ports', {})
        if ports:
            lines.append(f"\n**Ports** : engine={ports.get('brain_engine','?')} · mcp={ports.get('brain_mcp','?')}")
        return '\n'.join(lines)
    except Exception as exc:
        log.warning('brain_state failed: %s', exc)
        return f'Environnement indisponible : {exc}'


@mcp.tool()
def brain_boot() -> str:
    """
    Charge le contexte de boot du brain.

    Séquence :
    1. brain_state() — environnement fondamental dérivé (services, ports)
    2. 3 queries RAG ciblées (décisions récentes, todos prioritaires, sprint actif)

    Le slot `brain/now.md` de BRAIN-016 a été retiré le 10/09 : il lisait un
    chemin qui n'a jamais existé sous cette forme. Voir le commentaire dans le
    corps, et BRAIN-016, supersédée le même jour.

    À appeler en début de session pour enrichir le contexte sans saturer le
    context window. Si la recherche est indisponible (Ollama, index vide), la
    section le DIT au lieu de disparaître.

    Returns:
        Bloc markdown additif avec contexte de boot complet.
    """
    log.info('brain_boot')
    sections = []

    # ── Le « slot garanti » a ete retire le 10/09 — il ne l'a jamais ete. ──
    #
    # Il lisait `Path(__file__).parent.parent / 'brain' / 'now.md'`, ce que
    # BRAIN-016 declarait en mars. Le chemin n'existe pas : `now.md` a migre a
    # la racine du brain, puis a ete remplace par `cap.md`, puis par l'API
    # `/focus` servie depuis Dolt. Aucun de ces remplacements n'a supersede
    # BRAIN-016 — ils sont consignes dans une ligne de changelog.
    #
    # L'outil tourne a chaque demarrage de session. Le slot n'a donc jamais ete
    # rempli une seule fois, et ne pouvait pas s'en plaindre : `if exists()`
    # puis `except: pass`, deux silences l'un derriere l'autre.
    #
    # BRAIN-016 est superseded depuis le 10/09. L'etat courant vient de `/focus`,
    # que `brain_focus()` expose deja.

    # 1. Environnement dérivé
    env = brain_state()
    if env and 'Indisponible' not in env:
        sections.append(env)

    # 2. RAG queries
    try:
        results = run_boot_queries(allowed_scopes=MCP_SCOPES)
    except RechercheIndisponible as panne:
        results = []
        sections.append(f"⚠️ Recherche sémantique indisponible — {panne}.\n{panne.conseil()}")
    if results:
        sections.append(format_compact(results, label='brain_boot'))

    return '\n\n---\n\n'.join(sections) if sections else ''


@mcp.tool()
def brain_workflows() -> str:
    """
    Retourne ce qui avance EN AUTONOMIE — le résumé du palier b (BRAIN-079).

    Returns:
        Bloc markdown : par projet au palier b ou c, ce que `dev/autonome`
        porte et que le tronc n'a pas, et les PR d'agents qui attendent un
        verdict. Utile en début de session : ce qui s'est fait sans vous.
    """
    import json
    import urllib.request
    log.info('brain_workflows')
    try:
        url = f'{BRAIN_API}/workflows'
        # La route interroge la forge (quelques secondes) : 70 s, au-delà de
        # son propre délai (60 s), pour que ce soit elle qui dise pourquoi.
        with urllib.request.urlopen(url, timeout=70) as resp:
            data = json.loads(resp.read())
        projets = data.get('projets', []) if isinstance(data, dict) else []
        note = data.get('note') if isinstance(data, dict) else None
        if not projets:
            return f"Rien en autonomie — {note}." if note else 'Rien en autonomie.'
        lines = ['## Ce qui avance en autonomie (palier b)\n']
        for p in projets:
            tete = f"### {p.get('projet', '?')} — palier {p.get('palier', '?')}"
            etat = p.get('etat')
            if etat != 'ok':
                lines.append(f"{tete} — {etat}{' : ' + p['message'] if p.get('message') else ''}")
                continue
            lines.append(f"{tete} — `dev/autonome` : {p.get('en_avance', 0)} commit(s) "
                         f"que `{p.get('tronc', '?')}` n'a pas")
            for titre in p.get('titres', []):
                lines.append(f"  · {titre}")
            for pr in p.get('attendent', []):
                lines.append(f"  ⏳ attend un verdict : {pr}")
            if p.get('en_avance'):
                lines.append(f"  → à relire d'un bloc : une PR `dev/autonome` → `{p.get('tronc')}`")
            lines.append('')
        return '\n'.join(lines)
    except Exception as exc:
        log.warning('brain_workflows failed: %s', exc)
        return f'Autonomie indisponible : {exc}'


@mcp.tool()
def brain_agents(name: str = '') -> str:
    """
    Retourne les agents disponibles dans le brain.

    Args:
        name : Nom de l'agent (sans extension .md). Si vide, retourne la liste
               complète. Exemple : "debug", "vps", "code-review".

    Returns:
        Liste des agents en tableau markdown (nom, status, context_tier, description)
        ou contenu brut du fichier agents/{name}.md si name fourni.
        Fallback filesystem si brain-engine indisponible.
    """
    import json
    import urllib.request
    log.info('brain_agents name=%r', name)

    if name:
        # Confiné à agents/ : `../KERNEL` sortait du dossier et ramenait la zone
        # kernel, que les scopes MCP excluent précisément.
        try:
            agent_path = _resolve_under(_BRAIN_ROOT / 'agents', f'{name}.md')
        except ValueError:
            log.warning('brain_agents : nom hors agents/ refuse (%r)', name)
            return f'Nom d\'agent invalide : {name}'
        if not agent_path.is_file():
            return f'Agent introuvable : agents/{name}.md'
        return agent_path.read_text(encoding='utf-8')

    # Liste via brain-engine
    try:
        with urllib.request.urlopen(f'{BRAIN_API}/agents', timeout=3) as resp:
            data = json.loads(resp.read())
        agents = data.get('agents', data) if isinstance(data, dict) else data
        if not agents:
            return 'Aucun agent trouvé.'
        # `context_tier` ne fait plus partie de la reponse de GET /agents
        # depuis BRAIN-072 ; `classification` porte l'information utile.
        lines = ['## Agents disponibles\n', '| Nom | Classification | Zone | Description |',
                 '|-----|----------------|------|-------------|']
        for ag in agents:
            nom   = ag.get('name', ag.get('id', '?'))
            classif = ag.get('classification', '—')
            zone  = ag.get('scope', '—')
            desc  = (ag.get('boot_summary') or ag.get('description') or '')[:80]
            lines.append(f'| {nom} | {classif} | {zone} | {desc} |')
        return '\n'.join(lines)
    except Exception as exc:
        log.warning('brain_agents HTTP failed, fallback filesystem: %s', exc)

    # Fallback filesystem
    agents_dir = BRAIN_ROOT / 'agents'
    if not agents_dir.exists():
        return 'Répertoire agents/ introuvable.'
    # Index et meta-fichiers (`_conventions`, gabarits) ne sont PAS des agents.
    #
    # 🔴 Mesure du 10/09 : ce repli les listait. La route `GET /agents` les
    # ecarte, et son commentaire dit meme pourquoi — « meme regle que
    # myeline/tools/agent_registry.py, sinon les deux divergent ». La regle
    # existait donc en trois exemplaires, et c'est le troisieme, ici, qui avait
    # ete oublie.
    #
    # Ce que ca produisait : moteur joignable, 91 agents ; moteur eteint, 95 —
    # dont `AGENTS` (l'index), `_conventions`, `_template` et
    # `_template-orchestrator`. Une session qui boote pendant que le moteur est
    # arrete pouvait donc lire « charge l'agent _template ».
    #
    # Et c'est exactement la divergence que postule sans l'avoir jamais
    # mesuree : « ce sont trois chemins qui peuvent diverger ». En voici un.
    files = [f for f in sorted(agents_dir.glob('*.md'))
             if f.name != 'AGENTS.md' and not f.stem.startswith('_')]
    if not files:
        return 'Aucun agent trouvé.'
    lines = ['## Agents disponibles (filesystem)\n', '| Nom |', '|-----|']
    for f in files:
        lines.append(f'| {f.stem} |')
    return '\n'.join(lines)


@mcp.tool()
def brain_decisions(last: int = 5) -> str:
    """
    Retourne les dernières décisions architecturales (ADRs).

    Lit les fichiers profil/decisions/BRAIN-*.md, triés par nom décroissant
    (numérotation → plus récent en premier). Le motif était `*.md` : le
    gabarit `_template-adr.md` et l'index `README.md` passaient devant les
    ADR, et `last=5` n'en rendait que trois (audit du wiki, 29/09).

    Args:
        last : Nombre d'ADRs à retourner (défaut: 5).

    Returns:
        Bloc markdown avec numéro, titre, statut, date et résumé (150 chars)
        de chaque ADR. "Aucune décision trouvée" si le répertoire est absent.
    """
    log.info('brain_decisions last=%d', last)
    decisions_dir = BRAIN_ROOT / 'profil' / 'decisions'
    if not decisions_dir.exists():
        return 'Aucune décision trouvée.'
    files = sorted(decisions_dir.glob('BRAIN-*.md'), reverse=True)[:last]
    if not files:
        return 'Aucune décision trouvée.'
    lines = ['## Décisions architecturales récentes\n']
    for f in files:
        body = f.read_text(encoding='utf-8')
        # Extraire titre (première ligne # ...)
        titre = next((l.lstrip('# ').strip() for l in body.splitlines() if l.startswith('#')), f.stem)
        # Extraire statut et date depuis les premières lignes (format ADR standard)
        statut = '—'
        date   = '—'
        for line in body.splitlines():
            ll = line.lower()
            if ll.startswith('statut') or ll.startswith('status') or ll.startswith('- statut'):
                statut = line.split(':', 1)[-1].strip()
            if ll.startswith('date') or ll.startswith('- date'):
                date = line.split(':', 1)[-1].strip()
        # Résumé : premier paragraphe non-titre non-vide de moins de 150 chars
        resume = ''
        for line in body.splitlines():
            if line.startswith('#') or not line.strip():
                continue
            resume = line.strip()[:150]
            break
        lines.append(f'### {f.stem} — {titre}')
        lines.append(f'**Statut** : {statut} | **Date** : {date}')
        lines.append(f'{resume}')
        lines.append('')
    return '\n'.join(lines)


@mcp.tool()
def brain_focus() -> str:
    """
    Retourne le focus genere du brain depuis Dolt.

    Agregation live : cap humain + front rotatif + intentions actives + projets.
    Remplace la lecture statique de focus.md — zero drift.

    Returns:
        Bloc markdown avec le cap, front rotatif, intentions actives et projets.
        Moteur injoignable : le dernier instantané (focus.instantane.md, écrit
        toutes les 2 h par l'indexeur), annoncé comme un repli ; sinon focus.md.
    """
    import json
    import urllib.request
    import focus_instantane
    log.info('brain_focus')
    try:
        url = f'{BRAIN_API}/focus'
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        # Le rendu vit dans `focus_instantane` : l'instantané écrit au passage de
        # l'indexeur et la réponse live sont le MÊME texte.
        return focus_instantane.rendre(data)

    except Exception as exc:
        log.warning('brain_focus Dolt failed, fallback fichier: %s', exc)
        # 1. Le dernier instantané (depuis le 2/10) : le vrai focus, daté, au plus
        #    2 h de retard — annoncé comme un repli.
        instantane = focus_instantane.lire_instantane(BRAIN_ROOT)
        if instantane:
            return instantane
        # 2. Sinon focus.md, le fallback statique : il renvoie vers l'API.
        focus_path = BRAIN_ROOT / 'focus.md'
        if not focus_path.exists():
            return 'focus.md non trouve.'
        return focus_path.read_text(encoding='utf-8')


@mcp.tool()
def brain_write(path: str, content: str) -> str:
    """
    Écrit un fichier dans le brain via PUT /brain/{path}.

    Le MCP ecrit dans les zones libres (workspace/, projets/, content/…).
    Les zones kernel (agents/, profil/, scripts/) exigent le scope `kernel`,
    que le rôle mcp n'a pas — et les invariants sont refuses a tout le monde.

    Args:
        path    : Chemin relatif dans le brain (ex: "focus.md", "todos/sprint.md").
        content : Contenu complet du fichier à écrire.

    Returns:
        JSON {"ok": true, "path": path} en cas de succès,
        message d'erreur sinon. 403 → zone protegee (kernel ou invariant).
    """
    import json
    import urllib.request
    log.info('brain_write path=%r len=%d', path, len(content))
    url     = f'{BRAIN_API}/brain/{path}'
    payload = json.dumps({'content': content}).encode('utf-8')
    # Le MCP s'annonce avec SA propre identité, jamais avec celle de l'owner.
    # Sans en-tête, l'API répondait 401 (token configuré) ou accordait les scopes
    # kernel (aucun token) — la fonctionnalité ne marchait que quand elle était
    # une faille. Le rôle `mcp` n'a pas le scope `kernel` : il écrit de la data,
    # jamais le programme.
    headers = {'Content-Type': 'application/json'}
    if BRAIN_TOKEN_MCP:
        headers['Authorization'] = f'Bearer {BRAIN_TOKEN_MCP}'
    req = urllib.request.Request(url, data=payload, method='PUT', headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
            return json.dumps({'ok': True, 'path': path})
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = json.loads(exc.read()).get('detail', '')
        except Exception:
            pass
        if exc.code == 403:
            return f'Écriture refusée — {detail or "zone protégée"}'
        if exc.code == 409:
            return f'Écriture bloquée — {detail or "claim ou lock BSI"}'
        if exc.code == 401:
            return 'Écriture refusée — le MCP n\'a pas de token (BRAIN_TOKEN_MCP absent).'
        return f'Erreur {exc.code} : {detail or exc.reason}'
    except Exception as exc:
        log.warning('brain_write failed: %s', exc)
        return f'brain_write indisponible : {exc}'


# ── Content pipeline ──────────────────────────────────────────────────────────

# Une seule racine, calculee une seule fois — l.83.
#
# Il y en avait DEUX au niveau module, et elles ne se calculaient pas pareil :
# `_BRAIN_ROOT` avec `.resolve()`, celle-ci sans. Les chemins passes a
# `relative_to(BRAIN_ROOT)` (l.626, l.850) viennent de `_resolve_under(_BRAIN_ROOT,
# ...)`, donc RESOLUS — compares a une racine qui ne l'etait pas.
#
# Mesure le 10/09 : dormant sur cette machine, aucun lien symbolique sur
# `~/Dev/Brain`. Il s'activerait la ou il y en a un — un laptop, un fork — et
# `relative_to` leverait un ValueError. Le nom est conserve, ses quatre usages
# n'ont pas a changer.
BRAIN_ROOT = _BRAIN_ROOT
# Le satellite `contenu/` (BRAIN-080) : l'atelier et le publié dans un seul dépôt.
# Un fork sans `contenu/` voit un pipeline vide — `_scan_content_zone` rend une
# liste vide quand sa racine manque.
CONTENT_ATELIER  = BRAIN_ROOT / 'contenu' / 'atelier'
CONTENT_PUBLISHED = BRAIN_ROOT / 'contenu' / 'publie'

# Statuts valides et leur ordre de progression
CONTENT_STATUSES = ['draft', 'ready', 'scheduled', 'published', 'recycled']

# Mapping plateforme depuis le path
def _detect_platform(filepath: str) -> str:
    """Détecte la plateforme depuis le chemin relatif du fichier."""
    p = filepath.lower()
    if '/instagram/' in p:
        return 'instagram'
    if '/posts/' in p:
        return 'linkedin'
    if '/video/' in p or '/youtube/' in p:
        return 'video'
    if '/story/' in p:
        return 'story'
    if '/pov/' in p:
        return 'pov'
    return 'other'


def _parse_frontmatter(filepath: Path) -> dict | None:
    """Parse le frontmatter YAML d'un fichier markdown. Retourne None si absent."""
    try:
        text = filepath.read_text(encoding='utf-8')
    except Exception:
        return None
    if not text.startswith('---'):
        return None
    end = text.find('---', 3)
    if end == -1:
        return None
    import yaml
    try:
        fm = yaml.safe_load(text[3:end])
        return fm if isinstance(fm, dict) else None
    except Exception:
        return None


def _scan_content_zone(base: Path, zone: str) -> list[dict]:
    """Scanne une zone content et retourne la liste des posts avec métadonnées."""
    items = []
    if not base.exists():
        return items
    # Sous-dossiers exclus (specs, visions, stratégie — pas du contenu social)
    EXCLUDED_DIRS = {'brain-ui', 'assets', 'chardesign', 'story', 'pov'}
    EXCLUDED_FILES = {'CATALOG.md', 'STRATEGY.md', 'VISUAL-GUIDE.md',
                      'matiere-brute.md', 'chiffres-verifies.md',
                      'raw-material.md', 'scripts.md', 'seo-thumbnail.md',
                      'strategy.md', 'comfy-gen.py', 'cortex.md'}
    for md in sorted(base.rglob('*.md')):
        # Ignorer les dossiers exclus
        if any(part in EXCLUDED_DIRS for part in md.relative_to(base).parts):
            continue
        # Ignorer les fichiers de config/stratégie
        if md.name in EXCLUDED_FILES:
            continue
        fm = _parse_frontmatter(md)
        rel = str(md.relative_to(BRAIN_ROOT))
        status = (fm or {}).get('status', 'unknown')
        serie  = (fm or {}).get('serie', '')
        account = (fm or {}).get('account', '')
        item = {
            'path': rel,
            'filename': md.name,
            'zone': zone,
            'platform': _detect_platform(rel),
            'status': status,
            'serie': serie,
            'account': account,
            'date_draft': (fm or {}).get('date_draft', ''),
            'date_published': (fm or {}).get('date_published', ''),
            'date_scheduled': (fm or {}).get('date_scheduled', ''),
            'title': '',
        }
        # Extraire le titre (premier # du fichier)
        try:
            for line in md.read_text(encoding='utf-8').splitlines():
                if line.startswith('# '):
                    item['title'] = line.lstrip('# ').strip()
                    break
        except Exception:
            pass
        items.append(item)
    return items


@mcp.tool()
def brain_content(platform: str = '', status: str = '', zone: str = '') -> str:
    """
    Pipeline contenu du brain — vue unifiée atelier + publié.

    Scanne contenu/atelier/ (drafts, matière) et contenu/publie/ (livré — publié).
    Parse les frontmatters pour extraire status, série, plateforme, dates.

    Args:
        platform : Filtrer par plateforme (linkedin, instagram, video, story, pov). Vide = tout.
        status   : Filtrer par status (draft, ready, scheduled, published, recycled). Vide = tout.
        zone     : Filtrer par zone (atelier, published). Vide = tout.

    Returns:
        Tableau markdown avec le pipeline complet + compteurs par status.
    """
    log.info('brain_content platform=%r status=%r zone=%r', platform, status, zone)

    items = []
    if zone != 'published':
        items.extend(_scan_content_zone(CONTENT_ATELIER, 'atelier'))
    if zone != 'atelier':
        items.extend(_scan_content_zone(CONTENT_PUBLISHED, 'published'))

    # Filtres
    if platform:
        items = [i for i in items if i['platform'] == platform]
    if status:
        items = [i for i in items if i['status'] == status]

    if not items:
        return 'Aucun contenu trouvé avec ces filtres.'

    # Compteurs
    counts = {}
    for i in items:
        s = i['status']
        counts[s] = counts.get(s, 0) + 1
    stats_line = ' · '.join(f"**{s}**: {c}" for s, c in sorted(counts.items()))

    # Compteurs par plateforme
    plat_counts = {}
    for i in items:
        p = i['platform']
        plat_counts[p] = plat_counts.get(p, 0) + 1
    plat_line = ' · '.join(f"{p}: {c}" for p, c in sorted(plat_counts.items()))

    # Table
    lines = [
        f'## Content Pipeline — {len(items)} posts\n',
        f'{stats_line}\n',
        f'Plateformes : {plat_line}\n',
        '| Status | Zone | Platform | Titre | Path |',
        '|--------|------|----------|-------|------|',
    ]
    # Tri : draft en premier, puis ready, scheduled, published
    status_order = {s: i for i, s in enumerate(CONTENT_STATUSES)}
    items.sort(key=lambda x: (status_order.get(x['status'], 99), x['platform'], x['filename']))

    for i in items:
        icon = {'draft': '📝', 'ready': '✅', 'scheduled': '📅',
                'published': '🟢', 'recycled': '♻️'}.get(i['status'], '•')
        title = i['title'][:50] or i['filename']
        lines.append(f"| {icon} {i['status']} | {i['zone']} | {i['platform']} | {title} | `{i['path']}` |")

    return '\n'.join(lines)


@mcp.tool()
def brain_content_promote(path: str, target_status: str) -> str:
    """
    Promouvoir un contenu dans le pipeline.

    Gère deux types de transitions :
    - Dans la même zone : draft→ready (reste dans contenu/atelier/)
    - Cross-zone : ready→scheduled (move contenu/atelier/ → contenu/publie/)
    - Dans zone publiée : scheduled→published, published→recycled

    Le frontmatter est mis à jour automatiquement (status + dates).

    Args:
        path          : Chemin relatif dans le brain (ex: "contenu/atelier/posts/btb-001-postiz-timezone.md")
        target_status : Status cible (ready, scheduled, published, recycled)

    Returns:
        JSON {"ok": true, "path": new_path, "status": target_status} ou message d'erreur.
    """
    import json
    import shutil
    from datetime import date, datetime
    log.info('brain_content_promote path=%r target=%r', path, target_status)

    if target_status not in CONTENT_STATUSES:
        return f'Status invalide : {target_status}. Valides : {", ".join(CONTENT_STATUSES)}'

    # Confiné aux deux racines du pipeline contenu. Sans contrôle, `path`
    # atteignait n'importe quel fichier du dépôt — et cet outil ne fait pas que
    # lire : il déplace (shutil.move plus bas).
    try:
        source = _resolve_under(_BRAIN_ROOT, path)
    except ValueError:
        log.warning('brain_content_promote : chemin hors du brain (%r)', path)
        return f'Chemin invalide : {path}'
    if not any(source.is_relative_to(root.resolve())
               for root in (CONTENT_ATELIER, CONTENT_PUBLISHED)):
        log.warning('brain_content_promote : chemin hors pipeline contenu (%r)', path)
        return (f'Chemin hors du pipeline contenu : {path} — '
                f'attendu sous contenu/atelier/ ou contenu/publie/.')
    if not source.is_file():
        return f'Fichier introuvable : {path}'

    # Lire le contenu et le frontmatter
    text = source.read_text(encoding='utf-8')
    current_status = 'unknown'
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            import yaml
            try:
                fm = yaml.safe_load(text[3:end])
                if isinstance(fm, dict):
                    current_status = fm.get('status', 'unknown')
            except Exception:
                pass

    # Validation de la progression
    if target_status == current_status:
        return f'Déjà en status {target_status}.'

    current_idx = CONTENT_STATUSES.index(current_status) if current_status in CONTENT_STATUSES else -1
    target_idx  = CONTENT_STATUSES.index(target_status)
    if target_idx <= current_idx and current_status != 'unknown':
        return f'Régression interdite : {current_status} → {target_status}. Le pipeline avance.'

    # Déterminer si on doit déplacer cross-zone
    is_atelier = str(source).startswith(str(CONTENT_ATELIER))
    needs_move = is_atelier and target_status in ('scheduled', 'published')

    # Mettre à jour le frontmatter dans le texte
    today = date.today().isoformat()
    now_iso = datetime.now().strftime('%Y-%m-%dT%H:%M')
    replacements = {
        'status': target_status,
    }
    # date_draft: set si manquant
    if text.startswith('---'):
        end_fm = text.find('---', 3)
        if end_fm != -1:
            fm_block = text[3:end_fm]
            if 'date_draft:' not in fm_block or 'date_draft: null' in fm_block:
                replacements['date_draft'] = today
    # date_scheduled: set seulement si pas déjà planifié manuellement
    if target_status == 'scheduled':
        if text.startswith('---'):
            end_fm = text.find('---', 3)
            if end_fm != -1:
                fm_block = text[3:end_fm]
                has_scheduled = 'date_scheduled:' in fm_block and 'date_scheduled: null' not in fm_block
                # Check if value is non-empty
                import re as _re
                match = _re.search(r'date_scheduled:\s*(\S+)', fm_block)
                if not match or not match.group(1) or match.group(1) == 'null':
                    replacements['date_scheduled'] = today
    # date_published: toujours écraser avec datetime exact
    if target_status == 'published':
        replacements['date_published'] = now_iso

    # Appliquer les modifications au frontmatter
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            fm_text = text[3:end]
            body = text[end:]
            for key, val in replacements.items():
                import re
                pattern = rf'^{key}:.*$'
                replacement = f'{key}: {val}'
                if re.search(pattern, fm_text, re.MULTILINE):
                    fm_text = re.sub(pattern, replacement, fm_text, flags=re.MULTILINE)
                else:
                    fm_text = fm_text.rstrip('\n') + f'\n{key}: {val}\n'
            new_text = '---' + fm_text + body
        else:
            new_text = text
    else:
        new_text = text

    # Écrire le fichier (même emplacement ou nouveau)
    if needs_move:
        # Calculer le chemin destination dans contenu/publie/
        rel_to_atelier = source.relative_to(CONTENT_ATELIER)
        dest = CONTENT_PUBLISHED / rel_to_atelier
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(new_text, encoding='utf-8')
        source.unlink()
        new_path = str(dest.relative_to(BRAIN_ROOT))
        log.info('content promoted (moved) %s → %s [%s]', path, new_path, target_status)
    else:
        source.write_text(new_text, encoding='utf-8')
        new_path = path
        log.info('content promoted (in-place) %s [%s]', path, target_status)

    return json.dumps({'ok': True, 'path': new_path, 'status': target_status, 'moved': needs_move})


@mcp.tool()
def brain_intentions(project: str = '', status: str = '', front_only: bool = False) -> str:
    """
    Retourne les intentions du brain depuis Dolt.

    Les intentions sont les objectifs mesurables du brain — ce sur quoi on travaille.
    Elles sont liées aux sessions BSI et aux projets.

    Args:
        project    : Filtrer par projet (ex: "mon-projet", "mon-api"). Vide = tous.
        status     : Filtrer par status (active, stasis, identified, done, archived). Vide = tous sauf archived.
        front_only : True = uniquement les intentions du front rotatif (max 5).

    Returns:
        Tableau markdown avec les intentions, leur status, projet, sessions, et next_step.
    """
    import json
    import urllib.request
    log.info('brain_intentions project=%r status=%r front=%r', project, status, front_only)
    try:
        params = []
        if project:
            params.append(f'project={project}')
        if status:
            params.append(f'status={status}')
        if front_only:
            params.append('front_only=true')
        qs = f"?{'&'.join(params)}" if params else ''
        url = f'{BRAIN_API}/intentions{qs}'
        with urllib.request.urlopen(url, timeout=5) as resp:
            items = json.loads(resp.read())

        if not items:
            return 'Aucune intention trouvée avec ces filtres.'

        # Séparer front et reste
        front = [i for i in items if i.get('front')]
        rest = [i for i in items if not i.get('front')]

        lines = []

        if front:
            lines.append('## Front rotatif\n')
            for i in front:
                icon = {'active': '🔥', 'stasis': '💤', 'identified': '💡', 'done': '✅'}.get(i['status'], '⚪')
                sessions = i.get('total_sessions', 0)
                duration = i.get('total_duration', 0)
                ns = i.get('next_step', '')
                lines.append(f"**#{i.get('front_order','')}** {icon} **{i['id']}** — {i.get('project', '')} ({sessions} sessions, {duration}min)")
                if ns:
                    lines.append(f"  → {ns}")
            lines.append('')

        if rest and not front_only:
            # Group by status
            for s in ('active', 'stasis', 'identified'):
                group = [i for i in rest if i['status'] == s]
                if not group:
                    continue
                icon = {'active': '🔥', 'stasis': '💤', 'identified': '💡'}.get(s, '⚪')
                lines.append(f"### {icon} {s} ({len(group)})\n")
                for i in group:
                    ns = i.get('next_step', '')
                    reason = i.get('stasis_reason', '')
                    detail = f" — {reason}" if reason and s == 'stasis' else (f" → {ns}" if ns else '')
                    lines.append(f"- **{i['id']}** [{i.get('project', '')}]{detail}")
                lines.append('')

        return '\n'.join(lines) if lines else 'Aucune intention.'
    except Exception as exc:
        log.warning('brain_intentions failed: %s', exc)
        return f'Intentions indisponibles : {exc}'


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    auth_status = 'token actif' if BRAIN_TOKEN_MCP else 'auth désactivée (dev)'
    log.info('Brain MCP BE-4 — port %d — %s — scopes: %s',
             BRAIN_MCP_PORT, auth_status, MCP_SCOPES)
    log.info(_annonce_racines())
    # Les en-têtes de proxy ne sont crus que d'un proxy LOCAL : `'*'` laissait
    # n'importe quelle machine réécrire l'adresse du client (relecture du 28/09).
    uvicorn.run(mcp_app, host='0.0.0.0', port=BRAIN_MCP_PORT,
                forwarded_allow_ips='127.0.0.1', proxy_headers=True)
