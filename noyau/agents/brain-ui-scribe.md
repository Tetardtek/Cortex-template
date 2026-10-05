---
name: brain-ui-scribe
type: agent
context_tier: warm
domain: product
status: active
description: "Brain-UI scribe — contexte brain-ui, stack, composants"
brain:
  version:   1
  type:      scribe
  scope:     project
  owner:     human
  lifecycle: permanent
  read:      trigger
  triggers:  [brain-ui, dashboard, sprint-ui]
  ipc:
    receives_from: [orchestrator, human]
    sends_to:      [orchestrator]
    zone_access:   [project]
    zone_write:    []
    signals:       [SPAWN, RETURN, ESCALATE]
---

# Agent : brain-ui-scribe

> Dernière validation : 2026-03-17
> Domaine : Contexte technique + produit brain-ui — injecté dans tout agent travaillant sur l'interface
> **Type :** Scribe — chargé avant tout agent qui touche brain-ui

---

## boot-summary

Donne le contexte précis de brain-ui à tout agent qui doit travailler dessus.
Sans ce scribe, les agents re-découvrent l'architecture à chaque session.

---

## État actuel (2026-09-28)

### Déploiement
- **URL** : l'instance locale — `http://127.0.0.1:<BRAIN_PORT>/ui/`
  ⚠️ Jamais une URL distante : elle sert l'interface d'un AUTRE brain.
- **Repo** : ${GITEA_HOST}:<owner>/brain-ui.git
- **Servi par** : brain-engine, qui monte `brain-ui/dist/` sur `/ui/`
  (`scripts/brain-setup.sh` construit le dashboard)
- **Local** : `npm run dev` → localhost:5173

### Stack
- **Svelte 5** + Vite + TypeScript + Tailwind 4
- `marked` — rendu des pages de doc ; `three` — Cosmos 3D
- base Vite : `/ui/`

L'ancienne app React (React Flow, react-three-fiber, Zustand, `TierGate`,
`useTier`…) n'était plus atteinte par rien depuis la migration Svelte : 39
fichiers, retirés le 27/09. Ne pas la chercher.

### Ce que l'app contient
| Fichier | Rôle | Source des données |
|---------|------|--------------------|
| `App.svelte` + `lib/Sidebar.svelte` | coquille, navigation | — |
| `views/DocsView.svelte` | la doc | **live** — `GET /docs`, `GET /docs/<page>.md` |
| `views/Dashboard.svelte` | compteurs, fiches en cours, sessions | **live** — compteurs (`/agents`, `/docs`), fiches en cours (`GET /focus`), sessions (`GET /bsi/claims`) |
| `views/CosmosView.svelte` | Cosmos 3D | **live** — `GET /visualize` |
| `views/PlaceholderView.svelte` | vues à venir | — |

---

## Architecture cible (Sprint 3+)

### API locale (backend brain)
```
GET  /workflows              → liste workflows + statuts
POST /gate/…/approve         → retirée le 30/09 (machinerie archivée)
GET  /logs/:project          → retirée le 29/09 (ne lisait que pm2) ; l'état des services : GET /state
GET  /health                 → status, indexed, uptime + infos base
```

### Prochaines priorités
1. ~~Brancher `onGateApprove` sur l'API gate réelle~~ — la route est retirée (30/09)
2. `StatusDot` — indicateur pulsant live kernel/services
3. Cosmos heatmap mode nébuleuse → déjà livré ✅

---

## Références design
- Netdata — status indicators pulsants + densité info
- Vercel Dashboard — workflow steps + log viewer inline
- Grafana — command palette + alert banners

---

## Règles pour les agents qui travaillent sur brain-ui

```
- base Vite = '/ui/' — ne jamais changer
- Tailwind uniquement — pas de CSS inline
- Tokens brain-* dans tailwind.config.js — utiliser ces tokens, pas des hex orphelins
- Jamais de logique métier dans les composants UI — dans les hooks
```

---

## Sources à lire pour contexte complet
- `brain-ui/docs/specs/product-audit.md` — leviers + monitoring
- `brain-ui/docs/specs/design-system.md` — tokens + composants inventaire
- `brain-ui/docs/specs/sprint2-specs.md` — API + state + plan migration

---

## Invocation

```
brain-ui-scribe, donne le contexte complet avant de travailler sur brain-ui
brain-ui-scribe, qu'est-ce qui est branché vs mock dans l'UI actuelle ?
brain-ui-scribe, quelles dépendances sont déjà installées ?
```

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-17 | Création — contexte brain-ui injecté avant tout agent UI |
| 2026-03-18 | État mis à jour — Sprint 2 livré (cosmos 3D, WebSocket, GatesDrawer, CommandPalette, InfraRegistry, 8 hooks, zustand) — review audit guidé Batch B |
| 2026-10-04 | Dashboard : `data/demo.ts` retiré (il lit `/focus` et `/bsi/claims`) ; `/logs` marquée retirée, `/health` décrite comme elle répond ; règles et triggers React Flow retirés ; sources sous `brain-ui/docs/specs/` |
