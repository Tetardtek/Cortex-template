"""Traces et écriture gouvernée — deux des six capacités du CORE.

Rapatriées de `brain-engine/db.py` le 06/09, où elles vivaient mêlées à la
persistance. Les séparer n'est pas de la cosmétique : c'est ce mélange qui rend
l'ancien module impossible à tester sans une base Dolt vivante.

Un `Journal` **compose** un `Depot`. La persistance ne sait rien du
versionnement ; le journal l'ajoute par-dessus.

── Ce que la discipline garantit ───────────────────────────────────────────

    confinement   un commit ne stage QUE les tables qu'il nomme
    gel           avant toute suppression, un commit fige ce qui traînait

Sans le confinement, un commit « embed : N vecteurs » emportait aussi les claims
et les compteurs qui traînaient dans le working set — révocable en théorie,
introuvable en pratique. Sans le gel, une purge n'est pas annulable seule.

Ces deux garanties sont éprouvées par `tools/test_dolt_discipline.py` depuis
, sur une branche jetable depuis.

── ⚠️ Ce qui change en rapatriant ──────────────────────────────────────────

**La dégradation silencieuse est retirée.** L'ancien `purge()` sur SQLite
« dégénérait en un simple execute » — donc une suppression **sans gel**, sans
que l'appelant l'apprenne. Il se croyait protégé par une garantie qui n'existait
pas sur son backend.

Ici, un journal sur un backend sans versionnement le **dit** à la construction,
et `purge()` refuse plutôt que de faire semblant. Un dispositif de sécurité qui
s'efface en silence est pire que son absence : on compte dessus.

C'est le motif que ce chantier traque partout — une garantie déclarée quelque
part, absente là où elle s'exécute.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from core.persistance import DOLT, Depot

log = logging.getLogger("myeline.traces")

# `dolt_status` est une table SYSTÈME de Dolt, pas une table du brain : elle
# existe sans qu'on la crée. La brique ne possède donc rien qu'un schéma doive
# déclarer.
TABLES: frozenset[str] = frozenset()

# Les tables qu'un statement ÉCRIT. La lecture ne compte pas : un commit ne
# stage que ce qui change.
_TABLE = re.compile(
    r"\b(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+`?([A-Za-z_]\w*)`?",
    re.IGNORECASE)

# La queue d'un upsert contient un second `UPDATE … SET` qui ne nomme aucune
# table — sans cette coupure, `_tables_ecrites` rendrait un faux nom.
_QUEUE_UPSERT = re.compile(r"\bON\s+(?:CONFLICT|DUPLICATE\s+KEY)\b", re.IGNORECASE)


class SansVersionnement(RuntimeError):
    """Levée quand on demande une garantie que le backend ne peut pas tenir."""


@dataclass
class Gel:
    """Ce qu'un gel a figé. Vide si rien ne traînait — et c'est un cas normal."""
    raison: str
    tables: list[str]

    def __bool__(self) -> bool:
        return bool(self.tables)


def tables_ecrites(sql: str) -> list[str]:
    """Les tables qu'un statement écrit. Vide si la forme n'est pas reconnue.

    Une liste vide n'est pas une erreur : elle veut dire « je ne sais pas », et
    l'appelant doit alors élargir le commit plutôt que de deviner.
    """
    tete = _QUEUE_UPSERT.split(sql, maxsplit=1)[0]
    return sorted({m.lower() for m in _TABLE.findall(tete)})


class Journal:
    """La discipline d'écriture, posée sur un dépôt."""

    def __init__(self, depot: Depot) -> None:
        self.depot = depot
        self.versionne = depot.config.backend == DOLT
        if not self.versionne:
            # Dit une fois, à la construction — pas au moment où ça compte.
            log.warning(
                "journal sur backend `%s` : aucun versionnement. Le gel et le "
                "commit confiné n'ont pas d'objet, et `purge()` refusera.",
                depot.config.backend)

    # ── ce qui traîne ───────────────────────────────────────────────────────

    def tables_sales(self) -> list[str]:
        """Tables modifiées et non commitées."""
        if not self.versionne:
            return []
        return sorted({r["table_name"]
                       for r in self.depot.query("SELECT table_name FROM dolt_status")})

    def _tables_inconnues(self, noms: list[str]) -> list[str]:
        if not noms:
            return []
        marques = ",".join("%s" for _ in noms)
        connues = {r["TABLE_NAME"].lower() for r in self.depot.query(
            "SELECT TABLE_NAME FROM information_schema.tables "
            f"WHERE TABLE_SCHEMA = DATABASE() AND LOWER(TABLE_NAME) IN ({marques})",
            tuple(n.lower() for n in noms))}
        return [n for n in noms if n.lower() not in connues]

    # ── écrire l'histoire ───────────────────────────────────────────────────

    def commit(self, message: str, tables: list[str] | None = None) -> bool:
        """Un commit confiné aux tables nommées. `None` stage tout.

        Une table introuvable n'échoue pas l'écriture : `DOLT_ADD` lèverait, et
        l'appelant verrait une erreur là où il avait auparavant un commit trop
        large. On élargit — **en le disant fort**. Cas connu : un
        `DELETE FROM schema.table` fait dériver « schema » au lieu de la table.
        """
        if not self.versionne:
            return False
        if tables:
            inconnues = self._tables_inconnues(tables)
            if inconnues:
                log.error("commit : table(s) introuvable(s) %s pour « %s » — "
                          "élargi à tout plutôt qu'échoué", inconnues, message)
                tables = None
        try:
            for table in (tables or ["."]):
                self.depot.execute("CALL DOLT_ADD(%s)", (table,))
            self.depot.execute("CALL DOLT_COMMIT('-m', %s)", (message,))
            return True
        except Exception as exc:                           # noqa: BLE001
            if "nothing to commit" in str(exc).lower():
                return False                               # pas une erreur
            log.error("commit refusé : %s", exc)
            raise

    def gele(self, raison: str) -> Gel:
        """Fige ce qui traîne avant une opération destructive.

        C'est le seul appel qui stage tout à dessein : on capture ce qui
        traînait, **y compris ce qu'on n'a pas écrit soi-même**. Un commit vide
        ne protégeant rien, on n'en crée pas quand rien ne traîne.
        """
        if not self.versionne:
            return Gel(raison, [])
        sales = self.tables_sales()
        if not sales:
            return Gel(raison, [])
        self.commit(f"gel avant {raison} — {', '.join(sales)}")
        log.info("gel : %s (%s)", raison, ", ".join(sales))
        return Gel(raison, sales)

    def purge(self, sql: str, params: tuple = (), *,
              raison: str, tables: list[str] | None = None) -> int:
        """Une suppression encadrée : geler, opérer, dater.

            1. figer     un commit « gel avant <raison> »
            2. purger    le DELETE
            3. dater     un commit « purge : <raison> », confiné

        Le gel est ce qui rend la purge annulable seule.
        """
        if not raison:
            raise ValueError(
                "purge() exige une raison — un commit sans motif ne se relit pas")
        if not self.versionne:
            # ⚠️ Refuser, et non dégrader. L'ancien moteur faisait ici un
            # `execute` nu : l'appelant croyait geler, rien ne gelait, et rien
            # ne le disait.
            raise SansVersionnement(
                f"purge « {raison} » demandée sur un backend "
                f"`{self.depot.config.backend}` sans versionnement : le gel est "
                "impossible. Utiliser `depot.execute()` en connaissance de cause.")

        self.gele(raison)
        cibles = tables or tables_ecrites(sql)
        if not cibles:
            log.error("purge : tables indéterminées dans %r — commit élargi", sql[:120])
        n = self.depot.execute(sql, params)
        self.commit(f"purge : {raison}", cibles or None)
        log.info("purge : %s (%s lignes)", raison, n)
        return n
