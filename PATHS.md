# PATHS.md — Résolution des chemins machine

> **Fichier de reference** — les agents utilisent les noms semantiques ci-dessous pour resoudre les chemins.
> Les placeholders (`<BRAIN_ROOT>`) sont remplaces automatiquement par `scripts/brain-setup.sh`.
> Ce fichier reste avec des placeholders dans le template — c'est normal.
> Ne jamais hardcoder un chemin absolu dans les agents — toujours utiliser les noms semantiques.

---

## Chemins actifs

| Nom sémantique | Chemin réel | Remote | Gitignored dans brain |
|----------------|-------------|--------|----------------------|
| `brain/` | `<BRAIN_ROOT>` | `YOUR-ORG/Cortex-Template` | — (repo racine) |
| `toolkit/` | `<BRAIN_ROOT>/toolkit/` | `YOUR-ORG/Cortex-Template-Toolkit` | ✅ |
| `progression/` | `<BRAIN_ROOT>/progression/` | `YOUR-ORG/Cortex-Template-Progression` | ✅ |
| `reviews/` | `<BRAIN_ROOT>/reviews/` | `YOUR-ORG/Cortex-Template-Reviews` | ✅ |
| `profil/` | `<BRAIN_ROOT>/profil/` | `YOUR-ORG/Cortex-Template-Profil` | ✅ |
| `todo/` | `<BRAIN_ROOT>/todo/` | `YOUR-ORG/Cortex-Template-Todo` | ✅ |
| `projects/` | `<PROJECTS_ROOT>` | GitHub / Gitea | — |
| `home/` | `<HOME>` | — | — |

## Architecture satellite repos

Les repos gitignores dans `brain/` sont des **satellites autonomes** — chacun a son propre remote.
Chaque dossier satellite contient un README guide dans le template. Le setup les remplace par vos clones.

```bash
# Exemple avec GitHub (remplacer YOUR-ORG par votre organisation/user)
git clone https://github.com/YOUR-ORG/Cortex-Template.git <BRAIN_ROOT>
git clone https://github.com/YOUR-ORG/Cortex-Template-Toolkit.git <BRAIN_ROOT>/toolkit
git clone https://github.com/YOUR-ORG/Cortex-Template-Progression.git <BRAIN_ROOT>/progression
git clone https://github.com/YOUR-ORG/Cortex-Template-Reviews.git <BRAIN_ROOT>/reviews
git clone https://github.com/YOUR-ORG/Cortex-Template-Profil.git <BRAIN_ROOT>/profil
git clone https://github.com/YOUR-ORG/Cortex-Template-Todo.git <BRAIN_ROOT>/todo
```

---

## Règle anti-hallucination — obligatoire pour tous les agents

> Si un chemin n'est pas dans cette table → **ne pas deviner**.
> Écrire : `"Information manquante — vérifier PATHS.md"`

---

## Procedure — nouvelle machine

```bash
# 1. Forker Cortex-Template + les 5 satellites, puis cloner
git clone https://github.com/YOUR-ORG/Cortex-Template.git <BRAIN_ROOT>
cd <BRAIN_ROOT>

# 2. Lancer le setup — clone les satellites, configure CLAUDE.md, init brain-engine
bash scripts/brain-setup.sh

# 3. Configurer Claude Code
cp profil/CLAUDE.md.example ~/.claude/CLAUDE.md
# Editer brain_root et brain_name dans ~/.claude/CLAUDE.md

# 4. (Optionnel) Deployer le global memory Claude
ln -s <BRAIN_ROOT>/memory-global ~/.claude/memory

# 5. Lancer brain-engine + brain boot
bash scripts/brain-engine.sh start
# Dans un autre terminal : claude → brain boot
```

> Guide detaille : [docs/getting-started.md](docs/getting-started.md)

---

## Historique machines

| Machine | OS | `brain/` | Actif |
|---------|----|----------|-------|
| *(à remplir)* | | | |
