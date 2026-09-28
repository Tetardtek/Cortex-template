#!/usr/bin/env python3
"""
brain-engine/distill.py — BE-5 Session memory distillation
Distille une session BSI (.jsonl Claude) en chunks indexés dans brain.db.

Usage :
  python3 brain-engine/distill.py <session.jsonl>          → distille la session
  python3 brain-engine/distill.py <session.jsonl> --dry-run → aperçu sans écriture
  python3 brain-engine/distill.py --last                   → distille la dernière session Claude

Point de substitution LLM : fonction summarize() — Ollama local.
Pour un modèle distant : remplacer summarize() par un appel API Claude/OpenAI.

Scope : work — les distillats sont accessibles via brain_search (MCP + owner).
"""

import os
import sys
import json
import re
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
import db as brain_db
from embed import upsert_chunk, get_embedding, chunk_id, OLLAMA_URL

# ── Config ─────────────────────────────────────────────────────────────────────

BRAIN_ROOT    = Path(__file__).parent.parent
DISTILL_MODEL = os.getenv('DISTILL_MODEL', 'mistral:7b')  # LLM local pour résumé
SCOPE         = 'work'

# Sessions Claude — chemin par défaut
CLAUDE_SESSIONS_DIR = Path.home() / '.claude' / 'projects'

# Taille max du contexte envoyé au LLM (chars) — réduit pour garder le format few-shot (BE-5d)
MAX_CONTEXT_CHARS = 12_000

# Max messages récents envoyés au LLM — évite les narratives anglaises sur grandes sessions (BE-5d)
MAX_MESSAGES = 50

# Seuil minimum — sessions trop courtes ne contiennent que le brief, pas de vraies décisions (BE-5d)
MIN_MESSAGES = 10

# Levier 2 — max chunks par aspect (Stratégie A, split post-LLM)
CHUNK_LIMITS = {'decisions': 10, 'code': 5, 'todos': 5}


# ── Extraction session ─────────────────────────────────────────────────────────

def extract_messages(jsonl_path: Path) -> list[dict]:
    """Extrait les messages human/assistant du .jsonl Claude."""
    messages = []
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = entry.get('message', {})
                role = msg.get('role')
                if role not in ('user', 'assistant'):
                    continue
                content = msg.get('content', '')
                if isinstance(content, list):
                    # Extraire le texte des blocs content
                    parts = [b.get('text', '') for b in content
                             if isinstance(b, dict) and b.get('type') == 'text']
                    content = '\n'.join(parts)
                if content and content.strip():
                    messages.append({'role': role, 'content': content.strip()})
    except FileNotFoundError:
        sys.exit(f'❌ Fichier introuvable : {jsonl_path}')
    return messages


