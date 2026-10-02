#!/usr/bin/env python3
"""Un outil à deux chemins voit-il le même monde ? —.

`contrat/capacites.yml` déclare que deux outils MCP atteignent la donnée par
**deux mécanismes** : `http` quand le moteur répond, `disque` sinon. La fiche
Le constat est écrit depuis le 10/09 — *« ce sont trois chemins qui peuvent
diverger »* — mais personne ne l'avait mesuré.

    python3 tools/deux_chemins_meme_monde.py --brain ~/Dev/Brain

**Mesuré le 10/09 au soir, et ils divergeaient.** `brain_agents` rendait
91 agents par HTTP et **95** par le disque : le repli listait `AGENTS.md`
(l'index), `_conventions` et deux gabarits. Une session qui bootait pendant que
le moteur était arrêté pouvait donc lire « charge l'agent `_template` ».

La règle qui les écarte existait pourtant, et son commentaire dans `server.py`
disait déjà le risque : *« même règle que myeline/tools/agent_registry.py,
sinon les deux divergent »*. Elle était en **trois exemplaires**. C'est le
troisième — le repli du MCP — qui avait été oublié.

── Les deux règles, et pourquoi elles ne sont pas la même ──────────────────

**1. Convergence.** Là où les deux chemins prétendent rendre la même chose, ils
doivent la rendre. C'est le cas de `brain_agents` : une liste d'agents est une
liste d'agents, quelle que soit la route.

**2. Un repli doit s'annoncer.** `brain_focus` en repli ne rend PAS le focus :
il rend `focus.md`, un fichier qui pointe vers l'API — donc vers ce qui ne
répond pas. Exiger l'égalité là serait absurde. Ce qu'on peut exiger, c'est que
la sortie **dise** qu'elle est dégradée, pour qu'une session ne prenne pas un
pointeur pour une direction.

Un repli silencieux est le défaut mesuré partout ce jour-là : `pm2` absent
qu'aucune sortie ne signale, un verrou local qui se présente comme un verrou.

── Ce qu'il ne fait pas ────────────────────────────────────────────────────

Que des lectures, et il s'abstient si le moteur ne répond pas : sans le chemin
HTTP, il n'y a rien à comparer, et conclure reviendrait à accuser la mauvaise
chose.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Ce qu'on compare, et comment. La liste vient du contrat : toute capacité dont
# le `mecanisme` porte a la fois `disque` et `http` doit figurer ici, sinon on
# aurait deux endroits qui declarent la meme chose — le defaut que
# combat.
COMPARER_LES_NOMS = {"brain_agents"}          # regle 1 : convergence stricte
DOIT_S_ANNONCER = {                            # regle 2 : le repli se declare
    "brain_agents": ("filesystem",),
    # « repli » (2/10) : moteur éteint, `brain_focus` rend désormais le
    # dernier instantané du focus, annoncé en français ; `focus.md` reste le
    # fallback statique de dernier recours.
    "brain_focus":  ("fallback", "statique", "repli"),
}


def noms_du_tableau(texte: str) -> set[str]:
    """Les noms de la premiere colonne d'un tableau markdown."""
    out = set()
    for ligne in texte.splitlines():
        if ligne.startswith("|") and not ligne.startswith("|--") and "Nom |" not in ligne:
            morceaux = ligne.split("|")
            if len(morceaux) > 1 and morceaux[1].strip():
                out.add(morceaux[1].strip())
    return out


def capacites_a_deux_chemins(contrat: Path) -> set[str]:
    try:
        import yaml
    except ImportError:
        return set()
    d = (yaml.safe_load(contrat.read_text(encoding="utf-8")) or {}).get("capacites") or {}
    trouve = set()
    for nom, meta in d.items():
        meca = (meta or {}).get("mecanisme")
        meca = meca if isinstance(meca, list) else [meca]
        if "disque" in meca and "http" in meca:
            trouve.add((meta or {}).get("mcp") or nom)
    return trouve


