#!/usr/bin/env python3
"""Le hook `pre-commit-zone` refuse-t-il vraiment ? —.

Ce qui pourrirait en silence sans lui : **le garde qui protège les écritures
durables, éteint sans que personne le voie.**

`server.py` a ses gardes et elles sont éprouvées (`eprouver_gardes_ecriture.py`).
Le hook git, lui, n'était éprouvé par RIEN — et c'est le seul point où une
écriture devient durable, comme son propre docstring l'explique.

Mesuré le 26/09 : il s'éteignait dès qu'il n'y avait pas EXACTEMENT un claim
ouvert. Un claim de la veille resté ouvert l'a éteint pour tout le monde, et
trois écritures en zone kernel sont passées sans jugement dans la même journée.

    python3 tools/eprouver_garde_zone_hook.py --brain ~/Dev/Brain

── Comment on éprouve un hook sans toucher au vrai brain ────────────────────

On fabrique un dépôt jetable qui porte les deux fichiers que le hook LIT — un
`KERNEL.md` avec sa table de registre, un `NIVEAUX.yml` avec ses niveaux — on y
`chdir` **avant** d'importer le hook (il calcule sa racine à l'import), et on
remplace `sessions_ouvertes()` en mémoire, dans ce processus.

⚠️ **Aucune variable d'environnement de test n'a été ajoutée au hook**, et c'est
délibéré : une variable qui fabriquerait des claims serait un contournement du
garde, strictement pire que `BRAIN_ZONE_OVERRIDE` qui, lui, se voit.

── Il n'écrit rien dans le brain ────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# La table du registre, recopiee de KERNEL.md le 26/09. Fabriquee et non lue :
# le temoin doit tenir meme si la vraie table change de formulation — et s'il
# devait la lire, il mesurerait le brain au lieu de mesurer le hook.
KERNEL_MD = """# KERNEL (faux, pour le temoin)

## Session type → zone access

| Type session | Zones accessibles | Zones interdites | Notes |
|-------------|------------------|-----------------|-------|
| `work` | KERNEL (lecture) + INSTANCE | KERNEL (écriture) | Produit |
| `explore` | Toutes (lecture) | Écriture (sauf scope /audit → write-lock strict) | Reflechit |
| `pilote` | Toutes | — | Orchestre |
| `chill` | Toutes (lecture) + écriture on-demand | — | Présence |
"""

NIVEAUX_YML = """entrees:
  KERNEL.md:
    niveau: invariant
  agents/:
    niveau: programme
  workspace/:
    niveau: donnee
