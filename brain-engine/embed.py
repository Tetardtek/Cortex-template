#!/usr/bin/env python3
"""
brain-engine/embed.py — Pipeline d'embedding BE-2c
Indexe le corpus brain via Ollama nomic-embed-text → table embeddings dans brain.db

Usage :
  python3 brain-engine/embed.py                  → index tout le corpus
  python3 brain-engine/embed.py --dry-run        → liste les chunks sans embed
  python3 brain-engine/embed.py --file agents/helloWorld.md  → réindexer un fichier
  python3 brain-engine/embed.py --stats          → stats de l'index actuel

Headless : zéro dépendance Wayland/display.
OLLAMA_URL : variable d'env (défaut localhost:11434) — supporte réseau local.

Zone filter — BRAIN-033a (2026-03-18) :
  kernel  (agents/, wiki/, toolkit/, contexts/, KERNEL.md) → toujours indexé
  project (projets/, handoffs/, workspace/)                → TTL 60 jours git-based
  session (claims/)                                        → JAMAIS indexé
  personal (profil/bact/, profil/identity/, profil/gaming/)      → JAMAIS indexé
  profil/decisions/                                        → scope frontmatter (kernel | project)

Stratégie chunking par type :
  agents/*.md, projets/*.md, wiki/**/*.md  → chunk par section H2
  workspace/**/*.md, profil/decisions/*.md → H2 ou fichier entier si < 512 tokens
  KERNEL.md, focus.md, contexts/           → fichier entier (documents courts)
"""

import os
import re
import sys
import json
import struct
import hashlib
import argparse
import sqlite3  # conservé pour run_template() uniquement
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from racines import DONNEES as BRAIN_ROOT   # reçue, ou le parent du programme
DB_PATH      = Path(os.getenv('BRAIN_DB_PATH') or str(BRAIN_ROOT / 'brain.db'))

import db as brain_db
OLLAMA_URL   = os.getenv('OLLAMA_URL') or 'http://localhost:11434'
EMBED_MODEL  = os.getenv('EMBED_MODEL') or 'nomic-embed-text'

# Guardrail — LLMs génériques interdits : freeze machine garanti sur corpus entier
# (validé empiriquement : mistral:7b + qwen3:8b → freeze total ~20min, 2026-03-16)
_BLOCKED_MODELS = ['mistral', 'qwen', 'llama', 'gemma', 'phi', 'deepseek']
if any(b in EMBED_MODEL.lower() for b in _BLOCKED_MODELS):
    sys.exit(f"❌ EMBED_MODEL='{EMBED_MODEL}' interdit — LLM générique → freeze machine sur corpus entier.\n"
             f"   Utiliser un modèle dédié embedding : nomic-embed-text, mxbai-embed-large, all-minilm")

CHUNK_TOKENS = 512   # tokens max par chunk (approximé : 1 token ≈ 4 chars)
CHUNK_OVERLAP = 64   # overlap entre chunks consécutifs
MIN_BODY_CHARS = 30  # seuil sous lequel un chunk H2 est considéré stub (titre + bruit) → skip
SEP_LINE_RE = re.compile(r'^[\-=*_\s]+$', re.MULTILINE)  # lignes de séparateurs markdown

# ── Zones d'accès ─────────────────────────────────────────────────────────────

# Zone 0 — jamais indexé (privé absolu) — BRAIN-033a
PRIVATE_PATHS = [
    'profil/capital.md',
    'profil/objectifs.md',
    'profil/bact/',           # personal — jamais
    # `collaboration.md` a quitté cette liste le 05/09.
    #
    # Il y était « personal — jamais », et il portait en effet quatre marqueurs
    # de cette instance — un domaine cité deux fois, et deux règles nommant son
    # propriétaire. Ils sont sortis
    # dans `profil/forge-locale.md`, qui reste hors de `specs/` et hors du
    # template.
    #
    # Ce qui reste décrit le PROGRAMME, part au template depuis toujours, et
    # n'avait plus de raison d'être invisible au brain qui l'applique.
    'profil/identity/',       # BRAIN-056 — couche cognitive interprétation personnelle, owner-only absolu
    'profil/gaming/',         # BRAIN chill/gaming — profils gaming personnels, owner-only
    'vie/',                   # BRAIN-080 — satellite de la vie de l'owner (admin, terrain, concepts perso), owner-only absolu
    'progression/',           # personal — journal + tout le répertoire
    'MYSECRETS',
]

