#!/usr/bin/env python3
"""La porte MCP répond-elle vraiment ? —.

Ce qui pourrirait en silence sans lui : **un outil qui se charge et ne rend
rien.** `ast.parse` prouve qu'un fichier est syntaxiquement valide ; il ne
prouve pas qu'une fonction répond. Le 10/09, en retirant le « slot garanti » de
`brain_boot`, la seule vérification disponible était la lecture du diff — et la
journée entière avait démontré que lire ne suffit pas.

    python3 tools/eprouver_porte_mcp.py --brain ~/Dev/Brain

── Ce qu'il fait, et ce qu'il ne fait pas ──────────────────────────────────

Il **charge le module et appelle les outils**, dans un processus à part. Il ne
lance aucun serveur, ne touche pas au service en production, et n'écrit rien :
les outils éprouvés ici sont tous en lecture.

Il ne parle pas le protocole MCP. Ce n'est pas le sujet : ce qu'on veut savoir
est si la fonction rend quelque chose, pas si `FastMCP` sait la publier — ça,
le service qui tourne depuis des mois le prouve déjà.

── Il s'abstient plutôt que de mentir ──────────────────────────────────────

`brain_boot` interroge Ollama pour ses requêtes RAG. Si Ollama ne répond pas,
l'outil rend une réponse **partielle et légitime** — et un contrôle qui
lirait ça comme un échec accuserait la mauvaise chose. Il le déclare abstenu.

── Le témoin négatif ───────────────────────────────────────────────────────

Sans lui, « brain_boot rend du texte » ne mesure rien : il en rendrait aussi
avec une section morte. On force donc `brain_state` à échouer, et on vérifie
que la sortie **rétrécit**. Si elle ne bouge pas, c'est que la section n'y
était pas — et le vert du cas nominal était creux.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path


def charger(moteur: Path):
    sys.path.insert(0, str(moteur))
    return importlib.import_module("mcp_server")


def scopes_du_service() -> list[str] | None:
    """Les scopes que le SERVICE utilise — `None` si on ne peut pas savoir.

    🔴 Ajouté le 10/09 au soir, après avoir mesuré un défaut de cet outil
    lui-même. `mcp_server.MCP_SCOPES` est lu dans l'environnement au moment de
    l'import :

        MCP_SCOPES = os.getenv('BRAIN_MCP_SCOPES', 'public,work').split(',')

    Le service `brain-mcp-local` déclare `instance,satellite,public,work`. Mais
    ce contrôle charge le module dans un shell ordinaire, où la variable
    n'existe pas — il mesurait donc le MCP avec **deux scopes sur quatre**, sans
    le dire. Un outil qui éprouve une configuration que personne n'exécute
    rassure sur autre chose que ce qui tourne.

    On ne les invente donc pas : on les LIT dans l'unité systemd, et on les
    APPLIQUE avant l'import — mesurer ce qui tourne, plutôt qu'avertir dans une
    ligne que personne ne relit. Quand on ne peut pas les lire (pas de systemd,
    un fork du template), on mesure avec ce qu'on a et on le dit.
    """
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", "brain-mcp-local.service",
             "-p", "Environment"],
            capture_output=True, text=True, timeout=5)
    except Exception:                                          # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    for morceau in r.stdout.strip().split():
        if morceau.startswith("BRAIN_MCP_SCOPES="):
            valeur = morceau.split("=", 1)[1]
            return [s.strip() for s in valeur.split(",") if s.strip()]
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Éprouver les outils MCP hors service")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()

    moteur = a.brain.expanduser().resolve() / "brain-engine"
    if not (moteur / "mcp_server.py").is_file():
        print("⏭️  SKIP mcp_server.py introuvable.", file=sys.stderr)
        return 0

    # L'ordre compte : `MCP_SCOPES` est lu a l'import, pas a l'appel. Poser la
    # variable apres `charger()` n'aurait aucun effet — et aurait produit un
    # vert parfaitement trompeur.
    du_service = scopes_du_service()
    if du_service:
        os.environ["BRAIN_MCP_SCOPES"] = ",".join(du_service)

    try:
        m = charger(moteur)
    except Exception as exc:                                   # noqa: BLE001
        print(f"❌ le module ne se charge pas : {type(exc).__name__} — {exc}",
              file=sys.stderr)
        return 1
    print(f"  ✅ module chargé — {len([n for n in dir(m) if n.startswith('brain_')])} "
          f"outils définis, aucun service levé")

    # Avec QUELS scopes ? La reponse change ce que les outils rendent.
    ici = list(getattr(m, "MCP_SCOPES", []) or [])
    if du_service is None:
        print(f"  ⏭️  scopes : {','.join(ici) or '—'} — ceux du service sont "
              f"inconnus (pas de systemd utilisateur), on mesure avec ceux-ci")
    elif sorted(ici) != sorted(du_service):
        print(f"  ❌ scopes : {','.join(ici)} — le service dit "
              f"{','.join(du_service)} et l'import n'en a pas tenu compte.",
              file=sys.stderr)
        return 1
    else:
        print(f"  ✅ scopes repris du service : {','.join(ici)}")

    # ── 1. l'environnement dérivé, sans dépendance externe ──────────────────
    try:
        etat = m.brain_state()
    except Exception as exc:                                   # noqa: BLE001
        print(f"  ❌ brain_state a levé : {type(exc).__name__} — {exc}", file=sys.stderr)
        return 1
    etat_ok = bool(etat) and "Indisponible" not in etat
    print(f"  {'✅' if etat_ok else '⏭️ '} brain_state — {len(etat or '')} caractères"
          + ("" if etat_ok else "  (indisponible : le moteur HTTP ne répond pas)"))

    # ── 2. brain_boot, la porte qu'on vient de modifier ─────────────────────
    try:
        boot = m.brain_boot()
    except Exception as exc:                                   # noqa: BLE001
        print(f"  ❌ brain_boot a levé : {type(exc).__name__} — {exc}", file=sys.stderr)
        return 1

    sections = [s for s in (boot or "").split("\n\n---\n\n") if s.strip()]
    print(f"  {'✅' if sections else '❌'} brain_boot — {len(boot or '')} caractères, "
          f"{len(sections)} section(s)")

    if not sections:
        print("  ❌ brain_boot ne rend RIEN — la porte est muette.", file=sys.stderr)
        return 1

    # ── 3. le témoin négatif : une section retirée doit se voir ─────────────
    vrai_state = m.brain_state
    try:
        m.brain_state = lambda: "Indisponible"
        ampute = m.brain_boot()
    finally:
        m.brain_state = vrai_state

    sections_ampute = [s for s in (ampute or "").split("\n\n---\n\n") if s.strip()]
    if etat_ok:
        vu = len(sections_ampute) < len(sections)
        print(f"  {'✅' if vu else '❌'} témoin négatif — sans `brain_state` : "
              f"{len(sections)} → {len(sections_ampute)} section(s)")
        if not vu:
            print("  ❌ retirer une section ne change rien : le vert ci-dessus ne "
                  "mesurait pas ce qu'il annonçait.", file=sys.stderr)
            return 1
    else:
        print("  ⏭️  témoin négatif inapplicable — `brain_state` est déjà "
              "indisponible, on ne peut pas mesurer son retrait")

    # ── 4. les outils qui lisent le disque ──────────────────────────────────
    #
    # Ajouté le 10/09 après une leçon immédiate : la premiere version n'exercait
    # que `brain_state` et `brain_boot`, alors que la consolidation des racines
    # touchait `brain_agents`, `brain_decisions`, `brain_focus` et
    # `brain_content`. Un vert sur deux outils sur onze prouvait que le module
    # se chargeait, pas que le changement etait sans effet.
    #
    # Tous ceux-ci sont en LECTURE. Aucun outil d'ecriture n'est appele ici.
    lecture = ["brain_agents", "brain_decisions", "brain_focus", "brain_content",
               "brain_workflows", "brain_intentions"]
    muets = []
    for nom in lecture:
        f = getattr(m, nom, None)
        if not callable(f):
            print(f"  ❌ {nom} — absent du module", file=sys.stderr)
            return 1
        try:
            sortie = f()
        except Exception as exc:                               # noqa: BLE001
            print(f"  ❌ {nom} a levé : {type(exc).__name__} — {exc}", file=sys.stderr)
            return 1
        n = len(sortie or "")
        if n == 0:
            muets.append(nom)
        print(f"  {'✅' if n else '⏭️ '} {nom} — {n} caractères")

    if muets:
        print(f"  ⏭️  {len(muets)} outil(s) muet(s) : {', '.join(muets)} — vide n'est "
              f"pas forcément faux (un registre peut être vide), mais ça se dit.")

    # ── 5. ce que le slot retiré ne doit plus produire ──────────────────────
    if "now.md" in (boot or ""):
        print("  ❌ la sortie mentionne `now.md` — le slot retiré le 10/09 "
              "reviendrait-il ?", file=sys.stderr)
        return 1

    if not etat_ok:
        print("\n⏭️  ABSTENU — le moteur HTTP ne répond pas. `brain_boot` rend une "
              "réponse partielle et légitime ; conclure serait accuser la mauvaise "
              "chose.")
        return 0

    print(f"\n✅ la porte répond — {len(sections)} sections, et une section retirée "
          f"se voit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
