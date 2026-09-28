---
name: metabolism-spec
type: reference
context_tier: cold
---

# metabolism-spec.md — Schéma des métriques de santé session

> Dernière mise à jour : 2026-03-14
> Type : Référence
> Géré par : `metabolism-scribe`

---

## Schéma d'une entrée de session

```
session_id            : sess-YYYYMMDD-HHMM-<slug>
date                  : YYYY-MM-DD
type                  : build-brain | use-brain | auto
mode                  : prod | dev | sprint | debug | coach | brainstorm | ...
handoff_level         : NO | SEMI | SEMI+ | FULL
tokens_used           : <nombre — estimé depuis /context ou fourni manuellement>
context_peak_pct      : <pic d'utilisation du context — ex: 87>
context_at_close      : <context au moment du close — ex: 31>
duration_min          : <durée en minutes>
commits               : <nombre de commits produits>
todos_closed          : <todos cochés ✅ pendant la session>
saturation_flag       : true | false
health_score          : <calculé — voir formule>
cold_start_kpi_pass   : true | false | null   # OBLIGATOIRE si handoff_level: NO — voir §cold_start_kpi
agents_loaded         : <liste des agents invoqués/chargés pendant la session>
tokens_par_agent      : <estimation tokens par agent — voir formule prix>
notes                 : <optionnel — événement notable>
```

---

## Prix par agent — mandatory

Chaque session doit capturer `agents_loaded` et estimer le coût context de chaque agent.

```
Estimation :
  tokens_agent = taille_fichier_bytes / 4  (approximation standard)

Exemple :
  helloWorld.md      → 18k bytes → ~4500 tokens
  secrets-guardian.md → 12k bytes → ~3000 tokens
  debug.md           → 4k bytes  → ~1000 tokens
  total context agents : ~8500 tokens sur 200k = 4.3% alloué aux agents

Objectif : tendance sur 10 sessions
  → Quels agents sont toujours chargés pour rien ?
  → Quels agents coûtent cher vs leur valeur produite ?
  → Base de décision pour le context-orchestrator (chargement capillaire)
```

Format dans le metabolism log :
```
agents_loaded:
  - session-orchestrator : ~Xk tokens
  - helloWorld           : ~Xk tokens
  - <agent>              : ~Xk tokens
total_context_agents     : ~Xk tokens  (X% du budget total)
```

---

## Formule health_score — 3 profils (BRAIN-044)

Le health_score est adapte par profil de session. La formule universelle est remplacee par 3 formules.

### Profil productif (use-brain)

Sessions : work, deploy, debug, infra, urgence

```
health_score = (todos_closed * 10 + commits * 5) / max(1, tokens_used_k * context_peak_pct / 100)

Exemples :
  todos=2, commits=3, tokens=45k, peak=31%  → (20+15) / (45 * 0.31) = 35 / 13.95 ≈ 2.51
  todos=0, commits=0, tokens=80k, peak=87%  → 0 / 69.6 = 0  → saturation_flag = true
```

### Profil constructif (build-brain)

Sessions : brain, edit-brain, kernel, pilote

```
health_score = (kernel_files_touched * 15 + adrs_written * 20) / max(1, tokens_used_k * context_peak_pct / 100)

Notes :
  - kernel_files_touched = fichiers dans agents/, profil/, KERNEL.md, brain-compose.yml modifies
  - adrs_written = nombre d'ADRs ecrites ou mises a jour pendant la session
  - todos_closed non pertinent — pas de penalite si 0
```

### Profil exploratoire (explore-brain)

Sessions : brainstorm, navigate, coach, capital, handoff, audit

```
health_score = (insights_captured * 8 + duration_min * 0.1) / max(1, tokens_used_k * context_peak_pct / 100)

Notes :
  - insights_captured = todos crees + decisions prises + notes capturees
  - score minimal garanti : jamais 0 si duree > 10 min
  - commits et todos_closed non mesures (non attendus)
```

### Poids ratio 7j par profil

| Profil | Poids | Raison |
|--------|-------|--------|
| productif | 1.0 | Standard |
| constructif | 1.0 | Standard |
| exploratoire | 0.5 | Un brainstorm de 2h ne plombe pas le ratio |

Le score n'est pas absolu — il se lit en tendance sur 7 jours.

---

## saturation_flag — par profil

| Profil | Condition saturation_flag = true |
|--------|--------------------------------|
| **productif** | `context_peak_pct > 80` ET `todos_closed = 0` |
| **constructif** | `context_peak_pct > 85` ET `kernel_files_touched = 0` |
| **exploratoire** | Jamais — explore = libre par nature |

