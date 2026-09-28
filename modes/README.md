# modes/ — Soft locks comportementaux de session

Un mode se déclare dans le premier message : `brain boot mode navigate`

Il charge `modes/brain-<mode>.md` et définit ce que la session fait — et ce qu'elle refuse.

## Modes disponibles

| Mode | Trigger | Périmètre |
|------|---------|-----------|
| `navigate` | `brain boot mode navigate` | Architecture, coaching, brainstorm — pas d'exécution projet |

## Créer un mode

```markdown
---
name: brain-<mode>
type: mode
scope: session
trigger: "+<mode>"
---

## Ce que ce mode active
<Ce que la session fait>

## Ce que ce mode refuse
<Ce qu'elle ne fait pas — et quoi dire à la place>
```

→ Voir `examples/mode_example.md`
