"""Le pont vers le modèle d'embedding.

Sorti de `recherche.py` le 07/09, parce que le **test de la fondation** l'a
demandé.

`core/test_briques.py` applique la règle de la vision — *« retirer n'importe
quelle brique doit laisser un système qui démarre »* — et a trouvé que
`indexation` tirait `recherche`. Pas pour chercher : uniquement pour
l'`Encodeur`. Retirer la recherche cassait donc l'indexation, alors qu'elles ne
se servent de rien l'une de l'autre.

**L'encodeur n'appartient à aucune des deux.** C'est un pont vers l'extérieur,
au même titre que la persistance en est un vers la base. Les deux briques
l'utilisent ; aucune ne le possède.

La vision dit de corriger une frontière mal placée **avant d'en poser une
autre**, pas de la documenter. C'est ce que ce fichier fait.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("myeline.modele")

# Aucune table : ce module ne parle qu'au modèle d'embedding.
TABLES: frozenset[str] = frozenset()


@dataclass
class Encodeur:
    """Le pont vers le modèle d'embedding. Reçu, jamais deviné."""
    url: str = "http://localhost:11434"
    modele: str = "nomic-embed-text"
    delai: int = 30

    def encode(self, texte: str) -> list[float] | None:
        """Le vecteur d'un texte, ou `None` si le modèle est injoignable.

        `None` et non une exception : un CORE qui ne peut pas encoder doit
        pouvoir le dire à son appelant sans s'effondrer. Mais il ne rend jamais
        un vecteur vide, qui passerait pour un résultat.
        """
        requete = urllib.request.Request(
            f"{self.url}/api/embeddings",
            data=json.dumps({"model": self.modele, "prompt": texte}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(requete, timeout=self.delai) as reponse:
                vecteur = json.loads(reponse.read()).get("embedding")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.error("modèle d'embedding injoignable (%s) : %s", self.url, exc)
            return None
        return vecteur or None
