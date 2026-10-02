#!/usr/bin/env python3
"""Contrôle des manifests de session

`contexts/session-<type>.yml` décrit ce que chaque type de session charge au
boot. **Aucun code ne les parse** : c'est l'agent qui les lit, en texte. C'est
pourquoi trois formes différentes du même concept ont pu coexister sans que rien
proteste, et pourquoi `session-pilote.yml` a été du YAML invalide sans qu'on le
sache.

Un contrat que personne ne vérifie n'est pas un contrat.

    python3 tools/session_manifests.py --brain ~/Dev/Brain
    python3 tools/session_manifests.py --brain ~/Dev/Brain --check   # pour la CI

Le contrat vérifié, bloc `L2` :

    template  chaîne contenant `{project}`, ou null — le fichier du scope
    extras    liste de chemins ; `{project}` est substitué s'il apparaît,
              et un fichier absent est ignoré au boot
    fallback  chaîne ou null — chargé quand `template` ne résout rien

Une clé inconnue est une dérive, pas une extension : c'est ce qui a laissé
`template_optional` s'installer dans un seul manifest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("FAIL: PyYAML requis (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(1)

CLES_L2 = {"template", "extras", "fallback"}
TYPES_ATTENDUS = {"work", "brain", "explore", "pilote", "chill", "learning"}


def controle(chemin: Path, racine: Path) -> list[str]:
    """Anomalies d'un manifest. Liste vide = conforme."""
    anomalies: list[str] = []
    try:
        manifest = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        detail = next((l.strip() for l in str(exc).splitlines() if "line" in l), str(exc)[:70])
        return [f"YAML invalide — {detail}"]
    if not isinstance(manifest, dict):
        return ["le manifest n'est pas un mapping"]

    bloc = manifest.get("L2")
    if bloc is None:
        return ["bloc `L2` absent"]
    if not isinstance(bloc, dict):
        return ["`L2` n'est pas un mapping"]

    inconnues = set(bloc) - CLES_L2
    if inconnues:
        anomalies.append(f"clé(s) hors contrat : {', '.join(sorted(inconnues))}")
    for manquante in sorted(CLES_L2 - set(bloc)):
        anomalies.append(f"clé `{manquante}` absente")

    gabarit = bloc.get("template")
    if gabarit is not None:
        if not isinstance(gabarit, str):
            anomalies.append(f"`template` devrait être une chaîne ou null, pas {type(gabarit).__name__}")
        elif "{project}" not in gabarit:
            anomalies.append(f"`template` sans `{{project}}` : {gabarit!r}")

    extras = bloc.get("extras")
    if extras is not None and not isinstance(extras, list):
        anomalies.append(f"`extras` devrait être une liste, pas {type(extras).__name__}")
    elif isinstance(extras, list):
        for entree in extras:
            if not isinstance(entree, str):
                anomalies.append(f"`extras` contient un {type(entree).__name__}")
            elif "{project}" not in entree and not (racine / entree).exists():
                # Un chemin fixe qui n'existe plus fait charger moins, en silence.
                anomalies.append(f"`extras` pointe un fichier absent : {entree}")

    repli = bloc.get("fallback")
    if repli is not None and not isinstance(repli, str):
        anomalies.append(f"`fallback` devrait être une chaîne ou null, pas {type(repli).__name__}")

    return anomalies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brain", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="sortie non nulle si dérive")
    args = parser.parse_args()

    racine = args.brain.expanduser().resolve()
    manifests = sorted((racine / "contexts").glob("session-*.yml"))
    if not manifests:
        print(f"FAIL: aucun manifest dans {racine / 'contexts'}", file=sys.stderr)
        return 2

    print(f"\n{len(manifests)} manifests\n")
    total = 0
    for chemin in manifests:
        anomalies = controle(chemin, racine)
        total += len(anomalies)
        marque = "✅" if not anomalies else "❌"
        print(f"  {marque} {chemin.name}")
        for anomalie in anomalies:
            print(f"       {anomalie}")

    trouves = {c.stem.replace("session-", "") for c in manifests}
    if manquants := TYPES_ATTENDUS - trouves:
        total += len(manquants)
        print(f"\n  ❌ type(s) de session sans manifest : {', '.join(sorted(manquants))}")
    if surplus := trouves - TYPES_ATTENDUS:
        print(f"\n  ℹ️  manifest(s) hors des 6 types déclarés : {', '.join(sorted(surplus))}")

    print(f"\n{'✅ les manifests respectent le contrat' if not total else f'❌ {total} anomalie(s)'}\n")
    return 1 if (args.check and total) else 0


if __name__ == "__main__":
    raise SystemExit(main())
