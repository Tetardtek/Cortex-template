#!/usr/bin/env python3
"""
brain-engine/test_brain_engine.py — Tests unitaires BE-2
Stdlib uniquement (unittest). Aucun accès réseau, Ollama, ou brain.db requis.

Lancer :
  python3 brain-engine/test_brain_engine.py
  python3 brain-engine/test_brain_engine.py -v
"""

import sys
import os
import re
import contextlib
import unittest
import tempfile
import shutil
import sqlite3
import time
import json
import struct
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Import des modules sous test ───────────────────────────────────────────────
# Les modules ont un guardrail EMBED_MODEL au niveau module — nomic-embed-text
# (défaut) passe ; on s'assure de ne pas avoir de variable bloquante.
os.environ.setdefault('EMBED_MODEL', 'nomic-embed-text')

sys.path.insert(0, str(Path(__file__).parent))
import embed
import search
import distill


# ══════════════════════════════════════════════════════════════════════════════
# embed.py — chunk_by_size
# ══════════════════════════════════════════════════════════════════════════════

class TestDepotSerialise(unittest.TestCase):
    """Ce qu'on passe au CORE : le vrai `Depot`, délégué et sérialisé.

    L'incident : `server.py` passait le MODULE `db`, qui imitait le `Depot`
    à la main. Une méthode ajoutée au `Depot` (`colonne_existe`) et appelée
    par le CORE manquait à l'imitation — toute ouverture de claim par le
    moteur aurait rendu 500.
    """

    class _Faux:
        def __init__(self, db):
            self._db = db
            self.config = object()

        def verrou_tenu(self):
            return self._db._dolt_verrou._is_owned()

        def nouvelle_methode(self, x, y=0):
            return x + y

    def setUp(self):
        import db
        self.db = db
        self._avant = db._DEPOT
        db._DEPOT = self._Faux(db)

    def tearDown(self):
        self.db._DEPOT = self._avant

    def test_une_methode_nouvelle_du_depot_existe_d_office(self):
        # L'incident rejoué : rien n'a été ajouté à db.py pour cette méthode.
        self.assertEqual(self.db.depot().nouvelle_methode(2, y=3), 5)
        # Témoin : l'ancienne forme, le MODULE, ne l'a pas — ni `table_existe`,
        # que le CORE appelle (il n'a que `table_exists`).
        self.assertFalse(hasattr(self.db, 'nouvelle_methode'))
        self.assertFalse(hasattr(self.db, 'table_existe'))

    def test_chaque_appel_est_pris_sous_le_verrou(self):
        self.assertTrue(self.db.depot().verrou_tenu())
        self.assertFalse(self.db._DEPOT.verrou_tenu())   # témoin : hors délégation

    def test_un_attribut_est_rendu_tel_quel(self):
        self.assertIs(self.db.depot().config, self.db._DEPOT.config)

    def test_un_nom_prive_ne_traverse_pas(self):
        with self.assertRaises(AttributeError):
            self.db.depot()._db

    def test_toute_methode_publique_du_vrai_depot_est_joignable(self):
        from core.persistance import Depot
        publiques = [n for n in dir(Depot)
                     if not n.startswith('_') and callable(getattr(Depot, n))]
        self.assertIn('colonne_existe', publiques)
        self.db._DEPOT = self._avant
        manquantes = [n for n in publiques if not hasattr(type(self.db._depot()), n)]
        self.assertEqual(manquantes, [])
        for n in publiques:
            self.assertTrue(callable(getattr(self.db.depot(), n)), n)


class TestChunkBySize(unittest.TestCase):

    def test_short_text_single_chunk(self):
        """Texte plus court que max_chars → 1 seul chunk."""
        text = "Bonjour le monde."
        chunks = embed.chunk_by_size(text, "test.md")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]['text'], text)

    def test_long_text_multiple_chunks(self):
        """Texte long → plusieurs chunks, tous non vides."""
        text = "A" * (embed.CHUNK_TOKENS * 4 * 3)  # 3× la taille max
        chunks = embed.chunk_by_size(text, "test.md")
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertTrue(c['text'])

    def test_no_infinite_loop_regression(self):
        """
        RÉGRESSION — bug boucle infinie (corrigé 2026-03-16).
        Tout texte > CHUNK_TOKENS*4 sans saut de ligne déclenchait une boucle
        infinie : start = end - overlap restait toujours < len(text).
        Ce test doit terminer en < 1s.
        """
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("chunk_by_size en boucle infinie !")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(2)  # 2 secondes max
        try:
            # Texte sans saut de ligne — le cas exact qui causait le freeze
            text = "X" * (embed.CHUNK_TOKENS * 4 + 100)
            chunks = embed.chunk_by_size(text, "test.md")
            self.assertGreater(len(chunks), 0)
        finally:
            signal.alarm(0)

    def test_no_infinite_loop_with_newlines(self):
        """Texte avec sauts de ligne — variante avec newlines."""
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("chunk_by_size en boucle infinie !")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(2)
        try:
            line = "Ligne de texte normale.\n"
            text = line * 300  # ~7 200 chars
            chunks = embed.chunk_by_size(text, "test.md")
            self.assertGreater(len(chunks), 1)
        finally:
            signal.alarm(0)

    def test_chunks_cover_full_text(self):
        """Vérifier que les chunks couvrent bien tout le texte (pas de trou)."""
        text = "mot " * 1000  # ~4 000 chars
        chunks = embed.chunk_by_size(text, "test.md")
        # Le dernier chunk doit contenir la fin du texte
        last_chunk = chunks[-1]['text']
        self.assertIn("mot", last_chunk)

    def test_filepath_preserved(self):
        """Le filepath est propagé dans chaque chunk."""
        text = "A" * (embed.CHUNK_TOKENS * 4 + 1)
        fp = "agents/helloWorld.md"
        chunks = embed.chunk_by_size(text, fp)
        for c in chunks:
            self.assertEqual(c['filepath'], fp)

    def test_empty_text(self):
        """Texte vide → aucun chunk."""
        chunks = embed.chunk_by_size("", "test.md")
        self.assertEqual(len(chunks), 0)

    def test_whitespace_only(self):
        """Texte uniquement whitespace → aucun chunk."""
        chunks = embed.chunk_by_size("   \n\n   ", "test.md")
        self.assertEqual(len(chunks), 0)


# ══════════════════════════════════════════════════════════════════════════════
# embed.py — chunk_by_h2
# ══════════════════════════════════════════════════════════════════════════════

class TestChunkByH2(unittest.TestCase):

    def test_single_section(self):
        """Un seul fichier sans H2 → 1 chunk."""
        text = "# Titre\n\nContenu simple sans section H2."
        chunks = embed.chunk_by_h2(text, "test.md")
        self.assertEqual(len(chunks), 1)

    # Les corps doivent depasser MIN_BODY_CHARS : en dessous, la section est un
    # stub et chunk_by_h2 la saute — comportement voulu, ajoute apres ces tests,
    # qui affirmaient donc un decoupage que le code ne fait plus.
    CORPS = "Contenu de section suffisamment long pour ne pas etre un stub."

    def test_multiple_h2_sections(self):
        """Plusieurs sections H2 → un chunk par section."""
        text = "\n\n".join(f"## Section {i}\n{self.CORPS}" for i in (1, 2, 3))
        chunks = embed.chunk_by_h2(text, "test.md")
        self.assertEqual(len(chunks), 3)

    def test_section_title_extracted(self):
        """Le titre H2 est extrait proprement."""
        text = f"## Mon Agent\n{self.CORPS}"
        chunks = embed.chunk_by_h2(text, "test.md")
        self.assertEqual(chunks[0]['title'], 'Mon Agent')

    def test_titre_saute_le_frontmatter(self):
        """Le préambule d'un fichier commence par `---`, qui n'est pas un titre.

        L'ancienne extraction prenait la première ligne telle quelle : 558 chunks
        de l'index portaient le titre `---` au 03/09.
        """
        preambule = "---\nname: exemple\ntype: note\n---\n\n# Le Vrai Titre\n\nIntro."
        self.assertEqual(embed._titre_de_section(preambule), 'Le Vrai Titre')
        self.assertEqual(embed._titre_de_section("## Section\ncorps"), 'Section')
        # Une section qui ouvre sur du texte n'a pas de titre — et on ne va pas
        # chercher celui d'une sous-partie plus bas.
        self.assertEqual(embed._titre_de_section("Du texte\n\n### Sous-partie"), '')
        self.assertEqual(embed._titre_de_section("---\njamais refermé"), '')

    def test_section_longue_garde_son_titre(self):
        """Une section trop longue est sous-découpée — son titre suit.

        `chunk_by_size` écrivait `title: ''` : le titre était une ligne plus
        haut, et il était jeté. 2 265 chunks sans titre, 30 % de l'index.
        """
        long_corps = "Contenu de paragraphe. " * 300
        chunks = embed.chunk_by_h2(f"## Ma Section\n{long_corps}", "test.md")
        self.assertGreater(len(chunks), 1, "la section aurait dû être sous-découpée")
        self.assertEqual({c['title'] for c in chunks}, {'Ma Section'})

    def test_aucun_chunk_sans_titre(self):
        """Un chunk sans titre perd son seul repère lisible — repli sur le fichier."""
        texte = ("---\nname: x\n---\n\n# Titre H1\n\n" + "Préambule assez long. " * 10
                 + "\n\n## Une Section\n" + "Corps de section. " * 10)
        chunks = embed.chunk_by_h2(texte, "projets/exemple.md")
        sans = [c for c in chunks if not (c['title'] or '').strip()]
        self.assertEqual(sans, [], f"{len(sans)} chunk(s) sans titre")

    # Colonnes qui doivent se rafraîchir quand un chunk est réécrit. Une absence
    # ici ne casse rien : la valeur se fige simplement à sa première insertion,
    # pour toujours. `title` l'était, `model` aussi — et pour
    # `model` l'oubli devenait vicieux avec le saut de réindexation : un
    # changement de modèle aurait figé l'ancien nom, la condition de saut n'aurait
    # plus jamais correspondu, et le brain aurait ré-embarqué sans se réparer.
    COLONNES_A_RAFRAICHIR = ('title', 'content_hash', 'chunk_text', 'model', 'scope')

    def test_les_colonnes_se_mettent_a_jour_en_base(self):
        """Chaque colonne rafraîchissable figure dans TOUTES les clauses d'upsert.

        Le test lit la source : le défaut est une **ligne absente** d'une clause
        SQL, et une ligne absente ne se teste pas par le comportement d'un module
        isolé. L'espacement est libre — la première version comptait une chaîne
        alignée au caractère près, et un simple réalignement la faisait échouer.
        """
        source = Path(embed.__file__).read_text(encoding='utf-8')
        clauses = source.count('ON CONFLICT(chunk_id) DO UPDATE SET')
        self.assertGreater(clauses, 0, "aucune clause d'upsert trouvée")
        manquantes = {}
        for colonne in self.COLONNES_A_RAFRAICHIR:
            motif = re.compile(rf'`?{colonne}`?\s*=\s*(COALESCE\()?excluded\.')
            trouve = len(motif.findall(source))
            if trouve < clauses:
                manquantes[colonne] = f'{trouve}/{clauses}'
        self.assertEqual(manquantes, {},
                         f'colonnes absentes de certaines clauses : {manquantes}')

    def test_stub_sections_are_skipped(self):
        """Section H2 au corps trop court → sautee (MIN_BODY_CHARS).

        Ce comportement n'etait couvert par aucun test : il se manifestait en
        faisant echouer ceux d'a cote, ce qui ressemble a une panne et n'en est
        pas une.
        """
        garde = f"## Vraie section\n{self.CORPS}"
        text = f"## Stub\ntrop court\n\n{garde}"
        chunks = embed.chunk_by_h2(text, "test.md")
        self.assertEqual([c['title'] for c in chunks], ['Vraie section'])

    def test_long_section_sub_chunked(self):
        """Section H2 trop longue → sous-chunking par taille."""
        long_content = "X" * (embed.CHUNK_TOKENS * 4 + 100)
        text = f"## Section longue\n{long_content}"
        chunks = embed.chunk_by_h2(text, "test.md")
        # Doit produire plusieurs chunks, pas boucler
        self.assertGreater(len(chunks), 1)

    def test_empty_text_fallback(self):
        """Texte vide → chunk_by_h2 retourne 1 chunk (vide) — chunk_file filtre en amont."""
        chunks = embed.chunk_by_h2("", "test.md")
        # Le fallback retourne toujours au moins 1 chunk ; chunk_file gère le cas vide avant appel
        self.assertEqual(len(chunks), 1)


# ══════════════════════════════════════════════════════════════════════════════
# embed.py — utilitaires
# ══════════════════════════════════════════════════════════════════════════════

class TestEmbedUtils(unittest.TestCase):

    def test_chunk_id_deterministic(self):
        """Même input → même chunk_id."""
        cid1 = embed.chunk_id("agents/test.md", "contenu du chunk")
        cid2 = embed.chunk_id("agents/test.md", "contenu du chunk")
        self.assertEqual(cid1, cid2)

    def test_chunk_id_different_inputs(self):
        """Inputs différents → chunk_id différents."""
        cid1 = embed.chunk_id("agents/test.md", "contenu A")
        cid2 = embed.chunk_id("agents/test.md", "contenu B")
        self.assertNotEqual(cid1, cid2)

    def test_chunk_id_format(self):
        """chunk_id commence par 'emb-'."""
        cid = embed.chunk_id("test.md", "texte")
        self.assertTrue(cid.startswith("emb-"))

    def test_vector_roundtrip(self):
        """Sérialiser puis désérialiser un vecteur → valeurs identiques."""
        vec = [0.1, 0.2, 0.3, -0.5, 1.0]
        blob = embed.vector_to_blob(vec)
        restored = embed.blob_to_vector(blob)
        for a, b in zip(vec, restored):
            self.assertAlmostEqual(a, b, places=5)

    def test_should_exclude_brain_engine(self):
        """brain-engine/ est exclu."""
        p = Path("/brain/brain-engine/embed.py")
        self.assertTrue(embed.should_exclude(p))

    def test_should_exclude_git(self):
        """.git/ est exclu."""
        p = Path("/brain/.git/config")
        self.assertTrue(embed.should_exclude(p))

    def test_should_not_exclude_agents(self):
        """agents/ n'est pas exclu."""
        p = Path("/brain/agents/helloWorld.md")
        self.assertFalse(embed.should_exclude(p))

    def test_should_not_exclude_claims(self):
        """claims/ n'est pas exclu."""
        p = Path("/brain/claims/sess-20260316-test.yml")
        self.assertFalse(embed.should_exclude(p))

    def test_file_unique_applique_les_filtres_du_corpus(self):
        """🔴 `--file` ne court-circuite plus la politique de corpus.

        Jusqu'au 11/09, `collect_files(target_file=...)` rendait immediatement
        sans appeler `should_exclude` ni `should_skip_by_zone` — que la boucle
        du corpus complet, elle, applique. Un `PUT /brain/<fichier>` sur un
        fichier exclu le faisait donc entrer dans l'index, et la purge
        hors-corpus l'en retirait au passage suivant du cron : un
        va-et-vient silencieux, avec une fenetre de 6 h.

        Mesure du 11/09 : 573 fichiers hors bruit sont exclus du corpus, dont
        385 dans `workspace/` et `handoffs/` — des zones ECRIVABLES par la
        route. L'index n'en portait aucun, parce que le cron refermait
        derriere : le defaut existait sans s'etre jamais materialise.

        Le temoin tient dans la paire : un fichier exclu rend une liste VIDE,
        un fichier accepte en rend une de UN. Sans le second, « vide » pourrait
        venir d'un `--file` qui ne marche plus du tout.
        """
        exclu = embed.BRAIN_ROOT / "brain-engine" / "embed.py"
        self.assertTrue(embed.should_exclude(exclu),
                        "le fichier temoin doit bien etre exclu du corpus")
        self.assertEqual(
            embed.collect_files(str(exclu.relative_to(embed.BRAIN_ROOT))), [],
            "un fichier hors corpus ne doit pas etre indexe par --file")

        accepte = embed.BRAIN_ROOT / "agents" / "AGENTS.md"
        if accepte.is_file():
            self.assertEqual(
                len(embed.collect_files(str(accepte.relative_to(embed.BRAIN_ROOT)))), 1,
                "temoin : un fichier DU corpus passe toujours par --file")


# ══════════════════════════════════════════════════════════════════════════════
# search.py — cosine_sim
# ══════════════════════════════════════════════════════════════════════════════

class TestCosineSim(unittest.TestCase):

    def test_identical_vectors(self):
        """Vecteurs identiques → similarité 1.0."""
        v = [0.1, 0.5, -0.3, 0.8]
        self.assertAlmostEqual(search.cosine_sim(v, v), 1.0, places=5)

    def test_opposite_vectors(self):
        """Vecteurs opposés → similarité -1.0."""
        v = [1.0, 0.0, 0.0]
        w = [-1.0, 0.0, 0.0]
        self.assertAlmostEqual(search.cosine_sim(v, w), -1.0, places=5)

    def test_orthogonal_vectors(self):
        """Vecteurs orthogonaux → similarité 0.0."""
        v = [1.0, 0.0]
        w = [0.0, 1.0]
        self.assertAlmostEqual(search.cosine_sim(v, w), 0.0, places=5)

    def test_zero_vector(self):
        """Vecteur nul → similarité 0.0 (pas de division par zéro)."""
        v = [0.0, 0.0, 0.0]
        w = [1.0, 2.0, 3.0]
        self.assertEqual(search.cosine_sim(v, w), 0.0)

    def test_symmetry(self):
        """cosine_sim(a, b) == cosine_sim(b, a)."""
        a = [0.3, -0.1, 0.7]
        b = [0.5, 0.2, -0.4]
        self.assertAlmostEqual(search.cosine_sim(a, b), search.cosine_sim(b, a), places=10)

    def test_range(self):
        """Résultat toujours dans [-1, 1]."""
        import random
        random.seed(42)
        for _ in range(50):
            a = [random.uniform(-1, 1) for _ in range(768)]
            b = [random.uniform(-1, 1) for _ in range(768)]
            sim = search.cosine_sim(a, b)
            self.assertGreaterEqual(sim, -1.0 - 1e-6)
            self.assertLessEqual(sim, 1.0 + 1e-6)


# ══════════════════════════════════════════════════════════════════════════════
# search.py — blob_to_vector
# ══════════════════════════════════════════════════════════════════════════════

class TestSearchUtils(unittest.TestCase):

    def test_blob_to_vector_roundtrip(self):
        """Blob → vecteur cohérent avec embed.vector_to_blob."""
        vec = [0.1, -0.2, 0.5, 1.0, -0.9]
        blob = embed.vector_to_blob(vec)
        restored = search.blob_to_vector(blob)
        for a, b in zip(vec, restored):
            self.assertAlmostEqual(a, b, places=5)

    def test_blob_to_vector_768_dims(self):
        """Blob de 768 floats → vecteur de 768 éléments."""
        vec = [float(i) / 768 for i in range(768)]
        blob = embed.vector_to_blob(vec)
        restored = search.blob_to_vector(blob)
        self.assertEqual(len(restored), 768)


