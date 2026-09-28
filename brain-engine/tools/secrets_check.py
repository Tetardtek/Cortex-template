#!/usr/bin/env python3
"""
brain-secrets-check — validateur cohérence secrets zero-exposure
SHA256 local uniquement, jamais les valeurs.

Usage:
  secrets_check.py --register [--env <nom>]
  secrets_check.py --check    [--env <nom>] [--against <registry>]
  secrets_check.py --list
"""

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

BRAIN_ROOT = Path.home() / "Dev/Brain"
# Le fichier vit dans le satellite `brain-secrets/` (git-crypt), comme le
# declare PATHS.md. `SECRETS_REGISTRY`, lui, est bien reste a la racine.
MYSECRETS  = BRAIN_ROOT / "brain-secrets" / "MYSECRETS"
REGISTRY   = BRAIN_ROOT / "SECRETS_REGISTRY"

# Clés hors périmètre (faible entropie ou vérification différente)
EXCLUDED_PREFIXES = ("VPS_",)
EXCLUDED_KEYS     = ("VPS_IP", "VPS_USER")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def parse_mysecrets(path: Path) -> dict[str, str]:
    """Retourne {KEY: value} — exclut commentaires, vides, hors-périmètre."""
    if not path.exists():
        print("❌ MYSECRETS introuvable — vérifier brain_root", file=sys.stderr)
        sys.exit(2)

    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if not val:
            continue
        if key in EXCLUDED_KEYS:
            continue
        if any(key.startswith(p) for p in EXCLUDED_PREFIXES):
            continue
        entries[key] = val
    return entries


def load_registry(path: Path) -> tuple[dict[str, str], str]:
    """Retourne ({KEY: sha256_hex}, updated_str)."""
    if not path.exists():
        return {}, ""

    entries: dict[str, str] = {}
    updated = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# updated:"):
            updated = line.replace("# updated:", "").strip()
            continue
        if line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        rest = rest.strip()
        if rest.startswith("sha256="):
            entries[key.strip()] = rest[len("sha256="):]
    return entries, updated


def write_registry(entries: dict[str, str], env: str, path: Path) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    lines = [
        "# brain-secrets-check registry",
        f"# updated: {now}",
        f"# env: {env}",
        "",
    ]
    for key in sorted(entries):
        lines.append(f"{key}: sha256={entries[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Commandes
# ---------------------------------------------------------------------------

def cmd_register(env: str) -> int:
    secrets = parse_mysecrets(MYSECRETS)

    # Charger registry existant pour upsert
    existing, _ = load_registry(REGISTRY)
    merged = {**existing}
    for key, val in secrets.items():
        merged[key] = fingerprint(val)

    write_registry(merged, env, REGISTRY)
    print(f"✅ Registered: {len(secrets)} keys — env: {env}")
    return 0


def cmd_check(env: str, against: Path) -> int:
    if not against.exists():
        print("❌ Registry absent — lancer --register d'abord", file=sys.stderr)
        sys.exit(2)

    secrets  = parse_mysecrets(MYSECRETS)
    registry, _ = load_registry(against)

    mismatches = 0
    for key, val in sorted(secrets.items()):
        fp = fingerprint(val)
        if key not in registry:
            print(f"⚠️  {key} — absent du registry")
        elif registry[key] != fp:
            print(f"❌ {key} — mismatch")
            mismatches += 1
        else:
            print(f"✅ {key}")

    return 1 if mismatches else 0


def cmd_list(against: Path) -> int:
    if not against.exists():
        print("❌ Registry absent — lancer --register d'abord", file=sys.stderr)
        sys.exit(2)

    registry, updated = load_registry(against)
    if not registry:
        print("(registry vide)")
        return 0

    print(f"Registry — {len(registry)} clé(s) — enregistré: {updated or 'inconnu'}")
    print()
    for key in sorted(registry):
        print(f"  {key}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="secrets_check",
        description="Validateur cohérence secrets — zero-exposure (SHA256 local)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--register", action="store_true", help="Enregistrer les fingerprints")
    group.add_argument("--check",    action="store_true", help="Vérifier la cohérence")
    group.add_argument("--list",     action="store_true", help="Lister les clés du registry")

    parser.add_argument("--env",     default="prod",    help="Nom de l'environnement (default: prod)")
    parser.add_argument("--against", default=str(REGISTRY), help="Chemin du registry (default: SECRETS_REGISTRY)")

    args = parser.parse_args()
    registry_path = Path(args.against)

    if args.register:
        sys.exit(cmd_register(args.env))
    elif args.check:
        sys.exit(cmd_check(args.env, registry_path))
    elif args.list:
        sys.exit(cmd_list(registry_path))


if __name__ == "__main__":
    main()
