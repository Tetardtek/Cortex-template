"""Indexation — construire ce que la recherche consomme.

Rapatriée de `brain-engine/embed.py` le 07/09. L'ancien module fait **940
lignes** et mêle quatre choses : le découpage, l'encodage, la **politique de
corpus** (quels fichiers, quels scopes, quel TTL) et la purge.

── La redécision qui commande tout le reste ────────────────────────────────

**La politique de corpus n'est pas dans le CORE.** `embed.py` porte
`CORPUS_PATHS` et `EXCLUDE_PATTERNS` en dur — des listes qui décrivent
l'arborescence d'un brain précis :

    CORPUS_PATHS = [agents/, contexts/, profil/, projets/, workspace/, …]

Un programme ne peut pas porter ça. Quels fichiers indexer, sous quel scope et
avec quel TTL, c'est une décision **d'instance** — le CORE reçoit une liste de
chemins à indexer, il ne la devine pas. C'est la même règle que la persistance :
recevoir plutôt que déduire.

Conséquence : ce module ne sait pas parcourir un brain. Il sait découper un
texte, l'encoder et l'écrire. Le parcours appartient à la porte qui l'appelle.

── Ce que le découpage a coûté d'apprendre ─────────────────────────────────

**Un délimiteur n'est pas un titre.** L'extraction prenait la première ligne
d'une section, et la première section d'un fichier commence par le frontmatter :
**558 chunks portaient `---` comme titre** (03/09).

**Un titre se transmet au redécoupage.** Une section H2 trop longue était
recoupée par taille en perdant son seul repère lisible — **2 265 chunks sans
titre, 30 % de l'index**.

**Une empreinte de 64 caractères ne détecte pas un changement.** `identifiant`
ne hache que le début du texte : deux chunks qui divergent au-delà le partagent.
S'en servir pour sauter une réindexation garderait un vecteur périmé sans que
rien ne le signale — d'où `empreinte`, qui porte sur le texte entier.

**Une colonne absente du `DO UPDATE` ne se corrige jamais.** `title` y manquait
avant, `model` avant. Avec le saut de réindexation, l'oubli
devient vicieux : un changement de modèle figerait l'ancien nom, la condition de
saut ne correspondrait plus, et le brain ré-encoderait à chaque passe sans se
réparer.

**Les dates s'écrivent explicitement en UTC.** Sans ça, le `DEFAULT
CURRENT_TIMESTAMP` du schéma s'applique — l'horloge du moteur, donc l'heure
locale. Le même INSERT posait deux conventions dans une ligne : **328 chunks
avec `created_at` à 18:47 et `updated_at` à 16:47**.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.modele import Encodeur
from core.persistance import DOLT, Depot

log = logging.getLogger("myeline.indexation")

# La même table que `recherche`, mais en écriture. Deux briques partagent une
# table quand l'une la remplit et l'autre la lit — ce n'est pas un couplage,
# c'est la table qui les relie.
TABLES = frozenset({"embeddings"})

SEPARATEURS = re.compile(r"^[\-=*_\s]+$", re.MULTILINE)


@dataclass(frozen=True)
class Decoupage:
    """Les seuils du découpage. Un token vaut environ quatre caractères."""
    tokens: int = 512
    chevauchement: int = 64
    corps_minimum: int = 30          # sous ce seuil, une section H2 est un stub

    @property
    def taille_max(self) -> int:
        return self.tokens * 4

    @property
    def recouvrement(self) -> int:
        return self.chevauchement * 4


@dataclass
class Chunk:
    chemin: str
    texte: str
    titre: str = ""
    scope: str = "public"

    @property
    def identifiant(self) -> str:
        """Déterministe, sur le chemin et le DÉBUT du texte.

        ⚠️ Ne sert qu'à identifier, jamais à détecter un changement — voir
        `empreinte`.
        """
        h = hashlib.sha1(f"{self.chemin}::{self.texte[:64]}".encode()).hexdigest()[:12]
        return f"emb-{h}"

    @property
    def empreinte(self) -> str:
        """Le texte ENTIER. C'est elle qui autorise un saut de réindexation."""
        return hashlib.sha256(self.texte.encode()).hexdigest()


# ── Découpage ───────────────────────────────────────────────────────────────

def titre_de_section(section: str) -> str:
    """Le titre d'une section, ou rien.

    Le frontmatter est sauté : sa première ligne est `---`, un délimiteur. Et si
    la section ouvre sur du texte, elle n'a pas de titre — on ne va pas en
    chercher un plus bas, ce serait celui d'une sous-partie.
    """
    lignes = section.split("\n")
    if lignes and lignes[0].strip() == "---":
        try:
            lignes = lignes[lignes.index("---", 1) + 1:]
        except ValueError:                     # frontmatter jamais refermé
            return ""
    for ligne in lignes:
        nu = ligne.strip()
        if not nu:
            continue
        return nu.strip("#").strip() if nu.startswith("#") else ""
    return ""


def corps_utile(section: str) -> int:
    """La longueur du corps, séparateurs markdown et titre exclus."""
    parties = section.split("\n", 1)
    return len(SEPARATEURS.sub("", parties[1] if len(parties) > 1 else "").strip())