# Zone par préfixe — premier match gagne — BRAIN-033a + KERNEL.md zones
# Zones : kernel | instance | satellite | public  (private = exclusion totale ci-dessus)
PATH_SCOPES = [
    # KERNEL — protection maximale
    ('contexts/',             'kernel'),
    ('profil/decisions/',     'kernel'),
    ('profil/',               'kernel'),
    ('KERNEL.md',             'kernel'),
    ('brain-constitution.md', 'kernel'),
    ('scripts/',              'kernel'),
    # INSTANCE — configuration machine + projets actifs
    ('focus.md',              'instance'),
    ('projets/',              'instance'),
    ('PATHS.md',              'instance'),
    ('now.md',                'instance'),
    # SATELLITE — vie libre, promotion possible
    ('toolkit/',              'satellite'),
    ('todo/',                 'satellite'),
    ('workspace/',            'satellite'),
    ('handoffs/',             'satellite'),
    ('intentions/',           'satellite'),
    # `learning/` était le SEUL chemin réellement indexé à tomber sur le défaut :
    # 1 365 chunks servis en `public` — le scope du rôle le moins privilégié —
    # alors que `NIVEAUX.yml` le déclare `donnee`, « appartient à l'utilisateur,
    # ne se distribue jamais ». Mesuré le 05/09.
    #
    # Il porte `etf-finance/`, `montages-patrimoniaux/`, `genealogie-france/`.
    # `satellite` le garde lisible par `owner` et par le rôle `mcp` — l'usage
    # quotidien ne change pas — et le retire au rôle `public`.
    ('learning/',             'satellite'),
    # PUBLIC — visible, distribué
    ('wiki/',                 'public'),
    ('agents/',               'public'),
    ('infrastructure/',       'public'),
    ('BRAIN-INDEX.md',        'public'),
]
# ── Le défaut va dans le sens du doute ─────────────────────────────
#
# Il valait `public` : tout chemin non déclaré devenait lisible par le rôle le
# moins privilégié. Sur un arbre qui porte `brain-secrets/`, `identity/` et
# `SECRETS_REGISTRY`, c'est le mauvais sens.
#
# En pratique un seul chemin y tombait vraiment — `learning/`, désormais déclaré
# — parce que `is_private()` et `CORPUS_PATHS` rattrapaient les vingt-six autres.
# Un troisième mécanisme qui rattrape le deuxième n'est pas une garantie : c'est
# une coïncidence entretenue. Le jour où un répertoire échappe aux deux, le
# défaut décide seul.
#
# `satellite` reste lisible par `owner` et par le rôle `mcp` — rien ne change
# pour l'usage quotidien. Seul le rôle `public` perd ce que personne n'a
# explicitement décidé de lui donner.
DEFAULT_SCOPE = 'satellite'


TTL_PROJECT_DAYS = 60  # BRAIN-033a — TTL projet, git-based


def is_private(filepath: str) -> bool:
    """Zone 0 — jamais indexé, jamais accessible."""
    return any(filepath == p or filepath.startswith(p) for p in PRIVATE_PATHS)


def resolve_scope(filepath: str) -> str:
    """Retourne la zone d'accès (kernel | instance | satellite | public)."""
    for prefix, scope in PATH_SCOPES:
        if filepath == prefix or filepath.startswith(prefix):
            return scope
    return DEFAULT_SCOPE


def get_frontmatter_scope(filepath: Path) -> str | None:
    """
    Lit le champ scope: du frontmatter YAML d'un fichier .md.
    Retourne 'kernel' | 'project' | 'personal' | None si absent.
    BRAIN-033a Règle 2 — override sur la règle répertoire.
    """
    try:
        text = filepath.read_text(errors='replace')
        if not text.startswith('---'):
            return None
        end = text.find('\n---', 3)
        if end == -1:
            return None
        for line in text[3:end].splitlines():
            line = line.strip()
            if line.startswith('scope:'):
                val = line[len('scope:'):].strip()
                val = val.split('#')[0].strip()  # retire commentaires inline
                return val if val else None
    except Exception:
        pass
    return None


def get_git_age_days(filepath: Path) -> int | None:
    """
    Retourne le nombre de jours depuis le dernier git commit sur ce fichier.
    None si le fichier n'est pas tracké ou si git échoue.
    BRAIN-033a — TTL git-based, aucun couplage BSI.
    """
    try:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%ct', '--', str(filepath)],
            capture_output=True, text=True, cwd=str(BRAIN_ROOT), timeout=5
        )
        ts = result.stdout.strip()
        if not ts:
            return None
        age_secs = time.time() - int(ts)
        return int(age_secs / 86400)
    except Exception:
        return None


def get_mtime_age_days(filepath: Path) -> int | None:
    """Jours depuis la derniere ecriture du fichier. None si le stat echoue."""
    try:
        return int((time.time() - filepath.stat().st_mtime) / 86400)
    except OSError:
        return None


def get_age_days(filepath: Path) -> int | None:
    """
    Age du fichier — le signal le plus RECENT de git et de la mtime.

    `git log -1` seul avait deux defauts symetriques, mesures le 03/09 :

    - il est muet sur ce qui n'est pas suivi. 245 des 522 fichiers de la zone
      TTL sont gitignores (`concepts/`, `scratch/`, …) : l'age
      valait None, le TTL ne s'appliquait pas, ils restaient indexes a jamais.
    - il ment sur ce qui est suivi. Une passe de maintenance sans rapport avec
      le contenu — reecrire un frontmatter (une normalisation de registre) —
      cree un commit, donc rajeunit 32 fichiers d'un coup. L'appartenance au
      corpus suivait l'activite de commit, pas la pertinence.

    Retenir le plus recent des deux va dans le sens sur. Etre trop inclusif ne
    coute que du temps d'indexation : un fichier dans le corpus est rafraichi,
    donc vrai. Etre trop exclusif fabrique une entree figee servie comme
    fraiche — c'est le defaut que cette regle corrige.
    """
    ages = [a for a in (get_git_age_days(filepath), get_mtime_age_days(filepath))
            if a is not None]
    return min(ages) if ages else None


