#!/usr/bin/env python3
"""Les quatre déclarations de version du kernel disent-elles la même chose ? —.

Ce qui pourrirait en silence sans lui : **un numéro de version que chaque copie
dit différemment, et que rien ne compare.**

Mesuré le 26/09, et la divergence durait depuis le **2 septembre — 24 jours** :

    brain-compose.yml           version: "2.1.0"       la SOURCE
    brain-compose.local.yml     kernel_version 2.0.0   lue par le BOOT
    kernel.lock                 2.1.0
    brain-template/…            2.1.0

Le briefing du laptop annonçait encore « kernel v2.0.0 » ce matin-là.

🔴 **Et la comparaison était déjà prescrite.** `agents/helloWorld.md`, ordre de
lecture obligatoire, étape 1 :

    1. brain-compose.local.yml -> ... kernel_version local
       -> comparer avec brain-compose.yml.version
       -> si drift : ⚠️ Kernel drift : local=<A> / kernel=<B>
                      — brain-compose.yml a jour, local.yml decale

La consigne nomme la source, nomme le décalé, et prescrit jusqu'au texte de
l'avertissement. **Il n'a jamais été émis.** Une comparaison écrite en prose dans
un agent ne s'exécute que si une session pense à la faire — le motif de,
cette fois sur le numéro de version du kernel lui-même.

    python3 tools/versions_du_kernel.py --brain ~/Dev/Brain

── Ce qu'il mesure, et ce qu'il ne mesure PAS ──────────────────────────────

Les quatre ne sont pas quatre sources indépendantes : **trois sont des copies de
la première.**

    kernel.lock              derivee par kernel-lock-gen.sh (ligne 13)
    brain-compose.local.yml  copie d instance, ecrite a la main
    brain-template/          copie faite par sync-template.sh (un `cp`)

Ce contrôle mesure donc **« les copies ont-elles suivi »**, jamais « deux sources
concordent ». La nuance compte : sans elle il annoncerait quatre accords quand il
n'en mesure qu'un, répété. Ce que chaque divergence veut dire, en revanche, est
différent à chaque fois — et c'est ça qui est utile.

── Il n'écrit rien ─────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# La source, puis les trois copies — avec ce que leur divergence SIGNIFIE.
SOURCE = ("brain-compose.yml", r'^version:\s*"?([0-9][^"\s]*)"?')
COPIES = [
    ("brain-compose.local.yml", r'^\s*kernel_version:\s*"?([0-9][^"\s]*)"?',
     "lue par le BOOT — le briefing annonce alors une version que le programme "
     "n'a pas", True),
    ("kernel.lock", r'^kernel_version:\s*"?([0-9][^"\s]*)"?',
     "derivee de la source : une divergence dit que le lock PRECEDE une montee "
     "de version", False),
    ("brain-template/brain-compose.yml", r'^version:\s*"?([0-9][^"\s]*)"?',
     "copiee par sync-template.sh — les forks comparent alors contre une "
     "version perimee", False),
]

_ok = _ko = 0


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n     obtenu  : {obtenu!r}\n     attendu : {attendu!r}")


def lire(fichier: Path, motif: str) -> str | None:
    """La version declaree, ou None si le fichier ou la cle manquent.

    `None` veut dire « je n'ai pas pu regarder », jamais « elles concordent ».
    """
    if not fichier.is_file():
        return None
    rx = re.compile(motif, re.M)
    for ligne in fichier.read_text(encoding="utf-8", errors="replace").splitlines():
        m = rx.match(ligne)
        if m:
            return m.group(1).strip()
    return None


def rang(v: str) -> tuple[int, ...] | None:
    """(2, 1, 0) pour « 2.1.0 ». None si ce n'est pas comparable."""
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return None


