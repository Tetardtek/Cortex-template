#!/usr/bin/env python3
"""
brain-engine/rag.py — Couche RAG BE-3a
Enrichit le contexte Claude au boot avec des chunks additifs (non redondants avec helloWorld).

Usage :
  python3 brain-engine/rag.py                    → boot queries (3 ciblées, skip helloWorld)
  python3 brain-engine/rag.py "query custom"     → query ad-hoc (compact)
  python3 brain-engine/rag.py "query" --full     → chunks complets
  python3 brain-engine/rag.py --json             → JSON brut (boot)
  python3 brain-engine/rag.py "query" --json     → JSON brut (ad-hoc)
  python3 brain-engine/rag.py "query" --top 10   → top-10 résultats

Output : bloc markdown prêt à injection dans le contexte Claude.
Silencieux si aucun résultat ou Ollama indisponible (exit 0).
"""

import sys
import json
import argparse
from pathlib import Path

# Import search depuis le même répertoire
sys.path.insert(0, str(Path(__file__).parent))
from search import search as semantic_search


# ── Config ─────────────────────────────────────────────────────────────────────

# Fichiers déjà chargés par helloWorld — ignorés dans les résultats boot
# pour éviter de dupliquer le contexte déjà présent.
HELLOWORLD_SKIP = frozenset({
    'focus.md',
    'KERNEL.md',
    'BRAIN-INDEX.md',
    'agents/helloWorld.md',
    'agents/secrets-guardian.md',
    'agents/coach.md',
    'profil/specs/collaboration.md',
})

# Queries ciblées au boot — surface ce qu'helloWorld ne charge pas.
# Chaque tuple : (query, top_k)
RAG_BOOT_QUERIES = [
    ("décisions architecturales récentes",  3),   # ADRs, choix archi
    ("todos prioritaires backlog actif",    3),   # todo/*.md au-delà du README
    ("sprint en cours workspace actif",     2),   # workspace/shadow-*/
]

# Seuil minimum au boot — évite le bruit des chunks peu pertinents
BOOT_MIN_SCORE = 0.30


# ── Core ───────────────────────────────────────────────────────────────────────

def run_boot_queries(allowed_scopes: list[str] | None = None) -> list[dict]:
    """
    Exécute les 3 queries boot en séquence.
    Déduplique par filepath, filtre les fichiers helloWorld.
    Conserve la query source dans le champ '_query' pour le formatage.
    """
    seen_filepaths: set[str] = set()
    results: list[dict] = []

    for query, top_k in RAG_BOOT_QUERIES:
        hits = semantic_search(query, top_k=top_k, min_score=BOOT_MIN_SCORE,
                               allowed_scopes=allowed_scopes)
        for hit in hits:
            fp = hit['filepath']
            if fp in HELLOWORLD_SKIP:
                continue
            if fp in seen_filepaths:
                continue
            seen_filepaths.add(fp)
            results.append({**hit, '_query': query})

    return results


def run_single_query(query: str, top_k: int = 5,
                     allowed_scopes: list[str] | None = None) -> list[dict]:
    """Query ad-hoc — pas de skip helloWorld, pas de déduplication inter-queries."""
    hits = semantic_search(query, top_k=top_k, min_score=0.0,
                           allowed_scopes=allowed_scopes)
    return [{**h, '_query': query} for h in hits]


# ── Formatage ──────────────────────────────────────────────────────────────────

def format_compact(results: list[dict], label: str = 'RAG boot') -> str:
    """
    Format A (défaut) — filepath + extrait de 120 chars.
    ~100 tokens par chunk, lean pour injection boot.
    """
    if not results:
        return ''

    lines = [f'## Brain context ({label})\n']
    current_query: str | None = None

    for r in results:
        q = r.get('_query', '')
        if q and q != current_query:
            current_query = q
            lines.append(f'\n### {q}\n')

        fp      = r['filepath']
        score   = r['score']
        title   = r.get('title') or ''
        excerpt = r['chunk_text'].replace('\n', ' ')[:120].strip()
        if title:
            excerpt = f'[{title}] {excerpt}'

        lines.append(f'- `{fp}` *(score: {score:.2f})* — {excerpt}…\n')

    return ''.join(lines)


def format_full(results: list[dict], label: str = 'RAG — full') -> str:
    """
    Format B (--full) — chunks complets.
    Pour queries ad-hoc profondes où l'extrait est insuffisant.
    """
    if not results:
        return ''

    lines = [f'## Brain context ({label})\n']
    for r in results:
        fp    = r['filepath']
        score = r['score']
        title = r.get('title') or ''
        chunk = r['chunk_text']

        header = f'### `{fp}`'
        if title:
            header += f' — {title}'
        header += f' *(score: {score:.2f})*'

        lines.append(f'\n{header}\n\n{chunk}\n')

    return ''.join(lines)


def format_json(results: list[dict]) -> str:
    out = [{
        'score':      round(r['score'], 4),
        'filepath':   r['filepath'],
        'title':      r.get('title') or '',
        'chunk_text': r['chunk_text'],
        'query':      r.get('_query', ''),
    } for r in results]
    return json.dumps(out, ensure_ascii=False, indent=2)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='brain-engine RAG — BE-3a')
    parser.add_argument('query', nargs='?',
                        help='Query ad-hoc (sans arg = mode boot)')
    parser.add_argument('--full', action='store_true',
                        help='Chunks complets (défaut: compact)')
    parser.add_argument('--top',  type=int, default=5,
                        help='Top-K pour query ad-hoc (défaut: 5)')
    parser.add_argument('--json', action='store_true',
                        help='Output JSON brut')
    args = parser.parse_args()

    # Mode boot si aucune query fournie
    if not args.query:
        results = run_boot_queries()
        label   = 'RAG boot'
    else:
        results = run_single_query(args.query, top_k=args.top)
        label   = f'RAG — {args.query}'

    # Silencieux si aucun résultat — ne pas polluer le contexte
    if not results:
        sys.exit(0)

    if args.json:
        print(format_json(results))
    elif args.full:
        print(format_full(results, label=label))
    else:
        print(format_compact(results, label=label))


if __name__ == '__main__':
    main()