def should_skip_by_zone(filepath: Path) -> bool:
    """
    Applique les règles BRAIN-033a — retourne True si le fichier doit être exclu.

    Règle 1 — répertoire (défaut)
    Règle 2 — frontmatter scope: (override sur Règle 1, pour profil/decisions/)

    Zones :
      kernel               → False (toujours indexé)
      project + TTL > 60j  → True  (périmé)
      personal             → True  (jamais)
    """
    rel = str(filepath.relative_to(BRAIN_ROOT))

    # profil/decisions/ — Règle 2 : scope par frontmatter
    if rel.startswith('profil/decisions/'):
        scope = get_frontmatter_scope(filepath)
        if scope == 'personal':
            return True
        if scope == 'project':
            age = get_age_days(filepath)
            return age is not None and age > TTL_PROJECT_DAYS
        # scope: kernel ou absent → toujours indexé
        return False

    # Zone project — TTL git-based
    if any(rel.startswith(p) for p in ('projets/', 'handoffs/', 'workspace/')):
        age = get_age_days(filepath)
        return age is not None and age > TTL_PROJECT_DAYS

    return False


# Corpus à indexer — chemins relatifs à BRAIN_ROOT — BRAIN-033a
# kernel → toujours  |  project → TTL 60j git  |  omis → JAMAIS
CORPUS_PATHS = [
    # ── kernel — toujours indexé ──────────────────────────────────────────────
    ('agents',           '*.md',    'h2'),    # agents brain
    ('wiki',             '**/*.md', 'h2'),    # documentation (submodule)
    ('toolkit',          '**/*.md', 'h2'),    # patterns réutilisables
    ('contexts',         '*.yml',   'file'),  # contextes de session
    # ── learning — 5eme couche cognitive (BRAIN-049) ─────────────────────────────
    ('learning',         '**/*.md', 'h2'),    # tracks + inbox + sous-dossiers (modele-du-monde/, …)
    # ── project — TTL 60 jours git-based ─────────────────────────────────────
    # Récursif depuis le 1/10 (BRAIN-080, étape 4) : la connaissance d'un projet
    # vit dans `projets/<slug>/`, à côté de sa fiche. À plat, elle sortait du
    # corpus. Possible seulement après l'étape 1 — la vie a quitté `projets/`.
    ('projets',          '**/*.md', 'h2'),
    ('handoffs',         '*.md',    'file'),
    ('workspace',        '**/*.md', 'h2'),
    # ── profil/decisions — scope par frontmatter (kernel | project) ──────────
    ('profil/decisions', '*.md',    'file'),
    # ── profil/specs — les dix specs du programme ────────────
    #
    # `profil/` était exclu en bloc — « trop large, inclut bact/ ». Conséquence
    # mesurée le 05/09 : ZÉRO chunk pour les dix specs, alors que
    # `context-hygiene.md` est cité par quarante agents. Le brain ne pouvait pas
    # se relire sur ses propres specs.
    #
    # La découpe de rend l'indexation possible sans tout prendre : ce qui
    # est personnel (`identity/`, `gaming/`, `bact/`, `capital`, `objectifs`,
    # `forge-locale`) reste dans PRIVATE_PATHS ou hors de `specs/`.
    ('profil/specs',     '*.md',    'h2'),
    # ── fichiers racine kernel ────────────────────────────────────────────────
    ('.',                'KERNEL.md',      'file'),
    ('.',                'focus.md',       'file'),
    ('.',                'BRAIN-INDEX.md', 'file'),
    ('.',                'NIVEAUX.yml',    'file'),   # la source des niveaux
    # Deux INVARIANTS qui n'étaient pas indexés — mesuré le 05/09.
    # Le niveau le plus protégé du brain, absent du corpus que le brain relit.
    ('.',                'PATHS.md',              'file'),
    ('.',                'brain-constitution.md', 'file'),
    ('.',                'README.md',             'file'),
    # SUPPRIMÉ : ('ADR', ...) — chemin obsolète (ADRs dans profil/decisions/)
    # SUPPRIMÉ : ('profil', ...) — trop large, inclut bact/ — géré par scope
    # SUPPRIMÉ : ('claims', ...) — JAMAIS indexé per BRAIN-033a (session structurée)
]