def sens(source: str, copie: str) -> str:
    """« plus ancienne », « plus recente », ou rien si on ne peut pas trancher.

    🔴 Relu en juge le 26/09 : la premiere version annoncait « 2.1 est plus
    ancienne que 2.1.0 ». C'est la MEME version, ecrite autrement — le tuple
    (2, 1) est bien inferieur a (2, 1, 0) en Python, et le sens etait donc
    INVENTE. Les deux rangs sont completes de zeros avant comparaison.

    L'ecart reste signale : deux copies d'un meme numero doivent s'ecrire
    pareil. Mais aucune direction n'est annoncee, parce qu'il n'y en a pas.
    """
    a, b = rang(source), rang(copie)
    if a is None or b is None:
        return ""
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    if a == b:
        return ""
    return " (plus ancienne)" if b < a else " (plus recente que la source)"


def auto_epreuve(brain: Path) -> None:
    print("\nAUTO-ÉPREUVE — sur des fichiers fabriqués\n")

    import tempfile
    with tempfile.TemporaryDirectory(prefix="temoin-versions-") as tmp:
        faux = Path(tmp)

        def pose(chemin: str, contenu: str) -> None:
            p = faux / chemin
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(contenu, encoding="utf-8")

        # Le temoin negatif d'abord : sans lui, « aucun rouge » ne se distingue
        # pas de « le juge ne juge rien ».
        pose("brain-compose.yml", 'nom: faux\nversion: "2.1.0"\n')
        pose("brain-compose.local.yml", "instance: faux\nkernel_version: 2.1.0\n")
        pose("kernel.lock", 'genere: hier\nkernel_version: "2.1.0"\n')
        pose("brain-template/brain-compose.yml", 'version: "2.1.0"\n')
        verifie("témoin négatif : quatre déclarations identiques → aucun écart",
                juger(faux)[0], [])

        # 🔴 Le defaut REEL, copie mot pour mot : c'est le cas du 24/09.
        pose("brain-compose.local.yml", "instance: faux\nkernel_version: 2.0.0\n")
        ecarts, muettes = juger(faux)
        verifie("témoin du défaut réel : local 2.0.0 contre source 2.1.0",
                [(f, v) for f, v, _, _ in ecarts],
                [("brain-compose.local.yml", "2.0.0")])
        verifie("… et il dit dans quel SENS la copie est décalée",
                ecarts[0][3], " (plus ancienne)")

        pose("brain-compose.local.yml", "instance: faux\nkernel_version: 2.1.0\n")
        pose("kernel.lock", 'kernel_version: "2.0.9"\n')
        verifie("un lock qui précède une montée de version est un écart",
                [f for f, _, _, _ in juger(faux)[0]], ["kernel.lock"])

        pose("kernel.lock", 'kernel_version: "2.1.0"\n')
        pose("brain-template/brain-compose.yml", 'version: "1.9.0"\n')
        verifie("un template décalé aussi — c'est ce qu'un fork reçoit",
                [f for f, _, _, _ in juger(faux)[0]],
                ["brain-template/brain-compose.yml"])

        # 🔴 LE temoin qui compte le plus : une copie ABSENTE ne doit pas verdir.
        # `brain-compose.local.yml` est gitignore — il manque sur tout fork et sur
        # tout clone frais. Un controle qui compte l'absence comme un accord
        # annonce un vert qui ne mesure rien.
        pose("brain-template/brain-compose.yml", 'version: "2.1.0"\n')
        (faux / "brain-compose.local.yml").unlink()
        ecarts, muettes = juger(faux)
        verifie("une copie ABSENTE n'est pas un accord : aucun écart…",
                ecarts, [])
        verifie("… mais elle est nommée comme non mesurable",
                [f for f, _ in muettes], ["brain-compose.local.yml"])

        # La lecture, dans les deux ecritures que le brain emploie reellement.
        verifie("une version entre guillemets se lit",
                lire(faux / "brain-compose.yml", SOURCE[1]), "2.1.0")
        pose("nu.yml", "version: 3.4.5\n")
        verifie("… et une version nue aussi",
                lire(faux / "nu.yml", SOURCE[1]), "3.4.5")
        verifie("une cle absente rend None, pas une chaine vide",
                lire(faux / "kernel.lock", SOURCE[1]), None)
        verifie("le sens ne s'invente pas quand la version n'est pas comparable",
                sens("2.1.0", "deux-un-zero"), "")
        # 🔴 Trouve en relisant en JUGE : « 2.1 » et « 2.1.0 » sont la meme
        # version, et la premiere version du controle annoncait « plus ancienne ».
        verifie("« 2.1 » n'est pas plus ancienne que « 2.1.0 » — meme version",
                sens("2.1.0", "2.1"), "")
        verifie("… ni plus recente dans l'autre sens",
                sens("2.1", "2.1.0"), "")
        verifie("… mais un vrai recul se dit toujours",
                sens("2.1.0", "2.0.9"), " (plus ancienne)")
        verifie("… et une vraie avance aussi",
                sens("2.1.0", "2.2"), " (plus recente que la source)")


