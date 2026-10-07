#!/usr/bin/env python3
"""Les gardes d'écriture du serveur refusent-elles vraiment ? —,.

`server.py` déclare trois zones et trois refus :

    invariant   KERNEL.md, PATHS.md, brain-constitution.md, BRAIN-INDEX.md
                → 403 systématique, « édition humaine en session »
    kernel      agents/, profil/, scripts/, brain-compose.yml
                → scope `kernel` ET claim BSI ouvert
    libre       le reste → lock BSI respecté

**Rien ne l'avait jamais vérifié.** Ces gardes sont nées d'un constat : la
route ne les consultait pas ; les rédiger n'est pas les éprouver.

    python3 tools/eprouver_gardes_ecriture.py --brain ~/Dev/Brain

── Comment on éprouve un REFUS sans risquer une écriture ───────────────────

Le filet est simple et il tient tout seul : **on envoie le contenu actuel du
fichier.** Si la garde refuse, rien n'est écrit — c'est ce qu'on veut prouver.
Si elle cède, le fichier est réécrit **à l'identique** : le défaut est découvert
sans dégât.

Et on ne s'en remet pas à ce raisonnement : les empreintes SHA-256 sont relevées
avant et après, et le contrôle rougit si l'une d'elles bouge.

── Une garde à la fois ─────────────────────────────────────────────────────

`check_auth` s'exécute AVANT `_write_zone`. Sans jeton, tout rend 401 — et on
mesurerait l'authentification en croyant mesurer les zones. Le contrôle
neutralise donc l'auth **en mémoire, dans son propre processus**, pour isoler la
garde de zone. Aucun jeton n'est lu, MYSECRETS n'est jamais ouvert.

── Ce que ça a montré le 11/09, puis corrigé le même jour ──────────────────

Première version : `agents/coach.md` rendait **409 « 3 claims ouverts — préciser
sess_id »**, et le contrôle s'en contentait.

🔴 **Il mesurait une conjoncture.** Ce 409 ne venait pas de la protection du
kernel mais de l'AMBIGUÏTÉ entre trois claims ouverts. Le soir même, deux claims
sont fermés ; il n'en reste qu'un, la route le résout, et l'écriture kernel est
**légitimement autorisée**. Le contrôle a rougi — à raison : il n'annonçait plus
ce qu'il mesurait.

Et le vert de la veille cachait un risque : la route, quand elle N'a PAS refusé,
a écrit le fichier et lancé `embed.py --file` en sous-processus. Un contrôle qui
éprouve un REFUS produit une ÉCRITURE le jour où le refus ne vient plus. Rien
n'a été perdu — le contenu envoyé était identique, donc l'indexeur a vu la même
empreinte et n'a regénéré aucun chunk (mesuré : 0 fichier réindexé). Mais ça
tenait à une coïncidence, pas à une garantie.

Il éprouve donc désormais les trois branches de refus qui NE dépendent pas de
l'état des claims, en neutralisant `_open_claims` en mémoire — et aucun de ces
refus n'envoie plus un PUT qui pourrait aboutir. Seul le témoin en joue un, et
celui-là DOIT aboutir : réécriture à l'identique, empreinte vérifiée.

── Ce que le PUT qui aboutit touche du moteur, et ce qu'on en neutralise ────

Une écriture acceptée lit les verrous du réseau en base (`_foreign_lock`), puis
dépose une réindexation dans la file du moteur (`_demander_reindex`), qui la
mène à son terme : appel au modèle d'embedding, écritures en base. Intercepter
`Popen` ne neutralisait plus rien depuis que la réindexation passe par cette
file. Pendant TOUS les PUT, ces deux fonctions sont donc remplacées en mémoire
par des compteurs (rendues en `finally`, comme `_open_claims`) ; l'interception
de `Popen` reste, pour un moteur qui y reviendrait. Après le PUT qui aboutit,
on exige exactement une réindexation et une lecture de verrous interceptées :
zéro voudrait dire que la route réindexe ou lit les verrous par un détour que
ce contrôle ne neutralise pas. Un moteur sans ces fonctions est refusé, pas
sauté.

Et la racine : `server.BRAIN_ROOT` suit la variable `BRAIN_ROOT`, pas
`--brain`. Posée ailleurs, le contrôle écrirait dans un autre brain que celui
qu'il annonce : il refuse avant tout PUT.

Corollaire conservé : le MCP n'envoie jamais de `sess_id`, donc `brain_write` en
zone kernel est impossible dès qu'il y a plus d'un claim ouvert.
"""