# Fichiers à exclure
EXCLUDE_PATTERNS = [
    'brain-template/',
    'brain-engine/',
    '.git/',
    'node_modules/',
    '.venv/',
    'venv-',            # venvs de prototypage (venv-kokoro, venv-piper…)
    'site-packages/',
    '__pycache__/',
    # Outils tiers decompresses. `learning/` est zone kernel :
    # toujours indexee, jamais perimee. Un Ghidra et un JDK deposes dans
    # `learning/retro-ingenierie/lab/tools/` y pesaient 987 chunks sur
    # 7 899, dont 283 pour le seul ChangeHistory.md et 210 de notices de
    # licence. Le corpus etait defini par des chemins, pas par une
    # provenance — personne n'avait decide de les indexer.
    '/lab/tools/',
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def dans_un_brain_imbrique(filepath: Path) -> bool:
    """Vrai si le fichier vit dans une COPIE de brain posée dans celui-ci.

    `workspace/**/*.md` est du corpus, `workspace/scratch/` compris : les notes
    de travail s'y cherchent. Mais un worktree du brain ou du gabarit, un banc
    d'essai de fork, se posent aussi là — une copie entière, fraîche, que le
    TTL laisse passer. Mesuré le 28/09 : 14 751 chunks sur 30 453, presque la
    moitié de l'index, étaient trois worktrees.

    Deux critères :
    - un dossier, sous la racine, qui porte son propre `KERNEL.md` ;
    - un dossier à partir du DEUXIÈME niveau qui porte son propre `.git`
      (fichier : un worktree ; dossier : un clone). Le 30/09, un worktree de
      `profil` posé dans `workspace/scratch/` n'avait pas de `KERNEL.md` : 187
      fichiers indexés, dont `identity/` et `capital.md` — sous un chemin que
      `PRIVATE_PATHS` ne reconnaît pas. Au premier niveau vivent les satellites
      (des clones) et le sous-module `wiki/` (un `.git` fichier) : du corpus.

    Le `.git` n'est pas mis en cache : le moteur tourne longtemps, et un
    worktree ouvert après un premier passage doit être vu au suivant.
    """
    p = filepath if filepath.is_absolute() else BRAIN_ROOT / filepath
    try:
        parts = p.relative_to(BRAIN_ROOT).parts
    except ValueError:
        return False
    if any(_porte_un_kernel(BRAIN_ROOT.joinpath(*parts[:i])) for i in range(1, len(parts))):
        return True
    return any((BRAIN_ROOT.joinpath(*parts[:i]) / '.git').exists() for i in range(2, len(parts)))


_KERNELS: dict[Path, bool] = {}


def _porte_un_kernel(dossier: Path) -> bool:
    if dossier not in _KERNELS:
        _KERNELS[dossier] = (dossier / 'KERNEL.md').is_file()
    return _KERNELS[dossier]


def should_exclude(filepath: Path) -> bool:
    s = str(filepath)
    if any(p in s for p in EXCLUDE_PATTERNS):
        return True
    if dans_un_brain_imbrique(filepath):
        return True
    # Zone 0 — privé absolu, jamais indexé
    if filepath.is_absolute():
        try:
            rel = str(filepath.relative_to(BRAIN_ROOT))
        except ValueError:
            rel = s  # path hors BRAIN_ROOT — is_private unlikely mais safe
    else:
        rel = s
    return is_private(rel)


def _body_length(sec: str) -> int:
    """Longueur utile du body d'une section (sans titre H2 ni séparateurs markdown)."""
    lines = sec.split('\n', 1)
    body = lines[1] if len(lines) > 1 else ''
    body_clean = SEP_LINE_RE.sub('', body).strip()
    return len(body_clean)


def _titre_de_section(sec: str) -> str:
    """Titre d'une section markdown, ou '' si elle n'en porte pas.

    La première section d'un fichier n'est pas un `## ` : c'est le préambule, qui
    commence par le frontmatter YAML. L'ancienne extraction prenait sa première
    ligne telle quelle et rendait donc **`---`** — mesuré le 03/09 : 558 chunks
    de l'index portaient ce titre. Un délimiteur n'est pas un titre.

    On saute donc le frontmatter et on prend le premier titre markdown. Si la
    section ouvre sur du texte, elle n'a pas de titre — et on ne va pas en
    chercher un plus bas, ce serait celui d'une sous-partie.
    """
    lignes = sec.split('\n')
    if lignes and lignes[0].strip() == '---':
        try:
            lignes = lignes[lignes.index('---', 1) + 1:]
        except ValueError:      # frontmatter jamais refermé
            return ''
    for ligne in lignes:
        nu = ligne.strip()
        if not nu:
            continue
        return nu.strip('#').strip() if nu.startswith('#') else ''
    return ''


# ── Le découpage vient du CORE —, branché le 11/09 ──────────────────
#
# `core.indexation` porte les deux stratégies, et l'équivalence a été mesurée
# avant de brancher — au seul moment où elle était mesurable :
#
#     par sections   391 fichiers · 5 090 chunks · 0 ecart
#                    texte, identifiant ET empreinte
#     par taille     12 fichiers · 0 ecart
#
# Les identifiants et les empreintes comptent autant que le texte : des
# morceaux identiques sous d'autres identifiants feraient réindexer tout le
# corpus, et une empreinte qui change de formule ferait croire à chaque passe
# que tout a bougé.
#
# Ce qui RESTE ici : la politique de corpus (quels fichiers, quel scope, quel
# âge, quel plafond) et l'écriture. Douze fonctions qui répondent à « quoi
# indexer », et qui dépendent de CETTE installation — le CORE n'a pas à les
# porter, il a à les recevoir.


# Les seuils sont ceux de CETTE instance, passés explicitement — le CORE ne
# s'en remet pas à ses défauts. Ils coïncident aujourd'hui (512 / 64 / 30),
# et c'est précisément pourquoi il faut les donner : le jour où l'un des deux
# bouge, la divergence serait silencieuse.
def _seuils():
    from core.indexation import Decoupage
    return Decoupage(tokens=CHUNK_TOKENS,
                     chevauchement=CHUNK_OVERLAP,
                     corps_minimum=MIN_BODY_CHARS)


def _en_dicts(morceaux) -> list[dict]:
    """Les `Chunk` du CORE dans la forme que le reste de ce fichier attend."""
    return [{'text': m.texte, 'title': m.titre, 'filepath': m.chemin}
            for m in morceaux]


def chunk_by_h2(text: str, filepath: str) -> list[dict]:
    """Découpe un markdown par section H2. Délégué à `core.indexation`."""
    from core.indexation import par_sections
    return _en_dicts(par_sections(text, filepath, _seuils()))


def chunk_by_size(text: str, filepath: str, title: str = '') -> list[dict]:
    """Découpe en morceaux de taille bornée. Délégué à `core.indexation`."""
    from core.indexation import par_taille
    return _en_dicts(par_taille(text, filepath, title, _seuils()))


def chunk_file(filepath: Path, strategy: str) -> list[dict]:
    """Lit un fichier et retourne ses chunks selon la stratégie."""
    try:
        text = filepath.read_text(errors='replace').strip()
    except Exception as e:
        print(f"  ⚠️  {filepath.name} : erreur lecture — {e}")
        return []

    if not text:
        return []

    rel = str(filepath.relative_to(BRAIN_ROOT))

    if strategy == 'h2':
        return chunk_by_h2(text, rel)
    else:
        # Fichier entier — si trop long, chunk par taille
        # Le nom du fichier sert de titre — y compris quand il est découpé.
        # Sans cet argument, un fichier long perdait le sien : 239 chunks.
        if len(text) > CHUNK_TOKENS * 4:
            return chunk_by_size(text, rel, filepath.stem)
        return [{'text': text, 'title': filepath.stem, 'filepath': rel}]


def chunk_id(filepath: str, text: str) -> str:
    """ID déterministe : hash(filepath + text[:64])."""
    h = hashlib.sha1(f"{filepath}::{text[:64]}".encode()).hexdigest()[:12]
    return f"emb-{h}"


def content_hash(text: str) -> str:
    """Empreinte du contenu ENTIER d'un chunk.

    `chunk_id` ne peut pas servir à ça : il ne hache que les **64 premiers
    caractères**. Deux textes qui divergent au-delà partagent donc le même
    identifiant — se fier à lui pour sauter une réindexation garderait un vecteur
    périmé sans que rien ne le signale.
    """
    return hashlib.sha256(text.encode()).hexdigest()


# ── Ollama API ────────────────────────────────────────────────────────────────

def get_embedding(text: str) -> list[float] | None:
    """Appelle Ollama embeddings API — retourne None si indisponible."""
    url = f"{OLLAMA_URL}/api/embeddings"
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get('embedding')
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ⚠️  Ollama indisponible ({OLLAMA_URL}) : {e}")
        return None


def vector_to_blob(vec: list[float]) -> bytes:
    """Sérialise un vecteur float32 en BLOB SQLite."""
    return struct.pack(f'{len(vec)}f', *vec)


def blob_to_vector(blob: bytes) -> list[float]:
    """Désérialise un BLOB SQLite en vecteur float32."""
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))


