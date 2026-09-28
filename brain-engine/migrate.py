#!/usr/bin/env python3
"""
brain-engine/migrate.py — Migration BE-1 + BE-2b
Ingère les sources existantes du brain dans brain.db

Sources :
  - claims/*.yml        → table claims
  - BRAIN-INDEX.md ## Signals → table signals (parsing markdown)
  - handoffs/*.md       → table handoffs (parsing frontmatter)
  - claims → sessions   → table sessions (dérivée depuis claims, BE-2b)

Usage :
  python3 brain-engine/migrate.py [--dry-run] [--reset]

Anti-drift :
  - Lecture seule sur les sources — jamais de modification des .md
  - Idempotent — relancer ne duplique pas les données (UPSERT)
  - En cas d'erreur parsing → warning + skip, pas de crash
"""

import sqlite3
import os
import re
import sys
import argparse
from datetime import datetime, timezone

BRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv('BRAIN_DB_PATH', os.path.join(BRAIN_ROOT, 'brain.db'))
SCHEMA_PATH = os.path.join(BRAIN_ROOT, 'brain-engine', 'schema.sql')


def backend_declare() -> str:
    """Ce que le brain dit utiliser — pas ce que ce script utilise.

    `db.py` lit `BRAIN_DB_BACKEND` dans `brain-engine/.env.local`. Ce
    fichier-ci ne passe pas par `db.py` : il ouvre `brain.db` en SQLite, en
    dur, depuis toujours. Tant que les deux coïncidaient, personne n'avait de
    raison de le remarquer.
    """
    # ⚠️ L'ENVIRONNEMENT l'emporte sur le fichier — comme dans `db.py`, et
    # c'est le point.
    #
    # Ce module lisait `.env.local` EN PREMIER et rendait sa valeur, quand
    # `db.py` fait `os.environ.setdefault()` : une variable déjà posée y gagne.
    # Deux résolutions opposées pour la même variable, dans le même moteur.
    #
    # Démontré le 06/09 avec `BRAIN_DB_BACKEND=sqlite` dans l'environnement :
    # `db.BACKEND` valait `sqlite` et `backend_declare()` valait `dolt`. Le même
    # processus pouvait croire écrire dans deux bases selon le module qui parle.
    # Sur cette instance les deux coïncident, donc le désaccord ne se voyait
    # jamais — il a faussé une mesure qui croyait porter sur un fork.
    depuis_env = os.getenv('BRAIN_DB_BACKEND')
    if depuis_env:
        return depuis_env.strip()
    env = os.path.join(BRAIN_ROOT, 'brain-engine', '.env.local')
    if os.path.isfile(env):
        for ligne in open(env, encoding='utf-8', errors='replace'):
            if ligne.startswith('BRAIN_DB_BACKEND'):
                return ligne.split('=', 1)[1].strip()
    return 'dolt'   # le même défaut que db.py — deux modules, une base 


def avertir_si_backend_divergent() -> None:
    """Un script qui écrit ailleurs que là où le brain lit doit le dire.

    Mesuré le 04/09 : `handoffs` contient 16 lignes dans `brain.db` — dont les
    trois handoffs du jour — et **zéro** dans Dolt, qui est la base vivante.
    `brain-conciergerie.sh` interroge Dolt et compte donc zéro handoff actif.
    `brain.db` est déclaré `artefact` dans NIVEAUX.yml : ni versionné, ni
    sauvegardé. Le dump quotidien dumpe Dolt.

    Ce n'est pas corrigé ici — porter cette migration sur `db.py` est un
    chantier, pas une retouche. Mais elle cesse d'annoncer un succès sans dire
    où il a lieu.
    """
    declare = backend_declare()
    if declare == 'sqlite':
        return
    print("")
    print("  ⚠️  CE SCRIPT ÉCRIT DANS brain.db (SQLite), EN DUR.")
    print(f"     Le backend déclaré est `{declare}` — ce n'est pas la même base.")
    print("     Ce qui suit ne rejoint donc PAS la base que le brain lit, et")
    print("     n'entre dans aucune sauvegarde : brain.db est un artefact.")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection):
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    conn.executescript(schema)
    conn.commit()
    print(f"✅ Schema initialisé depuis {SCHEMA_PATH}")