# ══════════════════════════════════════════════════════════════════════════════
# Intégration — dry-run sur un fichier temporaire
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationDryRun(unittest.TestCase):

    def test_chunk_file_markdown(self):
        """chunk_file sur un vrai fichier .md → chunks non vides."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            # Corps > MIN_BODY_CHARS, sinon les deux sections sont vues comme
            # des stubs et le fichier ne rend qu'un seul chunk de repli.
            f.write("## Section A\nContenu de la section A, assez long pour compter.\n\n"
                    "## Section B\nContenu de la section B, assez long pour compter.\n")
            tmp = Path(f.name)
        try:
            with patch.object(embed, 'BRAIN_ROOT', tmp.parent):
                chunks = embed.chunk_file(tmp, 'h2')
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0]['title'], 'Section A')
            self.assertEqual(chunks[1]['title'], 'Section B')
        finally:
            tmp.unlink()

    def test_chunk_file_large_no_hang(self):
        """
        RÉGRESSION — chunk_file sur un fichier large (strategy=file)
        ne doit pas boucler indéfiniment.
        """
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("chunk_file en boucle infinie !")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(3)
        try:
            with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
                # focus.md fait ~11K — reproduire le cas exact du bug
                f.write("Contenu sans saut de ligne.\n" * 400)  # ~11 200 chars
                tmp = Path(f.name)
            with patch.object(embed, 'BRAIN_ROOT', tmp.parent):
                chunks = embed.chunk_file(tmp, 'file')
            self.assertGreater(len(chunks), 0)
        finally:
            signal.alarm(0)
            tmp.unlink()


# ══════════════════════════════════════════════════════════════════════════════
# migrate.py — parse_yml_field
# ══════════════════════════════════════════════════════════════════════════════

import migrate

class TestParseYmlField(unittest.TestCase):

    def test_basic_field(self):
        content = "sess_id: sess-20260316-test\nstatus: open\n"
        self.assertEqual(migrate.parse_yml_field(content, 'sess_id'), 'sess-20260316-test')
        self.assertEqual(migrate.parse_yml_field(content, 'status'), 'open')

    def test_quoted_value(self):
        content = 'story_angle: "Reprise BE-2 après crash"\n'
        self.assertEqual(migrate.parse_yml_field(content, 'story_angle'), 'Reprise BE-2 après crash')

    def test_missing_field_returns_default(self):
        content = "sess_id: test\n"
        self.assertIsNone(migrate.parse_yml_field(content, 'closed_at'))
        self.assertEqual(migrate.parse_yml_field(content, 'closed_at', 'fallback'), 'fallback')

    def test_field_with_spaces(self):
        content = "opened_at:  2026-03-16T13:40  \n"
        self.assertEqual(migrate.parse_yml_field(content, 'opened_at'), '2026-03-16T13:40')


# ══════════════════════════════════════════════════════════════════════════════
# migrate.py — migrate_claims + migrate_sessions (BE-2b)
# ══════════════════════════════════════════════════════════════════════════════

SCHEMA_PATH = Path(__file__).parent / 'schema.sql'

def make_in_memory_db():
    """Crée une DB SQLite in-memory avec le schéma brain + table embeddings."""
    import sqlite3
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    # Table embeddings créée par embed.connect() — pas dans schema.sql
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            chunk_id    TEXT PRIMARY KEY,
            filepath    TEXT NOT NULL,
            title       TEXT,
            chunk_text  TEXT NOT NULL,
            vector      BLOB,
            model       TEXT,
            indexed     INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


class TestMigrateClaims(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.claims_dir = Path(self.tmpdir.name) / 'claims'
        self.claims_dir.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_claim(self, filename, content):
        (self.claims_dir / filename).write_text(content)

    def test_migrate_single_claim(self):
        """Un claim valide est inséré dans la table claims."""
        self._write_claim('sess-20260316-test.yml', """
sess_id: sess-20260316-test
type: build-brain
scope: shadow-be2
status: open
opened_at: "2026-03-16T13:00"
handoff_level: FULL
""")
        conn = make_in_memory_db()
        with patch.object(migrate, 'BRAIN_ROOT', self.tmpdir.name):
            count = migrate.migrate_claims(conn)
        self.assertEqual(count, 1)
        row = conn.execute("SELECT * FROM claims WHERE sess_id='sess-20260316-test'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['status'], 'open')
        self.assertEqual(row['scope'], 'shadow-be2')

    def test_migrate_multiple_claims(self):
        """Plusieurs claims — tous insérés."""
        for i in range(3):
            self._write_claim(f'sess-2026031{i}-test.yml', f"""
sess_id: sess-2026031{i}-test
type: build-brain
scope: brain/
status: closed
opened_at: "2026-03-1{i}T10:00"
""")
        conn = make_in_memory_db()
        with patch.object(migrate, 'BRAIN_ROOT', self.tmpdir.name):
            count = migrate.migrate_claims(conn)
        self.assertEqual(count, 3)

    def test_migrate_idempotent(self):
        """Relancer migrate_claims ne duplique pas les données."""
        self._write_claim('sess-20260316-idem.yml', """
sess_id: sess-20260316-idem
type: brain
scope: brain/
status: open
opened_at: "2026-03-16T10:00"
""")
        conn = make_in_memory_db()
        with patch.object(migrate, 'BRAIN_ROOT', self.tmpdir.name):
            migrate.migrate_claims(conn)
            migrate.migrate_claims(conn)
        total = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        self.assertEqual(total, 1)

    def test_migrate_skips_non_yml(self):
        """Fichiers non .yml ignorés."""
        self._write_claim('README.md', "# not a claim")
        self._write_claim('sess-20260316-ok.yml', """
sess_id: sess-20260316-ok
type: brain
scope: brain/
status: closed
opened_at: "2026-03-16T10:00"
""")
        conn = make_in_memory_db()
        with patch.object(migrate, 'BRAIN_ROOT', self.tmpdir.name):
            count = migrate.migrate_claims(conn)
        self.assertEqual(count, 1)


class TestMigrateSessions(unittest.TestCase):
    """BE-2b — migrate_sessions dérive sessions depuis claims."""

    def _setup_claims(self, conn, claims):
        """Insère des claims directement en DB (sans passer par migrate_claims)."""
        for c in claims:
            conn.execute("""
                INSERT INTO claims(sess_id, type, scope, status, opened_at, handoff_level)
                VALUES (?,?,?,?,?,?)
            """, (c['sess_id'], c.get('type','brain'), c.get('scope','brain/'),
                  c.get('status','closed'), c.get('opened_at','2026-03-16T10:00'),
                  c.get('handoff_level','FULL')))
        conn.commit()

    def test_sessions_created_from_claims(self):
        """migrate_sessions crée autant de sessions que de claims."""
        conn = make_in_memory_db()
        self._setup_claims(conn, [
            {'sess_id': 'sess-A', 'opened_at': '2026-03-16T10:00'},
            {'sess_id': 'sess-B', 'opened_at': '2026-03-16T11:00'},
            {'sess_id': 'sess-C', 'opened_at': '2026-03-16T12:00'},
        ])
        count = migrate.migrate_sessions(conn)
        self.assertEqual(count, 3)

    def test_date_extracted_from_opened_at(self):
        """La date ISO est tronquée à YYYY-MM-DD dans sessions.date."""
        conn = make_in_memory_db()
        self._setup_claims(conn, [
            {'sess_id': 'sess-date-test', 'opened_at': '2026-03-16T13:40'},
        ])
        migrate.migrate_sessions(conn)
        row = conn.execute("SELECT date FROM sessions WHERE sess_id='sess-date-test'").fetchone()
        self.assertEqual(row['date'], '2026-03-16')

    def test_sessions_idempotent(self):
        """Relancer migrate_sessions ne duplique pas les sessions."""
        conn = make_in_memory_db()
        self._setup_claims(conn, [
            {'sess_id': 'sess-idem', 'opened_at': '2026-03-16T10:00'},
        ])
        migrate.migrate_sessions(conn)
        migrate.migrate_sessions(conn)
        total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        self.assertEqual(total, 1)

    def test_handoff_level_preserved(self):
        """handoff_level est propagé de claims vers sessions."""
        conn = make_in_memory_db()
        self._setup_claims(conn, [
            {'sess_id': 'sess-hl', 'opened_at': '2026-03-16T10:00', 'handoff_level': 'FULL'},
        ])
        migrate.migrate_sessions(conn)
        row = conn.execute("SELECT handoff_level FROM sessions WHERE sess_id='sess-hl'").fetchone()
        self.assertEqual(row['handoff_level'], 'FULL')

    def test_empty_claims_zero_sessions(self):
        """Aucun claim → aucune session."""
        conn = make_in_memory_db()
        count = migrate.migrate_sessions(conn)
        self.assertEqual(count, 0)


# ══════════════════════════════════════════════════════════════════════════════
# search.py — search() avec Ollama mocké + DB in-memory
# ══════════════════════════════════════════════════════════════════════════════

class TestSearchFunction(unittest.TestCase):
    """search() sur des fixtures — et vraiment sur elles.

    Ces cas montaient une base SQLite en mémoire et patchaient `sqlite3.connect`.
    Or `search()` passe par `brain_db.query()` → Dolt : la base montée n'était
    jamais lue et les tests s'exécutaient contre l'index réel du brain.

    Deux d'entre eux « passaient » quand même, parce que `cosine_sim` utilisait
    `zip()`, qui tronque silencieusement : une requête de 3 dimensions contre un
    index de 768 comparait les 3 premières composantes et rendait un résultat
    plausible. Un changement de modèle d'embedding aurait donc dégradé la
    recherche sans que rien ne le signale.

    L'isolation se fait maintenant à la couture qui existe — `_query_embeddings`,
    la lecture brute — et les écritures de suivi sont interceptées : aucun de ces
    cas ne touche la base réelle. `test_les_fixtures_sont_bien_lues` est le
    témoin qui le prouve.

    Depuis, `load_matrix()` garde la matrice en mémoire. Son empreinte
    interroge la vraie base : elle ne peut pas savoir qu'on a substitué la
    lecture. Chaque cas vide donc le cache d'abord — sans quoi il compare des
    fixtures à l'index réel du brain, exactement le défaut que ces tests
    corrigeaient.
    """

    def setUp(self):
        search.vider_cache()

    def _rows(self, entries):
        """Lignes telles que `_query_embeddings` les rend — pas une base montée."""
        return [{
            'chunk_id':   embed.chunk_id(e['filepath'], e['chunk_text']),
            'filepath':   e['filepath'],
            'title':      e['title'],
            'chunk_text': e['chunk_text'],
            'vector':     embed.vector_to_blob(e['vector']),
        } for e in entries]

    @contextlib.contextmanager
    def _isole(self, query_vec, entries):
        """Coupe search() de la base réelle — lecture ET écriture de suivi.

        ⚠️ **Réécrit le 11/09, et les six cas ont échoué pour le dire.** Ce bloc
        patchait `search.embed_query` et `search._query_embeddings` — deux
        coutures que `search()` n'emprunte plus depuis qu'il délègue le
        classement à `core.recherche`. L'isolation avait sauté : sans
        l'échec, ces cas auraient tourné contre l'index réel du brain, très
        exactement le défaut que leur docstring dit avoir corrigé.

        L'isolation ne se fait plus par substitution d'une fonction interne mais
        par **injection** — le CORE reçoit son dépôt et son encodeur, c'est sa
        conception. C'est plus robuste : un dépôt de test ne peut pas « rater »
        une couture, il EST la source.
        """
        from core.recherche import Recherche

        lignes = self._rows(entries)

        class DepotDeFixtures:
            """Rend les fixtures, et une empreinte stable pour le cache."""
            def query(self, sql, params=()):
                return lignes

            def query_one(self, sql, params=()):
                return {"m": "fixture", "n": len(lignes)}

        class EncodeurDeFixtures:
            def encode(self, texte):
                return query_vec

        ancien = search._MOTEUR_CORE
        search._MOTEUR_CORE = Recherche(DepotDeFixtures(), EncodeurDeFixtures())
        try:
            with patch.object(search.brain_db, 'execute',
                              return_value=0) as ecriture:
                yield ecriture
        finally:
            search._MOTEUR_CORE = ancien

    # Vecteurs à 3 dimensions : cohérents entre requête et fixtures, donc la
    # garde de dimension de search() est satisfaite sans dépendre du modèle réel.
    TROIS = [
        {'filepath': 'agents/a.md', 'title': 'A', 'chunk_text': 'chunk A',
         'vector': [1.0, 0.0, 0.0]},    # cos = 1.0 — le plus proche
        {'filepath': 'agents/b.md', 'title': 'B', 'chunk_text': 'chunk B',
         'vector': [0.0, 1.0, 0.0]},    # cos = 0.0
        {'filepath': 'agents/c.md', 'title': 'C', 'chunk_text': 'chunk C',
         'vector': [-1.0, 0.0, 0.0]},   # cos = -1.0 — le plus loin
    ]

    def test_les_fixtures_sont_bien_lues(self):
        """Témoin d'isolation : le résultat ne contient QUE les fixtures.

        C'est ce cas qui aurait dû échouer avant la correction — l'index réel
        porte des milliers de chunks, aucun nommé `agents/a.md`.
        """
        # min_score=-1.0 : sans ça, `agents/c.md` (cosinus -1) serait filtré et
        # le témoin dirait « manque un fichier » là où il n'y a rien à dire.
        with self._isole([1.0, 0.0, 0.0], self.TROIS) as ecriture:
            results = search.search("test", top_k=50, min_score=-1.0)
        self.assertEqual({r['filepath'] for r in results},
                         {'agents/a.md', 'agents/b.md', 'agents/c.md'})
        # Le suivi hit_count a bien été intercepté : rien n'est parti en base.
        self.assertTrue(ecriture.called)

    def test_returns_top_k_results(self):
        """search() retourne au plus top_k résultats."""
        with self._isole([1.0, 0.0, 0.0], self.TROIS):
            results = search.search("test", top_k=2)
        self.assertEqual(len(results), 2)

    def test_results_sorted_by_score_desc(self):
        """Les résultats sont triés par score décroissant."""
        entries = [
            {'filepath': 'a.md', 'title': '', 'chunk_text': 'A', 'vector': [1.0, 0.0, 0.0]},
            {'filepath': 'b.md', 'title': '', 'chunk_text': 'B', 'vector': [0.5, 0.5, 0.0]},
            {'filepath': 'c.md', 'title': '', 'chunk_text': 'C', 'vector': [0.0, 0.0, 1.0]},
        ]
        with self._isole([1.0, 0.0, 0.0], entries):
            results = search.search("test", top_k=3)
        scores = [r['score'] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_best_match_is_correct(self):
        """Le chunk le plus proche de la query est bien le premier résultat."""
        entries = [
            {'filepath': 'best.md', 'title': 'Best', 'chunk_text': 'best chunk',
             'vector': [1.0, 0.0, 0.0]},
            {'filepath': 'worst.md', 'title': 'Worst', 'chunk_text': 'worst chunk',
             'vector': [0.0, 1.0, 0.0]},
        ]
        with self._isole([1.0, 0.0, 0.0], entries):
            results = search.search("test", top_k=2)
        self.assertEqual(results[0]['filepath'], 'best.md')

    def test_min_score_filter(self):
        """Les chunks sous le score minimum sont filtrés."""
        entries = [
            {'filepath': 'high.md', 'title': '', 'chunk_text': 'H',
             'vector': [1.0, 0.0, 0.0]},   # cos = 1.0
            {'filepath': 'low.md',  'title': '', 'chunk_text': 'L',
             'vector': [0.0, 1.0, 0.0]},   # cos = 0.0
        ]
        with self._isole([1.0, 0.0, 0.0], entries):
            results = search.search("test", top_k=5, min_score=0.5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['filepath'], 'high.md')

    def test_ollama_unavailable_returns_empty(self):
        """Modèle d'embedding injoignable → liste vide, sans exception.

        Isolé par l'encodeur de fixtures qui rend `None`, et non plus par un
        patch de `search.embed_query` : le chemin passe par `core.recherche`
        depuis le 11/09, et cette fonction n'y est plus appelée.
        """
        with self._isole(None, self.TROIS):
            results = search.search("test")
        self.assertEqual(results, [])

    def test_empty_db_returns_empty(self):
        """Index vide → liste vide, sans exception."""
        with self._isole([1.0, 0.0, 0.0], []):
            results = search.search("test")
        self.assertEqual(results, [])

    def test_dimensions_incompatibles_sarretent_net(self):
        """Requête et index de dimensions différentes → erreur explicite.

        `zip()` tronquait ici en silence. La garde de `search()` doit dire
        laquelle des deux fait quelle taille, pas rendre un score plausible.
        """
        entries = [{'filepath': 'x.md', 'title': '', 'chunk_text': 'X',
                    'vector': [1.0, 0.0, 0.0, 0.0, 0.0]}]
        with self._isole([1.0, 0.0, 0.0], entries):
            with self.assertRaises(ValueError) as capture:
                search.search("test")
        # Le message vient de `core.recherche` depuis le 11/09 : il nomme LES
        # DEUX tailles au lieu d'annoncer « dimensions incompatibles ». On
        # vérifie donc le fond — qu'on puisse lire laquelle fait quelle taille —
        # plutôt qu'une formule. `DimensionsIncompatibles` hérite de
        # `ValueError`, l'`assertRaises` ci-dessus reste exact.
        message = str(capture.exception)
        self.assertIn('3', message)
        self.assertIn('5', message)
        self.assertIn("modèle d'embedding", message)


# ══════════════════════════════════════════════════════════════════════════════
# Convention temporelle — le brain compte en UTC
# ══════════════════════════════════════════════════════════════════════════════

class TestConventionUTC(unittest.TestCase):
    """Toutes les colonnes temporelles du brain sont en UTC.

    Deux conventions cohabitaient sans qu'aucune soit déclarée : Python écrivait
    en UTC, `NOW()` rendait l'heure locale du moteur Dolt. Le décalage a mordu
    trois fois — les claims le 22/08 (TTL réel de 2 h au lieu de 4), les locks le
    02/09 (tout lock de TTL < 120 min naissait expiré), et les mêmes locks côté
    shell, où un verrou de 30 minutes en paraissait 149 au serveur.

    La bascule était silencieuse : en SQLite, `db.py` traduit `NOW()` par
    `datetime('now')`, qui rend de l'UTC. Le même code a changé de sens en
    changeant de moteur.

    Ce test est ce qui manquait : sans lui, le quatrième incident est déjà écrit.
    """

    # Ce qui a le droit de nommer `NOW()`, et pourquoi. Une entrée sans raison
    # n'est pas une exception, c'est un oubli.
    TOLERES = {
        'db.py':          "couche de traduction — elle nomme NOW() pour le convertir",
    }
    # `brain-audit.sh` a perdu sa tolérance le 03/09. Elle disait « la convention
    # de `intentions.updated_at` n'est pas établie » — elle l'est depuis qu'on
    # l'a mesurée au lieu de la supposer : `dolt_history_intentions` donne la date
    # du commit qui a posé chaque valeur, et 74 versions sur 76 devançaient leur
    # commit de deux heures pile. La colonne était en heure locale ; elle est
    # passée en UTC, et son unique lecteur avec elle.

    def _sources(self):
        racine = Path(__file__).parent.parent
        yield from sorted((racine / 'brain-engine').glob('*.py'))
        yield from sorted((racine / 'scripts').glob('*.sh'))

    def test_aucune_ecriture_temporelle_en_heure_locale(self):
        fautifs = []
        for chemin in self._sources():
            if chemin.name == Path(__file__).name or chemin.name in self.TOLERES:
                continue
            dans_docstring = False
            for numero, ligne in enumerate(
                    chemin.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                # Un commentaire qui explique le piège n'est pas le piège — et les
                # scripts shell portent des docstrings Python en heredoc, où NOW()
                # est cité pour raconter la panne du 22/08.
                bascules = ligne.count('"""') + ligne.count("'''")
                etait_dedans = dans_docstring
                if bascules % 2:
                    dans_docstring = not dans_docstring
                if etait_dedans or dans_docstring or ligne.strip().startswith('#'):
                    continue
                if re.search(r'\bNOW\(\)', ligne):
                    fautifs.append(f'{chemin.name}:{numero}')
        self.assertEqual(fautifs, [],
                         "`NOW()` rend l'heure locale du moteur ; les colonnes du brain "
                         "sont en UTC. Utiliser UTC_TIMESTAMP(), et ne convertir qu'à "
                         f"l'affichage. Sites : {fautifs}")

    def test_les_tolerances_sont_motivees(self):
        """Une tolérance sans raison écrite se périme en silence."""
        for nom, raison in self.TOLERES.items():
            self.assertTrue(raison and len(raison) > 20,
                            f'{nom} est toléré sans raison lisible')


# ══════════════════════════════════════════════════════════════════════════════
# rag.py — BE-3a : couche RAG (formatters, déduplication, skip helloWorld)
# ══════════════════════════════════════════════════════════════════════════════