# ── DB ────────────────────────────────────────────────────────────────────────

def connect():
    """Initialise la DB pour l'indexation.
    Dolt : retourne None (tout passe par brain_db via dolt sql-server).
    SQLite : retourne None aussi (tout passe par brain_db). Tables créées au boot.
    Note : run_template() gère son propre SQLite dédié séparément."""
    # Dolt : schema géré par schema.sql, rien à init
    # SQLite : schema créé par migrate.py au setup initial
    return None


def upsert_chunk(conn, chunk: dict,
                 vector: list[float] | None, dry_run: bool = False) -> bool:
    """Upsert un chunk dans la DB. conn ignoré en mode Dolt (brain_db.execute).
    conn reste utilisé par run_template() qui écrit dans un SQLite dédié."""
    # `model` figure dans la clause DO UPDATE : il en etait absent, comme
    # `title` avant lui, donc la colonne ne se corrigeait jamais. Avec le
    # saut de reindexation, l'oubli devenait vicieux — un changement de modele
    # aurait fige l'ancien nom, la condition de saut n'aurait plus jamais
    # correspondu, et le brain aurait re-embarque a chaque passe sans se reparer.
    cid     = chunk_id(chunk['filepath'], chunk['text'])
    blob    = vector_to_blob(vector) if vector else None
    indexed = 1 if vector else 0
    scope   = chunk.get('scope', resolve_scope(chunk['filepath']))
    empreinte = content_hash(chunk['text'])

    if dry_run:
        return True

    if conn is not None:
        # Raw SQLite connection (run_template uniquement)
        conn.execute("""
            INSERT INTO embeddings(chunk_id, filepath, title, chunk_text, vector, model, indexed, scope, content_hash, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?, datetime('now'), datetime('now'))
            ON CONFLICT(chunk_id) DO UPDATE SET
                title        = excluded.title,
                content_hash = excluded.content_hash,
                chunk_text = excluded.chunk_text,
                model      = COALESCE(excluded.model, embeddings.model),
                vector     = COALESCE(excluded.vector, embeddings.vector),
                indexed    = COALESCE(excluded.indexed, embeddings.indexed),
                scope      = excluded.scope,
                updated_at = excluded.updated_at
        """, (cid, chunk['filepath'], chunk.get('title',''), chunk['text'],
              blob, EMBED_MODEL if vector else None, indexed, scope, empreinte))
    else:
        # brain_db.execute — Dolt ou SQLite via couche d'abstraction
        brain_db.execute("""
            -- `created_at` est écrit EXPLICITEMENT. Sans lui, le `DEFAULT
            -- CURRENT_TIMESTAMP` du schéma s'applique — et `CURRENT_TIMESTAMP`
            -- est l'horloge du moteur, donc l'heure locale. Le même INSERT
            -- posait alors deux conventions dans une seule ligne : mesuré le
            -- 03/09, 328 chunks avec `created_at` 18:47 et `updated_at` 16:47.
            -- La bascule en UTC avait corrigé le code et les données ; le schéma, non.
            INSERT INTO embeddings(chunk_id, filepath, title, chunk_text, `vector`, model, `indexed`, scope, content_hash, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, UTC_TIMESTAMP(), UTC_TIMESTAMP())
            ON CONFLICT(chunk_id) DO UPDATE SET
                title        = excluded.title,
                content_hash = excluded.content_hash,
                chunk_text = excluded.chunk_text,
                model      = COALESCE(excluded.model, embeddings.model),
                `vector`   = COALESCE(excluded.`vector`, embeddings.`vector`),
                `indexed`  = COALESCE(excluded.`indexed`, embeddings.`indexed`),
                scope      = excluded.scope,
                updated_at = excluded.updated_at
        """, (cid, chunk['filepath'], chunk.get('title',''), chunk['text'],
              blob, EMBED_MODEL if vector else None, indexed, scope, empreinte))
    return True


