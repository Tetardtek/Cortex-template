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

DEFAUT = Path(__file__).resolve().parent.parent.parent / "brain-compose.local.yml"


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
