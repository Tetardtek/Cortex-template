---
name: <nom-du-projet>
type: projet
context_tier: cold
status: <dev | prod | cadrage | pause | archived>
stack: [<tech1>, <tech2>]
deploy: <vps | local | none | github-pages>
---

# <Nom du projet>

> `brain/profil/memory-architecture.md` — sectionnarisation appliquée

---

## État courant
<!-- 🔴 CHAUD — mis à jour à chaque session -->

- <état général — prod live / en cours / en pause>
- <alertes actives ⚠️ si applicable>

---

## Opérationnel
<!-- 🟡 TIÈDE — infra, deploy, env — change moins souvent -->

| Info | Valeur |
|------|--------|
| URL prod | `https://<domaine>` |
| Process manager | <pm2 / Docker / systemd> |
| DB | `<nom-container>` — base `<nom-db>` — user `<user>` |
| VPS path | `/home/<user>/<projet>/` |
| Pipeline | `<fichier>.yml` — <N> jobs : <description> |
| Deploy | <procédure courte> |

**Commandes clés :**
```bash
# <commande fréquente>
<commande avec placeholders>
```

---

## Architecture
<!-- 🔵 FROID — structure technique, décisions — change rarement -->

**Stack :**
- Backend : <tech>
- Frontend : <tech>
- DB : <tech>
- Auth : <tech>

**Structure :**
```
<dossier>/
├── <dossier>/    ← <rôle>
└── <dossier>/    ← <rôle>
```

**Décisions clés :**
- <décision architecturale importante + pourquoi>

---

## Historique
<!-- 🔵 FROID — jalons, dates, contexte — ne change plus -->

| Date | Événement |
|------|-----------|
| <DATE> | Création du projet |
| <DATE> | <jalon important> |