# ── Pipeline principal ────────────────────────────────────────────────────────

def collect_files(target_file: str | None = None) -> list[tuple[Path, str]]:
    """Retourne la liste (path, strategy) des fichiers à indexer."""
    files = []
    seen = set()

    if target_file:
        p = (BRAIN_ROOT / target_file).resolve()
        if not str(p).startswith(str(BRAIN_ROOT.resolve())):
            print(f"  🚨 --file hors BRAIN_ROOT refusé : {p}")
            return files
        if p.exists():
            # 🔴 Les filtres du corpus s'appliquent AUSSI a un fichier unique.
            #
            # Jusqu'au 11/09, ce chemin rendait immediatement sans appeler
            # `should_exclude` ni `should_skip_by_zone` — que la boucle du
            # corpus complet, elle, applique. Un `PUT /brain/<fichier>` sur un
            # fichier exclu le faisait donc entrer dans l'index, et la purge
            # hors-corpus l'en retirait au passage suivant du cron.
            #
            # Un va-et-vient silencieux, avec une fenetre de 6 h. Mesure le
            # 11/09 : 573 fichiers hors bruit sont exclus du corpus, dont 385
            # dans `workspace/` et `handoffs/` — des zones ECRIVABLES par la
            # route. L'index n'en portait aucun (0 intrus sur 691 fichiers) :
            # le defaut existait dans le code sans s'etre jamais materialise,
            # parce que le cron refermait derriere.
            #
            # Deux portes vers le meme index qui n'ont pas la meme politique,
            # c'est exactement le motif que ce chantier traque.
            if should_exclude(p) or should_skip_by_zone(p):
                print(f"  ⏭️  --file hors corpus, non indexé : "
                      f"{p.relative_to(BRAIN_ROOT)}")
                return files
            # Déterminer stratégie par répertoire
            for base, pattern, strategy in CORPUS_PATHS:
                if str(p).startswith(str(BRAIN_ROOT / base)):
                    files.append((p, strategy))
                    break
            else:
                files.append((p, 'h2'))
        return files

    for base, pattern, strategy in CORPUS_PATHS:
        base_path = BRAIN_ROOT / base
        if not base_path.exists():
            continue
        for p in sorted(base_path.glob(pattern)):
            if p in seen or not p.is_file():
                continue
            if should_exclude(p):
                continue
            if should_skip_by_zone(p):
                continue
            seen.add(p)
            files.append((p, strategy))

    return files


# Plafond de casse — un script doit refuser l'absurde AVANT d'agir. Meme seuil
# que `tools/index_purge.py`, qui traite la classe symetrique (fichier disparu).
SEUIL_PURGE_PROPORTION = 0.25


def depasse_le_plafond(vises: int, total: int) -> bool:
    """Vrai si la purge visee depasse le plafond de casse. Pur — donc temoignable
    sans mettre l'index en jeu."""
    return total > 0 and vises / total > SEUIL_PURGE_PROPORTION


def chemins_hors_corpus(files: list[tuple[Path, str]] | None = None) -> dict[str, int]:
    """
    Chemins que l'index porte alors que le corpus courant ne les contient plus.

    Le fichier existe — sinon il serait orphelin, c'est l'autre classe.
    Il est simplement sorti : perime par le TTL, ou exclu par un motif.

    On compare des chemins relatifs bruts, **sans `resolve()`** : le corpus
    contient des liens symboliques (le JDK de `learning/` en a), et resoudre
    replierait le lien sur sa cible, donc declarerait hors corpus un fichier qui
    y est. C'est exactement l'erreur commise en mesurant ce defaut.
    """
    def ecart(liste) -> dict[str, int]:
        corpus = {str(chemin.relative_to(BRAIN_ROOT)) for chemin, _ in liste}
        return {r['filepath']: r['n'] for r in brain_db.query(
            "SELECT filepath, COUNT(*) n FROM embeddings GROUP BY filepath")
            if r['filepath'] not in corpus}

    if files is not None:
        return ecart(files)

    # Deux marches indépendantes, et on ne garde que l'intersection.
    #
    # Le contrôle compare un parcours du disque à une lecture de la base. Un
    # fichier créé ou retiré ENTRE les deux — une autre session qui écrit dans
    # `workspace/`, ce qui arrive tous les jours — apparaît comme une dérive qui
    # n'existe pas. Vu le 03/09 : un rouge sur un fichier de travail, introuvable
    # trente secondes plus tard.
    #
    # Un contrôle qui rougit à tort s'apprend à s'ignorer. C'est le défaut
    # symétrique de celui qui ne peut pas rougir, et il coûte aussi cher.
    premier = ecart(collect_files())
    if not premier:
        return premier
    second = ecart(collect_files())
    return {p: n for p, n in premier.items() if p in second}


