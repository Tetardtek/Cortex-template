---
name: <nom-du-projet>
type: projet
context_tier: cold
status: <planned | cadrage | dev | active | prod | pause | archived>
stack: [<tech1>, <tech2>]
deploy: <vps | local | none | github-pages>
# Une fiche ici, c'est ce qui SE CONSTRUIT. Une piste — une étude de cas, rien d'acquis — va dans
# vie/pistes/ ; la production (posts, réseaux) dans contenu/.
# La zone projet. Le slug (nom du fichier) est la clé :
# le dossier de liste est `workspace/backlog/<slug>/`.
repo: <forge>/<owner>/<depot>                 # le dépôt de TRAVAIL (la forge privée) ; ses issues
vitrine: <github.com>/<owner>/<depot>         # optionnel — la vitrine publique, releases seulement
prefixe: <XX>                                # le jour de sa PREMIÈRE tâche à suivre : <XX>-<n>
                                             # d'ici là, sa vision.md suffit
palier: a                                    # a (défaut) | b | c — c ne se pose que par l'humain
---

# <Nom du projet>

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
