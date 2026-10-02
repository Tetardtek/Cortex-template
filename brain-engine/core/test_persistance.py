#!/usr/bin/env python3
"""Ce que la persistance du CORE garantit.

    python3 core/test_persistance.py                      # tout sauf Dolt
    python3 core/test_persistance.py --dolt ~/Dev/Brain   # + lecture réelle

**La traduction SQL se teste sans base.** C'est le point de la refonte : ce sont
des fonctions pures, de texte vers texte, là où l'ancien module lisait un
`BACKEND` global figé à l'import. Onze garanties ci-dessous ne touchent aucun
disque.

⚠️ **Le test Dolt est en LECTURE SEULE et le reste.** Il interroge la base
vivante du brain pour prouver que ce CORE la lit — c'est la seule preuve qui
vaille — mais il n'écrit rien, ne commite rien, et ne crée aucune table. Le
brain est de la data : le programme qu'on construit n'a pas à la modifier pour
démontrer qu'il fonctionne.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.tests import pourquoi_abstenue                    # noqa: E402
from core.persistance import (                             # noqa: E402
    DOLT, SQLITE, Config, Depot, traduire,
)

_ok = _ko = 0

# Levé quand un service DEMANDÉ (`--dolt`, `--brain`) n'a pas répondu : la
# suite sort alors en 3 — « rien mesuré », distinct de 0 et de 1. Le lanceur
# (`core/tests.py`) la compte à part au lieu de l'additionner en silence.
_abstenu = False


def verifie(nom: str, obtenu, attendu) -> None:
    global _ok, _ko
    if obtenu == attendu:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom}\n       obtenu  : {obtenu!r}\n       attendu : {attendu!r}")


def refuse(nom: str, fn, exception=ValueError) -> None:
    global _ok, _ko
    try:
        fn()
    except exception:
        _ok += 1
        print(f"  ✅ {nom}")
    else:
        _ko += 1
        print(f"  ❌ {nom} — rien n'a été refusé")


# ── La traduction, sans toucher un disque ───────────────────────────────────

def traduction() -> None:
    print("\nTRADUCTION DU SQL PORTABLE — fonctions pures\n")

    verifie("sqlite : les placeholders deviennent ?",
            traduire("SELECT * FROM t WHERE a = %s", SQLITE),
            "SELECT * FROM t WHERE a = ?")
    verifie("dolt : les placeholders passent tels quels",
            traduire("SELECT * FROM t WHERE a = %s", DOLT),
            "SELECT * FROM t WHERE a = %s")
    verifie("sqlite : NOW() devient datetime('now')",
            traduire("SELECT NOW()", SQLITE), "SELECT datetime('now')")
    verifie("sqlite : REPLACE INTO devient INSERT OR REPLACE",
            traduire("REPLACE INTO t (a) VALUES (%s)", SQLITE),
            "INSERT OR REPLACE INTO t (a) VALUES (?)")
    verifie("sqlite : DATE_ADD devient datetime(+n)",
            traduire("SELECT DATE_ADD(x, INTERVAL 4 HOUR)", SQLITE),
            "SELECT datetime(x, '+' || 4 || ' hours')")
    verifie("dolt : DATE_ADD reste intact",
            traduire("SELECT DATE_ADD(x, INTERVAL 4 HOUR)", DOLT),
            "SELECT DATE_ADD(x, INTERVAL 4 HOUR)")

    # Le cas qui a demandé un découpage manuel : une parenthèse dans un argument.
    verifie("sqlite : TIMESTAMPDIFF avec NOW() en argument",
            traduire("SELECT TIMESTAMPDIFF(HOUR, a, NOW()) FROM t", SQLITE),
            "SELECT ((julianday(datetime('now')) - julianday(a)) * 24) FROM t")
    verifie("sqlite : deux TIMESTAMPDIFF dans la même requête",
            traduire("SELECT TIMESTAMPDIFF(DAY,a,b), TIMESTAMPDIFF(DAY,c,d)", SQLITE),
            "SELECT (julianday(b) - julianday(a)), (julianday(d) - julianday(c))")

    # 🔴 Les unités que personne n'avait converties.
    #
    # Jusqu'au 11/09, HOUR et MINUTE avaient un facteur et TOUT le reste
    # tombait dans un `else` qui rendait des JOURS. `TIMESTAMPDIFF(SECOND, …)`
    # rendait donc un nombre 86 400 fois trop petit — sans erreur ni log.
    # Mesuré : le brain n'emploie que MINUTE et HOUR, rien de vivant ne
    # changeait ; mais le CORE sert d'autres instances que celle-ci.
    verifie("sqlite : SECOND est converti, pas rendu en jours",
            traduire("SELECT TIMESTAMPDIFF(SECOND, a, b)", SQLITE),
            "SELECT ((julianday(b) - julianday(a)) * 86400)")
    verifie("sqlite : WEEK est converti",
            traduire("SELECT TIMESTAMPDIFF(WEEK, a, b)", SQLITE),
            "SELECT ((julianday(b) - julianday(a)) / 7)")
    verifie("sqlite : une unité inconnue n'est PAS traduite en silence",
            traduire("SELECT TIMESTAMPDIFF(QUARTER, a, b)", SQLITE),
            "SELECT TIMESTAMPDIFF(QUARTER, a, b)")
    verifie("dolt : ON CONFLICT devient ON DUPLICATE KEY",
            traduire("INSERT INTO t (a) VALUES (1) ON CONFLICT(a) DO UPDATE SET a = excluded.a",
                     DOLT),
            "INSERT INTO t (a) VALUES (1) ON DUPLICATE KEY UPDATE a = VALUES(a)")
    verifie("sqlite : ON CONFLICT reste, c'est sa syntaxe",
            "ON CONFLICT" in traduire(
                "INSERT INTO t (a) VALUES (1) ON CONFLICT(a) DO UPDATE SET a = excluded.a",
                SQLITE), True)


# ── La configuration refuse de deviner ──────────────────────────────────────

def configuration() -> None:
    print("\nLA CONFIGURATION EST REÇUE, JAMAIS DEVINÉE\n")

    refuse("sqlite sans chemin est refusé, pas complété en douce",
           lambda: Config(backend=SQLITE))
    refuse("un backend inconnu est refusé",
           lambda: Config(backend="postgres", chemin=Path("/tmp/x")))
    verifie("dolt n'a pas besoin de chemin",
            Config(backend=DOLT).backend, DOLT)

    # Deux dépôts dans le même processus — impossible avec l'ancien module,
    # dont le backend était figé à l'import.
    a = Depot(Config(backend=SQLITE, chemin=Path("/tmp/a.db")))
    b = Depot(Config(backend=DOLT, port=9999))
    verifie("deux dépôts coexistent, de backends différents",
            (a.config.backend, b.config.backend), (SQLITE, DOLT))


# ── Un dépôt SQLite réel, sur une base jetable ──────────────────────────────

def sqlite_reel() -> None:
    print("\nUN DÉPÔT SQLITE, SUR UNE BASE JETABLE\n")

    with tempfile.TemporaryDirectory(prefix="core-persistance-") as tmp:
        chemin = Path(tmp) / "essai.db"
        depot = Depot(Config(backend=SQLITE, chemin=chemin))

        depot.execute("CREATE TABLE claims (sess_id TEXT PRIMARY KEY, statut TEXT)")
        verifie("la table est vue", depot.table_existe("claims"), True)
        verifie("une table absente est vue absente",
                depot.table_existe("nexiste_pas"), False)

        depot.execute("INSERT INTO claims (sess_id, statut) VALUES (%s, %s)",
                      ("s1", "open"))
        depot.execute("INSERT INTO claims (sess_id, statut) VALUES (%s, %s)",
                      ("s2", "closed"))
        verifie("le SQL portable écrit vraiment", depot.count("claims"), 2)
        verifie("le WHERE de count est appliqué",
                depot.count("claims", "statut = 'open'"), 1)
        verifie("query_one rend un dict",
                depot.query_one("SELECT statut FROM claims WHERE sess_id = %s",
                                ("s1",)), {"statut": "open"})
        verifie("query_one sur rien rend None",
                depot.query_one("SELECT * FROM claims WHERE sess_id = %s",
                                ("absent",)), None)
        verifie("query rend une liste de dicts",
                len(depot.query("SELECT * FROM claims")), 2)
        verifie("query_one rend bien la premiere ligne de query",
                depot.query_one("SELECT * FROM claims ORDER BY sess_id"),
                depot.query("SELECT * FROM claims ORDER BY sess_id")[0])

        # 🔴 Les cles etrangeres, et le temoin qui prouve qu'on les tient.
        #
        # `foreign_keys` est OFF par defaut dans SQLite, et le reglage est par
        # CONNEXION. Sans le pragma, une ligne orpheline entre sans un bruit —
        # ce n'est pas une panne, c'est une base qui se corrompt lentement.
        # Le temoin ouvre la MEME base sans le pragma : si l'insertion passe
        # la-bas et echoue ici, c'est le pragma qui fait la difference, et non
        # l'absence de cle etrangere dans le schema.
        depot.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, "
                      "sess_id TEXT REFERENCES claims(sess_id))")
        orpheline = ("INSERT INTO notes (id, sess_id) VALUES (%s, %s)",
                     (1, "jamais-ouverte"))
        refusee = False
        try:
            depot.execute(*orpheline)
        except sqlite3.IntegrityError:
            refusee = True
        verifie("une ligne orpheline est refusee", refusee, True)

        sans_pragma = sqlite3.connect(str(chemin))
        try:
            sans_pragma.execute(
                "INSERT INTO notes (id, sess_id) VALUES (?, ?)",
                (2, "jamais-ouverte-non-plus"))
            sans_pragma.commit()
            passe_sans = True
        except sqlite3.IntegrityError:
            passe_sans = False
        finally:
            sans_pragma.close()
        verifie("temoin : sans le pragma, elle passerait", passe_sans, True)


# ── La base vivante, en lecture seule ───────────────────────────────────────

def dolt_lecture(brain: Path) -> None:
    print("\nLA BASE VIVANTE DU BRAIN — LECTURE SEULE\n")

    depot = Depot(Config(backend=DOLT))
    try:
        tables = depot.query("SHOW TABLES")
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⏭  ABSTENTION — {pourquoi_abstenue(exc)} — rien mesuré.")
        print("     C'est une abstention, pas un vert : `systemctl --user status`.\n")
        global _abstenu
        _abstenu = True
        return

    verifie("le CORE lit la base vivante", len(tables) > 0, True)
    verifie("claims est là", depot.table_existe("claims"), True)

    n = depot.count("claims")
    # Le nombre de lignes se compte, il ne se recopie pas : il disait 291 alors
    # que le module en faisait 357 — un chiffre juste le jour ou on l'ecrit.
    lignes = len((Path(__file__).parent / "persistance.py").read_text().splitlines())
    print(f"  ℹ️  {len(tables)} tables · {n} claims — lus par un CORE de {lignes} lignes")

    # La traduction sur une vraie requête, avec un argument entre parenthèses.
    ligne = depot.query_one(
        "SELECT COUNT(*) AS n FROM claims WHERE opened_at < NOW()")
    verifie("NOW() et le comptage passent sur Dolt", ligne is not None, True)

    # 🔴 Le mode d'écriture est-il celui qu'on croit ?
    #
    # Mesuré le 11/09 sur un serveur jetable : Dolt 1.84.0 ne pose pas le
    # drapeau `SERVER_STATUS_AUTOCOMMIT` dans son paquet d'authentification, et
    # pymysql en conclut qu'il n'a rien à envoyer. Le paramètre `autocommit` de
    # la bibliothèque était donc INOPÉRANT — le dépôt se croyait transactionnel
    # pendant que le serveur commitait tout seul.
    #
    # Ce qu'on éprouve ici n'est pas « autocommit vaut 1 » — ça, c'était déjà
    # vrai par accident. C'est que le dépôt **relit** le mode auprès du serveur
    # au lieu de le supposer. La lecture ci-dessous emprunte la connexion qu'il
    # a lui-même ouverte et vérifiée : si la vérification disparaissait du
    # `_connexion_dolt`, un serveur qui refuse le mode passerait sans bruit.
    mode = depot.query_one("SELECT @@autocommit AS ac")
    verifie("le dépôt écrit dans le mode qu'il a vérifié",
            int(mode["ac"]), 1 if depot.config.autocommit else 0)
    depot.ferme()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dolt", type=Path, metavar="BRAIN",
                   help="ajoute une lecture réelle de la base vivante")
    args = p.parse_args()

    traduction()
    configuration()
    sqlite_reel()
    if args.dolt:
        dolt_lecture(args.dolt.expanduser().resolve())

    print(f"\n  {_ok} garantie(s) tenue(s), {_ko} manquée(s)\n")
    return 1 if _ko else (3 if _abstenu else 0)


if __name__ == "__main__":
    sys.exit(main())