def purger_hors_corpus(files: list[tuple[Path, str]] | None = None,
                       *, force: bool = False) -> int:
    """
    Retire de l'index ce que le corpus a laisse tomber.

    Sans ca, une exclusion fabrique un mensonge : l'entree reste, le RAG la sert,
    et rien ne la rafraichira jamais puisque la passe ne la visite plus. Une
    source figee ne se distingue en rien d'une source fraiche. Mesure le 03/09 :
    50 chemins / 590 chunks dans cet etat, dont 17 gelés a jamais.

    L'index est un cache derive du corpus. Un cache qui garde ce que sa source a
    lache diverge — c'est le meme remede que pour les registres d'agents et de projets.

    Retourne le nombre de lignes supprimees. Refuse au-dela du plafond.
    """
    sortis = chemins_hors_corpus(files)
    if not sortis:
        return 0

    vises = sum(sortis.values())
    ligne = brain_db.query_one("SELECT COUNT(*) n FROM embeddings")
    total = int(ligne['n']) if ligne else 0
    proportion = vises / total if total else 0

    if depasse_le_plafond(vises, total) and not force:
        print(f"  ❌ purge hors corpus REFUSEE — {proportion:.1%} de l'index "
              f"({vises}/{total} chunks, {len(sortis)} chemins)")
        print(f"     Au-dela de {SEUIL_PURGE_PROPORTION:.0%}, c'est un evenement et pas une")
        print( "     routine : `tools/index_purge.py --apply --force` avec une intention ecrite.")
        return 0

    marques = ','.join('%s' for _ in sortis)
    supprimes = brain_db.purge(
        f"DELETE FROM embeddings WHERE filepath IN ({marques})",
        tuple(sortis),
        reason=f"{len(sortis)} chemins sortis du corpus, {vises} chunks",
    )
    print(f"  🧹 hors corpus purge — {len(sortis)} chemins, {supprimes} lignes")
    return supprimes


def run_template(output_path: str):
    """Génère un brain-template.db contenant uniquement les embeddings kernel+public."""
    TEMPLATE_SCOPES = ('kernel', 'public')
    out = Path(output_path)
    if out.exists():
        out.unlink()

    conn = sqlite3.connect(str(out))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            chunk_id    TEXT PRIMARY KEY,
            filepath    TEXT NOT NULL,
            title       TEXT,
            chunk_text  TEXT NOT NULL,
            vector      BLOB,
            model       TEXT,
            indexed     INTEGER DEFAULT 0,
            scope       TEXT NOT NULL DEFAULT 'work',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emb_filepath ON embeddings(filepath)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emb_indexed ON embeddings(indexed)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emb_scope ON embeddings(scope)")
    conn.commit()

    files = collect_files()
    print(f"Template : {len(files)} fichier(s) source — modèle {EMBED_MODEL} @ {OLLAMA_URL}")
    print(f"Scopes inclus : {', '.join(TEMPLATE_SCOPES)}")

    test_vec = get_embedding("test connexion")
    ollama_ok = test_vec is not None
    if not ollama_ok:
        print(f"  ⚠️  Ollama indisponible — impossible de générer le template")
        conn.close()
        out.unlink(missing_ok=True)
        return

    total_chunks = 0
    total_indexed = 0
    skipped_scope = 0

    for filepath, strategy in files:
        chunks = chunk_file(filepath, strategy)
        if not chunks:
            continue

        file_chunks = 0
        for chunk in chunks:
            scope = resolve_scope(chunk['filepath'])
            if scope not in TEMPLATE_SCOPES:
                skipped_scope += 1
                continue
            chunk['scope'] = scope
            vec = get_embedding(chunk['text'])
            if vec:
                total_indexed += 1
            upsert_chunk(conn, chunk, vec)
            total_chunks += 1
            file_chunks += 1

        if file_chunks > 0:
            rel = str(filepath.relative_to(BRAIN_ROOT))
            print(f"  ✅ {rel} — {file_chunks} chunk(s)")

    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    print(f"\nTemplate généré : {out}")
    print(f"  Chunks inclus  : {total_chunks}")
    print(f"  Vecteurs       : {total_indexed}")
    print(f"  Chunks ignorés : {skipped_scope} (scope hors {', '.join(TEMPLATE_SCOPES)})")