import rag


def _make_hit(filepath, score, chunk_text='chunk', title='', query='q'):
    return {
        'filepath':   filepath,
        'score':      score,
        'title':      title,
        'chunk_text': chunk_text,
        '_query':     query,
    }


class TestRagConstants(unittest.TestCase):

    def test_helloworld_skip_contains_focus(self):
        """focus.md est dans HELLOWORLD_SKIP (chargé par helloWorld)."""
        self.assertIn('focus.md', rag.HELLOWORLD_SKIP)

    def test_helloworld_skip_contains_kernel(self):
        self.assertIn('KERNEL.md', rag.HELLOWORLD_SKIP)

    def test_helloworld_skip_does_not_contain_adr(self):
        """Les ADRs ne sont pas dans HELLOWORLD_SKIP — ils doivent remonter."""
        self.assertFalse(any('ADR' in p for p in rag.HELLOWORLD_SKIP))

    def test_three_boot_queries(self):
        """Exactement 3 queries boot définies."""
        self.assertEqual(len(rag.RAG_BOOT_QUERIES), 3)

    def test_boot_queries_have_top_k(self):
        """Chaque query boot a un top_k > 0."""
        for query, top_k in rag.RAG_BOOT_QUERIES:
            self.assertIsInstance(query, str)
            self.assertGreater(top_k, 0)


class TestRagFormatCompact(unittest.TestCase):

    def test_empty_returns_empty_string(self):
        self.assertEqual(rag.format_compact([]), '')

    def test_contains_header(self):
        results = [_make_hit('ADR/001.md', 0.80)]
        out = rag.format_compact(results)
        self.assertIn('## Brain context', out)

    def test_contains_filepath(self):
        results = [_make_hit('ADR/001.md', 0.80)]
        out = rag.format_compact(results)
        self.assertIn('ADR/001.md', out)

    def test_contains_score(self):
        results = [_make_hit('ADR/001.md', 0.82)]
        out = rag.format_compact(results)
        self.assertIn('0.82', out)

    def test_title_prepended_to_excerpt(self):
        results = [_make_hit('f.md', 0.70, chunk_text='body', title='MyTitle')]
        out = rag.format_compact(results)
        self.assertIn('[MyTitle]', out)

    def test_query_grouping_header(self):
        """Deux résultats avec queries différentes → 2 sous-headers."""
        results = [
            _make_hit('a.md', 0.80, query='query A'),
            _make_hit('b.md', 0.70, query='query B'),
        ]
        out = rag.format_compact(results)
        self.assertIn('### query A', out)
        self.assertIn('### query B', out)

    def test_excerpt_max_120_chars(self):
        """L'extrait est tronqué à 120 chars."""
        long_text = 'X' * 300
        results = [_make_hit('f.md', 0.70, chunk_text=long_text)]
        out = rag.format_compact(results)
        # L'extrait dans la ligne = 120 chars max + "…" → ligne < 200 chars hors metadata
        line = [l for l in out.splitlines() if 'f.md' in l][0]
        # la partie après "— " est l'extrait ; on vérifie qu'il est borné
        excerpt_part = line.split('— ', 1)[1] if '— ' in line else ''
        self.assertLessEqual(len(excerpt_part.rstrip('…')), 120)

    def test_custom_label(self):
        results = [_make_hit('f.md', 0.70)]
        out = rag.format_compact(results, label='RAG — test')
        self.assertIn('RAG — test', out)


class TestRagFormatFull(unittest.TestCase):

    def test_empty_returns_empty_string(self):
        self.assertEqual(rag.format_full([]), '')

    def test_contains_full_chunk_text(self):
        long_text = 'Contenu complet ' * 20
        results = [_make_hit('f.md', 0.75, chunk_text=long_text)]
        out = rag.format_full(results)
        self.assertIn(long_text.strip(), out)

    def test_contains_filepath_header(self):
        results = [_make_hit('ADR/002.md', 0.75)]
        out = rag.format_full(results)
        self.assertIn('ADR/002.md', out)

    def test_custom_label(self):
        results = [_make_hit('f.md', 0.70)]
        out = rag.format_full(results, label='RAG — full')
        self.assertIn('RAG — full', out)


class TestRagFormatJson(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        import json
        self.assertEqual(json.loads(rag.format_json([])), [])

    def test_fields_present(self):
        import json
        results = [_make_hit('f.md', 0.80, chunk_text='text', title='T', query='q')]
        out = json.loads(rag.format_json(results))
        self.assertEqual(len(out), 1)
        self.assertIn('score', out[0])
        self.assertIn('filepath', out[0])
        self.assertIn('title', out[0])
        self.assertIn('chunk_text', out[0])
        self.assertIn('query', out[0])

    def test_score_rounded(self):
        import json
        results = [_make_hit('f.md', 0.123456789)]
        out = json.loads(rag.format_json(results))
        self.assertEqual(out[0]['score'], round(0.123456789, 4))


class TestRagBootDeduplication(unittest.TestCase):
    """
    Teste la logique de déduplication et skip helloWorld de run_boot_queries().
    Mocke semantic_search pour rester headless.
    """

    def _mock_search(self, hits_by_query):
        """
        hits_by_query = {query_str: [hit_dicts]}
        Retourne une fonction qui joue le rôle de semantic_search.
        """
        def _search(query, top_k=5, min_score=0.0, allowed_scopes=None):
            return hits_by_query.get(query, [])
        return _search

    def test_skip_helloworld_files(self):
        """Les fichiers HELLOWORLD_SKIP ne remontent pas dans les résultats boot."""
        hits = {
            rag.RAG_BOOT_QUERIES[0][0]: [
                _make_hit('focus.md', 0.90),          # doit être skippé
                _make_hit('ADR/001.md', 0.80),         # doit passer
            ],
            rag.RAG_BOOT_QUERIES[1][0]: [],
            rag.RAG_BOOT_QUERIES[2][0]: [],
        }
        with patch.object(rag, 'semantic_search', self._mock_search(hits)):
            results = rag.run_boot_queries()
        filepaths = [r['filepath'] for r in results]
        self.assertNotIn('focus.md', filepaths)
        self.assertIn('ADR/001.md', filepaths)

    def test_deduplication_across_queries(self):
        """Un filepath qui remonte dans 2 queries différentes n'est inclus qu'une fois."""
        common = _make_hit('workspace/sprint.md', 0.75, query=rag.RAG_BOOT_QUERIES[0][0])
        hits = {
            rag.RAG_BOOT_QUERIES[0][0]: [common],
            rag.RAG_BOOT_QUERIES[1][0]: [_make_hit('workspace/sprint.md', 0.65,
                                                    query=rag.RAG_BOOT_QUERIES[1][0])],
            rag.RAG_BOOT_QUERIES[2][0]: [],
        }
        with patch.object(rag, 'semantic_search', self._mock_search(hits)):
            results = rag.run_boot_queries()
        filepaths = [r['filepath'] for r in results]
        self.assertEqual(filepaths.count('workspace/sprint.md'), 1)

    def test_query_tag_preserved(self):
        """Chaque résultat conserve le tag _query de la query qui l'a produit."""
        q0 = rag.RAG_BOOT_QUERIES[0][0]
        hits = {
            q0: [_make_hit('ADR/001.md', 0.80, query=q0)],
            rag.RAG_BOOT_QUERIES[1][0]: [],
            rag.RAG_BOOT_QUERIES[2][0]: [],
        }
        with patch.object(rag, 'semantic_search', self._mock_search(hits)):
            results = rag.run_boot_queries()
        self.assertEqual(results[0]['_query'], q0)

    def test_empty_results_when_ollama_down(self):
        """Si semantic_search retourne [] partout → run_boot_queries retourne []."""
        hits = {q: [] for q, _ in rag.RAG_BOOT_QUERIES}
        with patch.object(rag, 'semantic_search', self._mock_search(hits)):
            results = rag.run_boot_queries()
        self.assertEqual(results, [])


# ══════════════════════════════════════════════════════════════════════════════
# server.py — BE-3b : Brain-as-a-Service (headless — pas de serveur réel lancé)
# ══════════════════════════════════════════════════════════════════════════════

import server as srv
from fastapi.testclient import TestClient

# Les clients de test sont la machine elle-même : sans jeton, le moteur ne
# répond qu'à elle — et TestClient se présente comme « testclient ».
LOCAL = ('127.0.0.1', 50000)


class TestServerAuth(unittest.TestCase):
    """Auth via Authorization: Bearer — sans token = dev, avec token = vérifié."""

    def setUp(self):
        self.client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)

    def test_no_token_env_allows_local_request(self):
        """Sans token configuré → la machine elle-même passe sans contrôle."""
        with patch.object(srv, '_TOKEN_MAP', {}):
            with patch.object(srv, 'run_single_query', return_value=[]):
                resp = self.client.get('/search?q=test')
        self.assertEqual(resp.status_code, 200)

    def test_no_token_env_refuses_remote_request(self):
        """Sans token configuré → une autre machine est refusée."""
        distant = TestClient(srv.app, raise_server_exceptions=False, client=('192.0.2.1', 50000))
        with patch.object(srv, '_TOKEN_MAP', {}):
            with patch.object(srv, 'run_single_query', return_value=[]):
                resp = distant.get('/search?q=test')
        self.assertEqual(resp.status_code, 403)

    def test_valid_token_accepted(self):
        """Bearer token correct → 200."""
        with patch.object(srv, '_TOKEN_MAP', {'secret': 'owner'}):
            with patch.object(srv, 'run_single_query', return_value=[]):
                resp = self.client.get('/search?q=test',
                                       headers={'Authorization': 'Bearer secret'})
        self.assertEqual(resp.status_code, 200)

    def test_wrong_token_rejected(self):
        """Bearer token incorrect → 403."""
        with patch.object(srv, '_TOKEN_MAP', {'secret': 'owner'}):
            resp = self.client.get('/search?q=test',
                                   headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(resp.status_code, 403)

    def test_missing_header_rejected(self):
        """Header absent quand token requis → 401."""
        with patch.object(srv, '_TOKEN_MAP', {'secret': 'owner'}):
            resp = self.client.get('/search?q=test')
        self.assertEqual(resp.status_code, 401)

    def test_token_not_in_query_param(self):
        """Token passé en query param n'est pas accepté comme auth."""
        with patch.object(srv, '_TOKEN_MAP', {'secret': 'owner'}):
            resp = self.client.get('/search?q=test&token=secret')
        self.assertIn(resp.status_code, [401, 422])  # pas autorisé, pas d'exception


class TestServerFormatResults(unittest.TestCase):
    """_format_results — filepath visibility, excerpt vs full, mode."""

    def _hit(self, filepath='f.md', score=0.80, chunk='body', title='T'):
        return {'filepath': filepath, 'score': score,
                'chunk_text': chunk, 'title': title, '_query': 'q'}

    def test_develop_mode_exposes_filepath(self):
        out = srv._format_results([self._hit()], full=False, mode='develop')
        self.assertIn('filepath', out['results'][0])

    def test_service_mode_hides_filepath(self):
        out = srv._format_results([self._hit()], full=False, mode='service')
        self.assertNotIn('filepath', out['results'][0])

    def test_compact_mode_has_excerpt_not_chunk(self):
        out = srv._format_results([self._hit(chunk='full content')], full=False, mode='develop')
        item = out['results'][0]
        self.assertIn('excerpt', item)
        self.assertNotIn('chunk_text', item)

    def test_full_mode_has_chunk_text(self):
        out = srv._format_results([self._hit(chunk='full content')], full=True, mode='develop')
        item = out['results'][0]
        self.assertIn('chunk_text', item)
        self.assertEqual(item['chunk_text'], 'full content')

    def test_count_matches_results(self):
        hits = [self._hit('a.md'), self._hit('b.md')]
        out = srv._format_results(hits, full=False, mode='develop')
        self.assertEqual(out['count'], 2)
        self.assertEqual(len(out['results']), 2)

    def test_score_rounded_to_4_decimals(self):
        out = srv._format_results([self._hit(score=0.123456789)], full=False, mode='develop')
        self.assertEqual(out['results'][0]['score'], round(0.123456789, 4))

    def test_empty_results(self):
        out = srv._format_results([], full=False, mode='develop')
        self.assertEqual(out, {'count': 0, 'results': []})


class TestServerRoutes(unittest.TestCase):
    """Routes /health /search /boot — mocked moteur."""

    def setUp(self):
        self.client = TestClient(srv.app, client=LOCAL)

    def test_health_returns_ok(self):
        with patch('sqlite3.connect') as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.execute.return_value.fetchone.return_value = [42]
            # Appel direct de la fonction
            resp = self.client.get('/health')
        self.assertIn(resp.status_code, [200, 503])  # 503 si brain.db absent en CI

    def test_search_requires_q(self):
        """GET /search sans ?q → 422 Unprocessable."""
        with patch.object(srv, '_TOKEN_MAP', {}):
            resp = self.client.get('/search')
        self.assertEqual(resp.status_code, 422)

    def test_search_mode_logged(self):
        """Le champ mode est accepté sans erreur."""
        with patch.object(srv, '_TOKEN_MAP', {}):
            with patch.object(srv, 'run_single_query', return_value=[]):
                resp = self.client.get('/search?q=test&mode=develop')
        self.assertEqual(resp.status_code, 200)

    def test_boot_endpoint_exists(self):
        """GET /boot répond (moteur mocké)."""
        with patch.object(srv, '_TOKEN_MAP', {}):
            with patch.object(srv, 'run_boot_queries', return_value=[]):
                resp = self.client.get('/boot')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 0)


class TestServerScript(unittest.TestCase):
    """bsi-server.sh — existence et exécutabilité."""

    SERVER_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'bsi-server.sh'

    def test_script_exists(self):
        self.assertTrue(self.SERVER_SCRIPT.exists())

    def test_script_executable(self):
        self.assertTrue(os.access(self.SERVER_SCRIPT, os.X_OK))

    def test_invalid_command_exits_nonzero(self):
        result = subprocess.run(
            ['bash', str(self.SERVER_SCRIPT), 'invalid'],
            capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)


class TestServerBe3c(unittest.TestCase):
    """BE-3c — mode=service masquage filepath, fichiers VPS."""

    def setUp(self):
        self.client = TestClient(srv.app, client=LOCAL)

    def test_service_mode_hides_filepath_end_to_end(self):
        """GET /search?mode=service → pas de filepath dans la réponse JSON."""
        hit = {'filepath': 'secret/path.md', 'score': 0.9,
                'chunk_text': 'body', 'title': 'T', '_query': 'q'}
        with patch.object(srv, '_TOKEN_MAP', {}):
            with patch.object(srv, 'run_single_query', return_value=[hit]):
                resp = self.client.get('/search?q=test&mode=service')
        self.assertEqual(resp.status_code, 200)
        item = resp.json()['results'][0]
        self.assertNotIn('filepath', item)

    def test_develop_mode_exposes_filepath_end_to_end(self):
        """GET /search?mode=develop → filepath présent dans la réponse JSON."""
        hit = {'filepath': 'ADR/001.md', 'score': 0.9,
                'chunk_text': 'body', 'title': 'T', '_query': 'q'}
        with patch.object(srv, '_TOKEN_MAP', {}):
            with patch.object(srv, 'run_single_query', return_value=[hit]):
                resp = self.client.get('/search?q=test&mode=develop')
        item = resp.json()['results'][0]
        self.assertIn('filepath', item)
        self.assertEqual(item['filepath'], 'ADR/001.md')

    def test_systemd_service_file_exists(self):
        """brain-engine.service présent dans scripts/."""
        svc = Path(__file__).parent.parent / 'scripts' / 'brain-engine.service'
        self.assertTrue(svc.exists(), f"Service absent : {svc}")

    def test_systemd_service_has_mysecrets_env(self):
        """Le service charge MYSECRETS via EnvironmentFile."""
        svc = Path(__file__).parent.parent / 'scripts' / 'brain-engine.service'
        content = svc.read_text()
        self.assertIn('EnvironmentFile', content)
        self.assertIn('MYSECRETS', content)

    def test_systemd_service_has_brain_token(self):
        """Le service ne hardcode pas BRAIN_TOKEN — il vient de EnvironmentFile."""
        svc = Path(__file__).parent.parent / 'scripts' / 'brain-engine.service'
        content = svc.read_text()
        self.assertNotIn('BRAIN_TOKEN=', content)  # jamais hardcodé dans le service

    def test_install_script_exists_and_executable(self):
        """install-brain-engine.sh existe et est exécutable."""
        script = Path(__file__).parent.parent / 'scripts' / 'install-brain-engine.sh'
        self.assertTrue(script.exists())
        self.assertTrue(os.access(script, os.X_OK))

    def test_mysecrets_has_brain_token_entry(self):
        """MYSECRETS declare BRAIN_TOKEN — sans qu'aucune valeur ne bouge.

        Le test cherchait `brain/MYSECRETS`. Le fichier vit dans
        `brain-secrets/`, satellite git-crypt, et `PATHS.md` le declare ainsi
        depuis le demenagement : la declaration etait juste, et fausse la ou
        elle s'executait. Le rouge permanent de `brain doctor` n'a jamais parle
        de la frontiere des secrets — il parlait d'un chemin perime.

        Et il lisait le fichier ENTIER en memoire pour y chercher un nom de cle.
        `grep -q` repond a la meme question sans qu'aucune valeur ne quitte le
        disque : c'est la seule facon correcte de tester un fichier de secrets.
        """
        mysecrets = Path(__file__).parent.parent / 'brain-secrets' / 'MYSECRETS'
        self.assertTrue(mysecrets.exists(), f"MYSECRETS absent : {mysecrets}")
        trouve = subprocess.run(['grep', '-q', 'BRAIN_TOKEN', str(mysecrets)],
                                capture_output=True)
        self.assertEqual(trouve.returncode, 0,
                         "MYSECRETS ne declare pas BRAIN_TOKEN")


