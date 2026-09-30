#!/usr/bin/env python3
"""
brain-engine/search.py — Recherche sémantique BE-2d
Embed une query → cosine similarity sur brain.db → top-K chunks

Usage :
  python3 brain-engine/search.py "décisions archi mon-api"
  python3 brain-engine/search.py "cold start" --top 10
  python3 brain-engine/search.py "agents helloWorld" --mode file
  python3 brain-engine/search.py "sessions metabolism" --mode json

Modes :
  human  (défaut) → tableau lisible : score | filepath | extrait
  file            → filepaths dédupliqués, triés par score (pour Claude : charger ces fichiers)
  json            → JSON brut : [{score, filepath, title, chunk_text}]

Headless : zéro dépendance display/Wayland.
OLLAMA_URL : variable d'env (défaut localhost:11434).
"""

import os
import sys
import json
import struct
import argparse
import urllib.request
import urllib.error
from pathlib import Path

BRAIN_ROOT  = Path(__file__).parent.parent
OLLAMA_URL  = os.getenv('OLLAMA_URL') or 'http://localhost:11434'
EMBED_MODEL = os.getenv('EMBED_MODEL') or 'nomic-embed-text'

# Guardrail — cohérent avec embed.py
_BLOCKED_MODELS = ['mistral', 'qwen', 'llama', 'gemma', 'phi', 'deepseek']
if any(b in EMBED_MODEL.lower() for b in _BLOCKED_MODELS):
    sys.exit(f"❌ EMBED_MODEL='{EMBED_MODEL}' interdit — utiliser nomic-embed-text ou mxbai-embed-large")


# ── Maths ─────────────────────────────────────────────────────────────────────

def cosine_sim(a: list[float], b: list[float]) -> float:
    dot    = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def blob_to_vector(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))


# ── Ollama ─────────────────────────────────────────────────────────────────────

def embed_query(text: str) -> list[float] | None:
    url     = f"{OLLAMA_URL}/api/embeddings"
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req     = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get('embedding')
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"❌ Ollama indisponible ({OLLAMA_URL}) : {e}", file=sys.stderr)
        return None


# ── DB ─────────────────────────────────────────────────────────────────────────

import db as brain_db

def _query_embeddings(allowed_scopes: list[str] | None,
                      include_historical: bool) -> list[dict]:
    """Lecture brute des chunks indexés. Une seule requête, deux consommateurs.

    pymysql (dolt) et sqlite3 retournent tous deux des bytes pour les BLOBs.
    Shadow indexing (BRAIN-037) : scope='historical' exclu par défaut.
    """
    historical_filter = "" if include_historical else "AND scope != 'historical'"
    if allowed_scopes:
        placeholders = ','.join('%s' for _ in allowed_scopes)
        return brain_db.query(f"""
            SELECT chunk_id, filepath, title, chunk_text, `vector`
            FROM embeddings
            WHERE indexed = 1 AND `vector` IS NOT NULL
              AND scope IN ({placeholders})
              {historical_filter}
        """, tuple(allowed_scopes))
    return brain_db.query(f"""
        SELECT chunk_id, filepath, title, chunk_text, `vector`
        FROM embeddings
        WHERE indexed = 1 AND `vector` IS NOT NULL
          {historical_filter}
    """)


def load_vectors(allowed_scopes: list[str] | None = None,
                 include_historical: bool = False) -> list[dict]:
    """Charge les chunks indexés depuis la DB, filtrés par scope si fourni.
    Shadow indexing (BRAIN-037) : scope='historical' exclu par défaut.
    Compatible sqlite et dolt via brain_db.query()."""
    rows = _query_embeddings(allowed_scopes, include_historical)
    result = []
    for row in rows:
        result.append({
            'chunk_id':   row['chunk_id'],
            'filepath':   row['filepath'],
            'title':      row.get('title') or '',
            'chunk_text': row['chunk_text'],
            'vector':     blob_to_vector(row['vector']),
        })
    return result


