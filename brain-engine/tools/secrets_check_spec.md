---
name: secrets_check
type: spec
status: ready-to-implement
created: 2026-03-16
---

# Spec — brain-secrets-check

Outil de validation de cohérence des secrets entre envs.
Zero-exposure : seuls les fingerprints (SHA256) transitent, jamais les valeurs.

---

## Contrat d'interface

```
brain-secrets-check --register [--env <nom>]
brain-secrets-check --check   [--env <nom>] [--against <registry>]
brain-secrets-check --list
```

### `--register`
Calcule le SHA256 de chaque secret présent dans MYSECRETS et écrit les fingerprints dans le registry.
- Source : `~/Dev/Brain/MYSECRETS`
- Destination : `~/Dev/Brain/SECRETS_REGISTRY` (gitignored)
- Comportement : upsert par clé — met à jour si la clé existe, ajoute sinon
- Output : `✅ Registered: <N> keys — env: <nom>`

### `--check`
Compare le SHA256 des secrets actuels contre le registry.
- Source : MYSECRETS (env courant)
- Référence : SECRETS_REGISTRY
- Output par clé : `✅ BRAIN_TOKEN_MCP` ou `❌ BRAIN_TOKEN_MCP — mismatch` ou `⚠️ BRAIN_TOKEN_MCP — absent du registry`
- Exit code : 0 si tout ✅, 1 si au moins un ❌, 2 si erreur

### `--list`
Affiche les clés présentes dans le registry avec leur date d'enregistrement.
Jamais les valeurs, jamais les hashes.

---

## Format du registry — SECRETS_REGISTRY

```
# brain-secrets-check registry
# updated: 2026-03-16T21:34:00
# env: prod

BRAIN_TOKEN_OWNER: sha256=a3f9c2d1e8b7f4a6c3d9e2f1b8a7c4d6e3f2a1b9c8d7e6f5a4b3c2d1e0f9a8
BRAIN_TOKEN_MCP: sha256=b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2
BRAIN_TOKEN_PUBLIC: sha256=c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3
ORIGINSDIGITAL_DB_PASSWORD: sha256=d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4
```

Règles de format :
- Une ligne par clé : `KEY: sha256=<64 hex chars>`
- Lignes `#` pour les métadonnées
- Lignes vides autorisées entre sections
- Fichier texte brut — pas de JSON, pas de YAML (lisible en bootstrap sans parser)

---

## Périmètre des clés couvertes

### Priorité 1 — Brain-engine tokens (déclencheur initial)
- `BRAIN_TOKEN_OWNER`
- `BRAIN_TOKEN_MCP`
- `BRAIN_TOKEN_PUBLIC`

### Priorité 2 — Secrets projet (pattern BYOKS)
Toutes les clés MYSECRETS correspondant aux tables BYOKS des projets actifs :
- `*_DB_PASSWORD`, `*_JWT_SECRET`, `*_JWT_REFRESH_SECRET`
- `*_REDIS_PASSWORD`, `*_OAUTH_CLIENT_SECRET`, `*_GATEWAY_TOKEN`
- `*_ADMIN_PASSWORD`, `*_NODEMAILER_PASS`

### Hors périmètre
- `VPS_IP`, `VPS_USER` — faible entropie, SHA256 peu robuste, hors scope validator
- SSH keys — vérification existence + chmod 600 uniquement, pas de hash

---

## Comportement bootstrap (intégration BE-5 / helloWorld)

Séquence au boot :

```
1. secrets_check --check
   → ✅ tout cohérent : continuer silencieusement
   → ❌ mismatch détecté : afficher les clés en mismatch (jamais les valeurs)
                           bloquer avec message d'action requise
   → ⚠️ clé absente du registry : avertir uniquement, ne pas bloquer

2. BYOKS manquant (pattern d'un projet à clés multiples) :
   → ⚠️ avertissement : "BYOKS absent pour <projet> — à compléter à l'init"
   → jamais bloquer — un bootstrap cassé sur BYOKS manquant est pire qu'un secret absent
```

---

## Implémentation — secrets_check.py

### Algorithme `--register`

```python
import hashlib, re
from pathlib import Path

MYSECRETS = Path.home() / "Dev/Brain/MYSECRETS"
REGISTRY  = Path.home() / "Dev/Brain/SECRETS_REGISTRY"

def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def register(env: str = "prod"):
    entries = {}
    for line in MYSECRETS.read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val and not key.startswith("VPS_") and key not in ("VPS_IP", "VPS_USER"):
            entries[key] = fingerprint(val)
    # upsert dans le registry
    write_registry(entries, env)
```

### Algorithme `--check`

```python
def check(env: str = "prod") -> int:
    registry = load_registry()
    mismatches = []
    for line in MYSECRETS.read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not val or key.startswith("VPS_"):
            continue
        fp = fingerprint(val)
        if key not in registry:
            print(f"⚠️  {key} — absent du registry")
        elif registry[key] != fp:
            print(f"❌ {key} — mismatch")
            mismatches.append(key)
        else:
            print(f"✅ {key}")
    return 1 if mismatches else 0
```

### Règles d'implémentation

- Jamais afficher une valeur, jamais afficher un hash
- `--list` : noms de clés + date d'enregistrement uniquement
- Pas de dépendance externe — stdlib Python uniquement
- MYSECRETS inaccessible → exit code 2, message : `❌ MYSECRETS introuvable — vérifier brain_root`
- SECRETS_REGISTRY absent au `--check` → exit code 2, message : `❌ Registry absent — lancer --register d'abord`

---

## .gitignore

```
SECRETS_REGISTRY
```

À ajouter dans `~/Dev/Brain/.gitignore`.

---

## Prochaines étapes

- [ ] Implémenter `brain-engine/tools/secrets_check.py`
- [ ] Ajouter `SECRETS_REGISTRY` dans `.gitignore`
- [ ] Hook bootstrap dans `helloWorld.md` — step boot claim
- [ ] Signal `scribe` : BYOKS du projet à compléter à l'init projet
