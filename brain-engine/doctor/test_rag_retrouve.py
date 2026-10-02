#!/usr/bin/env python3
"""Le RAG retrouve-t-il ce qu'il a indexé ?

`brain doctor` sait dire que l'index et le corpus s'accordent, que les vecteurs
existent, que les routes répondent. Aucun contrôle ne disait si **la recherche
rend le bon document**. Un index intact et un modèle changé donneraient la même
santé apparente, et des réponses fausses.

Le témoin ne juge pas la pertinence — personne ne sait la mesurer sans corpus
de référence. Il pose une question à laquelle la réponse est **connue d'avance** :

    on prend N chunks au hasard, on cherche avec LEUR PROPRE TEXTE,
    et on regarde s'ils se retrouvent eux-mêmes.

C'est indépendant du contenu, stable quand le corpus évolue, et ça exerce toute
la chaîne — embarquement de la requête, matrice, similarité, remontée des
métadonnées. Un désalignement entre vecteurs et `filepath` le ferait tomber
immédiatement.

    python3 tools/test_rag_retrouve.py --brain ~/Dev/Brain
    python3 tools/test_rag_retrouve.py --brain ~/Dev/Brain --echantillon 40

Mesuré le 04/09 : 20 sur 20, score moyen de la retrouvaille 0,99.

**Ce qu'il ne dit pas** : qu'une question posée avec d'autres mots trouvera le
bon document. Un mot isolé rend même du bruit à score élevé — c'est, et
ce n'est pas une panne mais une propriété du modèle. Ce témoin garde la chaîne,
pas la sémantique.

Sortie 1 si le taux passe sous le seuil.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SEUIL = 0.9   # une retrouvaille ratée sur dix reste tolérable ; deux, non
TETE = 3      # « retrouvé » = présent dans les trois premiers


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    p.add_argument("--echantillon", type=int, default=20)
    args = p.parse_args()

    moteur = args.brain.expanduser().resolve() / "brain-engine"
    if not moteur.is_dir():
        print(f"\n  ❌ {moteur} introuvable\n")
        return 1
    sys.path.insert(0, str(moteur))

    try:
        import search
        import db as brain_db
    except ImportError as exc:
        print(f"\n  SKIP moteur indisponible : {exc}\n")
        return 0

    # La recherche sémantique est facultative : sans Ollama, ce contrôle n'a rien
    # à mesurer, chez un fork comme ici. L'abstention dépend d'Ollama, jamais de
    # l'endroit : un fork qui a Ollama est jugé comme l'instance. Tranché par
    # l'owner le 2/10.
    import urllib.request
    try:
        import embed
        ollama = embed.OLLAMA_URL
    except Exception:                                        # noqa: BLE001
        ollama = "http://localhost:11434"
    try:
        urllib.request.urlopen(f"{ollama}/api/tags", timeout=3)
    except Exception as exc:                                 # noqa: BLE001
        print(f"\nSKIP Ollama injoignable ({ollama}) — la recherche sémantique "
              f"est facultative : {type(exc).__name__}\n")
        return 0

    lignes = brain_db.query(
        "SELECT filepath, chunk_text FROM embeddings "
        "WHERE indexed = 1 AND `vector` IS NOT NULL "
        "AND LENGTH(chunk_text) BETWEEN 300 AND 1500 "
        "ORDER BY RAND() LIMIT %s", (args.echantillon,))

    if not lignes:
        print("\n  ❌ aucun chunk exploitable — l'index est vide ou sans "
              "vecteurs.\n")
        return 1

    # Un brain d'avant le 28/09 rend `[]` quand la recherche n'a pas lieu ; un
    # brain d'après le DIT par une exception. Les deux sont un rouge — celui-ci
    # dit pourquoi, au lieu de compter des « manqués » qui n'ont pas été cherchés.
    panne = getattr(search, "RechercheIndisponible", ())
    retrouves, scores, manques = 0, [], []
    for r in lignes:
        try:
            resultats = search.search(r["chunk_text"][:400], top_k=TETE)
        except panne as exc:
            print(f"\n  ❌ recherche indisponible — {exc}. {exc.conseil()}\n")
            return 1
        chemins = [x.get("filepath") for x in resultats]
        if r["filepath"] in chemins:
            retrouves += 1
            rang = chemins.index(r["filepath"])
            s = resultats[rang].get("score") or resultats[rang].get("similarity") or 0
            scores.append(float(s))
        else:
            manques.append(r["filepath"])

    total = len(lignes)
    taux = retrouves / total
    moyen = sum(scores) / len(scores) if scores else 0.0

    print(f"\nRAG — {total} chunks cherchés avec leur propre texte")
    print(f"\n  retrouvés dans les {TETE} premiers   {retrouves}/{total} "
          f"({taux:.0%})")
    print(f"  score moyen de la retrouvaille    {moyen:.3f}")

    if manques:
        print(f"\n  non retrouvés :")
        for m in manques[:5]:
            print(f"       {m}")
        if len(manques) > 5:
            print(f"       … et {len(manques) - 5} autres")

    if taux < SEUIL:
        print(f"\n  ❌ sous le seuil de {SEUIL:.0%} — la recherche ne rend plus")
        print("     ce qu'elle a indexé. Un index intact et un modèle changé")
        print("     donnent la même santé apparente ; seul ce témoin les"
              " sépare.\n")
        return 1

    print("\n  ✅ la recherche retrouve ce qu'elle a indexé\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
