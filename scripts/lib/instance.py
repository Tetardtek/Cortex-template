#!/usr/bin/env python3
# brain-distribuable: oui  # bsi-signal.sh, distribuable, s'en sert
"""L'identité de CETTE instance — `<nom>@<machine>`, lue dans brain-compose.local.yml.

Une seule règle, deux lecteurs : `bsi-signal.sh` (mon_instance) et
`claude-boite.py`. Elle était recopiée dans les deux — la règle en deux
exemplaires que combat —, relevé en relisant brain#87.

🔴 Elle se PLAINT. L'ancienne `mon_instance` rendait `inconnue@inconnue` sur toute
erreur, sans un mot : `inbox` relevait une boîte qui n'existe pas et disait
« (aucun) ».

    python3 scripts/lib/instance.py [chemin/brain-compose.local.yml]
"""

from __future__ import annotations

import sys
from pathlib import Path


def _racine_des_donnees(env_d_abord: bool = False) -> Path:
    """La data de ce script, par `brain-engine/donnees.py` du programme : sans la
    marque d'un programme installé à part, la position (et `BRAIN_ROOT` si `env_d_abord`),
    comme avant. Un banc qui ne copie que ce script n'a pas `donnees.py` : la position."""
    import os as _os
    ici = Path(__file__).resolve().parent.parent.parent
    src = ici / "brain-engine" / "donnees.py"
    if not src.is_file():
        return Path(_os.environ.get("BRAIN_ROOT") or ici) if env_d_abord else ici
    import importlib.util
    spec = importlib.util.spec_from_file_location("_brain_donnees", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.trouver_donnees(ici, env_d_abord=env_d_abord)[0]
    except RuntimeError as exc:
        raise SystemExit(f"❌ {exc}")


DEFAUT = _racine_des_donnees() / "brain-compose.local.yml"   # la data


class IdentiteIllisible(RuntimeError):
    pass


def instance(compose: Path = DEFAUT) -> str:
    import yaml
    try:
        c = yaml.safe_load(Path(compose).read_text(encoding="utf-8")) or {}
    except Exception as exc:                                   # noqa: BLE001
        raise IdentiteIllisible(f"identité de l'instance illisible — {compose} : {exc}")
    inst = c.get("instances") or {}
    nom = next((k for k, v in inst.items() if (v or {}).get("active")), None) \
        or next(iter(inst), None)
    if not nom or not c.get("machine"):
        raise IdentiteIllisible(f"identité de l'instance incomplète dans {compose} "
                                f"(instance : {nom}, machine : {c.get('machine')})")
    return f"{nom}@{c['machine']}"


if __name__ == "__main__":
    try:
        print(instance(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAUT))
    except IdentiteIllisible as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
