#!/usr/bin/env python3
"""Tenir le backlog d'un geste — le palier a de BRAIN-079.

Une fiche coûtait six gestes, faits à la main à chaque fois : l'écrire,
régénérer l'index, le vérifier, la PR, l'issue, le rapport de clôture. Mesuré
le 29/09 : une dizaine de fiches, la même suite de commandes recopiée à chaque
fois. Trois de ces gestes sont mécaniques ; ils n'ont pas à dépendre de la
mémoire de la session. Cette commande les enchaîne — dans l'ordre qui compte :

    1. l'index suit les fiches        index_backlog.py --ecrire, puis --check
    2. une clôture porte sa preuve    cloture_backlog.py
    3. les issues suivent le backlog  backlog_issues.py --apply, puis --check

**Une clôture sans preuve arrête tout avant la forge.** `backlog_issues`
fermerait l'issue d'une fiche marquée ✅ : sans rapport de clôture (`mesuré` ·
`tenu par`), la fermeture ne se propage pas — la fiche reste à prouver, et la
commande le dit.

    python3 tools/kanban.py tenir --brain ~/Dev/Brain --projet <projet>
    python3 tools/kanban.py tenir --brain ~/Dev/Brain --a-blanc      rien n'est écrit
    python3 tools/kanban.py tenir --brain ~/Dev/Brain --sans-forge   s'arrête après 2

Sans `--projet`, la seule liste du brain ; s'il en a plusieurs, il faut la nommer.

Le palier b (BRAIN-079, étape 6) — un projet qui avance aussi sans l'humain :

    python3 tools/kanban.py resume --brain ~/Dev/Brain                 ce que dev/autonome porte
    python3 tools/kanban.py repartir --brain ~/Dev/Brain --projet X    dev/autonome repart du tronc

La forge de chaque projet se choisit par l'adresse de son dépôt (`repo:`) :
GitHub par `gh`, une autre forge déclarée dans `satellites.yml` (`forges:`) —
voir `forge.py`. En mode autonome sur GitHub, la PR s'ouvre et n'est pas
fusionnée : c'est l'humain qui fusionne.

Les règles restent dans les trois outils : celui-ci ne fait que les enchaîner.
Sortie 0 si tout suit, 1 sinon (et l'étape qui a manqué est nommée).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

OUTILS = Path(__file__).resolve().parent
sys.path.insert(0, str(OUTILS))
import forge  # noqa: E402 — la forge, choisie par l'adresse du dépôt


def lancer(outil: str, *args: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(OUTILS / outil), *args],
                       capture_output=True, text=True, timeout=600)
    return r.returncode, (r.stdout + r.stderr).strip()


def derniere(sortie: str) -> str:
    """La ligne qui dit le verdict — la dernière non vide."""
    lignes = [l.strip() for l in sortie.splitlines() if l.strip()]
    return lignes[-1][:140] if lignes else "(rien)"


def dire(ok: bool, titre: str, sortie: str, detail: bool = False) -> None:
    print(f"  {'✅' if ok else '❌'} {titre} — {derniere(sortie)}")
    if detail and not ok:
        for l in sortie.splitlines()[-12:]:
            print(f"       {l[:120]}")


def tenir(brain: Path, projet: str, a_blanc: bool, sans_forge: bool) -> int:
    b = ["--brain", str(brain)]
    print(f"\nTENIR LE BACKLOG — {projet}{' (à blanc)' if a_blanc else ''}\n")

    # 1. L'index
    if not a_blanc:
        code, sortie = lancer("index_backlog.py", *b, "--projet", projet, "--ecrire")
        if code != 0:
            dire(False, "l'index se régénère", sortie, True)
            print("\nVERDICT: l'index ne se régénère pas — rien d'autre n'est tenté")
            return 1
    code, sortie = lancer("index_backlog.py", *b, "--projet", projet, "--check")
    dire(code == 0, "l'index suit les fiches", sortie, True)
    if code != 0:
        print("\nVERDICT: l'index ne dit pas ce que disent les fiches"
              + (" — `tenir` sans --a-blanc le régénère" if a_blanc else ""))
        return 1

    # 2. La preuve des clôtures — AVANT la forge
    code, sortie = lancer("cloture_backlog.py", *b, "--projet", projet)
    dire(code == 0, "chaque clôture porte sa preuve", sortie, True)
    if code != 0:
        print("\nVERDICT: une fiche close sans preuve — arrêté AVANT la forge : "
              "aucune issue ne se ferme sur une clôture non prouvée")
        return 1

    if sans_forge:
        print("\nVERDICT: l'index et les clôtures tiennent ; la forge n'est pas touchée (--sans-forge)")
        return 0

    # 3. Les issues
    if not a_blanc:
        code, sortie = lancer("backlog_issues.py", *b, "--projet", projet, "--apply")
        if code != 0:
            dire(False, "les issues se dérivent", sortie, True)
            print("\nVERDICT: la forge a refusé — voir ci-dessus")
            return 1
    code, sortie = lancer("backlog_issues.py", *b, "--projet", projet, "--check")
    dire(code == 0, "les issues suivent le backlog", sortie, True)
    if code != 0:
        print("\nVERDICT: les issues ne disent pas ce que dit le backlog"
              + (" — `tenir` sans --a-blanc les dérive" if a_blanc else ""))
        return 1

    print("\nVERDICT: le backlog est tenu — index, clôtures et issues d'accord")
    return 0


# ── Le palier b — BRAIN-079, étape 6 ───────────────────────────────────────
#
# Un projet au palier b ou c avance aussi SANS l'humain : le travail validé par
# l'orchestrator s'empile sur `dev/autonome`, jamais sur le tronc (protégé sur
# la forge : seul l'humain y fusionne). Deux gestes :
#
#     resume     ce que `dev/autonome` porte et que le tronc n'a pas, et les PR
#                d'agents qui attendent un verdict — lu au boot (helloWorld)
#     repartir   `dev/autonome` repart du tronc après la fusion de l'humain —
#                refusé tant qu'elle porte quelque chose que le tronc n'a pas

AUTONOME = "dev/autonome"


def projets_autonomes(brain: Path) -> list:
    import _fiches
    trouves = []
    for f in sorted((brain / "projets").glob("*.md")):
        if f.name.startswith("_"):
            continue
        p = _fiches.projet(brain, f.stem)
        if p.palier in ("b", "c"):
            trouves.append(p)
    return trouves


def etat_autonome(fg, depot: str) -> dict:
    """{tronc, en_avance, titres, en_retard, attendent} — ou {absent|erreur}."""
    code, d = fg.call("GET", f"/repos/{depot}")
    if code != 200:
        return {"erreur": f"HTTP {code} en lisant {depot}"}
    tronc = d.get("default_branch") or "main"
    code, b = fg.call("GET", f"/repos/{depot}/branches/{AUTONOME}")
    if code == 404:
        return {"absent": True, "tronc": tronc}
    code, avant = fg.call("GET", f"/repos/{depot}/compare/{tronc}...{AUTONOME}")
    code2, arriere = fg.call("GET", f"/repos/{depot}/compare/{AUTONOME}...{tronc}")
    if code != 200 or code2 != 200:
        return {"erreur": f"comparaison illisible ({code}/{code2})"}
    code, prs = fg.call("GET", f"/repos/{depot}/pulls?state=open&limit=50")
    attendent = [f"#{x['number']} {x['title']}" for x in (prs or [])
                 if (x.get("base") or {}).get("ref") == AUTONOME] if code == 200 else []
    titres = [(c.get("commit") or {}).get("message", "").splitlines()[0]
              for c in (avant.get("commits") or [])]
    return {"tronc": tronc, "en_avance": avant.get("total_commits", 0),
            "titres": [x for x in titres if x.startswith("Merge pull request")] or titres,
            "en_retard": arriere.get("total_commits", 0), "attendent": attendent}


def collecter(brain: Path, fg=None) -> dict:
    """Le résumé du palier b, en DONNÉES : `{"projets": [...], "note": ...}`.

    Chaque projet porte un `etat` : `ok`, `absent` (pas de `dev/autonome`),
    `sans-repo`, `erreur` ou `injoignable`. C'est ce que `resume` affiche, et ce
    que le moteur sert sur `/workflows` : les « workflows actifs », ce sont les
    passes du palier c (décision de l'owner, 30/09).

    Chaque projet a SA forge, choisie par son adresse ; `fg` (une fausse forge)
    les remplace toutes, pour l'épreuve."""
    projets = projets_autonomes(brain)
    if not projets:
        return {"projets": [], "note": "aucun projet au palier b ou c"}
    rendu = []
    for p in projets:
        base = {"projet": p.slug, "palier": p.palier, "depot": p.depot}
        if not p.depot:
            rendu.append({**base, "etat": "sans-repo"})
            continue
        try:
            sa_forge = fg or forge.pour(p.adresse_depot, brain)
        except forge.ForgeRefus as exc:
            rendu.append({**base, "etat": "erreur", "message": str(exc)})
            continue
        try:
            e = etat_autonome(sa_forge, p.depot)
        except BaseException as exc:                          # noqa: BLE001
            rendu.append({**base, "etat": "injoignable", "message": type(exc).__name__})
            continue
        if "erreur" in e:
            rendu.append({**base, "etat": "erreur", "message": e["erreur"]})
        elif e.get("absent"):
            rendu.append({**base, "etat": "absent", "tronc": e.get("tronc")})
        else:
            rendu.append({**base, "etat": "ok", "tronc": e["tronc"],
                          "en_avance": e["en_avance"], "en_retard": e["en_retard"],
                          "titres": e["titres"][:6], "attendent": e["attendent"][:6]})
    return {"projets": rendu, "note": None}


def resume(brain: Path, en_json: bool = False, fg=None) -> int:
    donnees = collecter(brain, fg)
    if en_json:
        print(json.dumps(donnees, ensure_ascii=False))
        return 0
    print("\nPALIER B — ce qui a avancé sans toi\n")
    if donnees["note"]:
        print(f"  {donnees['note']} — rien à résumer")
        return 0
    for p in donnees["projets"]:
        tete = f"  {p['projet']:<14} palier {p['palier']}"
        if p["etat"] == "sans-repo":
            print(f"{tete} — pas de `repo:`, rien à lire")
        elif p["etat"] in ("erreur", "injoignable"):
            print(f"{tete} — {p['message']}")
        elif p["etat"] == "absent":
            print(f"{tete} — pas de `{AUTONOME}` sur {p['depot']}")
        else:
            ligne = (f"{tete} — `{AUTONOME}` : {p['en_avance']} commit(s) que "
                     f"`{p['tronc']}` n'a pas")
            if p["en_avance"] == 0 and p["en_retard"] > 0:
                ligne += (f" ; en retard de {p['en_retard']} → "
                          f"`kanban.py repartir --projet {p['projet']}`")
            print(ligne)
            for x in p["titres"]:
                print(f"       · {x[:90]}")
            for x in p["attendent"]:
                print(f"       ⏳ attend un verdict : {x[:80]}")
            if p["en_avance"]:
                print(f"       → à relire d'un bloc : une PR `{AUTONOME}` → `{p['tronc']}`")
    return 0


def repartir(brain: Path, projet: str, a_blanc: bool, fg=None) -> int:
    """`dev/autonome` repart du tronc — seulement si le tronc a TOUT ce qu'elle porte."""
    import _fiches
    if not (brain / "projets" / f"{projet}.md").is_file():
        print(f"  ❌ pas de fiche projets/{projet}.md")
        return 1
    p = _fiches.projet(brain, projet)
    if p.palier not in ("b", "c"):
        print(f"  ❌ {projet} est au palier {p.palier} — pas de `{AUTONOME}`")
        return 1
    if not p.depot:
        print(f"  ❌ {projet} ne déclare pas de `repo:`")
        return 1
    try:
        fg = fg or forge.pour(p.adresse_depot, brain)
    except forge.ForgeRefus as exc:
        print(f"  ❌ {exc}")
        return 1
    e = etat_autonome(fg, p.depot)
    if "erreur" in e:
        print(f"  ❌ {e['erreur']}")
        return 1
    if e.get("absent"):
        print(f"  ❌ pas de `{AUTONOME}` sur {p.depot}")
        return 1
    if e["en_avance"]:
        print(f"  ❌ `{AUTONOME}` porte {e['en_avance']} commit(s) que `{e['tronc']}` n'a pas "
              f"— la PR de l'humain d'abord. Rien n'est touché.")
        return 1
    if not e["en_retard"]:
        print(f"  ✅ `{AUTONOME}` est déjà au niveau de `{e['tronc']}`")
        return 0
    if a_blanc:
        print(f"  · `{AUTONOME}` repartirait de `{e['tronc']}` (en retard de {e['en_retard']}) — à blanc")
        return 0
    # `dev/autonome` est PROTÉGÉE (29/09) : personne n'y pousse, rien ne la
    # supprime — la première version (supprimer, recréer) reçoit « 403 branch
    # protected ». Elle rejoint le tronc par la seule porte qu'elle a : une PR
    # `tronc → dev/autonome`, fusionnée en AVANCE RAPIDE SEULE — la branche
    # pointe alors exactement le commit du tronc, sans commit de fusion. Si
    # l'avance rapide est impossible (ce qu'on a vérifié ne pas être), la forge
    # refuse et rien ne bouge.
    code, pr = fg.call("POST", f"/repos/{p.depot}/pulls",
                       {"head": e["tronc"], "base": AUTONOME,
                        "title": f"{AUTONOME} repart de {e['tronc']} (kanban.py repartir)",
                        "body": "Avance rapide seule — le tronc porte tout ce que "
                                f"`{AUTONOME}` portait (vérifié avant d'ouvrir)."})
    if code != 201 or not (pr or {}).get("number"):
        print(f"  ❌ la PR `{e['tronc']}` → `{AUTONOME}` n'a pas pu s'ouvrir (HTTP {code}) — rien n'a changé")
        return 1
    code, rep = fg.call("POST", f"/repos/{p.depot}/pulls/{pr['number']}/merge",
                        {"Do": "fast-forward-only", "delete_branch_after_merge": False})
    if code >= 300:
        raison = (rep or {}).get("message") if isinstance(rep, dict) else None
        # Le mode autonome sur GitHub ne fusionne pas : la PR reste ouverte, pour
        # l'humain — la refermer effacerait ce qu'on vient de lui préparer.
        if isinstance(rep, dict) and rep.get("refus_autonome"):
            print(f"  ⏳ {raison} — `{AUTONOME}` n'a pas bougé (PR #{pr['number']})")
            return 1
        fg.call("PATCH", f"/repos/{p.depot}/pulls/{pr['number']}", {"state": "closed"})
        print(f"  ❌ avance rapide refusée (HTTP {code}{' : ' + raison if raison else ''}) "
              f"— PR #{pr['number']} refermée, rien n'a changé")
        return 1
    print(f"  ✅ `{AUTONOME}` repart de `{e['tronc']}` (avance rapide, PR #{pr['number']})")
    return 0


class _FausseForge:
    def __init__(self, reponses: dict):
        self.reponses, self.ecrit = reponses, []

    def call(self, methode, chemin, corps=None):
        if methode != "GET":
            self.ecrit.append((methode, chemin))
            if methode == "DELETE":
                return (204, None)
            if chemin.endswith("/merge"):
                return (200, None)
            return (201, {"number": 1})
        for motif, rep in self.reponses.items():
            if motif in chemin:
                return rep
        return (404, None)


def auto_epreuve(brain: Path) -> list[str]:
    """`repartir` refuse ce qu'il doit refuser — contre une fausse forge."""
    import contextlib
    import io
    rates = []
    with contextlib.redirect_stdout(io.StringIO()):
        _epreuves(rates)
    return rates


def _epreuves(rates: list) -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="kanban-repartir-") as tmp:
        b = Path(tmp)
        (b / "projets").mkdir()
        (b / "projets" / "p.md").write_text("---\npalier: b\nrepo: forge.x/o/p\n---\n", encoding="utf-8")
        base = {"/repos/o/p/branches/": (200, {}), "/repos/o/p/pulls": (200, [])}
        def cas(avance, retard):
            r = dict(base)
            r["/repos/o/p/compare/main...dev"] = (200, {"total_commits": avance, "commits": []})
            r["/repos/o/p/compare/dev/autonome...main"] = (200, {"total_commits": retard, "commits": []})
            r["/repos/o/p"] = (200, {"default_branch": "main"})
            return _FausseForge(r)
        fg = cas(2, 1)
        if repartir(b, "p", False, fg) != 1 or fg.ecrit:
            rates.append("une dev/autonome en avance est touchée")
        fg = cas(0, 3)
        if repartir(b, "p", False, fg) != 0 or len(fg.ecrit) != 2:
            rates.append("une dev/autonome fusionnée ne repart pas")
        elif any(m == "DELETE" for m, _ in fg.ecrit):
            rates.append("repartir supprime la branche — elle est protégée")
        elif not any(c.endswith("/merge") for _, c in fg.ecrit):
            rates.append("repartir ne passe pas par une fusion en avance rapide")
        fg = cas(0, 3)
        if repartir(b, "p", True, fg) != 0 or fg.ecrit:
            rates.append("à blanc écrit")
        d = collecter(b, cas(2, 0))
        if not (d["note"] is None and len(d["projets"]) == 1
                and d["projets"][0]["etat"] == "ok" and d["projets"][0]["en_avance"] == 2):
            rates.append("le résumé en données ne dit pas ce que dit la forge")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="commande", required=True)
    t = sous.add_parser("tenir", help="index, clôtures, issues — d'un geste")
    t.add_argument("--brain", type=Path, required=True)
    t.add_argument("--projet", default=None, help="la liste à tenir — sans lui, la seule du brain")
    t.add_argument("--a-blanc", action="store_true", help="n'écrit rien : dit ce qui ne suit pas")
    t.add_argument("--sans-forge", action="store_true", help="s'arrête avant les issues")
    r = sous.add_parser("resume", help="palier b : ce qui a avancé sans l'humain")
    r.add_argument("--brain", type=Path, required=True)
    r.add_argument("--json", action="store_true", help="les données, pour le moteur (/workflows)")
    rp = sous.add_parser("repartir", help="palier b : dev/autonome repart du tronc")
    rp.add_argument("--brain", type=Path, required=True)
    rp.add_argument("--projet", required=True)
    rp.add_argument("--a-blanc", action="store_true")
    a = p.parse_args()
    brain = a.brain.expanduser().resolve()
    if a.commande == "resume":
        return resume(brain, a.json)
    if a.commande == "repartir":
        rates = auto_epreuve(brain)
        if rates:
            for x in rates:
                print(f"  ❌ auto-épreuve : {x}")
            return 1
        return repartir(brain, a.projet, a.a_blanc)
    if a.projet is None:
        import _fiches
        try:
            a.projet = _fiches.projet_par_defaut(brain)
        except _fiches.Illisible as exc:
            print(f"  ❌ {exc}")
            return 1
    if not (brain / "workspace" / "backlog" / a.projet).is_dir():
        print(f"SKIP pas de backlog `{a.projet}` dans {brain} — rien à tenir")
        return 0
    return tenir(brain, a.projet, a.a_blanc, a.sans_forge)


if __name__ == "__main__":
    sys.exit(main())