# La matrice reste en mémoire entre deux recherches, et son empreinte dit quand
# la relire. Mesuré au banc le 04/09 : `load_matrix` coûtait **155 ms sur 177**,
# soit 87 % du temps d'une recherche — 17 Mo de vecteurs relus dans Dolt à chaque
# requête, pour un produit matriciel qui tient dans le bruit.
#
# L'empreinte porte DEUX grandeurs, et il en faut deux : `MAX(updated_at)` voit
# les écritures, `COUNT(*)` voit les suppressions. C'est exactement la leçon de
# — un DELETE n'avance aucun horodatage, et le cache viz a servi des
# points disparus pour cette raison. On ne refait pas l'erreur deux fois.
_MATRICE_CACHE: dict[tuple, tuple] = {}


def vider_cache() -> None:
    # Le moteur du CORE porte son propre cache, invalide par empreinte
    # (MAX(updated_at), COUNT(*)). Le laisser en place apres un vidage explicite
    # rendrait le geste a moitie vrai — et « a moitie vrai » est pire qu'inerte.
    global _MOTEUR_CORE
    _MOTEUR_CORE = None
    """Oublie la matrice gardée en mémoire.

    L'empreinte est un PROXY de la donnée : elle interroge la base. Si un
    appelant substitue la lecture elle-même — ce que font les tests en patchant
    `_query_embeddings` —, le proxy continue de décrire la vraie base et le cache
    sert une matrice qui n'a rien à voir avec les fixtures. Aucun cache ne peut
    deviner qu'on lui a change sa source sous les pieds ; il faut le lui dire.

    Quatre tests l'ont signalé dans la minute qui a suivi la pose du cache.
    """
    _MATRICE_CACHE.clear()


def _empreinte_index(allowed_scopes: list[str] | None,
                     include_historical: bool) -> tuple | None:
    """(dernière écriture, nombre de lignes) sur le prédicat exact de la lecture.

    Une agrégation, quelques millisecondes — contre 155 ms de blobs. Retourne
    None si la mesure échoue : l'appelant relit alors, plutôt que de servir un
    cache dont il ne peut pas prouver la fraîcheur.
    """
    historical_filter = "" if include_historical else "AND scope != 'historical'"
    try:
        if allowed_scopes:
            placeholders = ','.join('%s' for _ in allowed_scopes)
            row = brain_db.query_one(f"""
                SELECT MAX(updated_at) m, COUNT(*) n FROM embeddings
                WHERE indexed = 1 AND `vector` IS NOT NULL
                  AND scope IN ({placeholders}) {historical_filter}
            """, tuple(allowed_scopes))
        else:
            row = brain_db.query_one(f"""
                SELECT MAX(updated_at) m, COUNT(*) n FROM embeddings
                WHERE indexed = 1 AND `vector` IS NOT NULL {historical_filter}
            """)
        return (str(row['m']), int(row['n'])) if row else None
    except Exception as exc:
        log_stderr(f'empreinte de l\'index illisible ({exc}) — relecture complète')
        return None


def load_matrix(allowed_scopes: list[str] | None = None,
                include_historical: bool = False):
    """Même chargement que `load_vectors`, mais sans passer par des listes Python.

    Mesuré le 02/09 sur 7 961 chunks × 768 dims : `struct.unpack` vers des listes
    coûtait ~200 ms et la boucle de similarité ~620 ms. `np.frombuffer` lit les
    blobs concaténés sans copie et le produit matriciel remplace la boucle —
    ~20 ms pour les deux, soit ×42.

    Retourne (métadonnées, matrice float32) ou (métadonnées, None) si numpy est
    absent : l'appelant retombe alors sur le chemin Python, en le disant.
    """
    cle = (tuple(sorted(allowed_scopes)) if allowed_scopes else None, include_historical)
    empreinte = _empreinte_index(allowed_scopes, include_historical)
    if empreinte is not None:
        garde = _MATRICE_CACHE.get(cle)
        if garde and garde[0] == empreinte:
            return garde[1], garde[2]

    rows = _query_embeddings(allowed_scopes, include_historical)
    meta = [{
        'chunk_id':   row['chunk_id'],
        'filepath':   row['filepath'],
        'title':      row.get('title') or '',
        'chunk_text': row['chunk_text'],
    } for row in rows]
    if not rows:
        return meta, None
    try:
        import numpy as np
    except ImportError:
        log_stderr('numpy absent — recherche en Python pur, ~40× plus lente')
        return meta, None
    dims   = len(rows[0]['vector']) // 4
    matrix = np.frombuffer(b''.join(r['vector'] for r in rows),
                           dtype=np.float32).reshape(-1, dims)
    if empreinte is not None:
        _MATRICE_CACHE[cle] = (empreinte, meta, matrix)
    return meta, matrix