from __future__ import annotations

import argparse
import os
import hashlib
import sys
from pathlib import Path

# Ce que chaque cas doit rendre, et pourquoi. Les chemins sont ceux du brain
# reel : on éprouve la garde SUR LA VRAIE CONFIGURATION, pas sur une fixture qui
# pourrait diverger — c'est le défaut mesure le 10/09 sur les scopes du MCP.
# Le MOTIF compte autant que le code. Un 403 peut venir de trois branches
# differentes de cette route — invariant, scope insuffisant, ou une garde en
# amont. Asserter sur le seul code laisserait passer un refus prononce pour la
# mauvaise raison, et le vert serait creux. On exige donc le mot qui identifie
# la branche.
ATTENDU = [
    ("KERNEL.md",             403, "invariant", "le noyau ne s'ecrit pas par l'API"),
    # Declare invariant, et ABSENT de la racine — il vit dans ~/.claude/. Le
    # laisser ici n'est pas une erreur : c'est ce qui fait dire au controle que
    # la liste decrit un brain qui n'est pas celui-ci.
    ("CLAUDE.md",             403, "invariant", "declare mais absent de la racine"),
    ("PATHS.md",              403, "invariant", "les chemins machine non plus"),
    # Entre dans la liste le 11/09 : il etait invariant pour NIVEAUX.yml et PAS
    # pour l'API, qui derivait d'une liste en dur. Le fichier qui GOUVERNE les
    # zones n'etait pas protege par la garde qu'il gouverne.
    ("NIVEAUX.yml",           403, "invariant", "la declaration des zones elle-meme"),
    ("brain-constitution.md", 403, "invariant", "ni la constitution"),
    ("BRAIN-INDEX.md",        403, "invariant", "ni l'index"),
]

# La zone `kernel` est eprouvee a part, plus bas : son refus depend de l'etat des
# CLAIMS, pas seulement du chemin. Le mettre dans cette table revenait a mesurer
# une conjoncture.


