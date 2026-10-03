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
l'état des claims, en neutralisant `_open_claims` en mémoire — et il n'envoie
plus jamais un PUT qui pourrait aboutir.

Corollaire conservé : le MCP n'envoie jamais de `sess_id`, donc `brain_write` en
zone kernel est impossible dès qu'il y a plus d'un claim ouvert.
"""

from __future__ import annotations

import argparse
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



def cible_kernel(racine: Path, server) -> str | None:
    """Le premier agent dont l'écriture tombe en zone kernel — `coach` d'abord."""
    dossier = racine / "agents"
    noms = ["coach.md"] + sorted(p.name for p in dossier.glob("*.md")
                                 if p.name not in ("coach.md", "AGENTS.md") and not p.name.startswith("_"))
    for nom in noms:
        f = dossier / nom
        if not f.is_file():
            continue
        reel = str(f.resolve().relative_to(racine.resolve()))
        if server._write_zone(reel) == "kernel":
            return f"agents/{nom}"
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

    racine = server.BRAIN_ROOT

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

    # ── Les refus de la route, avec le filet ────────────────────────────────
    cibles = [(c, code, zone, quoi) for c, code, zone, quoi in ATTENDU
              if (racine / c).is_file()]
    manquants = [c for c, *_ in ATTENDU if not (racine / c).is_file()]
    avant = {c: empreinte(racine / c) for c, *_ in cibles}

    client = TestClient(server.app, client=("127.0.0.1", 4242))
    server.check_auth = lambda a: ["public", "work", "kernel"]   # une garde a la fois

    echecs = 0
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
    # fichier et lance `embed.py --file`. Seul le témoin, plus bas, joue un cas
    # qui aboutit — et il intercepte le lancement de l'indexeur.
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
        # qui aboutit réécrit le fichier (à l'identique, le filet le vérifie) et
        # lance `embed.py --file` en sous-processus. Ce lancement-là n'a rien à
        # faire dans un contrôle : on le neutralise, plutôt que de compter sur
        # l'indexeur pour trouver le contenu inchangé. Un effet de bord qu'on
        # tolère parce qu'il est inoffensif reste un effet de bord.
        vrai_popen = server.subprocess.Popen
        lances = []
        try:
            server.subprocess.Popen = lambda *a, **k: lances.append(a) or None
            server._open_claims = lambda: []
            sans = client.put(f"/brain/{kernel_cible}", json={"content": contenu})
            server._open_claims = lambda: [{"sess_id": "seul", "scope": "x"}]
            avec = client.put(f"/brain/{kernel_cible}", json={"content": contenu})
        finally:
            server._open_claims = vrai_claims
            server.subprocess.Popen = vrai_popen
        # `avec` DOIT aboutir — c'est la contrepartie de la garde, et c'est
        # pour ça qu'on ne le joue qu'ici, en sachant que le contenu est
        # identique et que le filet d'empreintes le vérifie juste après.
        vu = sans.status_code != avec.status_code
        print(f"  {'✅' if vu else '❌'} témoin — sans claim {sans.status_code}, "
              f"avec un claim {avec.status_code} : la garde consulte bien les claims")
        print(f"  ℹ️  {len(lances)} reindexation(s) interceptée(s) — aucune n'a "
              f"atteint l'indexeur")
        if not vu:
            echecs += 1
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
        return 1
    print(f"\n✅ les gardes refusent — {len(cibles)} refus vérifiés, rien n'a été "
          f"écrit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
