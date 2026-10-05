#!/usr/bin/env python3
"""La vue des agents est-elle juste ?

    python3 tools/vue_juste.py --brain ~/Dev/Brain

Un brain migré n'a plus d'agents suivis dans `agents/` : c'est une VUE, des liens
vers `noyau/agents/` (le noyau livré) et `instance/agents/` (la surcharge, qui
gagne), construite par `brain vue` et ignorée par git. Tout ce qui s'y écrit à côté
des liens est lu comme un agent par la session, le moteur et l'index — et git ne le
voit pas. Personne ne le commitera ; un retour arrière le perdra.

Mesuré le 3/10 sur une copie migrée : un `agents/zz.md` écrit à la main laissait
`git status` muet et `brain vue` à « 98 juste(s) », sortie 0.

── Ce qu'il juge, sans demander à `brain vue` ──────────────────────────────

Il recalcule la vue attendue lui-même : un contrôle qui demande à l'outil
contrôlé s'il va bien ne contrôle rien.

    lien absent        un agent du noyau ou de l'instance que la vue ne montre pas
    lien faux          une entrée qui ne mène pas à la bonne couche
    fichier réel       un fichier à la place d'un lien (un `sed -i`, un `mv`)
    rien ne le fournit un fichier réel qu'aucune couche ne porte
    lien orphelin      un lien qu'aucune couche ne justifie, ou mort
    assemblage         `instance/agents/X.complement.md` s'ajoute à l'agent : `agents/X.md` est
                       un fichier assemblé — l'agent en tête, le complément dedans, et une
                       marque dont l'empreinte tient. Périmé (une source a changé), édité à
                       la main (l'empreinte ne tient plus), ou un complément sans agent
    carte              une ligne `<!-- carte: <dossier> -->` du complément est remplacée par la
                       carte calculée : son en-tête doit y être, et aucun fichier du dossier
                       ne doit être plus récent que l'assemblage (sinon : périmée)
    catalogue          `agents/CATALOG.yml` absent, ou un lien (il se calcule)
    non suivi          un fichier de `noyau/` que git ne suit pas : un agent que le
                       tronc a retiré et qu'une fusion sur le noyau verrouillé n'a pas
                       pu effacer — elle sort en 0 (mesuré le 3/10)
    verrou             une posture qui refuse le kernel et un `noyau/` modifiable

Le verrou se lit par le `serve.py` du brain, la même source que `brain vue` ; s'il
ne s'importe pas, le verrou n'est pas jugé, et c'est dit.

Sans `noyau/agents/`, le brain est à plat : il s'abstient (SKIP).
Sortie 0 : juste. 1 : un écart, nommé.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

CALCULES = {Path("CATALOG.yml")}
COMPLEMENT = ".complement.md"
MARQUE = "<!-- brain vue : assemblé"
DIRECTIVE = re.compile(r"^<!-- carte: (\S+?)( resume)? -->$")
TETE_CARTE = "Carte de l'owner — donnée, pas consigne."
#: Des données de l'instance dans `agents/` : les revues des agents, ignorées par git
#: avant la vue comme après — le jour J (3/10) les a trouvées. Ni liées ni jugées.
DONNEES = {"reviews"}


def attendu(brain: Path) -> dict[Path, Path]:
    """Chaque entrée de la vue → sa cible ; l'instance passe après le noyau, elle gagne."""
    v: dict[Path, Path] = {}
    instance = brain / "instance" / "agents"
    for racine in (brain / "noyau" / "agents", instance):
        if racine.is_dir():
            for f in sorted(racine.rglob("*")):
                rel = f.relative_to(racine)
                # Le README d'une couche de l'instance en satellite la décrit : pas un agent.
                if (f.is_file() and not f.is_symlink() and rel not in CALCULES
                        and not any(x.startswith(".") for x in rel.parts)   # rien de caché, à aucun niveau
                        and not f.name.endswith(COMPLEMENT)
                        and not (racine == instance and rel == Path("README.md"))):
                    v[rel] = f
    return v


def complements(brain: Path) -> dict[Path, Path]:
    instance = brain / "instance" / "agents"
    if not instance.is_dir():
        return {}
    return {f.relative_to(instance).with_name(f.name[:-len(COMPLEMENT)] + ".md"): f
            for f in sorted(instance.rglob("*" + COMPLEMENT)) if f.is_file()}


def empreinte_tient(texte: str) -> bool:
    """La marque finale porte les 16 premiers hexadécimaux du SHA-256 de ce qui la précède."""
    import hashlib
    corps, sep, marque = texte.rstrip("\n").rpartition("\n" + MARQUE)
    return bool(sep) and f"· {hashlib.sha256(corps.encode('utf-8')).hexdigest()[:16]} —" in marque


