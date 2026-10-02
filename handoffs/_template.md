---
name: handoff-template
type: handoff
context_tier: cold
status: active          # active | consumed | archived
consumed_by: ~          # sess-id qui a consommé ce fichier
---

# Handoff — sess-YYYYMMDD-HHMM-<role>

> Écrit par la session source avant fermeture ou CHECKPOINT.
> Lu par helloWorld au boot de la session cible.
> Jamais édité manuellement après écriture.

---

## Contexte de transfert

| Champ | Valeur |
|-------|--------|
| Session source | `sess-YYYYMMDD-HHMM-<role>@machine` |
| Session cible | `sess-YYYYMMDD-HHMM-<role>@machine` (ou `prod@desktop` pour broadcast) |
| Type | `CHECKPOINT` / `HANDOFF` |
| Projet concerné | — |
| Écrit le | YYYY-MM-DD HH:MM |

---

## Ce qui a été fait

<!-- Bullet points — ce qui est terminé et fonctionnel -->

-

---

## État actuel

<!-- Ce qui tourne, ce qui est cassé, ce qui est en cours -->

-

---

## Prochaine étape (pour la session cible)

<!-- Action concrète à reprendre — une tâche précise, pas une direction vague -->

1.

---

## Fichiers clés

<!-- Fichiers créés ou modifiés — chemins relatifs au repo concerné -->

| Fichier | Rôle |
|---------|------|
| — | — |

---

## Commandes utiles

```bash
# Reprendre où la session s'est arrêtée
```

---

## Contexte supplémentaire

<!-- Tout ce qui évite à la session cible de re-découvrir ce qui a déjà été tenté -->

-