Signal : session qui consomme sans produire, adapte au type de session.

---

## Taxonomie session — 3 categories (BRAIN-044)

| Categorie | Sessions | Definition |
|-----------|----------|-----------|
| **use-brain** | work, deploy, debug, infra, urgence | Utilise le brain pour produire sur un projet |
| **build-brain** | brain, edit-brain, kernel, pilote | Construit/ameliore le brain lui-meme |
| **explore-brain** | brainstorm, navigate, coach, capital, handoff, audit | Explore, reflechit, audite — pas de livrable attendu |
| `auto` | — | Session mixte ou non classifiable — metabolism-scribe tranche en fin |

> Evolution depuis la dichotomie build/use : la categorie `explore-brain` capture les sessions
> qui ne sont ni productives ni constructives mais ont une valeur propre (reflexion, orientation).

**Regle ratio sur 7 jours glissants :**
```
ratio = use-brain_sessions / build-brain_sessions
→ ratio >= 1.0 : equilibre ou sain
→ ratio < 0.5  : ⚠️ Signal boucle narcissique — trop de build-brain sans usage reel

Note : les sessions explore-brain comptent avec un poids de 0.5 dans le denominateur.
Un brainstorm de 2h ne plombe pas le ratio.
```

Le signal est affiche dans le briefing helloWorld si `ratio < 0.5` sur 7j.

---

## Seuils — mode conserve

| Condition | Signal |
|-----------|--------|
| `context_peak_pct > 70` ET `health_score < 1.0` | ⚠️ Session peu efficiente détectée |
| `context_at_close > 60` | ⚠️ Mode conserve recommandé pour la prochaine session |
| `ratio < 0.5` sur 7j | ⚠️ Boucle narcissique — alterner avec une session use-brain |

Mode `conserve` : helloWorld le propose (jamais forcé) si seuil atteint au boot.

---

## Modes et budget context attendu

| Mode | Budget context | Saturation tolérée |
|------|----------------|-------------------|
| `prod` | normal — surveiller à 60% | non |
| `sprint` | élargi — 80% acceptable si output élevé | oui si commits > 5 |
| `conserve` | strict — target <40% | non |
| `brainstorm` | libre | oui — exclut saturation_flag |
| `review` | minimal — lecture seule | non |
| `debug` | modéré | non |
| `coach` | modéré | non |

---

## cold_start_kpi — KPI North Star (brain-constitution.md §3)

> Ce KPI mesure l'identité réelle de Layer 0 : est-il suffisant pour démarrer productif sans handoff ?

```
Condition d'activation : handoff_level == NO dans le claim de session

Mesure :
  cold_start_time = durée entre le boot (briefing helloWorld) et la première action productive
  → "première action productive" = premier commit | premier todo coché | première décision validée

cold_start_kpi_pass :
  true  → cold_start_time < 2 min  (Layer 0 est solide)
  false → cold_start_time >= 2 min (Layer 0 insuffisant → enrichir brain-constitution.md)
  null  → non mesuré (session NO HANDOFF mais pas chronométrée — acceptable, annoter dans notes)
```

**Règle metabolism-scribe :**
- Si `handoff_level: NO` → demander à l'utilisateur : "Première action productive en moins de 2 min ?" (oui/non)
- Si `null` → laisser `null` mais annoter `notes: cold_start non mesuré`
- Ne pas inventer une valeur — `null` est préférable à une estimation non fondée

**Tendance sur 7 sessions NO HANDOFF :**
```
ratio_pass = count(cold_start_kpi_pass == true) / count(cold_start_kpi_pass != null)
→ ratio_pass >= 0.80 : Layer 0 stable
→ ratio_pass < 0.60  : Layer 0 à enrichir — session dédiée brain-constitution.md requise
```

---

## Changelog

| Date | Changement |
|------|------------|
| 2026-03-14 | Création — schéma métriques, formule health_score, taxonomie build/use-brain, seuils conserve, ratio 7j |
| 2026-03-14 | Prix par agent mandatory — champs agents_loaded + tokens_par_agent, formule estimation, objectif tendance 10 sessions |
| 2026-03-16 | P4 shadow-sql — ajout handoff_level + cold_start_kpi_pass + section §cold_start_kpi (KPI North Star brain-constitution §3) |
| 2026-03-20 | BRAIN-044 — 3 profils scoring (productif/constructif/exploratoire), taxonomy 3 categories (use/build/explore-brain), saturation_flag par profil |