class TestRagScript(unittest.TestCase):
    """Test existence et exécutabilité du script bash bsi-rag.sh."""

    RAG_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'bsi-rag.sh'

    def test_script_exists(self):
        self.assertTrue(self.RAG_SCRIPT.exists(), f"bsi-rag.sh absent : {self.RAG_SCRIPT}")

    def test_script_executable(self):
        self.assertTrue(os.access(self.RAG_SCRIPT, os.X_OK),
                        f"bsi-rag.sh non exécutable : {self.RAG_SCRIPT}")

    def test_script_help_passthrough(self):
        """bsi-rag.sh --help passe à rag.py et sort proprement (exit 0)."""
        result = subprocess.run(
            ['bash', str(self.RAG_SCRIPT), '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('brain-engine RAG', result.stdout)


# ══════════════════════════════════════════════════════════════════════════════
# brain-db-sync.sh — tests bash (--check mode)
# ══════════════════════════════════════════════════════════════════════════════

import subprocess

BRAIN_ROOT_PATH = Path(__file__).parent.parent
SYNC_SCRIPT     = BRAIN_ROOT_PATH / 'scripts' / 'brain-db-sync.sh'

class TestBrainDbSyncScript(unittest.TestCase):

    def test_script_exists_and_executable(self):
        """brain-db-sync.sh existe et est exécutable."""
        self.assertTrue(SYNC_SCRIPT.exists(), f"Script absent : {SYNC_SCRIPT}")
        self.assertTrue(os.access(SYNC_SCRIPT, os.X_OK),
                        f"Script non exécutable : {SYNC_SCRIPT}")

    def _brain_jetable(self, tmp: Path) -> Path:
        """Un brain minimal : le script, son lib/python.sh, les VRAIS `migrate.py`
        et `db.py` (une imitation se périme en silence), un handoff. Le script
        calcule BRAIN_ROOT depuis son chemin — on le COPIE, sinon il lirait et
        écrirait le vrai brain. Le venv est LIÉ : il porte le CORE que `db.py`
        importe."""
        (tmp / 'scripts' / 'lib').mkdir(parents=True)
        (tmp / 'brain-engine').mkdir()
        (tmp / 'handoffs').mkdir()
        shutil.copy(SYNC_SCRIPT, tmp / 'scripts' / 'brain-db-sync.sh')
        shutil.copy(BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'python.sh', tmp / 'scripts' / 'lib' / 'python.sh')
        for f in ('migrate.py', 'db.py', 'schema.sql'):
            shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, tmp / 'brain-engine' / f)
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv'
        if not venv.is_dir():
            # Sans le CORE, `db.py` ne s'importe pas : --check s'abstiendrait et
            # le test accuserait le code. Un worktree n'a pas de venv — le lier.
            self.skipTest(f"venv absent ({venv}) — le CORE que db.py importe n'est pas là")
        (tmp / 'brain-engine' / '.venv').symlink_to(venv)
        (tmp / 'handoffs' / 'a.md').write_text(
            '---\ntype: handoff\nstatus: active\ncreated: 2026-09-27\n---\n# a\n')
        # Un dépôt, comme un vrai brain : sans lui, l'ancien --check mourait sur
        # `git log` et le témoin tombait pour une autre raison que l'incident.
        for c in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't']):
            subprocess.run(['git', *c], cwd=tmp, check=True)
        subprocess.run(['git', 'add', 'handoffs'], cwd=tmp, check=True)
        subprocess.run(['git', 'commit', '-q', '--no-verify', '-m', 'h'], cwd=tmp, check=True)
        return tmp

    def _env(self, brain: Path) -> dict:
        """Rien n'est hérité de qui lance : le backend et la base sont DITS."""
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        return {**env, 'BRAIN_DB_BACKEND': 'sqlite', 'BRAIN_DB_PATH': str(brain / 'brain.db')}

    def _lancer(self, brain: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(['bash', str(brain / 'scripts' / 'brain-db-sync.sh'), *args],
                              cwd=brain, capture_output=True, text=True, env=self._env(brain))

    def _check(self, brain: Path) -> int:
        return self._lancer(brain, '--check').returncode

    def _base(self, brain: Path, sql: str):
        con = sqlite3.connect(brain / 'brain.db')
        try:
            con.execute(sql)
            con.commit()
        finally:
            con.close()

    def test_check_mesure_la_base_pas_le_journal(self):
        """--check compare la base à `handoffs/`, pas un horodatage à `sync.log`.

        Le premier cas est l'incident : un handoff sur le disque, absent de la
        base, et un journal qui dit « OK » après son commit — un `pull`
        divergent fait exactement ça. L'ancien --check le disait à jour.
        """
        with tempfile.TemporaryDirectory() as tmp:
            brain = self._brain_jetable(Path(tmp))
            sync = self._lancer(brain)
            self.assertEqual(sync.returncode, 0, sync.stdout + sync.stderr)
            self.assertEqual(self._check(brain), 0, "synchronisé → à jour")

            self._base(brain, "DELETE FROM handoffs WHERE filename = 'a.md'")
            self.assertEqual(self._check(brain), 2,
                             "handoff absent de la base, journal « OK » → stale")
            self._lancer(brain)
            self.assertEqual(self._check(brain), 0, "resynchronisé → à jour")

            (brain / 'handoffs' / 'a.md').write_text(
                '---\ntype: handoff\nstatus: consumed\ncreated: 2026-09-27\n---\n# a\n')
            self.assertEqual(self._check(brain), 2, "statut changé sur le disque → stale")
            self._lancer(brain)
            self.assertEqual(self._check(brain), 0, "le statut suit après synchro")

    def test_check_s_abstient_sans_base_et_ne_la_cree_pas(self):
        """Sans base, --check s'abstient (`SKIP`, sortie 0) — et surtout ne la
        crée pas : `sqlite3.connect()` fait naître le fichier qu'il ouvre."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = self._brain_jetable(Path(tmp))
            r = self._lancer(brain, '--check')
            self.assertEqual(r.returncode, 0)
            self.assertTrue(r.stdout.startswith('SKIP'), r.stdout)
            self.assertFalse((brain / 'brain.db').exists(), "le contrôle a créé la base")

    def test_check_n_ecrit_rien(self):
        """--check ne touche ni au journal ni à la base. Il écrivait dans
        sync.log, et cette suite — lancée par le doctor — déposait deux
        « STALE » à chaque passage dans le journal du VRAI brain."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = self._brain_jetable(Path(tmp))
            self._lancer(brain)
            journal = brain / 'brain-engine' / 'sync.log'
            avant = journal.read_bytes()
            con = sqlite3.connect(brain / 'brain.db')
            lignes = con.execute("SELECT * FROM handoffs ORDER BY filename").fetchall()
            con.close()
            self._check(brain)
            self.assertEqual(journal.read_bytes(), avant)
            con = sqlite3.connect(brain / 'brain.db')
            self.assertEqual(con.execute("SELECT * FROM handoffs ORDER BY filename").fetchall(), lignes)
            con.close()

    def test_install_hooks_script_exists(self):
        """install-brain-hooks.sh existe et est exécutable."""
        hooks_script = BRAIN_ROOT_PATH / 'scripts' / 'install-brain-hooks.sh'
        self.assertTrue(hooks_script.exists())
        self.assertTrue(os.access(hooks_script, os.X_OK))

    def test_install_hooks_check_mode_installed(self):
        """
        install-brain-hooks.sh --check : exit 0 si le hook est installé.
        Le hook est installé dans le vrai brain root (scripts/install-brain-hooks.sh
        calcule BRAIN_ROOT depuis dirname $0 — ne peut pas être redirigé).
        On vérifie l'état réel : le hook doit être présent en dev actif.
        """
        hooks_script = BRAIN_ROOT_PATH / 'scripts' / 'install-brain-hooks.sh'
        result = subprocess.run(
            ['bash', str(hooks_script), '--check'],
            cwd=str(BRAIN_ROOT_PATH),
            capture_output=True, text=True
        )
        # Exit 0 = installé, exit 1 = absent
        # Les deux sont acceptables — on vérifie juste que le script ne crash pas (pas exit > 1)
        self.assertLessEqual(result.returncode, 1,
                             f"Script crash inattendu (exit {result.returncode}): {result.stderr}")


# ══════════════════════════════════════════════════════════════════════════════
# distill.py — BE-5e (summarisation 2 passes)
# ══════════════════════════════════════════════════════════════════════════════

def _make_messages(n: int) -> list[dict]:
    """Génère n messages alternés user/assistant pour les tests."""
    roles = ['user', 'assistant']
    return [{'role': roles[i % 2], 'content': f'message {i}'} for i in range(n)]


class TestBuildContext(unittest.TestCase):

    def test_small_session_uses_all_messages(self):
        """Session ≤ MAX_MESSAGES → tous les messages sont inclus dans le contexte."""
        msgs = _make_messages(distill.MAX_MESSAGES)
        ctx = distill.build_context(msgs)
        # Chaque message doit apparaître
        self.assertIn('message 0', ctx)
        self.assertIn(f'message {distill.MAX_MESSAGES - 1}', ctx)

    def test_large_session_truncates_to_recent(self):
        """Session > MAX_MESSAGES → build_context prend les MAX_MESSAGES derniers."""
        msgs = _make_messages(distill.MAX_MESSAGES + 20)
        ctx = distill.build_context(msgs)
        # Les 20 premiers messages (trop anciens) ne doivent pas apparaître
        self.assertNotIn('message 0', ctx)
        # Les derniers doivent être présents
        self.assertIn(f'message {len(msgs) - 1}', ctx)

    def test_context_respects_max_chars(self):
        """build_context respecte max_chars même sur grande session."""
        msgs = _make_messages(10)
        ctx = distill.build_context(msgs, max_chars=50)
        self.assertLessEqual(len(ctx), 50)


class TestSummarize2Pass(unittest.TestCase):

    def test_splits_into_blocks_of_max_messages(self):
        """summarize_2pass appelle summarize une fois par bloc + 1 fois pour la passe finale."""
        n = distill.MAX_MESSAGES * 3  # 3 blocs complets
        msgs = _make_messages(n)

        call_count = []

        def fake_summarize(context, aspect):
            call_count.append(1)
            return f'- résumé bloc {len(call_count)}'

        with patch.object(distill, 'summarize', side_effect=fake_summarize):
            result = distill.summarize_2pass(msgs, 'decisions')

        # Pass 1 : 3 appels (un par bloc) + Pass 2 : 1 appel final = 4 total
        self.assertEqual(len(call_count), 4)
        self.assertIsNotNone(result)

    def test_partial_none_blocks_are_skipped(self):
        """Blocs dont summarize retourne None ne cassent pas la 2e passe."""
        n = distill.MAX_MESSAGES * 2
        msgs = _make_messages(n)

        responses = [None, '- décision bloc 2']  # bloc 1 → None, bloc 2 → bullet

        def fake_summarize(context, aspect):
            if responses:
                return responses.pop(0)
            return '- résumé final'

        with patch.object(distill, 'summarize', side_effect=fake_summarize):
            result = distill.summarize_2pass(msgs, 'decisions')

        # La passe 2 est appelée car il y a au moins 1 résumé partiel non-None
        self.assertIsNotNone(result)

    def test_all_none_blocks_returns_none(self):
        """Si tous les blocs renvoient None, summarize_2pass retourne None."""
        n = distill.MAX_MESSAGES * 2
        msgs = _make_messages(n)

        with patch.object(distill, 'summarize', return_value=None):
            result = distill.summarize_2pass(msgs, 'decisions')

        self.assertIsNone(result)

    def test_all_none_sentinel_blocks_returns_none(self):
        """Si tous les blocs renvoient 'none', summarize_2pass retourne None."""
        n = distill.MAX_MESSAGES * 2
        msgs = _make_messages(n)

        with patch.object(distill, 'summarize', return_value='none'):
            result = distill.summarize_2pass(msgs, 'decisions')

        self.assertIsNone(result)

    def test_single_block_still_calls_pass2(self):
        """Même avec exactement MAX_MESSAGES+1 messages (2 blocs dont 1 micro), pass 2 est appelée."""
        msgs = _make_messages(distill.MAX_MESSAGES + 1)
        call_args = []

        def fake_summarize(context, aspect):
            call_args.append(context[:30])
            return '- bullet test'

        with patch.object(distill, 'summarize', side_effect=fake_summarize):
            result = distill.summarize_2pass(msgs, 'todos')

        # Pass 1 : 2 blocs → 2 appels ; Pass 2 : 1 appel → total 3
        self.assertEqual(len(call_args), 3)
        self.assertIsNotNone(result)


class TestDistillSession2Pass(unittest.TestCase):
    """distill_session() sélectionne 1-pass ou 2-pass selon la taille de la session."""

    def _make_jsonl(self, n_messages: int) -> Path:
        """Crée un .jsonl temporaire avec n messages."""
        import json as _json
        tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w')
        for i in range(n_messages):
            role = 'user' if i % 2 == 0 else 'assistant'
            entry = {'message': {'role': role, 'content': f'contenu message {i}'}}
            tmp.write(_json.dumps(entry) + '\n')
        tmp.close()
        return Path(tmp.name)

    def test_small_session_uses_single_pass(self):
        """Session ≤ MAX_MESSAGES → summarize() appelé directement (pas summarize_2pass)."""
        jsonl = self._make_jsonl(distill.MAX_MESSAGES)
        try:
            with patch.object(distill, 'summarize', return_value='- décision test') as mock_sum, \
                 patch.object(distill, 'summarize_2pass') as mock_2pass, \
                 patch.object(distill, 'upsert_chunk'), \
                 patch.object(distill, 'get_embedding', return_value=None):
                distill.distill_session(jsonl, dry_run=True)
            mock_sum.assert_called()
            mock_2pass.assert_not_called()
        finally:
            jsonl.unlink(missing_ok=True)

    def test_large_session_uses_2pass(self):
        """Session > MAX_MESSAGES → summarize_2pass() appelé, pas summarize() directement."""
        jsonl = self._make_jsonl(distill.MAX_MESSAGES + 10)
        try:
            with patch.object(distill, 'summarize_2pass', return_value='- décision 2pass') as mock_2pass, \
                 patch.object(distill, 'summarize') as mock_sum, \
                 patch.object(distill, 'upsert_chunk'), \
                 patch.object(distill, 'get_embedding', return_value=None):
                distill.distill_session(jsonl, dry_run=True)
            mock_2pass.assert_called()
            mock_sum.assert_not_called()
        finally:
            jsonl.unlink(missing_ok=True)

    def test_large_session_dry_run_produces_chunks(self):
        """Grande session en dry-run → au moins 1 chunk produit par aspect non-vide."""
        jsonl = self._make_jsonl(distill.MAX_MESSAGES * 2)
        try:
            with patch.object(distill, 'summarize_2pass', return_value='- décision test') as mock_2pass:
                n = distill.distill_session(jsonl, dry_run=True)
            # 3 aspects × 1 bullet min
            self.assertGreater(n, 0)
        finally:
            jsonl.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════

class TestVizCachePeremption(unittest.TestCase):
    """La péremption du cache viz doit voir aussi les suppressions.

    `MAX(updated_at)` ne bouge pas quand on supprime : le détecteur ne voyait que
    les écritures. La purge des chemins sortis du corpus a retiré 2 427
    chunks d'un coup — sans second signal, le cache aurait continué de tracer des
    points qui n'existent plus, et rien ne l'aurait dit.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / 'brain-engine').mkdir()
        self.client = TestClient(srv.app, client=LOCAL)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pose_cache(self, n_points):
        """Cache horodaté dans le futur : le signal de date dit « frais »."""
        scopes = srv._SCOPE_ACCESS['owner']
        chemin = self.tmp / 'brain-engine' / f"viz_cache_{'-'.join(sorted(scopes))}.json"
        chemin.write_text(json.dumps({
            'points': [{'filepath': f'f{i}.md', 'zone': 'kernel',
                        'x': 0.0, 'y': 0.0, 'z': 0.0} for i in range(n_points)],
            'generated_at': '2099-01-01T00:00:00+00:00',
            'cached': True,
        }))
        return chemin

    @contextlib.contextmanager
    def _index(self, compte):
        """L'index annonce `compte` chunks, et une écriture bien antérieure au cache."""
        import db as brain_db

        def query_one(sql, params=None):
            if 'MAX(updated_at)' in sql:
                return {'m': datetime(2026, 1, 1)}
            if 'COUNT(*)' in sql:
                return {'n': compte}
            return None

        with patch.object(srv, 'BRAIN_ROOT', self.tmp), \
             patch.object(srv, '_is_localhost', return_value=True), \
             patch.object(brain_db, 'query_one', side_effect=query_one), \
             patch.object(brain_db, 'table_exists', return_value=True), \
             patch.object(brain_db, 'query', return_value=[]):
            yield

    def test_un_cache_au_bon_compte_est_servi_tel_quel(self):
        """Témoin négatif : sans écart, la route ne régénère pas."""
        self._pose_cache(5)
        with self._index(5):
            resp = self.client.get('/visualize')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('stale', resp.json())
        self.assertEqual(len(resp.json()['points']), 5)

    def test_des_points_supprimes_perime_le_cache(self):
        """L'index en a 5, le cache en trace 8 — la date dit « frais », le compte non."""
        self._pose_cache(8)
        with self._index(5):
            resp = self.client.get('/visualize')
        self.assertEqual(resp.status_code, 200)
        # La régénération a bien été tentée : elle échoue faute de lignes, et la
        # réponse le déclare au lieu de servir un cache périmé en silence.
        self.assertTrue(resp.json().get('stale'))
        self.assertIn('aucun chunk indexe', resp.json().get('regen_error', ''))


# ══════════════════════════════════════════════════════════════════════════════

class TestAgeDuFichier(unittest.TestCase):
    """Le signal de fraîcheur du TTL.

    `git log -1` seul avait deux défauts symétriques : muet sur ce qui n'est pas
    suivi (245 fichiers de la zone TTL, jamais périmés), menteur sur ce qui l'est
    (réécrire un frontmatter rajeunit un fichier dont le contenu n'a pas bougé).
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.f = self.tmp / 'note.md'
        self.f.write_text('# Note\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mtime_seule_quand_git_se_tait(self):
        """Un fichier hors dépôt a quand même un âge — sinon le TTL ne s'applique pas."""
        os.utime(self.f, (time.time() - 100 * 86400,) * 2)
        self.assertIsNone(embed.get_git_age_days(self.f))
        self.assertEqual(embed.get_age_days(self.f), 100)

    def test_retient_le_plus_recent_des_deux(self):
        """Éprouvé dans les deux sens : un `max` passerait un test à sens unique."""
        os.utime(self.f, (time.time() - 100 * 86400,) * 2)
        with patch.object(embed, 'get_git_age_days', return_value=90):
            self.assertEqual(embed.get_age_days(self.f), 90)
        with patch.object(embed, 'get_git_age_days', return_value=120):
            self.assertEqual(embed.get_age_days(self.f), 100)

    def test_aucun_signal_rend_none(self):
        """Sans git ni stat, pas d'âge — et le TTL s'abstient plutôt que d'exclure."""
        with patch.object(embed, 'get_git_age_days', return_value=None), \
             patch.object(embed, 'get_mtime_age_days', return_value=None):
            self.assertIsNone(embed.get_age_days(self.f))

    def test_outils_tiers_decompresses_exclus(self):
        """Un Ghidra déposé dans `learning/` pesait 987 chunks sur 7 899."""
        self.assertTrue(embed.should_exclude(
            Path('learning/retro-ingenierie/lab/tools/ghidra/docs/ChangeHistory.md')))
        self.assertFalse(embed.should_exclude(
            Path('learning/retro-ingenierie/notes-lab.md')))

    def test_le_plafond_refuse_l_absurde(self):
        """Une purge de 31 % de l'index est un évènement, pas une routine."""
        self.assertTrue(embed.depasse_le_plafond(2427, 7899))
        self.assertFalse(embed.depasse_le_plafond(400, 7899))
        self.assertFalse(embed.depasse_le_plafond(0, 0))


# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# brain-satellites.py — les satellites de la machine, à jour
# ══════════════════════════════════════════════════════════════════════════════

class TestBrainSatellites(unittest.TestCase):
    """Une forge JETABLE (dépôts nus), un brain qui en est cloné, et la vraie
    liste remplacée par une liste d'essai. Rien ne touche le vrai brain : le
    script reçoit `--brain`, et l'environnement ne transmet aucun `BRAIN_`.

    Le premier cas est l'incident du 27/09 : un satellite déclaré pour la
    machine, en retard sur son amont, et rien qui le dise."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'brain-satellites.py'

    def _git(self, *a, cwd):
        return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True, check=True)

    def _poste(self, depot: Path, fichier: str, contenu: str):
        (depot / fichier).write_text(contenu)
        self._git('add', fichier, cwd=depot)
        self._git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--no-verify',
                  '-m', fichier, cwd=depot)

    def _forge(self, tmp: Path, *noms: str) -> Path:
        forge = tmp / 'forge'
        for nom in noms:
            graine = tmp / 'graines' / nom
            graine.mkdir(parents=True)
            self._git('init', '-q', '-b', 'main', cwd=graine)
            self._poste(graine, 'LISEZ-MOI', nom)
            self._git('clone', '-q', '--bare', str(graine), str(forge / f'{nom}.git'), cwd=tmp)
        return forge

    def _pousser(self, tmp: Path, forge: Path, nom: str, fichier: str):
        voisin = tmp / f'voisin-{nom}-{fichier}'
        self._git('clone', '-q', str(forge / f'{nom}.git'), str(voisin), cwd=tmp)
        self._poste(voisin, fichier, 'amont')
        self._git('push', '-q', cwd=voisin)

    def _lancer(self, brain: Path, *args) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        return subprocess.run([sys.executable, str(self.SCRIPT), '--brain', str(brain), *args],
                              capture_output=True, text=True, env=env, timeout=120)

    def _brain(self, tmp: Path, machine='laptop') -> tuple[Path, Path]:
        forge = self._forge(tmp, 'brain', 'profil-depot', 'todo-depot', 'fixe-depot')
        brain = tmp / 'Brain'
        self._git('clone', '-q', str(forge / 'brain.git'), str(brain), cwd=tmp)
        (brain / 'brain-compose.local.yml').write_text(f'machine: {machine}\n')
        (brain / 'satellites.yml').write_text(
            'satellites:\n'
            '  profil: {depot: profil-depot, machines: [desktop, laptop]}\n'
            '  todo:   {depot: todo-depot,   machines: [desktop, laptop]}\n'
            '  fixe:   {depot: fixe-depot,   machines: [desktop]}\n')
        return brain, forge

    def test_un_satellite_en_retard_se_voit_et_se_rattrape(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brain, forge = self._brain(tmp)
            self.assertEqual(self._lancer(brain, '--check').returncode, 1, "deux absents → rouge")
            r = self._lancer(brain, '--cloner')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((brain / 'profil' / 'LISEZ-MOI').exists(), "cloné depuis l'URL du brain")
            self.assertFalse((brain / 'fixe').exists(), "un satellite d'une autre machine n'est pas cloné")
            self.assertEqual(self._lancer(brain, '--check').returncode, 0, "tout est là et à jour")

            self._pousser(tmp, forge, 'profil-depot', 'nouveau.md')     # l'incident
            r = self._lancer(brain, '--check')
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn('derrière', r.stdout)
            self.assertFalse((brain / 'profil' / 'nouveau.md').exists(), "--check n'a rien récupéré")
            self.assertEqual(self._lancer(brain, '--pull').returncode, 0)
            self.assertTrue((brain / 'profil' / 'nouveau.md').exists(), "--pull a avancé")
            self.assertEqual(self._lancer(brain, '--check').returncode, 0)

    def test_pull_ne_touche_ni_un_depot_devant_ni_un_fichier_modifie(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brain, forge = self._brain(tmp)
            self._lancer(brain, '--cloner')
            self._poste(brain / 'todo', 'local.md', 'jamais poussé')
            r = self._lancer(brain, '--pull')
            self.assertEqual(r.returncode, 1)
            self.assertIn('devant', r.stdout, "un commit non poussé se dit")

            self._pousser(tmp, forge, 'profil-depot', 'LISEZ-MOI')     # l'amont modifie un fichier…
            (brain / 'profil' / 'LISEZ-MOI').write_text('travail en cours')  # …modifié ici aussi
            r = self._lancer(brain, '--pull')
            self.assertIn('bloqué', r.stdout, r.stdout)
            self.assertIn('LISEZ-MOI', r.stdout, "le refus nomme le fichier protégé, pas « Aborting »")
            self.assertEqual((brain / 'profil' / 'LISEZ-MOI').read_text(), 'travail en cours',
                             "le travail en cours n'est jamais écrasé")

    def test_dossier_vide_se_clone_dossier_plein_jamais(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brain, _ = self._brain(tmp)
            (brain / 'profil').mkdir()                        # le wiki/ vide du laptop
            (brain / 'todo').mkdir()
            (brain / 'todo' / 'notes.txt').write_text('à moi')
            r = self._lancer(brain, '--cloner')
            self.assertTrue((brain / 'profil' / '.git').exists(), "un dossier vide se clone")
            self.assertEqual(sorted(p.name for p in (brain / 'todo').iterdir()), ['notes.txt'],
                             "un dossier avec du contenu n'est jamais écrasé")
            self.assertIn('pas un dépôt', self._lancer(brain, '--check').stdout)

    def test_un_depot_non_declare_se_dit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brain, _ = self._brain(tmp, machine='desktop')
            self._lancer(brain, '--cloner')
            self._git('init', '-q', str(brain / 'inconnu'), cwd=tmp)
            r = self._lancer(brain, '--check')
            self.assertEqual(r.returncode, 1)
            self.assertIn('non déclaré', r.stdout)

    def test_abstentions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brain, forge = self._brain(tmp)
            self._lancer(brain, '--cloner')
            (brain / 'brain-compose.local.yml').write_text('instances: {}\n')
            r = self._lancer(brain, '--check')
            self.assertEqual((r.returncode, r.stdout[:4]), (0, 'SKIP'), "machine inconnue → abstention")
            (brain / 'brain-compose.local.yml').write_text('machine: laptop-perso\n')
            r = self._lancer(brain, '--check')
            self.assertEqual(r.returncode, 1, "une machine que la liste ignore → rouge")
            self.assertIn('machines connues', r.stdout)
            (brain / 'brain-compose.local.yml').write_text('machine: laptop\n')
            shutil.rmtree(forge)                              # la forge ne répond plus
            r = self._lancer(brain, '--check')
            self.assertEqual((r.returncode, r.stdout[:4]), (0, 'SKIP'),
                             "rien mesuré → abstention, pas un vert : " + r.stdout)


# ══════════════════════════════════════════════════════════════════════════════
# sync-template.sh — ce qui part au gabarit
# ══════════════════════════════════════════════════════════════════════════════

class TestSyncTemplate(unittest.TestCase):
    """Un brain JETABLE réduit à ce que la synchro lit (~3 Mo), ses satellites
    liés en lecture, et un gabarit qui pousse vers un dépôt nu jetable. Rien ne
    touche le vrai `brain-template/` ni la forge.

    Le cas de l'incident : le filet contre les marqueurs d'instance était placé
    APRÈS le push — `--push` publiait, puis annonçait « sync interrompu »."""

    CHEMINS = ('scripts', 'agents', 'docs', 'contexts', 'workflows', 'brain-engine',
               'KERNEL.md', 'brain-compose.yml', 'brain-constitution.md',
               'MYSECRETS.example', 'brain-compose.local.yml.example')
    SATELLITES = ('profil', 'wiki', 'brain-ui')

    def setUp(self):
        manquants = [s for s in self.SATELLITES if not (BRAIN_ROOT_PATH / s).exists()]
        if manquants:
            self.skipTest(f"satellites absents ({', '.join(manquants)}) — la synchro les lit")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.brain = self.tmp / 'Brain'
        suivis = subprocess.run(['git', '-C', str(BRAIN_ROOT_PATH), 'ls-files', '--', *self.CHEMINS],
                                capture_output=True, text=True, check=True).stdout.split('\n')
        for rel in filter(None, suivis):
            src = BRAIN_ROOT_PATH / rel
            if src.is_file():
                (self.brain / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, self.brain / rel)
        for sat in self.SATELLITES:
            (self.brain / sat).symlink_to((BRAIN_ROOT_PATH / sat).resolve())
        # La sonde : une étiquette qui se retire, un renvoi pris dans la phrase.
        # Construits à l'exécution : ce fichier est distribué, et un renvoi
        # écrit en toutes lettres ici ferait refuser la synchro par son filet.
        self.etiquette = '[' + 'MY' + '-1]'
        self.renvoi = 'MY' + '-2'
        # Le chemin aussi : écrit en toutes lettres, le contrôle des liens morts le
        # prenait pour un lien vers un fichier absent (35 → 36, au seuil).
        self.chemin_sonde = 'contexts' + '/' + 'sonde.yml'
        (self.brain / 'contexts' / 'sonde.yml').write_text(
            f'# une raison {self.etiquette} dite\n# comme avant {self.renvoi} dans la phrase\ncle: 1\n')
        # Sans `GABARIT_DEPOT` hérité : sinon tous les rendus partiraient du
        # vrai brain-template de la machine (relecture du 28/09).
        self.env = {**{k: v for k, v in os.environ.items() if k != 'GABARIT_DEPOT'},
                    'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                    'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        self._git('init', '-q', cwd=self.brain)
        self._git('add', '-A', cwd=self.brain)
        self._git('commit', '-q', '--no-verify', '-m', 'b', cwd=self.brain)

    def tearDown(self):
        if hasattr(self, '_tmp'):
            self._tmp.cleanup()

    def _git(self, *a, cwd):
        return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True,
                              env=self.env, check=True)

    def _sync(self, *args):
        return subprocess.run(['bash', str(self.brain / 'scripts' / 'sync-template.sh'), *args],
                              cwd=self.brain, capture_output=True, text=True, env=self.env,
                              timeout=300)

    def test_une_etiquette_se_retire_un_renvoi_dans_la_phrase_refuse(self):
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        sonde = (rendu / 'contexts' / 'sonde.yml').read_text()
        self.assertIn('# une raison dite', sonde, "l'étiquette est retirée au rendu")
        self.assertIn(f'avant {self.renvoi}', sonde, "un renvoi dans la phrase n'est pas mutilé")
        self.assertEqual(r.returncode, 1, r.stdout[-400:])
        self.assertIn('RENVOI AU BACKLOG PRIVÉ', r.stdout)
        self.assertIn(self.chemin_sonde, r.stdout, "le filet nomme le fichier — même au-delà du dixième")
        self.assertIn('réécrire la SOURCE', r.stdout, "le filet va jusqu'à sa consigne")
        self.assertIn('cle: 1', (self.brain / 'contexts' / 'sonde.yml').read_text())
        self.assertIn(self.etiquette, (self.brain / 'contexts' / 'sonde.yml').read_text(),
                      "la SOURCE garde son étiquette")

    def test_un_push_refuse_ne_publie_rien(self):
        nu = self.tmp / 'forge.git'
        self._git('init', '-q', '--bare', '-b', 'main', str(nu), cwd=self.tmp)
        graine = self.tmp / 'graine'
        self._git('init', '-q', '-b', 'main', str(graine), cwd=self.tmp)
        (graine / 'LISEZ-MOI').write_text('gabarit')
        # Un fichier que la synchro MODIFIE : sans lui, l'ancien script ne
        # voyait « aucune modification » (il ignorait les fichiers neufs) et ne
        # poussait pas — le témoin passait pour une autre raison que la sienne.
        (graine / 'KERNEL.md').write_text('ancien noyau\n')
        self._git('add', '-A', cwd=graine)
        self._git('commit', '-q', '-m', 'init', cwd=graine)
        self._git('push', '-q', str(nu), 'main', cwd=graine)
        self._git('clone', '-q', str(nu), str(self.brain / 'brain-template'), cwd=self.tmp)
        avant = self._git('rev-parse', 'main', cwd=nu).stdout
        r = self._sync('--push')
        self.assertEqual(r.returncode, 1, "un renvoi dans la phrase refuse la synchro")
        self.assertEqual(self._git('rev-parse', 'main', cwd=nu).stdout, avant,
                         "RIEN n'est poussé quand le filet refuse")

    def test_ce_que_la_source_ne_suit_plus_sort_du_template(self):
        """`brain-engine/start.sh` était encore publié six mois après son retrait."""
        tpl = self.brain / 'brain-template'
        (tpl / 'brain-engine').mkdir(parents=True)
        self._git('init', '-q', str(tpl), cwd=self.tmp)
        (tpl / 'brain-engine' / 'start.sh').write_text('#!/bin/sh\n')
        self._sync()
        self.assertFalse((tpl / 'brain-engine' / 'start.sh').exists(),
                         "un fichier que la source ne suit plus est retiré")
        self.assertTrue((tpl / 'brain-engine' / 'db.py').exists(), "le reste est là")
        self.assertTrue((tpl / 'brain-engine' / 'README.md').exists(), "le README du template aussi")

    def test_le_moteur_du_gabarit_demarre_avec_son_core(self):
        """L'incident du 27/09 : la v2.2.0 livrait un moteur qui importait le CORE
        installé sur cette machine seulement. Le CORE est désormais copié dans
        `brain-engine/core/` du rendu : le moteur démarre sans rien d'ici."""
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        self.assertIn('le moteur du gabarit démarre', r.stdout, r.stdout[-600:])
        self.assertTrue((rendu / 'brain-engine' / 'core' / '__init__.py').exists())
        self.assertTrue((rendu / 'brain-engine' / 'core' / 'tests.py').exists(), "les tests partent aussi")
        self.assertEqual(list(rendu.rglob('__pycache__')), [], "rien de compilé ne part")

    def test_un_manifeste_ne_charge_que_ce_qui_part(self):
        """L'incident du 27/09 : les manifests publiés chargeaient en L1
        l'identité de l'owner (BRAIN-056 : jamais distribuée) et le disaient en
        commentaire. Le brain jetable porte les VRAIS manifests — le cas est
        l'incident, pas un exemple."""
        source = (self.brain / 'contexts' / 'session-brain.yml').read_text()
        identite = 'profil/' + 'identity/'
        self.assertIn(identite, source, "la source charge l'identité — le témoin a de quoi rougir")
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        publie = (rendu / 'contexts' / 'session-brain.yml').read_text()
        self.assertNotIn(identite, publie, r.stdout[-600:])
        self.assertIn('KERNEL.md', publie, "ce qui part reste chargé")
        self.assertIn('brain-compose.local.yml', publie,
                      "un fichier que le setup CRÉE n'est pas un chargement mort")
        self.assertIn(identite, (self.brain / 'contexts' / 'session-brain.yml').read_text(),
                      "la SOURCE garde ses chargements — c'est le boot de l'owner")

    def test_l_index_ne_presente_pas_les_agents_absents(self):
        """L'incident du 28/09 : `AGENTS.md` publié présentait `recruiter`,
        `coach-scribe`, `storyteller`… comme disponibles chez le fork.
        Le brain jetable porte le VRAI index."""
        ligne = '| `recruiter` |'
        self.assertIn(ligne, (self.brain / 'agents' / 'AGENTS.md').read_text(),
                      "la source présente le recruiter — le témoin a de quoi rougir")
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        self.assertFalse((rendu / 'agents' / 'recruiter.md').exists())
        index = (rendu / 'agents' / 'AGENTS.md').read_text()
        self.assertNotIn(ligne, index, r.stdout[-600:])
        self.assertIn('| `debug` |', index, "un agent qui part reste dans l'index")
        self.assertIn(ligne, (self.brain / 'agents' / 'AGENTS.md').read_text(),
                      "la SOURCE garde sa ligne — c'est l'index de l'owner")

    def test_un_nom_de_l_instance_refuse_la_synchro(self):
        """L'incident du 28/09 : des agents publiés disaient « l'infra réelle de
        <owner> » et prenaient ses projets en exemple — le filet ne cherchait que
        des chemins, des IP et des domaines."""
        nom = 'Tetard' + 'tek'                     # construit : ce fichier part au gabarit
        (self.brain / 'marqueurs-instance.txt').write_text('# liste\n\\b' + nom.lower() + '\\b(?!-cortex)\n')
        (self.brain / 'agents' / 'monitoring.md').write_text(f"connaît l'infra réelle de {nom}\n")
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        self.assertEqual(r.returncode, 1, r.stdout[-600:])
        self.assertIn("NOM DE L'INSTANCE", r.stdout)
        self.assertIn('agents/monitoring.md', r.stdout)
        self.assertFalse((rendu / 'marqueurs-instance.txt').exists(), "la liste ne part pas")

    def test_l_organisation_qui_publie_n_est_pas_un_nom(self):
        nom = 'Tetard' + 'tek'
        (self.brain / 'marqueurs-instance.txt').write_text('\\b' + nom.lower() + '\\b(?!-cortex)\n')
        (self.brain / 'agents' / 'monitoring.md').write_text(
            f"git clone https://github.com/{nom}-Cortex/Cortex-Template-Todo.git todo\n")
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        self.assertTrue("NOM DE L'INSTANCE" in r.stdout or "aucun nom de l'instance" in r.stdout,
                        "le filet a jugé : " + r.stdout[-400:])
        section = r.stdout.split("NOM DE L'INSTANCE")[1].split('🚨')[0] if "NOM DE L'INSTANCE" in r.stdout else ''
        self.assertNotIn('agents/monitoring.md', section, r.stdout[-600:])

    def _gabarit_publie(self, gitignore: str) -> None:
        tpl = self.brain / 'brain-template'
        self._git('init', '-q', '-b', 'main', str(tpl), cwd=self.tmp)
        (tpl / '.gitignore').write_text(gitignore)
        self._git('add', '-A', cwd=tpl)
        self._git('commit', '-q', '--no-verify', '-m', 'gabarit', cwd=tpl)

    def test_ce_que_git_ignore_ne_part_pas_et_refuse(self):
        """L'incident du 28/09 : le `.gitignore` du gabarit (`profil/*`, sans
        exception pour `specs/`) écartait les douze specs que la synchro écrit.
        Le `.gitignore` du témoin est celui du gabarit publié, mot pour mot."""
        self._gabarit_publie('profil/*\n!profil/README.md\n!profil/CLAUDE.md.example\n')
        r = self._sync('--rendre', str(self.tmp / 'rendu'))
        self.assertEqual(r.returncode, 1, r.stdout[-600:])
        self.assertIn('IGNORÉ PAR GIT', r.stdout)
        self.assertIn('profil/specs/', r.stdout)

    def test_un_gitignore_qui_laisse_passer_les_specs(self):
        self._gabarit_publie('profil/*\n!profil/README.md\n!profil/CLAUDE.md.example\n!profil/specs/\n')
        r = self._sync('--rendre', str(self.tmp / 'rendu'))
        self.assertIn('tout ce que la synchro écrit, git le publie', r.stdout, r.stdout[-600:])

    def test_le_rendu_part_du_gabarit_publie(self):
        """Un fichier qui n'existe que dans le gabarit publié (écrit pour lui)
        est dans le rendu : `--rendre` ne juge plus un gabarit que personne ne
        reçoit."""
        tpl = self.brain / 'brain-template'
        self._git('init', '-q', '-b', 'main', str(tpl), cwd=self.tmp)
        (tpl / 'focus.md').write_text('# écrit pour le gabarit\n')
        self._git('add', '-A', cwd=tpl)
        self._git('commit', '-q', '--no-verify', '-m', 'gabarit', cwd=tpl)
        rendu = self.tmp / 'rendu'
        self._sync('--rendre', str(rendu))
        self.assertTrue((rendu / 'focus.md').exists(), "le fichier propre au gabarit est rendu")
        self.assertTrue((rendu / 'KERNEL.md').exists(), "et la synchro a bien rendu le reste")

    def test_lister_voit_tout_ce_qui_part(self):
        r = self._sync('--lister')
        liste = set(r.stdout.split('\n'))
        for attendu in ('brain-engine/db.py', 'profil/specs/collaboration.md',
                        'KERNEL.md', self.chemin_sonde, 'brain-ui/package.json'):
            self.assertIn(attendu, liste, f"{attendu} part au gabarit")
        self.assertFalse(any(x.startswith('profil/identity') for x in liste), "BRAIN-056")
        # Le wiki ne part plus : six pages, 33 affirmations fausses.
        self.assertFalse(any(x.startswith('wiki/') for x in liste), "le wiki reste chez l'owner")

    def test_le_wiki_publie_autrefois_sort_du_gabarit(self):
        """Le rendu part du gabarit publié, qui porte encore les six pages :
        ne plus les envoyer ne suffit pas, il faut les retirer."""
        tpl = self.brain / 'brain-template'
        self._git('init', '-q', '-b', 'main', str(tpl), cwd=self.tmp)
        (tpl / 'wiki').mkdir()
        (tpl / 'wiki' / 'vocabulary.md').write_text('# 🟢 **free** — palier\n')
        self._git('add', '-A', cwd=tpl)
        self._git('commit', '-q', '--no-verify', '-m', 'gabarit', cwd=tpl)
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        self.assertTrue((rendu / 'KERNEL.md').exists(), r.stdout[-400:])
        self.assertFalse((rendu / 'wiki').exists(), r.stdout[-400:])


# ══════════════════════════════════════════════════════════════════════════════
# bsi-claim.sh open — le TTL du type
# ══════════════════════════════════════════════════════════════════════════════

class BrainBsiJetable(unittest.TestCase):
    """Un brain jetable pour `bsi-claim.sh` : le script, ses libs, le vrai
    `db.py`, une base SQLite jetable, `HOME` isolé, aucun `BRAIN_` hérité."""

    def setUp(self):
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv'
        if not venv.is_dir():
            self.skipTest(f"venv absent ({venv}) — le CORE que db.py importe n'est pas là")
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name)
        self.brain = t / 'Brain'
        (self.brain / 'scripts' / 'lib').mkdir(parents=True)
        (self.brain / 'brain-engine').mkdir()
        (self.brain / 'contexts').mkdir()
        shutil.copy(BRAIN_ROOT_PATH / 'scripts' / 'bsi-claim.sh', self.brain / 'scripts')
        for f in (BRAIN_ROOT_PATH / 'scripts' / 'lib').glob('*.*'):
            shutil.copy(f, self.brain / 'scripts' / 'lib')
        for f in ('db.py', 'schema.sql'):
            shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, self.brain / 'brain-engine' / f)
        (self.brain / 'brain-engine' / '.venv').symlink_to(venv)
        (self.brain / 'contexts' / 'session-pilote.yml').write_text('type: pilote\nttl_hours: 12\n')
        self.base = t / 'brain.db'
        con = sqlite3.connect(self.base)
        con.executescript((BRAIN_ROOT_PATH / 'brain-engine' / 'schema.sql').read_text())
        con.close()
        (t / 'home').mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('BRAIN_') and k != 'CLAUDE_CODE_SESSION_ID'}
        self.env.update(BRAIN_DB_BACKEND='sqlite', BRAIN_DB_PATH=str(self.base),
                        HOME=str(t / 'home'), BRAIN_PORT='1')

    def tearDown(self):
        if hasattr(self, '_tmp'):
            self._tmp.cleanup()

    def _bsi(self, *args, port='1'):
        return subprocess.run(['bash', str(self.brain / 'scripts' / 'bsi-claim.sh'), *args],
                              capture_output=True, text=True, timeout=60,
                              env={**self.env, 'BRAIN_PORT': port})

    def _open(self, sess, *args, port='1'):
        return self._bsi('open', sess, *args, port=port)