def main() -> int:
    p = argparse.ArgumentParser(description="Les deux chemins d'un outil convergent-ils ?")
    p.add_argument("--brain", required=True, type=Path)
    p.add_argument("--contrat", type=Path, default=RACINE / "contrat" / "capacites.yml")
    a = p.parse_args()

    moteur = a.brain.expanduser().resolve() / "brain-engine"
    if not (moteur / "mcp_server.py").is_file():
        print("⏭️  SKIP mcp_server.py introuvable.", file=sys.stderr)
        return 0

    attendues = capacites_a_deux_chemins(a.contrat) if a.contrat.is_file() else set()
    connues = set(DOIT_S_ANNONCER)
    if attendues and attendues - connues:
        print(f"❌ le contrat déclare {len(attendues - connues)} capacité(s) à deux "
              f"chemins que ce contrôle ne sait pas éprouver : "
              f"{', '.join(sorted(attendues - connues))}\n"
              f"   → les ajouter ici, sinon leur divergence ne serait vue par "
              f"personne.", file=sys.stderr)
        return 1

    sys.path.insert(0, str(moteur))
    import urllib.request
    try:
        import mcp_server as m
    except Exception as exc:                                   # noqa: BLE001
        print(f"❌ le module ne se charge pas : {type(exc).__name__} — {exc}",
              file=sys.stderr)
        return 1

    vrai_urlopen = urllib.request.urlopen

    def par_disque(outil):
        """Force le repli en rendant le moteur injoignable, le temps d'un appel."""
        urllib.request.urlopen = lambda *x, **k: (_ for _ in ()).throw(
            OSError("moteur rendu injoignable par le contrôle"))
        try:
            return outil()
        finally:
            urllib.request.urlopen = vrai_urlopen

    echecs = 0
    for nom in sorted(DOIT_S_ANNONCER):
        outil = getattr(m, nom, None)
        if not callable(outil):
            print(f"  ❌ {nom} — absent du module", file=sys.stderr)
            echecs += 1
            continue

        par_http = outil()
        if not par_http or "Indisponible" in par_http or "indisponible" in par_http:
            print(f"  ⏭️  {nom} — le moteur ne répond pas, rien à comparer")
            continue
        repli = par_disque(outil)

        # Règle 2 — le repli s'annonce-t-il ?
        marqueurs = DOIT_S_ANNONCER[nom]
        annonce = any(mot.lower() in (repli or "").lower() for mot in marqueurs)
        print(f"  {'✅' if annonce else '❌'} {nom} — le repli s'annonce "
              f"({' ou '.join(marqueurs)})")
        if not annonce:
            print(f"     ❌ un repli qui ne se declare pas laisse croire a la "
                  f"session qu'elle lit la source.", file=sys.stderr)
            echecs += 1

        # Règle 1 — convergence, là où elle a un sens
        if nom in COMPARER_LES_NOMS:
            a_http, a_disque = noms_du_tableau(par_http), noms_du_tableau(repli)
            ecart = a_http ^ a_disque
            print(f"  {'✅' if not ecart else '❌'} {nom} — {len(a_http)} par HTTP, "
                  f"{len(a_disque)} par le disque")
            if ecart:
                seul_http = sorted(a_http - a_disque)
                seul_disque = sorted(a_disque - a_http)
                if seul_http:
                    print(f"     HTTP seul   : {', '.join(seul_http[:8])}", file=sys.stderr)
                if seul_disque:
                    print(f"     DISQUE seul : {', '.join(seul_disque[:8])}", file=sys.stderr)
                print(f"     → les deux chemins du MEME outil ne voient pas le "
                      f"meme monde. Une session qui boote moteur eteint lit "
                      f"autre chose.", file=sys.stderr)
                echecs += 1

    if echecs:
        print(f"\n❌ {echecs} écart(s) — : « trois chemins qui peuvent "
              f"diverger », et ils divergent.", file=sys.stderr)
        return 1
    print("\n✅ les deux chemins voient le même monde, et le repli se dit repli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