def juger(brain: Path) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str]]]:
    """(ecarts, non mesurables). Separe de l'affichage pour etre eprouve sans brain."""
    attendue = lire(brain / SOURCE[0], SOURCE[1])
    if attendue is None:
        return [], [(SOURCE[0], "la source elle-meme est illisible")]
    ecarts, muettes = [], []
    for nom, motif, role, _ in COPIES:
        v = lire(brain / nom, motif)
        if v is None:
            muettes.append((nom, "fichier ou cle absent"))
        elif v != attendue:
            ecarts.append((nom, v, role, sens(attendue, v)))
    return ecarts, muettes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", type=Path, default=Path.home() / "Dev/Brain")
    args = ap.parse_args()
    brain = args.brain.expanduser().resolve()

    print("VERSIONS DU KERNEL — les quatre déclarations disent-elles la même "
          "chose ?\n")

    attendue = lire(brain / SOURCE[0], SOURCE[1])
    if attendue is None:
        print(f"SKIP — {SOURCE[0]} illisible : c'est la source, rien ne se compare "
              f"sans elle.")
        auto_epreuve(brain)
        print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
        return 1 if _ko else 0

    print(f"  source ({SOURCE[0]}) : {attendue}\n")
    ecarts, muettes = juger(brain)

    for nom, motif, role, _ in COPIES:
        v = lire(brain / nom, motif)
        drapeau = "⚪" if v is None else ("🔴" if v != attendue else "  ")
        print(f"  {drapeau} {nom:<34} {v if v is not None else '(absent)'}")

    print()
    if ecarts:
        print(f"  ❌ {len(ecarts)} copie(s) ne suivent pas la source :")
        for nom, v, role, direction in ecarts:
            print(f"     {nom} : {v}{direction} contre {attendue}")
            print(f"       {role}")
        print("     Ce ne sont pas des sources independantes — ce sont des COPIES")
        print("     de brain-compose.yml. Ce controle mesure si elles ont suivi.")
    else:
        print(f"  ✅ les {len(COPIES) - len(muettes)} copie(s) mesurables suivent "
              f"la source")

    if muettes:
        print(f"\n  ⚪ {len(muettes)} non mesurable(s) — jamais comptee(s) comme "
              f"d'accord :")
        for nom, raison in muettes:
            print(f"     {nom:<34} {raison}")
        print("     `brain-compose.local.yml` est gitignore : il manque sur tout")
        print("     fork et tout clone frais. Compter son absence comme un accord")
        print("     serait un vert qui ne mesure rien.")

    auto_epreuve(brain)
    print(f"\n  {_ok} vérification(s), {_ko} échec(s)")
    if not ecarts and not _ko:
        print(f"\n  ✅ les {len(COPIES) + 1 - len(muettes)} déclarations de version "
              f"concordent — source {attendue}")
    return 1 if (ecarts or _ko) else 0


if __name__ == "__main__":
    sys.exit(main())