def log_stderr(message: str) -> None:
    print(f'⚠️  {message}', file=sys.stderr)


# ── Search ─────────────────────────────────────────────────────────────────────

# Sous ce nombre de mots, la requête n'encode plus grand-chose : le modèle rend
# un sens GLOBAL, et deux mots n'en portent pas. Mesuré le 04/09 sur 25 chunks
# cherchés avec leurs N premiers mots — taux de retrouvaille dans les trois
# premiers résultats :
#
#     1 mot    0 %        5 mots   44 %        20 mots   96 %
#     2 mots   4 %        8 mots   60 %        40 mots  100 %
#     3 mots  12 %       12 mots   76 %
#
# Et le score ne discrimine pas : la retrouvaille RÉUSSIE à 5 mots vaut 0,751 en
# moyenne, quand la requête « démyélinisation » rend une fiche projet sans rapport à 0,889. Le
# bruit peut scorer plus haut qu'un bon résultat, donc rien dans le chiffre ne
# prévient. C'est pour ça que l'avertissement porte sur la REQUÊTE.
# Deux seuils, tous deux lus dans le tableau ci-dessus. Sous 3 mots, la
# retrouvaille est nulle à un chiffre près. Sous 6, elle passe à peine la moitié.
# Au-delà, c'est « perfectible », et un avertissement qui se déclencherait là
# se déclencherait presque toujours — il ne protégerait plus rien, comme
# une abstention permanente, ou un rouge permanent.
MOTS_MUETTE = 3
MOTS_COURTE = 6


def requete_faible(query: str) -> str | None:
    """Pourquoi cette requête ne veut probablement rien dire — ou None.

    Ne refuse rien, ne modifie rien : elle donne à l'appelant de quoi le dire.
    """
    mots = [m for m in (query or "").split() if m]
    if len(mots) < MOTS_MUETTE:
        return (f"{len(mots)} mot(s) — mesuré, une requête si courte retrouve "
                f"sa propre source moins d'une fois sur dix. Poser une phrase.")
    if len(mots) < MOTS_COURTE:
        return (f"{len(mots)} mots — retrouvaille mesurée sous la moitié. "
                f"Une phrase entière remonte à 76 % dès douze mots.")
    return None


# ── Le calcul vient du CORE —, branché le 11/09 ─────────────────────
#
# Une seule instance, au niveau module : `core.recherche.Index` garde la matrice
# en mémoire entre deux recherches, et c'est ce qui compte. Mesuré au banc le
# 04/09 : relire les vecteurs coûtait **155 ms sur 177**, soit 87 % du temps
# d'une recherche. Reconstruire un `Recherche` à chaque appel jetterait ce cache
# à chaque requête.
#
# Le CORE **reçoit** son encodeur, il ne le devine pas : `OLLAMA_URL` et
# `EMBED_MODEL` viennent de l'environnement de CETTE instance. Ses valeurs par
# défaut sont les mêmes, mais s'en remettre à elles ferait diverger le jour où
# quelqu'un pose la variable — et la divergence serait silencieuse, puisque deux
# modèles rendent tous deux des vecteurs plausibles.
_MOTEUR_CORE = None


def _moteur_core():
    global _MOTEUR_CORE
    if _MOTEUR_CORE is None:
        from core.modele import Encodeur
        from core.recherche import Recherche
        _MOTEUR_CORE = Recherche(
            brain_db.depot(), Encodeur(url=OLLAMA_URL, modele=EMBED_MODEL))
    return _MOTEUR_CORE


