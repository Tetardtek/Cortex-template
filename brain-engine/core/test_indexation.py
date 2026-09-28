#!/usr/bin/env python3
"""Ce que l'indexation garantit.

    python3 core/test_indexation.py

**Tout est éprouvé sans modèle et sans service** : le découpage est du texte
vers du texte, et l'écriture se teste sur une base jetable avec un encodeur
factice. Aucune ligne n'est écrite dans le brain.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.indexation import (                               # noqa: E402
    Chunk, Decoupage, Indexeur, corps_utile, decoupe, par_sections,
    par_taille, titre_de_section,
)
from core.persistance import SQLITE, Config, Depot          # noqa: E402

_ok = _ko = 0
SCHEMA = """
CREATE TABLE embeddings (
    chunk_id TEXT PRIMARY KEY, filepath TEXT, title TEXT, chunk_text TEXT,
    vector BLOB, model TEXT, indexed INTEGER, scope TEXT,
    content_hash TEXT, created_at TEXT, updated_at TEXT)
"""


class EncodeurFactice:
    """Rend un vecteur constant. Compte ses appels — c'est ce qui prouve le saut."""
    modele = "factice"

    def __init__(self) -> None:
        self.appels = 0

    def encode(self, texte: str):
        self.appels += 1
        return [0.1, 0.2, 0.3]


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def titres() -> None:
    print("\nUN DÉLIMITEUR N'EST PAS UN TITRE — 558 chunks le portaient\n")

    verifie("le frontmatter est sauté",
            titre_de_section("---\nname: x\n---\n\n# Le vrai titre\ntexte"),
            "Le vrai titre")
    verifie("un titre H2 est rendu sans ses dièses",
            titre_de_section("## Une section\ndu texte"), "Une section")
    verifie("une section qui ouvre sur du texte n'a pas de titre",
            titre_de_section("du texte直\n\n## Un titre plus bas"), "")
    verifie("un frontmatter jamais refermé ne rend rien",
            titre_de_section("---\nname: x\ntexte sans fin"), "")

    verifie("le corps ignore les séparateurs markdown",
            corps_utile("## Titre\n\n---\n===\n"), 0)
    verifie("le corps compte le vrai texte",
            corps_utile("## Titre\nabcde") >= 5, True)


def decoupages() -> None:
    print("\nLE DÉCOUPAGE\n")

    cfg = Decoupage(tokens=10, chevauchement=2)     # 40 caractères par morceau
    texte = "\n".join(f"ligne numero {i} avec du contenu" for i in range(12))
    morceaux = par_taille(texte, "f.md", "Mon titre", cfg)
    verifie("un texte long est découpé", len(morceaux) > 1, True)
    verifie("CHAQUE morceau garde le titre —",
            all(m.titre == "Mon titre" for m in morceaux), True)
    verifie("aucun morceau n'est vide",
            all(m.texte.strip() for m in morceaux), True)

    # Un texte sans saut de ligne ne doit pas boucler à l'infini.
    verifie("un texte sans saut de ligne se découpe quand même",
            len(par_taille("x" * 200, "f.md", "", cfg)) > 1, True)

    doc = ("---\nname: x\n---\n\n## Première\ncontenu suffisamment long pour rester\n\n"
           "## Stub\n\n---\n\n## Troisième\nun autre contenu bien assez long ici")
    sections = par_sections(doc, "f.md")
    titres_vus = [s.titre for s in sections]
    verifie("le stub est sauté", "Stub" in titres_vus, False)
    verifie("les sections utiles restent", len(sections), 3)

    verifie("un texte vide ne rend aucun chunk", decoupe("", "f.md"), [])
    verifie("la stratégie fichier replie sur le nom",
            decoupe("court", "dossier/mon-fichier.md", strategie="fichier")[0].titre,
            "mon-fichier")


def identite() -> None:
    print("\nIDENTIFIER N'EST PAS DÉTECTER UN CHANGEMENT —\n")

    debut = "x" * 64
    a = Chunk("f.md", debut + " première version")
    b = Chunk("f.md", debut + " SECONDE version, très différente")

    verifie("deux textes qui divergent APRÈS 64 caractères partagent l'identifiant",
            a.identifiant == b.identifiant, True)
    verifie("… mais PAS l'empreinte", a.empreinte == b.empreinte, False)
    verifie("l'identifiant est stable pour un même texte",
            Chunk("f.md", "abc").identifiant, Chunk("f.md", "abc").identifiant)
    verifie("le chemin change l'identifiant",
            Chunk("a.md", "abc").identifiant == Chunk("b.md", "abc").identifiant, False)


def ecriture() -> None:
    print("\nL'ÉCRITURE, SUR UNE BASE JETABLE\n")

    with tempfile.TemporaryDirectory(prefix="core-idx-") as tmp:
        depot = Depot(Config(backend=SQLITE, chemin=Path(tmp) / "i.db"))
        depot.execute(SCHEMA)
        encodeur = EncodeurFactice()
        indexeur = Indexeur(depot, encodeur)

        chunks = decoupe("## Une\nassez de contenu ici pour ne pas être un stub\n\n"
                         "## Deux\nune autre section avec du contenu suffisant",
                         "essai.md")
        rapport = indexeur.indexe(chunks)
        verifie("les deux chunks sont encodés", rapport.encodes, 2)
        verifie("aucun échec", rapport.echecs, 0)
        verifie("le modèle a été appelé deux fois", encodeur.appels, 2)
        verifie("la base les porte", depot.count("embeddings"), 2)

        # Rejouer à l'identique : rien ne doit être ré-encodé.
        rapport = indexeur.indexe(chunks)
        verifie("un second passage saute tout —", rapport.sautes, 2)
        verifie("et n'encode rien", rapport.encodes, 0)
        verifie("le modèle n'a pas été rappelé", encodeur.appels, 2)

        # Un texte modifié après les 64 premiers caractères DOIT être ré-encodé.
        debut = "## Une\n" + "y" * 60
        v1 = [Chunk("m.md", debut + " version initiale")]
        v2 = [Chunk("m.md", debut + " version corrigée, differente")]
        indexeur.indexe(v1)
        appels_avant = encodeur.appels
        rapport = indexeur.indexe(v2)
        verifie("un changement au-delà de 64 caractères est vu",
                rapport.encodes, 1)
        verifie("et le modèle est bien rappelé",
                encodeur.appels, appels_avant + 1)
        verifie("sans créer de doublon — même identifiant",
                depot.count("embeddings", "filepath = 'm.md'"), 1)

        ligne = depot.query_one("SELECT title, model, indexed, created_at, updated_at "
                                "FROM embeddings WHERE filepath = 'm.md'")
        verifie("le modèle est enregistré", ligne["model"], "factice")
        verifie("le chunk est marqué indexé", ligne["indexed"], 1)
        verifie("les deux dates sont posées",
                bool(ligne["created_at"]) and bool(ligne["updated_at"]), True)

        # À blanc : on compte sans écrire ni encoder.
        appels = encodeur.appels
        r = indexeur.indexe([Chunk("neuf.md", "un contenu jamais vu")], a_blanc=True)
        verifie("à blanc, rien n'est encodé", encodeur.appels, appels)
        verifie("à blanc, rien n'est écrit",
                depot.count("embeddings", "filepath = 'neuf.md'"), 0)
        verifie("mais le compte est rendu", r.encodes, 1)


def main() -> int:
    titres()
    decoupages()
    identite()
    ecriture()
    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(main())
