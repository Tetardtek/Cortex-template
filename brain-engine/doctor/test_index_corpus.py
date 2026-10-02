#!/usr/bin/env python3
"""Témoin de l'accord index ↔ corpus

Une entrée d'index qui survit à la sortie du corpus est un mensonge silencieux :
le fichier existe, le RAG le sert, et la passe ne le visite plus donc ne le
rafraîchira jamais. Une source figée ne se distingue en rien d'une source
fraîche. Mesuré le 03/09 : 409 chemins, 2 427 chunks, 31 % de l'index.

Ce test vérifie que le remède tient, et qu'il discrimine vraiment :

    accord            l'index ne porte rien que le corpus ait laissé tomber
    témoin négatif    un corpus vide déclare TOUT hors corpus
    liens             un chemin symbolique du corpus n'est pas déclaré dehors
    TTL non suivi     un fichier gitignoré et vieux sort ; frais, il reste
    signal            `get_age_days` retient le plus récent de git et mtime
    outils tiers      `lab/tools/` n'entre pas dans le corpus
    purge             une entrée hors corpus est retirée, le fichier reste
    plafond           au-delà de 25 %, la purge refuse

Le témoin négatif est le cœur : sans lui, une fonction qui répondrait « rien
n'est hors corpus » quoi qu'on lui donne passerait pour verte.

    python3 tools/test_index_corpus.py --brain ~/Dev/Brain

Sortie 1 si une garantie tombe. Écrit sous `workspace/_temoin-my34/`, nettoyé
en sortie quoi qu'il arrive.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import time
from pathlib import Path


def _rendre_les_signaux_interruptibles() -> None:
    """Pour que `finally` ait lieu même quand on nous tue.

    `finally` ne s'exécute pas sur SIGTERM — c'est ce que `timeout` envoie, et
    c'est ce qui est arrivé le 04/09 : trois fichiers témoins sont restés dans
    `workspace/_temoin-my34/`, un `git add -A` les a commités, et le témoin
    s'est abstenu aux passages suivants en refusant de s'installer sur un reste.
    Le refus était juste ; c'est le reste qui n'aurait pas dû exister.

    On convertit donc le signal en `KeyboardInterrupt`, que `finally` intercepte.
    Même geste que le `trap … EXIT TERM INT` de `kernel-isolation-check.sh`,
    et même famille qu'un verrou d'exclusion déjà vu : ce qui
    s'installe doit savoir se retirer, y compris quand on l'interrompt.
    """
    def _lever(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _lever)
        except (ValueError, OSError):
            pass

# L'abri porte l'identifiant de l'execution. Avec un nom FIXE, il a suffi qu'un
# `git add -A` commite un reste pour que le chemin acquiere un historique git —
# et le temoin veut precisement que git SE TAISE sur ce fichier, pour verifier
# que `get_age_days` retombe sur la mtime. Quatre garanties sont tombees d'un
# coup, et rien dans le brain n'avait change.
#
# Meme remede que pour la discipline Dolt : ce qui s'installe porte un nom qui n'appartient qu'a
# son execution.
EXECUTION = f"{os.getpid()}-{int(time.time()) % 100000}"
ABRI = f"workspace/_temoin-my34-{EXECUTION}"
# Le `chunk_id` etait fixe lui aussi, et l'abri unique ne suffisait pas : deux
# executions inseraient la meme cle, et la purge `LIKE '_temoin-my34-%'`
# emportait celle de la voisine. Mesure — l'une des deux rougissait.
CHUNK = f"_temoin-my34-{EXECUTION}"
# `purger_hors_corpus()` agit sur l'index ENTIER : deux temoins qui la lancent
# ensemble se purgent mutuellement leurs entrees, et l'un compte zero ligne
# retiree. Un identifiant unique n'y peut rien — c'est un etat global, comme le
# working set Dolt. On s'excluent donc, et on le DIT.
EXCLUSIF = "_my34-exclusif.md"
VIEUX = 100 * 86400  # au-delà du TTL de 60 jours


def main() -> int:
    _rendre_les_signaux_interruptibles()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=True)
    args = parser.parse_args()

    root = args.brain.expanduser().resolve()
    sys.path.insert(0, str(root / "brain-engine"))
    import db
    import embed

    if db.BACKEND != "dolt":
        print(f"SKIP: backend `{db.BACKEND}` — le témoin écrit dans l'index Dolt.")
        return 0

    # Geler plutôt que s'abstenir. La saleté sur `embeddings` est ATTENDUE :
    # chaque recherche incrémente `hit_count` sans commit, et c'est voulu,
    # « acceptable pour les compteurs à haute fréquence ». S'abstenir
    # rendait ce témoin muet dès qu'une recherche avait eu lieu — c'est-à-dire
    # presque toujours. Une abstention qui se déclenche tout le temps ne protège
    # pas plus qu'un contrôle qui ne peut pas rougir : on cesse de la lire.
    sales = db.dirty_tables()
    if sales:
        db.freeze(f"avant le témoin d'accord index/corpus — {', '.join(sales)}")
        print(f"  ℹ️  working set gelé avant de mesurer ({', '.join(sales)})")

    echecs: list[str] = []

    def verifie(nom: str, cond: bool, detail: str = "") -> None:
        if not cond:
            echecs.append(nom)
        print(f"  {'✅' if cond else '❌'} {nom:<40} {detail}")

    print("\nACCORD INDEX ↔ CORPUS\n")

    # Pas de `purge()` : elle gèle et commite. Retirer un verrou périmé n'est
    # pas une suppression de données, c'est du ménage d'état.
    db.execute("DELETE FROM locks WHERE filepath = %s "
               "AND expires_at < UTC_TIMESTAMP()", (EXCLUSIF,))
    try:
        db.execute(
            "INSERT INTO locks (filepath, holder, claimed_at, expires_at, ttl_min) "
            "VALUES (%s, %s, UTC_TIMESTAMP(), "
            "DATE_ADD(UTC_TIMESTAMP(), INTERVAL 10 MINUTE), 10)",
            # SANS commit_msg. Le working set Dolt est partagé entre
            # sessions : un verrou écrit et non commité est vu par un autre
            # processus — mesuré le 04/09 — et coûte zéro commit. Le commiter
            # n'ajoutait rien à l'exclusion, seulement du poids permanent dans
            # un magasin de 13 Go sans remote.
            (EXCLUSIF, f"temoin-my34-{EXECUTION}"))
    except Exception:                                  # noqa: BLE001
        print("SKIP un autre témoin du corpus purge déjà l'index ;")
        print("     à deux, la mesure ne veut plus rien dire. Relancer seul.")
        return 0

    abri = root / ABRI
    if abri.exists():
        print(f"SKIP: {ABRI} existe déjà — un témoin ne s'installe pas sur un reste.")
        return 0

    try:
        abri.mkdir(parents=True)
        frais = abri / "frais.md"
        frais.write_text("# Frais\n\nUn fichier écrit à l'instant.\n")
        vieux = abri / "vieux.md"
        vieux.write_text("# Vieux\n\nUn fichier que personne n'a touché depuis longtemps.\n")
        os.utime(vieux, (time.time() - VIEUX, time.time() - VIEUX))
        lien = abri / "lien.md"
        lien.symlink_to(frais)

        # Une seule marche du corpus pour tout le témoin : chaque appel
        # reglobe le brain entier, et `brain doctor` se vend en secondes.
        fichiers = embed.collect_files()
        corpus = {str(c.relative_to(embed.BRAIN_ROOT)) for c, _ in fichiers}

        # ── 1. accord sur le corpus réel ─────────────────────────────────────
        sortis = embed.chemins_hors_corpus(fichiers)
        verifie("index et corpus d'accord", not sortis,
                f"{len(sortis)} hors corpus" if sortis else "aucun écart")

        # ── 2. témoin négatif : un corpus vide met tout dehors ───────────────
        tout_dehors = embed.chemins_hors_corpus(files=[])
        indexes = db.query_one("SELECT COUNT(DISTINCT filepath) n FROM embeddings")["n"]
        verifie("un corpus vide met tout dehors", len(tout_dehors) == int(indexes),
                f"{len(tout_dehors)}/{indexes} chemins")

        # ── 3. un lien symbolique n'est pas replié sur sa cible ──────────────
        # C'est l'erreur commise en mesurant l'accord : `resolve()` faisait passer
        # un fichier du corpus pour un intrus.
        verifie("le lien symbolique reste dans le corpus", str(lien.relative_to(root)) in corpus,
                str(lien.relative_to(root)))

        # ── 4. le TTL couvre enfin ce qui n'est pas suivi ────────────────────
        verifie("non suivi et vieux → hors corpus",
                str(vieux.relative_to(root)) not in corpus,
                f"mtime {embed.get_mtime_age_days(vieux)} j")
        verifie("non suivi et frais → dans le corpus",
                str(frais.relative_to(root)) in corpus,
                f"mtime {embed.get_mtime_age_days(frais)} j")

        # ── 5. le signal retient le plus récent des deux ─────────────────────
        verifie("get_age_days = mtime quand git se tait",
                embed.get_git_age_days(vieux) is None
                and embed.get_age_days(vieux) == embed.get_mtime_age_days(vieux),
                f"git None, âge {embed.get_age_days(vieux)} j")
        # Éprouvé dans les deux sens : un fichier reel du depot donnerait
        # souvent git == mtime, et le test passerait aussi pour un `max`.
        vrai_git = embed.get_git_age_days
        try:
            embed.get_git_age_days = lambda _p: 90
            plus_jeune_par_git = embed.get_age_days(vieux)
            embed.get_git_age_days = lambda _p: 120
            plus_jeune_par_mtime = embed.get_age_days(vieux)
        finally:
            embed.get_git_age_days = vrai_git
        verifie("get_age_days = min(git, mtime)",
                plus_jeune_par_git == 90 and plus_jeune_par_mtime == 100,
                f"git 90/mtime 100 → {plus_jeune_par_git} · "
                f"git 120/mtime 100 → {plus_jeune_par_mtime}")

        # ── 6. les outils tiers décompressés n'entrent pas ───────────────────
        faux_outil = root / "learning" / "x" / "lab" / "tools" / "README.md"
        verifie("`lab/tools/` exclu du corpus", embed.should_exclude(faux_outil))

        # ── 7. la sortie du corpus emporte l'entrée d'index ──────────────────
        rel = str(vieux.relative_to(root))
        db.execute("INSERT INTO embeddings (chunk_id, filepath, chunk_text, scope, "
                   "created_at, updated_at) "
                   "VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP())",
                   (CHUNK, rel, "témoin", "satellite"))
        avant = embed.chemins_hors_corpus(fichiers)
        verifie("une entrée hors corpus est repérée", rel in avant)

        # Sur un index vide ou presque (un fork sans Ollama), le témoin est à lui
        # seul plus de 31 % de l'index : le plafond refusait la purge, et ce cas
        # rougissait selon ce que l'index contenait ce jour-là. Le plafond a son
        # propre cas (8). On ne le lève QUE si le témoin est la seule chose à
        # purger — jamais sur une purge réelle.
        seul_le_temoin = set(avant) == {rel}
        retires = embed.purger_hors_corpus(fichiers, force=seul_le_temoin)
        apres = embed.chemins_hors_corpus(fichiers)
        verifie("elle est retirée de l'index", retires >= 1 and rel not in apres,
                f"{retires} ligne(s)")
        verifie("le fichier, lui, reste sur le disque", vieux.exists())

        # ── 8. le plafond refuse l'absurde ───────────────────────────────────
        verifie("plafond : 31 % refusé", embed.depasse_le_plafond(2427, 7899))
        verifie("plafond : 5 % accepté", not embed.depasse_le_plafond(400, 7899))

    finally:
        db.execute("DELETE FROM embeddings WHERE chunk_id LIKE %s",
                   (CHUNK + "%",))
        if db.dirty_tables():
            db._dolt_commit("purge : témoin d'accord index/corpus",
                            tables=["embeddings"])
        shutil.rmtree(abri, ignore_errors=True)
        # `purge()` gèlerait et commiterait : deux commits permanents pour rendre
        # un verrou qui n'en a pas coûté un seul.
        db.execute("DELETE FROM locks WHERE filepath = %s AND holder = %s",
                   (EXCLUSIF, f"temoin-my34-{EXECUTION}"))

    print()
    if echecs:
        print(f"  ❌ {len(echecs)} garantie(s) tombée(s) : {', '.join(echecs)}\n")
        return 1
    print("  ✅ l'index ne peut pas garder ce que le corpus a lâché\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