class RechercheIndisponible(RuntimeError):
    """La recherche n'a pas eu lieu : modèle d'embedding injoignable, ou index vide.

    Levée plutôt qu'une liste vide : « aucun résultat » et « pas de recherche »
    se ressemblaient au point qu'un fork sans Ollama croyait son brain vide de
    souvenirs. Le message est l'alerte du CORE ; `conseil()` dit quoi faire.
    """

    def conseil(self) -> str:
        from core.recherche import INJOIGNABLE
        if str(self) == INJOIGNABLE:
            return (f"Ollama répond-il ({OLLAMA_URL}) avec le modèle « {EMBED_MODEL} » ? "
                    f"`ollama pull {EMBED_MODEL}`, puis `bash scripts/brain-engine.sh embed`.")
        return "Indexer le brain : `bash scripts/brain-engine.sh embed` (Ollama requis)."


def search(query: str, top_k: int = 5, min_score: float = 0.0,
           allowed_scopes: list[str] | None = None) -> list[dict]:
    """Retourne les top-K chunks les plus proches de la query.

    Le classement est calculé par `core.recherche` depuis le 11/09 — équivalence
    vérifiée et gardée par `myeline/tools/equivalence_recherche.py` : 12
    requêtes, mêmes rangs et mêmes scores, et un écart de similarité
    **exactement nul** sur 500 paires de vecteurs réels.

    Ce qui reste ici est ce qui appartient à l'INSTANCE : la traduction des noms
    de champs que ses appelants attendent, et le tracking des hits.

    ⚠️ **Une différence connue, latente aujourd'hui.** `load_vectors` excluait
    `scope='historical'` par défaut (shadow indexing, BRAIN-037) ; le CORE filtre
    par scope mais ne connaît pas cette exclusion. Sans effet actuellement —
    l'index ne porte aucun chunk `historical` (vérifié : satellite, public,
    instance, kernel), et les deux portes passent toujours `allowed_scopes`. À
    reprendre si le shadow indexing revient.
    """
    resultats, _alerte = _moteur_core().cherche(
        query, combien=top_k, score_min=min_score, scopes=allowed_scopes)

    if not resultats:
        # Le CORE distingue « index vide » et « modèle injoignable » — une panne,
        # à dire — d'un avis sur la requête, qui n'empêche pas un vrai « rien ».
        from core.recherche import PANNES
        if _alerte in PANNES:
            raise RechercheIndisponible(_alerte)
        return []

    # Le CORE parle sa langue, l'instance traduit vers la sienne. La
    # correspondance est bijective — rien ne se perd.
    top_results = [{
        'chunk_id':   r.chunk_id,
        'filepath':   r.chemin,
        'title':      r.titre,
        'chunk_text': r.texte,
        'score':      r.score,
    } for r in resultats]

    # 5. Tracking V1 (BRAIN-037) — dans `embedding_hits`, PAS dans `embeddings`
    #
    # Volontairement SANS commit_msg : une écriture par recherche noierait
    # l'historique Dolt sous des commits d'un compteur. Ces lignes flottent donc
    # dans le working set jusqu'au prochain commit qui porte la même table.
    # C'est le gel (`db.freeze`) qui les protège avant toute opération
    # destructive, pas un commit par requête.
    #
    # ── Pourquoi une table à part ────────────────────────────────────
    #
    # `embeddings` porte `vector varbinary(4096)` et `chunk_text longtext` dans
    # la même ligne que le compteur. Dolt stocke en arbre de Merkle : incrémenter
    # un entier y réécrit le nœud entier, vecteurs voisins compris. Mesuré le
    # 04/09 sur une branche jetable :
    #
    #     embeddings, une ligne à la fois      16 847 o
    #     embeddings, groupées (ce code)        7 743 o
    #     table légère, une à la fois           9 653 o
    #     table légère, groupées                  967 o   ← ici
    #
    # Le groupement était déjà là et vaut un facteur deux ; la table légère en
    # vaut huit de plus. Une lecture, elle, coûte zéro.
    #
    # `embeddings.hit_count` et `last_queried_at` restent en place mais **gelés,
    # et plus personne ne les lit** : les vider ou les supprimer coûterait 38,9 Mo
    # de réécriture — mesuré — dans un magasin qu'on cherche justement à alléger
    #. Le geste attend un `dolt gc`, où le coût sera absorbé. En
    # attendant, `hits_hors_table.py` vérifie que personne ne les relit.
    #
    # Effet de bord bienvenu : la réindexation ne peut plus écraser les
    # compteurs, puisqu'elle ne touche plus leur table. C'était tout.
    if top_results:
        try:
            chunk_ids = [r['chunk_id'] for r in top_results if r.get('chunk_id')]
            if chunk_ids:
                valeurs = ','.join('(%s, 1, UTC_TIMESTAMP())' for _ in chunk_ids)
                brain_db.execute(f"""
                    INSERT INTO embedding_hits (chunk_id, hit_count, last_queried_at)
                    VALUES {valeurs}
                    -- Forme PORTABLE : `db.py` traduit `ON CONFLICT` vers
                    -- `ON DUPLICATE KEY` pour Dolt, jamais l'inverse. Écrit en
                    -- MySQL natif, ce bloc levait « near DUPLICATE: syntax
                    -- error » chez tout fork en SQLite — donc le compteur que
                    -- a réparé ne s'incrémentait JAMAIS chez eux, et
                    -- l'avertissement best-effort le disait sans que personne
                    -- ne le lise.
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        hit_count       = embedding_hits.hit_count + 1,
                        last_queried_at = UTC_TIMESTAMP()
                """, tuple(chunk_ids))
        except Exception as exc:
            # Best-effort : le tracking ne casse jamais la recherche. Mais il se
            # plaint — un compteur muet qui ne s'incrémente plus ressemble en
            # tout point à un compteur à zéro, et ne se découvre que par hasard.
            log_stderr(f'tracking hit_count indisponible : {exc}')

    return top_results


