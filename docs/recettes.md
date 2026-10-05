---
# Généré depuis docs/src/recettes.md par scripts/docs-generer.py — ne pas éditer ici.
label: Recettes
groupe: Utiliser
ordre: 7
---

# Recettes — quelle session, quels agents

> Les combinaisons qui marchent. Tout agent peut aussi se charger seul, dans
> n'importe quelle session : « charge l'agent X ».

---

## Au quotidien

**Coder, débugger** — `brain boot work/<projet>`

`debug`, `code-review` et `security` sont chargés d'office. Le debug suit une
méthode : reproduire, isoler, poser des hypothèses, vérifier, corriger. Si le
problème est d'infrastructure, il passe la main à `vps`.

**Explorer une idée** — `brain boot explore/brainstorm`

`brainstorm` challenge l'idée plutôt que de l'approuver. Pas de code attendu.

**Faire le point** — `brain boot explore/coach`

Bilan, objectifs, progression, avec `coach`.

**Voir où on en est** — `brain boot explore`, ou dire « pulse »

`pulse` résume les chantiers actifs, les dernières sessions, les derniers
commits — voir **Pulse**.

---

## Avant de livrer

**Review complète** — en session `work` : « charge les agents code-review,
security et testing ».

`code-review` lit selon sept priorités, de la sécurité à l'obsolescence ;
`security` audite l'OWASP Top 10, l'authentification, la configuration, les
secrets et les dépendances ; `testing` couvre les corrections.

**Performance** — « charge les agents optimizer-backend, optimizer-db et
optimizer-frontend ».

Chacun sait ce qu'il ne couvre pas et renvoie aux deux autres.

**Refacto sans casse** — « charge les agents refacto et testing ».

`testing` pose les tests d'abord ; `refacto` restructure une étape à la fois,
les tests verts à chaque étape. Pas de tests, pas de refacto qui touche un
module ou l'architecture.

---

## Déployer, surveiller

En session `work` : « charge les agents vps et ci-cd ».

`vps` monte le service (conteneur, reverse proxy, certificat), `ci-cd` écrit le
pipeline, `monitoring` propose une sonde après le déploiement. `pm2`,
`migration` et `mail` complètent selon le cas.

---

## Travailler sur le brain lui-même

**Modifier le noyau, les agents** — `brain boot brain`

`brain-guardian` exige une preuve pour chaque affirmation du brain sur
lui-même ; toute écriture dans le noyau attend ta confirmation.

**Auditer les agents** — en session `brain` : « charge l'agent agent-review ».

---

## Apprendre

`brain boot learning/<piste>` — une piste d'apprentissage, sans pression de
fin de session, sans écriture dans le noyau.

## Une longue session pilotée

`brain boot pilote/<projet>` — réservée à l'owner du brain. Le brain anticipe
et documente en continu ; les décisions irréversibles te reviennent.
