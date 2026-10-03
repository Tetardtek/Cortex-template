#!/usr/bin/env python3
"""
brain-engine/server.py — Brain-as-a-Service BE-4
Expose la recherche sémantique via HTTP (FastAPI + uvicorn).

Usage :
  python3 brain-engine/server.py                  → port 7700 (défaut)
  BRAIN_PORT=8080 python3 brain-engine/server.py  → port custom

Tokens (MYSECRETS) :
  BRAIN_TOKEN_OWNER   → zones public + work + kernel  (toi, sessions locales)
  BRAIN_TOKEN_MCP     → zones public + work           (Claude via MCP)
  BRAIN_TOKEN_PUBLIC  → zone public seule             (bot, démo externe)
  BRAIN_TOKEN         → alias owner (compat BE-3)

Zones :
  public  → focus.md, wiki/, agents/, infrastructure/
  work    → todo/, projets/, handoffs/, workspace/
  kernel  → profil/, KERNEL.md, contexts/
  (private → jamais indexé — profil/capital.md, objectifs.md...)

Autorisation (BRAIN-072 — plus de paliers commerciaux) :
  check_auth(token) → role (_TOKEN_MAP) → scopes (_SCOPE_ACCESS)
  PUT /brain/{path} autorise PAR ZONE : invariant refuse, kernel exige le scope
  `kernel` plus un claim BSI ouvert, le reste exige `work` et respecte les locks.

Level 2 localhost trust (_is_localhost) :
  BSI endpoints → bypass auth depuis 127.0.0.1

Endpoints :
  GET  /health                       → statut + uptime + version
  GET  /state                        → env fondamental dérivé (systemd, pm2, git)
  GET  /boot                         → zones brain + queries initiales
  GET  /search?q=                    → RAG sémantique
  GET  /agents                       → liste agents disponibles
  GET  /workflows                    → ce qui avance en autonomie (palier b)
  GET  /visualize                    → coordonnées 3D UMAP
  PUT  /brain/{path}                 → écriture fichier brain + reindex
  POST /ambient/notify               → broadcast event daemon Ambient
  GET  /bsi/claims                    → liste claims BSI (liste plate)
  GET  /bsi/claims?include_peers=true  → {claims, peers_injoignables} — un OBJET
  POST /bsi/claims                    → créer un claim BSI dans la base
  PATCH /bsi/claims/{sess_id}         → update claim (status, close, result)
  GET  /bsi/locks                     → liste locks actifs
  POST /bsi/locks                     → acquérir un lock fichier
  DELETE /bsi/locks/{filepath}        → libérer un lock fichier
  GET  /bsi/network                   → vue réseau BSI (peers + claims agrégés)
  WS   /ws                           → WebSocket temps réel

L'autorisation se lit dans chaque route : `check_auth` → scopes du RÔLE du porteur
(owner, mcp, public), plus la confiance localhost des routes BSI. Les étiquettes
[free]/[PRO] qui suivaient chaque route décrivaient les paliers commerciaux,
supprimés par BRAIN-072, et la route /tier n'existe plus.
"""

import os
import sys
import re
import time
import hashlib
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import asyncio
from fastapi import FastAPI, Header, HTTPException, Query, Body, WebSocket, Request
from fastapi.responses import JSONResponse
from fastapi.websockets import WebSocketDisconnect

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# Import moteur RAG depuis le même répertoire
sys.path.insert(0, str(Path(__file__).parent))
from rag import run_boot_queries, run_single_query
from search import RechercheIndisponible

# ── Config ─────────────────────────────────────────────────────────────────────

BRAIN_PORT = int(os.getenv('BRAIN_PORT') or 7700)

# Zones accessibles par rôle
_SCOPE_ACCESS: dict[str, list[str]] = {
    'owner':  ['public', 'kernel', 'instance', 'satellite', 'work'],
    'mcp':    ['public', 'work', 'instance', 'satellite'],
    'public': ['public'],
}

# Résolution token → rôle (dernière valeur gagne si conflit)
_TOKEN_MAP: dict[str, str] = {}
for _env, _role in [
    ('BRAIN_TOKEN',        'owner'),   # compat BE-3 — alias owner
    ('BRAIN_TOKEN_OWNER',  'owner'),
    ('BRAIN_TOKEN_MCP',    'mcp'),
    ('BRAIN_TOKEN_PUBLIC', 'public'),
]:
    _val = os.getenv(_env)
    if _val:
        _TOKEN_MAP[_val] = _role

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('brain-engine')

# ── Rôles ──────────────────────────────────────────────────────────────────────
#
# BRAIN-072 : le TierGate est retiré. Ce qui disparaît, ce sont les PALIERS
# COMMERCIAUX (free / featured / pro / full) et leur validation réseau contre
# un service de validation distant — arrêté des deux côtés.
#
# Ce qui reste, et qu'il ne faut pas confondre : les RÔLES (`owner`, `mcp`,
# `public`) portés par `_TOKEN_MAP` et traduits en scopes par `_SCOPE_ACCESS`.
# C'est eux qui font tenir l'autorisation par zone de `brain_put`.
#
# Les deux chaînes coexistaient et se contredisaient : pour un même token,
# `check_auth` répondait `mcp` et l'ancien `get_tier_from_request` répondait
# `free`. La contradiction se règle par soustraction, pas par arbitrage.


def role_from_token(authorization: str | None) -> str:
    """Rôle du porteur, pour la trace d'audit. Jamais pour autoriser.

    L'autorisation passe par `check_auth` → scopes. Cette fonction ne sert qu'à
    savoir *qui* a écrit, ce qui rend une trace exploitable.
    """
    if not authorization or not authorization.startswith('Bearer '):
        return 'anonyme'
    token = authorization.removeprefix('Bearer ').strip()
    return _TOKEN_MAP.get(token, 'inconnu') if token else 'anonyme'


# Uptime tracking
_START_TIME: float = time.time()

# WebSocket clients
_ws_clients: list[WebSocket] = []

# Deux racines, une source : `racines.py`. BRAIN_ROOT est la DATA —
# reçue par la variable du même nom, sinon le parent du programme.
from racines import DONNEES as BRAIN_ROOT, PROGRAMME, annonce as _annonce_racines
# La frontière d'un verrou, écrite une fois dans le CORE.
from core.bsi import VERROU_ACTIF
log.info(_annonce_racines())
DB_PATH    = Path(os.getenv('BRAIN_DB_PATH') or str(BRAIN_ROOT / 'brain.db'))
BRAIN_MODE = os.getenv('BRAIN_MODE') or 'owner'  # 'owner' (full) | 'prod' | 'satellite' (kernel en lecture) | 'template' (read-only) | 'demo' (vitrine)


def _readonly_guard():
    """Bloque les endpoints write/session en mode template ou demo."""
    if BRAIN_MODE in ('template', 'demo'):
        raise HTTPException(status_code=403, detail='not available on this instance')


app = FastAPI(title='Brain-as-a-Service', version='BE-4', docs_url='/api-docs')