# ── Output ─────────────────────────────────────────────────────────────────────

def print_human(results: list[dict], query: str):
    if not results:
        print(f"Aucun résultat pour : {query!r}")
        return
    print(f"\nRecherche : {query!r}  ({len(results)} résultat(s))\n")
    print(f"{'Score':>6}  {'Fichier':<50}  Extrait")
    print("─" * 100)
    for r in results:
        score   = f"{r['score']:.3f}"
        fp      = r['filepath']
        if len(fp) > 50:
            fp = '…' + fp[-49:]
        title   = r['title']
        excerpt = r['chunk_text'].replace('\n', ' ')[:80]
        if title:
            excerpt = f"[{title}] {excerpt}"
        print(f"{score:>6}  {fp:<50}  {excerpt}")
    print()


def print_files(results: list[dict]):
    """Filepaths dédupliqués, ordre par meilleur score."""
    seen = []
    for r in results:
        if r['filepath'] not in seen:
            seen.append(r['filepath'])
    for fp in seen:
        print(fp)


def print_json(results: list[dict]):
    out = [{
        'score':      round(r['score'], 4),
        'filepath':   r['filepath'],
        'title':      r['title'],
        'chunk_text': r['chunk_text'],
    } for r in results]
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='brain-engine search — BE-2d')
    parser.add_argument('query',                          help='Requête en langage naturel')
    parser.add_argument('--top',    type=int, default=5,  help='Nombre de résultats (défaut: 5)')
    parser.add_argument('--mode',   choices=['human', 'file', 'json'], default='human',
                        help='Format de sortie (défaut: human)')
    parser.add_argument('--min-score', type=float, default=0.0,
                        help='Score minimum cosine (0.0–1.0, défaut: 0.0)')
    args = parser.parse_args()

    results = search(args.query, top_k=args.top, min_score=args.min_score)

    if args.mode == 'file':
        print_files(results)
    elif args.mode == 'json':
        print_json(results)
    else:
        print_human(results, args.query)


if __name__ == '__main__':
    main()