def par_taille(texte: str, chemin: str, titre: str = "",
               cfg: Decoupage | None = None) -> list[Chunk]:
    """Découpe en morceaux de taille bornée, en coupant sur un saut de ligne.

    Le titre est estampillé sur CHAQUE morceau : sans lui, une section longue
    perd son seul repère lisible en se faisant découper.
    """
    cfg = cfg or Decoupage()
    morceaux, debut = [], 0
    while debut < len(texte):
        fin = min(debut + cfg.taille_max, len(texte))
        if fin < len(texte):
            saut = texte.rfind("\n", debut, fin)
            if saut > debut:
                fin = saut
        corps = texte[debut:fin].strip()
        if corps:
            morceaux.append(Chunk(chemin, corps, titre))
        if fin >= len(texte):
            break
        # Toujours avancer : si le recouvrement remonterait avant `debut`, on
        # saute à `fin`. Sans ça, une boucle infinie sur un texte sans saut.
        suivant = fin - cfg.recouvrement
        debut = suivant if suivant > debut else fin
    return morceaux


def par_sections(texte: str, chemin: str, cfg: Decoupage | None = None) -> list[Chunk]:
    """Découpe un markdown par section `## `, en repliant les trop longues."""
    cfg = cfg or Decoupage()
    morceaux: list[Chunk] = []
    for section in re.split(r"\n(?=## )", texte):
        section = section.strip()
        if not section:
            continue
        # Repli sur le nom du fichier : une section sans titre reste repérable.
        titre = titre_de_section(section) or Path(chemin).stem
        if len(section) > cfg.taille_max:
            morceaux.extend(par_taille(section, chemin, titre, cfg))
        elif section.startswith("## ") and corps_utile(section) < cfg.corps_minimum:
            continue                            # un stub : titre et bruit
        else:
            morceaux.append(Chunk(chemin, section, titre))
    return morceaux or [Chunk(chemin, texte, "")]


def decoupe(texte: str, chemin: str, *, strategie: str = "sections",
            cfg: Decoupage | None = None) -> list[Chunk]:
    """Le point d'entrée. `chemin` est RELATIF — le CORE ne connaît aucune racine."""
    cfg = cfg or Decoupage()
    texte = texte.strip()
    if not texte:
        return []
    if strategie == "sections":
        return par_sections(texte, chemin, cfg)
    titre = Path(chemin).stem
    if len(texte) > cfg.taille_max:
        return par_taille(texte, chemin, titre, cfg)
    return [Chunk(chemin, texte, titre)]


# ── Écriture ────────────────────────────────────────────────────────────────

@dataclass
class Rapport:
    encodes: int = 0
    sautes: int = 0
    echecs: int = 0
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (f"{self.encodes} encodé(s), {self.sautes} sauté(s) "
                f"(inchangés), {self.echecs} échec(s)")


class Indexeur:
    """Encode des chunks et les écrit. Ne parcourt rien."""

    def __init__(self, depot: Depot, encodeur: Encodeur | None = None) -> None:
        self.depot = depot
        self.encodeur = encodeur or Encodeur()

    def empreintes_connues(self, chemins: list[str]) -> dict[str, str]:
        """Ce que la base porte déjà, pour sauter ce qui n'a pas bougé."""
        if not chemins:
            return {}
        marques = ",".join("%s" for _ in chemins)
        return {r["chunk_id"]: r["content_hash"] for r in self.depot.query(
            f"SELECT chunk_id, content_hash FROM embeddings "
            f"WHERE filepath IN ({marques})", tuple(chemins))}

    def indexe(self, chunks: list[Chunk], *, a_blanc: bool = False) -> Rapport:
        """Encode ce qui a changé, écrit, et rend le compte.

        Le saut repose sur `empreinte` — le texte entier — jamais sur
        `identifiant`, qui ne hache que les 64 premiers caractères.
        """
        rapport = Rapport()
        connues = self.empreintes_connues(sorted({c.chemin for c in chunks}))

        for chunk in chunks:
            if connues.get(chunk.identifiant) == chunk.empreinte:
                rapport.sautes += 1
                continue
            if a_blanc:
                rapport.encodes += 1
                continue
            vecteur = self.encodeur.encode(chunk.texte)
            if vecteur is None:
                rapport.echecs += 1
                rapport.details.append(f"encodage refusé : {chunk.chemin}")
                continue
            self._ecris(chunk, vecteur)
            rapport.encodes += 1
        return rapport

    def _ecris(self, chunk: Chunk, vecteur: list[float]) -> None:
        import struct
        blob = struct.pack(f"{len(vecteur)}f", *vecteur)
        maintenant = ("UTC_TIMESTAMP()" if self.depot.config.backend == DOLT
                      else "datetime('now')")
        # ⚠️ `title` et `model` DOIVENT figurer dans le DO UPDATE : une colonne
        # qui n'y est pas ne se corrige jamais, et avec le saut de réindexation
        # l'oubli se fige.
        # ⚠️ Les dates sont explicites : le DEFAULT du schéma est l'horloge du
        # moteur, donc l'heure locale.
        self.depot.execute(
            f"INSERT INTO embeddings (chunk_id, filepath, title, chunk_text, "
            f"  `vector`, model, `indexed`, scope, content_hash, created_at, updated_at) "
            f"VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s,{maintenant},{maintenant}) "
            f"ON CONFLICT(chunk_id) DO UPDATE SET "
            f"  title = excluded.title, chunk_text = excluded.chunk_text, "
            f"  content_hash = excluded.content_hash, "
            f"  `vector` = excluded.`vector`, model = excluded.model, "
            f"  scope = excluded.scope, updated_at = excluded.updated_at",
            (chunk.identifiant, chunk.chemin, chunk.titre, chunk.texte, blob,
             self.encodeur.modele, chunk.scope, chunk.empreinte))