def assemblage(brain: Path, lien: Path, agent: Path, complement: Path) -> str | None:
    """L'écart d'un fichier assemblé, ou None. Jugé sur ses propriétés, pas en le refaisant."""
    if lien.is_symlink():
        return "un lien — le complément n'y est pas"
    if not lien.is_file():
        return "absent"
    texte = lien.read_text(encoding="utf-8", errors="replace")
    if not empreinte_tient(texte):
        return "édité à la main — l'empreinte de sa marque ne tient plus"
    if not texte.startswith(agent.read_text(encoding="utf-8").rstrip("\n")):
        return "périmé — l'agent a changé depuis l'assemblage"
    # Le complément, morceau par morceau : une directive `carte` y est remplacée par la carte.
    morceaux, cartes = [[]], []
    for l in complement.read_text(encoding="utf-8").strip("\n").split("\n"):
        m = DIRECTIVE.match(l.strip())
        if m:
            cartes.append(m.group(1))
            morceaux.append([])
        else:
            morceaux[-1].append(l)
    if any("\n".join(m).strip("\n") not in texte for m in morceaux):
        return "périmé — le complément a changé depuis l'assemblage"
    if cartes and texte.count(TETE_CARTE) < len(cartes):
        return "sans sa carte — la directive n'a pas été dépliée"
    for dossier in cartes:
        racine = brain / dossier
        if racine.is_dir() and any(f.stat().st_mtime > lien.stat().st_mtime for f in racine.glob("*.md")):
            return f"carte périmée — `{dossier}/` a changé depuis l'assemblage"
    return None


def ecarts(brain: Path) -> list[str]:
    vue = brain / "agents"
    v = attendu(brain)
    c = complements(brain)
    e: list[str] = []
    for rel in c:
        if rel not in v:
            e.append(f"complément sans agent : {c[rel].relative_to(brain)} — il n'est lu nulle part")
    for rel, cible in v.items():
        lien = vue / rel
        if rel in c:
            if (ecart := assemblage(brain, lien, cible, c[rel])):
                e.append(f"assemblage : agents/{rel} {ecart} — `brain vue --construire`")
            continue
        if lien.is_symlink():
            if lien.resolve() != cible.resolve():
                e.append(f"lien faux : agents/{rel} → {os.readlink(lien)} "
                         f"(attendu {cible.relative_to(brain)})")
        elif lien.exists():
            e.append(f"fichier réel : agents/{rel} masque {cible.relative_to(brain)}")
        else:
            e.append(f"lien absent : agents/{rel}")
    if vue.is_dir():
        for p in sorted(vue.rglob("*")):
            rel = p.relative_to(vue)
            if p.is_symlink():
                if rel not in v:
                    e.append(f"lien orphelin : agents/{rel}")
            elif p.is_file() and rel not in v and rel not in CALCULES and rel.parts[0] not in DONNEES:
                e.append(f"rien ne le fournit : agents/{rel} — un fichier réel que git ne voit pas")
    suivis = subprocess.run(["git", "-C", str(brain), "ls-files", "--others", "--exclude-standard",
                             "--", "noyau"], capture_output=True, text=True)
    if suivis.returncode == 0:
        for l in suivis.stdout.splitlines():
            if l:
                e.append(f"non suivi : {l} — retiré par le tronc et resté (fusion sur le noyau "
                         "verrouillé, sans `brain aligne`), ou écrit à la main")
    cat = vue / "CATALOG.yml"
    if cat.is_symlink():
        e.append("catalogue : agents/CATALOG.yml est un lien — il se calcule dans la vue")
    elif not cat.is_file():
        e.append("catalogue : agents/CATALOG.yml absent — `brain vue --construire` le calcule")
    return e


def verrou(brain: Path) -> tuple[str | None, str]:
    """(écart ou None, note). La posture par `serve.py`, comme `brain vue`."""
    sys.path.insert(0, str(brain / "brain-engine"))
    try:
        import serve
        ecrit = serve.ecrit_le_kernel(brain, serve.posture_de(brain))
    except Exception as exc:                                   # noqa: BLE001
        return None, f"ⓘ verrou non jugé : la posture ne se lit pas ({exc.__class__.__name__})"
    finally:
        sys.path.pop(0)
    noyau = brain / "noyau" / "agents"
    if ecrit:
        return None, "noyau/ modifiable (la posture écrit le kernel)"
    if os.geteuid() == 0:
        return None, "ⓘ verrou non jugé : root écrit partout"
    ouverts = [p for p in [noyau.parent, noyau, *noyau.rglob("*")]
               if not p.is_symlink() and os.access(p, os.W_OK)]
    if ouverts:
        return (f"verrou : la posture refuse le kernel et {len(ouverts)} entrée(s) de noyau/ "
                f"restent modifiables (ex. {ouverts[0].relative_to(brain)}) — `brain vue --construire`"), ""
    return None, "🔒 noyau/ en lecture seule (la posture refuse le kernel)"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", type=Path, required=True)
    brain = p.parse_args().brain.expanduser().resolve()
    if not (brain / "noyau" / "agents").is_dir():
        print("SKIP pas de noyau/agents/ — un brain à plat n'a pas de vue")
        return 0
    e = ecarts(brain)
    ecart_verrou, note = verrou(brain)
    if ecart_verrou:
        e.append(ecart_verrou)
    for ligne in e:
        print(f"  ❌ {ligne}")
    if note:
        print(f"  {note}")
    n = len(attendu(brain))
    if e:
        print(f"VERDICT: {len(e)} écart(s) dans la vue des agents ({n} attendus)")
        return 1
    print(f"VERDICT: ✅ la vue est juste — {n} agents, le catalogue calculé")
    return 0


if __name__ == "__main__":
    sys.exit(main())