def empreinte(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def motif_de(r) -> str:
    """Le `detail` d'une réponse, ou rien : un 200 rend `{"ok": …}`, une panne
    peut ne pas rendre de JSON du tout."""
    try:
        d = r.json()
    except ValueError:
        return ""
    return str(d.get("detail", "")) if isinstance(d, dict) else ""


#: Si aucun agent de zone kernel n'est inscriptible, d'autres fichiers de la même zone.
AUTRES_KERNEL = ("brain-compose.yml",)


def cible_kernel(racine: Path, server) -> str | None:
    """Un fichier de zone kernel que le témoin peut ÉCRIRE — un agent d'abord (`coach`).

    Le témoin, plus bas, joue un PUT qui aboutit : sur un fichier en lecture seule,
    le serveur ne peut pas écrire. Chez un fork dont le noyau se lit (`noyau: lecture`),
    `agents/coach.md` mène à `noyau/agents/coach.md`, verrouillé : viser un agent à
    l'aveugle faisait tomber le serveur dans le contrôle (6/10). On vise donc un fichier
    réellement inscriptible ; à défaut d'agent, un autre fichier de zone kernel. Ce qui
    n'est pas inscriptible n'est pas une garde qui refuse : c'est le disque."""
    dossier = racine / "agents"
    noms = ["coach.md"] + sorted(p.name for p in dossier.glob("*.md")
                                 if p.name not in ("coach.md", "AGENTS.md") and not p.name.startswith("_"))
    candidats = [f"agents/{n}" for n in noms] + list(AUTRES_KERNEL)
    for rel in candidats:
        f = racine / rel
        if not f.is_file() or not os.access(f.resolve(), os.W_OK):
            continue
        reel = str(f.resolve().relative_to(racine.resolve()))
        if server._write_zone(reel) == "kernel":
            return rel
    return None

def main() -> int:
    p = argparse.ArgumentParser(description="Les gardes d'écriture refusent-elles ?")
    p.add_argument("--brain", required=True, type=Path)
    a = p.parse_args()

    moteur = a.brain.expanduser().resolve() / "brain-engine"
    if not (moteur / "server.py").is_file():
        print("⏭️  SKIP brain-engine/server.py introuvable.", file=sys.stderr)
        return 0
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("⏭️  SKIP fastapi.testclient absent.", file=sys.stderr)
        return 0

    sys.path.insert(0, str(moteur))
    try:
        import server
    except Exception as exc:                                   # noqa: BLE001
        print(f"❌ le module ne se charge pas : {type(exc).__name__} — {exc}",
              file=sys.stderr)
        return 1

    # La racine que le moteur écrit est celle qu'il lit de `BRAIN_ROOT`, pas
    # `--brain`. Une autre racine, et chaque PUT viserait un brain que personne
    # n'a annoncé : refus, avant tout PUT.
    annonce = a.brain.expanduser().resolve()
    if Path(server.BRAIN_ROOT).resolve() != annonce:
        print(f"❌ le moteur sert {Path(server.BRAIN_ROOT).resolve()}, pas {annonce} "
              f"(variable BRAIN_ROOT ?) — aucun PUT envoyé.", file=sys.stderr)
        return 1
    racine = server.BRAIN_ROOT

    # Ce que le PUT qui aboutit touche hors du fichier — à neutraliser. Un moteur
    # qui ne les porte plus n'est pas sauté : on ne saurait plus ce qu'on laisse
    # passer.
    absentes = [f for f in ("_demander_reindex", "_foreign_lock")
                if not callable(getattr(server, f, None))]
    if absentes:
        print(f"❌ le moteur ne porte pas {', '.join(absentes)} : ce contrôle ne sait "
              f"plus neutraliser ce qu'une écriture déclenche — aucun PUT envoyé.",
              file=sys.stderr)
        return 1

    # ── Le classement des zones, sans toucher au reseau ─────────────────────
    #
    # `_write_zone` est une fonction pure : on peut l'interroger sur des chemins
    # qui n'existent pas, sans aucun effet. C'est la regle elle-meme, avant
    # qu'une route ne l'applique.
    classement = [
        ("KERNEL.md",              "invariant"),
        ("agents/coach.md",        "kernel"),
        ("profil/identity/x.md",   "kernel"),
        ("scripts/quelconque.sh",  "kernel"),
        ("brain-compose.yml",      "kernel"),
        ("workspace/scratch/n.md", "libre"),
        ("handoffs/n.md",          "libre"),
    ]
    faux = [(c, server._write_zone(c), z) for c, z in classement
            if server._write_zone(c) != z]
    print(f"  {'✅' if not faux else '❌'} classement des zones — "
          f"{len(classement)} chemins")
    for c, obtenu, attendu in faux:
        print(f"     ❌ {c} → `{obtenu}`, attendu `{attendu}`", file=sys.stderr)
    if faux:
        return 1

    # Temoin : un fichier declare AUTREMENT doit CHANGER de zone. Sans lui,
    # « KERNEL.md est invariant » pourrait venir d'une regle qui rend toujours
    # « invariant ».
    #
    # ⚠️ Reecrit le 11/09. Il vidait `KERNEL_INVARIANT`, la liste en dur — mais
    # depuis que `_write_zone` derive de `NIVEAUX.yml` par `core.zones`, cette
    # liste n'est plus que le REPLI. Vider un repli ne prouve rien sur le chemin
    # nominal : le controle a echoue en le disant, et c'est exactement son role.
    #
    # On patche donc la SOURCE reelle — la lecture des declarations — pour
    # annoncer `KERNEL.md` comme une donnee ordinaire.
    vrai = server._declarations_niveaux
    try:
        server._declarations_niveaux = lambda: ({"KERNEL.md": "donnee"}, {})
        apres = server._write_zone("KERNEL.md")
    finally:
        server._declarations_niveaux = vrai
    if apres == "invariant":
        print("  ❌ témoin — KERNEL.md reste `invariant` alors qu'il est déclaré "
              "`donnee` :\n     la règle ne consulte pas les déclarations.",
              file=sys.stderr)
        return 1
    print(f"  ✅ témoin — déclaré `donnee`, KERNEL.md tombe en `{apres}`")

    client = TestClient(server.app, client=("127.0.0.1", 4242))
    server.check_auth = lambda a: ["public", "work", "kernel"]   # une garde a la fois

    # ── Pendant TOUS les PUT : réindexation, verrous, sous-processus ────────
    #
    # Remplacés en mémoire par des compteurs, dans ce processus, et rendus en
    # `finally` — comme `_open_claims` plus bas. Le PUT qui aboutit ne lit
    # donc aucun verrou en base et ne dépose aucune réindexation dans la file
    # du moteur.
    demandes, verrous, lances = [], [], []
    vrai_reindex, vrai_verrou = server._demander_reindex, server._foreign_lock
    sp = getattr(server, "subprocess", None)
    vrai_popen = sp.Popen if sp else None
    try:
        server._demander_reindex = lambda rel: demandes.append(rel) or True
        server._foreign_lock = lambda rel, holder: verrous.append(rel) or None
        if sp:
            sp.Popen = lambda *a, **k: lances.append(a) or None
        return refus_et_temoin(server, racine, client, demandes, verrous, lances)
    finally:
        server._demander_reindex, server._foreign_lock = vrai_reindex, vrai_verrou
        if sp:
            sp.Popen = vrai_popen


def refus_et_temoin(server, racine: Path, client, demandes: list, verrous: list,
                    lances: list) -> int:
    """Les PUT : les refus déclarés, la zone kernel, puis le témoin. Appelée
    par `main` seulement, réindexation et verrous neutralisés (les listes
    reçoivent ce qui a été intercepté)."""
    # ── Les refus de la route, avec le filet ────────────────────────────────
    cibles = [(c, code, zone, quoi) for c, code, zone, quoi in ATTENDU
              if (racine / c).is_file()]
    manquants = [c for c, *_ in ATTENDU if not (racine / c).is_file()]
    avant = {c: empreinte(racine / c) for c, *_ in cibles}

    echecs = 0
    temoin_ko = False
    effets_ko = False
    for chemin, code_attendu, zone, quoi in cibles:
        contenu = (racine / chemin).read_text(encoding="utf-8")
        r = client.put(f"/brain/{chemin}", json={"content": contenu})
        motif = str((r.json() or {}).get("detail", ""))
        # « invariant » pour la zone du meme nom ; « claims ouverts » pour la
        # garde de claim BSI. Le mot dit QUELLE branche a refuse.
        attendu_mot = "invariant" if zone == "invariant" else "claim"
        ok = r.status_code == code_attendu and attendu_mot in motif.lower()
        print(f"  {'✅' if ok else '❌'} {r.status_code} attendu {code_attendu}  "
              f"{chemin:24} {quoi}")
        if not ok:
            if r.status_code != code_attendu:
                print(f"     ❌ la garde `{zone}` n'a pas refusé — {motif[:56]}",
                      file=sys.stderr)
            else:
                print(f"     ❌ refus prononcé, mais pas par la garde `{zone}` : "
                      f"le motif ne dit pas « {attendu_mot} » — {motif[:56]}",
                      file=sys.stderr)
            echecs += 1

    # Le filet, verifie et pas seulement raisonne.
    bouges = [c for c, e in avant.items() if empreinte(racine / c) != e]
    if bouges:
        print(f"\n🚨 {len(bouges)} fichier(s) MODIFIE(S) par ce contrôle : "
              f"{', '.join(bouges)}\n   Le contenu envoyé était identique, donc "
              f"rien n'est perdu — mais une garde a cédé.", file=sys.stderr)
        return 1
    print(f"  ✅ filet — {len(avant)} empreinte(s) inchangée(s)")

    # ── La zone `kernel` : trois refus, aucun ne dépend de l'état réel ──────
    #
    # `_open_claims` est neutralisé en mémoire, dans ce processus. Sans ça, le
    # résultat dépendrait du nombre de claims ouverts au moment de la passe — et
    # c'est exactement ce qui a fait rougir ce contrôle le 11/09.
    #
    # ⚠️ Aucun de ces trois cas ne doit ABOUTIR : un PUT accepté écrit le
    # fichier, lit les verrous et demande une réindexation. Seul le témoin,
    # plus bas, joue un cas qui aboutit — verrous et réindexation sont
    # neutralisés par `main` pendant tous les PUT, et comptés.
    # La cible : un agent RÉELLEMENT en zone kernel. `agents/` peut être une vue,
    # et un agent surchargé dans `instance/` vit en zone instance — son écriture
    # n'exige pas de claim, c'est voulu. Viser `coach` à l'aveugle faisait rougir
    # ce contrôle chez tout fork qui surcharge son coach.
    kernel_cible = cible_kernel(racine, server)
    if kernel_cible:
        contenu = (racine / kernel_cible).read_text(encoding="utf-8")
        empreinte_avant = empreinte(racine / kernel_cible)
        vrai_claims = server._open_claims
        cas_kernel = [
            ("aucun claim ouvert", lambda: [], None,
             "aucun claim", "pas de claim, pas d'ecriture kernel"),
            ("un claim inconnu",
             lambda: [{"sess_id": "sess-reel", "scope": "x"}], "sess-invente",
             "non ouvert", "un sess_id qu'aucun claim ne porte"),
            ("deux claims, sans sess_id",
             lambda: [{"sess_id": "a", "scope": "x"},
                      {"sess_id": "b", "scope": "y"}], None,
             "claims ouverts", "l'ambiguite se refuse au lieu de choisir"),
        ]
        for nom, faux_claims, sess, mot, quoi in cas_kernel:
            try:
                server._open_claims = faux_claims
                corps = {"content": contenu}
                if sess:
                    corps["sess_id"] = sess
                r = client.put(f"/brain/{kernel_cible}", json=corps)
            finally:
                server._open_claims = vrai_claims
            motif = str((r.json() or {}).get("detail", ""))
            ok = r.status_code == 409 and mot in motif.lower()
            print(f"  {'✅' if ok else '❌'} {r.status_code} attendu 409  "
                  f"{nom:26} {quoi}")
            if not ok:
                print(f"     ❌ zone kernel — {nom} : {motif[:70]}", file=sys.stderr)
                echecs += 1

        # Le témoin : la neutralisation fait-elle vraiment quelque chose ?
        # Si `_open_claims` n'était pas consulté, les trois cas ci-dessus
        # rendraient la même chose et le vert serait creux.
        #
        # ⚠️ Le second cas ABOUTIT — c'est tout l'intérêt du témoin. Une route
        # qui aboutit réécrit le fichier (à l'identique, le filet le vérifie),
        # lit les verrous du réseau et demande une réindexation. Ces deux-là
        # n'ont rien à faire dans un contrôle : `main` les a neutralisés, plutôt
        # que de compter sur l'indexeur pour trouver le contenu inchangé. Un
        # effet de bord qu'on tolère parce qu'il est inoffensif reste un effet
        # de bord.
        try:
            server._open_claims = lambda: []
            sans = client.put(f"/brain/{kernel_cible}", json={"content": contenu})
            server._open_claims = lambda: [{"sess_id": "seul", "scope": "x"}]
            avec = client.put(f"/brain/{kernel_cible}", json={"content": contenu})
        finally:
            server._open_claims = vrai_claims
        # `avec` DOIT aboutir — c'est la contrepartie de la garde, et c'est
        # pour ça qu'on ne le joue qu'ici, en sachant que le contenu est
        # identique et que le filet d'empreintes le vérifie juste après.
        #
        # Une DIFFÉRENCE ne suffit pas : « sans 409, avec 403 » (un autre refus)
        # ou « avec 503 » (une panne) différaient aussi, et passaient au vert
        # sans que rien ait abouti. On exige le refus de la garde de claim
        # d'un côté, l'écriture de l'autre.
        sans_motif, avec_motif = motif_de(sans), motif_de(avec)
        sans_ok = sans.status_code == 409 and "aucun claim" in sans_motif.lower()
        avec_ok = avec.status_code == 200
        vu = sans_ok and avec_ok
        print(f"  {'✅' if vu else '❌'} témoin — sans claim {sans.status_code}, "
              f"avec un claim {avec.status_code} : "
              + ("la garde consulte bien les claims" if vu
                 else "rien ne prouve que la garde consulte les claims"))
        if not sans_ok:
            print(f"     ❌ le PUT SANS claim a rendu {sans.status_code}, attendu 409 "
                  f"« aucun claim » — {sans_motif[:56]}", file=sys.stderr)
        if not avec_ok:
            print(f"     ❌ le PUT AVEC un claim a rendu {avec.status_code}, attendu 200 : "
                  f"l'écriture n'a pas abouti (un autre refus ou une panne) — "
                  f"{avec_motif[:56]}", file=sys.stderr)
        if not vu:
            temoin_ko = True
        # Ce que l'écriture a déclenché, intercepté. On compte, on ne compare pas
        # les chemins : la route passe le chemin RÉSOLU, pas celui demandé.
        # Zéro après un 200 : la route réindexe (ou lit les verrous) par un
        # détour que ce contrôle ne neutralise pas — rien ne dit qu'il n'a pas
        # atteint le vrai moteur. Plus d'un : un autre PUT a abouti.
        if avec_ok:
            reindex_ok = len(demandes) == 1
            verrous_ok = len(verrous) == 1
            print(f"  {'✅' if reindex_ok and verrous_ok else '❌'} effets interceptés — "
                  f"{len(demandes)} réindexation(s), {len(verrous)} lecture(s) de "
                  f"verrous, {len(lances)} sous-processus ; attendu 1 et 1")
            if not reindex_ok:
                print(f"     ❌ {len(demandes)} réindexation(s) interceptée(s) après le "
                      f"PUT qui aboutit, attendu 1 : la route réindexe par un "
                      f"autre chemin que `_demander_reindex`, non neutralisé",
                      file=sys.stderr)
                effets_ko = True
            if not verrous_ok:
                print(f"     ❌ {len(verrous)} lecture(s) de verrous interceptée(s) "
                      f"après le PUT qui aboutit, attendu 1 : la route lit les "
                      f"verrous par un autre chemin que `_foreign_lock`, non "
                      f"neutralisé", file=sys.stderr)
                effets_ko = True
        if empreinte(racine / kernel_cible) != empreinte_avant:
            print(f"\n🚨 {kernel_cible} A ÉTÉ MODIFIÉ par ce contrôle.",
                  file=sys.stderr)
            return 1
        print(f"  ✅ filet kernel — {kernel_cible} inchangé")

    if manquants:
        print(f"  ℹ️  {len(manquants)} invariant(s) déclaré(s) et absent(s) du "
              f"disque : {', '.join(manquants)}")
        print(f"     Protéger un fichier absent est inoffensif, mais la liste "
              f"décrit alors\n     un brain qui n'est pas celui-ci. `CLAUDE.md` "
              f"vit dans ~/.claude/.")

    if echecs:
        print(f"\n❌ {echecs} garde(s) n'ont pas refusé ce qu'elles déclarent "
              f"refuser.", file=sys.stderr)
    if temoin_ko:
        print("\n❌ le témoin n'a pas abouti : sans claim, la garde devait refuser "
              "(409 « aucun claim ») ;\n   avec un claim, l'écriture devait aboutir "
              "(200). Sans les deux, rien ne prouve que la garde consulte les claims.",
              file=sys.stderr)
    if effets_ko:
        print("\n❌ l'écriture qui aboutit n'a pas déclenché exactement une réindexation "
              "et une lecture\n   de verrous interceptées : ce contrôle ne sait pas ce "
              "qu'elle a touché du moteur.", file=sys.stderr)
    if echecs or temoin_ko or effets_ko:
        return 1
    print(f"\n✅ les gardes refusent — {len(cibles)} refus vérifiés, contenu "
          f"inchangé, réindexation et verrous neutralisés")
    return 0


if __name__ == "__main__":
    sys.exit(main())