"""

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


def ancienne_lecture(ouverts: list[tuple[str, str]]) -> str | None:
    """La condition d'AVANT le 26/09, pour que le temoin du defaut soit reel.

        if len(r) != 1: return None

    Recopiee ici parce qu'un temoin qui ne montre pas l'ancien comportement ne
    prouve pas que le correctif corrige quelque chose.
    """
    return ouverts[0][0] if len(ouverts) == 1 else None


def faux_brain(racine: Path) -> None:
    (racine / "KERNEL.md").write_text(KERNEL_MD, encoding="utf-8")
    (racine / "NIVEAUX.yml").write_text(NIVEAUX_YML, encoding="utf-8")
    (racine / "agents").mkdir(exist_ok=True)
    (racine / "agents" / "faux-agent.md").write_text("# faux\n", encoding="utf-8")
    (racine / "workspace").mkdir(exist_ok=True)
    (racine / "workspace" / "note.md").write_text("# note\n", encoding="utf-8")
    for cmd in (["git", "init", "-q", "-b", "main"],
                ["git", "config", "user.email", "t@t"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=racine, check=True)


def stage(racine: Path, *chemins: str) -> None:
    subprocess.run(["git", "reset", "-q"], cwd=racine, check=True)
    subprocess.run(["git", "add", "-f", *chemins], cwd=racine, check=True)


def lance(hook, ouverts, racine: Path, *stages: str) -> tuple[int, str]:
    """(code de sortie, ce qui est ecrit sur stderr)."""
    stage(racine, *stages)
    hook.sessions_ouvertes = lambda: ouverts          # en memoire, ce processus
    tampon = io.StringIO()
    with contextlib.redirect_stderr(tampon):
        code = hook.main()
    return code, tampon.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", type=Path, default=Path.home() / "Dev/Brain")
    args = ap.parse_args()
    brain = args.brain.expanduser().resolve()

    print("GARDE DE ZONE (hook git) — refuse-t-elle vraiment ?\n")

    chemin_hook = brain / "scripts" / "hooks" / "pre-commit-zone"
    if not chemin_hook.is_file():
        print(f"SKIP — hook introuvable ({chemin_hook})")
        return 0

    print("── La SELECTION du type, sans base ──────────────────────────────\n")

    # On importe d'abord dans un depot jetable : le hook calcule sa racine a
    # l'import, et l'importer depuis le vrai brain le ferait lire le vrai depot.
    ancien_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="temoin-garde-zone-") as tmp:
        racine = Path(tmp)
        faux_brain(racine)
        os.chdir(racine)
        spec = importlib.util.spec_from_loader(
            "pre_commit_zone",
            importlib.machinery.SourceFileLoader("pre_commit_zone",
                                                 str(chemin_hook)))
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)

        try:
            # ── temoin negatif d'abord : sans lui, « ca refuse » ne se distingue
            #    pas de « ca refuse tout ».
            verifie("témoin négatif : un seul claim, type autorisé partout → passe",
                    lance(hook, [("pilote", "")], racine, "agents/faux-agent.md")[0], 0)

            verifie("un seul claim `work` → REFUSE une écriture kernel",
                    lance(hook, [("work", "")], racine, "agents/faux-agent.md")[0], 1)

            verifie("… et laisse passer la même session hors zone kernel",
                    lance(hook, [("work", "")], racine, "workspace/note.md")[0], 0)

            # 🔴 LE temoin du defaut reel.
            avant = ancienne_lecture([("work", "a"), ("work", "b")])
            verifie("l'ancienne lecture s'abstenait sur DEUX claims de même type",
                    avant, None)
            code, sortie = lance(hook, [("work", "a"), ("work", "b")], racine,
                                 "agents/faux-agent.md")
            verifie("… la nouvelle REFUSE — deux `work` portent la même règle",
                    code, 1)
            verifie("… et son refus nomme le type, pas l'ambiguïté",
                    "une session `work` n'écrit pas ici" in sortie, True)

            # Types divergents : on n'invente pas un refus, mais on ne se tait plus.
            code, sortie = lance(hook, [("work", ""), ("pilote", "")], racine,
                                 "agents/faux-agent.md")
            verifie("types divergents → ne refuse PAS (un refus faux se contourne)",
                    code, 0)
            verifie("… mais AVERTIT, en nommant le type qui l'interdirait",
                    "une session `work` n'écrirait PAS ici" in sortie, True)
            verifie("… et l'avertissement cite MY" "-139",
                    "[MY" "-139]" in sortie, True)

            code, sortie = lance(hook, [("pilote", ""), ("chill", "")], racine,
                                 "agents/faux-agent.md")
            verifie("types divergents mais AUCUN ne l'interdit → silencieux",
                    (code, sortie.strip()), (0, ""))
            # 🔴 Ce temoin dit que `chill` est bien JUGE et non « non mesurable » :
            # sans lui, le test ci-dessus passait la ou la chose ne pouvait pas
            # echouer — `chill` etait absent de la table fabriquee.
            verifie("… et `chill` est bien au registre, donc réellement jugé",
                    hook.juge_un_type("chill", "", ["agents/faux-agent.md"],
                                      hook.registre())[0], "ok")

            # ── Le scope, et le choix restrictif que fait `a_juger` ───────────
            #
            # `explore` interdit TOUTE ecriture « sauf scope /audit ». Deux
            # sessions `explore` dont une seule est en audit : le scope est vide,
            # donc l'exception NE s'applique PAS. C'est le seul endroit ou le
            # correctif choisit la lecture la moins permissive, et sans ce temoin
            # rien ne le prouverait.
            verifie("deux `explore`, une seule en /audit → l'exception NE joue pas",
                    lance(hook, [("explore", "audit"), ("explore", "brain")],
                          racine, "workspace/note.md")[0], 1)
            verifie("… les deux en /audit → l'exception joue, et ça passe",
                    lance(hook, [("explore", "audit"), ("explore", "audit")],
                          racine, "workspace/note.md")[0], 0)
            verifie("… un seul `explore` hors audit refuse tout, meme hors kernel",
                    lance(hook, [("explore", "brain")], racine,
                          "workspace/note.md")[0], 1)

            # Les deux abstentions legitimes, et elles doivent se DISTINGUER.
            code, sortie = lance(hook, [], racine, "agents/faux-agent.md")
            verifie("aucun claim → s'abstient, et dit que le boot a été sauté",
                    (code, "le boot a été sauté" in sortie), (0, True))
            code, sortie = lance(hook, None, racine, "agents/faux-agent.md")
            verifie("base injoignable → s'abstient, et le dit AUTREMENT",
                    (code, "injoignable" in sortie), (0, True))
            verifie("… « je n'ai pas pu regarder » n'est pas « aucun claim »",
                    "le boot a été sauté" in sortie, False)

            # 🔴 Trouve en relisant en JUGE, le 26/09. `type` est `NOT NULL` au
            # schema, mais NOT NULL n'interdit pas la chaine vide, et le backend
            # SQLite du replica est plus permissif. Un claim malforme faisait
            # dire « le boot a ete saute » — ce qui envoie chercher le defaut au
            # mauvais endroit.
            code, sortie = lance(hook, [("", "myeline")], racine,
                                 "agents/faux-agent.md")
            verifie("un claim au `type` VIDE : s'abstient, mais ne parle pas de boot",
                    (code, "le boot a été sauté" in sortie), (0, False))
            verifie("… et il dit que le claim existe, c'est son type qui est vide",
                    "aucun ne porte de type" in sortie, True)

            # L'echappement nomme reste ouvert.
            os.environ["BRAIN_ZONE_OVERRIDE"] = "1"
            code, sortie = lance(hook, [("work", "")], racine,
                                 "agents/faux-agent.md")
            os.environ.pop("BRAIN_ZONE_OVERRIDE")
            verifie("BRAIN_ZONE_OVERRIDE=1 lève la garde, et l'annonce",
                    (code, "levée" in sortie), (0, True))

            # ── La session DÉSIGNÉE — BRAIN-077, ─────────────────────
            #
            # Le hook herite de l'environnement de la session qui commite :
            # `CLAUDE_CODE_SESSION_ID` y designe SON claim. Plusieurs types
            # ouverts ne sont alors plus un doute. Les cas ci-dessus injectent
            # des PAIRES (type, scope) : aucun n'exercait la designation.
            #
            # La variable est FIXEE ici, puis restauree : l'outil tourne souvent
            # dans une session Claude, et en heriterait sinon.
            herite = os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            deux = [("pilote", "", "agent-pilote"), ("explore", "brain", "agent-explore")]
            # Un brain d'avant BRAIN-077 n'a pas `designe` : le DIRE, pas planter.
            verifie("le hook sait désigner la session qui commite (BRAIN-077)",
                    hasattr(hook, "designe"), True)

            if hasattr(hook, "designe"):
                os.environ["CLAUDE_CODE_SESSION_ID"] = "agent-explore"
                code, sortie = lance(hook, deux, racine, "workspace/note.md")
                verifie("une session `explore` DÉSIGNÉE parmi deux types → REFUSE",
                        code, 1)
                verifie("… et le refus nomme son type, pas l'ambiguïté",
                        ("une session `explore` n'écrit pas ici" in sortie,
                         "[MY" "-139]" in sortie), (True, False))

                os.environ["CLAUDE_CODE_SESSION_ID"] = "agent-pilote"
                verifie("la session `pilote` désignée, même commit → passe",
                        lance(hook, deux, racine, "workspace/note.md")[0], 0)

                # Le temoin : les MEMES claims, sans identite — l'ancien doute.
                os.environ.pop("CLAUDE_CODE_SESSION_ID")
                code, sortie = lance(hook, deux, racine, "workspace/note.md")
                verifie("témoin : mêmes claims SANS identité → ne refuse pas, avertit",
                        (code, "[MY" "-139]" in sortie), (0, True))

                # Ce qui ne designe PAS exactement un claim retombe sur l'ancien
                # jugement — ne jamais choisir a la place de l'appelant.
                os.environ["CLAUDE_CODE_SESSION_ID"] = "agent-double"
                code, sortie = lance(hook, [("pilote", "", "agent-double"),
                                            ("explore", "brain", "agent-double")],
                                     racine, "workspace/note.md")
                verifie("une identité qui porte DEUX claims → pas de désignation",
                        (code, "[MY" "-139]" in sortie), (0, True))
                os.environ["CLAUDE_CODE_SESSION_ID"] = "agent-inconnu"
                code, sortie = lance(hook, deux, racine, "workspace/note.md")
                verifie("une identité inconnue → pas de désignation",
                        (code, "[MY" "-139]" in sortie), (0, True))

                verifie("`designe` — paires d'avant : rendues telles quelles",
                        hook.designe([("work", "a"), ("pilote", "")], "x"),
                        [("work", "a"), ("pilote", "")])
                verifie("`designe` — sans identité : tous les claims, en paires",
                        hook.designe(deux, None), [("pilote", ""), ("explore", "brain")])
                verifie("`designe` — l'identité d'un seul claim : lui seul",
                        hook.designe(deux, "agent-pilote"), [("pilote", "")])

            # Restaurer ce dont l'outil a herite — hors du `if`, toujours.
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            if herite is not None:
                os.environ["CLAUDE_CODE_SESSION_ID"] = herite

            # La selection, en pur.
            verifie("`a_juger` — aucun claim",
                    hook.a_juger([]), (None, "", []))
            verifie("`a_juger` — un seul claim garde son scope",
                    hook.a_juger([("pilote", "myeline")]), ("pilote", "myeline", []))
            verifie("`a_juger` — deux mêmes types, MÊME scope : le scope suit",
                    hook.a_juger([("work", "a"), ("work", "a")]), ("work", "a", []))
            verifie("`a_juger` — deux mêmes types, scopes DIFFÉRENTS : scope vidé",
                    hook.a_juger([("work", "a"), ("work", "b")]), ("work", "", []))
            verifie("`a_juger` — types divergents : aucun type, et les deux nommés",
                    hook.a_juger([("work", ""), ("pilote", "")]),
                    (None, "", ["pilote", "work"]))
        finally:
            os.chdir(ancien_cwd)

    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    if not _ko:
        print(f"\n  ✅ le hook juge et refuse — {_ok} garanties, dont l'abstention "
              f"qui a laissé passer trois écritures kernel le 26/09")
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(main())
