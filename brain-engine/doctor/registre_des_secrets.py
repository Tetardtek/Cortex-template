#!/usr/bin/env python3
"""Le registre des secrets dit-il ce que MYSECRETS porte ? — BRAIN-076.

Ce qui pourrirait en silence sans lui : **un registre qui dérive vers la
fiction.** Personne ne s'en aperçoit, parce qu'un registre faux se lit
exactement comme un registre juste.

Mesuré le 10/09, avant d'écrire ce contrôle :

    MYSECRETS          79 cles a valeur non vide
    secrets.yml        28 cles declarees
    non declarees      73
    declarees fantomes 22   dont OSTIZ_ENCRYPTION_KEY — un `P` manquant devant
                            POSTIZ_ENCRYPTION_KEY, invisible depuis cinq mois

Et un second registre, `SECRETS_REGISTRY` (empreintes SHA256), figé le jour
même de sa création — 16/03 18:22 — que `BRAIN-040` n'a jamais retiré en en
décidant un autre trois jours plus tard.

── Zero-exposure ───────────────────────────────────────────────────────────

**Aucune valeur ne sort d'ici.** Ni dans la sortie, ni dans un message
d'erreur, ni dans une trace. Le contrôle ne manipule que des **noms de clés**
et des longueurs. C'est la contrainte qui prime sur toutes les autres : un
contrôle de secrets qui fuit vaut moins que pas de contrôle.

── Ce qu'il refuse, et pourquoi ────────────────────────────────────────────

    non declaree      une cle vit dans MYSECRETS et le registre l'ignore
                      → le registre ne peut plus servir d'inventaire

    fantome           le registre declare une cle qui n'existe pas
                      → c'est la coquille OSTIZ ; un registre qui invente
                        n'est plus une reference

    doublon           une cle est declaree deux fois dans MYSECRETS
                      → c'est ce qui a casse `brain-notify.sh` : un `grep`
                        rendait les DEUX lignes, le jeton faisait 47
                        caracteres dont un saut de ligne

    perimee           `expires_at` est passe
                      → une rotation due qui ne se signale pas ne se fait pas

Ce qu'il ne refuse **pas** : une `description` vide, un `rotated_at` absent.
Un rouge permanent que seul l'humain peut eteindre est un rouge qu'on apprend
a ignorer — et alors le controle ne protege plus rien.

    python3 tools/registre_des_secrets.py --brain ~/Dev/Brain
    python3 tools/registre_des_secrets.py --brain ~/Dev/Brain --bootstrap
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


def lire_mysecrets(chemin: Path) -> tuple[dict[str, int], list[str],
                                         dict[str, str], dict[str, list[int]]]:
    """({nom: nb de valeurs non vides}, [doublons], {doublon: NATURE},
    {doublon: [numeros des lignes vides]}).

    Ne retourne JAMAIS de valeur — seulement des noms, des comptes, et pour
    chaque doublon une NATURE, obtenue en comparant des empreintes sha256 en
    memoire. Aucune valeur n'est ni rendue, ni journalisee, ni affichee.

    🔴 Pourquoi la nature, ajoutee le 26/09 : « 2 doublons » ne dit pas s'il faut
    courir. Deux lignes identiques sont une redite sans consequence ; deux lignes
    DIVERGENTES font lire une valeur selon l'ordre du fichier, et le comportement
    depend alors de qui lit et comment. C'est la difference entre un menage et un
    incident, et le controle ne la disait pas.

    ⚠️ Les deux comptes ne mesurent pas la meme chose, et c'est deliberé.

    Le premier ignore les gabarits vides : une cle a valeur vide n'est pas
    fournie. Le second les compte TOUS, parce que le danger ne vient pas de la
    valeur mais de la ligne : `grep "^CLE="` rend chaque occurrence, vide ou
    non. C'est exactement ce qui a casse `brain-notify.sh` — un gabarit vide en
    ligne 22, la vraie valeur en ligne 87, et un jeton de 47 caracteres dont un
    saut de ligne.

    La premiere version de ce controle comptait les doublons sur les seules
    valeurs non vides. Elle n'aurait pas vu le defaut qui l'a fait ecrire.
    """
    import hashlib
    fournies: dict[str, int] = {}
    lignes: dict[str, int] = {}
    # {nom: [empreinte ou None pour un gabarit vide]} — jamais la valeur
    # {nom: [(empreinte ou None, numero de ligne)]} — jamais la valeur
    traces: dict[str, list[tuple[str | None, int]]] = {}
    for no, ligne in enumerate(
            chemin.read_text(encoding="utf-8").splitlines(), 1):
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, _, valeur = ligne.partition("=")
        nom = nom.strip()
        lignes[nom] = lignes.get(nom, 0) + 1
        v = valeur.strip()
        traces.setdefault(nom, []).append(
            (hashlib.sha256(v.encode()).hexdigest() if v else None, no))
        if v:
            fournies[nom] = fournies.get(nom, 0) + 1
    doublons = sorted(n for n, c in lignes.items() if c > 1)

    nature: dict[str, str] = {}
    for n in doublons:
        emp = [e for e, _ in traces[n]]
        pleines = [e for e in emp if e is not None]
        vides = len(emp) - len(pleines)
        if not pleines:
            nature[n] = "toutes les lignes sont vides"
        elif len(set(pleines)) > 1:
            nature[n] = ("🔴 valeurs DIVERGENTES — la lecture depend de l'ordre "
                         "du fichier")
        elif vides:
            nature[n] = ("un gabarit VIDE et une vraie valeur — le defaut de "
                         "brain-notify.sh")
        else:
            nature[n] = "valeurs identiques — une redite, sans consequence"
    # Les numeros des lignes VIDES d un doublon : c est ce qu il faut retirer,
    # et un numero de ligne n est pas une valeur.
    vides_de: dict[str, list[int]] = {
        n: [no for e, no in traces[n] if e is None] for n in doublons}
    return fournies, doublons, nature, vides_de


def lire_registre(chemin: Path) -> dict[str, dict]:
    import yaml
    charge = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    return charge.get("secrets") or {}


def machine_courante(brain: Path) -> str | None:
    """Le nom de CETTE machine, tel que `brain-compose.local.yml` le declare.

    ⚠️ Sans lui, ce controle est faux — et il l'a ete a sa premiere execution.

    `secrets.yml` declare `machines: [...]` par cle, parce que BRAIN-040 a ete
    ecrite pour plusieurs machines. Une cle `machines: ['vps']` n'a rien a faire
    dans le MYSECRETS du poste fixe : son absence est **correcte**.

    Mesure du 10/09 : sur 22 cles declarees-et-absentes ici, **21 portaient
    `machines: ['vps']`**. Un controle qui ignore ce champ accuse 21
    declarations justes et rate la seule vraie — `VPS_USER`, declaree pour
    `desktop` et absente.
    """
    import yaml
    f = brain / "brain-compose.local.yml"
    if not f.is_file():
        return None
    charge = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return charge.get("machine")


# Fichiers ou une cle peut legitimement etre citee. On EXCLUT les deux fichiers
# du registre lui-meme : MYSECRETS declare tout, `secrets.yml` aussi, et les
# compter comme consommateurs rendrait toute cle « utilisee ».
# 🔴 Un document QUI PARLE des cles n'est pas un consommateur — 26/09.
#
# Mesure : ecrire `tri-des-secrets-20260926.md`, qui enumere les cles a trier, a
# fait passer l'inventaire de 36 orphelines a 8. Le document redige pour decider
# quelles cles sont mortes les a toutes ressuscitees. **Documenter la mesure la
# detruisait.**
#
# Il est donc exclu nommement, comme MYSECRETS et le registre le sont : ce sont
# les fichiers dont le metier est de NOMMER des cles.
EXCLUS = {"MYSECRETS", "MYSECRETS.example", "secrets.yml", "SECRETS_REGISTRY",
          "tri-des-secrets-20260926.md",
          # ⚠️ Les fichiers GENERES qui enumerent l'environnement.
          #
          # `.svelte-kit/ambient.d.ts` est produit au build et liste TOUTES les
          # variables d'environnement presentes dans le shell. Il cite donc
          # chaque cle de MYSECRETS — et faisait passer les 79 pour utilisees,
          # `N8N_OLD_ENCRYPTION_A_TEJ` compris, dont le nom dit qu'elle est a
          # jeter. Un fichier qui nomme tout ne temoigne de rien.
          "ambient.d.ts",
          # Et l'outil lui-meme, dont la documentation cite des noms de cles.
          "registre_des_secrets.py", "test_registre_des_secrets.py"}
GENERES = {".svelte-kit", ".nuxt", ".output", ".turbo", ".angular"}
SUFFIXES = {".sh", ".py", ".yml", ".yaml", ".md", ".service", ".json", ".ts",
            ".js", ".env", ".conf", ".toml"}


def racines_de_scan(brain: Path) -> list[Path]:
    """Ou une cle peut etre citee — et le brain n'est PAS le principal.

    Premiere version : le brain seul. Elle rendait 37 cles « que rien ne
    cite », dont `CLICKERZ_DB_PASSWORD` et les `CLOUDFLARE_R2_*` — consommes
    par leurs depots projet, pas par le brain. Un inventaire qui ne regarde
    qu'un tiers du disque appelle « orphelin » ce qu'il n'a pas cherche.
    """
    maison = brain.parent.parent          # ~/Dev/Brain → ~
    racines = [brain]
    for d in ("Dev/Gitea", "Dev/Github"):
        c = maison / d
        if c.is_dir():
            racines.append(c)
    return racines


def consommateurs(brain: Path, noms: set[str]) -> dict[str, list[str]]:
    """{cle: [fichiers qui la citent]} — DERIVE du code, jamais stocke comme verite.

    Repond a la question que `last_use` ne peut pas honnetement poser : *cette
    cle sert-elle encore ?* MYSECRETS est un fichier plat que chaque script lit
    avec son propre `grep` — il n'existe aucun point de passage ou intercepter
    une lecture, donc aucun horodatage d'usage n'est mesurable. Le jour ou
    toutes les lectures passeront par une porte unique (, « 42 scripts
    deviennent des sous-commandes »), `last_use` deviendra gratuit et vrai.

    En attendant, ce qui se mesure vraiment : **qui cite ce nom.** Une cle
    citee nulle part est un vestige — et il y en a, l'inventaire porte cinq
    mois d'essais.

    Un seul passage sur les fichiers, pas un par cle : 101 cles fois quelques
    milliers de fichiers serait une mesure qu'on renonce a relancer.

    ⚠️ Le parcours ignore `.git/` et `brain-template/` mais PAS les satellites
    gitignores : `grep` du shell les rate, et une cle cite uniquement dans
    `todo/` ou `profil/` passerait pour orpheline.
    """
    trouve: dict[str, list[str]] = {n: [] for n in noms}
    # 🔴 `scratch` ajoute le 26/09. Mon propre script de tri, pose la, citait
    # deux cles dans son docstring — et les faisait sortir de la liste des
    # orphelines qu'il servait a etablir. `workspace/scratch/` est par
    # definition jetable : une cle « consommee » par un brouillon ne l'est pas.
    #
    # C'est la seconde face du meme defaut que l'exclusion nommee ci-dessus :
    # tout fichier qui PARLE des cles pollue la mesure, l'outil du tri compris.
    ignores = {".git", "node_modules", "__pycache__", ".venv", ".venv-x11",
               "brain-template", "archive", ".dolt", "brain-dolt", "dist",
               "build", "target", ".next", "vendor", "coverage", ".cache",
               "scratch"} | GENERES
    maison = brain.parent.parent
    for racine in racines_de_scan(brain):
        for f in racine.rglob("*"):
            try:
                if not f.is_file() or f.suffix not in SUFFIXES or f.name in EXCLUS:
                    continue
                parts = set(f.relative_to(racine).parts)
                if ignores & parts:
                    continue
                texte = f.read_text(encoding="utf-8", errors="ignore")
            except (OSError, ValueError):
                continue
            try:
                rel = str(f.relative_to(maison))
            except ValueError:
                rel = str(f)
            for n in noms:
                if n in texte:
                    trouve[n].append(rel)
    return trouve


def perimees(registre: dict[str, dict]) -> list[str]:
    aujourdhui = date.today()
    dues = []
    for nom, meta in registre.items():
        exp = (meta or {}).get("expires_at")
        if exp is None:
            continue
        if isinstance(exp, str):
            try:
                exp = date.fromisoformat(exp)
            except ValueError:
                continue                   # une date illisible n'est pas une peremption
        if isinstance(exp, date) and exp < aujourdhui:
            dues.append(f"{nom} (expire le {exp})")
    return sorted(dues)


def bootstrap(mysecrets: dict[str, int], registre: dict[str, dict],
              chemin_registre: Path) -> int:
    """Declare les cles manquantes, avec ce qui se DERIVE du nom — rien d'invente.

    `description` reste vide : elle appartient a l'humain, et le controle ne
    l'exige pas. Le but est que le registre devienne exhaustif, pas bavard.
    """
    manquantes = sorted(set(mysecrets) - set(registre))
    if not manquantes:
        print("✅ rien a declarer — le registre couvre deja MYSECRETS")
        return 0

    # ⚠️ On AJOUTE du texte, on ne re-serialise pas.
    #
    # La premiere version faisait `yaml.safe_dump` du document entier. Elle
    # aurait detruit les seize lignes de commentaire de `secrets.yml`, dont la
    # documentation du schema — silencieusement, et sans que le controle qui
    # suit s'en apercoive : un YAML sans commentaires reste un YAML valide.
    texte = chemin_registre.read_text(encoding="utf-8").rstrip("\n")
    bloc = [texte, "",
            f"  # --- Declarees en masse le {date.today():%Y-%m-%d} "
            f"(BRAIN-076, `--bootstrap`) ---",
            "  # `scope` derive du prefixe du nom. `description` appartient a",
            "  # l'humain : le controle ne l'exige pas, et ne rougira pas dessus."]
    aujourdhui = f"{date.today():%Y-%m-%d}"
    for nom in manquantes:
        bloc += [f"  {nom}:",
                 f"    scope: {nom.split('_')[0].lower()}",
                 # ⚠️ `created_at` est la date de DECLARATION, pas la naissance
                 # du secret. MYSECRETS est chiffre par git-crypt : git n'en
                 # garde aucun historique ligne a ligne, la vraie date de
                 # creation n'est pas recuperable. Dire « declare le » est vrai ;
                 # dire « cree le » serait une date inventee.
                 f"    created_at: {aujourdhui}",
                 f"    declared_modified_at: {aujourdhui}",
                 "    expires_at: null",
                 "    rotated_at: null",
                 "    machines: [desktop]",
                 "    required: false",
                 "    description: ''"]
    chemin_registre.write_text("\n".join(bloc) + "\n", encoding="utf-8")

    # Relire : un fichier qu'on vient d'ecrire et qu'on ne relit pas est une
    # supposition. S'il ne se recharge pas, on l'a casse.
    import yaml
    recharge = yaml.safe_load(chemin_registre.read_text(encoding="utf-8")) or {}
    n = len((recharge.get("secrets") or {}))
    attendu = len(registre) + len(manquantes)
    if n != attendu:
        print(f"❌ apres ecriture le registre porte {n} cles, {attendu} attendues — "
              f"le fichier est casse", file=sys.stderr)
        return 1
    print(f"✅ {len(manquantes)} cle(s) declaree(s) — {n} au total, commentaires "
          f"preserves, fichier relu et valide")
    return 0


def ecrire_consommateurs(chemin: Path, cites: dict[str, list[str]],
                         maxi: int = 5) -> int:
    """Ecrit le cache des consommateurs DANS le registre, ligne a ligne.

    Cache derive, jamais verite : il est reecrit a chaque `--consommateurs`.
    Le motif est connu — une source, un cache regenere.
    Editer ce champ a la main n'a aucun effet : le passage suivant l'ecrase.

    Ligne a ligne, et non par `yaml.safe_dump`, pour la meme raison qu'au
    bootstrap : le fichier porte dix-neuf lignes de commentaire, dont la
    documentation du schema, qu'une re-serialisation effacerait sans bruit.
    """
    import yaml
    # 🔴 L invariant, releve AVANT : une reecriture de CACHE ne doit pas changer
    # le nombre de cles. Relu en juge le 26/09 — la garde comparait le resultat a
    # `len(cites)`, soit 79, alors que le registre en porte 101. `101 < 79` etant
    # faux, elle ne mordait JAMAIS : perdre jusqu a 22 cles passait en silence.
    brut = chemin.read_text(encoding="utf-8")
    try:
        attendu = len((yaml.safe_load(brut) or {}).get("secrets") or {})
    except yaml.YAMLError as exc:
        print(f"❌ le registre est DEJA illisible — un cache ne se reecrit pas sur "
              f"un fichier casse.\n   {str(exc).splitlines()[0]}", file=sys.stderr)
        return 1
    lignes = brut.splitlines()
    scan = f"{date.today():%Y-%m-%d}"
    sortie, i, touchees = [], 0, 0
    while i < len(lignes):
        l = lignes[i]
        sortie.append(l)
        # une entree de cle : deux espaces, un nom, deux-points, rien apres
        if (l.startswith("  ") and not l.startswith("   ")
                and l.rstrip().endswith(":") and not l.lstrip().startswith("#")):
            nom = l.strip().rstrip(":")
            if nom in cites:
                i += 1
                # ── Retirer l'ancien cache, EN-TETE ET ITEMS ────────────────
                #
                # 🔴 La premiere version testait `sortie[-1]` — la SORTIE — pour
                # savoir si un `- ` appartenait au cache. Or l'en-tete
                # `consommateurs:` venait d'y etre SUPPRIMEE : elle n'y
                # apparaissait jamais, donc le test ne pouvait pas mordre. Les
                # items restaient, suspendus sous `description:`, et le YAML
                # devenait illisible.
                #
                # Consequence, mesuree le 26/09 : l'ecriture n'etait PAS
                # idempotente. Elle a reussi le 10/09 sur un fichier sans cache,
                # et cassait a chaque passage suivant. Personne ne l'avait
                # relancee entre les deux.
                #
                # On suit donc l'ENTREE, pas la sortie.
                dans_cache = False
                while i < len(lignes) and (lignes[i].startswith("    ")
                                           or not lignes[i].strip()):
                    nu = lignes[i].lstrip()
                    if nu.startswith(("consommateurs:", "consommateurs_scan:")):
                        dans_cache = True
                    elif dans_cache and (nu.startswith("- ") or nu.startswith("#")):
                        pass                    # item ou « … et N autre(s) » du cache
                    elif not nu:
                        sortie.append(lignes[i])
                    else:
                        dans_cache = False
                        sortie.append(lignes[i])
                    i += 1
                while sortie and not sortie[-1].strip():
                    sortie.pop()
                f = cites[nom]
                sortie.append(f"    consommateurs_scan: {scan}")
                if not f:
                    sortie.append("    consommateurs: []")
                else:
                    sortie.append("    consommateurs:")
                    for c in f[:maxi]:
                        sortie.append(f"      - {c}")
                    if len(f) > maxi:
                        sortie.append(f"      # … et {len(f) - maxi} autre(s)")
                sortie.append("")
                touchees += 1
                continue
        i += 1
    # 🔴 On valide AVANT de remplacer le fichier — [26/09].
    #
    # La premiere version ecrivait, relisait, et signalait le degat. Le controle
    # de relecture a effectivement mordu ce jour-la : il a leve une
    # `ParserError`. Mais il l'a levee APRES l'ecriture, donc le registre des
    # secrets est reste CASSE sur le disque, et l'exception n'etait meme pas
    # rattrapee. Un garde qui detecte un degat sans l'empecher n'est pas un
    # garde : c'est un temoin.
    texte = "\n".join(sortie).rstrip("\n") + "\n"
    try:
        recharge = yaml.safe_load(texte) or {}
    except yaml.YAMLError as exc:
        print(f"❌ l'ecriture produirait un YAML illisible — RIEN n'a ete ecrit.\n"
              f"   {str(exc).splitlines()[0]}", file=sys.stderr)
        return 1
    n = len(recharge.get("secrets") or {})
    if n != attendu:
        print(f"❌ l'ecriture changerait le nombre de cles : {attendu} → {n} — "
              f"RIEN n'a ete ecrit.", file=sys.stderr)
        return 1
    chemin.write_text(texte, encoding="utf-8")
    orph = sum(1 for f in cites.values() if not f)
    print(f"✅ consommateurs ecrits pour {touchees} cle(s) — {orph} sans aucun "
          f"citateur sur ce disque · fichier relu, {n} cles")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Le registre des secrets vs MYSECRETS")
    p.add_argument("--brain", required=True, type=Path)
    p.add_argument("--bootstrap", action="store_true",
                   help="declare les cles manquantes (derive du nom, jamais de valeur)")
    p.add_argument("--consommateurs", action="store_true",
                   help="rescanne qui cite chaque cle et reecrit le cache (~75 s)")
    a = p.parse_args()

    secrets_dir = a.brain / "brain-secrets"
    f_mysecrets = secrets_dir / "MYSECRETS"
    f_registre = secrets_dir / "secrets.yml"

    # Un controle qui ne peut pas s'exercer s'abstient — il ne verdit pas.
    if not f_mysecrets.is_file():
        print("⏭️  SKIP MYSECRETS absent — rien a comparer.", file=sys.stderr)
        return 0
    if not f_registre.is_file():
        print(f"❌ registre absent : {f_registre}", file=sys.stderr)
        return 1
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("⏭️  SKIP pyyaml absent — le registre ne peut pas etre lu.", file=sys.stderr)
        return 0

    mysecrets, doublons, nature, vides_de = lire_mysecrets(f_mysecrets)
    registre = lire_registre(f_registre)

    if a.bootstrap:
        return bootstrap(mysecrets, registre, f_registre)

    ici = machine_courante(a.brain)
    if ici is None:
        print("⏭️  SKIP `machine:` absent de brain-compose.local.yml — le controle "
              "ne peut pas savoir quelles cles le concernent.", file=sys.stderr)
        return 0

    def concerne(nom: str) -> bool:
        m = (registre.get(nom) or {}).get("machines")
        return True if not m else ici in m   # non declare = concerne tout le monde

    non_declarees = sorted(set(mysecrets) - set(registre))
    fantomes = sorted(n for n in set(registre) - set(mysecrets) if concerne(n))
    ailleurs = len(set(registre) - set(mysecrets)) - len(fantomes)
    dues = perimees(registre)

    # Les orphelines ne font PAS rougir : « personne ne la cite » n'est pas un
    # defaut, c'est une question posee a l'humain. Un rouge qu'on ne peut
    # eteindre qu'en supprimant un secret serait une pression a supprimer.
    # Le scan coute ~75 s : il ne tourne pas a chaque passage. Le controle par
    # defaut reste a 0,2 s, et `brain doctor` peut donc le jouer sans le subir.
    orphelines: list[str] = []
    if a.consommateurs:
        cites = consommateurs(a.brain, set(mysecrets))
        return ecrire_consommateurs(f_registre, cites)

    if not (non_declarees or fantomes or doublons or dues):
        print(f"✅ registre et MYSECRETS d'accord sur `{ici}` — {len(mysecrets)} cles, "
              f"0 fantome, 0 doublon"
              + (f" ({ailleurs} declarees pour une autre machine)" if ailleurs else ""))
        if orphelines:
            print(f"ℹ️  {len(orphelines)} cle(s) que RIEN ne cite dans le brain — "
                  f"vestiges probables, a trancher :")
            for n in orphelines:
                print(f"     • {n}")
        return 0

    print("❌ le registre des secrets ne decrit pas MYSECRETS", file=sys.stderr)
    print("", file=sys.stderr)
    if doublons:
        print(f"   {len(doublons)} doublon(s) dans MYSECRETS — une lecture naive rend "
              f"les DEUX lignes :", file=sys.stderr)
        a_retirer = []
        for n in doublons:
            print(f"     • {n}", file=sys.stderr)
            print(f"       {nature.get(n, 'nature inconnue')}", file=sys.stderr)
            for no in vides_de.get(n, []):
                print(f"       ligne {no} : gabarit vide", file=sys.stderr)
                a_retirer.append(no)
        if a_retirer:
            # Le geste, pret a lancer. Un numero de ligne n est pas une valeur,
            # et `sed` ne fait sortir aucun contenu.
            lst = ";".join(f"{no}d" for no in sorted(a_retirer, reverse=True))
            print(f"\n     Retirer les gabarits vides, en gardant les vraies "
                  f"valeurs :", file=sys.stderr)
            print(f"       cp brain-secrets/MYSECRETS brain-secrets/MYSECRETS.bak"
                  f" && sed -i '{lst}' brain-secrets/MYSECRETS", file=sys.stderr)
            print(f"     Puis relancer ce controle, et retirer le .bak.",
                  file=sys.stderr)
    if fantomes:
        print(f"   {len(fantomes)} cle(s) declaree(s) pour `{ici}` mais absente(s) "
              f"de MYSECRETS :", file=sys.stderr)
        for n in fantomes[:12]:
            print(f"     • {n}", file=sys.stderr)
        if len(fantomes) > 12:
            print(f"     … et {len(fantomes) - 12} autres", file=sys.stderr)
    if non_declarees:
        print(f"   {len(non_declarees)} cle(s) dans MYSECRETS, absente(s) du registre :",
              file=sys.stderr)
        for n in non_declarees[:12]:
            print(f"     • {n}", file=sys.stderr)
        if len(non_declarees) > 12:
            print(f"     … et {len(non_declarees) - 12} autres", file=sys.stderr)
        print("     → `--bootstrap` les declare, sans inventer de description.",
              file=sys.stderr)
    if dues:
        print(f"   {len(dues)} rotation(s) due(s) :", file=sys.stderr)
        for d in dues:
            print(f"     • {d}", file=sys.stderr)
    if orphelines:
        print("", file=sys.stderr)
        print(f"   ℹ️  hors verdict — {len(orphelines)} cle(s) que RIEN ne cite dans "
              f"le brain :", file=sys.stderr)
        for n in orphelines[:20]:
            print(f"     • {n}", file=sys.stderr)
        if len(orphelines) > 20:
            print(f"     … et {len(orphelines) - 20} autres", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