def parse_yml_field(content: str, field: str, default=None) -> str:
    """Extrait un champ YAML simple (pas de parsing YAML complet — volontaire)."""
    m = re.search(rf'^{re.escape(field)}:\s*(.+)', content, re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"\'')
    return default


def migrate_claims(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Migre claims/*.yml → table claims — SOURCE ABOLIE.

    `claims/` n'existe plus depuis l'ADR-042 : les claims vivent dans la base,
    ouverts par `bsi-claim.sh`, et plus jamais dans des fichiers YAML. Cette
    fonction ne peut donc plus rien migrer.

    Elle affichait « ⚠️ claims/ introuvable » à chaque passage, dans un journal
    que personne ne lit — la forme d'un accident pour une décision prise. Les 54
    lignes qu'elle avait laissées dans `brain.db` ont été retirées le 04/09,
    après vérification qu'elles étaient toutes couvertes par Dolt.

    Gardée plutôt que supprimée : un fork qui migre depuis une version
    antérieure à l'ADR-042 en a encore besoin. Mais elle dit maintenant ce
    qu'elle est.
    """
    claims_dir = os.path.join(BRAIN_ROOT, 'claims')
    if not os.path.isdir(claims_dir):
        print("ℹ️  claims/ n'existe plus — aboli par l'ADR-042, les claims")
        print("   vivent dans la base. Rien à migrer, et c'est normal.")
        return 0

    count = 0
    for filename in sorted(os.listdir(claims_dir)):
        if not filename.startswith('sess-') or not filename.endswith('.yml'):
            continue

        filepath = os.path.join(claims_dir, filename)
        try:
            with open(filepath) as f:
                content = f.read()
        except Exception as e:
            print(f"  ⚠️  {filename} : erreur lecture — {e}")
            continue

        # Gère v1 (name:) et v2 (sess_id:)
        sess_id = parse_yml_field(content, 'sess_id') or \
                  parse_yml_field(content, 'name', filename.replace('.yml', ''))
        scope        = parse_yml_field(content, 'scope', '—')
        status       = parse_yml_field(content, 'status', 'closed')
        opened_at    = parse_yml_field(content, 'opened_at') or \
                       parse_yml_field(content, 'opened', '—')
        closed_at    = parse_yml_field(content, 'closed_at') or \
                       parse_yml_field(content, 'closed')
        sess_type    = parse_yml_field(content, 'type', 'brain')
        handoff_lvl  = parse_yml_field(content, 'handoff_level')
        story_angle  = parse_yml_field(content, 'story_angle')

        if not sess_id or sess_id == '—':
            print(f"  ⚠️  {filename} : sess_id introuvable — skippé")
            continue

        if not dry_run:
            conn.execute("""
                INSERT INTO claims(sess_id, type, scope, status, opened_at, closed_at,
                                   handoff_level, story_angle)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(sess_id) DO UPDATE SET
                    status=excluded.status,
                    closed_at=excluded.closed_at,
                    story_angle=excluded.story_angle
            """, (sess_id, sess_type, scope, status, opened_at, closed_at,
                  handoff_lvl, story_angle))
        else:
            print(f"  [dry] claim: {sess_id} | {status} | {scope}")

        count += 1

    if not dry_run:
        conn.commit()
    print(f"✅ Claims migrés : {count}")
    return count


SIGNAL_TYPES = {'READY_FOR_REVIEW', 'REVIEWED', 'BLOCKED_ON', 'HANDOFF',
                'CHECKPOINT', 'INFO'}
SIGNAL_LIGNE = re.compile(
    r'^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*'
    r'\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|', re.M)


def lire_signals() -> list[tuple]:
    """Les signaux de `BRAIN-INDEX.md`, prêts à écrire.

    Extrait de `migrate_signals()` pour qu'un second écrivain s'en serve sans
    reparser le fichier — deux lectures de la même source finissent toujours par
    diverger.
    """
    index_path = os.path.join(BRAIN_ROOT, 'BRAIN-INDEX.md')
    if not os.path.exists(index_path):
        return []
    with open(index_path) as f:
        contenu = f.read()
    m = re.search(r'## Signals.*?\n(.*?)(?=\n##|\Z)', contenu, re.DOTALL)
    if not m:
        return []
    # UTC, jamais `datetime.now()`. Les dates de la base sont en UTC — c'est le
    # défaut du 22/08, et je viens de le réintroduire : les deux signaux
    # écrits ce matin portaient l'heure locale, donc deux heures d'avance sur
    # UTC en CEST, et `test_conventions_temporelles.py` l'a dit au premier
    # passage. Un contrôle qui attrape son auteur le jour même vaut sa place.
    maintenant = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    lignes = []
    for r in SIGNAL_LIGNE.finditer(m.group(1)):
        sig_id, de, pour, typ, projet, payload, etat = [v.strip() for v in r.groups()]
        if not sig_id.startswith('sig-') or typ not in SIGNAL_TYPES:
            continue
        etat = etat.lower().strip()
        if etat not in ('pending', 'delivered', 'archived'):
            etat = 'delivered'
        # `to_sess` est NOT NULL en base ; le tableau y met parfois un tiret.
        pour = pour if pour and pour not in ('—', '-', '') else 'inconnu'
        de = de if de and de not in ('—', '-', '') else None
        lignes.append((sig_id, de, pour, typ, projet or None,
                       payload or None, etat, maintenant))
    return lignes


def migrate_signals_backend(dry_run: bool = False) -> int:
    """Écrit les signaux dans le backend DÉCLARÉ — troisième et dernière table.

    Même défaut que les handoffs et les sessions : `signals` portait 2 lignes
    dans `brain.db` et **zéro dans Dolt**. La source, elle, est vivante
    et versionnée — `BRAIN-INDEX.md`, section `## Signals`.

    Une seule requête, donc un seul commit.
    """
    try:
        sys.path.insert(0, os.path.join(BRAIN_ROOT, 'brain-engine'))
        import db
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⚠️  backend indisponible ({type(exc).__name__}) — SQLite seul.")
        return 0
    if db.BACKEND == 'sqlite':
        return 0

    lignes = lire_signals()
    if not lignes:
        print("  ℹ️  aucun signal dans BRAIN-INDEX.md — rien à écrire.")
        return 0
    if dry_run:
        print(f"  [dry] {len(lignes)} signal(aux) → backend `{db.BACKEND}`")
        return len(lignes)

    valeurs = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s)"] * len(lignes))
    try:
        db.execute(
            "INSERT INTO signals (sig_id, from_sess, to_sess, type, projet, "
            "payload, state, created_at) "
            f"VALUES {valeurs} "
            # Portable : traduit vers `ON DUPLICATE KEY` pour Dolt.
            "ON CONFLICT(sig_id) DO UPDATE SET state = excluded.state",
            tuple(v for ligne in lignes for v in ligne),
            commit_msg=f"signals : {len(lignes)} depuis BRAIN-INDEX.md",
            tables=["signals"])
    except Exception as exc:                               # noqa: BLE001
        print(f"  ❌ écriture backend échouée : {type(exc).__name__}: {exc}")
        return 0
    total = db.query_one("SELECT COUNT(*) AS n FROM signals")["n"]
    print(f"✅ Signals → backend `{db.BACKEND}` : {total} en base")
    return total


def migrate_signals(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Migre ## Signals depuis BRAIN-INDEX.md → table signals (SQLite)."""
    index_path = os.path.join(BRAIN_ROOT, 'BRAIN-INDEX.md')
    if not os.path.exists(index_path):
        print(f"⚠️  BRAIN-INDEX.md introuvable")
        return 0

    with open(index_path) as f:
        content = f.read()

    # Extraire la section ## Signals
    m = re.search(r'## Signals.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if not m:
        print("⚠️  Section ## Signals non trouvée dans BRAIN-INDEX.md")
        return 0

    signals_section = m.group(1)

    # Parser le tableau markdown
    # Format : | sig_id | De | Pour | Type | Concerné | Payload | État |
    row_pattern = re.compile(
        r'^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|',
        re.MULTILINE
    )

    count = 0
    for m in row_pattern.finditer(signals_section):
        sig_id, from_sess, to_sess, sig_type, projet, payload, state = [
            v.strip() for v in m.groups()
        ]

        # Ignorer les lignes d'en-tête
        if sig_id.startswith('ID') or sig_id.startswith('-'):
            continue
        if not sig_id.startswith('sig-'):
            continue

        VALID_TYPES = {'READY_FOR_REVIEW', 'REVIEWED', 'BLOCKED_ON', 'HANDOFF', 'CHECKPOINT', 'INFO'}
        if sig_type not in VALID_TYPES:
            continue

        state = state.lower().strip()
        if state not in ('pending', 'delivered', 'archived'):
            state = 'delivered'

        if not dry_run:
            conn.execute("""
                INSERT INTO signals(sig_id, from_sess, to_sess, type, projet, payload, state, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(sig_id) DO UPDATE SET state=excluded.state
            """, (sig_id, from_sess, to_sess, sig_type, projet, payload, state,
                  datetime.now().isoformat()))
        else:
            print(f"  [dry] signal: {sig_id} | {sig_type} | {state}")

        count += 1

    if not dry_run:
        conn.commit()
    print(f"✅ Signals migrés : {count}")
    return count


def normaliser_date(valeur: str) -> str:
    """Rend une date que Dolt accepte, quel que soit le format du frontmatter.

    Trouvé le 05/09 en élargissant la lecture à `handoffs/archive/` : la
    migration est tombée sur

        DataError: '2026-03-15T20:30' is not a valid value for 'datetime'

    Un seul fichier sur trente et un l'écrit ainsi — et c'est de l'ISO 8601
    parfaitement valide. Corriger le fichier aurait fait passer la migration du
    jour et rien de plus : le suivant qui date son handoff en ISO casserait à
    nouveau, et le message ne dirait toujours pas quel fichier.

    On accepte donc les trois formes rencontrées — `YYYY-MM-DD`,
    `YYYY-MM-DDTHH:MM[:SS]`, `YYYY-MM-DD HH:MM[:SS]` — et on rend ce que le
    moteur sait lire. Ce qui n'est reconnu par aucune est rendu tel quel : ce
    n'est pas à cette fonction de décider qu'une valeur est fausse.
    """
    if not valeur:
        return valeur
    v = str(valeur).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return v


def lire_handoffs() -> list[tuple]:
    """Le contenu de `handoffs/*.md`, sous forme de lignes prêtes à écrire.

    Extrait de `migrate_handoffs()` le 04/09 pour qu'un second écrivain puisse
    s'en servir sans reparser les fichiers une deuxième fois — deux lectures du
    même disque finissent toujours par diverger.
    """
    handoffs_dir = os.path.join(BRAIN_ROOT, 'handoffs')
    if not os.path.isdir(handoffs_dir):
        return []

    # ── `handoffs/archive/` est lu aussi ───────────────────────────
    #
    # `os.listdir` ne descend pas. Mesuré le 05/09 : VINGT fichiers dans
    # `handoffs/archive/`, dont les cinq que `brain.db` portait seul — et
    # quinze qui n'étaient dans aucune base, ni SQLite ni Dolt. Un handoff
    # archivé reste un fait ; la colonne `status` existe précisément pour ça.
    #
    # **L'emplacement fait foi sur le frontmatter.** Un fichier déplacé dans
    # `archive/` est archivé, quoi qu'en dise son en-tête — figé au moment de
    # l'écriture, il n'a pas suivi le déplacement. Trois des cinq se déclaraient
    # encore `active` ou `consumed` depuis l'archive. C'est le motif du rework :
    # la déclaration est juste quelque part, et fausse là où elle s'exécute.
    #
    # Deux fichiers sans frontmatter sont ignorés, comme partout ailleurs.
    fichiers = [(f, handoffs_dir, False) for f in sorted(os.listdir(handoffs_dir))]
    archive_dir = os.path.join(handoffs_dir, 'archive')
    if os.path.isdir(archive_dir):
        fichiers += [(f, archive_dir, True) for f in sorted(os.listdir(archive_dir))]

    lignes = []
    for filename, dossier, est_archive in fichiers:
        if not filename.endswith('.md') or filename.startswith('_'):
            continue
        try:
            with open(os.path.join(dossier, filename)) as f:
                content = f.read()
        except Exception:                                  # noqa: BLE001
            continue
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not fm_match:
            continue
        fm = fm_match.group(1)
        status = parse_yml_field(fm, 'status', 'active')
        if status not in ('active', 'consumed', 'archived'):
            status = 'active'
        # L'emplacement fait foi : un fichier dans `archive/` est archivé, quel
        # que soit ce que son frontmatter figé continue d'annoncer.
        if est_archive:
            status = 'archived'
        lignes.append((
            filename,
            parse_yml_field(fm, 'type', 'HANDOFF'),
            parse_yml_field(fm, 'projet') or parse_yml_field(fm, 'project'),
            status,
            parse_yml_field(fm, 'from') or parse_yml_field(fm, 'source'),
            normaliser_date(
                parse_yml_field(fm, 'created') or parse_yml_field(
                    fm, 'date', datetime.now().strftime('%Y-%m-%d'))),
        ))
    return lignes


def migrate_handoffs_backend(dry_run: bool = False) -> int:
    """Écrit les handoffs dans le backend DÉCLARÉ, pas seulement dans SQLite.

    Mesuré le 04/09 : `handoffs` portait 16 lignes dans `brain.db` — dont les
    trois du jour — et **zéro** dans Dolt, qui est la base que le brain lit.
    `brain-conciergerie.sh` interroge Dolt et comptait donc zéro handoff actif ;
    le dump quotidien dumpe Dolt, donc aucune sauvegarde ne les portait ; et
    `brain.db` est déclaré `artefact`, ni versionné ni sauvegardé.

    Ceci ne corrige PAS le fond — `migrate.py` écrit toujours en SQLite en dur,
    et le porter entièrement sur `db.py` reste un chantier : il faudrait décider
    quoi faire des 54 claims et 54 sessions figés au 29 mars qui s'y trouvent, et
    que Dolt porte déjà autrement. Ici on ne traite que la table qui manquait, et
    depuis sa source de vérité : les fichiers, jamais l'autre base.

    Une seule requête, donc un seul commit : douze commits pour douze handoffs
    noieraient l'historique, et a montré ce que chaque écriture coûte.
    """
    try:
        sys.path.insert(0, os.path.join(BRAIN_ROOT, 'brain-engine'))
        import db
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⚠️  backend indisponible ({type(exc).__name__}) — SQLite seul.")
        return 0
    if db.BACKEND == 'sqlite':
        return 0

    lignes = lire_handoffs()
    if not lignes:
        print("  ⚠️  aucun handoff lisible sur le disque — rien à écrire.")
        return 0
    if dry_run:
        print(f"  [dry] {len(lignes)} handoff(s) → backend `{db.BACKEND}`")
        return len(lignes)

    valeurs = "(%s,%s,%s,%s,%s,%s)"
    sql = ("INSERT INTO handoffs "
           "(filename, type, projet, status, from_sess, created_at) VALUES "
           + ",".join([valeurs] * len(lignes))
           # Portable : traduit vers `ON DUPLICATE KEY` pour Dolt.
           + " ON CONFLICT(filename) DO UPDATE SET status = excluded.status")
    params = tuple(v for ligne in lignes for v in ligne)
    try:
        db.execute(sql, params,
                   commit_msg=f"handoffs : {len(lignes)} depuis handoffs/*.md",
                   tables=["handoffs"])
    except Exception as exc:                               # noqa: BLE001
        print(f"  ❌ écriture backend échouée : {type(exc).__name__}: {exc}")
        return 0
    total = db.query_one("SELECT COUNT(*) AS n FROM handoffs")["n"]
    print(f"✅ Handoffs → backend `{db.BACKEND}` : {len(lignes)} écrits, "
          f"{total} en base")
    return len(lignes)


def verifier_handoffs() -> int:
    """La base porte-t-elle ce que `handoffs/` dit ? — lecture seule.

    0 si chaque handoff du disque est en base avec le même statut, 2 sinon.
    S'abstient (`SKIP`, sortie 0) quand la base ne peut pas être lue.

    Mesure le RÉSULTAT de la synchro, pas sa trace. Jusqu'au 27/09,
    `brain-db-sync.sh --check` comparait l'heure du dernier commit `handoffs/`
    à la dernière ligne « OK » de `sync.log` : un handoff arrivé par un `pull`
    divergent garde l'heure de sa fusion sur la forge, et une synchro locale
    faite entre-temps pour autre chose le déclarait à jour sans qu'il soit en
    base. Ici, la comparaison porte sur ce que la synchro écrit —
    `lire_handoffs()`, la même fonction — et sur ce que la base contient. La
    table ne met à jour que `status` : c'est la clé et le seul champ comparés.

    Une ligne en base sans fichier n'est pas rougie : la synchro n'efface
    jamais, un rouge qu'elle ne peut pas éteindre s'apprend à ignorer. Elle est
    nommée.
    """
    # SQLite : `sqlite3.connect()` CRÉE le fichier qu'il ouvre. Un contrôle ne
    # doit pas faire naître la base qu'il vérifie.
    if backend_declare() == 'sqlite' and not os.path.isfile(DB_PATH):
        print(f"SKIP base SQLite absente ({DB_PATH}) — rien à comparer.")
        return 0
    try:
        sys.path.insert(0, os.path.join(BRAIN_ROOT, 'brain-engine'))
        import db
        base = {r['filename']: r['status']
                for r in db.query("SELECT filename, status FROM handoffs")}
    except Exception as exc:                               # noqa: BLE001
        print(f"SKIP base injoignable ({type(exc).__name__}) — rien à comparer.")
        return 0

    disque = {l[0]: l[3] for l in lire_handoffs()}
    absents = sorted(set(disque) - set(base))
    ecarts = sorted(f for f in disque if f in base and base[f] != disque[f])
    orphelins = sorted(set(base) - set(disque))

    if absents or ecarts:
        print(f"❌ la base ne suit pas handoffs/ — {len(absents)} absent(s), "
              f"{len(ecarts)} statut(s) divergent(s) sur {len(disque)}")
        for f in absents[:12]:
            print(f"     absent   {f}")
        for f in ecarts[:12]:
            print(f"     statut   {f} : disque `{disque[f]}`, base `{base[f]}`")
        print("   → bash scripts/brain-db-sync.sh")
    else:
        print(f"✅ la base porte les {len(disque)} handoff(s) du disque, statuts compris")
    if orphelins:
        print(f"ℹ️  {len(orphelins)} ligne(s) en base sans fichier — la synchro "
              f"n'efface pas : {', '.join(orphelins[:5])}")
    return 2 if (absents or ecarts) else 0


def migrate_sessions_archive_backend(dry_run: bool = False) -> int:
    """Dérive `sessions_archive` depuis `claims_archive`.

    Le pendant archivé de `migrate_sessions_backend`. Mesuré le 05/09 :
    **389 claims archivés n'avaient de ligne de session NULLE PART** — ni dans
    `sessions`, ni dans `sessions_archive`. De mars à juillet 2026.

    ── Comment on y est arrivé, parce que le chemin compte ────────────────────

    Le point de départ était : « 54 sessions figées au 29 mars dans
    `brain.db` ». J'ai d'abord comparé les CARDINAUX — 54 dans SQLite, 53 dans
    Dolt — et conclu « un d'écart ». Les deux ensembles étaient **disjoints**.

    Puis j'ai voulu dériver `claims_archive` vers `sessions`, la table vivante.
    C'était verser 521 archives dans le registre courant, et la docstring d'à
    côté disait déjà le contraire : *« sessions_archive porte 131 lignes et
    n'est pas touchée : c'est l'archive, elle a sa propre vie. »* Je l'avais lue
    avant de l'enfreindre. Le dry-run l'a dit — « 573 sessions à dériver » — et
    c'est le chiffre absurde qui a arrêté le geste.

    Enfin, `brain.db` n'est pas la source. Ses 37 sessions manquantes ne portent
    que quatre champs renseignés : `sess_id`, `date`, `type`, et `handoff_level`
    pour vingt et une d'entre elles. `claims_archive` porte les quatre. Recopier
    l'artefact non versionné n'aurait rien apporté que la dérivation n'apporte.

    131 + 389 = 520, pour 521 claims archivés. Le compte tombe.
    """
    try:
        sys.path.insert(0, os.path.join(BRAIN_ROOT, 'brain-engine'))
        import db
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⚠️  backend indisponible ({type(exc).__name__}) — SQLite seul.")
        return 0
    if db.BACKEND == 'sqlite':
        return 0

    manquantes = db.query_one(
        "SELECT COUNT(*) AS n FROM claims_archive a "
        "LEFT JOIN sessions_archive s ON s.sess_id = a.sess_id "
        "LEFT JOIN sessions v ON v.sess_id = a.sess_id "
        "WHERE s.sess_id IS NULL AND v.sess_id IS NULL")["n"]

    if dry_run:
        print(f"  [dry] {manquantes} session(s) archivée(s) à dériver "
              f"→ backend `{db.BACKEND}`")
        return manquantes
    if not manquantes:
        print("✅ Sessions archivées : rien à dériver")
        return 0

    # Une seule requête, donc un seul commit — discipline.
    #
    # `sessions` est exclue de la cible : une session déjà vivante ne se
    # duplique pas dans l'archive. C'est ce que le double LEFT JOIN garantit.
    try:
        db.execute(
            "INSERT IGNORE INTO sessions_archive "
            "  (sess_id, date, type, mode, handoff_level, context_at_close, "
            "   duration_min, health_score, cold_start_kpi_pass, archived_at) "
            "SELECT a.sess_id, DATE_FORMAT(a.opened_at, '%%Y-%%m-%%d'), a.type, "
            "       a.mode, CAST(a.handoff_level AS CHAR), a.context_at_close, a.duration_min, "
            "       a.health_score, a.cold_start_kpi_pass, a.archived_at "
            "FROM claims_archive a "
            "LEFT JOIN sessions_archive s ON s.sess_id = a.sess_id "
            "LEFT JOIN sessions v ON v.sess_id = a.sess_id "
            "WHERE s.sess_id IS NULL AND v.sess_id IS NULL",
            (),
            commit_msg=f"sessions_archive : {manquantes} derivees depuis claims_archive",
            tables=["sessions_archive"])
    except Exception as exc:                               # noqa: BLE001
        print(f"  ❌ dérivation des sessions archivées : {type(exc).__name__}: {exc}")
        return 0

    total = db.query_one("SELECT COUNT(*) AS n FROM sessions_archive")["n"]
    print(f"✅ Sessions archivées → backend `{db.BACKEND}` : "
          f"{manquantes} dérivées, {total} en base")
    return manquantes


def migrate_sessions_backend(dry_run: bool = False) -> int:
    """Dérive `sessions` depuis `claims`, dans le backend DÉCLARÉ.

    ⚠️ `CAST(handoff_level AS CHAR)` n'est pas décoratif. `claims.handoff_level`
    est un `enum` ; `sessions.handoff_level` un `varchar`. Sans le cast, **Dolt
    écrit l'INDEX de l'énumération, pas son littéral** — `'1'` au lieu de `'NO'`.

    C'est le même défaut que sur `dolt dump` et `SHOW CREATE TABLE`
   , mais sur un `UPDATE` entre colonnes : il ne touche pas que les
    exports, il touche les écritures. Mesuré le 05/09 en réparant `sessions` —
    la réparation elle-même a réintroduit 118 `'1'` et 2 `'2'` avant le cast.

    C'est l'origine des `'0'` que `sessions` portait sur ses 54 lignes.

    Même défaut que les handoffs, trouvé le 04/09 en auditant le BSI à la
    demande de l'owner : `sessions` portait **54 lignes dans `brain.db` et zéro
    dans Dolt**. Trois tables étaient dans ce cas — `handoffs`, `sessions`,
    `signals` — parce que `migrate.py` écrit en SQLite en dur.

    La source est `claims`, comme pour la version SQLite : une session EST un
    claim. On ne recopie pas l'autre base — les 54 sessions de `brain.db`
    dérivent de claims que Dolt porte déjà, dans `claims` ou `claims_archive`.
    Vérifié avant d'écrire : **aucune n'est orpheline**, les 54 ont leur claim.

    `sessions_archive` porte 131 lignes et n'est pas touchée : c'est l'archive,
    elle a sa propre vie.
    """
    try:
        sys.path.insert(0, os.path.join(BRAIN_ROOT, 'brain-engine'))
        import db
    except Exception as exc:                               # noqa: BLE001
        print(f"  ⚠️  backend indisponible ({type(exc).__name__}) — SQLite seul.")
        return 0
    if db.BACKEND == 'sqlite':
        return 0

    n_claims = db.query_one("SELECT COUNT(*) AS n FROM claims")["n"]
    if dry_run:
        print(f"  [dry] {n_claims} session(s) à dériver → backend `{db.BACKEND}`")
        return n_claims
    if not n_claims:
        print("  ⚠️  aucun claim dans le backend — rien à dériver.")
        return 0

    # Deux temps, un seul commit — porté par la seconde requête, qui stage la
    # table et emporte donc aussi les lignes créées par la première.
    #
    # Pourquoi pas un `ON DUPLICATE KEY UPDATE` : Dolt refuse `VALUES(col)`
    # dans un `INSERT … SELECT` — « expected ON DUPLICATE KEY ... VALUES() to
    # reference a column, found: __new_ins.date ». Mesuré le 04/09, et l'échec
    # s'est plaint au lieu d'écrire à moitié.
    #
    # `COALESCE` dans le UPDATE protège ce que metabolism-scribe a déjà
    # renseigné : la dérivation complète, elle n'écrase pas.
    try:
        db.execute(
            "INSERT IGNORE INTO sessions (sess_id, date, type, handoff_level) "
            "SELECT sess_id, DATE_FORMAT(opened_at, '%%Y-%%m-%%d'), type, "
            "       CAST(handoff_level AS CHAR) FROM claims")
        db.execute(
            "UPDATE sessions s JOIN claims c ON s.sess_id = c.sess_id SET "
            "  s.date          = COALESCE(DATE_FORMAT(c.opened_at, '%%Y-%%m-%%d'), s.date), "
            "  s.type          = COALESCE(c.type, s.type), "
            "  s.handoff_level = COALESCE(CAST(c.handoff_level AS CHAR), s.handoff_level)",
            (),
            commit_msg=f"sessions : {n_claims} dérivées depuis claims",
            tables=["sessions"])
    except Exception as exc:                               # noqa: BLE001
        print(f"  ❌ dérivation backend échouée : {type(exc).__name__}: {exc}")
        return 0
    total = db.query_one("SELECT COUNT(*) AS n FROM sessions")["n"]
    print(f"✅ Sessions → backend `{db.BACKEND}` : {total} en base")
    return total


def migrate_handoffs(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Migre les handoffs → table `handoffs` (SQLite).

    ⚠️ **Cette fonction avait sa PROPRE lecture du disque.** Elle dupliquait
    `lire_handoffs()`, dont la docstring avertissait pourtant : *« deux lectures
    du même disque finissent toujours par diverger »*.

    Elles ont divergé le 05/09, une heure après que la seconde a été élargie à
    `handoffs/archive/` : **11 lignes en SQLite, 29 dans Dolt**, pour le même
    disque, dans la même exécution. Le message le disait à l'écran, deux lignes
    l'un sous l'autre, sans que rien ne le signale comme une anomalie.

    Une seule lecture désormais. C'est la moitié de : il en reste une —
    cette fonction écrit toujours en SQLite en dur, en plus du backend déclaré.
    """
    lignes = lire_handoffs()
    if not lignes:
        print("✅ Handoffs migrés : 0")
        return 0

    for ligne in lignes:
        filename, htype, projet, status, from_s, created = ligne[:6]
        if dry_run:
            print(f"  [dry] handoff: {filename} | {status}")
            continue
        conn.execute(
            "INSERT INTO handoffs(filename, type, projet, status, from_sess, created_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(filename) DO UPDATE SET status=excluded.status",
            (filename, htype, projet, status, from_s, created))

    if not dry_run:
        conn.commit()
    print(f"✅ Handoffs migrés : {len(lignes)}")
    return len(lignes)


def migrate_sessions(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """
    Peuple la table sessions depuis claims (BE-2b).

    Stratégie : claims = sessions — chaque claim est une session brain.
    Les champs metabolism (tokens_used, duration_min, etc.) restent NULL
    jusqu'à ce que metabolism-scribe les alimente directement.

    Mapping :
      claims.sess_id       → sessions.sess_id
      claims.opened_at     → sessions.date (partie date uniquement)
      claims.type          → sessions.type
      claims.handoff_level → sessions.handoff_level
      claims.health_score  → sessions.health_score (si présent dans yml)
      claims.cold_start_kpi_pass → sessions.cold_start_kpi_pass
    """
    if dry_run:
        rows = conn.execute("SELECT COUNT(*) as n FROM claims").fetchone()
        print(f"  [dry] sessions à créer depuis claims : {rows['n']}")
        return rows['n']

    # `schema.sql` declare `claims.health_score` et `claims.cold_start_kpi_pass`.
    # La table, elle, ne les a pas : `CREATE TABLE IF NOT EXISTS` cree une table
    # absente, il ne migre jamais une table presente. La declaration etait juste
    # dans le fichier, et fausse la ou elle s'executait — et cette requete
    # echouait chaque jour sur `no such column: c.health_score`.
    #
    # On lit donc les colonnes reellement la, et on ne demande que celles-la.
    presentes = {r["name"] for r in conn.execute("PRAGMA table_info(claims)")}
    optionnelles = [c for c in ("health_score", "cold_start_kpi_pass")
                    if c in presentes]
    manquantes = [c for c in ("health_score", "cold_start_kpi_pass")
                  if c not in presentes]
    if manquantes:
        print(f"  ⚠️  claims n'a pas {', '.join(manquantes)} — colonnes ignorees. "
              f"schema.sql les declare ; la table est anterieure.")

    colonnes = ["sess_id", "date", "type", "handoff_level", *optionnelles]
    selection = ["c.sess_id", "SUBSTR(c.opened_at, 1, 10) AS date", "c.type",
                 "c.handoff_level", *(f"c.{c}" for c in optionnelles)]
    maj = ",\n            ".join(
        f"{c:19} = COALESCE(excluded.{c}, sessions.{c})"
        for c in colonnes if c != "sess_id")

    # UPSERT : ne pas écraser les champs metabolism déjà renseignés
    conn.execute(f"""
        INSERT INTO sessions({', '.join(colonnes)})
        SELECT
            {', '.join(selection)}
        FROM claims c
        WHERE TRUE
        ON CONFLICT(sess_id) DO UPDATE SET
            {maj}
    """)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    kpi_row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN cold_start_kpi_pass = 1 THEN 1 ELSE 0 END) as passes
        FROM sessions WHERE handoff_level = 'NO'
    """).fetchone()

    print(f"✅ Sessions migrées : {count}")
    if kpi_row and kpi_row[0] > 0:
        print(f"   cold_start KPI (handoff=NO) : {kpi_row[1]}/{kpi_row[0]} passes")
    return count


def main():
    parser = argparse.ArgumentParser(description='Brain state engine — migration BE-1 + BE-2b')
    parser.add_argument('--dry-run', action='store_true', help='Simulation sans écriture')
    parser.add_argument('--reset', action='store_true', help='Supprimer brain.db avant migration')
    parser.add_argument('--sessions-only', action='store_true', help='Rejouer uniquement migrate_sessions')
    parser.add_argument('--verifier-handoffs', action='store_true',
                        help='Compare handoffs/ à la base, sans rien écrire (0 à jour, 2 sinon)')
    args = parser.parse_args()

    if args.verifier_handoffs:
        sys.exit(verifier_handoffs())

    if args.reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"♻️  brain.db supprimé — reconstruction depuis zéro")

    print(f"Brain root : {BRAIN_ROOT}")
    print(f"DB path    : {DB_PATH}")
    print(f"Mode       : {'DRY RUN' if args.dry_run else 'WRITE'}")
    print()

    # `brain.db` n'est plus ouvert quand le backend déclaré n'est pas SQLite.
    #
    # Tranché par Kevin le 06/09 : le fossile disparaît. Il ne
    # suffisait pas de supprimer le fichier — `sqlite3.connect()` le RECRÉE, et
    # le hook `post-commit` appelle ce script dès qu'un handoff change. Le
    # fossile serait revenu au commit suivant, vide puis repeuplé.
    #
    # Vérifié ligne à ligne avant de couper, jamais par cardinal : 32 handoffs,
    # 2 signals et 54 sessions, tous présents dans Dolt — zéro absent. Gelé dans
    # `brain-db-backup/sqlite-fossile-20260906.db`, versionné et poussé.
    #
    # SQLite reste le chemin nominal d'un fork qui n'a pas Dolt : la branche
    # n'est pas retirée, elle est conditionnée.
    declare = backend_declare()
    sqlite_actif = declare == 'sqlite'
    conn = None

    if sqlite_actif:
        conn = connect(DB_PATH)
        init_schema(conn)
    else:
        print(f"  ⓘ  backend déclaré : `{declare}` — SQLite n'est pas ouvert.")
        print("     Les tables dérivées vont dans la base que le brain LIT.")

    if args.sessions_only:
        print("\n── Sessions (replay) ───────────────────")
        if sqlite_actif:
            migrate_sessions(conn, dry_run=args.dry_run)
        migrate_sessions_backend(dry_run=args.dry_run)
    else:
        print("\n── Claims ──────────────────────────────")
        if sqlite_actif:
            migrate_claims(conn, dry_run=args.dry_run)
        else:
            print("  ⏭  SQLite sauté — les claims vivent dans le backend.")

        print("\n── Signals ─────────────────────────────")
        if sqlite_actif:
            migrate_signals(conn, dry_run=args.dry_run)
        # La troisième table qui manquait dans la base vivante.
        migrate_signals_backend(dry_run=args.dry_run)

        print("\n── Handoffs ────────────────────────────")
        if sqlite_actif:
            migrate_handoffs(conn, dry_run=args.dry_run)
        # La table qui manquait dans la base vivante.
        migrate_handoffs_backend(dry_run=args.dry_run)

        print("\n── Sessions ────────────────────────────")
        if sqlite_actif:
            migrate_sessions(conn, dry_run=args.dry_run)
        # La seconde table qui manquait dans la base vivante.
        migrate_sessions_backend(dry_run=args.dry_run)
        # Et son pendant archivé : 389 claims archivés n'avaient de ligne de
        # session nulle part, ni vivante ni archivée.
        migrate_sessions_archive_backend(dry_run=args.dry_run)

    if not args.dry_run and sqlite_actif:
        # Vérification finale
        print("\n── Vérification ────────────────────────")
        for table in ('claims', 'signals', 'handoffs', 'agent_memory', 'sessions'):
            row = conn.execute(f"SELECT COUNT(*) as n FROM {table}").fetchone()
            print(f"  {table:<15} : {row['n']} entrées")

        print("\n── Vues ────────────────────────────────")
        row = conn.execute("SELECT * FROM v_open_claims").fetchall()
        print(f"  v_open_claims  : {len(row)} claim(s) open")
        row = conn.execute("SELECT * FROM v_stale_claims").fetchall()
        if row:
            print(f"  ⚠️  v_stale_claims : {len(row)} claim(s) stale !")
        else:
            print(f"  v_stale_claims : ✅ aucun stale")
        row = conn.execute("SELECT * FROM v_cold_start_kpi").fetchone()
        if row and row['total_no_handoff'] > 0:
            rate = row['pass_rate_pct'] or 0
            print(f"  v_cold_start_kpi: {row['passes']}/{row['total_no_handoff']} passes ({rate:.0f}%)")

    if conn is not None:
        conn.close()
        print("\n✅ Migration terminée — brain.db (SQLite) à jour")
    else:
        print(f"\n✅ Migration terminée — backend `{declare}` à jour, SQLite intouché")


if __name__ == '__main__':
    main()
