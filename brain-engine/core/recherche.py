"""Recherche sémantique — la quatrième capacité rapatriée.

Rapatriée de `brain-engine/search.py` le 06/09.

⚠️ **L'indexation n'est pas ici.** `embed.py` fait 940 lignes et mêle
l'encodage, les scopes, le TTL du corpus et la purge — c'est une capacité
d'écriture, elle mérite son propre module et sa propre séance. Le CORE sait
chercher dans un index existant ; il ne sait pas encore le construire.

── Trois choses que ce module refuse de faire en silence ───────────────────

**1. Comparer des vecteurs de dimensions différentes.** La boucle d'origine
utilisait `zip()`, qui **tronque à la plus courte des deux séquences** : une
requête de 3 dimensions contre un index de 768 comparait les trois premières
composantes et rendait un résultat parfaitement plausible. Un changement de
modèle d'embedding dégradait donc la recherche sans que rien ne le signale.
Ici, ça s'arrête net.

**2. Chercher sans le dire quand numpy manque.** Le repli Python pur donne le
même résultat, ~40× plus lentement. Il est légitime — mais annoncé.

**3. Accepter une requête trop courte sans avertir.** Mesuré le 04/09 sur 25
chunks, taux de retrouvaille dans les trois premiers résultats :

    1 mot    0 %       5 mots   44 %      20 mots   96 %
    2 mots   4 %       8 mots   60 %      40 mots  100 %
    3 mots  12 %      12 mots   76 %

Et **le score ne prévient pas** : une retrouvaille réussie à 5 mots vaut 0,751
en moyenne, quand une requête d'un mot peut rendre du bruit à 0,889. Le bruit
score parfois plus haut qu'un bon résultat, donc rien dans le chiffre n'alerte.
C'est pourquoi l'avertissement porte sur la **requête**, jamais sur le score
.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field

from core.modele import Encodeur
from core.persistance import Depot

log = logging.getLogger("myeline.recherche")

# Lue, jamais écrite ici : l'écriture appartient à `indexation`.
TABLES = frozenset({"embeddings"})

# Les deux seuils sortent du tableau ci-dessus. Sous 3 mots la retrouvaille est
# nulle à un chiffre près ; sous 6 elle passe à peine la moitié. Au-delà c'est
# « perfectible », et un avertissement qui se déclencherait là se déclencherait
# presque toujours — il ne protégerait plus rien.
MOTS_MUETTE = 3
MOTS_COURTE = 6


class DimensionsIncompatibles(ValueError):
    """La requête et l'index ne parlent pas le même modèle."""


@dataclass
class Resultat:
    chunk_id: str
    chemin: str
    titre: str
    texte: str
    score: float


