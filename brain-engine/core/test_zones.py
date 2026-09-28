#!/usr/bin/env python3
"""Ce que la garde de zone garantit.

    python3 core/test_zones.py                        # sur un registre fabriqué
    python3 core/test_zones.py --brain ~/Dev/Brain    # + le registre réel

Le registre est **reçu**, donc tout se teste sans lire un fichier. La lecture
réelle vérifie une chose de plus : que la règle écrite dans `NIVEAUX.yml` le
07/09 donne bien les zones que `KERNEL.md` nomme.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.zones import (                                    # noqa: E402
    INSTANCE, KERNEL, EcritureRefusee, Gardien, Registre,
)

_ok = _ko = 0

# Levé quand un service DEMANDÉ (`--dolt`, `--brain`) n'a pas répondu : la
# suite sort alors en 3 — « rien mesuré », distinct de 0 et de 1. Le lanceur
# (`core/tests.py`) la compte à part au lieu de l'additionner en silence.
_abstenu = False


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def refuse(nom: str, fn, exception) -> None:
    global _ok, _ko
    try:
        fn()
    except exception:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom} — rien n'a été refusé")


REGISTRE = Registre(
    niveaux={"agents/": "programme", "contexts/": "programme",
             "KERNEL.md": "invariant", "scripts/": "moteur",
             "projets/": "donnee", "profil/": "donnee"},
    exceptions={"profil/": KERNEL},
    interdits={"work": {KERNEL}, "explore": {KERNEL, INSTANCE}, "pilote": set()},
)


def derivation() -> None:
    print("\nLA ZONE SE DÉRIVE DU NIVEAU\n")
    r = REGISTRE
    verifie("un `programme` est kernel", r.zone("agents/vps.md"), KERNEL)
    verifie("un `invariant` est kernel", r.zone("KERNEL.md"), KERNEL)
    verifie("un `moteur` ne l'est pas", r.zone("scripts/x.sh"), INSTANCE)
    verifie("une `donnee` ne l'est pas", r.zone("projets/brain.md"), INSTANCE)
    verifie("un chemin inconnu retombe sur instance",
            r.zone("inconnu/x.md"), INSTANCE)

    # ⚠️ L'exception qui a motivé toute la décision.
    verifie("`profil/` est kernel PAR EXCEPTION, malgré `donnee`",
            r.zone("profil/identity/career.md"), KERNEL)
    verifie("le répertoire lui-même aussi", r.zone("profil/"), KERNEL)

    # Le préfixe le plus long gagne — l'ordre du dictionnaire ne décide pas.
    precis = Registre(niveaux={"a/": "donnee", "a/b/": "programme"})
    verifie("le préfixe le plus long l'emporte", precis.zone("a/b/c.md"), KERNEL)
    verifie("et le plus court garde le reste", precis.zone("a/z.md"), INSTANCE)


def garde() -> None:
    print("\nCE QUE LE GARDIEN REFUSE\n")
    g = Gardien(REGISTRE)

    verifie("`work` n'écrit pas en kernel",
            g.autorise("work", "agents/vps.md"), False)
    verifie("`work` écrit en instance",
            g.autorise("work", "projets/brain.md"), True)
    verifie("`work` n'écrit pas dans profil/ — l'exception s'applique",
            g.autorise("work", "profil/identity/career.md"), False)
    verifie("`explore` n'écrit nulle part",
            g.autorise("explore", "projets/brain.md"), False)
    verifie("`pilote` écrit partout",
            g.autorise("pilote", "KERNEL.md"), True)

    refuse("exige() lève au lieu de rendre un booléen qu'on oublie",
           lambda: g.exige("work", "KERNEL.md"), EcritureRefusee)

    verifie("plusieurs chemins sont jugés d'un coup",
            len(g.verifie("work", ["agents/a.md", "projets/b.md", "KERNEL.md"])), 2)

    # Ne pas savoir n'est pas savoir qu'il n'y a rien.
    verifie("un type absent du registre ne fait RIEN refuser",
            g.verifie("learning", ["KERNEL.md"]), [])
    verifie("et l'appelant peut le savoir",
            REGISTRE.zones_interdites("learning"), None)
    verifie("un type déclaré sans interdit se distingue d'un type absent",
            REGISTRE.zones_interdites("pilote"), set())


def registre_reel(brain: Path) -> None:
    print("\nLE REGISTRE RÉEL — NIVEAUX.yml contre KERNEL.md\n")
    try:
        import yaml
        d = yaml.safe_load((brain / "NIVEAUX.yml").read_text(encoding="utf-8"))
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⏭  `NIVEAUX.yml` illisible — {type(exc).__name__} : {exc}\n")
        global _abstenu
        _abstenu = True
        return

    niveaux, exceptions = {}, {}
    for bloc in d.values():
        if not isinstance(bloc, dict):
            continue
        for nom, val in bloc.items():
            if isinstance(val, dict):
                niveaux[nom] = val.get("niveau")
                if val.get("zone"):
                    exceptions[nom] = val["zone"]
            else:
                niveaux[nom] = val

    r = Registre(niveaux=niveaux, exceptions=exceptions)
    print(f"  ℹ️  {len(niveaux)} chemins déclarés · {len(exceptions)} exception(s) : "
          f"{', '.join(exceptions) or 'aucune'}")

    # Les quatre que `KERNEL.md` nomme explicitement KERNEL.
    for chemin in ("agents/", "profil/", "KERNEL.md", "brain-constitution.md"):
        verifie(f"« {chemin} » est kernel, comme le registre le dit",
                r.zone(chemin), KERNEL)

    verifie("`projets/` n'est pas kernel", r.zone("projets/brain.md"), INSTANCE)
    verifie("`workspace/` non plus", r.zone("workspace/x.md"), INSTANCE)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path)
    args = p.parse_args()

    derivation()
    garde()
    if args.brain:
        registre_reel(args.brain.expanduser().resolve())

    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
    return 1 if _ko else (3 if _abstenu else 0)


if __name__ == "__main__":
    sys.exit(main())