class _SansJetonResteLocal:
    """Sans jeton configuré, le moteur ne répond qu'à la machine elle-même.

    La règle du MCP, tranchée par l'owner le 28/09. `check_auth` rend
    les trois zones à qui n'a pas de jeton quand aucun n'est configuré — l'état
    d'un fork neuf — et uvicorn écoute sur 0.0.0.0 : sans cette garde, toute
    machine du réseau local lisait le corpus et écrivait. Elle couvre HTTP et
    WebSocket, fichiers servis compris ; avec des jetons, rien ne change.

    `X-Forwarded-For` présent = un proxy relaie quelqu'un d'autre : pas local
    (la règle de `_is_localhost`)."""

    _BOUCLE = ('127.0.0.1', '::1')

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket') and not _TOKEN_MAP:
            client = (scope.get('client') or ('',))[0]
            relaye = any(k == b'x-forwarded-for' for k, _ in scope.get('headers', []))
            if client not in self._BOUCLE or relaye:
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1008})
                    return
                await JSONResponse(status_code=403, content={
                    'detail': 'aucun jeton configuré : le moteur ne répond qu\'à la machine locale'
                })(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(_SansJetonResteLocal)

# ── Montage brain-ui static (si build disponible) ────────────────────────────

# L'interface voyage avec le programme, pas avec la data.
_UI_DIST = PROGRAMME.parent / 'brain-ui' / 'dist'
if _UI_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount('/ui', StaticFiles(directory=str(_UI_DIST), html=True), name='brain-ui')
    log.info('brain-ui monté sur /ui depuis %s', _UI_DIST)


# ── Level 2 — localhost frictionless ───────────────────────────────────────────

def _is_localhost(request: Request) -> bool:
    """True si la requête vient de localhost — Level 2 agents (frictionless).
    Si X-Forwarded-For présent → vient d'Apache proxy → pas localhost trust.
    """
    if request is None:
        return False
    if request.headers.get('x-forwarded-for'):
        return False
    client_host = request.client.host if request.client else ''
    result = client_host in ('127.0.0.1', '::1', 'localhost')
    if result:
        log.debug('level2 local bypass: %s', request.url.path)
    return result


# ── Auth ───────────────────────────────────────────────────────────────────────

def check_auth(authorization: str | None) -> list[str]:
    """
    Vérifie le header Authorization: Bearer <token>.
    Retourne la liste des scopes autorisés pour ce token.
    Si aucun token configuré : auth désactivée (dev local) → accès total.

    « Accès total » rendait `['public', 'work', 'kernel']` — la même liste
    recopiée que `/boot` portait avant d'être corrigée, et qui avait dérivé de
    la même façon : ni `instance` (projets/, focus.md) ni `satellite` (workspace/,
    handoffs/, learning/). `/search` sans jeton ne les voyait pas (audit du
    wiki, 29/09). Sans jeton, le middleware ne laisse passer que la machine
    elle-même : c'est l'owner, et il voit ce que `_SCOPE_ACCESS` lui déclare.
    """
    if not _TOKEN_MAP:
        return list(_SCOPE_ACCESS['owner'])  # dev local — accès total
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Authorization header requis')
    token = authorization.removeprefix('Bearer ').strip()
    role  = _TOKEN_MAP.get(token)
    if not role:
        raise HTTPException(status_code=403, detail='Token invalide')
    return _SCOPE_ACCESS[role]


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get('/health')
def health():
    """Sanity check — vérifie que le moteur répond."""
    uptime = int(time.time() - _START_TIME)
    try:
        import db as brain_db
        indexed = brain_db.count('embeddings', 'indexed = 1')
        result = {'status': 'ok', 'indexed': indexed, 'uptime': uptime}
        result.update(brain_db.info())
        return result
    except Exception as e:
        return JSONResponse(status_code=503, content={'status': 'error', 'detail': str(e), 'uptime': uptime})


# ── Docs — les pages de docs/, servies au dashboard ───────────────────────────────

@app.get('/docs')
def docs_list():
    """Les pages de docs/*.md, avec leur libellé, groupe et ordre déclarés.

    Chaque page les DÉCLARE dans son frontmatter (`label`, `groupe`, `ordre`).

    Une table de libellés vivait ici, devinée depuis le nom du fichier. Elle
    annonçait encore les vues par palier commercial — `vue-free`, `vue-pro`… —
    trois semaines après leur suppression, et renommer une page cassait sa place
    dans la barre latérale. La page dit elle-même où elle va."""
    docs_dir = BRAIN_ROOT / 'docs'
    if not docs_dir.is_dir():
        return {'docs': []}

    results = []
    for f in sorted(docs_dir.glob('*.md')):
        if f.name == 'README.md':
            continue
        meta = _doc_frontmatter(f)
        results.append({
            'name': f.stem,
            'label': str(meta.get('label') or f.stem.replace('-', ' ').capitalize()),
            'group': str(meta.get('groupe') or 'Guides'),
            'order': _ordre(meta.get('ordre')),
            'path': f'/docs/{f.name}',
            'size': f.stat().st_size,
            'modified': datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    results.sort(key=lambda d: (d['order'], d['name']))
    return {'docs': results}


def _ordre(valeur) -> float:
    """`ordre: 3`, `ordre: "3"` ou `1.5` — un nombre ; le reste (absent, `true`) en fin."""
    if isinstance(valeur, bool):
        return 999
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return 999


def _doc_frontmatter(chemin: Path) -> dict:
    """Le frontmatter d'une page — `{}` s'il n'y en a pas ou s'il est illisible."""
    texte = chemin.read_text(encoding='utf-8')
    m = re.match(r'^---\n([\s\S]*?)\n---\n', texte)
    if not m or not _YAML_AVAILABLE:
        return {}
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


@app.get('/docs/{filename}')
def docs_read(filename: str):
    """Retourne le contenu brut d'un fichier docs/*.md."""
    # Sécurité : pas de path traversal
    if '/' in filename or '..' in filename:
        raise HTTPException(status_code=400, detail='Nom de fichier invalide')
    target = BRAIN_ROOT / 'docs' / filename
    if not target.exists() or not target.suffix == '.md':
        raise HTTPException(status_code=404, detail=f'{filename} introuvable')
    content = target.read_text(encoding='utf-8')
    # Strip frontmatter
    content = re.sub(r'^---[\s\S]*?---\n*', '', content)
    return JSONResponse(content={'name': target.stem, 'content': content})


@app.get('/search')
def search(
    q:             str        = Query(..., description='Requête en langage naturel'),
    top:           int        = Query(5,   description='Nombre de résultats'),
    full:          bool       = Query(False, description='Chunks complets (défaut: compact)'),
    mode:          str        = Query('develop', description='develop | service (réservé)'),
    authorization: str | None = Header(None),
):
    scopes = check_auth(authorization)
    log.info('search q=%r top=%d full=%s scopes=%s', q, top, full, scopes)

    try:
        results = run_single_query(q, top_k=top, allowed_scopes=scopes)
    except RechercheIndisponible as panne:
        # 503, pas 200 vide : la recherche n'a pas eu lieu.
        raise HTTPException(status_code=503, detail=f"recherche indisponible — {panne}. {panne.conseil()}")

    return _format_results(results, full=full, mode=mode)


@app.get('/boot')
def boot(
    full:          bool       = Query(False, description='Chunks complets (défaut: compact)'),
    mode:          str        = Query('develop', description='develop | service (réservé)'),
    authorization: str | None = Header(None),
    request:       Request    = None,
):
    if _is_localhost(request):
        # ── Localhost EST l'owner, et l'owner voit ses cinq zones ─────
        #
        # Cette liste valait `['public', 'work', 'kernel']` — trois scopes sur
        # cinq, recopiés à la main à côté de `_SCOPE_ACCESS` qui les déclare.
        # Mesuré le 05/09 : le boot en local voyait **1 950 chunks sur 5 719**,
        # soit un tiers du brain. Manquaient `instance` — `focus.md`, `projets/`,
        # `PATHS.md`, `now.md` — et `satellite` — `toolkit/`, `todo/`,
        # `handoffs/`, `intentions/`, `learning/`.
        #
        # Ce n'est pas une restriction voulue : `role_from_token` et la docstring
        # de `brain_get` disent tous deux « localhost = owner ». C'est une
        # sixième déclaration du même fait, et elle avait dérivé des cinq autres.
        # On la dérive maintenant de la seule qui fait autorité.
        scopes = list(_SCOPE_ACCESS['owner'])
    else:
        scopes = check_auth(authorization)
    log.info('boot full=%s scopes=%s', full, scopes)

    try:
        results = run_boot_queries(allowed_scopes=scopes)
    except RechercheIndisponible as panne:
        raise HTTPException(status_code=503, detail=f"recherche indisponible — {panne}. {panne.conseil()}")

    return _format_results(results, full=full, mode=mode)


def _load_catalog(agents_dir: Path) -> dict:
    """
    Charge agents/CATALOG.yml — fichier GÉNÉRÉ depuis le frontmatter des agents
    (myeline/tools/agent_registry.py). Retourne
    {agent_id: {classification, distributable, description, hold}}.

    Le catalogue ne détient plus aucune donnée qui lui soit propre : il est
    dérivé, donc il ne peut pas diverger des fichiers qu'il décrit. L'ancien
    couple {tier, export} est supprimé — `tier` était une barrière commerciale
    (BRAIN-072), `export` un booléen maintenu à la main qui contredisait le
    frontmatter sur 22 des 73 entrées partagées.
    """
    catalog_path = agents_dir / 'CATALOG.yml'
    if not catalog_path.exists():
        return {}
    data = _load_yaml_file(catalog_path)
    if not data or not isinstance(data.get('agents'), list):
        return {}
    return {
        entry['id']: {
            'classification': entry.get('classification', 'programme'),
            'distributable':  bool(entry.get('distributable', True)),
            'description':    entry.get('description') or '',
            'hold':           entry.get('hold'),
        }
        for entry in data['agents']
        if isinstance(entry, dict) and 'id' in entry
    }


@app.get('/agents')
def agents_list(
    authorization: str | None = Header(None),
    request:       Request    = None,
):
    """Liste les agents, avec leur classification dérivée depuis agents/CATALOG.yml.

    Plus de filtrage par tier (BRAIN-072) : la liste est la même pour tous. Ce
    qu'un agent est — programme, privé ou état — se dérive de `scope` + `writer`,
    et `distributable` de sa classification plus l'absence de `hold`.
    """
    if not _is_localhost(request):
        check_auth(authorization)  # zones=['public'] — tout token valide suffit

    log.info('agents_list')

    agents_dir = BRAIN_ROOT / 'agents'
    tier_map   = _parse_agents_tier_map(agents_dir / 'AGENTS.md')
    catalog    = _load_catalog(agents_dir)
    result     = []

    for md_file in sorted(agents_dir.glob('*.md')):
        # Index et méta-fichiers (`_conventions`, gabarits) ne sont pas des agents.
        # Même règle que myeline/tools/agent_registry.py, sinon les deux divergent.
        if md_file.name == 'AGENTS.md' or md_file.stem.startswith('_'):
            continue
        fm = _parse_frontmatter(md_file)
        if not fm:
            continue
        agent_id = fm.get('name') or md_file.stem

        # Plus de filtrage par tier (BRAIN-072). Le catalogue étant généré depuis
        # ces mêmes fichiers, aucun agent ne peut en être absent : une entrée
        # manquante signale un catalogue périmé, pas un agent à cacher.
        cat_entry = catalog.get(agent_id)
        if cat_entry is None:
            log.warning('agent %s absent du CATALOG généré — régénérer', agent_id)
            cat_entry = {'classification': 'programme', 'distributable': True,
                         'description': '', 'hold': None}

        info  = tier_map.get(agent_id, {})
        brain = fm.get('brain', {}) if isinstance(fm.get('brain'), dict) else {}
        result.append({
            'id':             agent_id,
            'label':          agent_id,
            'classification': cat_entry['classification'],
            'distributable':  cat_entry['distributable'],
            'hold':           cat_entry['hold'],
            'status':         fm.get('status', 'active'),
            'triggers':       brain.get('triggers') or fm.get('domain') or [],
            'scope':          brain.get('scope', 'project'),
            'created':        info.get('created', ''),
            'description':    cat_entry['description'] or fm.get('description', ''),
        })

    return result


# `GET /teams` — retirée le 2/10 : elle lisait `teams/*.yml`,
# des presets d'équipes de mars que rien n'appelait — ni brain-ui, ni le MCP, ni
# un script — et qui ne partaient pas au gabarit : chez un fork, une liste vide
# qui ne disait pas pourquoi. Les presets sont dans `teams/archive/`.


@app.get('/workflows')
def workflows_list(
    authorization: str | None = Header(None),
    request: Request = None,
):
    """Ce qui avance EN AUTONOMIE — le résumé du palier b (BRAIN-079).

    Réaffectée le 30/09 : elle rendait les claims portant
    un `workflow` ou un `satellite_type`, colonnes que rien n'écrit (0 sur 627,
    mesuré le 27/09) — donc toujours `[]`, alors que `brain_workflows` est un
    réflexe de début de session. Les « workflows actifs », depuis BRAIN-079, ce
    sont les passes du palier c : ce que `dev/autonome` porte, les PR qui
    attendent un verdict.

    Le moteur reste NEUTRE : la commande qui produit ce résumé se déclare dans
    la config locale (`BRAIN_RESUME_AUTONOMIE_CMD`, `.env.local`) et rend du
    JSON `{"projets": [...], "note": ...}`. Sans déclaration, ou si elle
    échoue, la route répond quand même — 200, `projets` vide, et la `note` dit
    pourquoi : un vide qui se tait se confond avec « rien n'avance ».
    """
    if _is_localhost(request):
        scopes = ['work', 'kernel', 'public']
    else:
        scopes = check_auth(authorization)
    if 'work' not in scopes:
        raise HTTPException(status_code=403, detail='Zone work requise')
    log.info('workflows_list scopes=%s', scopes)
    return _resume_autonomie()


def _resume_autonomie() -> dict:
    import shlex
    commande = (os.environ.get('BRAIN_RESUME_AUTONOMIE_CMD') or '').strip()
    if not commande:
        return {'projets': [], 'note': 'aucune source déclarée (BRAIN_RESUME_AUTONOMIE_CMD)'}
    try:
        r = subprocess.run(shlex.split(commande), capture_output=True, text=True, timeout=60)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'projets': [], 'note': f'la source ne répond pas ({type(exc).__name__})'}
    if r.returncode != 0:
        return {'projets': [], 'note': f'la source a échoué (sortie {r.returncode})'}
    try:
        donnees = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'projets': [], 'note': 'la source ne rend pas de JSON lisible'}
    if not isinstance(donnees, dict) or not isinstance(donnees.get('projets'), list):
        return {'projets': [], 'note': 'la source ne rend pas {"projets": [...]}'}
    return {'projets': donnees['projets'], 'note': donnees.get('note')}


# `POST /workflows/create` — retirée le 30/09 (BRAIN-079) : elle ouvrait un claim
# portant la colonne `workflow`, que plus rien ne lit, et aucune interface ne
# l'appelait. Le lancement d'agents passe par le palier c.


def _as_utc(valeur):
    """Datetime naif de la base → aware UTC. Les colonnes du brain sont en UTC
    depuis la bascule du 02/09 ; sans le fuseau explicite, la comparaison retomberait sur
    l'heure locale et rendrait un ecart de deux heures."""
    if valeur is None:
        return None
    return valeur.replace(tzinfo=timezone.utc) if valeur.tzinfo is None else valeur


def _cache_generated_at(cache_path: Path):
    """Horodatage du cache viz, ou None s'il est illisible."""
    try:
        brut = __import__('json').loads(cache_path.read_text()).get('generated_at')
        return _as_utc(datetime.fromisoformat(brut)) if brut else None
    except Exception as exc:
        log.warning('visualize: horodatage du cache illisible (%s) — %s',
                    cache_path.name, exc)
        return None


def _cache_point_count(cache_path: Path):
    """Nombre de points que le cache viz porte, ou None s'il est illisible."""
    try:
        points = __import__('json').loads(cache_path.read_text()).get('points')
        return len(points) if isinstance(points, list) else None
    except Exception as exc:
        log.warning('visualize: cache illisible pour le comptage (%s) — %s',
                    cache_path.name, exc)
        return None


@app.get('/visualize')
def visualize(
    request:       Request,
    zone:          str       = Query('all'),
    force:         bool      = Query(False),
    authorization: str | None = Header(None),
):
    """Retourne les coordonnées 3D UMAP des embeddings brain. Cache JSON regénéré si stale."""
    # Les scopes viennent de l'authentification, plus d'un palier commercial.
    scopes = _SCOPE_ACCESS['owner'] if _is_localhost(request) else check_auth(authorization)

    # Le cache etait indexe par palier commercial. Il l'est desormais par
    # l'ensemble des scopes visibles — ce qui determine reellement le contenu.
    cache_key  = '-'.join(sorted(scopes)) or 'public'
    cache_path = BRAIN_ROOT / 'brain-engine' / f'viz_cache_{cache_key}.json'

    import db as brain_db
    need_regen  = force or not cache_path.exists()
    index_maj   = None
    if not need_regen:
        # La peremption se lit dans la DONNEE, pas sur le systeme de fichiers.
        #
        # En sqlite, la comparaison portait sur le FICHIER de base, dont le mtime
        # bougeait a chaque ecriture. La migration Dolt a pointe la meme ligne
        # vers un REPERTOIRE, dont le mtime ne bouge pas quand Dolt ecrit dans ses
        # sous-dossiers : fige au 28 avril, il rendait `need_regen` definitivement
        # faux. Le signal etait mort sans que rien le dise — c'est ce qui a laisse
        # le cache du 24 mars etre servi cinq mois.
        row = brain_db.query_one('SELECT MAX(updated_at) m FROM embeddings')
        index_maj = row['m'] if row else None
        genere = _cache_generated_at(cache_path)
        if index_maj is not None and genere is not None:
            need_regen = _as_utc(index_maj) > genere
        elif index_maj is not None:
            # Cache sans horodatage lisible : on ne peut pas dater sa fraicheur,
            # donc on ne fait pas semblant.
            need_regen = True

        # Une SUPPRESSION n'avance pas MAX(updated_at) — le detecteur ne voyait
        # que les ecritures. La purge des chemins sortis du corpus a
        # retire 2 427 chunks d'un coup : sans ce second signal, le cache aurait
        # continue de tracer des points qui n'existent plus, et rien ne l'aurait
        # dit. On compare donc aussi le compte, sur le meme predicat que la
        # regeneration.
        if not need_regen:
            marques = ','.join('%s' for _ in scopes)
            ligne = brain_db.query_one(
                'SELECT COUNT(*) n FROM embeddings WHERE indexed = 1'
                f' AND `vector` IS NOT NULL AND scope IN ({marques})', tuple(scopes))
            attendu = int(ligne['n']) if ligne else None
            observe = _cache_point_count(cache_path)
            if attendu is not None and observe is not None and attendu != observe:
                log.info('visualize: cache a %s points, index a %s — regeneration',
                         observe, attendu)
                need_regen = True

    regen_error: str | None = None
    if need_regen:
        try:
            import struct as _struct
            import numpy as _np
            import umap as _umap

            if not brain_db.table_exists('embeddings'):
                raise HTTPException(status_code=503, detail='embeddings not indexed — run migrate.py')

            # `get_raw_connection()` etait refuse en mode Dolt : la regeneration
            # echouait a chaque appel depuis la migration, et la route servait le
            # cache du 24 mars en repondant 200. Elle passe par la couche commune.
            placeholders = ','.join('%s' for _ in scopes)
            rows = brain_db.query(
                'SELECT filepath, title, scope, `vector`, chunk_text FROM embeddings'
                f' WHERE indexed = 1 AND `vector` IS NOT NULL AND scope IN ({placeholders})',
                tuple(scopes)
            )
            if not rows:
                raise RuntimeError(f'aucun chunk indexe pour les scopes {sorted(scopes)}')

            vecs = [_struct.unpack(f'{len(r["vector"])//4}f', r['vector']) for r in rows]
            X    = _np.array(vecs, dtype=_np.float32)

            t0      = __import__('time').time()
            reducer = _umap.UMAP(n_components=3, n_neighbors=15, min_dist=0.1, random_state=42, verbose=False)
            coords  = reducer.fit_transform(X)
            elapsed = __import__('time').time() - t0

            points = [
                {
                    'id':      r['filepath'],
                    'path':    r['filepath'],
                    'zone':    r['scope'] or 'unknown',
                    'label':   r['title'] or Path(r['filepath']).stem,
                    'excerpt': (r['chunk_text'] or '')[:200],
                    'x': float(coords[i, 0]),
                    'y': float(coords[i, 1]),
                    'z': float(coords[i, 2]),
                }
                for i, r in enumerate(rows)
            ]
            cache_data = {
                'points':       points,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'cached':       False,
                'umap_params':  {'n_components': 3, 'n_neighbors': 15, 'min_dist': 0.1},
                'elapsed_s':    round(elapsed, 1),
            }
            cache_path.write_text(__import__('json').dumps(cache_data))
            log.info('visualize: cache regenerated %d points in %.1fs', len(points), elapsed)
        except Exception as exc:
            log.error('visualize regen failed: %s', exc)
            if not cache_path.exists():
                raise HTTPException(status_code=503, detail=f'UMAP generation failed: {exc}')
            # Le cache de repli est servi, mais la reponse le dit. Sans ce champ,
            # la vue Cosmos affichait des donnees de mars en se croyant fraiche.
            regen_error = str(exc)

    raw = __import__('json').loads(cache_path.read_text())
    points = raw.get('points', [])
    if zone != 'all':
        points = [p for p in points if p.get('zone') == zone]

    reponse = {**raw, 'points': points, 'cached': True}
    if index_maj is not None:
        reponse['index_updated_at'] = str(index_maj)
    if regen_error:
        # `stale` est ce qui manquait : la vue Cosmos affichait des positions du
        # 24 mars sans rien qui distingue « a jour » de « ce qu'on a pu sauver ».
        reponse['stale']       = True
        reponse['regen_error'] = regen_error
    return reponse


def _unites_systemd(run=subprocess.run) -> list[dict]:
    """Les unités utilisateur du brain (`brain-*`, `dolt-*`) et leur état.

    Le moteur, le MCP, la base, l'indexation et les sauvegardes tournent sous
    systemd (`brain-engine.sh install systemd`) : `/state` ne lisait que pm2,
    absent, et ne montrait donc aucun service (audit du wiki, 29/09).
    Lecture seule. Sans systemd utilisateur, une liste vide.
    """
    try:
        r = run(['systemctl', '--user', 'list-units', '--all', '--plain', '--no-legend',
                 'brain-*', 'dolt-*'], capture_output=True, text=True, timeout=5)
    except Exception as exc:
        log.warning('state systemd error: %s', exc)
        return []
    if r.returncode != 0:
        return []
    unites = []
    for ligne in r.stdout.splitlines():
        champs = ligne.split(None, 4)
        if len(champs) < 4 or champs[1] != 'loaded':
            continue
        unites.append({'name': champs[0], 'active': champs[2], 'sub': champs[3]})
    return unites


@app.get('/state')
def state_get(request: Request = None):
    """
    Environnement fondamental dérivé — Layer 2 uniquement.
    Unités systemd + pm2 s'il y en a + git version + ports. Jamais mis en
    cache, toujours frais.
    """
    if not _is_localhost(request):
        raise HTTPException(status_code=403, detail='Layer 2 only — localhost requis')

    # pm2 status
    pm2_procs = []
    try:
        result = subprocess.run(['pm2', 'jlist'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for proc in json.loads(result.stdout):
                env = proc.get('pm2_env', {})
                pm2_procs.append({
                    'name':    proc.get('name', '?'),
                    'status':  env.get('status', 'unknown'),
                    'uptime':  env.get('pm_uptime'),
                    'restarts': env.get('restart_time', 0),
                })
    except Exception as exc:
        log.warning('state pm2 error: %s', exc)

    # Version brain (dernier commit)
    brain_version = ''
    try:
        r = subprocess.run(
            ['git', 'log', '-1', '--oneline'],
            capture_output=True, text=True, timeout=3, cwd=str(BRAIN_ROOT)
        )
        if r.returncode == 0:
            brain_version = r.stdout.strip()
    except Exception:
        pass

    import socket
    return {
        'hostname':      socket.gethostname(),
        'brain_version': brain_version,
        'systemd':       _unites_systemd(),
        'pm2':           pm2_procs,
        'ports': {
            'brain_engine': BRAIN_PORT,
            'brain_mcp':    int(os.getenv('BRAIN_MCP_PORT') or 7701),
        },
    }


# `GET /infra` et `GET /logs/{project}` sont retirés (29/09) : ils ne lisaient
# que pm2, absent quand le moteur tourne sous systemd, et `/infra` renvoyait une
# liste de services écrite en dur — Apache, Gitea — qui ne tournent pas chez un
# fork. Personne ne les appelait (ni brain-ui, ni le MCP, ni un script). L'état
# des services : `GET /state`, qui lit systemd.


# ── Zones d'écriture ───────────────────────────────────────────────────────────
# Synchronisé avec KERNEL.md (`scripts/archive/preflight-check.sh`, qui en
# portait une copie, est archivé depuis le 30/09).

# Invariants : jamais écrits par l'API. CLAUDE.md exige une confirmation humaine
# explicite pour ces fichiers — une requête HTTP ne peut pas la fournir.
KERNEL_INVARIANT: frozenset[str] = frozenset({
    'KERNEL.md', 'CLAUDE.md', 'PATHS.md', 'brain-constitution.md', 'BRAIN-INDEX.md',
})

KERNEL_ZONE_PREFIXES: tuple[str, ...] = ('agents/', 'profil/', 'scripts/')
KERNEL_ZONE_FILES:    frozenset[str]  = frozenset({'brain-compose.yml'})


def _resolve_in_brain(path: str) -> Path:
    """Résout un chemin et garantit qu'il reste sous BRAIN_ROOT.

    `is_relative_to` compare les composants du chemin. Un `startswith` textuel
    acceptait un dossier frère partageant le préfixe — `…/Brain-evil` passait.
    """
    root   = BRAIN_ROOT.resolve()
    target = (root / path).resolve()
    if target != root and not target.is_relative_to(root):
        raise HTTPException(status_code=403, detail='path traversal interdit')
    return target


# ── Les zones viennent du CORE —, branché le 11/09 ─────────────────
#
# Ces trois listes écrites à la main — cinq invariants, trois préfixes, un
# fichier — décrivaient la même règle que `scripts/hooks/pre-commit-zone`, et
# les deux ne disaient pas la même chose. Mesuré sur les 792 fichiers suivis :
#
#     kernel pour le HOOK   306        kernel pour l'API   229
#     ecart 77, dans UN SEUL SENS — l'API etait strictement plus permissive
#
# `docs/`, `contexts/` (les manifests de session), `workflows/`, `teams/` et
# quatre fichiers racine étaient gardés au commit et pas à l'écriture HTTP. Et
# `NIVEAUX.yml` — le fichier qui GOUVERNE les zones — n'était pas invariant
# pour l'API, tandis que `CLAUDE.md` l'était sans exister à la racine.
#
# Les deux gardes dérivent désormais de la même source, `NIVEAUX.yml`, par le
# même code. Identiques par CONSTRUCTION, plus par vérification.
_ZONES_CACHE: dict = {}


def _declarations_niveaux() -> tuple[dict, dict]:
    """`NIVEAUX.yml` tel qu'il est écrit — rien n'est dérivé ici.

    Mis en cache sur (mtime, taille) : une écriture est rare, mais relire et
    parser le YAML à chaque `PUT` serait un coût gratuit. Le cache se périme
    quand le fichier change, pas après un délai — il ne sert que s'il peut
    prouver sa fraîcheur.
    """
    src = BRAIN_ROOT / 'NIVEAUX.yml'
    try:
        st = src.stat()
        cle = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}, {}
    if _ZONES_CACHE.get('cle') == cle:
        return _ZONES_CACHE['niveaux'], _ZONES_CACHE['exceptions']
    if not _YAML_AVAILABLE:
        return {}, {}
    try:
        d = yaml.safe_load(src.read_text(encoding='utf-8')) or {}
    except Exception as exc:                                   # noqa: BLE001
        log.warning('NIVEAUX.yml illisible (%s) — repli sur les listes en dur', exc)
        return {}, {}
    niveaux, exceptions = {}, {}
    for bloc in d.values():
        if not isinstance(bloc, dict):
            continue
        for nom, val in bloc.items():
            if isinstance(val, dict):
                if val.get('niveau'):
                    niveaux[nom] = val['niveau']
                if val.get('zone'):
                    exceptions[nom] = val['zone']
            elif val:
                niveaux[nom] = val
    _ZONES_CACHE.update(cle=cle, niveaux=niveaux, exceptions=exceptions)
    return niveaux, exceptions


def _write_zone(rel_path: str) -> str:
    """'invariant' | 'kernel' | 'libre' — dérivé du chemin, jamais déclaré.

    La dérivation vient de `core.zones`, qui REÇOIT ce que `NIVEAUX.yml`
    déclare. Le CORE ne connaît que deux zones — `kernel` et `instance` — et
    l'invariant est propre à cette porte : il ne dit pas « qui peut écrire »
    mais « personne, par l'API ». On l'obtient en interrogeant le CORE sur un
    registre réduit aux seuls invariants, plutôt qu'en recopiant sa règle du
    préfixe le plus long.

    Repli sur les listes en dur si `NIVEAUX.yml` ou le CORE sont indisponibles :
    une garde qui s'effondre parce qu'un paquet manque laisserait tout passer.
    """
    niveaux, exceptions = _declarations_niveaux()
    if niveaux:
        try:
            from core.zones import KERNEL, Registre
        except ImportError:
            pass
        else:
            invariants = Registre(
                niveaux={c: n for c, n in niveaux.items() if n == 'invariant'})
            if invariants.zone(rel_path) == KERNEL:
                return 'invariant'
            zone = Registre(niveaux=niveaux, exceptions=exceptions).zone(rel_path)
            return 'kernel' if zone == KERNEL else 'libre'

    # Repli — les listes en dur, conservées pour ça et pour rien d'autre.
    if rel_path in KERNEL_INVARIANT:
        return 'invariant'
    if rel_path in KERNEL_ZONE_FILES or rel_path.startswith(KERNEL_ZONE_PREFIXES):
        return 'kernel'
    return 'libre'


def _open_claims() -> list[dict]:
    """Claims BSI ouverts. Une lecture impossible refuse l'écriture, jamais l'inverse."""
    try:
        return brain_db.query(
            "SELECT sess_id, scope FROM claims WHERE status = 'open' ORDER BY opened_at DESC"
        )
    except Exception as exc:
        log.error('claims illisibles: %s', exc)
        raise HTTPException(status_code=503, detail='claims illisibles — écriture refusée')


def _foreign_lock(rel_path: str, holder: str | None) -> dict | None:
    """Lock actif tenu par quelqu'un d'autre, sur n'importe quelle machine du
    réseau, ou None."""
    try:
        rows = brain_db.verrous_du_reseau("filepath = %s", (rel_path,))
    except Exception as exc:
        log.error('locks illisibles: %s', exc)
        raise HTTPException(status_code=503, detail='locks illisibles — écriture refusée')
    return next((r for r in rows if r['holder'] != holder), None)


@app.get('/brain/{path:path}')
async def brain_get(
    request:       Request,
    path:          str,
    authorization: str | None = Header(None),
):
    """Lit un fichier brain. Localhost = owner, sinon auth requise.

    La zone privée (`embed.PRIVATE_PATHS` : `profil/identity/`, `vie/`…) ne se
    lit qu'en owner. Le reste suit les zones du rôle (`_SCOPE_ACCESS`), comme
    l'écriture. Jusqu'au 1/10, tout jeton valide — `mcp`, `public`
    — lisait tout `.md` : l'indexeur protégeait ces chemins, la lecture directe
    non. Une seule liste pour les deux, jugée sur le chemin RÉSOLU : un détour
    (`agents/../profil/identity/…`) ne la contourne pas.
    """
    owner = True
    scopes = _SCOPE_ACCESS['owner']
    if not _is_localhost(request):
        scopes = check_auth(authorization)  # jeton valide, ou 401/403
        # Le rôle lu dans `_TOKEN_MAP` après validation — pas `role_from_token`,
        # qui ne sert qu'à la trace et le dit.
        jeton = (authorization or '').removeprefix('Bearer ').strip()
        owner = not _TOKEN_MAP or _TOKEN_MAP.get(jeton) == 'owner'

    safe = _resolve_in_brain(path)
    if not owner:
        import embed
        rel = safe.relative_to(BRAIN_ROOT.resolve()).as_posix()
        if embed.is_private(rel):
            raise HTTPException(status_code=403, detail='zone privée — owner seulement')
        # Hors zone privée, la lecture suit les zones du rôle, comme l'écriture
        # (tranché le 1/10) : `public` → `public`, `mcp` → tout sauf `kernel`.
        if embed.resolve_scope(rel) not in scopes:
            raise HTTPException(status_code=403, detail='zone hors de la portée du jeton')
    if not safe.exists() or not safe.is_file():
        raise HTTPException(status_code=404, detail=f'{path} introuvable')
    if not safe.suffix == '.md':
        raise HTTPException(status_code=403, detail='seuls les fichiers .md sont lisibles')

    content = safe.read_text(encoding='utf-8')
    return {'path': path, 'content': content, 'size': len(content)}


@app.put('/brain/{path:path}')
async def brain_put(
    request:       Request,
    path:          str,
    body:          dict       = Body(...),
    authorization: str | None = Header(None),
):
    """
    Écrit ou met à jour un document brain.

    L'écriture passe par les gardes que le brain possédait déjà mais que cette
    route ne consultait pas :

      invariant  KERNEL.md, CLAUDE.md, PATHS.md… → refus systématique
      kernel     agents/, profil/, scripts/, brain-compose.yml → claim BSI ouvert requis
      libre      le reste → lock BSI respecté

    body: { content: str, sess_id?: str }  — ou en-tête `X-Brain-Session`.
    """
    _readonly_guard()
    scopes = check_auth(authorization)
    target = _resolve_in_brain(path)
    root   = BRAIN_ROOT.resolve()
    if target == root or target.is_dir():
        raise HTTPException(status_code=422, detail='chemin de fichier requis')
    rel  = str(target.relative_to(root))
    zone = _write_zone(rel)

    # 1. Les invariants ne s'écrivent pas par l'API — CLAUDE.md exige une
    #    confirmation humaine explicite, qu'une requête HTTP ne peut pas donner.
    if zone == 'invariant':
        raise HTTPException(
            status_code=403,
            detail=f'{rel} est un invariant kernel — édition humaine en session, jamais par l\'API',
        )

    # 1ter. Un satellite n'écrit pas le kernel. Sa posture le déclare
    #       (`kernel_write: false`) ; `serve.py` la lit et lance le moteur en
    #       `satellite`. Le refus vient du moteur, plus de la session qu'il
    #       restreint — et il passe avant le jeton, le claim et la base.
    if zone == 'kernel' and BRAIN_MODE == 'satellite':
        raise HTTPException(
            status_code=403,
            detail=f'instance satellite — la zone kernel s\'écrit sur le master, pas ici ({rel})',
        )

    # 1bis. Autorisation PAR ZONE, et non globale. Le rôle `mcp` a les scopes
    #       public/work/instance/satellite mais pas `kernel` : il peut donc
    #       écrire de la data, jamais le programme. C'est ce qui empêche l'agent
    #       qui écrit d'hériter des droits du système qu'il modifie.
    required_scope = 'kernel' if zone == 'kernel' else 'work'
    if required_scope not in scopes:
        raise HTTPException(
            status_code=403,
            detail=f'zone {zone} : scope `{required_scope}` requis pour écrire {rel}',
        )

    content = body.get('content', '')
    if not content:
        raise HTTPException(status_code=422, detail='content requis')

    sess_id = body.get('sess_id') or (request.headers.get('x-brain-session') if request else None)

    # 2. Zone kernel : un claim BSI ouvert est obligatoire. Pas de claim, pas
    #    d'écriture — c'est la discipline que le brain s'impose déjà au boot.
    if zone == 'kernel':
        claims = _open_claims()
        if not claims:
            raise HTTPException(
                status_code=409,
                detail=f'aucun claim BSI ouvert — écriture kernel refusée sur {rel}',
            )
        known = {c['sess_id']: (c['scope'] or '') for c in claims}
        if sess_id:
            if sess_id not in known:
                raise HTTPException(status_code=409, detail=f'claim {sess_id} non ouvert')
        elif len(known) > 1:
            raise HTTPException(
                status_code=409,
                detail=f'{len(known)} claims ouverts — préciser sess_id',
            )
        else:
            sess_id = next(iter(known))
        # Le scope reste informatif : son vocabulaire n'est pas normalisé
        # (« pilote/veille-repo » ne s'exprime pas en chemins). Tracé, pas opposé.
        log.info('brain_put kernel sess=%s scope=%r path=%s', sess_id, known[sess_id], rel)

    # 3. Un lock actif tenu par un autre bloque l'écriture, kernel ou non.
    lock = _foreign_lock(rel, sess_id)
    if lock:
        raise HTTPException(
            status_code=409,
            detail=f"lock détenu par {lock['holder']} jusqu'à {lock['expires_at']}",
        )

    # Écriture
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    # Trace d'audit : sans identité de l'écrivain, on sait quoi a changé mais
    # pas qui l'a changé — la moitié inutile de l'information.
    writer = 'localhost' if _is_localhost(request) else role_from_token(authorization)
    log.info('brain_put zone=%s role=%s sess=%s path=%s (%d bytes)',
             zone, writer, sess_id or 'none', rel, len(content))

    # Signal reindex — par la FILE, plus par un sous-processus.
    #
    # Le defaut historique vaut d'etre garde en memoire : ceci pointait sur
    # `index.py` depuis le 17/03, un fichier qui n'a jamais existe. `Popen`
    # reussit (il fork), donc la route repondait `reindex: true` pendant que
    # l'enfant mourait sur un « can't open file ». Le cron de 6 h rattrapait
    # l'index, ce qui a masque la panne pendant six mois.
    #
    # La file rend ce defaut-la impossible : il n'y a plus de chemin a viser,
    # plus d'interpreteur a supposer, et un echec du worker se journalise au
    # lieu de mourir dans un processus que personne ne regarde.
    reindex_triggered = _demander_reindex(rel)

    # Broadcast WebSocket — les clients rechargent le point modifié
    await _broadcast({
        'type':    'brain:updated',
        'payload': {'path': path, 'reindex': reindex_triggered,
                    'zone': zone, 'sess_id': sess_id},
    })

    return {'ok': True, 'path': path, 'reindex': reindex_triggered}


# ── Ambient Brain ──────────────────────────────────────────────────────────────

@app.post('/ambient/notify')
async def ambient_notify(
    body:          dict       = Body(...),
    authorization: str | None = Header(None),
    request:       Request    = None,
):
    """Reçoit un event du daemon Ambient Brain et le broadcast aux clients WebSocket."""
    _readonly_guard()
    if not _is_localhost(request):
        # La gate tier etait ici le seul controle pour le non-localhost : la
        # retirer sans rien mettre ouvrirait la route. Scope `work` requis.
        scopes = check_auth(authorization)
        if 'work' not in scopes:
            raise HTTPException(status_code=403, detail='zone work requise')
    event = {
        'type':    body.get('type', 'ambient:event'),
        'context': body.get('context', ''),
        'message': body.get('message', ''),
        'level':   body.get('level', 'info'),
        'ts':      body.get('ts', ''),
    }
    log.info('ambient_notify context=%s msg=%s', event['context'], event['message'])
    await _broadcast(event)
    return {'ok': True}


# ── WebSocket ──────────────────────────────────────────────────────────────────

@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket temps réel — les événements BSI (claims, verrous) et ambient.

    La boucle locale passe ; le réseau montre un jeton, comme sur les autres
    routes. Mesuré le 30/09 : la route acceptait n'importe qui et lui
    rediffusait identifiants de session, scopes, chemins verrouillés et corps
    des `PATCH` de claims — à tout appareil du réseau local."""
    if not _is_localhost(websocket):
        try:
            check_auth(websocket.headers.get('authorization'))
        except HTTPException:
            await websocket.close(code=1008)
            return
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive ping
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)


async def _broadcast(payload: dict) -> None:
    """Broadcast JSON à tous les clients WebSocket connectés."""
    import json as _json
    dead = []
    for ws in list(_ws_clients):
        try:
            await ws.send_text(_json.dumps(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ── BSI endpoints (BRAIN-036) ────────────────────────────────────────────────

import db as brain_db

# ── BSI peers — chargement depuis brain-compose.local.yml ─────────────────

def _load_peers() -> list[dict]:
    """Charge les peers actifs depuis brain-compose.local.yml."""
    compose_local = BRAIN_ROOT / 'brain-compose.local.yml'
    if not compose_local.exists():
        return []
    try:
        if _YAML_AVAILABLE:
            with open(compose_local) as f:
                data = yaml.safe_load(f) or {}
        else:
            return []
        peers = data.get('peers', {})
        return [
            {'name': name, 'url': p.get('url', '')}
            for name, p in peers.items()
            if isinstance(p, dict) and p.get('active', False)
        ]
    except Exception as exc:
        log.warning('peers load error: %s', exc)
        return []


def _fetch_peer_claims(peer_url: str, timeout: float = 2.0) -> list[dict] | None:
    """Claims d'un peer. `None` = injoignable ; `[]` = joignable, aucun claim.

    🔴 Cette fonction rendait `[]` dans les DEUX cas. `bsi_network` testait
    pourtant `if peer_claims is not None and isinstance(..., list)` pour
    décider `online` / `offline` : une liste vide passe les deux conditions,
    donc **la branche `offline` n'était atteignable par aucune valeur**.

    Un peer éteint s'affichait `online, claims_open: 0` — exactement comme un
    peer allumé sans session en cours. Les deux états les plus différents du
    réseau BSI se ressemblaient trait pour trait. Mesuré le 15/09 sur un peer
    pointé vers un port mort ; `laptop` est dans ce cas tous les jours.

    C'est le motif déjà écrit dans `collaboration.md` : *une métrique qui n'a
    jamais rien enregistré ressemble à une métrique à zéro.*

    Le `log.debug` devient `log.warning` : un peer déclaré `active` qui ne
    répond pas n'est pas un détail de mise au point.
    """
    try:
        req = urllib.request.Request(f"{peer_url.rstrip('/')}/bsi/claims")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            recu = json.loads(resp.read())
            # Un peer qui répond autre chose qu'une liste est aussi inutilisable
            # qu'un peer muet — et le dire `online` serait aussi faux.
            return recu if isinstance(recu, list) else None
    except Exception as exc:                                # noqa: BLE001
        log.warning('peer %s injoignable (%s: %s) — non consulté',
                    peer_url, type(exc).__name__, exc)
        return None

## _bsi_conn() supprimé — remplacé par brain_db.query/execute (db.py)


# ── Focus (généré depuis Dolt) ────────────────────────────────────────────────

@app.get('/focus')
def focus_generated(
    request:       Request     = None,
    authorization: str | None  = Header(None),
):
    """Focus généré depuis Dolt — remplace focus.md statique. Zéro drift."""
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'work' not in scopes:
            raise HTTPException(status_code=403, detail='Zone work requise')

    result = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'cap': None,
        'front': [],
        'active': [],
        'stasis_count': 0,
        'stasis_summary': [],
        'projects': [],
        'last_session': None,
        'archived_count': 0,
    }

    # Cap (human file)
    cap_path = BRAIN_ROOT / 'brain' / 'cap.md'
    if cap_path.exists():
        try:
            content = cap_path.read_text(encoding='utf-8')
            # Strip header and comment lines
            lines = [l for l in content.split('\n')
                     if l.strip() and not l.startswith('#') and not l.startswith('>')]
            result['cap'] = '\n'.join(lines)
        except Exception:
            pass

    try:
        # Front rotatif
        front = brain_db.query("""
            SELECT id, title, status, project, priority, next_step,
                   total_sessions, total_duration, last_touched
            FROM intentions WHERE front = 1
            ORDER BY front_order ASC
        """)
        result['front'] = front

        # Active (non-front)
        active = brain_db.query("""
            SELECT id, title, project, priority, next_step, total_sessions
            FROM intentions WHERE status = 'active' AND front = 0
            -- `CASE` plutôt que `FIELD()` : cette dernière est propre à MySQL
            -- et lève `no such function` en SQLite, où l'`except` alentour la
            -- transforme en « aucune intention ». Un fork ne voyait pas une
            -- erreur, il voyait du vide.
            ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2
                                   WHEN 'low' THEN 3 ELSE 4 END,
                     updated_at DESC
        """)
        result['active'] = active

        # Stasis
        stasis = brain_db.query("""
            SELECT id, project, stasis_reason FROM intentions WHERE status = 'stasis'
            ORDER BY project, id
        """)
        result['stasis_count'] = len(stasis)
        result['stasis_summary'] = stasis

        # Archived count
        result['archived_count'] = brain_db.count('intentions', "status = 'archived'")

        # Projects with active intentions
        projects_raw = brain_db.query("""
            SELECT project, COUNT(*) as intention_count,
                   SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_count,
                   SUM(CASE WHEN status = 'stasis' THEN 1 ELSE 0 END) as stasis_count
            FROM intentions
            WHERE status IN ('active', 'stasis', 'identified')
            AND project IS NOT NULL AND project != ''
            GROUP BY project
            ORDER BY active_count DESC, project
        """)
        result['projects'] = projects_raw

    except Exception as exc:
        log.warning('focus Dolt query failed: %s', exc)

    # Last session from claims
    try:
        last = brain_db.query_one("""
            SELECT sess_id, type, project, opened_at, closed_at, duration_min, result, energy
            FROM claims WHERE status = 'closed'
            ORDER BY closed_at DESC LIMIT 1
        """)
        result['last_session'] = last
    except Exception:
        pass

    return result


# ── Intentions (Dolt) ─────────────────────────────────────────────────────────

@app.get('/intentions')
def intentions_list(
    status:        str | None  = Query(None),
    project:       str | None  = Query(None),
    front_only:    bool        = Query(False),
    request:       Request     = None,
    authorization: str | None  = Header(None),
):
    """Liste les intentions depuis Dolt. Filtres optionnels par status, project, front."""
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'work' not in scopes:
            raise HTTPException(status_code=403, detail='Zone work requise')

    conditions = []
    params = []

    if status:
        conditions.append("i.status = %s")
        params.append(status)
    if project:
        conditions.append("i.project = %s")
        params.append(project)
    if front_only:
        conditions.append("i.front = 1")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    try:
        intentions = brain_db.query(f"""
            SELECT i.id, i.title, i.status, i.project, i.domain, i.scope,
                   i.priority, i.brief, i.next_step, i.stasis_reason,
                   i.front, i.front_order, i.total_sessions, i.total_duration,
                   i.last_touched, i.created_at, i.updated_at, i.agents, i.adrs
            FROM intentions i
            {where}
            -- `CASE` plutôt que `FIELD()` — portable des deux côtés.
            ORDER BY i.front DESC, i.front_order ASC,
                     CASE i.status WHEN 'active' THEN 1 WHEN 'stasis' THEN 2
                                   WHEN 'identified' THEN 3 WHEN 'done' THEN 4
                                   WHEN 'archived' THEN 5 ELSE 9 END,
                     CASE i.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2
                                     WHEN 'low' THEN 3 ELSE 4 END,
                     i.updated_at DESC
        """, tuple(params))
    except Exception:
        # Fallback si table absente (template sans Dolt)
        return []

    # Enrichir avec tags et edges
    for intent in intentions:
        iid = intent['id']
        try:
            intent['tags'] = [r['tag'] for r in brain_db.query(
                "SELECT tag FROM intention_tags WHERE intention_id = %s", (iid,)
            )]
        except Exception:
            intent['tags'] = []
        try:
            intent['depends_on'] = [r['source_id'] for r in brain_db.query(
                "SELECT source_id FROM intention_edges WHERE target_id = %s AND relation = 'blocks'", (iid,)
            )]
            intent['blocks'] = [r['target_id'] for r in brain_db.query(
                "SELECT target_id FROM intention_edges WHERE source_id = %s AND relation = 'blocks'", (iid,)
            )]
        except Exception:
            intent['depends_on'] = []
            intent['blocks'] = []
        try:
            intent['sessions'] = [r['sess_id'] for r in brain_db.query(
                "SELECT sess_id FROM intention_sessions WHERE intention_id = %s ORDER BY linked_at DESC", (iid,)
            )]
        except Exception:
            intent['sessions'] = []

        # Parse JSON fields
        import json as _json
        for field in ('agents', 'adrs'):
            val = intent.get(field)
            if isinstance(val, str):
                try:
                    intent[field] = _json.loads(val)
                except Exception:
                    intent[field] = []
            elif val is None:
                intent[field] = []

    return intentions


@app.get('/intentions/{intention_id}')
def intention_detail(
    intention_id:  str,
    request:       Request     = None,
    authorization: str | None  = Header(None),
):
    """Détail d'une intention spécifique avec toutes les relations."""
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'work' not in scopes:
            raise HTTPException(status_code=403, detail='Zone work requise')

    try:
        intent = brain_db.query_one(
            "SELECT * FROM intentions WHERE id = %s", (intention_id,)
        )
    except Exception:
        raise HTTPException(status_code=404, detail='Intention not found')

    if not intent:
        raise HTTPException(status_code=404, detail='Intention not found')

    import json as _json
    for field in ('agents', 'adrs'):
        val = intent.get(field)
        if isinstance(val, str):
            try:
                intent[field] = _json.loads(val)
            except Exception:
                intent[field] = []
        elif val is None:
            intent[field] = []

    iid = intent['id']
    try:
        intent['tags'] = [r['tag'] for r in brain_db.query(
            "SELECT tag FROM intention_tags WHERE intention_id = %s", (iid,)
        )]
        intent['depends_on'] = [r['source_id'] for r in brain_db.query(
            "SELECT source_id FROM intention_edges WHERE target_id = %s AND relation = 'blocks'", (iid,)
        )]
        intent['blocks'] = [r['target_id'] for r in brain_db.query(
            "SELECT target_id FROM intention_edges WHERE source_id = %s AND relation = 'blocks'", (iid,)
        )]
        intent['sessions'] = [r['sess_id'] for r in brain_db.query(
            "SELECT sess_id FROM intention_sessions WHERE intention_id = %s ORDER BY linked_at DESC", (iid,)
        )]
    except Exception:
        intent['tags'] = []
        intent['depends_on'] = []
        intent['blocks'] = []
        intent['sessions'] = []

    return intent


@app.get('/bsi/claims')
def bsi_claims_list(
    status:        str | None  = Query(None),
    include_peers: bool        = Query(False),
    request:       Request     = None,
    authorization: str | None  = Header(None),
):
    """Liste les claims BSI depuis la base.

    Deux formes de réponse, selon `include_peers` :

        sans le parametre   [ {claim}, {claim}, ... ]        une liste plate
        ?include_peers=true { "claims": [...],
                              "peers_injoignables": [...] }  un objet

    La seconde porte les peers qui n'ont pas répondu. Sans elle, un appelant ne
    distinguait pas « le laptop n'a aucune session » de « le laptop est
    éteint » — les deux rendaient les mêmes claims locaux, sans un mot.
    """
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'work' not in scopes:
            raise HTTPException(status_code=403, detail='Zone work requise')

    # Local claims — ceux de cette base, et ceux que chaque machine satellite a
    # ouverts sur SA branche (BRAIN-078) : chaque machine fait foi pour ses lignes.
    if status:
        local_claims = brain_db.claims_du_reseau("status = %s", (status,))
    else:
        local_claims = brain_db.claims_du_reseau()
    local_claims.sort(key=lambda c: c.get('opened_at') or '', reverse=True)

    # Tag local claims with instance
    compose_local = BRAIN_ROOT / 'brain-compose.local.yml'
    machine_name = 'local'
    if compose_local.exists() and _YAML_AVAILABLE:
        try:
            with open(compose_local) as f:
                data = yaml.safe_load(f) or {}
            machine_name = data.get('machine', 'local')
        except Exception:
            pass

    for c in local_claims:
        c['_source'] = c.pop('_branche', None) or machine_name

    if not include_peers:
        return local_claims

    # Fetch peer claims
    #
    # `_fetch_peer_claims` rend `None` pour un peer injoignable, là où il
    # rendait `[]` — sans quoi la boucle ci-dessous itérerait sur `None`.
    #
    # 🔴 **La forme de la réponse change avec `include_peers`, et c'est voulu.**
    # Sans le paramètre, elle reste une liste plate : c'est le contrat que le
    # Dashboard, `_fetch_peer_claims` et les contrôles consomment, et rien ne
    # bouge pour eux.
    #
    # Avec, elle devient un objet qui porte AUSSI les peers muets. Une liste
    # plate n'avait pas de place pour « le laptop n'a pas répondu », et un
    # appelant ne distinguait donc pas « le laptop n'a aucune session » de
    # « le laptop est éteint » — les deux rendaient les mêmes claims locaux.
    #
    # Deux formes pour une route se défendent mal en général. Ici la raison
    # tient : `include_peers=true` ne pose pas la même question. Elle demande
    # l'état d'un RÉSEAU, pas d'une machine, et un réseau doit pouvoir répondre
    # « voici ce que j'ai, et voici qui n'a pas répondu ». Décidé le 16/09 par
    # L'owner, après audit : aucun appelant n'utilisait ce mode, donc la dette se
    # soldait sans casse — et ne pas la solder l'aurait laissée à celui qui
    # aurait écrit le premier appelant.
    all_claims = list(local_claims)
    injoignables = []
    for peer in _load_peers():
        peer_claims = _fetch_peer_claims(peer['url'])
        if peer_claims is None:
            injoignables.append(peer['name'])
            continue
        for c in peer_claims:
            c['_source'] = peer['name']
            if status and c.get('status') != status:
                continue
            all_claims.append(c)

    # `peers_injoignables` est toujours présent, même vide — pour la même raison
    # que dans `POST /bsi/locks` : un champ qui n'apparaît que dans le mauvais
    # cas oblige l'appelant à distinguer « absent parce que tout va bien » de
    # « absent parce que je parle à une vieille version ».
    return {'claims': all_claims, 'peers_injoignables': injoignables}


@app.get('/bsi/network')
def bsi_network(
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Vue réseau BSI — état de chaque peer + claims open agrégés."""
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'work' not in scopes:
            raise HTTPException(status_code=403, detail='Zone work requise')

    # Local
    local_open = brain_db.count('claims', "status = 'open'")
    local_total = brain_db.count('claims')

    compose_local = BRAIN_ROOT / 'brain-compose.local.yml'
    machine_name = 'local'
    if compose_local.exists() and _YAML_AVAILABLE:
        try:
            with open(compose_local) as f:
                data = yaml.safe_load(f) or {}
            machine_name = data.get('machine', 'local')
        except Exception:
            pass

    nodes = [{
        'name': machine_name,
        'url': f'http://localhost:{BRAIN_PORT}',
        'status': 'online',
        'claims_open': local_open,
        'claims_total': local_total,
    }]

    # Peers
    for peer in _load_peers():
        peer_claims = _fetch_peer_claims(peer['url'])
        # Ce test était déjà écrit ainsi — il était simplement inatteignable :
        # `_fetch_peer_claims` rendait `[]` sur échec, et une liste vide passe
        # les deux conditions. La branche `offline` ci-dessous n'a jamais servi.
        # C'est la fonction qui a été corrigée, pas ce test : il disait la
        # bonne chose depuis le début, à une source qui ne savait pas répondre.
        if peer_claims is not None and isinstance(peer_claims, list):
            open_count = sum(1 for c in peer_claims if c.get('status') == 'open')
            nodes.append({
                'name': peer['name'],
                'url': peer['url'],
                'status': 'online',
                'claims_open': open_count,
                'claims_total': len(peer_claims),
            })
        else:
            nodes.append({
                'name': peer['name'],
                'url': peer['url'],
                'status': 'offline',
                'claims_open': 0,
                'claims_total': 0,
            })

    return {'nodes': nodes, 'peer_count': len(nodes)}


# ── La file de reindexation — ───────────────────────────────────────
#
# `PUT /brain/{path}` lancait `python3 embed.py --file` en sous-processus. Deux
# capacites declarees `core` en heritaient un mecanisme `sousproc`, et un CORE
# portable ne peut pas supposer un interpreteur et un fichier a un chemin.
#
# ⚠️ Le fork etait NON BLOQUANT, a dessein : la reindexation lit, decoupe, et
# fait un aller-retour vers Ollama par chunk. L'appeler en ligne dans la route
# rendrait `PUT` lent a proportion du fichier. Le remplacer par un import nu
# aurait donc corrige le mecanisme en cassant la latence.
#
# D'ou une FILE : la route depose un chemin et rend la main ; un worker unique
# la vide en appelant `embed.run()` **en bibliotheque**.
#
# Pourquoi `embed.run` et pas une reimplementation : c'est le MEME code que la
# passe complete. L'equivalence est acquise par construction, pas prouvee puis
# esperee — et `embed.py` porte la politique de corpus, qui appartient a
# l'instance. Le CORE, lui, calcule deja dedans depuis le branchement du 11/09
# (`core.indexation.par_sections`).
#
# Le worker est UNIQUE a dessein : deux reindexations concurrentes se
# disputeraient Ollama et la meme table. Et la file DEDOUBLONNE : dix ecritures
# du meme fichier avant que le worker ne se reveille valent une reindexation.

_FILE_REINDEX: asyncio.Queue | None = None
_REINDEX_EN_ATTENTE: set[str] = set()


async def _worker_reindex() -> None:
    """Vide la file, un fichier a la fois, hors du chemin de la requete."""
    assert _FILE_REINDEX is not None
    while True:
        rel = await _FILE_REINDEX.get()
        try:
            # `embed.run` ecrit sur stdout : on le detourne vers le journal,
            # sinon la sortie du serveur devient illisible et l'echec muet.
            import contextlib
            import io

            import embed
            tampon = io.StringIO()
            def _indexer():
                with contextlib.redirect_stdout(tampon):
                    embed.run(target_file=rel)
            # Bloquant par nature : dans un thread, pour ne pas figer la boucle
            # d'evenements pendant les appels a Ollama.
            await asyncio.to_thread(_indexer)
            sortie = tampon.getvalue().strip()
            log.info('reindex %s — %s', rel,
                     sortie.replace('\n', ' | ')[:300] or 'rien a faire')
        except Exception as exc:                           # noqa: BLE001
            # Une reindexation qui echoue ne doit pas tuer le worker : le
            # fichier suivant merite sa chance, et le cron rattrapera.
            log.error('reindex %s a echoue (%s: %s) — le cron rattrapera',
                      rel, type(exc).__name__, exc)
        finally:
            _REINDEX_EN_ATTENTE.discard(rel)
            _FILE_REINDEX.task_done()


def _demarrer_worker_reindex() -> None:
    """Cree la file et son worker, au premier besoin.

    Demarrage PARESSEUX, et non un `@app.on_event('startup')` — pour deux
    raisons mesurees le 11/09 :

    1. `on_event` est deprecie dans FastAPI ; le remplacant, `lifespan`, se
       passe a `FastAPI(...)`, donc trente lignes plus haut que ce worker.
    2. 🔴 `tools/parite_capacites.py` a REFUSE le decorateur : son extracteur
       de routes voyait `on_event` comme un verbe HTTP inconnu et s'est arrete
       net — « les routes qui l'utilisent ne sont ni comptees ni refusees :
       elles n'existent pour personne ». Il avait raison de ne pas deviner.

    Paresseux marche aussi hors serveur : un test qui appelle
    `_demander_reindex` obtient sa file sans monter de cycle de vie.
    """
    global _FILE_REINDEX
    if _FILE_REINDEX is not None:
        return
    _FILE_REINDEX = asyncio.Queue()
    asyncio.get_running_loop().create_task(_worker_reindex())
    log.info('file de reindexation prete — plus de sous-processus')


def _demander_reindex(rel: str) -> bool:
    """Depose un chemin dans la file. `False` si elle n'a pas pu etre creee.

    Rend `False` plutot que de lever : une reindexation manquee est rattrapee
    par le cron, une exception ferait echouer une ecriture DEJA FAITE sur le
    disque — on repondrait 500 pour un fichier correctement ecrit.
    """
    try:
        _demarrer_worker_reindex()
    except RuntimeError:                 # pas de boucle d'evenements ici
        log.error('reindex impossible hors boucle asyncio — %s', rel)
        return False
    if rel in _REINDEX_EN_ATTENTE:
        return True                      # deja en file : un passage suffit
    _REINDEX_EN_ATTENTE.add(rel)
    _FILE_REINDEX.put_nowait(rel)
    return True


def _deriver_session() -> None:
    """Fait naître la session avec le claim —,.

    Repris de `scripts/bsi-claim.sh`, où il vit depuis le 05/09, parce qu'une
    porte gouvernée doit produire le **même effet** que la porte qu'elle
    remplace. Sans lui, basculer le script sur cette route serait une perte.

    Rien ne planifie `migrate.py` — ni cron, ni timer, vérifié le 05/09. La
    table `sessions` ne se remplit qu'au moment où un claim s'ouvre.

    **Le claim est le point critique : s'il est écrit, la session peut
    attendre.** Un échec de dérivation ne fait donc pas échouer la requête — mais
    il se plaint. `migrate_sessions_backend` attrape ses propres erreurs et les
    imprime sur stdout, qu'on détourne : sans le ré-émetteur ci-dessous, un
    échec passerait inaperçu, exactement le défaut que ce mécanisme traque.
    """
    import contextlib
    import io
    try:
        import migrate
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon):
            total = migrate.migrate_sessions_backend()
        if not total:
            sortie = tampon.getvalue().strip()
            if sortie:
                log.warning('derivation de session : %s', sortie)
    except Exception as exc:                               # noqa: BLE001
        log.error('session non dérivée (%s: %s) — `python3 brain-engine/'
                  'migrate.py` la rattrapera', type(exc).__name__, exc)


@app.post('/bsi/claims')
async def bsi_claims_create(
    body:          dict       = Body(...),
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Crée un claim BSI dans la base."""
    _readonly_guard()
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'kernel' not in scopes:
            raise HTTPException(status_code=403, detail='Zone kernel requise (owner only)')

    sess_id = body.get('sess_id')
    if not sess_id:
        raise HTTPException(status_code=422, detail='sess_id requis')

    # ── La RÈGLE vient du CORE, le SCHÉMA reste à l'instance — ───────
    #
    # Branché le 11/09, une fois `myeline-core` installé en paquet. Cette route
    # écrivait sans rien vérifier : ni la forme de l'identifiant, ni le
    # chevauchement de scope, ni le projet. `scripts/bsi-claim.sh` le faisait,
    # elle non — deux portes sur la même table, deux comportements.
    #
    # `core.bsi` porte les trois, avec 39 garanties, et décide **exactement**
    # comme le shell : vérifié le 11/09 sur huit cas de conflit, le seul écart
    # (un `scope` NULL) étant impossible — la colonne est `NOT NULL`.
    #
    # Ce qui n'est PAS délégué : l'écriture elle-même. `core.bsi.ouvre()` écrit
    # dix colonnes, cette table en porte seize — `handoff_level`, `instance`,
    # `parent_sess`, `satellite_*`, `theme_branch` sont des notions de CETTE
    # installation, pas du programme. Les déléguer les ferait disparaître.
    #
    # C'est la frontière que Myéline sépare : le CORE dit **ce qui est permis**,
    # l'instance dit **ce qu'elle range**.
    from core.bsi import BSI, valide, projet_depuis_scope

    try:
        sess_id = valide(sess_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    scope = body.get('scope', '')
    zone  = body.get('zone')

    # Le verrou voit aussi les machines satellites (BRAIN-078).
    bsi = BSI(brain_db.depot(), ouverts_du_reseau=brain_db.ouverts_du_reseau)
    bloquant = bsi.conflit(scope, zone or 'project')
    if bloquant is not None:
        raise HTTPException(
            status_code=409,
            detail=f'scope verrouillé par {bloquant.sess_id} ({bloquant.scope}) '
                   f'— fermer ce claim, ou choisir un autre scope',
        )

    # ── Ce qui se chevauche sans bloquer, et qu'il faut DIRE — ───────
    #
    # `conflit()` répond « qui bloque » ; hors zone kernel il rend None, et la
    # route se taisait. `scripts/bsi-claim.sh`, lui, affichait
    # « ⚠️ SCOPE OVERLAP détecté » avec les deux identifiants.
    #
    # 🔴 Basculer le script sur cette route l'aurait donc fait **perdre
    # l'avertissement** — et aucune comparaison d'écritures ne l'aurait montré,
    # puisque les deux écrivent exactement la même ligne. Trouvé en relisant ce
    # que les deux portes DISENT, pas seulement ce qu'elles écrivent.
    chevauchements = [
        {'sess_id': c.sess_id, 'scope': c.scope}
        for c in bsi.recouvrements(scope) if c.sess_id != sess_id
    ]

    # Auto-extraction du projet (BRAIN-046 + BRAIN-047). La route ne l'écrivait
    # pas du tout : tout claim ouvert par HTTP arrivait sans projet.
    projet = projet_depuis_scope(scope, body.get('project'))

    # ── L'enum `handoff_level`, lu dans le schéma et jamais recopié ──────────
    #
    # Ajouté le 11/09 pour étape 4. `scripts/bsi-claim.sh` valide ce
    # niveau depuis le 05/09 ; la route, non. Or **MySQL comme Dolt avalent une
    # valeur hors enum en chaîne vide, sans erreur** — un claim ouvert par HTTP
    # avec un niveau fautif perdait son handoff en silence.
    #
    # L'enum se LIT dans la base plutôt que de se recopier ici : une règle
    # dupliquée dérive de sa source. Le coût est nul dans le cas nominal —
    # `handoff_level` est rarement passé, et sans lui on ne lit rien.
    handoff = body.get('handoff_level')
    if handoff is not None:
        try:
            col = brain_db.query("SHOW COLUMNS FROM claims LIKE 'handoff_level'")
            permis = re.findall(r"'([^']*)'", str(col[0]['Type'])) if col else []
        except Exception:                                  # noqa: BLE001
            permis = []
        if permis and handoff not in permis:
            raise HTTPException(
                status_code=422,
                detail=f'handoff_level invalide : {handoff!r} — attendu '
                       f'{" | ".join(permis)}. Une valeur hors enum est avalée '
                       f'en chaîne vide, sans erreur.',
            )
        if not permis:
            log.warning('enum handoff_level illisible — %r accepté sans contrôle',
                        handoff)

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    ttl_hours = body.get('ttl_hours', 4)

    # ── La session qui porte le claim — BRAIN-077, ─────────────────
    #
    # `agent_session` n'est écrit que si la base porte la colonne. Sinon le
    # claim s'ouvre comme avant, et la réponse le DIT (`identite`) : une
    # identité transmise et jetée en silence ressemblerait à une identité
    # enregistrée, et la fermeture croirait pouvoir s'y fier.
    agent_session = body.get('agent_session') or None
    if agent_session is None:
        identite = 'non transmise'
    elif bsi.porte_identite:
        identite = 'enregistree'
    else:
        identite, agent_session = 'base sans colonne agent_session', None
    col_identite = ', agent_session' if agent_session else ''
    val_identite = ', %s' if agent_session else ''

    brain_db.execute(f"""
        REPLACE INTO claims
            (sess_id, type, scope, status, opened_at, handoff_level,
             ttl_hours, expires_at, instance, parent_sess,
             satellite_type, satellite_level, theme_branch, zone, mode, project,
             story_angle{col_identite})
        VALUES (%s, %s, %s, %s, %s, %s, %s, DATE_ADD(%s, INTERVAL %s HOUR), %s, %s, %s, %s, %s, %s, %s, %s, %s{val_identite})
    """, (
        sess_id,
        body.get('type', 'work'),
        scope,
        body.get('status', 'open'),
        body.get('opened_at', now),
        body.get('handoff_level'),
        ttl_hours,
        body.get('opened_at', now), ttl_hours,
        body.get('instance'),
        body.get('parent_sess'),
        body.get('satellite_type'),
        body.get('satellite_level'),
        body.get('theme_branch'),
        zone,
        body.get('mode'),
        projet,
        # Dernière colonne que `bsi-claim.sh` écrivait et pas la route —
        # l'angle narratif de la session.
        body.get('story_angle'),
    ) + ((agent_session,) if agent_session else ()),
        commit_msg=f'claim ouvert : {sess_id}')
    log.info('bsi_claims_create sess_id=%s', sess_id)

    # ── La session naît avec le claim ───────────────────────────────────────
    #
    # Rien ne planifie `migrate.py` — ni cron, ni timer, vérifié le 05/09. La
    # table `sessions` ne se remplit donc qu'au moment où un claim s'ouvre, et
    # `bsi-claim.sh` le fait depuis. La route, non : un claim ouvert par
    # HTTP ne faisait naître aucune session, et le contrôle « registres en base »
    # rougissait dessus.
    #
    # C'est le prérequis de la bascule du script : une porte
    # gouvernée doit produire le MÊME effet que la porte qu'elle remplace,
    # sinon la bascule est une perte.
    #
    # On appelle la dérivation de `migrate.py` plutôt que de recopier son
    # INSERT : elle porte le `CAST(handoff_level AS CHAR)` sans lequel Dolt
    # écrit l'index de l'enum au lieu de son littéral — ce défaut-là a déjà
    # coûté 118 `'1'` le 05/09.
    _deriver_session()

    await _broadcast({
        'type': 'bsi:claim:open',
        'payload': {'sess_id': sess_id, 'scope': scope, 'status': 'open'},
    })

    # `overlap` est toujours présent, vide ou non : un champ qui n'apparaît que
    # parfois se lit mal, et l'appelant finit par ne plus le regarder.
    return {'ok': True, 'sess_id': sess_id, 'project': projet,
            'overlap': chevauchements, 'identite': identite}


def _duree_du_claim(opened_at) -> int | None:
    """Minutes écoulées depuis l'ouverture — la métrique de BRAIN-046.

    Même calcul que `scripts/bsi-claim.sh:cmd_close`, et même précaution, pour
    la même raison mesurée le 22/08 : le backend rend un `datetime`, pas une
    chaîne. `strptime` levait alors `TypeError`, qu'un `except: pass` avalait —
    43 claims fermés, 43 sans durée, et rien ne le disait. On accepte donc les
    deux formes, et un échec se plaint.

    Les dates sont stockées en UTC ; un datetime naïf le sous-entend.
    """
    if not opened_at:
        return None
    try:
        if isinstance(opened_at, datetime):
            ouvert = opened_at
        else:
            ouvert = datetime.strptime(str(opened_at)[:19], '%Y-%m-%d %H:%M:%S')
        if ouvert.tzinfo is None:
            ouvert = ouvert.replace(tzinfo=timezone.utc)
        return max(1, int((datetime.now(timezone.utc) - ouvert).total_seconds() / 60))
    except (ValueError, TypeError) as err:
        log.warning('duree non calculee (%s: %s) — opened_at=%r',
                    type(err).__name__, err, opened_at)
        return None


# L'énergie de clôture a TROIS niveaux (BRAIN-046) — tranché par l'owner le
# 29/09. Rien ne le vérifiait : mesuré le même jour, une vingtaine de valeurs en
# base (« 5 », « high », « 4 », « haute », « 9 », « energized »…), aucune série
# comparable. `bsi-claim.sh` normalise de la même façon ; la route est l'autorité,
# pour tout écrivain qui ne passerait pas par le script.
_ENERGIES = {
    'high': 'high', 'h': 'high', 'haute': 'high', 'haut': 'high',
    'medium': 'medium', 'm': 'medium', 'moyenne': 'medium', 'moyen': 'medium',
    'low': 'low', 'l': 'low', 'basse': 'low', 'bas': 'low',
}


def _energie(valeur):
    """`high` / `medium` / `low`, ou None si absente — sinon 422."""
    if valeur is None:
        return None
    n = _ENERGIES.get(str(valeur).strip().lower())
    if n is None:
        raise HTTPException(
            status_code=422,
            detail=f"energy « {valeur} » refusée — trois niveaux : high / medium / low")
    return n


@app.patch('/bsi/claims/{sess_id}')
async def bsi_claims_update(
    sess_id:       str,
    body:          dict       = Body(...),
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Met à jour un claim BSI (status, result, close).

    Enrichie le 15/09 pour : `cmd_open` est passé par le moteur le
    11/09, `cmd_close` non, et la route ne savait pas écrire ce qu'une
    fermeture porte. Mesuré avant de toucher quoi que ce soit, par
    `workspace/scratch/banc-bsi-claim/equivalence_close.py` :

        le script écrit   status, closed_at, result, duration_min,
                          energy, intention, tags, deliverables      8 champs
        la route écrivait status, closed_at                          2 champs
        perdus en basculant                                          6

    Les six manquants portent toute la métabolisation de fin de session
    (BRAIN-046). Basculer sans eux n'aurait rien levé : le claim se serait
    fermé correctement, et la métrique aurait disparu — exactement ce qui
    s'est produit le 22/08, 43 claims sur 43 sans durée.
    """
    # 🔴 Cette route était la SEULE des huit routes d'écriture à ne pas
    # appeler `_readonly_guard()` — mesuré le 15/09, 7 sur 8 l'avaient. Sans
    # conséquence sur une instance `prod`, où le garde laisse tout passer ;
    # sur un template ou une démo publiés, elle était la seule écriture
    # ouverte de tout le serveur.
    _readonly_guard()
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'kernel' not in scopes:
            raise HTTPException(status_code=403, detail='Zone kernel requise (owner only)')

    if 'energy' in body:
        body['energy'] = _energie(body['energy'])

    from core.bsi import BSI, autre_session
    porte_identite = BSI(brain_db.depot()).porte_identite
    existing = brain_db.query_one(
        "SELECT sess_id, status, opened_at"
        + (", agent_session" if porte_identite else "")
        + " FROM claims WHERE sess_id = %s", (sess_id,)
    )
    if not existing:
        raise HTTPException(status_code=404, detail=f'Claim {sess_id} introuvable')

    ferme = body.get('status') == 'closed'

    # ── Fermer le claim d'une AUTRE session — BRAIN-077, ───────────
    #
    # Le 26/09, une session a fermé le claim d'une autre en relisant un
    # fichier commun à la machine. Succès affiché, l'autre a continué sans
    # claim. La règle vient du CORE (`autre_session`) : cette route écrit
    # elle-même, et recopier la condition l'aurait mise en double.
    #
    # `par` : la session qui demande. `meme_si_autre` : la levée nommée.
    # Sans `par` (shell humain, cron), rien ne change.
    #
    # ⚠️ Un FILET contre l'erreur, PAS une barrière d'autorisation : `par` et
    # `meme_si_autre` viennent du corps de la requête, et n'importe quel
    # appelant peut s'annoncer comme n'importe quelle session. Qui a le droit
    # de fermer reste décidé plus haut — localhost, ou un jeton `kernel`.
    sienne = existing.get('agent_session')
    if ferme and autre_session(sienne, body.get('par')) \
            and not body.get('meme_si_autre'):
        raise HTTPException(
            status_code=409,
            detail=f"{sess_id} appartient à une autre session d'agent "
                   f"({sienne}) — le fermer d'ici fermerait le travail d'une "
                   f"session vivante. Levée : --pas-le-mien")

    # Fermer un claim déjà fermé écrasait son `closed_at` et son `result`, et
    # rendait 200. Le script s'en garde depuis toujours (`AND status = 'open'`
    # dans son WHERE) ; la route n'avait aucun filtre. Une fermeture n'est pas
    # idempotente : elle date un évènement.
    if ferme and existing.get('status') != 'open':
        raise HTTPException(
            status_code=409,
            detail=f"Claim {sess_id} déjà {existing.get('status')} — "
                   f"une fermeture ne se rejoue pas")

    updates = []
    values  = []
    # `result` rejoint la liste, et ne remplace pas `result_status`/`result_json` :
    # les trois colonnes coexistent dans le schéma. Mesuré le 15/09 sur les
    # 599 claims des deux tables — `result` 598 remplis, `result_status` 109
    # dont AUCUN hors de l'archive, `result_json` 0 partout. Aucun écrivain de
    # `result_status` ne subsiste dans le code ; le seul lecteur,
    # `scripts/archive/workflow-launch.sh`, est archivé depuis le 30/09.
    # Trancher laquelle survit est une décision de schéma, pas un effet de
    # bord de cette route : voir.
    for field in ('status', 'closed_at', 'health_score', 'context_at_close',
                   'result_status', 'result_json', 'mode',
                   'result', 'duration_min', 'energy', 'intention',
                   'tags', 'deliverables'):
        if field in body:
            updates.append(f"{field} = %s")
            values.append(body[field])

    if not updates:
        raise HTTPException(status_code=422, detail='Aucun champ à mettre à jour')

    # Auto-set closed_at if status → closed
    if ferme and 'closed_at' not in body:
        updates.append("closed_at = %s")
        values.append(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))

    # La durée se calcule ici quand l'appelant ne la donne pas — sinon elle
    # dépendrait de qui appelle, et la métrique de BRAIN-046 vaudrait ce que
    # vaut le client le moins soigneux.
    duree = body.get('duration_min')
    if ferme and 'duration_min' not in body:
        duree = _duree_du_claim(existing.get('opened_at'))
        if duree is not None:
            updates.append("duration_min = %s")
            values.append(duree)

    values.append(sess_id)
    # 🔴 L'UPDATE etait nu —, mesure le 24/09. Une erreur de la base
    # remontait en exception non geree, et FastAPI rendait un « 500 » sans un
    # mot. Cote appelant, `bsi-claim.sh close` refuse a juste titre de se
    # rabattre sur un code HTTP : le claim restait donc OUVERT, et rien
    # ne disait pourquoi.
    #
    # Le cas rencontre : `result` est un `varchar(64)` et recevait 300
    # caracteres. Elargir la colonne est un autre sujet ; ici on repare ce que
    # `collaboration.md` proscrit — « un echec doit se plaindre ».
    try:
        brain_db.execute(f"UPDATE claims SET {', '.join(updates)} WHERE sess_id = %s", tuple(values),
                         commit_msg=f'claim maj : {sess_id} ({", ".join(body.keys())})')
    except Exception as exc:                                       # noqa: BLE001
        # 422 et non 500 : la donnee envoyee est refusee par le schema, ce n'est
        # pas une panne du serveur. Les longueurs sont jointes au message parce
        # que « trop long » sans dire de combien fait perdre un quart d'heure.
        #
        # 🔴 Le message de la base RECOPIE la valeur refusee — mesure le 26/09 :
        # 474 caracteres dont 300 de valeur, et l'information utile repoussee
        # apres elle. `result` porte ce qu'une session a produit : le jour ou
        # une session y met quelque chose de sensible, le refus l'ecrit dans la
        # reponse HTTP ET dans le journal. On masque donc tout litteral long
        # avant de logger comme avant de repondre — une seule fois, pour les
        # deux surfaces.
        tailles = {k: len(v) for k, v in body.items() if isinstance(v, str)}
        motif = re.sub(r"'[^']{32,}'",
                       lambda m: f"'<valeur masquee : {len(m.group(0)) - 2} caracteres>'",
                       str(exc))
        log.warning('bsi_claims_update REFUSE sess_id=%s champs=%s : %s',
                    sess_id, tailles, motif)
        # Ou va la prose : `result` est une etiquette, et la mesure le dit —
        # 55 claims, 45 caracteres au plus long, 7 en mediane. `deliverables` et
        # `story_angle` sont des `text` et existent pour le recit. Tranche le
        # 26/09 : on garde la contrainte plutot que d'elargir la colonne.
        indice = (" `result` est une etiquette (varchar 64) : la prose va dans"
                  " `deliverables` ou `story_angle`, qui sont des `text`."
                  if len(str(body.get('result') or '')) > 64 else "")
        raise HTTPException(
            status_code=422,
            detail=(f"ecriture refusee par la base : {motif}. "
                    f"Longueurs envoyees : {tailles}. "
                    f"Le claim {sess_id} est reste OUVERT.{indice}"),
        ) from exc
    log.info('bsi_claims_update sess_id=%s fields=%s', sess_id, list(body.keys()))

    await _broadcast({
        'type': f'bsi:claim:{body.get("status", "update")}',
        'payload': {'sess_id': sess_id, **body},
    })

    # `duration_min` revient dans la réponse — la route la calcule, donc elle
    # doit dire ce qu'elle a écrit.
    #
    # Ce n'est pas un confort d'affichage : depuis étape 5,
    # `bsi-claim.sh close` ne lit plus rien en local. S'il veut montrer la durée
    # de la session qu'il vient de fermer, la seule source est cette réponse.
    # Une route qui décide sans rapporter oblige son appelant à re-lire — et
    # c'est comme ça qu'on se retrouve avec deux chemins qui calculent chacun
    # leur version de la même chose.
    #
    # `None` est une réponse : il veut dire « je n'ai pas pu la calculer », et
    # le `log.warning` de `_duree_du_claim` dit pourquoi.
    reponse = {'ok': True, 'sess_id': sess_id}
    if ferme:
        reponse['duration_min'] = duree
    return reponse


@app.post('/bsi/claims/touch')
async def bsi_claims_touch(
    body:          dict       = Body(default={}),
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Repousse l'expiration des claims ouverts — le signe de vie du BSI.

    étape 5. `cmd_touch` écrivait `expires_at` en direct ; c'est une
    **horloge**, et une horloge appartient à celui qui détient la base.

    Une route dédiée plutôt qu'un champ de plus sur `PATCH` : `touch` ne dit
    pas *« écris cette date »*, il dit *« je suis vivant »*. Laisser l'appelant
    calculer la date lui ferait porter une règle — `ttl_hours` du claim — qu'il
    n'a pas à connaître, et deux appelants la calculeraient tôt ou tard
    différemment.

    Le hook `post-commit` appelle à chaque commit, et la route repousse ce
    qu'on lui NOMME : un claim (`sess_id`), ou les claims d'une session d'agent
    (`agent_session`). Rien de nommé → 422.

    Jusqu'au 27/09, « rien de nommé » voulait dire « tous les claims ouverts » :
    le signe de vie d'une session servait à toutes, les mortes comprises — un
    claim abandonné depuis la veille n'expirait jamais tant qu'une autre session
    commitait. C'était juste avant qu'un claim connaisse sa session (BRAIN-077) ;
    depuis, on sait lequel est vivant.

    ⚠️ **Sans commit Dolt, délibérément**. Le working set est
    partagé et durable : la valeur est visible des autres processus tout de
    suite. Un commit par `touch` ajouterait 3,7 Ko à chaque commit git, pour un
    compteur.
    """
    _readonly_guard()
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'kernel' not in scopes:
            raise HTTPException(status_code=403, detail='Zone kernel requise (owner only)')

    sess_id = (body or {}).get('sess_id')
    agent = (body or {}).get('agent_session')
    where, params = "status = 'open'", ()
    if sess_id:
        where += " AND sess_id = %s"
        params = (sess_id,)
    elif agent:
        where += " AND agent_session = %s"
        params = (agent,)
    else:
        raise HTTPException(
            status_code=422,
            detail="touch : nommer le claim (sess_id) ou la session (agent_session) "
                   "— un signe de vie ne vaut que pour celui qui le donne")

    ouverts = brain_db.query(
        f"SELECT sess_id, ttl_hours FROM claims WHERE {where}", params)
    if not ouverts:
        return {'ok': True, 'touches': [], 'detail': 'aucun claim ouvert à prolonger'}

    brain_db.execute(
        f"UPDATE claims SET expires_at = DATE_ADD(UTC_TIMESTAMP(), "
        f"INTERVAL COALESCE(ttl_hours, 4) HOUR) WHERE {where}", params)

    log.info('bsi_claims_touch sess_id=%s agent=%s touches=%d',
             sess_id or '-', (agent or '-')[:8], len(ouverts))
    return {'ok': True,
            'touches': [{'sess_id': c['sess_id'], 'ttl_hours': c['ttl_hours'] or 4}
                        for c in ouverts]}


@app.post('/bsi/claims/close-stale')
async def bsi_claims_close_stale(
    body:          dict       = Body(default={}),
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Ferme les claims restés ouverts au-delà de leur expiration.

    étape 5. Une route dédiée, et non une boucle de `PATCH` côté
    appelant : le critère — *qu'est-ce qu'un claim oublié ?* — est une règle du
    BSI, pas une affaire de client. Deux clients qui la porteraient finiraient
    par ne pas fermer les mêmes claims.

    🔴 **L'UPDATE ferme EXACTEMENT ce que le SELECT a listé**, par `sess_id`.
    C'est la correction de : les deux requêtes portaient chacune leur
    critère temporel, le SELECT depuis l'EXPIRATION et l'UPDATE depuis
    l'OUVERTURE. Une session touchée il y a cinq minutes n'était pas listée et
    était fermée quand même. Fermer par identifiants supprime la divergence par
    construction — il n'y a plus deux critères à tenir d'accord.

    `min_hours` relève le seuil sans toucher au `ttl_hours` de chaque claim :
    l'appel manuel garde le TTL nominal, l'appel automatisé ne ferme que ce qui
    est certainement un oubli. **Une session longue n'est pas un oubli** — dix
    claims `pilote` de 9,6 h à 76,8 h ont été fermés à tort avant.
    """
    _readonly_guard()
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'kernel' not in scopes:
            raise HTTPException(status_code=403, detail='Zone kernel requise (owner only)')

    min_hours = (body or {}).get('min_hours')
    if min_hours is not None:
        try:
            min_hours = int(min_hours)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422,
                                detail=f'min_hours attend un entier, reçu : {min_hours!r}')
        seuil_sql, seuil_params = "%s", (min_hours,)
        seuil_txt = f'expiré depuis > {min_hours}h'
    else:
        seuil_sql, seuil_params = "COALESCE(ttl_hours, 4)", ()
        seuil_txt = 'expiré depuis > TTL du claim'

    # Le temps se mesure depuis l'EXPIRATION, pas depuis l'ouverture :
    # `expires_at` est repoussé par `touch` à chaque commit, ce qui en fait un
    # signe de vie. Mesurer depuis `opened_at` ne pourrait que grandir.
    stale = brain_db.query(f"""
        SELECT sess_id, TIMESTAMPDIFF(MINUTE, opened_at, UTC_TIMESTAMP()) AS age_min
        FROM claims
        WHERE status = 'open'
          AND TIMESTAMPDIFF(HOUR,
                COALESCE(expires_at,
                         DATE_ADD(opened_at, INTERVAL COALESCE(ttl_hours,4) HOUR)),
                UTC_TIMESTAMP()) > {seuil_sql}
    """, seuil_params)

    if not stale:
        return {'ok': True, 'fermes': [], 'seuil': seuil_txt}

    ids = [c['sess_id'] for c in stale]
    trous = ', '.join(['%s'] * len(ids))
    ferme = brain_db.execute(f"""
        UPDATE claims
        SET status = 'closed',
            closed_at = UTC_TIMESTAMP(),
            result = 'stale-auto-closed',
            duration_min = TIMESTAMPDIFF(MINUTE, opened_at, UTC_TIMESTAMP())
        WHERE status = 'open' AND sess_id IN ({trous})
    """, tuple(ids),
        commit_msg=f'bsi: {len(ids)} claim(s) stale ferme(s) automatiquement',
        tables=['claims'])

    # Entre le SELECT et l'UPDATE, une autre session a pu fermer un claim
    # proprement. Le `status = 'open'` du WHERE empêche de le rouvrir en
    # `stale-auto-closed` ; l'écart, lui, se dit.
    #
    # ⚠️ Inactif en dolt — `execute` y rend -1. Il ne sert qu'en sqlite : le
    # repli d'un fork, et le template. C'est écrit plutôt que laissé deviner.
    if ferme is not None and ferme >= 0 and ferme != len(ids):
        log.warning('close-stale : %d claim(s) liste(s), %d ferme(s) — '
                    'un claim a change d etat entre les deux requetes',
                    len(ids), ferme)

    log.info('bsi_claims_close_stale fermes=%d seuil=%s', len(ids), seuil_txt)
    for c in stale:
        await _broadcast({'type': 'bsi:claim:closed',
                          'payload': {'sess_id': c['sess_id'],
                                      'result': 'stale-auto-closed'}})
    return {'ok': True, 'seuil': seuil_txt,
            'fermes': [{'sess_id': c['sess_id'], 'age_min': c['age_min']}
                       for c in stale]}


@app.get('/bsi/locks')
def bsi_locks_list(
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Liste les locks actifs depuis la base."""
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'work' not in scopes:
            raise HTTPException(status_code=403, detail='Zone work requise')

    locaux = brain_db.query(f"""
        SELECT filepath, holder, claimed_at, expires_at,
               CASE WHEN {VERROU_ACTIF}
                    THEN 'active' ELSE 'expired' END AS lock_status
        FROM locks ORDER BY claimed_at DESC
    """)
    # Les verrous actifs des AUTRES machines, avec leur source. C'est
    # `verrous_du_reseau` qui tranche, et c'est lui que la prise de verrou
    # consulte.
    propre = brain_db.branche_propre()
    ailleurs = []
    for r in brain_db.verrous_du_reseau():
        if r['_branche'] != propre:
            r = dict(r, lock_status='active', branche=r['_branche'] or 'main')
            r.pop('_branche', None)
            ailleurs.append(r)
    return locaux + ailleurs


@app.post('/bsi/locks')
async def bsi_locks_acquire(
    body:          dict       = Body(...),
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Acquiert un lock fichier. Échoue si déjà tenu par un autre holder."""
    _readonly_guard()
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'kernel' not in scopes:
            raise HTTPException(status_code=403, detail='Zone kernel requise (owner only)')

    filepath = body.get('filepath')
    holder   = body.get('holder')
    ttl_min  = body.get('ttl_min', 60)

    if not filepath or not holder:
        raise HTTPException(status_code=422, detail='filepath et holder requis')

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ── Les verrous de tout le réseau, lus dans la base commune — ──
    #
    # Jusqu'au 2/10, la route consultait chaque pair en HTTP (`_load_peers`).
    # Sans jeton et à travers un pare-feu, la consultation n'a jamais abouti
    # (000 dans un sens, 401 dans l'autre) : chaque machine accordait chez elle,
    # et un pair injoignable était avalé — `file-lock.sh` affichait « peers
    # consultés » sur un verrou que personne d'autre n'avait vu (15/09). Le
    # réseau se lit maintenant là où il est écrit, `main` et chaque branche
    # satellite, comme les claims.
    try:
        tenus = brain_db.verrous_du_reseau("filepath = %s", (filepath,))
        sources = brain_db.sources_des_verrous()
    except Exception as exc:                                # noqa: BLE001
        log.error('locks du réseau illisibles: %s', exc)
        raise HTTPException(status_code=503, detail='verrous du réseau illisibles — verrou refusé')
    autre = next((r for r in tenus if r['holder'] != holder), None)
    if autre:
        ou = f" sur {autre['_branche']}" if autre.get('_branche') else ''
        raise HTTPException(
            status_code=409,
            detail=f"Lock détenu par {autre['holder']}{ou} jusqu'à {autre['expires_at']}"
        )

    # Upsert — remplace si même holder ou expiré
    brain_db.execute("DELETE FROM locks WHERE filepath = %s", (filepath,))
    brain_db.execute("""
        INSERT INTO locks (filepath, holder, claimed_at, expires_at, ttl_min)
        VALUES (%s, %s, %s, DATE_ADD(%s, INTERVAL %s MINUTE), %s)
    """, (filepath, holder, now, now, ttl_min, ttl_min),
        commit_msg=f'lock pris : {filepath} par {holder}')
    log.info('bsi_lock_acquire filepath=%s holder=%s ttl=%dm', filepath, holder, ttl_min)

    await _broadcast({
        'type': 'bsi:lock:acquire',
        'payload': {'filepath': filepath, 'holder': holder},
    })

    # `peers_injoignables` est toujours présent, même vide. Un champ qui
    # n'apparaît que dans le mauvais cas oblige chaque appelant à distinguer
    # « absent parce que tout va bien » de « absent parce que l'appelant parle
    # à une vieille version » — et c'est précisément l'ambiguïté qui a permis
    # à `file-lock.sh` d'affirmer « peers consultés » pendant des mois.
    # `peers_injoignables` reste, toujours vide : `file-lock.sh` le lit. `reseau`
    # dit ce qui a été consulté — l'affirmation vient d'ici, avec sa preuve.
    return {'ok': True, 'filepath': filepath, 'holder': holder,
            'peers_injoignables': [], 'reseau': sources}


@app.delete('/bsi/locks/{filepath:path}')
async def bsi_locks_release(
    filepath:      str,
    holder:        str        = Query(...),
    request:       Request    = None,
    authorization: str | None = Header(None),
):
    """Libère un lock fichier. Seul le holder peut libérer."""
    _readonly_guard()
    if not _is_localhost(request):
        scopes = check_auth(authorization)
        if 'kernel' not in scopes:
            raise HTTPException(status_code=403, detail='Zone kernel requise (owner only)')

    # Check lock exists before delete (dolt doesn't return rowcount)
    existing = brain_db.query_one(
        "SELECT filepath FROM locks WHERE filepath = %s AND holder = %s", (filepath, holder)
    )
    if not existing:
        raise HTTPException(status_code=404, detail=f'Lock {filepath} non trouvé pour {holder}')

    brain_db.execute(
        "DELETE FROM locks WHERE filepath = %s AND holder = %s", (filepath, holder),
        commit_msg=f'lock rendu : {filepath} par {holder}',
    )

    log.info('bsi_lock_release filepath=%s holder=%s', filepath, holder)

    await _broadcast({
        'type': 'bsi:lock:release',
        'payload': {'filepath': filepath, 'holder': holder},
    })

    return {'ok': True, 'filepath': filepath}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_results(results: list[dict], full: bool, mode: str) -> dict:
    """
    Sérialise les chunks en JSON.
    mode=develop  → filepath visible
    mode=service  → filepath masqué (prévu BE-3c — structure prête)
    """
    expose_filepath = (mode != 'service')   # garde le if pour BE-3c

    items = []
    for r in results:
        item = {
            'score':      round(r['score'], 4),
            'title':      r.get('title') or '',
            'query':      r.get('_query', ''),
        }
        if expose_filepath:
            item['filepath'] = r['filepath']
        if full:
            item['chunk_text'] = r['chunk_text']
        else:
            item['excerpt'] = r['chunk_text'].replace('\n', ' ')[:120].strip() + '…'
        items.append(item)

    return {'count': len(items), 'results': items}


_FRONTMATTER_DEGRADE: set[str] = set()


def _parse_frontmatter(path: Path) -> dict:
    """
    Parse le frontmatter YAML d'un fichier Markdown (bloc entre les premiers `---`).
    Retourne {} si absent ou en cas d'erreur.
    """
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return {}

    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not m:
        return {}

    raw = m.group(1)
    if _YAML_AVAILABLE:
        try:
            return yaml.safe_load(raw) or {}
        except Exception as exc:
            # Le repli regex fait le travail, mais en silence : 9 fichiers de
            # `projets/` prenaient ce chemin degrade sans que rien le dise, parce
            # que leur champ `status:` contient de la prose avec des « : ».
            # Une fois par chemin — se plaindre, pas inonder.
            if str(path) not in _FRONTMATTER_DEGRADE:
                _FRONTMATTER_DEGRADE.add(str(path))
                log.warning('frontmatter YAML invalide (%s) — repli sur le parseur '
                            'simple : %s', path, str(exc).splitlines()[0][:120])

    # Fallback : parser simple key: value (une profondeur)
    result: dict = {}
    for line in raw.splitlines():
        kv = re.match(r'^(\w[\w-]*):\s*(.*)$', line)
        if kv:
            k, v = kv.group(1), kv.group(2).strip()
            # liste inline [a, b, c]
            if v.startswith('[') and v.endswith(']'):
                items = [x.strip().strip('"\'') for x in v[1:-1].split(',') if x.strip()]
                result[k] = items
            else:
                result[k] = v.strip('"\'') or None
    return result


def _load_yaml_file(path: Path) -> dict:
    """Charge un fichier YAML. Retourne {} si absent ou invalide."""
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return {}

    if _YAML_AVAILABLE:
        try:
            return yaml.safe_load(text) or {}
        except Exception:
            return {}

    # Fallback : même parser simple que _parse_frontmatter
    result: dict = {}
    for line in text.splitlines():
        kv = re.match(r'^(\w[\w-]*):\s*(.*)$', line)
        if kv:
            k, v = kv.group(1), kv.group(2).strip()
            if v.startswith('[') and v.endswith(']'):
                items = [x.strip().strip('"\'') for x in v[1:-1].split(',') if x.strip()]
                result[k] = items
            else:
                result[k] = v.strip('"\'') or None
    return result


def _parse_agents_tier_map(agents_md: Path) -> dict:
    """
    Parse AGENTS.md pour extraire tier et date de création par agent.
    Retourne {agent_id: {'tier': 'hot'|'stable'|'kernel', 'created': 'YYYY-MM-DD'}}.
    """
    tier_map: dict = {}
    try:
        text = agents_md.read_text(encoding='utf-8')
    except Exception:
        return tier_map

    # Détection de section : 🔴 → hot, 🔵 → stable, ⚙️ → kernel
    current_tier = 'stable'
    for line in text.splitlines():
        if '🔴' in line:
            current_tier = 'hot'
        elif '🔵' in line:
            current_tier = 'stable'
        elif '⚙️' in line or '⚙' in line:
            current_tier = 'kernel'
        # Ligne de tableau : | `agent-name` | ... | ✅ 2026-03-12 |
        row = re.match(r'\|\s*`([^`]+)`\s*\|.*\|\s*(.*?)\s*\|?\s*$', line)
        if row:
            agent_id = row.group(1)
            status_col = row.group(2)
            date_m = re.search(r'(\d{4}-\d{2}-\d{2})', status_col)
            created = date_m.group(1) if date_m else ''
            tier_map[agent_id] = {'tier': current_tier, 'created': created}

    return tier_map


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    roles = ', '.join(sorted(set(_TOKEN_MAP.values()))) if _TOKEN_MAP else 'auth désactivée (dev)'
    log.info('Brain-as-a-Service BE-4 — port %d — rôles: %s', BRAIN_PORT, roles)
    # En-têtes de proxy crus d'un proxy LOCAL seulement (relecture du 28/09).
    uvicorn.run(app, host='0.0.0.0', port=BRAIN_PORT,
                forwarded_allow_ips='127.0.0.1', proxy_headers=True)
