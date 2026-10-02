#!/usr/bin/env python3
"""Le test de la fondation — retirer une brique casse-t-il le CORE ?

    python3 core/test_briques.py

La vision de Myéline pose la règle : *« retirer n'importe quelle brique doit
laisser un système qui démarre, indexe, cherche, écrit et trace. Si retirer une
brique casse le core, la frontière est mal placée — on la corrige avant d'en
poser une autre. »*

Ce test l'applique au CORE lui-même. Il ne vérifie pas que le code est juste —
les six autres fichiers de test s'en chargent — mais que **les frontières sont
au bon endroit**.

── Comment on mesure une frontière ─────────────────────────────────────────

Un module est *retirable* si le CORE tourne sans lui. On le vérifie en
l'important seul dans un interpréteur neuf : ce qu'il tire avec lui est sa
dépendance réelle, pas celle qu'on croit avoir écrite.

`persistance` est le socle **par construction** — tout accès aux données passe
par lui, et c'est la seule dépendance qu'on accepte de tous. Toute autre
dépendance entre briques est un couplage à justifier ou à défaire.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BRIQUES = ["persistance", "modele", "traces", "bsi",
           "recherche", "indexation", "zones"]

# Le SOCLE n'est pas un module, c'est un ENSEMBLE : les ponts vers l'extérieur.
# `persistance` mène à la base, `modele` au modèle d'embedding. Aucun des deux ne
# dépend de quoi que ce soit, et toutes les autres briques ont le droit de s'y
# appuyer — c'est leur raison d'être.
#
# Ce que la règle interdit, c'est qu'une brique MÉTIER en tienne une autre : le
# jour où l'on retire l'une, l'autre tombe. C'est ce que le premier passage a
# trouvé — `indexation` tenait `recherche` pour un encodeur qui n'appartenait à
# aucune des deux.
SOCLE = {"persistance", "modele"}

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def tirees_par(brique: str) -> set[str]:
    """Les briques du CORE qu'un import de `brique` charge réellement.

    Dans un interpréteur neuf : ce qui est en mémoire après l'import est ce que
    la brique tire, quelle que soit l'intention du fichier.
    """
    code = (f"import core.{brique}, sys; "
            "print(' '.join(sorted(m.split('.')[1] for m in sys.modules "
            "if m.startswith('core.') and m.count('.') == 1)))")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(RACINE),
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        return {f"ERREUR:{r.stderr.strip().splitlines()[-1][:50]}"}
    return set(r.stdout.split()) - {brique}


# Les tables SYSTÈME ne sont possédées par personne : elles existent sans qu'un
# schéma les crée. Les compter comme des tables de brique ferait rougir des
# déclarations parfaitement justes.
SYSTEME = {"information_schema", "sqlite_master", "dolt_status", "dolt_log",
           "sqlite_sequence", "pragma_table_info"}

# `DO UPDATE SET` : le motif capturait « set » comme nom de table. Un mot
# réservé n'est jamais une table — et l'oublier fait rougir une déclaration
# juste.
RESERVES = {"set", "select", "where", "values", "key", "table", "into", "from"}

TABLE_SQL = re.compile(
    r"\b(?:FROM|INTO|UPDATE|JOIN)\s+`?([a-z_][a-z0-9_]*)`?", re.IGNORECASE)

# Les méthodes par lesquelles une requête part vers la base.
PORTES = {"query", "query_one", "execute", "count", "table_existe"}


def tables_citees(brique: str) -> set[str]:
    """Les tables qu'un module interroge, lues dans l'ARBRE de son source.

    ⚠️ **Trois regex successives ont échoué avant celle-ci**, et c'est
    l'enseignement. Chercher `FROM x` dans le texte ramassait
    `from dataclasses import` ; le filtrer par verbe SQL ratait les f-strings
    coupées en deux ; l'ancrer en début de chaîne remontait les imports cités
    dans les docstrings.

    L'arbre syntaxique ne se trompe pas : on ne regarde que les chaînes passées
    en argument à `query`, `execute` et leurs semblables. Une docstring n'est
    jamais un argument d'appel.

    Après trois réglages ratés, changer d'instrument vaut mieux qu'un quatrième.
    """
    src = (Path(__file__).resolve().parent / f"{brique}.py").read_text(encoding="utf-8")
    trouvees: set[str] = set()

    def morceaux(noeud) -> list[str]:
        """Les chaînes d'un argument, f-strings et concaténations comprises."""
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            return [noeud.value]
        if isinstance(noeud, ast.JoinedStr):
            return [v.value for v in noeud.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        if isinstance(noeud, ast.BinOp):
            return morceaux(noeud.left) + morceaux(noeud.right)
        return []

    for noeud in ast.walk(ast.parse(src)):
        if not isinstance(noeud, ast.Call):
            continue
        nom = (noeud.func.attr if isinstance(noeud.func, ast.Attribute)
               else getattr(noeud.func, "id", ""))
        if nom not in PORTES:
            continue
        for arg in noeud.args:
            for texte in morceaux(arg):
                trouvees |= {m.lower() for m in TABLE_SQL.findall(texte)}
        # `count("embeddings")` nomme la table directement.
        if nom in ("count", "table_existe") and noeud.args:
            for texte in morceaux(noeud.args[0]):
                if texte.isidentifier():
                    trouvees.add(texte.lower())

    return trouvees - SYSTEME - RESERVES


# Un `CREATE TABLE` où qu'il soit : dans un schéma, ou en dur dans le code.
CREATEUR = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([a-z_][a-z0-9_]*)`?",
    re.IGNORECASE)


# Ce qui PART chez un fork. Un dump de sauvegarde contient tous les
# `CREATE TABLE` du monde et n'installe rien chez personne.
LIVRE = ("brain-engine", "brain-template", "brain-dolt", "scripts")


def createurs(brain: Path) -> dict[str, list[str]]:
    """Qui crée quelle table **dans ce qui est livré** — schémas et code.

    ⚠️ **Deux contrôles évidents auraient été faux, dans les deux sens.**

    Comparer les TABLES au seul `schema.sql` faisait rougir `embeddings`,
    absente du schéma du template mais créée à la volée par `embed.py`. Un
    rouge sur une chose qui marche ne protège plus rien.

    Puis chercher `CREATE TABLE` dans *tout* le brain a rendu 94 sources pour
    `claims` — dont la première était `brain-db-backup/brain-2026-08-11.sql`.
    Un dump de sauvegarde n'installe rien chez personne. Le vert était acquis
    d'avance, et **un contrôle qui ne peut pas rougir ne mesure rien**.

    D'où `LIVRE` : on ne regarde que ce qui part. Ce qu'on veut savoir n'est
    pas « la chaîne existe-t-elle quelque part » mais **« le fork obtient-il
    cette table »** — un défaut qu'aucune instance ne peut voir sur elle-même,
    puisque chez elle la table est déjà là.
    """
    trouves: dict[str, list[str]] = {}
    for coin in LIVRE:
        racine = brain / coin
        if not racine.is_dir():
            continue
        for f in list(racine.rglob("*.sql")) + list(racine.rglob("*.py")):
            if any(p in f.parts for p in (".git", "node_modules", "__pycache__")):
                continue
            try:
                texte = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for table in CREATEUR.findall(texte):
                trouves.setdefault(table.lower(), []).append(
                    str(f.relative_to(brain)))
    return trouves


# Ce qui fait qu'un programme devine où vivent les données au lieu de le
# recevoir. `Path.home()` et `expanduser` fabriquent un chemin depuis
# l'utilisateur courant ; `getenv`/`environ` depuis son environnement.
DEVINETTES = {"home", "expanduser", "getenv", "environ", "cwd", "getcwd"}


def chemins_devines(brique: str) -> set[str]:
    """Les appels par lesquels un module DEVINERAIT où sont les données.

    ⚠️ Ce contrôle vient d'un incident voisin, pas d'une idée. Le 09/10/09, la
    session régie a trouvé que `cargo test` écrivait dans le `~/.config` réel
    de l'owner — trois fois, dont un `impl Default` qui rouvrait un vrai tirage à
    chaque exécution des tests. Un bug qu'il avait signalé comme un défaut
    produit le 14/08 venait de la suite de tests.

    Le CORE ne peut pas connaître ce défaut : il reçoit sa `Config`, il ne la
    déduit jamais. Mais **rien ne le garantissait**, et l'ancien `db.py` faisait
    exactement l'inverse — `BRAIN_ROOT = Path(__file__).parent.parent`, un
    programme qui déduit où vivent les données de sa position sur le disque.

    Mesuré avant d'écrire ce contrôle : zéro devinette dans les sept briques, et
    zéro fichier touché chez l'utilisateur par la suite de tests (579 321
    fichiers relevés avant/après, 13 modifiés, tous appartenant à Spotify qui
    tournait en fond).

    On mesure la **cause** — deviner un chemin — plutôt que le symptôme, qui
    demanderait de relever tout le disque à chaque exécution.
    """
    src = (Path(__file__).resolve().parent / f"{brique}.py").read_text(encoding="utf-8")
    trouves: set[str] = set()
    for noeud in ast.walk(ast.parse(src)):
        if isinstance(noeud, ast.Call):
            nom = (noeud.func.attr if isinstance(noeud.func, ast.Attribute)
                   else getattr(noeud.func, "id", ""))
            if nom in DEVINETTES:
                trouves.add(f"{nom}()")
        elif isinstance(noeud, ast.Attribute) and noeud.attr == "environ":
            trouves.add("environ")
    return trouves


def main() -> int:
    print("\nLE TEST DE LA FONDATION — où sont les frontières ?\n")

    carte: dict[str, set[str]] = {}
    for brique in BRIQUES:
        carte[brique] = tirees_par(brique)
        tire = ", ".join(sorted(carte[brique])) or "—"
        print(f"     {brique:<14} tire : {tire}")

    print()
    for pont in sorted(SOCLE):
        verifie(f"le pont « {pont} » ne dépend de rien", carte[pont], set())

    # Chaque brique doit pouvoir vivre avec le socle SEUL. Tirer une autre
    # brique est un couplage : le CORE ne tourne alors plus sans elle.
    for brique in BRIQUES:
        if brique in SOCLE:
            continue
        verifie(f"« {brique} » ne tire que le socle",
                carte[brique] - SOCLE, set())

    # Une brique qu'aucune autre ne tire est retirable : la retirer laisse le
    # reste debout. C'est la propriété que la vision demande.
    print()
    for brique in BRIQUES:
        if brique in SOCLE:
            continue
        tirent = [b for b in BRIQUES if brique in carte[b]]
        etat = "retirable" if not tirent else f"⚠️ tenue par {', '.join(tirent)}"
        print(f"     {brique:<14} {etat}")

    # ── Chaque brique sait-elle ses tables ? — ─────────────────
    print("\n  CE QUE CHAQUE BRIQUE POSSÈDE\n")
    import importlib
    sys.path.insert(0, str(RACINE))
    for brique in BRIQUES:
        mod = importlib.import_module(f"core.{brique}")
        declarees = set(getattr(mod, "TABLES", set()))
        citees = tables_citees(brique)
        print(f"     {brique:<14} déclare {sorted(declarees) or '—'}")
        verifie(f"« {brique} » ne cite aucune table qu'il ne déclare",
                citees - declarees, set())
        verifie(f"« {brique} » ne déclare aucune table qu'il n'utilise",
                declarees - citees, set())
        verifie(f"« {brique} » ne devine aucun chemin",
                chemins_devines(brique), set())

    # ── Ces tables, quelqu'un les crée-t-il ? — ────────────────
    brain = None
    if "--brain" in sys.argv:
        brain = Path(sys.argv[sys.argv.index("--brain") + 1]).expanduser()
    if brain is None or not brain.is_dir():
        print("\n  ⏭️  créateurs de tables — pas de brain à confronter")
        print("     Un vert qui ne mesure rien serait pire qu'un rouge.")
    else:
        print("\n  QUI CRÉE CE QUE LE CORE ATTEND\n")
        connus = createurs(brain)
        for brique in BRIQUES:
            mod = importlib.import_module(f"core.{brique}")
            for table in sorted(getattr(mod, "TABLES", set())):
                ou = connus.get(table, [])
                origine = f"{len(ou)} source(s)" if ou else "PERSONNE"
                print(f"     {table:<14} {origine:<12} {ou[0] if ou else ''}")
                verifie(f"« {table} », attendue par {brique}, a un créateur",
                        bool(ou), True)

    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)")
    if _ko:
        print("\n  Une frontière est mal placée. La vision dit de la corriger")
        print("  AVANT d'en poser une autre — pas de la documenter.\n")
    else:
        print()
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(main())