class TestFermetureRefusee(BrainBsiJetable):
    """Le repli dit le refus de la base comme la route : motif, longueurs, « resté
    OUVERT », et la valeur MASQUÉE. Un déclencheur SQLite joue le `varchar(64)`
    de Dolt — et, comme lui, recopie la valeur dans son message : c'est l'incident
    mesuré le 27/09 sur une branche Dolt jetable."""

    def test_un_result_trop_long_se_dit_sans_recopier_la_valeur(self):
        sess = 'sess-20260927-2330-work-t'
        self._open(sess, '--type', 'work', '--scope', 'work/t')
        con = sqlite3.connect(self.base)
        con.execute("CREATE TRIGGER mur BEFORE UPDATE OF result ON claims "
                    "WHEN length(NEW.result) > 64 BEGIN "
                    "SELECT RAISE(ABORT, 'string ' || char(39) || NEW.result || char(39)"
                    " || ' is too large'); END")
        con.commit()
        con.close()
        valeur = 'r' * 100
        r = self._bsi('close', sess, '--pas-le-mien', '--result', valeur)
        sortie = r.stdout + r.stderr
        self.assertEqual(r.returncode, 1, sortie[-300:])
        self.assertNotIn(valeur, sortie, "la valeur refusée ne s'affiche jamais")
        self.assertIn('reste OUVERT', sortie)
        self.assertIn("'result': 100", sortie, "les longueurs envoyées sont dites")
        self.assertNotIn('Traceback', sortie, "pas une trace brute")
        self.assertNotIn('COMPLETEMENT', sortie, "le repli n'annonce pas une fermeture qui n'a pas eu lieu")
        con = sqlite3.connect(self.base)
        statut = con.execute("SELECT status FROM claims WHERE sess_id = ?", (sess,)).fetchone()[0]
        con.close()
        self.assertEqual(statut, 'open')


    def test_une_fermeture_reussie_dit_son_bilan(self):
        sess = 'sess-20260927-2331-work-u'
        self._open(sess, '--type', 'work', '--scope', 'work/u')
        r = self._bsi('close', sess, '--pas-le-mien', '--result', 'ok')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('COMPLETEMENT', r.stdout, "le bilan se dit APRÈS l'écriture")