def vecteur_depuis_blob(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def similarite(a: list[float], b: list[float]) -> float:
    """Cosinus, en Python pur.

    ⚠️ Les longueurs sont comparées AVANT de zipper. `zip()` tronque en
    silence, et c'est ce qui laissait passer un index encodé par un autre
    modèle.
    """
    if len(a) != len(b):
        raise DimensionsIncompatibles(
            f"requête {len(a)}, index {len(b)} — modèle d'embedding différent "
            "de celui de l'indexation")
    produit = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return 0.0 if na == 0.0 or nb == 0.0 else produit / (na * nb)


@dataclass
class Index:
    """Les vecteurs indexés, lus depuis un dépôt."""
    depot: Depot
    _cache: dict = field(default_factory=dict, repr=False)

    def empreinte(self, scopes: list[str] | None = None) -> tuple | None:
        """(dernière écriture, nombre de lignes) sur le prédicat exact de la lecture.

        Une agrégation coûte quelques millisecondes ; relire les blobs en coûte
        150. `None` si la mesure échoue — l'appelant relit alors, plutôt que de
        servir un cache dont il ne peut pas prouver la fraîcheur.
        """
        where, params = "indexed = 1 AND `vector` IS NOT NULL", ()
        if scopes:
            marques = ",".join("%s" for _ in scopes)
            where += f" AND scope IN ({marques})"
            params = tuple(scopes)
        try:
            ligne = self.depot.query_one(
                f"SELECT MAX(updated_at) AS m, COUNT(*) AS n "
                f"FROM embeddings WHERE {where}", params)
        except Exception as exc:                           # noqa: BLE001
            log.warning("empreinte de l'index illisible (%s) — relecture complète", exc)
            return None
        return (str(ligne["m"]), int(ligne["n"])) if ligne else None

    def charge(self, scopes: list[str] | None = None) -> tuple[list[dict], object | None]:
        """Les métadonnées et la matrice. La matrice est `None` sans numpy.

        ⚠️ **Le cache n'était pas rapatrié, et c'est le banc qui l'a dit.**
        Sans lui, chaque recherche relisait 6 000 blobs : 115 ms contre 82 ms
        pour le moteur vivant, soit 40 % plus lent que ce qu'on remplace. Une
        régression silencieuse — le genre que ce chantier traque.

        Le cache est gardé par une **empreinte**, pas par une durée : il ne sert
        que s'il peut prouver sa fraîcheur.
        """
        cle = tuple(sorted(scopes)) if scopes else None
        empreinte = self.empreinte(scopes)
        if empreinte is not None:
            garde = self._cache.get(cle)
            if garde and garde[0] == empreinte:
                return garde[1], garde[2]

        where, params = "indexed = 1", ()
        if scopes:
            marques = ",".join("%s" for _ in scopes)
            where += f" AND scope IN ({marques})"
            params = tuple(scopes)

        # ⚠️ `vector` est un MOT RÉSERVÉ chez Dolt — sans les accents graves,
        # « syntax error at position 58 near 'FROM' ». L'ancien `search.py` les
        # portait depuis toujours ; ne pas les reprendre est exactement le
        # risque du rapatriement, et c'est le test réel qui l'a dit.
        lignes = self.depot.query(
            f"SELECT chunk_id, filepath, title, chunk_text, `vector` "
            f"FROM embeddings WHERE {where} ORDER BY chunk_id", params)
        meta = [{"chunk_id": l["chunk_id"], "chemin": l["filepath"],
                 "titre": l.get("title") or "", "texte": l["chunk_text"]}
                for l in lignes]
        if not lignes:
            return meta, None
        try:
            import numpy as np
        except ImportError:
            log.warning("numpy absent — recherche en Python pur, ~40× plus lente")
            self._vecteurs = [vecteur_depuis_blob(l["vector"]) for l in lignes]
            return meta, None

        dims = len(lignes[0]["vector"]) // 4
        matrice = np.frombuffer(b"".join(l["vector"] for l in lignes),
                                dtype=np.float32).reshape(-1, dims)
        if empreinte is not None:
            # Les normes voyagent avec la matrice : elles n'en dépendent que
            # d'elle, donc elles se périment exactement quand elle se périme.
            # Une seule empreinte garde les deux — il n'y a pas d'état à
            # invalider séparément, donc pas de fraîcheur à prouver deux fois.
            self._cache[cle] = (empreinte, meta, matrice,
                                np.linalg.norm(matrice, axis=1))
        return meta, matrice

    def normes(self, scopes: list[str] | None = None,
               matrice: object | None = None) -> object | None:
        """‖ligne‖ pour chaque vecteur de l'index — calculé une seule fois.

        ⚠️ **** `recherche()` faisait `np.linalg.norm(matrice, axis=1)`
        à CHAQUE requête : 6 104 × 768 valeurs reparcourues pour un résultat
        qui ne change pas tant que la matrice ne change pas. Mesuré le 07/09 —
        3,448 ms contre 0,436 en gardant les normes, **×7,9 à résultat
        identique** (top-5 et scores identiques à 1e-6 près).

        Trouvé en construisant un banc Rust, pas en cherchant une optimisation :
        pour comparer deux langages il fallait isoler le calcul, et l'isoler a
        montré que l'essentiel du coût était du travail refait.

        ⚠️ **Ce n'est pas un goulot** : une recherche complète fait ~27 ms et
        l'encodage par Ollama ~63. On retire ce travail parce qu'il est gratuit
        de le retirer, pas parce qu'il se voyait.

        Rend `None` sans numpy — l'appelant retombe alors sur le chemin lent.
        """
        try:
            import numpy as np
        except ImportError:
            return None
        cle = tuple(sorted(scopes)) if scopes else None
        garde = self._cache.get(cle)
        if garde and len(garde) > 3 and garde[3] is not None:
            return garde[3]
        # Pas de cache — soit l'empreinte est illisible, soit l'index n'a pas
        # encore été chargé. On calcule sans ranger : ranger sous une empreinte
        # qu'on ne peut pas prouver servirait un jour un index périmé.
        if matrice is None:
            _, matrice = self.charge(scopes)
        return None if matrice is None else np.linalg.norm(matrice, axis=1)


def alerte_requete(requete: str) -> str | None:
    """Ce qu'il faut dire de la requête avant de croire au résultat."""
    mots = len(requete.split())
    if mots < MOTS_MUETTE:
        return (f"{mots} mot(s) : la retrouvaille est quasi nulle sous "
                f"{MOTS_MUETTE} mots. Le score ne le dira pas — du bruit peut "
                "scorer plus haut qu'un bon résultat.")
    if mots < MOTS_COURTE:
        return (f"{mots} mots : moins d'une chance sur deux de retrouver le bon "
                f"passage. Reformuler en {MOTS_COURTE}+ mots double le taux.")
    return None


class Recherche:
    """Chercher dans l'index, en disant ce qui affaiblit le résultat."""

    def __init__(self, depot: Depot, encodeur: Encodeur | None = None) -> None:
        self.index = Index(depot)
        self.encodeur = encodeur or Encodeur()

    def cherche(self, requete: str, *, combien: int = 5,
                score_min: float = 0.0,
                scopes: list[str] | None = None) -> tuple[list[Resultat], str | None]:
        """Les meilleurs passages, et l'alerte s'il y en a une.

        Rend toujours un couple : ignorer l'alerte doit être un geste, pas un
        oubli. C'est ce qui manquait quand un résultat de bruit passait pour
        une réponse.
        """
        alerte = alerte_requete(requete)

        vecteur = self.encodeur.encode(requete)
        if vecteur is None:
            return [], alerte or "le modèle d'embedding est injoignable"

        meta, matrice = self.index.charge(scopes)
        if not meta:
            return [], alerte or "l'index est vide"

        if matrice is not None:
            import numpy as np
            q = np.asarray(vecteur, dtype=np.float32)
            if q.shape[0] != matrice.shape[1]:
                raise DimensionsIncompatibles(
                    f"requête {q.shape[0]}, index {matrice.shape[1]} — modèle "
                    "d'embedding différent de celui de l'indexation")
            normes = self.index.normes(scopes, matrice)
            if normes is None:
                normes = np.linalg.norm(matrice, axis=1)
            denom = normes * float(np.linalg.norm(q))
            scores = np.divide(matrice @ q, denom,
                               out=np.zeros(len(meta), dtype=np.float32),
                               where=denom != 0)
            gardes = np.nonzero(scores >= score_min)[0]
            ordre = gardes[np.argsort(-scores[gardes], kind="stable")][:combien]
            classes = [(int(i), float(scores[i])) for i in ordre]
        else:
            paires = [(i, similarite(vecteur, v))
                      for i, v in enumerate(getattr(self.index, "_vecteurs", []))]
            paires = [p for p in paires if p[1] >= score_min]
            classes = sorted(paires, key=lambda p: -p[1])[:combien]

        return [Resultat(meta[i]["chunk_id"], meta[i]["chemin"], meta[i]["titre"],
                         meta[i]["texte"], s) for i, s in classes], alerte