def build_context(messages: list[dict], max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Construit un contexte tronqué pour le LLM.
    Priorise les N derniers messages (MAX_MESSAGES) pour garder le LLM dans le format few-shot.
    """
    # Bug 2 fix — prioriser les messages récents sur grandes sessions
    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]
    lines = []
    total = 0
    # On prend les messages les plus récents en priorité
    for msg in reversed(messages):
        prefix = 'USER' if msg['role'] == 'user' else 'ASSISTANT'
        line = f'[{prefix}] {msg["content"][:500]}'
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    lines.reverse()
    return '\n\n'.join(lines)


# ── LLM — point de substitution ───────────────────────────────────────────────

def summarize(context: str, aspect: str) -> str | None:
    """
    Résume le contexte selon l'aspect demandé.
    POINT DE SUBSTITUTION : remplacer par API Claude/OpenAI pour un modèle distant.

    aspect : 'decisions' | 'code' | 'todos'
    """
    prompts = {
        'decisions': (
            'Tu es un extracteur de mémoire technique. '
            'Extrait les décisions architecturales et techniques prises dans cette session.\n\n'
            'FORMAT OBLIGATOIRE : une décision par ligne, commençant par "- ".\n'
            'Si aucune décision : répondre uniquement "none".\n\n'
            'EXEMPLES :\n'
            'Session : "On a choisi mistral:7b parce que mistral-small était trop lent"\n'
            '→\n'
            '- Modèle LLM distillation : mistral:7b retenu (mistral-small écarté — latence)\n\n'
            'Session : "On garde 3 chunks par session, max 10 decisions, 5 code, 5 todos"\n'
            '→\n'
            '- Chunking BE-5 : 3 aspects (decisions/code/todos), caps 10/5/5\n\n'
            'Session : "Finalement on utilise SQLite plutôt que Postgres pour brain.db"\n'
            '→\n'
            '- Stockage brain.db : SQLite retenu (Postgres écarté — overhead opérationnel)\n\n'
            'Réponds dans la même langue que la session. Max 15 mots par bullet.\n\n'
            'Session :\n'
        ),
        'code': (
            'Tu es un extracteur de mémoire technique. '
            'Extrait les fichiers créés ou modifiés, les fonctions clés implémentées, et les bugs corrigés.\n\n'
            'FORMAT OBLIGATOIRE : une entrée par ligne, commençant par "- ".\n'
            'Si rien de notable : répondre uniquement "none".\n\n'
            'EXEMPLES :\n'
            'Session : "On a créé distill.py avec les fonctions extract_messages, build_context et summarize"\n'
            '→\n'
            '- brain-engine/distill.py créé — pipeline distillation : extract_messages(), build_context(), summarize()\n\n'
            'Session : "J\'ai corrigé le timeout dans embed.py, maintenant c\'est 90s au lieu de 60s"\n'
            '→\n'
            '- embed.py:get_embedding() — fix timeout 60s → 90s\n\n'
            'Session : "On a ajouté CHUNK_LIMITS et parse_bullets dans distill.py"\n'
            '→\n'
            '- distill.py — ajout CHUNK_LIMITS (10/5/5) + parse_bullets() stratégie A\n\n'
            'Réponds dans la même langue que la session. Sois concis.\n\n'
            'Session :\n'
        ),
        'todos': (
            'Tu es un extracteur de mémoire technique. '
            'Extrait les tâches ouvertes, blockers et prochaines étapes mentionnés dans cette session.\n\n'
            'FORMAT OBLIGATOIRE : une tâche par ligne, commençant par "- ".\n'
            'Si aucune tâche : répondre uniquement "none".\n\n'
            'EXEMPLES :\n'
            'Session : "Il faudra tester deepseek-coder pour l\'aspect code plus tard"\n'
            '→\n'
            '- Tester deepseek-coder:6.7b pour aspect "code" (levier 3 BE-5)\n\n'
            'Session : "Le cron VPS n\'est pas viable tant qu\'Ollama ne tourne pas sur le VPS"\n'
            '→\n'
            '- Installer Ollama sur VPS pour activer cron distillation automatique\n\n'
            'Session : "On fera l\'externalisation des prompts en BE-5c si nécessaire"\n'
            '→\n'
            '- BE-5c (optionnel) : externaliser prompts distill dans brain-engine/prompts/*.txt\n\n'
            'Réponds dans la même langue que la session. Sois concis.\n\n'
            'Session :\n'
        ),
    }
    prompt = prompts[aspect] + context

    url     = f'{OLLAMA_URL}/api/generate'
    payload = json.dumps({
        'model':  DISTILL_MODEL,
        'prompt': prompt,
        'stream': False,
        'options': {'temperature': 0.1, 'num_predict': 400},
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get('response', '').strip()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f'⚠️  Ollama indisponible ({OLLAMA_URL}) : {e}', file=sys.stderr)
        return None


# ── Parsing bullets (Stratégie A — post-split) ────────────────────────────────

def parse_bullets(text: str) -> list[str]:
    """
    Extrait les bullets d'une réponse LLM.
    Reconnaît : '- ', '• ', '* ', '– ' en début de ligne.
    Gère les continuations (ligne indentée sans préfixe = suite du bullet précédent).
    """
    bullets: list[str] = []
    current: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Préfixes reconnus : tiret court, puce, astérisque, tiret long
        is_bullet = (
            stripped[:2] in ('- ', '• ', '* ')
            or (stripped[0] == '–' and len(stripped) > 1 and stripped[1] == ' ')
        )
        if is_bullet:
            if current:
                bullets.append(' '.join(current))
            # Extraire le texte après le préfixe (1 ou 2 chars)
            prefix_len = 2 if stripped[:2] in ('- ', '• ', '* ') else 2
            current = [stripped[prefix_len:].strip()]
        elif current:
            # Continuation d'un bullet multi-ligne
            current.append(stripped)

    if current:
        bullets.append(' '.join(current))

    return [b for b in bullets if b]


# ── Summarisation 2 passes (BE-5e) ────────────────────────────────────────────

def summarize_2pass(messages: list[dict], aspect: str) -> str | None:
    """
    Summarisation en 2 passes pour grandes sessions (BE-5e).
    Pass 1 : résumé de chaque bloc de MAX_MESSAGES messages.
    Pass 2 : résumé final sur la concaténation des résumés partiels.
    """
    blocks = [messages[i:i + MAX_MESSAGES] for i in range(0, len(messages), MAX_MESSAGES)]
    partial_summaries = []
    for idx, block in enumerate(blocks):
        context = build_context(block)
        partial = summarize(context, aspect)
        if partial and partial.strip().lower() not in ('none', 'aucune', 'aucun', 'ninguno', 'ninguna', ''):
            partial_summaries.append(f'# Bloc {idx + 1}/{len(blocks)}\n{partial}')

    if not partial_summaries:
        return None

    combined = '\n\n'.join(partial_summaries)
    # Pass 2 : résumé final
    return summarize(combined[:MAX_CONTEXT_CHARS], aspect)


# ── Distillation ──────────────────────────────────────────────────────────────

def distill_session(jsonl_path: Path, dry_run: bool = False) -> int:
    """
    Distille une session en chunks granulaires (1 bullet = 1 chunk).
    Caps : decisions ≤ 10, code ≤ 5, todos ≤ 5.
    Retourne le nombre de chunks indexés.
    """
    print(f'📖 Lecture : {jsonl_path.name}')
    messages = extract_messages(jsonl_path)
    if not messages:
        print('⚠️  Aucun message extractible — session vide ou format inconnu.')
        return 0

    print(f'   {len(messages)} messages extraits')

    # Bug 1 fix — filtre micro-sessions (brief bootstrap seul, pas de vraies décisions)
    if len(messages) < MIN_MESSAGES:
        print(f'⚠️  Session trop courte ({len(messages)} messages < {MIN_MESSAGES}) — skip.')
        return 0

    is_large = len(messages) > MAX_MESSAGES
    context  = build_context(messages) if not is_large else None
    if is_large:
        print(f'   ⚡ Grande session ({len(messages)} msg) — mode 2-pass activé')
    sess_id  = jsonl_path.stem  # ex: c22807f5-04df-...
    date_str = datetime.now().strftime('%Y-%m-%d')

    total = 0

    # Bug 3 fix — purger les anciens chunks sans suffixe numérique (format pré-BE-5b)
    if not dry_run:
        purged = brain_db.purge(
            'DELETE FROM embeddings WHERE filepath LIKE %s AND filepath NOT LIKE %s',
            (f'sessions/{sess_id}/%', f'sessions/{sess_id}/%/%'),
            reason=f'chunks pre-BE-5b de {sess_id}',
        )
        if purged and purged > 0:
            print(f'   🧹 {purged} anciens chunk(s) purgés (format pré-BE-5b)')

    for aspect in ('decisions', 'code', 'todos'):
        limit = CHUNK_LIMITS[aspect]
        if is_large:
            print(f'   🧠 Distillation [{aspect}] (2-pass)...', end=' ', flush=True)
            summary = summarize_2pass(messages, aspect)
        else:
            print(f'   🧠 Distillation [{aspect}]...', end=' ', flush=True)
            summary = summarize(context, aspect)

        if not summary or summary.strip().lower() in ('aucune', 'aucun', 'none', 'ninguno', 'ninguna', ''):
            print('vide — ignoré')
            continue

        bullets = parse_bullets(summary)
        if not bullets:
            # Fallback : LLM n'a pas suivi le format — 1 chunk brut plutôt que perdre l'info
            bullets = [summary.strip()]

        # Filtrer les bullets "none" parasites (LLM met parfois "none:" au lieu du sentinel)
        _none_words = {'none', 'aucune', 'aucun', 'ninguno', 'ninguna'}
        bullets = [b for b in bullets
                   if b.strip().lower().split()[0].rstrip(':') not in _none_words]

        bullets = bullets[:limit]
        print(f'{len(bullets)} bullet(s)')

        for i, bullet in enumerate(bullets):
            filepath = f'sessions/{sess_id}/{aspect}/{i:02d}'
            title    = f'Session {date_str} — {aspect} #{i+1:02d}'
            chunk    = {
                'filepath': filepath,
                'title':    title,
                'text':     f'# {title}\n\nSource : {jsonl_path.name}\n\n- {bullet}',
                'scope':    SCOPE,
            }

            if dry_run:
                print(f'      [{aspect}/{i:02d}] {bullet[:100]}')
                total += 1
                continue

            vector = get_embedding(chunk['text'])
            if vector:
                upsert_chunk(None, chunk, vector)
                total += 1
            else:
                print(f'⚠️  embed échoué [{aspect}/{i:02d}] — stocké sans vecteur')
                upsert_chunk(None, chunk, None)

    # Dolt commit en fin de distillation
    if not dry_run and total > 0 and brain_db.BACKEND == 'dolt':
        from db import _dolt_commit
        _dolt_commit(f"distill: {total} chunks — {sess_id[:12]}")

    return total


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_last_session() -> Path | None:
    """Trouve le .jsonl de la dernière session Claude dans ~/.claude/projects."""
    jsonl_files = list(CLAUDE_SESSIONS_DIR.glob('**/*.jsonl'))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda p: p.stat().st_mtime)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='brain-engine distill — BE-5 session memory distillation'
    )
    parser.add_argument('session', nargs='?', type=Path,
                        help='Chemin vers le .jsonl de session Claude')
    parser.add_argument('--last', action='store_true',
                        help='Distille la dernière session Claude automatiquement')
    parser.add_argument('--dry-run', action='store_true',
                        help='Aperçu sans écriture dans brain.db')
    args = parser.parse_args()

    if args.last:
        jsonl = find_last_session()
        if not jsonl:
            sys.exit('❌ Aucune session trouvée dans ~/.claude/projects/')
        print(f'📌 Dernière session : {jsonl}')
    elif args.session:
        jsonl = args.session
    else:
        parser.print_help()
        sys.exit(1)

    mode = ' (dry-run)' if args.dry_run else ''
    print(f'\n🔬 Distillation BE-5{mode}\n')

    n = distill_session(jsonl, dry_run=args.dry_run)

    if n == 0:
        print('\n⚠️  Aucun chunk produit — session vide ou Ollama indisponible.')
        sys.exit(2)

    print(f'\n✅ {n} chunk(s) distillé(s) → brain.db (scope: {SCOPE})')
    if not args.dry_run:
        print('   → brain_search "session précédente" pour retrouver ce contexte')


if __name__ == '__main__':
    main()