class TestMoteurAutonome(unittest.TestCase):
    """`moteur_autonome.py` : un moteur qui n'importe que le gabarit, son
    environnement et la bibliothèque standard démarre ; un moteur qui importe ce
    qui vit ailleurs sur cette machine ne démarre pas."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'moteur_autonome.py'

    def _juge(self, contenu: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            moteur = Path(tmp) / 'brain-engine'
            moteur.mkdir()
            for m in ('db', 'search', 'embed'):
                (moteur / f'{m}.py').write_text(contenu)
            return subprocess.run([sys.executable, str(self.SCRIPT), tmp],
                                  capture_output=True, text=True, timeout=60)

    def test_un_moteur_autonome_demarre(self):
        r = self._juge('import json, sqlite3\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_le_garde_ne_laisse_rien_derriere_lui(self):
        with tempfile.TemporaryDirectory() as tmp:
            moteur = Path(tmp) / 'brain-engine'
            moteur.mkdir()
            for m in ('db', 'search', 'embed'):
                (moteur / f'{m}.py').write_text('import json\n')
            subprocess.run([sys.executable, str(self.SCRIPT), tmp], capture_output=True, timeout=60)
            self.assertEqual(list(Path(tmp).rglob('__pycache__')), [],
                             "importer n'écrit pas de bytecode dans ce qui sera publié")

    def test_un_import_de_cette_machine_est_refuse(self):
        try:
            import core  # noqa: F401
        except ImportError:
            self.skipTest("le CORE n'est pas installé ici")
        r = self._juge('import core\n')
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('hors du gabarit', r.stdout)


class TestTtlDuType(BrainBsiJetable):
    """Sans `--ttl`, un claim prend le `ttl_hours` du manifeste de son type —
    par les DEUX chemins d'ouverture : la route du moteur (un serveur jetable
    capture le corps envoyé) et le repli (moteur injoignable, SQLite jetable).

    L'incident : des sessions `pilote` ouvertes à 4 h au lieu de 12, parce que
    le TTL ne dépendait que de l'appelant et que deux ouvertures prescrites
    l'oubliaient."""

    def _ttl(self, sess):
        con = sqlite3.connect(self.base)
        try:
            r = con.execute("SELECT ttl_hours FROM claims WHERE sess_id = ?", (sess,)).fetchone()
        finally:
            con.close()
        return r[0] if r else None

    def test_le_repli_prend_le_ttl_du_type(self):
        r = self._open('sess-20260927-1200-pilote-t', '--type', 'pilote', '--scope', 'pilote/t')
        self.assertEqual(self._ttl('sess-20260927-1200-pilote-t'), 12, r.stdout + r.stderr)

    def test_ttl_explicite_reste_une_surcharge_et_sans_manifeste_4h(self):
        self._open('sess-20260927-1201-pilote-u', '--type', 'pilote', '--scope', 'pilote/u', '--ttl', '2')
        self.assertEqual(self._ttl('sess-20260927-1201-pilote-u'), 2, "--ttl l'emporte")
        self._open('sess-20260927-1202-satellite-v', '--type', 'satellite', '--scope', 'x/v')
        self.assertEqual(self._ttl('sess-20260927-1202-satellite-v'), 4, "sans manifeste : le défaut")

    def test_la_route_du_moteur_recoit_le_ttl_du_type(self):
        import http.server, json, threading
        recu = {}

        class Capture(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0))
                recu.update(json.loads(self.rfile.read(n)))
                corps = json.dumps({'sess_id': recu.get('sess_id'), 'expires_at': 'x'}).encode()
                self.send_response(201)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *a):
                pass

        serveur = http.server.HTTPServer(('127.0.0.1', 0), Capture)
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        try:
            self._open('sess-20260927-1203-pilote-w', '--type', 'pilote', '--scope', 'pilote/w',
                       port=str(serveur.server_address[1]))
        finally:
            serveur.shutdown()
            serveur.server_close()
        self.assertEqual(recu.get('ttl_hours'), 12, recu)


# ══════════════════════════════════════════════════════════════════════════════
# dolt-setup.sh — la base d'un fork, en Dolt
# ══════════════════════════════════════════════════════════════════════════════

class TestDoltSetup(unittest.TestCase):
    """Un brain jetable, le VRAI Dolt du système sur un port libre, un
    `systemctl` factice qui enregistre ses appels : rien ne touche la base de
    prod ni le gestionnaire de services. Le vrai `db.py` doit lire la base créée.

    L'incident : `brain-setup.sh` ne savait rien de Dolt, un fork restait en
    SQLite — où le CORE refuse la purge, et l'indexation s'arrête."""

    def setUp(self):
        import shutil as _sh
        if not _sh.which('dolt'):
            self.skipTest('dolt absent de cette machine')
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv'
        if not venv.is_dir():
            self.skipTest('venv absent — le CORE que db.py importe')
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name)
        self.brain = t / 'Brain'
        (self.brain / 'scripts').mkdir(parents=True)
        (self.brain / 'brain-engine').mkdir()
        shutil.copy(BRAIN_ROOT_PATH / 'scripts' / 'dolt-setup.sh', self.brain / 'scripts')
        # dolt-setup.sh charge scripts/lib/premieres.sh depuis le 28/09 : le brain
        # jetable doit la porter, comme le gabarit la porte.
        (self.brain / 'scripts' / 'lib').mkdir(exist_ok=True)
        shutil.copy(BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'premieres.sh', self.brain / 'scripts' / 'lib')
        for f in ('schema-dolt.sql', 'views-dolt.sql', '.env.local.example', 'db.py'):
            shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, self.brain / 'brain-engine' / f)
        (self.brain / 'brain-engine' / '.venv').symlink_to(venv)
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.fausse = t / 'bin'
        self.fausse.mkdir()
        self.journal = t / 'systemctl.log'
        (self.fausse / 'systemctl').write_text(f'#!/bin/sh\necho "$@" >> {self.journal}\n')
        (self.fausse / 'systemctl').chmod(0o755)
        self.env = {**{k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')},
                    'HOME': str(t / 'home'), 'XDG_CONFIG_HOME': str(t / 'config'),
                    'BRAIN_DOLT_PORT': str(self.port),
                    'PATH': f"{self.fausse}:{os.environ['PATH']}"}
        (t / 'home').mkdir()

    def tearDown(self):
        if hasattr(self, '_tmp'):
            self._tmp.cleanup()

    def _setup(self, *args):
        return subprocess.run(['bash', str(self.brain / 'scripts' / 'dolt-setup.sh'), *args],
                              capture_output=True, text=True, env=self.env, timeout=120)

    def test_la_base_se_cree_se_sert_et_db_la_lit(self):
        r = self._setup('--sans-service')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        base = self.brain / 'brain-dolt'
        self.assertTrue((base / '.dolt').is_dir())
        self.assertIn(f'port: {self.port}', (base / 'config.yaml').read_text())
        env_local = (self.brain / 'brain-engine' / '.env.local').read_text()
        self.assertIn('BRAIN_DB_BACKEND=dolt', env_local)
        self.assertIn(f'BRAIN_DOLT_PORT={self.port}', env_local)
        serveur = subprocess.Popen(['dolt', 'sql-server', '--config', 'config.yaml'], cwd=base,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import socket, time as _t
            for _ in range(100):
                try:
                    socket.create_connection(('127.0.0.1', self.port), 0.2).close(); break
                except OSError:
                    _t.sleep(0.1)
            # Le VRAI db.py, qui lit .env.local de CE brain : rien d'hérité.
            env = {k: v for k, v in self.env.items() if not k.startswith('BRAIN_')}
            q = subprocess.run([str(self.brain / 'brain-engine' / '.venv' / 'bin' / 'python3'), '-c',
                                'import sys; sys.dont_write_bytecode=True; sys.path.insert(0, "brain-engine"); import db; '
                                'print(db.BACKEND, db.query_one("select count(*) n from claims")["n"])'],
                               cwd=self.brain, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(q.stdout.split()[-2:], ['dolt', '0'], q.stdout + q.stderr)
        finally:
            serveur.terminate()
            serveur.wait(10)

    def test_l_unite_d_un_autre_brain_n_est_pas_remplacee(self):
        # Sur une machine qui a déjà sa base servie par dolt-server.service, le
        # setup d'un fork remplaçait l'unité : au prochain démarrage, la prod
        # servait la base VIDE du fork (relecture du 28/09).
        unites = Path(self.env['XDG_CONFIG_HOME']) / 'systemd' / 'user'
        unites.mkdir(parents=True)
        autre = '[Service]\nWorkingDirectory=/ailleurs/un-autre-brain/brain-dolt\n'
        (unites / 'dolt-server.service').write_text(autre)
        r = self._setup()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('AUTRE brain', r.stdout + r.stderr)
        self.assertEqual((unites / 'dolt-server.service').read_text(), autre, "l'unité de l'autre est intacte")
        journal = self.journal.read_text() if self.journal.exists() else ''
        self.assertNotIn('enable', journal, "systemctl n'a rien activé")

    def test_relancer_ne_casse_rien(self):
        self._setup('--sans-service')
        (self.brain / 'brain-dolt' / 'config.yaml').write_text('# à moi\n')
        r = self._setup('--sans-service')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('existe déjà', r.stdout)
        self.assertEqual((self.brain / 'brain-dolt' / 'config.yaml').read_text(), '# à moi\n',
                         "un config.yaml existant est gardé")

    def test_le_service_s_ecrit_et_s_active(self):
        r = self._setup()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        unite = Path(self.env['XDG_CONFIG_HOME']) / 'systemd' / 'user' / 'dolt-server.service'
        self.assertIn(f"WorkingDirectory={self.brain / 'brain-dolt'}", unite.read_text())
        appels = self.journal.read_text()
        self.assertIn('--user daemon-reload', appels)
        self.assertIn('--user enable --now dolt-server.service', appels)


class TestDefautDuBackend(unittest.TestCase):
    """Sans `BRAIN_DB_BACKEND` ni `.env.local`, le brain vise Dolt — `db.py` ET
    `migrate.py`, le même défaut. Ils ont déjà divergé ; et le défaut
    `sqlite` faisait créer en silence un `brain.db` vide."""

    def test_les_deux_modules_disent_dolt(self):
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv'
        if not venv.is_dir():
            self.skipTest('venv absent')
        with tempfile.TemporaryDirectory() as tmp:
            moteur = Path(tmp) / 'brain-engine'
            moteur.mkdir()
            for f in ('db.py', 'migrate.py'):
                shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, moteur / f)
            env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
            r = subprocess.run([str(venv / 'bin' / 'python3'), '-c',
                                'import sys; sys.dont_write_bytecode=True; sys.path.insert(0, "brain-engine"); '
                                'import db, migrate; print(db.BACKEND, migrate.backend_declare())'],
                               cwd=tmp, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.stdout.split()[-2:], ['dolt', 'dolt'], r.stdout + r.stderr)
            self.assertFalse((Path(tmp) / 'brain.db').exists(), "aucune base créée par défaut")


class TestBrainEngineNeTouchePasLesAutres(unittest.TestCase):
    """Deux brains sur une machine. `brain-engine.sh stop` de l'un ne doit
    jamais arrêter le moteur de l'autre.

    L'incident du 27/09 : le repli `pgrep -f "python3.*brain-engine/server.py"`
    attrapait le moteur de N'IMPORTE QUEL brain. Un essai de fork l'a appelé à
    côté de la prod, qui n'a survécu que par chance. Le témoin : un
    faux moteur, lancé en `python3 <autre>/brain-engine/server.py`, exactement
    la forme que l'ancien motif reconnaissait."""

    def _brain(self, racine: Path) -> Path:
        (racine / 'scripts' / 'lib').mkdir(parents=True)
        (racine / 'brain-engine').mkdir()
        for rel in ('scripts/brain-engine.sh', 'scripts/lib/python.sh'):
            shutil.copy(BRAIN_ROOT_PATH / rel, racine / rel)
        # Un serveur qui dort : assez pour exister dans `ps`, rien d'autre.
        (racine / 'brain-engine' / 'server.py').write_text('import time\ntime.sleep(60)\n')
        return racine

    def test_stop_n_arrete_pas_le_moteur_d_un_autre_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            autre = self._brain(Path(tmp) / 'autre')
            ici = self._brain(Path(tmp) / 'ici')
            moteur = subprocess.Popen(['python3', str(autre / 'brain-engine' / 'server.py')])
            try:
                time.sleep(0.3)
                env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
                env['PATH'] = f"/nonexistent:{env.get('PATH', '')}"
                r = subprocess.run(['bash', str(ici / 'scripts' / 'brain-engine.sh'), 'stop'],
                                   capture_output=True, text=True, timeout=30, env=env)
                self.assertIsNone(moteur.poll(),
                                  f"le moteur de l'AUTRE brain a été arrêté\n{r.stdout}{r.stderr}")
                self.assertIn("n'est pas en cours", r.stdout)
            finally:
                moteur.kill()
                moteur.wait()

    def _lancer(self, brain: Path, *, fichier_de_pid: bool):
        moteur = subprocess.Popen(['python3', str(brain / 'brain-engine' / 'server.py')])
        if fichier_de_pid:
            (brain / '.brain-engine.pid').write_text(str(moteur.pid))
        time.sleep(0.3)
        return moteur

    def _stop(self, brain: Path):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        return subprocess.run(['bash', str(brain / 'scripts' / 'brain-engine.sh'), 'stop'],
                              capture_output=True, text=True, timeout=30, env=env)

    def test_stop_arrete_ce_que_start_a_lance(self):
        # Avec SON fichier de PID. Couvre aussi `((i++))`, qui rendait 1 quand
        # i valait 0 : sous `set -e`, `stop` mourait après le premier `kill`,
        # sans jamais dire « arrêté » ni retirer le fichier.
        with tempfile.TemporaryDirectory() as tmp:
            ici = self._brain(Path(tmp) / 'ici')
            moteur = self._lancer(ici, fichier_de_pid=True)
            try:
                r = self._stop(ici)
                moteur.wait(timeout=10)
                self.assertIn('brain-engine arrêté', r.stdout, r.stdout + r.stderr)
                self.assertFalse((ici / '.brain-engine.pid').exists())
            finally:
                if moteur.poll() is None:
                    moteur.kill()

    def test_un_fichier_de_pid_recycle_ne_fait_pas_tuer_un_inconnu(self):
        # Après un redémarrage, le numéro du fichier de PID peut désigner
        # n'importe quel processus : `kill -0` seul le faisait tuer par `stop`.
        with tempfile.TemporaryDirectory() as tmp:
            ici = self._brain(Path(tmp) / 'ici')
            inconnu = subprocess.Popen(['sleep', '60'])
            try:
                (ici / '.brain-engine.pid').write_text(str(inconnu.pid))
                self._stop(ici)
                time.sleep(0.3)
                self.assertIsNone(inconnu.poll(), "un processus étranger a été tué par `stop`")
            finally:
                inconnu.kill()
                inconnu.wait()

    def _port_libre(self) -> int:
        import socket
        with socket.socket() as so:
            so.bind(('127.0.0.1', 0))
            return so.getsockname()[1]

    def _start(self, brain: Path, port_dolt: int, dans_env_local: bool = False):
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv' / 'bin'
        if not (venv / 'python3').exists():
            self.skipTest("pas de venv : `start` exige fastapi")
        (brain / 'brain-engine' / '.env.local').write_text(
            'BRAIN_DB_BACKEND=dolt\n' + (f'BRAIN_DOLT_PORT={port_dolt}\n' if dans_env_local else ''))
        (brain / 'brain-dolt').mkdir(exist_ok=True)
        (brain / 'brain-engine' / 'mcp_server.py').write_text('import time\ntime.sleep(60)\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(PATH=f"{venv}:{env.get('PATH', '')}",
                   BRAIN_PORT=str(self._port_libre()), BRAIN_MCP_PORT=str(self._port_libre()))
        if not dans_env_local:
            env['BRAIN_DOLT_PORT'] = str(port_dolt)
        return subprocess.run(['bash', str(brain / 'scripts' / 'brain-engine.sh'), 'start'],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_start_refuse_la_base_d_un_autre_brain(self):
        # Un second brain sur la machine : « le port répond » n'est pas « c'est
        # ma base ». Il se serait branché sur la base de l'autre — la prod.
        with tempfile.TemporaryDirectory() as tmp:
            ici = self._brain(Path(tmp) / 'ici')
            autre = Path(tmp) / 'autre' / 'brain-dolt'
            autre.mkdir(parents=True)
            port = self._port_libre()
            base = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'],
                                    cwd=autre, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.8)
                r = self._start(ici, port)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('pas avec la base de ce brain', r.stdout + r.stderr)
                self.assertFalse((ici / '.brain-engine.pid').exists(), "le moteur ne devait pas démarrer")
            finally:
                base.kill()
                base.wait()

    def test_le_port_de_la_base_se_lit_dans_env_local(self):
        # `dolt-setup.sh` écrit BRAIN_DOLT_PORT dans .env.local ; `start` ne
        # lisait que l'environnement, et visait 3307 (relecture du 28/09).
        # Dans un espace réseau isolé : 3307 n'y existe pas, rien de la prod.
        with tempfile.TemporaryDirectory() as tmp:
            ici = self._brain(Path(tmp) / 'ici')
            (ici / 'brain-dolt').mkdir()
            port = self._port_libre()
            base = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'],
                                    cwd=ici / 'brain-dolt', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.8)
                r = self._start(ici, port, dans_env_local=True)
                self.assertIn(f'le port {port} sert déjà la base de ce brain', r.stdout, r.stdout + r.stderr)
            finally:
                self._stop(ici)
                base.kill()
                base.wait()

    def test_start_reutilise_la_base_de_ce_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ici = self._brain(Path(tmp) / 'ici')
            (ici / 'brain-dolt').mkdir()
            port = self._port_libre()
            base = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'],
                                    cwd=ici / 'brain-dolt', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.8)
                r = self._start(ici, port)
                self.assertIn('sert déjà la base de ce brain', r.stdout, r.stdout + r.stderr)
            finally:
                self._stop(ici)
                base.kill()
                base.wait()

    def test_stop_ne_tue_pas_le_moteur_de_ce_brain_lance_par_un_autre(self):
        # Sans fichier de PID : le moteur de CE brain lancé par systemd ou pm2.
        # Le trouver par son chemin et l'arrêter proprement, c'est un arrêt que
        # `Restart=on-failure` ne relance pas — la prod éteinte par un `stop`.
        with tempfile.TemporaryDirectory() as tmp:
            ici = self._brain(Path(tmp) / 'ici')
            moteur = self._lancer(ici, fichier_de_pid=False)
            try:
                r = self._stop(ici)
                self.assertIsNone(moteur.poll(), "un moteur non lancé par `start` a été arrêté")
                self.assertIn('pas lancé par ce script', r.stdout)
            finally:
                moteur.kill()
                moteur.wait()


