#!/usr/bin/env python3
"""La réindexation passe-t-elle par la file, et la file tient-elle ? —.

Ce qui pourrirait en silence sans lui : **une réindexation qui n'a jamais
lieu.** C'est déjà arrivé — de mars à septembre, `PUT /brain/{path}` forkait
`python3 index.py`, un fichier qui n'a jamais existé. `Popen` réussit (il fork),
donc la route répondait `reindex: true` pendant que l'enfant mourait. Le cron de
6 h rattrapait l'index, ce qui a masqué la panne **six mois**.

    python3 tools/eprouver_file_reindex.py --brain ~/Dev/Brain

── Il n'écrit ni fichier ni ligne d'index ──────────────────────────────────

`embed.run` est remplacé en mémoire par un compteur : on mesure **ce que la
file demande**, pas ce que l'indexeur produit — l'équivalence de l'indexation,
elle, est acquise par construction puisque c'est le même `embed.run` qu'appelle
la passe complète.

── Ce qu'il éprouve ────────────────────────────────────────────────────────

    statique     plus aucun `Popen` vers l'indexeur dans la route
    file         un chemin déposé est réindexé
    dedoublonne  dix dépôts du même chemin valent UNE réindexation
    survie       une réindexation qui lève ne tue pas le worker
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import sys
from pathlib import Path

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}",
              file=sys.stderr)


def sans_popen_vers_indexeur(moteur: Path) -> bool:
    """La route `brain_put` lance-t-elle encore un sous-processus ?

    Lecture statique : on cherche un `subprocess.Popen` DANS la fonction. Les
    autres `subprocess` du fichier — `pm2 jlist`, `pm2 logs`, `git log` — ne
    nous regardent pas : ils appartiennent à des capacités d'instance, pas au
    CORE.
    """
    arbre = ast.parse((moteur / "server.py").read_text(encoding="utf-8"))
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "brain_put":
            for x in ast.walk(n):
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute):
                    if x.func.attr in ("Popen", "run") and \
                       getattr(x.func.value, "id", "") == "subprocess":
                        return False
            return True
    raise SystemExit("brain_put introuvable — ce contrôle ne mesure plus rien")


async def scenario(server, demandes: list[str], casse: str | None = None) -> list[str]:
    """Démarre la file, dépose `demandes`, rend les chemins réellement traités."""
    traites: list[str] = []

    class _FauxEmbed:
        @staticmethod
        def run(target_file=None, **_):
            if casse is not None and target_file == casse:
                raise RuntimeError("panne simulée de l'indexeur")
            traites.append(target_file)

    import types
    faux = types.ModuleType("embed")
    faux.run = _FauxEmbed.run
    sys.modules["embed"] = faux

    server._FILE_REINDEX = None      # une file neuve par scenario
    server._REINDEX_EN_ATTENTE.clear()
    for d in demandes:
        server._demander_reindex(d)
    await server._FILE_REINDEX.join()
    return traites


def main() -> int:
    p = argparse.ArgumentParser(description="La file de réindexation tient-elle ?")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()
    moteur = a.brain.expanduser().resolve() / "brain-engine"
    if not (moteur / "server.py").is_file():
        print("⏭️  SKIP brain-engine/server.py introuvable.", file=sys.stderr)
        return 0

    verifie("`brain_put` ne lance plus de sous-processus",
            sans_popen_vers_indexeur(moteur), True)

    sys.path.insert(0, str(moteur))
    try:
        import server
    except Exception as exc:                               # noqa: BLE001
        print(f"❌ le module ne se charge pas : {type(exc).__name__} — {exc}",
              file=sys.stderr)
        return 1

    # ── Un chemin déposé est réindexé ───────────────────────────────────────
    traites = asyncio.run(scenario(server, ["agents/coach-boot.md"]))
    verifie("un chemin déposé est réindexé", traites, ["agents/coach-boot.md"])

    # ── Dix dépôts du même chemin valent UNE réindexation ───────────────────
    #
    # Sans dédoublonnage, enregistrer dix fois le même fichier — ce qu'un
    # éditeur fait — lancerait dix passages sur Ollama pour un résultat
    # identique. Le témoin négatif est dans la paire : DEUX chemins distincts
    # doivent, eux, produire DEUX réindexations.
    traites = asyncio.run(scenario(server, ["a.md"] * 10))
    verifie("dix dépôts du même chemin → une réindexation", traites, ["a.md"])
    traites = asyncio.run(scenario(server, ["a.md", "b.md"]))
    verifie("témoin — deux chemins distincts → deux réindexations",
            sorted(traites), ["a.md", "b.md"])

    # ── 🔴 Une réindexation qui lève ne tue pas le worker ───────────────────
    #
    # Le cas qui compte. Un worker mort ne se plaint pas : il cesse simplement
    # de vider la file, et chaque écriture suivante répond `reindex: true` sans
    # que rien ne soit indexé. Exactement la panne de six mois, sous une autre
    # forme.
    traites = asyncio.run(scenario(server, ["casse.md", "apres.md"], casse="casse.md"))
    verifie("une réindexation qui lève ne tue pas le worker",
            traites, ["apres.md"])

    print()
    if _ko:
        print(f"❌ {_ko} garantie(s) tombée(s) — la réindexation peut se perdre.\n",
              file=sys.stderr)
        return 1
    print(f"✅ {_ok} garanties — la file réindexe, dédoublonne, et survit à une panne\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
