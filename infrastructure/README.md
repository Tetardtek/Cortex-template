# infrastructure/

> Documentation de votre infrastructure reelle — VPS, services, ports, sous-domaines.

## Contenu attendu

- `vps.md` — architecture VPS (services, containers, reverse proxy)
- `monitoring.md` — stack monitoring (Gatus, Uptime Kuma, etc.)
- `mail.md` — configuration mail self-hosted (si applicable)

## Pourquoi

Les agents infra (`vps.md`, `monitoring.md`, `mail.md`, `ci-cd.md`) chargent ces fichiers comme contexte.
Sans eux, les agents fonctionnent mais sans connaissance de votre infrastructure.

> Creer ces fichiers au fur et a mesure que vous deployez vos services.
> Ne jamais commiter d'IP, ports ou credentials ici — utiliser MYSECRETS pour les valeurs sensibles.
