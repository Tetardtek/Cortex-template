"""Identité et zones — la sixième et dernière capacité du CORE.

Elle a été la dernière parce qu'elle n'attendait pas du code : elle attendait une
**décision**. Le registre de `KERNEL.md` disait quel type de session peut écrire
dans quelle zone, et rien ne disait **quels chemins composent une zone**.

Tranché le 07/09 par Kevin, après mesure :

    invariant · programme   →   zone kernel
    tout le reste           →   zone instance
    plus les exceptions qui se déclarent — aujourd'hui `profil/` seul

La dérivation couvrait 20 chemins et trois des quatre que le registre nomme
KERNEL. Il en manquait exactement un : `profil/`, qui est **donnée souveraine
ET zone d'autorité**. Les deux à la fois — la preuve qu'un seul axe ne peut pas
porter les deux sens.

── Ce que ce module ne fait pas ────────────────────────────────────────────

**Il ne lit ni `NIVEAUX.yml` ni `KERNEL.md`.** Il reçoit ce qu'ils déclarent.
Un CORE qui irait les chercher supposerait une arborescence — exactement ce que
les cinq autres modules refusent.

⚠️ **Il ne remplace pas le hook.** Le hook `pre-commit-zone` garde le dépôt au
moment du commit ; ce module garde une écriture, d'où qu'elle vienne. Les deux
appliqueront la même règle, ce qui est le but : une règle, plusieurs points
d'application — le motif de.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("myeline.zones")

# Aucune table : la règle vient de `NIVEAUX.yml`, reçue et jamais lue.
TABLES: frozenset[str] = frozenset()

KERNEL = "kernel"
INSTANCE = "instance"

# Les niveaux qui font une zone kernel. Dérivé, pas déclaré chemin par chemin :
# une liste de chemins se périme, une règle sur la nature tient.
NIVEAUX_KERNEL = frozenset({"invariant", "programme"})


class EcritureRefusee(PermissionError):
    """Une session écrit hors de sa zone."""

    def __init__(self, type_session: str, chemin: str, zone: str) -> None:
        self.type_session, self.chemin, self.zone = type_session, chemin, zone
        super().__init__(
            f"une session `{type_session}` n'écrit pas en zone {zone} — {chemin}")


@dataclass
class Registre:
    """Ce que les sources déclarent. Reçu, jamais lu.

    `niveaux` : chemin → niveau, tel que `NIVEAUX.yml` le dit.
    `exceptions` : chemin → zone, pour ce que la dérivation ne couvre pas.
    `interdits` : type de session → zones interdites, tel que `KERNEL.md` le dit.
    """
    niveaux: dict[str, str] = field(default_factory=dict)
    exceptions: dict[str, str] = field(default_factory=dict)
    interdits: dict[str, set[str]] = field(default_factory=dict)

    def zone(self, chemin: str) -> str:
        """La zone d'un chemin. Les exceptions l'emportent sur la dérivation.

        La correspondance se fait sur le préfixe **le plus long** : `profil/` et
        `profil/decisions/` peuvent coexister sans que l'ordre du dictionnaire
        décide à leur place.
        """
        meilleur, resultat = -1, INSTANCE
        for source, valeur in ((self.exceptions, None), (self.niveaux, "niveau")):
            for prefixe, brut in source.items():
                if chemin == prefixe.rstrip("/") or chemin.startswith(prefixe):
                    if len(prefixe) > meilleur:
                        meilleur = len(prefixe)
                        resultat = (KERNEL if brut in NIVEAUX_KERNEL else INSTANCE) \
                            if valeur == "niveau" else brut
        return resultat

    def zones_interdites(self, type_session: str) -> set[str] | None:
        """Les zones interdites à ce type. `None` si le type n'est pas déclaré.

        `None` et non un ensemble vide : ne pas savoir n'est pas savoir qu'il
        n'y a rien. C'est ce qui laisse l'appelant s'abstenir au lieu
        d'autoriser par défaut.
        """
        return self.interdits.get(type_session)


class Gardien:
    """Applique le registre à une écriture."""

    def __init__(self, registre: Registre) -> None:
        self.registre = registre

    def verifie(self, type_session: str, chemins: list[str]) -> list[tuple[str, str]]:
        """Les chemins refusés, avec leur zone. Liste vide si tout passe.

        Un type absent du registre ne fait rien refuser — et l'appelant doit le
        savoir : il le lit dans `zones_interdites()`. Un gardien qui devine sa
        règle refuserait des gestes légitimes sur une lecture approximative.
        """
        interdites = self.registre.zones_interdites(type_session)
        if not interdites:
            if interdites is None:
                log.warning("type de session `%s` absent du registre — rien n'est jugé",
                            type_session)
            return []
        return [(c, self.registre.zone(c)) for c in chemins
                if self.registre.zone(c) in interdites]

    def autorise(self, type_session: str, chemin: str) -> bool:
        return not self.verifie(type_session, [chemin])

    def exige(self, type_session: str, chemin: str) -> None:
        """Lève `EcritureRefusee` plutôt que de rendre un booléen qu'on oublie."""
        refuses = self.verifie(type_session, [chemin])
        if refuses:
            raise EcritureRefusee(type_session, chemin, refuses[0][1])