def run(dry_run: bool = False, target_file: str | None = None,
        stats_only: bool = False):

    conn = connect()

    if stats_only:
        total   = brain_db.count('embeddings')
        indexed = brain_db.count('embeddings', 'indexed=1')
        pending = total - indexed
        row     = brain_db.query_one("SELECT COUNT(DISTINCT filepath) as n FROM embeddings")
        files_n = int(row['n']) if row else 0
        print(f"Index embeddings :")
        print(f"  chunks total  : {total}")
        print(f"  indexés       : {indexed}  ({100*indexed//total if total else 0}%)")
        print(f"  sans vecteur  : {pending}")
        print(f"  fichiers      : {files_n}")
        print(f"  modèle        : {EMBED_MODEL} @ {OLLAMA_URL}")
        if conn:
            conn.close()
        return

    files = collect_files(target_file)
    print(f"Corpus : {len(files)} fichier(s) — modèle {EMBED_MODEL} @ {OLLAMA_URL}")

    # Tester Ollama avant de boucler
    test_vec = get_embedding("test connexion") if not dry_run else None
    ollama_ok = test_vec is not None
    if not ollama_ok and not dry_run:
        print(f"  ⚠️  Ollama indisponible — chunks enregistrés sans vecteur (indexed=0)")

    total_chunks = 0
    total_indexed = 0
    total_inchanges = 0

    for filepath, strategy in files:
        chunks = chunk_file(filepath, strategy)
        if not chunks:
            continue

        rel = str(filepath.relative_to(BRAIN_ROOT))

        # Ce que la base sait deja de ce fichier — UNE requete par fichier, pas
        # une par chunk. Sert a sauter les chunks dont rien n'a bouge.
        # Le chemin sqlite (`conn`) n'est utilise que par run_template : il garde
        # son comportement d'origine, on ne l'optimise pas au passage.
        connus = {}
        if not dry_run and conn is None:
            connus = {r['chunk_id']: r for r in brain_db.query(
                "SELECT chunk_id, content_hash, model, scope, title, "
                "CASE WHEN `vector` IS NULL THEN 0 ELSE 1 END AS a_vecteur "
                "FROM embeddings WHERE filepath = %s", (rel,))}

        # On insère d'abord, on purge ensuite — et seulement ce qui a disparu.
        #
        # L'ordre inverse (DELETE de tout le fichier, puis re-INSERT) effaçait la
        # ligne avant que le `ON CONFLICT(chunk_id) DO UPDATE` puisse s'appliquer :
        # les colonnes qu'il préserve volontairement, `hit_count` et
        # `last_queried_at` (BRAIN-037), repartaient donc de zéro à chaque
        # réindexation. Mesuré le 02/09 : 8 hits au total sur six mois d'usage.
        file_chunks = 0
        seen_ids = []
        for chunk in chunks:
            chunk['scope'] = resolve_scope(chunk['filepath'])
            cid = chunk_id(chunk['filepath'], chunk['text'])

            # Rien n'a bouge ? Ni embedding, ni ecriture. Ne pas ecrire est le
            # point important : l'upsert touchait `updated_at` meme a contenu
            # identique, donc `MAX(updated_at)` avancait a chaque passe du cron
            # et invalidait le cache de /visualize pour rien.
            #
            # La comparaison porte sur tout ce qui rendrait la ligne fausse : le
            # texte, le modele, la presence du vecteur, le scope et le titre. Les
            # deux derniers changent sans que le texte bouge — c'etait tout le defaut du titre.
            deja = connus.get(cid)
            if (deja
                    and deja['content_hash'] == content_hash(chunk['text'])
                    and deja['model'] == EMBED_MODEL
                    and deja['a_vecteur']
                    and (deja['scope'] or '') == (chunk['scope'] or '')
                    and (deja['title'] or '') == (chunk.get('title') or '')):
                seen_ids.append(cid)
                total_chunks += 1
                total_inchanges += 1
                file_chunks += 1
                continue

            vec = None
            if ollama_ok and not dry_run:
                vec = get_embedding(chunk['text'])
                if vec:
                    total_indexed += 1

            upsert_chunk(conn, chunk, vec, dry_run=dry_run)
            seen_ids.append(cid)
            total_chunks += 1
            file_chunks += 1

        # Purge des chunks orphelins : ceux du fichier qui ne sont plus produits
        # par le découpage courant (refactor, suppression de section).
        if not dry_run and seen_ids:
            if conn is not None:
                marks = ','.join('?' for _ in seen_ids)
                conn.execute(
                    f"DELETE FROM embeddings WHERE filepath = ? AND chunk_id NOT IN ({marks})",
                    (rel, *seen_ids),
                )
            else:
                marks = ','.join('%s' for _ in seen_ids)
                brain_db.execute(
                    f"DELETE FROM embeddings WHERE filepath = %s AND chunk_id NOT IN ({marks})",
                    (rel, *seen_ids),
                )

        status = "✅" if ollama_ok else "⬜"
        print(f"  {status} {rel} — {file_chunks} chunk(s)")

    # Une sortie du corpus emporte l'entree d'index. Seulement sur une
    # passe complete : avec `--file`, `collect_files()` ne renvoie qu'un fichier
    # et tout le reste paraitrait hors corpus.
    if not dry_run and conn is None and target_file is None:
        purger_hors_corpus(files)

    if not dry_run:
        if conn:
            # SQLite : commit batch
            conn.commit()
        elif brain_db.BACKEND == 'dolt' and total_chunks > 0:
            # Dolt : stage + commit après le batch complet
            from db import _dolt_commit
            # Confine a `embeddings` : sans cette liste, DOLT_ADD('.') emportait
            # aussi les claims et les locks qui trainaient.
            _dolt_commit(f"embed: {total_indexed} vecteurs, {total_chunks} chunks",
                         tables=['embeddings'])
            print(f"  📦 dolt commit — {total_indexed} vecteurs")

    print(f"\n{'[dry] ' if dry_run else ''}Chunks traités : {total_chunks}")
    if total_inchanges:
        print(f"Inchangés — ni embedding ni écriture : {total_inchanges}")
    if not dry_run:
        print(f"Vecteurs générés : {total_indexed}")
        if not ollama_ok:
            print(f"⚠️  Relancer avec Ollama actif pour compléter l'index")

    if conn:
        conn.close()

    # Sans Ollama, les chunks sont gardés SANS vecteur : la recherche ne les
    # trouvera pas. Le dire par le code de sortie, pas seulement en passant —
    # `brain-engine.sh embed` concluait « ✅ embedding terminé ».
    if not dry_run and not ollama_ok:
        return 2
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='brain-engine embed — pipeline embeddings BE-2c')
    parser.add_argument('--dry-run',  action='store_true', help='Liste les chunks sans embed')
    parser.add_argument('--file',     metavar='PATH',      help='Réindexer un fichier spécifique')
    parser.add_argument('--stats',    action='store_true', help='Stats de l\'index actuel')
    parser.add_argument('--template', metavar='OUTPUT',    help='Générer brain-template.db (kernel+public only)')
    args = parser.parse_args()

    if args.template:
        run_template(args.template)
    else:
        sys.exit(run(dry_run=args.dry_run, target_file=args.file, stats_only=args.stats) or 0)


if __name__ == '__main__':
    main()
