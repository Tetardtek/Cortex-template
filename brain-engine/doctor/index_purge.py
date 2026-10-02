#!/usr/bin/env python3
"""Purge des entrées orphelines de l'index

Moitié symétrique de : `embed.py` purge les chunks orphelins *à
l'intérieur* d'un fichier réindexé, mais un fichier **entièrement supprimé**
garde ses lignes pour toujours. Une passe complète ne les touche pas.

Conséquence mesurée le 02/09 : le RAG renvoie des documents morts. La requête
« Myeline programme immuable overlay » remontait un ADR à un chemin abandonné
quelques heures plus tôt, au même score que le vrai fichier — une citation qui
ne s'ouvre pas, un fantôme qui concurrence l'original au classement.

    python3 tools/index_purge.py --brain ~/Dev/Brain            # inventaire
    python3 tools/index_purge.py --brain ~/Dev/Brain --apply    # geler, purger, dater

Depuis, il traite **deux classes** :

    fichier absent      → l'entrée est orpheline
    fichier hors corpus → il existe, mais le corpus ne le contient plus :
                          périmé par le TTL, ou exclu par un motif

La seconde est la plus insidieuse. Rien ne casse : l'entrée reste, le RAG la
sert, et la passe ne la visite plus donc ne la rafraîchira jamais. Une source
figée ne se distingue en rien d'une source fraîche. L'index est un cache dérivé
du corpus ; un cache qui garde ce que sa source a lâché diverge.

`embed.py` purge cette classe à chaque passe complète. Cet outil reste le
rattrapage — et le témoin qu'on peut interroger sans réindexer.

**Garde-fous.** Les satellites (`learning/`, `profil/`, `workspace/`) sont
gitignorés et montés hors du dépôt : sur une machine où l'un n'est pas monté,
tous ses fichiers paraissent supprimés. Une purge naïve viderait l'index de tout
un pan du brain, et l'index ne se reconstruit qu'en repayant l'embedding.

    répertoire entier absent  → refus, on nomme le répertoire
    plus de 25 % de l'index   → refus, il faut `--force` et une intention

Un script doit plafonner sa liste de travail et refuser l'absurde AVANT d'agir.

Sortie 1 si un garde-fou se déclenche, 0 sinon.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

SEUIL_PROPORTION = 0.25


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="geler, purger, dater")
    parser.add_argument("--check", action="store_true",
                        help="sortie 1 si l'index et le corpus divergent — pour brain doctor")
    parser.add_argument("--force", action="store_true",
                        help="passer outre le plafond de proportion — jamais le refus "
                             "de répertoire entier")
    args = parser.parse_args()

    root = args.brain.expanduser().resolve()
    sys.path.insert(0, str(root / "brain-engine"))
    import db
    # Le corpus se demande au moteur, jamais reimplemente ici : deux definitions
    # du meme corpus, c'est exactement la maladie qu'on soigne.
    import embed

    lignes = db.query("SELECT filepath, COUNT(*) n FROM embeddings GROUP BY filepath")
    total_chunks = sum(r["n"] for r in lignes)
    chemins = {r["filepath"]: r["n"] for r in lignes}

    absents = {p: n for p, n in chemins.items() if not (root / p).exists()}
    presents = set(chemins) - set(absents)
    # Hors corpus : le fichier existe, le corpus ne le contient plus.
    sortis = {p: n for p, n in embed.chemins_hors_corpus().items() if p not in absents}

    print(f"\nINDEX — {len(chemins)} chemins, {total_chunks} chunks\n")
    print(f"  fichier présent      {len(presents):>5} chemins")
    print(f"  fichier absent       {len(absents):>5} chemins, "
          f"{sum(absents.values())} chunks")
    print(f"  hors corpus          {len(sortis):>5} chemins, "
          f"{sum(sortis.values())} chunks")

    if not absents and not sortis:
        print("\n  ✅ index et corpus d'accord — rien à purger\n")
        return 0

    # `--check` : un inventaire non vide est une dérive, pas une information.
    #
    # Sans ce mode, l'outil sortait 0 des qu'il n'atteignait pas un garde-fou —
    # et `brain doctor`, qui l'appelle sans `--apply`, restait donc vert avec 409
    # chemins hors corpus dans l'index. Un controle qui ne peut pas rougir ne
    # controle rien : c'est la deuxieme fois que le medecin masque son patient.
    if args.check:
        print(f"\n  ❌ {len(absents)} orphelines, {len(sortis)} hors corpus — "
              f"{sum(absents.values()) + sum(sortis.values())} chunks à purger\n")
        return 1

    if sortis:
        print("\n  hors corpus, par répertoire de tête :")
        for prefixe, n in Counter(p.split("/")[0] for p in sortis).most_common(6):
            print(f"    {prefixe:<14} {n:>4} chemins")

    # Un fichier a la racine n'est pas un repertoire : le grouper comme tel
    # ferait refuser toute purge des qu'un `focus.md` disparait, alors que c'est
    # un orphelin ordinaire. Le garde-fou ne vise que les arborescences.
    def racine(chemin: str) -> str | None:
        return chemin.split("/")[0] if "/" in chemin else None

    par_prefixe = Counter(r for p in absents if (r := racine(p)))
    presents_par_prefixe = Counter(r for p in presents if (r := racine(p)))
    fichiers_racine = [p for p in absents if racine(p) is None]

    if par_prefixe:
        print("\n  absents, par répertoire de tête :")
    for prefixe, n in par_prefixe.most_common():
        restants = presents_par_prefixe.get(prefixe, 0)
        print(f"    {prefixe:<14} {n:>4} absents · {restants:>4} encore présents")
    if fichiers_racine:
        print(f"    {'(racine)':<14} {len(fichiers_racine):>4} absents · "
              f"{', '.join(sorted(fichiers_racine))}")

    # ── Garde-fou 1 : un répertoire entier absent sent le satellite démonté ────
    vides = [p for p in par_prefixe if presents_par_prefixe.get(p, 0) == 0]
    if vides:
        print(f"\n  ❌ REFUS — répertoire(s) entièrement absent(s) : {', '.join(sorted(vides))}")
        print("     Les satellites sont montés hors du dépôt. Un répertoire dont plus")
        print("     AUCUN fichier n'existe ressemble à une suppression et à un montage")
        print("     manquant de la même façon — et l'index ne se reconstruit qu'en")
        print("     repayant l'embedding. Vérifier le montage avant d'insister.\n")
        return 1

    # ── Garde-fou 2 : un plafond sur la casse ─────────────────────────────────
    chunks_absents = sum(absents.values())
    chunks_sortis = sum(sortis.values())
    vises = chunks_absents + chunks_sortis
    proportion = vises / total_chunks if total_chunks else 0
    print(f"\n  proportion de l'index visée : {proportion:.1%} "
          f"({vises}/{total_chunks} chunks)")
    if proportion > SEUIL_PROPORTION and not args.force:
        print(f"\n  ❌ REFUS — au-delà de {SEUIL_PROPORTION:.0%} de l'index.")
        print("     Une purge de cette taille est un évènement, pas une routine :")
        print("     la justifier, puis `--force`.\n")
        return 1

    if not args.apply:
        print("\n  INVENTAIRE — rien n'a été supprimé. Les 10 plus gros :\n")
        tout = {**absents, **sortis}
        for p, n in sorted(tout.items(), key=lambda kv: -kv[1])[:10]:
            marque = "absent" if p in absents else "sorti "
            print(f"    {n:>4} chunks  {marque}  {p}")
        print(f"\n  → `--apply` pour geler, purger, dater ({len(tout)} chemins)\n")
        return 0

    # ── Geler, purger, dater ──────────────────────────────────────────────────
    # `db.purge()` pose le gel lui-même : sans lui, le commit de purge emporte ce
    # qui traînait dans le working set, et l'annuler annulerait des choses sans
    # rapport. Le remède serait pire que le mal.
    supprimes = 0
    for lot, motif in ((absents, f"{len(absents)} chemins orphelins, "
                                 f"{chunks_absents} chunks"),
                       (sortis,  f"{len(sortis)} chemins sortis du corpus, "
                                 f"{chunks_sortis} chunks")):
        if not lot:
            continue
        marques = ",".join("%s" for _ in lot)
        supprimes += db.purge(
            f"DELETE FROM embeddings WHERE filepath IN ({marques})",
            tuple(lot),
            reason=motif,
        )

    # Le temoin se reprend a la source, il ne fait pas confiance au compte.
    restants_absents = [l["filepath"] for l in db.query(
        "SELECT DISTINCT filepath FROM embeddings")
        if not (root / l["filepath"]).exists()]
    restants_sortis = embed.chemins_hors_corpus()
    print(f"\n  purgé      {supprimes} lignes")
    print(f"  restant    {len(restants_absents)} orphelins, "
          f"{len(restants_sortis)} hors corpus")
    net = not restants_absents and not restants_sortis
    print(f"\n  {'✅ index et corpus d_accord' if net else '❌ des écarts subsistent'}\n"
          .replace("d_accord", "d'accord"))
    return 0 if net else 1


if __name__ == "__main__":
    raise SystemExit(main())