class TestDocsVerite(unittest.TestCase):
    """Un gabarit JETABLE, et des pages qui nomment des choses. Chaque ligne
    fautive est copiée mot pour mot de la doc publiée en v2.2.1 — le premier
    cas d'un contrôle est l'incident, pas un exemple fabriqué."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'docs-verite.py'

    def _gabarit(self, tmp: Path, page: str) -> Path:
        g = tmp / 'gabarit'
        for rel, contenu in {
            'agents/debug.md': '# debug', 'agents/coach.md': '# coach',
            'contexts/session-work.yml': 'type: work',
            'contexts/session-explore.yml': 'type: explore',
            'scripts/brain-engine.sh': 'cmd="$1"\ncase "$cmd" in\n  start) ;;\n  stop) ;;\nesac\n',
            'scripts/brain-setup.sh': 'BRAIN_NAME="$1"\necho x > brain-engine/.env.local\n'
                                      'echo "bash scripts/brain-engine.sh start"\n',
            'scripts/bsi-claim.sh': '# Usage: bsi-claim.sh <open|close|close-stale>\n',
            'skills/brain/SKILL.md': '# skill\n',
            'docs/page.md': page,
        }.items():
            (g / rel).parent.mkdir(parents=True, exist_ok=True)
            (g / rel).write_text(contenu)
        return g

    def _juger(self, page: str, *, sans_agents: bool = False):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._gabarit(Path(tmp), page)
            if sans_agents:
                shutil.rmtree(g / 'agents')
            r = subprocess.run([sys.executable, str(self.SCRIPT), '--gabarit', str(g)],
                               capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    def _faux(self, ligne: str, regle: str):
        code, sortie = self._juger(ligne + '\n')
        self.assertEqual(code, 1, f"{ligne!r} doit rougir\n{sortie}")
        self.assertIn(f'[{regle}]', sortie)

    def _vrai(self, ligne: str):
        code, sortie = self._juger(ligne + '\n')
        self.assertEqual(code, 0, f"{ligne!r} ne doit pas rougir\n{sortie}")

    # ── Les incidents de la v2.2.1 ──

    def test_un_badge_de_palier(self):
        self._faux('> 🟢 **free** — Observe en silence. Intervient uniquement sur un risque critique.', 'retiré')

    def test_la_mecanique_des_paliers(self):
        self._faux('Valide la Brain API Key au boot. Pas de cle → tier free (silencieux, pas d\'erreur).', 'retiré')

    def test_un_boot_d_avant_les_sessions_v2(self):
        # Tel qu'il était : dans un bloc de code de workflows.md.
        self._faux('```\nbrain boot mode debug/mon-projet\n```', 'boot')

    def test_le_mode_seul_suffit_a_rougir(self):
        # Le type est juste : seul le `mode` d'avant les sessions V2 est faux.
        code, sortie = self._juger('```\nbrain boot mode work/mon-projet\n```\n')
        self.assertEqual(code, 1, sortie)
        self.assertIn('`brain boot mode …`', sortie)

    def test_un_type_de_session_qui_n_existe_pas(self):
        code, sortie = self._juger('- `brain boot urgence`\n')
        self.assertEqual(code, 1)
        self.assertIn('`urgence` n\'est pas un type de session', sortie)

    def test_un_script_qui_n_existe_pas(self):
        # Le chemin se CONSTRUIT : écrit en toutes lettres dans ce fichier
        # distribué, le contrôle des liens morts le compte comme un vrai renvoi.
        mort = 'scripts/' + 'ownership.sh'
        self._faux(f'> Tu peux aussi le faire manuellement : `bash {mort}`', 'chemin')

    def test_un_lien_vers_une_page_absente(self):
        self._faux('| [vue-tiers.md](vue-tiers.md) | Comparatif — tous les tiers d\'un coup d\'oeil |', 'lien')

    def test_un_agent_supprime(self):
        self._faux('> 🧭 `key-guardian` · `pre-flight`', 'agent')

    def test_une_sous_commande_inconnue(self):
        self._faux('`bash scripts/brain-engine.sh restart`', 'commande')

    def test_une_variable_non_rendue(self):
        self._faux('> Envie de comprendre le projet avant de fork ? → [${story_HOST}](https://x)', 'gabarit')

    # ── Ce qui ne doit PAS rougir ──

    def test_des_tiers_sont_des_tierces_parties(self):
        self._vrai('- Configurer un relay tiers (Brevo) sans confirmation')

    def test_always_tier_est_un_budget_de_contexte(self):
        self._vrai('| always-tier total | < 1 500 lignes | > 2 000 lignes | context-tier-split requis |')

    def test_un_argument_n_est_pas_une_sous_commande(self):
        self._vrai('`bash scripts/brain-setup.sh mon-brain ~/Dev/Brain`')

    def test_une_sous_commande_connue(self):
        self._vrai('`bash scripts/brain-engine.sh start`')

    def test_un_fichier_que_le_setup_cree(self):
        self._vrai('Le backend se choisit dans `brain-engine/.env.local`.')

    def test_un_nom_cite_par_un_script_ne_blanchit_pas_un_chemin_mort(self):
        # `brain-setup.sh` du témoin écrit `brain-engine/.env.local` : le NOM
        # `.env.local` y est, mais `wiki/.env.local` n'est écrit par personne.
        self._faux('Voir `wiki/.env.local`.', 'chemin')

    def test_une_route_bsi_n_est_pas_le_dossier_claims(self):
        self._vrai('| POST | `/bsi/claims/touch` | Repousse l\'expiration des claims ouverts |')

    def test_le_dossier_claims_rougit(self):
        self._faux('- `claims/` — quelle session est active, sur quoi', 'retiré')

    def test_un_boot_juste(self):
        self._vrai('`brain boot work/mon-projet`')

    def test_une_ligne_qui_declare_citer_un_retrait(self):
        self._vrai('`key-guardian` a été supprimé par BRAIN-072. <!-- docs-verite: permis -->')

    # ── Relecture du 28/09 ──

    def test_la_prose_n_est_pas_une_commande(self):
        self._vrai('Tape `brain boot` puis choisis ton type, ou lance brain boot et laisse faire.')
        self._vrai('Le script bash scripts/brain-engine.sh gère le moteur.')

    def test_les_sous_commandes_d_un_script_qui_aiguille_ailleurs(self):
        # `bsi-claim.sh` aiguille en Python : c'est sa ligne d'usage qui dit ses
        # sous-commandes. Le script le plus cité de la doc n'était jamais jugé.
        self._faux('`bash scripts/bsi-claim.sh ouvre un claim`', 'commande')
        self._vrai('`bash scripts/bsi-claim.sh close-stale`')

    def test_un_prefixe_n_est_pas_un_chemin_ecrit_par_un_script(self):
        self._faux('Voir `scripts/brain-eng` pour démarrer.', 'chemin')

    def test_un_marqueur_mal_forme_rougit(self):
        self._faux('Il y a {{ NB_AGENTS }} agents.', 'gabarit')
        self._faux('<!-- genere:outils-mcp -->', 'gabarit')

    def test_un_shell_en_bloc_n_est_pas_un_gabarit(self):
        self._vrai('```bash\nexport BRAIN_ROOT="${HOME}/Dev/Brain"\n```')

    def test_un_lien_avec_titre_ou_vers_un_script_est_juge(self):
        self._faux('[la page](absente.md "titre")', 'lien')
        # Construit : écrit en entier, le contrôle des liens morts le compterait.
        self._faux('[le script](../' + 'scripts/' + 'nexistepas.sh)', 'lien')

    def test_un_motif_n_est_pas_un_chemin(self):
        self._vrai('Chaque type a son manifest : `contexts/session-*.yml`, `contexts/session-<type>.yml`.')

    def test_toutes_les_racines_sont_jugees(self):
        self._faux('Voir `skills/brain/nexiste.md`.', 'chemin')
        self._vrai('Voir `skills/brain/SKILL.md`.')

    def test_un_modele_d_issue_qui_demande_un_palier(self):
        # La ligne publiée jusqu'au 28/09, mot pour mot, dans .github/.
        with tempfile.TemporaryDirectory() as tmp:
            g = self._gabarit(Path(tmp), 'rien\n')
            (g / '.github' / 'ISSUE_TEMPLATE').mkdir(parents=True)
            (g / '.github' / 'ISSUE_TEMPLATE' / 'bug_report.md').write_text(
                '## Environnement\n\n- Claude Code : [ex: dernière version]\n- Tier : [free / pro / full]\n')
            r = subprocess.run([sys.executable, str(self.SCRIPT), '--gabarit', str(g)],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('.github/ISSUE_TEMPLATE/bug_report.md', r.stdout)

    def test_un_gabarit_illisible_n_est_pas_un_vert(self):
        code, sortie = self._juger('rien\n', sans_agents=True)
        self.assertEqual(code, 2, sortie)


class TestDocsVeriteRenvois(unittest.TestCase):
    """Un agent distribué qui renvoie à un agent absent du gabarit le dit
    conditionnel. Les lignes fautives sont celles des agents publiés
    jusqu'au 28/09, copiées mot pour mot."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'docs-verite.py'

    def _juger(self, agent: str, *, avec_brain: bool = True):
        with tempfile.TemporaryDirectory() as tmp:
            g, b = Path(tmp) / 'gabarit', Path(tmp) / 'brain'
            for racine in (g, b):
                (racine / 'agents').mkdir(parents=True)
                (racine / 'contexts').mkdir()
                (racine / 'contexts' / 'session-work.yml').write_text('type: work')
                (racine / 'agents' / 'debug.md').write_text('# debug')
            # L'agent privé n'existe que chez l'auteur.
            (b / 'agents' / 'recruiter.md').write_text('# recruiter')
            (b / 'agents' / 'coach-scribe.md').write_text('# coach-scribe')
            (g / 'agents' / 'agent-review.md').write_text(agent)
            cmd = [sys.executable, str(self.SCRIPT), '--gabarit', str(g)]
            if avec_brain:
                cmd += ['--brain', str(b)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    def test_un_renvoi_vers_un_agent_prive(self):
        code, sortie = self._juger('- On veut créer un nouvel agent → `recruiter`\n')
        self.assertEqual(code, 1, sortie)
        self.assertIn('[renvoi]', sortie)

    def test_un_renvoi_en_toutes_lettres(self):
        code, sortie = self._juger('> Le recruiter forge. L\'agent-review détecte et signale uniquement.\n')
        self.assertEqual(code, 1, sortie)

    def test_une_delegation_en_pseudo_code(self):
        # session-orchestrator, à la fermeture : un bloc de code est ici une consigne.
        code, sortie = self._juger('```\n  IF tags CONTAINS "coach":    → coach-scribe\n```\n')
        self.assertEqual(code, 1, sortie)

    def test_un_renvoi_conditionnel(self):
        code, sortie = self._juger('- On veut créer un nouvel agent → `recruiter` (si présent)\n')
        self.assertEqual(code, 0, sortie)

    def test_le_frontmatter_et_l_historique_ne_delegent_pas(self):
        code, sortie = self._juger('---\nsends_to: [human, recruiter]\n---\n'
                                   '| 2026-03-12 | Création — signal recruiter |\n')
        self.assertEqual(code, 0, sortie)

    def test_un_nom_plus_long_n_est_pas_l_agent(self):
        code, sortie = self._juger('Voir `recruiter-bis` et coach-scribes.\n')
        self.assertEqual(code, 0, sortie)

    def test_sans_brain_rien_n_est_absent(self):
        code, sortie = self._juger('- → `recruiter`\n', avec_brain=False)
        self.assertEqual(code, 0, sortie)


class TestSkillBrain(unittest.TestCase):
    """La skill distribuée se charge : un frontmatter lisible, un `name` et une
    `description` — c'est la seule partie qu'un agent lit avant de décider de
    l'ouvrir. Et elle est à jour de ses sources."""

    RACINE = BRAIN_ROOT_PATH / 'skills' / 'brain'

    def test_le_frontmatter_se_lit(self):
        import yaml
        texte = (self.RACINE / 'SKILL.md').read_text()
        self.assertTrue(texte.startswith('---\n'))
        fm = yaml.safe_load(texte[4:texte.index('\n---', 4)])
        self.assertEqual(fm['name'], 'brain')
        self.assertGreater(len(fm['description']), 80)

    def test_chaque_page_citee_existe(self):
        texte = (self.RACINE / 'SKILL.md').read_text()
        for page in re.findall(r'\]\(([a-z-]+\.md)\)', texte):
            self.assertTrue((self.RACINE / page).is_file(), page)

    def test_la_skill_est_a_jour(self):
        r = subprocess.run([sys.executable, str(BRAIN_ROOT_PATH / 'scripts' / 'docs-generer.py'),
                            '--brain', str(BRAIN_ROOT_PATH), '--check'],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestDocsServies(unittest.TestCase):
    """La barre latérale du dashboard vient de ce que les pages DÉCLARENT.

    L'incident : `server.py` devinait les libellés depuis le nom du fichier, avec
    une table qui annonçait encore les vues par palier (`vue-free`, `vue-pro`…)
    supprimées par BRAIN-072 — et une page renommée perdait sa place."""

    def setUp(self):
        self.client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        self._tmp = tempfile.TemporaryDirectory()
        racine = Path(self._tmp.name)
        (racine / 'docs').mkdir()
        # `ordre: 0` : l'ordre déclaré CONTREDIT l'alphabet — sinon le test
        # passerait sans le tri (relecture du 28/09).
        (racine / 'docs' / 'moteur.md').write_text(
            '---\n# généré\nlabel: Brain-engine\ngroupe: Utiliser\nordre: 0\n---\n# Le moteur\n')
        (racine / 'docs' / 'demarrer.md').write_text(
            '---\nlabel: Démarrer\ngroupe: Démarrer\nordre: 1\n---\n# Démarrer\n')
        (racine / 'docs' / 'sans-entete.md').write_text('# rien de déclaré\n')
        (racine / 'docs' / 'README.md').write_text('# index\n')
        self._patch = patch.object(srv, 'BRAIN_ROOT', racine)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_une_page_dit_son_libelle_son_groupe_son_ordre(self):
        docs = self.client.get('/docs').json()['docs']
        self.assertEqual([d['name'] for d in docs], ['moteur', 'demarrer', 'sans-entete'],
                         "dans l'ordre déclaré, README exclu")
        moteur = next(d for d in docs if d['name'] == 'moteur')
        self.assertEqual((moteur['label'], moteur['group']), ('Brain-engine', 'Utiliser'))

    def test_une_page_sans_entete_a_des_valeurs_neutres(self):
        docs = {d['name']: d for d in self.client.get('/docs').json()['docs']}
        self.assertEqual(docs['sans-entete']['group'], 'Guides')
        self.assertEqual(docs['sans-entete']['label'], 'Sans entete')

    def test_le_frontmatter_ne_s_affiche_pas(self):
        contenu = self.client.get('/docs/moteur.md').json()['content']
        self.assertTrue(contenu.startswith('# Le moteur'), contenu[:80])


class TestDocsGenerer(unittest.TestCase):
    """Un brain JETABLE et minimal : deux agents, un type de session, une table.
    La doc générée doit suivre le brain — un agent ajouté la rend en retard.

    L'incident : la doc publiée le 27/09 comptait « 81 agents » pour 75, et
    `docs-inject.sh` calculait encore des variables de palier (-2, -5) depuis
    des listes supprimées."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'docs-generer.py'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        b = self.brain = Path(self._tmp.name)
        for rel, contenu in {
            'agents/debug.md': '---\nname: debug\ndescription: "Debug — bugs"\nbrain:\n  scope: project\n  type: metier\n---\n# debug\n',
            'agents/' + 'secret.md': '---\nname: secret\ndescription: "privé"\nbrain:\n  scope: personal\n  type: agent\n---\n',
            'agents/CATALOG.yml': 'agents:\n- id: debug\n  distributable: true\n- id: secret\n  distributable: false\n',
            'contexts/session-work.yml': ('# Posture : je produis\n# Trigger : "brain boot work[/<project>]"\n'
                                          'session_type: work\nttl_hours: 4\nL1:\n  - agents/debug.md\n'
                                          'context_target:\n  total_boot: "~25%"\n'),
            'brain-engine/schema-dolt.sql': 'CREATE TABLE `claims` (\n  `id` int\n);\n',
            'brain-engine/views-dolt.sql': 'CREATE OR REPLACE VIEW v_open AS SELECT 1;\n',
            'brain-compose.yml': 'version: "9.9.9"\n',
            'docs/src/agents.md': '---\nlabel: Agents\n---\n# {{NB_AGENTS}} agents, v{{VERSION}}\n\n<!-- genere:agents -->\n\n<!-- genere:sessions -->\n',
        }.items():
            (b / rel).parent.mkdir(parents=True, exist_ok=True)
            (b / rel).write_text(contenu)

    def tearDown(self):
        self._tmp.cleanup()

    def _gen(self, *args):
        return subprocess.run([sys.executable, str(self.SCRIPT), '--brain', str(self.brain), *args],
                              capture_output=True, text=True, timeout=30)

    def test_la_doc_generee_dit_ce_que_le_brain_contient(self):
        self.assertEqual(self._gen('--ecrire').returncode, 0)
        page = (self.brain / 'docs' / 'agents.md').read_text()
        self.assertIn('# 1 agents, v9.9.9', page)
        self.assertIn('`debug`', page)
        self.assertNotIn('secret', page, "un agent privé n'apparaît pas")
        self.assertIn('`brain boot work[/<project>]`', page)
        self.assertTrue(page.startswith('---\n# Généré'), "la mention reste DANS le frontmatter")
        self.assertEqual(self._gen('--check').returncode, 0)

    def test_un_agent_ajoute_rend_la_doc_en_retard(self):
        self._gen('--ecrire')
        (self.brain / 'agents' / 'testing.md').write_text(
            '---\ndescription: "Tests"\nbrain:\n  scope: project\n  type: metier\n---\n')
        with open(self.brain / 'agents' / 'CATALOG.yml', 'a') as f:
            f.write('- id: testing\n  distributable: true\n')
        r = self._gen('--check')
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('docs/agents.md en retard', r.stdout)

    def test_une_variable_de_palier_est_une_erreur_pas_un_vide(self):
        (self.brain / 'docs' / 'src' / 'agents.md').write_text('# {{AGENTS_FREE}} agents free\n')
        r = self._gen('--check')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('valeur inconnue', r.stderr)

    def test_les_routes_se_lisent_dans_le_code_pas_dans_le_texte(self):
        # Une route citée en commentaire ou en docstring n'est pas une route :
        # « parser le code, pas le texte ».
        (self.brain / 'brain-engine' / 'server.py').write_text(
            '# @app.get("/fantome")\n'
            '@app.get("/health")\ndef health():\n    """Le moteur répond."""\n\n'
            'def aide():\n    """@app.post("/docstring")"""\n')
        (self.brain / 'skills' / 'brain' / 'src').mkdir(parents=True)
        (self.brain / 'skills' / 'brain' / 'src' / 'moteur.md').write_text(
            '# {{NB_ROUTES}} routes\n\n<!-- genere:routes -->\n')
        self.assertEqual(self._gen('--ecrire').returncode, 0)
        page = (self.brain / 'skills' / 'brain' / 'moteur.md').read_text()
        self.assertIn('# 1 routes', page)
        self.assertIn('| GET | `/health` | Le moteur répond. |', page)
        self.assertNotIn('fantome', page)
        self.assertNotIn('docstring', page)

    def test_un_outil_mcp_sans_source_est_une_erreur(self):
        (self.brain / 'docs' / 'src' / 'agents.md').write_text('<!-- genere:outils -->\n')
        r = self._gen('--check')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('mcp_server.py absent', r.stderr)

    def test_un_exemple_en_code_reste_un_exemple(self):
        # La page qui explique le mécanisme disait « `74`, jamais 75 écrit à la
        # main » : son exemple `{{NB_AGENTS}}` avait été remplacé.
        (self.brain / 'docs' / 'src' / 'agents.md').write_text(
            'On écrit `{{NB_AGENTS}}`, jamais un nombre : il y a {{NB_AGENTS}} agents.\n'
            '```\n{{VERSION}}\n```\n')
        self.assertEqual(self._gen('--ecrire').returncode, 0)
        page = (self.brain / 'docs' / 'agents.md').read_text()
        self.assertIn('On écrit `{{NB_AGENTS}}`, jamais un nombre : il y a 1 agents.', page)
        self.assertIn('```\n{{VERSION}}\n```', page)

    def test_un_marqueur_mal_forme_est_une_erreur(self):
        for faux in ('Il y a {{ NB_AGENTS }} agents.', '  <!-- genere:agents -->'):
            (self.brain / 'docs' / 'src' / 'agents.md').write_text(faux + '\n')
            r = self._gen('--check')
            self.assertEqual(r.returncode, 2, faux + '\n' + r.stdout + r.stderr)
            self.assertIn('mal formé', r.stderr)

    def test_l_agent_qu_un_fork_cree_apparait(self):
        # Le catalogue ne connaît pas l'agent — son générateur n'est pas dans le
        # gabarit. S'il n'est pas `personal`, la doc le montre.
        (self.brain / 'agents' / 'mien.md').write_text(
            '---\ndescription: "Le mien"\nbrain:\n  scope: project\n  type: metier\n---\n')
        self._gen('--ecrire')
        self.assertIn('`mien`', (self.brain / 'docs' / 'agents.md').read_text())

    def test_un_en_tete_casse_est_illisible_pas_en_retard(self):
        (self.brain / 'agents' / 'casse.md').write_text('---\n- une liste\n---\n')
        (self.brain / 'agents' / 'CATALOG.yml').write_text('agents: plus une liste\n')
        r = self._gen('--check')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_une_page_sans_source_est_retiree(self):
        self._gen('--ecrire')
        (self.brain / 'docs' / 'getting-started.md').write_text('# ancien\n')
        self.assertEqual(self._gen('--check').returncode, 1)
        self._gen('--ecrire')
        self.assertFalse((self.brain / 'docs' / 'getting-started.md').exists())


class TestMcpSansJetonResteLocal(unittest.TestCase):
    """Sans jeton, le MCP ne répond qu'à la machine elle-même — même quand la
    requête forge `X-Forwarded-For: 127.0.0.1` et `Host: 127.0.0.1`.

    L'incident, mesuré le 28/09 : uvicorn (`forwarded_allow_ips='*'`) réécrivait
    l'adresse du client d'après l'en-tête, et une machine du réseau recevait 200.
    Le témoin tourne dans un espace réseau ISOLÉ (`unshare --net`), avec une
    interface factice 192.0.2.1 (plage de documentation, RFC 5737 — ni privée
    ni routable) : rien ne sort, rien de la machine n'est touché."""

    SCRIPT = r"""
ip link set lo up
ip link add d0 type dummy 2>/dev/null && ip addr add 192.0.2.1/24 dev d0 && ip link set d0 up || exit 3
cd "$1"
env -i PATH=/usr/bin:/bin HOME=/tmp BRAIN_MCP_PORT=17999 BRAIN_PORT=17998 "$2" brain-engine/mcp_server.py >/dev/null 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do sleep 1; curl -s -o /dev/null http://127.0.0.1:17999/mcp && break; done
Q='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}'
c() { curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d "$Q" "$@"; }
echo "local=$(c http://127.0.0.1:17999/mcp)"
echo "reseau=$(c --interface 192.0.2.1 http://192.0.2.1:17999/mcp)"
echo "forge=$(c --interface 192.0.2.1 -H 'X-Forwarded-For: 127.0.0.1' -H 'Host: 127.0.0.1:17999' http://192.0.2.1:17999/mcp)"
kill %1 2>/dev/null
"""

    def test_une_machine_du_reseau_ne_passe_pas_pour_la_machine(self):
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv' / 'bin' / 'python3'
        if not venv.exists() or not shutil.which('unshare') or not shutil.which('curl'):
            self.skipTest("il faut le venv, unshare et curl")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'xff.sh'
            script.write_text(self.SCRIPT)
            r = subprocess.run(['unshare', '-rpf', '--mount-proc', '--net', 'sh', str(script),
                                str(BRAIN_ROOT_PATH), str(venv)], capture_output=True, text=True, timeout=120)
        if r.returncode == 3 or 'local=' not in r.stdout:
            self.skipTest(f"pas d'espace réseau isolé ici : {r.stderr[-200:]}")
        codes = dict(l.split('=') for l in r.stdout.split() if '=' in l)
        self.assertEqual(codes.get('local'), '200', r.stdout)
        self.assertEqual(codes.get('reseau'), '401', r.stdout)
        self.assertEqual(codes.get('forge'), '401', "X-Forwarded-For + Host forgés passaient la garde\n" + r.stdout)


class TestMoteurSansJetonResteLocal(unittest.TestCase):
    """Sans jeton, l'API du moteur ne répond qu'à la machine elle-même — la
    règle du MCP, tranchée par Kevin le 28/09.

    Avant : `check_auth` rendait les trois zones à TOUT appelant, uvicorn
    écoute sur 0.0.0.0, et un fork neuf n'a pas de jeton : n'importe quelle
    machine du réseau local lisait le corpus et écrivait. Le témoin tourne dans
    un espace réseau ISOLÉ (`unshare --net`, interface factice 192.0.2.1, RFC
    5737) et ne frappe que des routes de LECTURE : sur l'ancien code, la
    requête du réseau passe — il ne faut pas qu'elle puisse écrire."""

    SCRIPT = r"""
ip link set lo up
ip link add d0 type dummy 2>/dev/null && ip addr add 192.0.2.1/24 dev d0 && ip link set d0 up || exit 3
cd "$1"
env -i PATH=/usr/bin:/bin HOME="$3" BRAIN_PORT=17998 BRAIN_DOLT_PORT=13399 "$2" brain-engine/server.py >/dev/null 2>&1 &
for i in $(seq 1 30); do sleep 1; curl -s -o /dev/null http://127.0.0.1:17998/health && break; done
c() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
echo "local=$(c http://127.0.0.1:17998/health)"
echo "reseau=$(c --interface 192.0.2.1 http://192.0.2.1:17998/health)"
echo "reseau_docs=$(c --interface 192.0.2.1 http://192.0.2.1:17998/docs)"
echo "forge=$(c --interface 192.0.2.1 -H 'X-Forwarded-For: 127.0.0.1' -H 'Host: 127.0.0.1:17998' http://192.0.2.1:17998/health)"
echo "local_xff=$(c -H 'X-Forwarded-For: 192.0.2.7' http://127.0.0.1:17998/health)"
kill %1 2>/dev/null
env -i PATH=/usr/bin:/bin HOME="$3" BRAIN_PORT=17997 BRAIN_DOLT_PORT=13399 BRAIN_TOKEN_PUBLIC=temoin "$2" brain-engine/server.py >/dev/null 2>&1 &
for i in $(seq 1 30); do sleep 1; curl -s -o /dev/null http://127.0.0.1:17997/health && break; done
echo "jeton_reseau_docs=$(c --interface 192.0.2.1 http://192.0.2.1:17997/docs)"
kill %2 2>/dev/null
"""

    def test_une_machine_du_reseau_est_refusee(self):
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv' / 'bin' / 'python3'
        if not venv.exists():
            venv = Path(os.path.expanduser('~/Dev/Brain/brain-engine/.venv/bin/python3'))
        if not venv.exists() or not shutil.which('unshare') or not shutil.which('curl'):
            self.skipTest("il faut le venv, unshare et curl")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'lan.sh'
            script.write_text(self.SCRIPT)
            r = subprocess.run(['unshare', '-rpf', '--mount-proc', '--net', 'sh', str(script),
                                str(BRAIN_ROOT_PATH), str(venv), tmp],
                               capture_output=True, text=True, timeout=120)
        if r.returncode == 3 or 'local=' not in r.stdout:
            self.skipTest(f"pas d'espace réseau isolé ici : {r.stderr[-200:]}")
        codes = dict(l.split('=') for l in r.stdout.split() if '=' in l)
        self.assertNotIn(codes.get('local'), ('000', '401', '403'), r.stdout)
        self.assertEqual(codes.get('reseau'), '403', "le réseau lisait le moteur sans jeton\n" + r.stdout)
        self.assertEqual(codes.get('reseau_docs'), '403', r.stdout)
        self.assertEqual(codes.get('forge'), '403', "X-Forwarded-For + Host forgés passaient la garde\n" + r.stdout)
        self.assertEqual(codes.get('local_xff'), '403', "un proxy local relaie un appelant distant\n" + r.stdout)
        # Avec un jeton configuré, la garde s'efface : le réseau passe, filtré par rôle.
        self.assertEqual(codes.get('jeton_reseau_docs'), '200', r.stdout)


class TestPairsSansCompteDeLOwner(unittest.TestCase):
    """Un peer déclaré sans `ssh_user` se joint avec le compte de celui qui
    lance, jamais avec celui de l'owner — écrit en dur dans `bsi-query.sh` et
    `bsi-signal.sh` jusqu'au 28/09. Brain jetable, `ssh` leurré qui
    note ses arguments, réseau isolé : aucun vrai peer n'est contacté."""

    # Construit à l'exécution : le nom écrit en toutes lettres ferait refuser
    # la synchro par son propre filet.
    OWNER = 'tetard' + 'tek'
    COMPOSE = 'machine: fixe\npeers:\n  laptop:\n    active: true\n    url: http://192.0.2.9:7700\n'

    def _brain(self, tmp: Path, script: str, compose: str | None = None) -> Path:
        # Un fork installé AILLEURS que l'owner : ~/src/mon-fork.
        b = tmp / 'src' / 'mon-fork'
        (b / 'scripts' / 'lib').mkdir(parents=True)
        shutil.copy2(BRAIN_ROOT_PATH / 'scripts' / script, b / 'scripts' / script)
        shutil.copy2(BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'pair.py', b / 'scripts' / 'lib' / 'pair.py')
        (b / 'brain-compose.local.yml').write_text(compose or self.COMPOSE)
        return b

    def _query(self, compose: str | None = None) -> tuple[str, str]:
        if not shutil.which('unshare'):
            self.skipTest("il faut unshare")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            b = self._brain(tmp, 'bsi-query.sh', compose)
            leurres = tmp / 'leurres'
            leurres.mkdir()
            (leurres / 'ssh').write_text(f'#!/bin/sh\necho "$@" >> {tmp}/ssh.log\nexit 1\n')
            (leurres / 'ssh').chmod(0o755)
            env = {'PATH': f'{leurres}:/usr/bin:/bin', 'HOME': str(tmp), 'USER': 'alice'}
            r = subprocess.run(['unshare', '-rn', 'bash', str(b / 'scripts' / 'bsi-query.sh'), 'peers'],
                               env=env, capture_output=True, text=True, timeout=60)
            appel = (tmp / 'ssh.log').read_text() if (tmp / 'ssh.log').exists() else ''
        return appel, r.stdout + r.stderr

    def test_bsi_query_peers(self):
        appel, sortie = self._query()
        self.assertIn('alice@192.0.2.9', appel, "le peer est joint avec le compte local\n" + sortie)
        self.assertNotIn(self.OWNER, appel)

    def test_bsi_query_cherche_le_brain_ou_il_est(self):
        appel, sortie = self._query()
        self.assertIn('cd ~/src/mon-fork &&', appel, sortie)
        self.assertNotIn('Dev/Brain', appel)

    def test_bsi_query_brain_root_declare(self):
        appel, sortie = self._query(self.COMPOSE + '    brain_root: ~/ailleurs/brain\n')
        self.assertIn('cd ~/ailleurs/brain &&', appel, sortie)

    def test_bsi_query_refuse_une_racine_piegee(self):
        appel, sortie = self._query(self.COMPOSE + '    brain_root: "~/x; touch /tmp/pwn"\n')
        self.assertEqual(appel, '', "le peer à la racine piégée n'est jamais appelé")
        self.assertIn('sauté', sortie)

    def test_bsi_peer_poll_cherche_le_brain_ou_il_est(self):
        if not shutil.which('unshare'):
            self.skipTest("il faut unshare")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            b = self._brain(tmp, 'bsi-peer-poll.sh')
            for f in ('bsi-query.sh', 'lib/python.sh'):
                shutil.copy2(BRAIN_ROOT_PATH / 'scripts' / f, b / 'scripts' / f)
            (b / 'workspace').mkdir()
            leurres = tmp / 'leurres'
            leurres.mkdir()
            (leurres / 'ssh').write_text(f'#!/bin/sh\necho "$@" >> {tmp}/ssh.log\nexit 1\n')
            (leurres / 'ssh').chmod(0o755)
            env = {'PATH': f'{leurres}:/usr/bin:/bin', 'HOME': str(tmp), 'USER': 'alice'}
            r = subprocess.run(['unshare', '-rn', 'bash', str(b / 'scripts' / 'bsi-peer-poll.sh')],
                               env=env, capture_output=True, text=True, timeout=60)
            appel = (tmp / 'ssh.log').read_text() if (tmp / 'ssh.log').exists() else ''
        self.assertIn('alice@192.0.2.9', appel, r.stdout + r.stderr)
        self.assertIn('cd ~/src/mon-fork &&', appel)

    def _signal(self, compose: str | None = None):
        texte = (BRAIN_ROOT_PATH / 'scripts' / 'bsi-signal.sh').read_text()
        debut = texte.index("peers() {")
        code = texte[texte.index("<<'PYEOF'\n", debut) + len("<<'PYEOF'\n"):texte.index("\nPYEOF", debut)]
        with tempfile.TemporaryDirectory() as tmp:
            b = self._brain(Path(tmp), 'bsi-signal.sh', compose)
            return subprocess.run([sys.executable, '-c', code, str(b / 'brain-compose.local.yml'), str(b)],
                                  capture_output=True, text=True, timeout=30,
                                  env={**os.environ, 'USER': 'alice', 'HOME': tmp})

    def test_bsi_signal_peers(self):
        r = self._signal()
        self.assertEqual(r.stdout.split(), ['laptop', 'alice', '192.0.2.9', '~/src/mon-fork'],
                         r.stdout + r.stderr)

    def test_bsi_signal_refuse_une_racine_piegee(self):
        r = self._signal(self.COMPOSE + '    brain_root: "~/../../etc"\n')
        self.assertEqual(r.stdout.strip(), '', r.stdout)
        self.assertIn('sauté', r.stderr)


class TestSyncSansSigpipe(unittest.TestCase):
    """Un `| head` ne tue plus un script sous `pipefail` + `-e`.

    `| head -N` fermait le tuyau pendant que la commande en amont écrivait :
    SIGPIPE, et le script mourait au milieu d'un rapport — 5 fois sur 300 dans
    sync-template.sh. Le témoin négatif est déterministe : un producteur qui
    écrit un million de lignes meurt TOUJOURS sous `head`. La fonction jugée est
    celle de `scripts/lib/premieres.sh`, lue telle quelle."""

    LIB = BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'premieres.sh'

    def _joue(self, filtre: str) -> str:
        definition = next((l for l in self.LIB.read_text().splitlines()
                           if l.startswith('premieres()')), '') if self.LIB.exists() else ''
        r = subprocess.run(['bash', '-c', f'set -euo pipefail\n{definition}\n'
                            f'seq 1 1000000 | {filtre} >/dev/null\necho vivant'],
                           capture_output=True, text=True, timeout=60)
        return r.stdout

    def test_le_temoin_negatif_meurt_sous_head(self):
        self.assertNotIn('vivant', self._joue('head -30'), "sans ce mort, le témoin ne prouve rien")

    def test_premieres_ne_tue_pas_le_script(self):
        self.assertIn('vivant', self._joue('premieres 30'))

    def test_aucun_head_sans_repli_sous_pipefail(self):
        """Tout script sous `-e` + `pipefail` : pas de `| head` dans le CODE, sauf
        repli `||` sur la ligne, ou exemption DÉCLARÉE `# sigpipe:`. Les
        commentaires ne comptent pas — le premier témoin s'était pris dans celui
        qui explique la règle."""
        fautives = []
        for f in sorted((BRAIN_ROOT_PATH / 'scripts').glob('**/*.sh')):
            texte = f.read_text(errors='replace')
            if not (re.search(r"^set -\w*e", texte, re.M) and 'pipefail' in texte):
                continue
            for n, l in enumerate(texte.splitlines(), 1):
                if l.lstrip().startswith('#') or '# sigpipe:' in l:
                    continue
                m = re.search(r"\| *head\b", l)
                if m and '||' not in l[m.end():]:
                    fautives.append(f"{f.relative_to(BRAIN_ROOT_PATH)}:{n}")
        self.assertEqual(fautives, [])

    def test_brain_status_survit_a_un_claim_incomplet(self):
        """`grep` rend 1 sur un champ absent : `status=$(claim_field …)` tuait
        brain-status sous pipefail, avant d'afficher le claim (mesuré le 28/09)."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Path(tmp) / 'b'
            (b / 'scripts' / 'lib').mkdir(parents=True)
            for d in ('claims', 'locks'):
                (b / d).mkdir()
            shutil.copy2(BRAIN_ROOT_PATH / 'scripts' / 'brain-status.sh', b / 'scripts')
            if self.LIB.exists():
                shutil.copy2(self.LIB, b / 'scripts' / 'lib')
            subprocess.run(['git', 'init', '-q', str(b)], check=True)
            (b / 'claims' / 'sess-x.yml').write_text(
                'sess_id: sess-x\nstatus: open\nscope: work/x\nopened_at: 2026-09-28T10:00:00Z\n')
            r = subprocess.run(['bash', str(b / 'scripts' / 'brain-status.sh')], cwd=b,
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout[-300:] + r.stderr[-300:])
        self.assertIn('sess-x', r.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
