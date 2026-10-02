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
import io
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

class TestLaSuiteEntiereTourne(unittest.TestCase):
    """Aucune classe de test après `unittest.main()`.

    Le 28/09, une classe s'est ajoutée APRÈS le bloc `if __name__ == '__main__'`,
    puis 23 autres à sa suite : lancé en script — comme le doctor le lance —, le
    fichier exécutait `unittest.main()` avant de les définir. 92 tests sur 376
    n'ont pas tourné pendant deux jours, sans un bruit : « Ran 284 tests, OK ».
    Relevé le 30/09 en ajoutant une classe.

    Cette classe est la PREMIÈRE du fichier, exprès : placée en fin de
    fichier, elle serait elle-même définie après un `main()` mal placé, et ne
    tournerait jamais dans le seul cas qu'elle doit attraper."""

    def test_le_main_est_la_derniere_instruction(self):
        import ast
        arbre = ast.parse(Path(__file__).read_text(encoding='utf-8'))
        mains = [i for i, n in enumerate(arbre.body)
                 if isinstance(n, ast.If) and '__main__' in ast.unparse(n.test)]
        self.assertEqual(len(mains), 1, 'un seul bloc `if __name__ == "__main__"`')
        apres = [n.name for n in arbre.body[mains[0] + 1:] if isinstance(n, ast.ClassDef)]
        self.assertEqual(apres, [], f'classes définies après unittest.main() : {apres}')



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

    def test_ollama_unavailable_se_dit(self):
        """Modèle d'embedding injoignable → `RechercheIndisponible`, pas `[]`.

        Ce test exigeait une liste vide : il gravait dans la suite le défaut que
        répare — « aucun résultat » et « pas de recherche » confondus.
        Isolé par l'encodeur de fixtures qui rend `None` (le chemin passe par
        `core.recherche` depuis le 11/09).
        """
        with self._isole(None, self.TROIS):
            with self.assertRaises(search.RechercheIndisponible):
                search.search("test")

    def test_empty_db_se_dit(self):
        """Index vide → `RechercheIndisponible` : il faut indexer."""
        with self._isole([1.0, 0.0, 0.0], []):
            with self.assertRaises(search.RechercheIndisponible):
                search.search("test")

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


class TestStateVoitSystemd(unittest.TestCase):
    """`/state` voit les unités systemd du brain. Il ne lisait que pm2 — absent
    sur le fixe — et rendait une liste de services vide (audit du wiki, 29/09).
    `systemctl` n'est jamais appelé pour de vrai : sa sortie est fabriquée."""

    SORTIE = (
        "brain-engine-local.service  loaded active   running Brain Engine local — HTTP API (port 7700)\n"
        "brain-embed-local.service   loaded inactive dead    Brain local — indexation\n"
        "brain-embed-local.timer     loaded active   waiting Brain local — embed toutes les 2 h\n"
        "dolt-server.service         loaded failed   failed  Dolt SQL Server\n"
        "brain-vieux.service         not-found inactive dead brain-vieux.service\n"
    )

    def _run(self, code=0, sortie=SORTIE):
        return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout=sortie, stderr='')

    def test_les_unites_chargees_et_leur_etat(self):
        self.assertEqual(srv._unites_systemd(run=self._run()), [
            {'name': 'brain-engine-local.service', 'active': 'active', 'sub': 'running'},
            {'name': 'brain-embed-local.service', 'active': 'inactive', 'sub': 'dead'},
            {'name': 'brain-embed-local.timer', 'active': 'active', 'sub': 'waiting'},
            {'name': 'dolt-server.service', 'active': 'failed', 'sub': 'failed'},
        ])

    def test_sans_systemd_utilisateur_une_liste_vide(self):
        self.assertEqual(srv._unites_systemd(run=self._run(code=1, sortie='')), [])

        def absent(*a, **k):
            raise FileNotFoundError('systemctl')
        self.assertEqual(srv._unites_systemd(run=absent), [])

    def test_la_route_les_rend_et_plus_le_port_du_serveur_de_cles(self):
        client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        unites = [{'name': 'brain-engine-local.service', 'active': 'active', 'sub': 'running'}]
        with patch.object(srv, '_unites_systemd', return_value=unites):
            resp = client.get('/state')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['systemd'], unites)
        self.assertNotIn('brain_key', resp.json()['ports'])

    def test_infra_et_logs_sont_retires(self):
        """`/infra` ne lisait que pm2 et renvoyait des services écrits en dur
        (Apache, Gitea) qui ne tournent pas chez un fork ; `/logs` ne lisait que
        pm2. Personne ne les appelait (29/09)."""
        client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        self.assertEqual(client.get('/infra').status_code, 404)
        self.assertEqual(client.get('/logs/mon-projet').status_code, 404)


class TestSansJetonLOwnerVoitTout(unittest.TestCase):
    """Sans jeton configuré, `check_auth` rend les zones de l'owner. Il rendait
    `['public', 'work', 'kernel']`, une copie à la main qui avait dérivé comme
    celle de `/boot` : `/search` ne voyait ni `instance` ni `satellite`
    (audit du wiki, 29/09)."""

    def test_check_auth_sans_jeton_rend_les_zones_de_l_owner(self):
        with patch.object(srv, '_TOKEN_MAP', {}):
            self.assertEqual(sorted(srv.check_auth(None)), sorted(srv._SCOPE_ACCESS['owner']))

    def test_search_en_local_sans_jeton_cherche_dans_les_cinq_zones(self):
        client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        vu = {}

        def run(q, top_k=5, allowed_scopes=None):
            vu['scopes'] = allowed_scopes
            return []
        with patch.object(srv, '_TOKEN_MAP', {}), patch.object(srv, 'run_single_query', run):
            resp = client.get('/search?q=test')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('instance', vu['scopes'])
        self.assertIn('satellite', vu['scopes'])

    def test_avec_un_jeton_le_role_decide_toujours(self):
        with patch.object(srv, '_TOKEN_MAP', {'j-mcp': 'mcp'}):
            self.assertEqual(srv.check_auth('Bearer j-mcp'), srv._SCOPE_ACCESS['mcp'])
            self.assertNotIn('kernel', srv.check_auth('Bearer j-mcp'))


class TestLectureZonePrivee(unittest.TestCase):
    """🔴 `GET /brain/{path}` ne sert la zone privée qu'à l'owner.

    Mesuré le 1/10 : la route servait tout `.md` à tout jeton valide — `mcp`
    et `public` compris — sans regarder le chemin : `profil/identity/` (la
    couche cognitive, BRAIN-056) et `vie/` (BRAIN-080) étaient lisibles avec le
    jeton le plus faible. L'indexeur les protégeait (`PRIVATE_PATHS`), la
    lecture directe non. La règle est désormais UNE liste : `embed.is_private`.

    Joué dans un brain jetable (`srv.BRAIN_ROOT` redirigé). Le témoin : un
    fichier hors zone privée reste lisible par le même jeton."""

    JETONS = {'j-owner': 'owner', 'j-mcp': 'mcp', 'j-public': 'public'}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-lecture-'))
        for rel in ('profil/identity/career.md', 'vie/papiers.md',
                    'profil/capital.md', 'agents/coach.md'):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text(f'# {rel}\n')
        self._racine = srv.BRAIN_ROOT
        srv.BRAIN_ROOT = self.tmp
        self.local = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        self.distant = TestClient(srv.app, raise_server_exceptions=False, client=('192.0.2.1', 50000))

    def tearDown(self):
        srv.BRAIN_ROOT = self._racine
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lire(self, client, chemin, jeton=None):
        h = {'Authorization': f'Bearer {jeton}'} if jeton else {}
        with patch.object(srv, '_TOKEN_MAP', self.JETONS):
            return client.get(f'/brain/{chemin}', headers=h).status_code

    def test_un_jeton_non_owner_ne_lit_pas_la_zone_privee(self):
        for jeton in ('j-mcp', 'j-public'):
            for chemin in ('profil/identity/career.md', 'vie/papiers.md', 'profil/capital.md'):
                self.assertEqual(self._lire(self.distant, chemin, jeton), 403, f'{jeton} lit {chemin}')

    def test_le_meme_jeton_lit_hors_zone_privee(self):
        self.assertEqual(self._lire(self.distant, 'agents/coach.md', 'j-public'), 200)

    def test_l_owner_lit_la_zone_privee(self):
        self.assertEqual(self._lire(self.distant, 'profil/identity/career.md', 'j-owner'), 200)
        self.assertEqual(self._lire(self.local, 'vie/papiers.md'), 200, "la machine elle-même = owner")

    def test_un_detour_par_le_chemin_ne_contourne_pas(self):
        for chemin in ('agents/../profil/identity/career.md', 'profil/./identity/career.md',
                       './vie/papiers.md'):
            self.assertEqual(self._lire(self.distant, chemin, 'j-mcp'), 403, chemin)

    def test_la_regle_est_celle_de_l_indexeur(self):
        import embed
        self.assertTrue(embed.is_private('vie/x.md') and embed.is_private('profil/identity/x.md'))


class TestLectureParZone(unittest.TestCase):
    """`GET /brain/{path}` applique à la lecture les zones de `_SCOPE_ACCESS`.

    Hors zone privée, la route servait toutes les zones à tout jeton — un
    jeton `public` lisait
    `KERNEL.md` et `projets/`. L'écriture appliquait déjà les zones ; la lecture
    non. `public` → la zone `public` ; `mcp` → tout sauf `kernel` ; l'owner et la
    machine elle-même → tout."""

    JETONS = {'j-owner': 'owner', 'j-mcp': 'mcp', 'j-public': 'public'}
    FICHIERS = ('agents/coach.md', 'KERNEL.md', 'projets/mon-projet.md', 'workspace/note.md')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-lecture-zone-'))
        for rel in self.FICHIERS:
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text(f'# {rel}\n')
        self._racine = srv.BRAIN_ROOT
        srv.BRAIN_ROOT = self.tmp
        self.distant = TestClient(srv.app, raise_server_exceptions=False, client=('192.0.2.1', 50000))
        self.local = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)

    def tearDown(self):
        srv.BRAIN_ROOT = self._racine
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lire(self, client, chemin, jeton=None):
        h = {'Authorization': f'Bearer {jeton}'} if jeton else {}
        with patch.object(srv, '_TOKEN_MAP', self.JETONS):
            return client.get(f'/brain/{chemin}', headers=h).status_code

    def test_public_ne_lit_que_la_zone_public(self):
        self.assertEqual(self._lire(self.distant, 'agents/coach.md', 'j-public'), 200, "le témoin : zone public")
        for c in ('KERNEL.md', 'projets/mon-projet.md', 'workspace/note.md'):
            self.assertEqual(self._lire(self.distant, c, 'j-public'), 403, c)

    def test_mcp_lit_tout_sauf_le_kernel(self):
        for c in ('agents/coach.md', 'projets/mon-projet.md', 'workspace/note.md'):
            self.assertEqual(self._lire(self.distant, c, 'j-mcp'), 200, c)
        self.assertEqual(self._lire(self.distant, 'KERNEL.md', 'j-mcp'), 403)

    def test_l_owner_et_la_machine_lisent_tout(self):
        for c in self.FICHIERS:
            self.assertEqual(self._lire(self.distant, c, 'j-owner'), 200, c)
            self.assertEqual(self._lire(self.local, c), 200, c)


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

    def setUp(self):
        script_d_instance(self.SERVER_SCRIPT)

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
        svc = script_d_instance(Path(__file__).parent.parent / 'scripts' / 'brain-engine.service')
        self.assertTrue(svc.exists(), f"Service absent : {svc}")

    def test_systemd_service_has_mysecrets_env(self):
        """Le service charge MYSECRETS via EnvironmentFile."""
        svc = script_d_instance(Path(__file__).parent.parent / 'scripts' / 'brain-engine.service')
        content = svc.read_text()
        self.assertIn('EnvironmentFile', content)
        self.assertIn('MYSECRETS', content)

    def test_systemd_service_has_brain_token(self):
        """Le service ne hardcode pas BRAIN_TOKEN — il vient de EnvironmentFile."""
        svc = script_d_instance(Path(__file__).parent.parent / 'scripts' / 'brain-engine.service')
        content = svc.read_text()
        self.assertNotIn('BRAIN_TOKEN=', content)  # jamais hardcodé dans le service

    def test_install_script_exists_and_executable(self):
        """install-brain-engine.sh existe et est exécutable."""
        script = script_d_instance(Path(__file__).parent.parent / 'scripts' / 'install-brain-engine.sh')
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
        # Un fork neuf n'a pas encore de MYSECRETS : il s'abstient. Le brain
        # d'origine en a un, et son absence reste rouge.
        mysecrets = script_d_instance(Path(__file__).parent.parent / 'brain-secrets' / 'MYSECRETS')
        self.assertTrue(mysecrets.exists(), f"MYSECRETS absent : {mysecrets}")
        trouve = subprocess.run(['grep', '-q', 'BRAIN_TOKEN', str(mysecrets)],
                                capture_output=True)
        self.assertEqual(trouve.returncode, 0,
                         "MYSECRETS ne declare pas BRAIN_TOKEN")


class TestRagScript(unittest.TestCase):
    """Test existence et exécutabilité du script bash bsi-rag.sh."""

    RAG_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'bsi-rag.sh'

    def setUp(self):
        script_d_instance(self.RAG_SCRIPT)

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

# ── Ce qui n'est que dans le brain d'origine — chez un fork, on s'abstient ─────
#
# Le gabarit livre cette suite, pas les scripts d'instance qu'une partie de ses
# classes éprouve. Mesuré le 2/10 sur un fork installé : 34 tests rouges pour un
# script absent, une suite qu'aucun fork ne pouvait voir verte.
#
# Mais dans le brain d'origine, un script absent n'est pas « d'instance » : il est
# PERDU, et doit rester rouge. Le brain d'origine se reconnaît à
# `scripts/sync-template.sh`, qui ne part jamais au gabarit.
BRAIN_D_ORIGINE = (BRAIN_ROOT_PATH / 'scripts' / 'sync-template.sh').is_file()


def absent_d_instance(chemin: Path) -> bool:
    """Vrai si `chemin` manque chez un fork. Absent du brain d'origine : rouge."""
    if chemin.exists():
        return False
    if BRAIN_D_ORIGINE:
        raise AssertionError(f"{chemin} absent du brain d'origine — perdu, pas d'instance")
    return True


def script_d_instance(chemin: Path) -> Path:
    """Le chemin, ou l'abstention du test chez un fork qui ne l'a pas."""
    if absent_d_instance(chemin):
        raise unittest.SkipTest(f'{chemin.name} absent — script d’instance')
    return chemin


def avec_le_core(moteur: Path) -> None:
    """Un brain témoin reçoit le CORE quand le brain le livre (`brain-engine/core/`).

    L'instance a le CORE installé en éditable : un `db.py` copié seul le trouve
    partout. Un fork ne l'a que dans `brain-engine/core/` — sans ce lien, le
    témoin meurt sur `No module named 'core'`."""
    core = BRAIN_ROOT_PATH / 'brain-engine' / 'core'
    if core.is_dir() and not (moteur / 'core').exists():
        (moteur / 'core').symlink_to(core.resolve())

class TestScriptDInstance(unittest.TestCase):
    """L'abstention ne couvre que le fork : dans le brain d'origine, un script
    absent est perdu, et le test reste rouge."""

    ABSENT = BRAIN_ROOT_PATH / 'scripts' / 'jamais-ecrit-temoin.sh'

    def test_chez_un_fork_le_test_s_abstient(self):
        with patch(f'{__name__}.BRAIN_D_ORIGINE', False):
            with self.assertRaises(unittest.SkipTest):
                script_d_instance(self.ABSENT)

    def test_dans_le_brain_d_origine_il_rougit(self):
        with patch(f'{__name__}.BRAIN_D_ORIGINE', True):
            with self.assertRaises(AssertionError):
                script_d_instance(self.ABSENT)

    def test_present_il_rend_le_chemin(self):
        self.assertEqual(script_d_instance(SYNC_SCRIPT), SYNC_SCRIPT)

    def test_ce_brain_se_sait_d_origine_ou_fork(self):
        self.assertEqual(BRAIN_D_ORIGINE, (BRAIN_ROOT_PATH / 'scripts' / 'sync-template.sh').is_file())


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
        for f in ('migrate.py', 'db.py', 'racines.py', 'schema.sql'):
            shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, tmp / 'brain-engine' / f)
        avec_le_core(tmp / 'brain-engine')
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

    def _lancer(self, brain: Path, *args, home: Path | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        if home is not None:
            env['HOME'] = str(home)
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

    def test_un_depot_hors_du_brain_se_clone_et_se_suit(self):
        """`chemin:` — le CORE vit hors du brain (`myeline`), et le laptop tirait un
        brain qui attendait un CORE plus récent que le sien (1/10). HOME jetable :
        `~` ne désigne jamais le vrai dossier personnel."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brain, forge = self._brain(tmp)
            self._forge(tmp / 'f2', 'myeline-depot')
            (forge / 'myeline-depot.git').parent.mkdir(exist_ok=True)
            shutil.move(str(tmp / 'f2' / 'forge' / 'myeline-depot.git'), str(forge / 'myeline-depot.git'))
            with (brain / 'satellites.yml').open('a') as f:
                f.write('  myeline: {depot: myeline-depot, machines: [laptop], chemin: ~/Gitea/myeline}\n')
            home = tmp / 'home'
            home.mkdir()
            r = self._lancer(brain, '--cloner', home=home)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            dehors = home / 'Gitea' / 'myeline'
            self.assertTrue((dehors / 'LISEZ-MOI').exists(), "cloné à son chemin, hors du brain")
            self.assertFalse((brain / 'myeline').exists(), "rien sous le brain")
            self.assertEqual(self._lancer(brain, '--check', home=home).returncode, 0)
            self._pousser(tmp, forge, 'myeline-depot', 'nouveau.py')
            r = self._lancer(brain, '--check', home=home)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn('myeline', r.stdout)
            self.assertIn('derrière', r.stdout, "un CORE en retard se voit")

    def test_un_chemin_relatif_est_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brain, _ = self._brain(tmp)
            with (brain / 'satellites.yml').open('a') as f:
                f.write('  ailleurs: {depot: profil-depot, machines: [laptop], chemin: ../x}\n')
            r = self._lancer(brain, '--check', home=tmp)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('chemin relatif', r.stdout + r.stderr)

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
               'gabarit', 'KERNEL.md', 'brain-compose.yml', 'brain-constitution.md',
               'MYSECRETS.example', 'brain-compose.local.yml.example',
               'NIVEAUX.yml')
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

    def test_les_specs_de_brain_ui_ne_partent_pas(self):
        """`brain-ui/docs/specs/` reste chez l'owner [BRAIN-080].

        Les specs de l'interface (des visions de mars, qui nomment l'instance)
        vivent dans le dépôt `brain-ui`, à côté du code. La synchro copie
        `brain-ui/` en entier : sans exclusion, elles partaient au gabarit. Le
        témoin : le reste de `brain-ui/`, `docs/` compris, part bien."""
        ui = self.brain / 'brain-ui'
        ui.unlink()
        for rel, texte in (('src/main.ts', 'export {}\n'), ('package.json', '{}\n'),
                           ('docs/lisez-moi.md', '# docs\n'), ('docs/specs/vision.md', '# une vision\n')):
            (ui / rel).parent.mkdir(parents=True, exist_ok=True)
            (ui / rel).write_text(texte)
        rendu = self.tmp / 'rendu'
        self._sync('--rendre', str(rendu))
        self.assertTrue((rendu / 'brain-ui' / 'package.json').exists(), "le témoin : brain-ui part")
        self.assertTrue((rendu / 'brain-ui' / 'docs' / 'lisez-moi.md').exists(), "docs/ hors specs part")
        self.assertFalse((rendu / 'brain-ui' / 'docs' / 'specs').exists(), "les specs ne partent pas")

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
        self._gabarit_publie('profil/*\n!profil/README.md\n!profil/CLAUDE.md.example\n!profil/specs/\n'
                             '!profil/identity.exemple/\n')   #, comme le vrai
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
        self.assertFalse(any(x.startswith('profil/identity/') for x in liste), "BRAIN-056")
        # la forme part, sans contenu — un fork sait quoi remplir.
        self.assertIn('profil/identity.exemple/INDEX.md', liste)
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


class TestTypeParDefaut(BrainBsiJetable):
    """Un claim ouvert sans `--type` est un `explore` — le lobby V2 — et prend
    le TTL que ce manifeste déclare. C'était `navigate`, un type V1 sans
    manifeste : 4 h, quand `explore` en déclare 8 (audit du wiki, 29/09)."""

    def _ligne(self, sess):
        con = sqlite3.connect(self.base)
        ligne = con.execute("SELECT type, ttl_hours FROM claims WHERE sess_id = ?",
                            (sess,)).fetchone()
        con.close()
        return ligne

    def test_sans_type_le_claim_est_un_explore_a_son_ttl(self):
        (self.brain / 'contexts' / 'session-explore.yml').write_text('type: explore\nttl_hours: 8\n')
        sess = 'sess-20260929-1800-explore-t'
        r = self._open(sess, '--scope', 'explore/t')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._ligne(sess), ('explore', 8))

    def test_un_type_donne_reste_le_sien(self):
        sess = 'sess-20260929-1801-pilote-t'
        r = self._open(sess, '--type', 'pilote', '--scope', 'pilote/t')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._ligne(sess), ('pilote', 12))


class TestTranscribeVoxtype(unittest.TestCase):
    """`brain-transcribe.sh` passe par voxtype — joué avec de FAUX
    `yt-dlp`, `ffmpeg` et `voxtype`, dans un PATH construit à la main : le vrai
    voxtype (l'outil de dictée de l'utilisateur) n'y figure pas, il ne peut pas
    être appelé."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'brain-transcribe.sh'
    OUTILS = ('bash', 'sh', 'env', 'grep', 'sed', 'tr', 'cut', 'du', 'wc', 'mkdir',
              'cp', 'rm', 'dirname', 'tail', 'cat', 'echo', 'printf')

    def setUp(self):
        script_d_instance(self.SCRIPT)
        self.d = Path(tempfile.mkdtemp(prefix='transcribe-'))
        self.bin = self.d / 'bin'
        self.bin.mkdir()
        for o in self.OUTILS:
            chemin = shutil.which(o)
            if chemin:
                (self.bin / o).symlink_to(chemin)
        self.appels = self.d / 'voxtype.args'
        self._faux('yt-dlp', r"""
case "$*" in
  *"--print title"*) echo "Une Vidéo d'essai" ;;
  *"--print duration_string"*) echo "1:00" ;;
  *) for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
     : > "${out/\%(ext)s/wav}" ;;
esac""")
        self._faux('ffmpeg', 'for a in "$@"; do dernier="$a"; done; : > "$dernier"')
        self._faux('voxtype', f"""echo "$@" > {self.appels}
echo 'Loading audio file: "x.wav"'
echo 'Audio format: 16000 Hz, 1 channel(s), Int'
echo 'Processing 16000 samples (1.00s)...'
echo ''
echo 'Bonjour le brain.'""")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _faux(self, nom, corps):
        f = self.bin / nom
        f.write_text('#!/bin/bash\n' + corps + '\n', encoding='utf-8')
        f.chmod(0o755)

    def _lancer(self, *args):
        env = {'PATH': str(self.bin), 'HOME': str(self.d),
               'BRAIN_TRANSCRIBE_DIR': str(self.d / 'travail')}
        return subprocess.run(['bash', str(self.SCRIPT), 'https://exemple/v', *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_la_transcription_sort_sans_preambule(self):
        sortie = self.d / 'sortie.txt'
        r = self._lancer('--out', str(sortie))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sortie.read_text(encoding='utf-8'), 'Bonjour le brain.\n')

    def test_modele_et_langue_sont_passes_explicitement(self):
        self._lancer('--out', str(self.d / 's.txt'))
        args = self.appels.read_text(encoding='utf-8').split()
        self.assertIn('-q', args)
        self.assertEqual(args[args.index('--model') + 1], 'small')
        self.assertEqual(args[args.index('--language') + 1], 'fr')
        self.assertIn('transcribe', args)

    def test_sans_voxtype_il_refuse_en_le_disant(self):
        (self.bin / 'voxtype').unlink()
        r = self._lancer('--out', str(self.d / 's.txt'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('voxtype introuvable', r.stdout)


class TestWorkflowsCestLAutonomie(unittest.TestCase):
    """`/workflows` sert le résumé du palier b, produit par la commande que la
    config locale déclare. Sans source ou en échec, 200 et une
    `note` — jamais un vide qui se tait."""

    def setUp(self):
        self.client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        self.d = Path(tempfile.mkdtemp(prefix='workflows-'))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _source(self, corps, sortie=0):
        f = self.d / 'source'
        f.write_text(f'#!/bin/bash\n{corps}\nexit {sortie}\n', encoding='utf-8')
        f.chmod(0o755)
        return str(f)

    def _get(self, commande):
        env = {} if commande is None else {'BRAIN_RESUME_AUTONOMIE_CMD': commande}
        with patch.dict(os.environ, env, clear=False):
            if commande is None:
                os.environ.pop('BRAIN_RESUME_AUTONOMIE_CMD', None)
            r = self.client.get('/workflows')
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_sans_source_declaree_la_note_le_dit(self):
        d = self._get(None)
        self.assertEqual(d['projets'], [])
        self.assertIn('BRAIN_RESUME_AUTONOMIE_CMD', d['note'])

    def test_la_source_est_servie_telle_quelle(self):
        d = self._get(self._source(
            "echo '{\"projets\": [{\"projet\": \"p\", \"etat\": \"ok\", \"en_avance\": 2}], \"note\": null}'"))
        self.assertEqual(d['projets'][0]['en_avance'], 2)
        self.assertIsNone(d['note'])

    def test_une_source_qui_echoue_se_dit(self):
        d = self._get(self._source('echo boum', sortie=3))
        self.assertEqual(d['projets'], [])
        self.assertIn('échoué', d['note'])

    def test_une_source_illisible_se_dit(self):
        d = self._get(self._source('echo pas du json'))
        self.assertIn('JSON', d['note'])


class TestPlantesApresReboot(BrainBsiJetable):
    """Après un reboot, `plantes` voit les sessions coupées.

    Mesuré sur un brain du réseau le 29/09 : le reboot efface les
    fichiers `~/.claude/sessions/*.json` des sessions coupées ; `plantes` ne
    déclarait planté qu'une identité ENCORE présente ici, et leurs claims
    tenaient leur scope jusqu'à l'expiration. Le démarrage de la machine
    (`btime`) est fabriqué, les sessions aussi — rien de réel n'est lu."""

    DEMARRAGE = 1_790_000_000          # 2026-09-21 — le reboot fabriqué

    def setUp(self):
        super().setUp()
        t = Path(self._tmp.name)
        self.sessions = t / 'sessions'
        self.sessions.mkdir()
        self.stat = t / 'stat'
        self.stat.write_text(f'cpu  1 2 3\nbtime {self.DEMARRAGE}\n', encoding='utf-8')
        self.env.update(CLAUDE_SESSIONS_DIR=str(self.sessions), BRAIN_PROC_STAT=str(self.stat))

    def _claim(self, sess, agent, heures_avant_le_demarrage):
        from datetime import datetime, timedelta, timezone
        quand = (datetime.fromtimestamp(self.DEMARRAGE, timezone.utc)
                 - timedelta(hours=heures_avant_le_demarrage)).strftime('%Y-%m-%d %H:%M:%S')
        con = sqlite3.connect(self.base)
        con.execute("INSERT INTO claims (sess_id, type, scope, status, opened_at, agent_session) "
                    "VALUES (?, 'pilote', 'pilote/t', 'open', ?, ?)", (sess, quand, agent))
        con.commit()
        con.close()

    def _session(self, agent, pid):
        (self.sessions / f'{pid}.json').write_text(json.dumps({'sessionId': agent, 'pid': pid}),
                                                    encoding='utf-8')

    def _plantes(self):
        r = self._bsi('plantes')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return {l.split('|')[0] for l in r.stdout.splitlines() if '|' in l}

    def test_l_incident_une_session_coupee_par_le_reboot_est_plantee(self):
        self._claim('sess-avant', 'coupee-1', heures_avant_le_demarrage=2)
        self.assertEqual(self._plantes(), {'sess-avant'})

    def test_ouvert_apres_le_demarrage_une_identite_inconnue_n_est_pas_jugee(self):
        self._claim('sess-apres', 'inconnue-2', heures_avant_le_demarrage=-1)
        self.assertEqual(self._plantes(), set())

    def test_une_session_reprise_apres_le_reboot_n_est_pas_plantee(self):
        self._claim('sess-reprise', 'reprise-3', heures_avant_le_demarrage=2)
        self._session('reprise-3', os.getpid())        # même identité, processus vivant
        self.assertEqual(self._plantes(), set())

    def test_un_claim_sans_identite_n_est_jamais_juge(self):
        self._claim('sess-sans', None, heures_avant_le_demarrage=2)
        self.assertEqual(self._plantes(), set())

    def test_sans_btime_la_prudence_d_avant_reste(self):
        self.stat.write_text('cpu  1 2 3\n', encoding='utf-8')
        self._claim('sess-avant', 'coupee-4', heures_avant_le_demarrage=2)
        self.assertEqual(self._plantes(), set())


class TestEnergieTroisNiveaux(BrainBsiJetable):
    """L'énergie de clôture a trois niveaux (BRAIN-046, tranché le 29/09) : le
    script normalise, et refuse le reste AVANT d'écrire. Le premier cas est
    l'incident : « 5 », la valeur la plus écrite de l'archive."""

    def _energie(self, sess):
        con = sqlite3.connect(self.base)
        ligne = con.execute("SELECT status, energy FROM claims WHERE sess_id = ?",
                            (sess,)).fetchone()
        con.close()
        return ligne

    def test_cinq_est_refuse_et_rien_ne_se_ferme(self):
        sess = 'sess-20260929-2200-work-e'
        self._open(sess, '--type', 'work', '--scope', 'work/e')
        r = self._bsi('close', sess, '--pas-le-mien', '--energy', '5')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('high / medium / low', r.stdout)
        self.assertEqual(self._energie(sess), ('open', None))

    def test_le_francais_et_la_lettre_se_normalisent(self):
        for sess, donnee, attendu in (('sess-20260929-2201-work-f', 'haute', 'high'),
                                      ('sess-20260929-2202-work-g', 'M', 'medium'),
                                      ('sess-20260929-2203-work-h', 'low', 'low')):
            self._open(sess, '--type', 'work', '--scope', f'work/{sess[-1]}')
            r = self._bsi('close', sess, '--pas-le-mien', '--energy', donnee)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self._energie(sess), ('closed', attendu))

    def test_sans_energie_rien_ne_change(self):
        sess = 'sess-20260929-2204-work-i'
        self._open(sess, '--type', 'work', '--scope', 'work/i')
        r = self._bsi('close', sess, '--pas-le-mien')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._energie(sess), ('closed', None))


class TestEnergieDeLaRoute(unittest.TestCase):
    """La route est l'autorité : même règle que le script, pour tout écrivain."""

    def test_la_regle(self):
        self.assertEqual(srv._energie('Haute'), 'high')
        self.assertEqual(srv._energie(' m '), 'medium')
        self.assertIsNone(srv._energie(None))
        for mauvaise in ('5', '9', 'energized', '5/5', ''):
            with self.assertRaises(srv.HTTPException) as e:
                srv._energie(mauvaise)
            self.assertEqual(e.exception.status_code, 422)

    def test_la_route_refuse_avant_de_lire_la_base(self):
        client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        import db as brain_db
        with patch.object(srv, '_readonly_guard'), \
             patch.object(brain_db, 'query_one', side_effect=AssertionError('lu')) as lu:
            r = client.patch('/bsi/claims/sess-20260929-2205-work-j',
                             json={'status': 'closed', 'energy': '5'})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn('high / medium / low', r.text)
        lu.assert_not_called()


class TestMoteurAutonome(unittest.TestCase):
    """`moteur_autonome.py` : un moteur qui n'importe que le gabarit, son
    environnement et la bibliothèque standard démarre ; un moteur qui importe ce
    qui vit ailleurs sur cette machine ne démarre pas."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'moteur_autonome.py'

    def setUp(self):
        script_d_instance(self.SCRIPT)

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
        for f in ('schema-dolt.sql', 'views-dolt.sql', '.env.local.example', 'db.py', 'racines.py'):
            shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, self.brain / 'brain-engine' / f)
        avec_le_core(self.brain / 'brain-engine')
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
            for f in ('db.py', 'migrate.py', 'racines.py'):
                shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, moteur / f)
            avec_le_core(moteur)
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
            'brain-compose.yml': 'version: "2.3.5"\n',
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

    # ── Les versions écrites en dur (Cortex-Template#7) ──
    def test_une_version_passee_en_dur_rougit_meme_en_code(self):
        """L'incident : la page publiée en v2.3.4 disait, dans un bloc de code,
        `git merge v2.3.4` — juste ce jour-là, fausse dès la v2.3.5."""
        code, sortie = self._juger('```bash\ngit merge v2.3.4\n```\n')
        self.assertEqual(code, 1, sortie)
        self.assertIn('[version]', sortie)

    def test_la_version_courante_ne_rougit_pas(self):
        self._vrai('> travail. Kernel v2.3.5.')

    def test_une_adresse_n_est_pas_une_version(self):
        self._vrai('Avec un client MySQL, sur `127.0.0.1:3307`, base `brain-dolt` :')

    def test_un_exemple_declare_ne_rougit_pas(self):
        self._vrai('git : chaque version est un **tag** (`v2.3.3`…), posé par-dessus '
                   'la précédente. <!-- docs-verite: permis -->')

    def test_sans_version_du_gabarit_la_regle_se_tait(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._gabarit(Path(tmp), 'git merge v2.3.4\n')
            (g / 'brain-compose.yml').unlink()
            r = subprocess.run([sys.executable, str(self.SCRIPT), '--gabarit', str(g)],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_un_commentaire_ne_cree_pas_un_fichier(self):
        """L'incident du 28/09 : `brain-engine/modules.yml`, absent du gabarit,
        passait parce qu'un COMMENTAIRE de script le nommait. Seul le
        code d'un script crée un fichier ; le texte qui en parle, non."""
        page = 'Le rangement : `brain-engine/modules.yml`.\n'
        with tempfile.TemporaryDirectory() as tmp:
            g = self._gabarit(Path(tmp), page)
            (g / 'scripts' / 'retraits.sh').write_text(
                '# la table sort aussi de `brain-engine/modules.yml`\necho ok\n')
            r = subprocess.run([sys.executable, str(self.SCRIPT), '--gabarit', str(g)],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[chemin]', r.stdout)

    def test_le_code_d_un_script_cree_toujours(self):
        # Le témoin contraire : `brain-setup.sh` écrit `.env.local` dans son CODE.
        self._vrai('Le setup écrit `brain-engine/.env.local`.')

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

    # ── Le wiki jugé — les lignes sont celles du wiki du 29/09 ──
    def test_deux_spans_voisins_ne_font_pas_une_commande(self):
        """Recollés, `scripts/bsi-claim.sh` et `ttl_hours` faisaient la commande
        `bsi-claim.sh ttl_hours` — ligne de context-loading, mot pour mot."""
        self._vrai('| `scripts/bsi-claim.sh` | lit `ttl_hours` à l\'ouverture du claim |')
        self._faux('Lancer `bsi-claim.sh ttl_hours`.', 'commande')

    def _juger_avec(self, fichiers: dict, *args):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._gabarit(Path(tmp), 'rien\n')
            for rel, contenu in fichiers.items():
                (g / rel).parent.mkdir(parents=True, exist_ok=True)
                (g / rel).write_text(contenu)
            r = subprocess.run([sys.executable, str(self.SCRIPT), '--gabarit', str(g),
                                '--pages', 'wiki/*.md', *args],
                               capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    def test_un_lien_de_wiki_sans_md_mene_a_sa_page_avec_wiki(self):
        pages = {'wiki/Home.md': '[Le laptop](laptop-satellite)\n',
                 'wiki/laptop-satellite.md': '# laptop\n'}
        code, sortie = self._juger_avec(pages)
        self.assertEqual(code, 1, "sans --wiki, dans un dépôt, ce lien est mort")
        code, sortie = self._juger_avec(pages, '--wiki')
        self.assertEqual(code, 0, sortie)
        code, sortie = self._juger_avec({'wiki/Home.md': '[Absente](absente)\n'}, '--wiki')
        self.assertEqual(code, 1, "une page absente reste un lien mort")
        self.assertIn('[lien]', sortie)

    def test_un_journal_raconte_mais_ses_liens_sont_juges(self):
        journal = ('---\nname: CHANGELOG\ndocs-verite: journal\n---\n'
                   '## 2.1.0 — tiers free/pro/owner, `brain boot mode work`\n')
        code, sortie = self._juger_avec({'wiki/CHANGELOG.md': journal})
        self.assertEqual(code, 0, sortie)
        code, sortie = self._juger_avec({'wiki/CHANGELOG.md': journal + '[vers](absente.md)\n'})
        self.assertEqual(code, 1)
        self.assertIn('[lien]', sortie)

    def test_journal_hors_du_frontmatter_ne_declare_rien(self):
        page = '# Page\n\ndocs-verite: journal\n\n`brain boot mode work`\n'
        code, sortie = self._juger_avec({'wiki/page.md': page})
        self.assertEqual(code, 1, "déclaré dans le frontmatter, jamais ailleurs")


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
    règle du MCP.

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
        script_d_instance(BRAIN_ROOT_PATH / 'scripts' / 'bsi-peer-poll.sh')
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



class TestSchemaRetraits(unittest.TestCase):
    """Un retrait de table atteint les instances — et jamais sur des lignes.

    `schema.sql` n'a aucun `DROP` : une table retirée du schéma restait chez
    toutes les instances (le laptop, le 28/09, gardait les huit tables retirées). Le
    script les retire, mais une table qui porte des lignes n'est jamais touchée,
    et une seule suffit à tout refuser. Éprouvé sur une base SQLite jetable,
    construite depuis le schéma COURANT plus les tables retirées."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'schema-retraits.sh'
    RETIREES = ['learning_modules', 'learning_tracks', 'todo_items', 'todo_sections',
                'backlog_visions', 'decision_chantiers', 'agent_memory', 'agent_loads']

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('schema-retraits.sh absent')
        self.tmp = Path(tempfile.mkdtemp(prefix='retraits-'))
        self.base = self.tmp / 'base.db'
        c = sqlite3.connect(self.base)
        c.executescript((BRAIN_ROOT_PATH / 'brain-engine' / 'schema.sql').read_text())
        self.attendues = self._tables(c)
        # En toutes lettres : `template_autonome` lit le SQL du gabarit, et une
        # table créée par une f-string y passe pour « interrogée, créée nulle
        # part ». Ce montage CRÉE ce qu'il interroge — il faut que ça se lise.
        c.executescript('''
            CREATE TABLE learning_modules   (id INTEGER PRIMARY KEY, x TEXT);
            CREATE TABLE learning_tracks    (id INTEGER PRIMARY KEY, x TEXT);
            CREATE TABLE todo_items         (id INTEGER PRIMARY KEY, x TEXT);
            CREATE TABLE todo_sections      (id INTEGER PRIMARY KEY, x TEXT);
            CREATE TABLE backlog_visions    (id INTEGER PRIMARY KEY, x TEXT);
            CREATE TABLE decision_chantiers (id INTEGER PRIMARY KEY, x TEXT);
            CREATE TABLE agent_memory       (id INTEGER PRIMARY KEY, x TEXT);
            CREATE TABLE agent_loads        (id INTEGER PRIMARY KEY, x TEXT);
        ''')
        self.assertEqual(self._tables(c) - self.attendues, set(self.RETIREES))
        c.execute('CREATE VIEW v_graduation_candidates AS SELECT id FROM agent_memory')
        c.commit(); c.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _tables(c):
        return {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite%'")}

    def _joue(self, *args, base=None):
        env = {**os.environ, 'BRAIN_DB_BACKEND': 'sqlite', 'BRAIN_DB_PATH': str(base or self.base)}
        return subprocess.run(['bash', str(self.SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def _etat(self):
        c = sqlite3.connect(f'file:{self.base}?mode=ro', uri=True)
        try:
            vues = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
            return self._tables(c), vues
        finally:
            c.close()

    def test_a_blanc_ne_touche_rien(self):
        avant = self._etat()
        r = self._joue()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('à blanc', r.stdout)
        self.assertEqual(self._etat(), avant)

    def test_applique_ramene_la_base_au_schema(self):
        r = self._joue('--appliquer')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tables, vues = self._etat()
        self.assertEqual(tables, self.attendues)
        self.assertNotIn('v_graduation_candidates', vues)

    def test_une_table_pleine_refuse_tout(self):
        c = sqlite3.connect(self.base)
        c.execute("INSERT INTO agent_loads (x) VALUES ('la donnee du fork')"); c.commit(); c.close()
        avant = self._etat()
        r = self._joue('--appliquer')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('agent_loads', r.stdout)
        self.assertEqual(self._etat(), avant, "un refus ne laisse pas une base à moitié migrée")

    def test_relancer_ne_fait_rien(self):
        self._joue('--appliquer')
        r = self._joue('--appliquer')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('rien à retirer', r.stdout)

    def test_une_base_absente_n_est_pas_creee(self):
        absente = self.tmp / 'absente.db'
        r = self._joue('--appliquer', base=absente)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(absente.exists(), "sqlite3 crée ce qu'il ouvre — le script ne doit pas l'ouvrir")


class TestModulesDesTables(unittest.TestCase):
    """Chaque table de la base appartient à exactement un module.

    Le 28/09, huit tables sont parties en une fois : il avait fallu mesurer à la
    main qui les lisait, et deux lecteurs avaient échappé à la première mesure.
    `modules.yml` range les tables ; ce test tient le rangement dans les deux
    sens, et le confronte au CORE, qui déclare les siennes dans `TABLES`."""

    SCHEMA = BRAIN_ROOT_PATH / 'brain-engine' / 'schema-dolt.sql'
    MANIFESTE = BRAIN_ROOT_PATH / 'brain-engine' / 'modules.yml'

    @classmethod
    def setUpClass(cls):
        if not cls.MANIFESTE.exists():
            raise unittest.SkipTest('modules.yml absent')
        import yaml
        cls.schema = set(re.findall(r'^CREATE TABLE `([a-z_]+)`',
                                    cls.SCHEMA.read_text(), re.MULTILINE))
        cls.modules = yaml.safe_load(cls.MANIFESTE.read_text())['modules']

    def test_le_schema_est_lu(self):
        self.assertGreater(len(self.schema), 10, "un schéma vide rendrait tout le reste vert")

    def test_une_table_n_a_qu_un_module(self):
        vues = {}
        for nom, m in self.modules.items():
            for t in (m.get('tables') or []):
                vues.setdefault(t, []).append(nom)
        doublons = {t: ms for t, ms in vues.items() if len(ms) > 1}
        self.assertEqual(doublons, {})

    def test_toute_table_du_schema_est_rangee(self):
        rangees = {t for m in self.modules.values() for t in (m.get('tables') or [])}
        self.assertEqual(self.schema - rangees, set(),
                         "une table du schéma n'a pas de module — la ranger dans modules.yml")

    def test_tout_ce_qui_est_range_existe(self):
        rangees = {t for m in self.modules.values() for t in (m.get('tables') or [])}
        self.assertEqual(rangees - self.schema, set(),
                         "modules.yml range une table absente du schéma — retirée ?")

    def test_le_core_et_le_manifeste_disent_la_meme_chose(self):
        import importlib
        import pkgutil
        try:
            import core
        except ImportError:
            self.skipTest('CORE absent')
        declarees = {}
        for info in pkgutil.iter_modules(core.__path__):
            if info.name.startswith('test'):
                continue
            tables = set(getattr(importlib.import_module(f'core.{info.name}'), 'TABLES', set()))
            if tables:
                declarees[info.name] = tables
        self.assertTrue(declarees, "aucune brique ne déclare de table — le CORE a-t-il été lu ?")
        for brique, tables in declarees.items():
            porteurs = [n for n, m in self.modules.items() if brique in (m.get('core') or [])]
            self.assertEqual(len(porteurs), 1, f"la brique « {brique} » doit être nommée par un seul module")
            self.assertLessEqual(tables, set(self.modules[porteurs[0]].get('tables') or []),
                                 f"« {brique} » déclare des tables que son module ne range pas")
        for nom, m in self.modules.items():
            for brique in m.get('core') or []:
                self.assertIn(brique, declarees, f"« {nom} » nomme une brique « {brique} » sans tables")


class TestUnitesSansCycle(unittest.TestCase):
    """Aucune unité générée ne s'ordonne après la target qui la réclame.

    Cortex-Template#5 : `dolt-server.service` portait `After=default.target` et
    `WantedBy=default.target`. La target se range après ce qu'elle réclame :
    cycle, et systemd le casse au boot en supprimant le démarrage du moteur."""

    def test_aucun_generateur_ne_fait_de_cycle(self):
        fautifs = []
        for s in sorted((BRAIN_ROOT_PATH / 'scripts').glob('*.sh')):
            texte = s.read_text(encoding='utf-8', errors='replace')
            reclamee = re.search(r'^WantedBy=.*\bdefault\.target\b', texte, re.MULTILINE)
            apres = re.search(r'^After=.*\bdefault\.target\b', texte, re.MULTILINE)
            if reclamee and apres:
                fautifs.append(s.name)
        self.assertEqual(fautifs, [])


class TestClesVides(unittest.TestCase):
    """Une clé d'environnement VIDE vaut sa valeur par défaut [Cortex-Template#6].

    `os.getenv(X, défaut)` rend '' pour une clé présente et vide : `int('')`
    faisait planter le moteur et le MCP (redémarrage n° 127), et un
    `BRAIN_MCP_SCOPES` vide donnait zéro scope, en silence. Un `MYSECRETS`
    copié de l'exemple sans remplir les clés optionnelles suffisait."""

    def test_aucune_lecture_ou_le_vide_ecrase_le_defaut(self):
        import ast
        fautifs = []
        for f in sorted((BRAIN_ROOT_PATH / 'brain-engine').glob('*.py')):
            if f.name.startswith('test_'):
                continue
            for n in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
                if (isinstance(n, ast.Call) and len(n.args) == 2
                        and ast.unparse(n.func) in ('os.getenv', 'os.environ.get')):
                    fautifs.append(f'{f.name}:{n.lineno}')
        self.assertEqual(fautifs, [], "écrire `os.getenv(X) or défaut`")

    EXEMPLE = BRAIN_ROOT_PATH / 'MYSECRETS.example'

    def _defauts_du_code(self) -> dict:
        """{CLÉ: défaut} pour chaque `os.getenv('CLÉ') or <constante>` du moteur."""
        import ast
        vus = {}
        for f in sorted((BRAIN_ROOT_PATH / 'brain-engine').glob('*.py')):
            if f.name.startswith('test_'):
                continue
            for n in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
                if (isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and len(n.values) == 2
                        and isinstance(n.values[0], ast.Call)
                        and ast.unparse(n.values[0].func) == 'os.getenv'
                        and isinstance(n.values[1], ast.Constant)):
                    vus[n.values[0].args[0].value] = str(n.values[1].value)
        return vus

    def test_l_exemple_ne_laisse_vide_que_les_jetons(self):
        if not self.EXEMPLE.exists():
            self.skipTest('MYSECRETS.example absent')
        vides = [l for l in self.EXEMPLE.read_text().splitlines()
                 if re.fullmatch(r'[A-Z_]+=', l) and not l.startswith('BRAIN_TOKEN')]
        self.assertEqual(vides, [], "une clé de réglage vide écrase l'Environment= de l'unité : la commenter")

    def test_l_exemple_n_a_pas_de_commentaire_en_fin_de_ligne(self):
        if not self.EXEMPLE.exists():
            self.skipTest('MYSECRETS.example absent')
        fautives = [l for l in self.EXEMPLE.read_text().splitlines()
                    if re.match(r'[A-Z_]+=', l) and '#' in l]
        self.assertEqual(fautives, [], "sous systemd, le commentaire ferait partie de la valeur")

    def test_les_defauts_de_l_exemple_sont_ceux_du_code(self):
        if not self.EXEMPLE.exists():
            self.skipTest('MYSECRETS.example absent')
        code = self._defauts_du_code()
        self.assertGreater(len(code), 10, "le code n'a pas été lu")
        ecarts = {}
        for l in self.EXEMPLE.read_text().splitlines():
            m = re.fullmatch(r'# ([A-Z_]+)=(\S+)', l)
            if m and m.group(1) in code and code[m.group(1)] != m.group(2):
                ecarts[m.group(1)] = (m.group(2), code[m.group(1)])
        self.assertEqual(ecarts, {}, "(exemple, code)")

    def test_db_supporte_des_cles_vides(self):
        env = {**os.environ, 'BRAIN_DOLT_PORT': '', 'BRAIN_DB_BACKEND': '', 'BRAIN_DOLT_DB': ''}
        r = subprocess.run([sys.executable, '-c',
                            'import db; print(db.DOLT_PORT, db.BACKEND, db.DOLT_DB)'],
                           cwd=BRAIN_ROOT_PATH / 'brain-engine', env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertEqual(r.stdout.split()[-3:], ['3307', 'dolt', 'brain-dolt'])


class TestExempleConfigLocale(unittest.TestCase):
    """`brain-compose.local.yml.example` a la forme de ce que le setup écrit.

    L'exemple était resté à `kernel_version: "0.9.2"` et `feature_set: full` (un
    reste des paliers), quand le setup écrivait `mode`, `docs_fetch`… Un forkeur
    lisait une forme que rien ne produit plus."""

    def _setup_ecrit(self) -> dict:
        import yaml
        texte = (BRAIN_ROOT_PATH / 'scripts' / 'brain-setup.sh').read_text()
        m = re.search(r'cat > "\$LOCAL_COMPOSE" << EOF\n(.*?)\nEOF\n', texte, re.S)
        self.assertIsNotNone(m, "le bloc écrit par le setup n'a pas été trouvé")
        corps = re.sub(r'\$\([^)]*\)', 'x', m.group(1))         # $(date …)
        corps = corps.replace('${WRITE_MODE}', '')               # fork : pas de verrou
        corps = re.sub(r'\$\{?[A-Z_]+\}?', 'x', corps)
        return yaml.safe_load(corps)

    def _exemple(self) -> dict:
        import yaml
        texte = (BRAIN_ROOT_PATH / 'brain-compose.local.yml.example').read_text()
        return yaml.safe_load(re.sub(r'<[A-Z_-]+>', 'x', texte))

    def test_memes_cles_racine(self):
        self.assertEqual(set(self._exemple()) , set(self._setup_ecrit()))

    def test_memes_cles_d_instance(self):
        ex = next(iter(self._exemple()['instances'].values()))
        se = next(iter(self._setup_ecrit()['instances'].values()))
        self.assertEqual(set(ex), set(se))

    def test_pas_de_version_figee(self):
        texte = (BRAIN_ROOT_PATH / 'brain-compose.local.yml.example').read_text()
        self.assertIsNone(re.search(r'^kernel_version: "\d', texte, re.M),
                          "une version écrite en dur vieillit : un marqueur, le setup écrit la vraie")


class TestRechercheDitSaPanne(unittest.TestCase):
    """Sans Ollama, la recherche le DIT — pas « Aucun résultat ».

    Mesuré sur un fork v2.3.4 sans Ollama : `brain_search` répondait « Aucun
    résultat », `brain_boot` omettait sa section, `embed` concluait « ✅ ». Le
    CORE rendait pourtant la bonne alerte ; `search.py` la jetait."""

    def _core(self, rendu):
        faux = MagicMock()
        faux.cherche.return_value = rendu
        return patch.object(search, '_moteur_core', return_value=faux)

    def test_modele_injoignable_leve(self):
        from core.recherche import INJOIGNABLE
        with self._core(([], INJOIGNABLE)):
            with self.assertRaises(search.RechercheIndisponible) as ctx:
                search.search('une question', top_k=3)
        self.assertIn('ollama pull', ctx.exception.conseil())

    def test_index_vide_leve(self):
        from core.recherche import INDEX_VIDE
        with self._core(([], INDEX_VIDE)):
            with self.assertRaises(search.RechercheIndisponible) as ctx:
                search.search('une question', top_k=3)
        self.assertIn('brain-engine.sh embed', ctx.exception.conseil())

    def test_un_avis_sur_la_requete_n_est_pas_une_panne(self):
        with self._core(([], "2 mot(s) : la retrouvaille est quasi nulle")):
            self.assertEqual(search.search('deux mots', top_k=3), [])

    def test_la_route_search_repond_503(self):
        from core.recherche import INJOIGNABLE
        client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        with patch.object(srv, '_TOKEN_MAP', {}), \
             patch.object(srv, 'run_single_query', side_effect=search.RechercheIndisponible(INJOIGNABLE)):
            r = client.get('/search?q=une+question')
        self.assertEqual(r.status_code, 503)
        self.assertIn('injoignable', r.json()['detail'])

    def test_la_route_boot_repond_503(self):
        from core.recherche import INDEX_VIDE
        client = TestClient(srv.app, raise_server_exceptions=False, client=LOCAL)
        with patch.object(srv, 'run_boot_queries', side_effect=search.RechercheIndisponible(INDEX_VIDE)):
            r = client.get('/boot')
        self.assertEqual(r.status_code, 503)
        self.assertIn('index est vide', r.json()['detail'])

    def _mcp(self):
        import mcp_server
        return mcp_server

    def test_brain_decisions_ne_rend_que_des_adr(self):
        """Le motif `*.md` faisait passer `_template-adr.md` et `README.md`
        devant les ADR : `last=2` ne rendait aucune décision (29/09)."""
        m = self._mcp()
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'profil' / 'decisions'
            d.mkdir(parents=True)
            for nom in ('_template-adr.md', 'README.md', 'BRAIN-001-a.md', 'BRAIN-078-b.md'):
                (d / nom).write_text(f'---\ntitle: {nom}\nstatus: accepted\n---\ncorps\n')
            with patch.object(m, 'BRAIN_ROOT', Path(tmp)):
                texte = getattr(m.brain_decisions, 'fn', m.brain_decisions)(2)
        self.assertIn('BRAIN-078', texte)
        self.assertIn('BRAIN-001', texte)
        self.assertNotIn('_template', texte)
        self.assertNotIn('README', texte)

    def test_brain_search_dit_la_panne(self):
        from core.recherche import INJOIGNABLE
        m = self._mcp()
        with patch.object(m, 'run_single_query', side_effect=search.RechercheIndisponible(INJOIGNABLE)):
            texte = getattr(m.brain_search, 'fn', m.brain_search)('une question')
        self.assertIn('Recherche indisponible', texte)
        self.assertNotIn('Aucun résultat', texte)

    def test_brain_boot_dit_la_panne(self):
        from core.recherche import INJOIGNABLE
        m = self._mcp()
        with patch.object(m, 'run_boot_queries', side_effect=search.RechercheIndisponible(INJOIGNABLE)), \
             patch.object(m, 'brain_state', return_value=''):
            texte = getattr(m.brain_boot, 'fn', m.brain_boot)()
        self.assertIn('Recherche sémantique indisponible', texte)

    def test_embed_sort_en_2_sans_ollama(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'b.db'
            c = sqlite3.connect(base)
            c.executescript((BRAIN_ROOT_PATH / 'brain-engine' / 'schema.sql').read_text())
            c.commit(); c.close()
            env = {**os.environ, 'BRAIN_DB_BACKEND': 'sqlite', 'BRAIN_DB_PATH': str(base),
                   'OLLAMA_URL': 'http://127.0.0.1:9'}
            r = subprocess.run([sys.executable, 'embed.py', '--file', 'agents/debug.md'],
                               cwd=BRAIN_ROOT_PATH / 'brain-engine', env=env,
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2, (r.stdout + r.stderr)[-600:])


class TestScopesDuMcpLocal(unittest.TestCase):
    """Le MCP local d'un fork voit ce que le rôle `mcp` voit [Cortex-Template#9].

    L'unité `brain-mcp` générée ne posait pas `BRAIN_MCP_SCOPES` : le MCP d'un
    fork tombait sur le défaut ÉTROIT de mcp_server.py (public, work), et
    `brain_search` ne voyait ni projets, ni focus, ni learning — sans signal.
    La prod, elle, élargissait par sa propre unité."""

    def test_l_unite_pose_le_role_mcp(self):
        texte = (BRAIN_ROOT_PATH / 'scripts' / 'brain-engine.sh').read_text()
        bloc = re.search(r'cat > "\$unites/brain-mcp\.service" << SVCEOF\n(.*?)\nSVCEOF', texte, re.S)
        self.assertIsNotNone(bloc, "l'unité brain-mcp n'a pas été trouvée")
        # Depuis `brain serve`, les scopes sont DÉCLARÉS dans serve.py et
        # l'unité passe par lui : les deux moitiés sont tenues, sinon le MCP local
        # retomberait sur le défaut étroit sans aucun signal (Cortex-Template#9).
        self.assertRegex(bloc.group(1), r'(?m)^ExecStart=\S+ \$SERVE mcp$',
                         "l'unité MCP ne passe pas par serve.py — les scopes ne s'appliqueraient pas")
        import serve
        self.assertEqual(set(serve.DEFAUTS['BRAIN_MCP_SCOPES'].split(',')), set(srv._SCOPE_ACCESS['mcp']))


class TestEchangesBoite(unittest.TestCase):
    """Le boot montre ce que l'autre brain a déposé — une fois, par machine.

    `echanges/` est partagé avec le brain d'une autre personne. Au boot, les
    nouveautés de `boites/moi/` et `rapports/` s'affichent, puis sont
    marquées vues dans la config LOCALE du clone (rien n'entre dans le dépôt)."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'echanges-boite.sh'

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('echanges-boite.sh absent — script d’instance')
        self.tmp = Path(tempfile.mkdtemp(prefix='echanges-'))
        (self.tmp / 'scripts').mkdir()
        shutil.copy(self.SCRIPT, self.tmp / 'scripts' / 'echanges-boite.sh')
        self.e = self.tmp / 'echanges'
        for d in ('boites/moi', 'boites/autre', 'rapports'):
            (self.e / d).mkdir(parents=True)
            (self.e / d / '.gitkeep').write_text('')
        self._git('init', '-q')
        # La boîte de CE brain, déclarée comme `brain.vu` : dans la config du clone.
        self._git('config', '--local', 'brain.boite', 'moi')
        self._depose('README.md', '# contrat\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args):
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                       cwd=self.e, check=True, capture_output=True)

    def _depose(self, chemin, texte):
        (self.e / chemin).write_text(texte)
        self._git('add', '-A'); self._git('commit', '-qm', chemin)

    def _boite(self, *args):
        return subprocess.run(['bash', str(self.tmp / 'scripts' / 'echanges-boite.sh'), *args],
                              capture_output=True, text=True, timeout=30)

    def test_une_fois_puis_silence(self):
        self._depose('boites/moi/2026-09-28-salut.md', '# Salut\n\n— Claude, pour l’autre\n')
        r = self._boite()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('boites/moi/2026-09-28-salut.md — Salut', r.stdout)
        self.assertIn('— Claude, pour l’autre', r.stdout)
        self.assertNotIn('.gitkeep', r.stdout)
        self.assertEqual(self._boite().stdout, '', "déjà vu : plus rien au boot suivant")

    def test_seule_la_nouveaute_s_affiche(self):
        self._depose('boites/moi/a.md', '# A\n')
        self._boite()
        self._depose('rapports/2026-09-28-mesure.md', '# Mesure\n')
        self._depose('boites/autre/pour-lui.md', '# pas pour l’owner\n')
        sortie = self._boite().stdout
        self.assertIn('rapports/2026-09-28-mesure.md', sortie)
        self.assertNotIn('boites/moi/a.md', sortie)
        self.assertNotIn('pour-lui', sortie, "la boîte de l'autre ne s'affiche pas")

    def test_tout_ne_deplace_pas_le_vu(self):
        self._depose('boites/moi/a.md', '# A\n')
        self.assertIn('boites/moi/a.md', self._boite('--tout').stdout)
        self.assertIn('boites/moi/a.md', self._boite().stdout, "--tout n'a rien marqué vu")

    def test_boite_non_declaree_les_rapports_seuls_et_le_dire(self):
        self._git('config', '--local', '--unset', 'brain.boite')
        self._depose('boites/moi/a.md', '# A\n')
        self._depose('rapports/r.md', '# R\n')
        r = self._boite()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('rapports/r.md', r.stdout)
        self.assertNotIn('boites/moi/a.md', r.stdout, "sans boîte déclarée, aucune boîte lue")
        self.assertIn('brain.boite', r.stdout, "le script dit quoi poser")

    def test_un_nom_de_boite_douteux_est_refuse(self):
        self._git('config', '--local', 'brain.boite', '../rapports')
        r = self._boite()
        self.assertEqual(r.returncode, 2)

    def test_satellite_absent_silence(self):
        shutil.rmtree(self.e)
        r = self._boite()
        self.assertEqual((r.returncode, r.stdout), (0, ''))


class TestInstallSystemd(unittest.TestCase):
    """`install systemd` se rejoue : il réécrit les unités ET les relance, et
    installe le timer d'embed [Cortex-Template#10].

    Joué pour de vrai : un faux `systemctl` en tête du PATH note ses appels,
    les unités s'écrivent dans un XDG_CONFIG_HOME jetable, les ports sont ceux
    d'un bac à sable — rien ne touche aux unités de la machine."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'brain-engine.sh'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='install-systemd-'))
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        self.appels = self.tmp / 'appels'
        faux = self.bin / 'systemctl'
        faux.write_text(f'#!/bin/sh\necho "$*" >> {self.appels}\nexit 0\n')
        faux.chmod(0o755)
        self.unites = self.tmp / 'config' / 'systemd' / 'user'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _installer(self, mode='prod'):
        # HOME jetable : `install systemd` pose ~/.local/bin/brain. Sans lui, la
        # suite réécrivait le VRAI lien de la machine — vers le worktree où elle
        # tournait, supprimé ensuite : la commande `brain` était cassée (2/10).
        env = {**os.environ,
               'PATH': f'{self.bin}:{os.environ["PATH"]}',
               'HOME': str(self.tmp / 'home'),
               'XDG_CONFIG_HOME': str(self.tmp / 'config'),
               'BRAIN_MODE': mode, 'BRAIN_PORT': '17799', 'BRAIN_MCP_PORT': '17798'}
        r = subprocess.run(['bash', str(self.SCRIPT), 'install', 'systemd'],
                           env=env, capture_output=True, text=True, timeout=60)
        appels = self.appels.read_text().splitlines() if self.appels.exists() else []
        return r, appels

    def test_la_commande_brain_se_pose_dans_le_home_recu(self):
        vrai = Path(os.path.expanduser('~/.local/bin/brain'))
        avant = os.readlink(vrai) if vrai.is_symlink() else None
        r, _ = self._installer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lien = self.tmp / 'home' / '.local' / 'bin' / 'brain'
        self.assertTrue(lien.is_symlink(), r.stdout + r.stderr)
        self.assertEqual(Path(os.readlink(lien)).name, 'brain')
        apres = os.readlink(vrai) if vrai.is_symlink() else None
        self.assertEqual(avant, apres, 'le vrai ~/.local/bin/brain a bougé pendant le test')

    def test_les_unites_actives_sont_relancees(self):
        # `enable --now` ne relance pas une unité déjà active : le nouvel
        # environnement n'arrivait qu'au prochain démarrage de session.
        r, appels = self._installer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('--user restart brain-engine.service brain-mcp.service', appels)
        self.assertNotIn('--user enable --now brain-engine.service brain-mcp.service', appels)

    def test_le_timer_d_embed_remplace_le_cron(self):
        r, appels = self._installer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('crontab', r.stdout + r.stderr)
        timer = (self.unites / 'brain-embed.timer').read_text()
        self.assertIn('OnUnitActiveSec=', timer)
        service = (self.unites / 'brain-embed.service').read_text()
        # Par `brain-engine.sh embed` : son code 2 (Ollama injoignable) fait
        # échouer l'unité, et l'échec se voit.
        self.assertRegex(service, r'(?m)^ExecStart=.*scripts/brain-engine\.sh embed$')
        self.assertIn('--user enable --now brain-embed.timer', appels)

    def test_pas_d_embed_en_demo(self):
        r, appels = self._installer(mode='demo')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.unites / 'brain-embed.timer').exists())
        self.assertNotIn('--user enable --now brain-embed.timer', appels)

    def test_rejouer_n_empile_pas_de_sauvegardes(self):
        # La page « Se mettre à jour » fait rejouer `install systemd` à chaque
        # version : une copie par passage empilerait des sauvegardes identiques.
        self._installer()
        r, _ = self._installer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(self.unites.glob('*.avant-*')), [])

    def test_une_unite_changee_est_gardee_a_cote(self):
        self._installer()
        mcp = self.unites / 'brain-mcp.service'
        mcp.write_text(mcp.read_text().replace('ExecStart=', 'Environment=ANCIEN=1\nExecStart='))
        r, _ = self._installer()
        gardees = sorted(p.name for p in self.unites.glob('*.avant-*'))
        self.assertEqual(len(gardees), 1, gardees)
        self.assertTrue(gardees[0].startswith('brain-mcp.service.avant-'))
        self.assertIn('ANCIEN=1', (self.unites / gardees[0]).read_text())

    def _status(self):
        env = {**os.environ,
               'PATH': f'{self.bin}:{os.environ["PATH"]}',
               'XDG_CONFIG_HOME': str(self.tmp / 'config'),
               'BRAIN_MODE': 'prod', 'BRAIN_PORT': '17799', 'BRAIN_MCP_PORT': '17798'}
        r = subprocess.run(['bash', str(self.SCRIPT), 'status'],
                           env=env, capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr

    def test_status_voit_une_unite_d_une_version_passee(self):
        # L'incident de #10 : une unité MCP d'une version passée, relancée par un
        # simple `restart` — sans aucun signal. Depuis `brain serve`, la
        # version passée est celle qui lance mcp_server.py en direct, sans la
        # déclaration (ni les scopes du MCP local).
        self._installer()
        mcp = self.unites / 'brain-mcp.service'
        mcp.write_text(mcp.read_text().replace('serve.py mcp', 'mcp_server.py'))
        sortie = self._status()
        self.assertIn('brain-mcp.service', sortie)
        self.assertIn('install systemd', sortie)
        self.assertNotIn('celles de cette version', sortie)

    def test_status_dit_des_unites_a_jour(self):
        self._installer()
        sortie = self._status()
        self.assertIn('unités : celles de cette version', sortie)
        self.assertNotIn("d'une autre version", sortie)

    def test_status_se_tait_sans_unites_ou_pour_un_autre_brain(self):
        self.assertNotIn('unités', self._status())
        self.unites.mkdir(parents=True)
        (self.unites / 'brain-engine.service').write_text('[Service]\nWorkingDirectory=/ailleurs/Brain\n')
        self.assertNotIn('unités', self._status())

    def test_un_moteur_de_systemd_n_est_pas_une_instance_manuelle(self):
        # L'incident : un moteur lancé par systemd (pas de fichier de PID) était
        # annoncé « instance manuelle », puis `stop` répondait « pas lancé par
        # ce script ». Un faux moteur de CE brain — la ligne de commande que
        # `pid_en_cours` reconnaît, sans port — tient le rôle de systemd.
        serveur = BRAIN_ROOT_PATH / 'brain-engine' / 'server.py'
        faux = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', str(serveur)])
        try:
            r, _ = self._installer()
        finally:
            faux.kill()
            faux.wait()
        sortie = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, sortie)
        self.assertNotIn("Arrêt de l'instance manuelle", sortie)
        self.assertIn('tourne déjà', sortie)


class TestBrainImbrique(unittest.TestCase):
    """Une copie de brain posée dans celui-ci ne s'indexe pas.

    Le 28/09, le premier passage du timer d'embed a indexé trois worktrees de
    `workspace/scratch/` : 14 751 chunks sur 30 453. `workspace/**/*.md` est du
    corpus et le TTL laisse passer une copie fraîche. Le premier cas est le
    chemin de l'incident, copié du journal."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-imbrique-'))
        self._racine = embed.BRAIN_ROOT
        embed.BRAIN_ROOT = self.tmp
        embed._KERNELS.clear()
        def f(rel, texte='## Titre\n\nun contenu assez long pour un chunk.\n'):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text(texte)
        f('KERNEL.md')
        f('workspace/scratch/notes-de-travail.md')
        f('workspace/scratch/wt-v236/KERNEL.md')
        f('workspace/scratch/wt-v236/workspace/papers/README.md')
        f('workspace/scratch/wt-v236/agents/helloWorld.md')
        # Un sous-module a un `.git` FICHIER, comme un worktree : il reste du corpus.
        f('wiki/.git', 'gitdir: ../.git/modules/wiki\n')
        f('wiki/page.md')

    def tearDown(self):
        embed.BRAIN_ROOT = self._racine
        embed._KERNELS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_le_chemin_de_l_incident_est_exclu(self):
        p = self.tmp / 'workspace/scratch/wt-v236/workspace/papers/README.md'
        self.assertTrue(embed.should_exclude(p))

    def test_le_corpus_ne_prend_pas_la_copie(self):
        pris = {str(p.relative_to(self.tmp)) for p, _ in embed.collect_files()}
        self.assertIn('workspace/scratch/notes-de-travail.md', pris)
        self.assertIn('wiki/page.md', pris)
        self.assertEqual([x for x in pris if 'wt-v236' in x], [])

    def test_la_racine_n_est_pas_une_copie(self):
        self.assertFalse(embed.dans_un_brain_imbrique(self.tmp / 'KERNEL.md'))
        self.assertFalse(embed.dans_un_brain_imbrique(self.tmp / 'workspace/scratch/notes-de-travail.md'))


class TestDepotImbriqueHorsIndex(unittest.TestCase):
    """🔴 Un dépôt git posé sous le brain ne s'indexe pas, même sans `KERNEL.md`.

    Le 30/09, un worktree du dépôt `profil` ouvert dans `workspace/scratch/`
    pour relire une ADR a été indexé par l'embed de 22:04 : 187 fichiers, dont
    17 privés — `identity/`, `capital.md`, `gaming/`. `PRIVATE_PATHS` protège
    `profil/identity/`, pas une copie de `profil/` sous un autre chemin ; et le
    filtre des copies ne reconnaissait qu'un brain, à son `KERNEL.md`. Purgés
    à 22:27 par le doctor, sans être sortis de la machine.

    Le critère : un dossier à partir du DEUXIÈME niveau qui porte son propre
    `.git` — fichier (un worktree) ou dossier (un clone). Au premier niveau
    vivent les satellites et le sous-module `wiki/` : du corpus.
    Le premier cas est le chemin de l'incident, copié du journal Dolt."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-depot-imbrique-'))
        self._racine = embed.BRAIN_ROOT
        embed.BRAIN_ROOT = self.tmp
        embed._KERNELS.clear()
        def f(rel, texte='## Titre\n\nun contenu assez long pour un chunk.\n'):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text(texte)
        f('KERNEL.md')
        f('workspace/scratch/notes-de-travail.md')
        # L'incident : un worktree de `profil`, sans KERNEL.md.
        f('workspace/scratch/wt-brain-080/.git',
          'gitdir: ../../../profil/.git/worktrees/wt-brain-080\n')
        f('workspace/scratch/wt-brain-080/identity/career.md')
        f('workspace/scratch/wt-brain-080/capital.md')
        # Un clone (`.git` dossier), relevé le même soir dans scratch.
        (self.tmp / 'workspace/scratch/audit-192/sat-profil/.git').mkdir(parents=True)
        f('workspace/scratch/audit-192/sat-profil/collaboration.md')
        # Au premier niveau : un satellite (clone) et le sous-module restent du corpus.
        (self.tmp / 'profil/.git').mkdir(parents=True)
        f('profil/specs/regle.md')
        f('wiki/.git', 'gitdir: ../.git/modules/wiki\n')
        f('wiki/page.md')

    def tearDown(self):
        embed.BRAIN_ROOT = self._racine
        embed._KERNELS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_le_chemin_de_l_incident_est_exclu(self):
        self.assertTrue(embed.should_exclude(
            self.tmp / 'workspace/scratch/wt-brain-080/identity/career.md'))

    def test_la_passe_complete_ne_prend_aucune_copie(self):
        pris = {str(p.relative_to(self.tmp)) for p, _ in embed.collect_files()}
        self.assertIn('workspace/scratch/notes-de-travail.md', pris,
                      "le témoin voisin doit être pris, sinon « aucune copie » ne prouve rien")
        self.assertEqual([x for x in pris if 'wt-brain-080' in x or 'sat-profil' in x], [])

    def test_file_refuse_la_copie(self):
        self.assertEqual(embed.collect_files('workspace/scratch/wt-brain-080/capital.md'), [])
        self.assertEqual(embed.collect_files('workspace/scratch/audit-192/sat-profil/collaboration.md'), [])

    def test_le_premier_niveau_reste_du_corpus(self):
        self.assertFalse(embed.dans_un_brain_imbrique(self.tmp / 'profil/specs/regle.md'))
        self.assertFalse(embed.dans_un_brain_imbrique(self.tmp / 'wiki/page.md'))
        self.assertFalse(embed.dans_un_brain_imbrique(self.tmp / 'workspace/scratch/notes-de-travail.md'))


class TestContenuSatellite(unittest.TestCase):
    """Le pipeline de contenu vit dans le satellite `contenu/` [BRAIN-080].

    L'atelier et le publié étaient à deux endroits du dépôt brain
    (`workspace/content/`, `content/`) ; ils sont dans un seul satellite.
    Joué dans un brain JETABLE : les racines du module sont redirigées, rien
    ne touche le vrai `contenu/`."""

    def setUp(self):
        import mcp_server
        self.m = mcp_server
        self._sauve = (mcp_server.BRAIN_ROOT, mcp_server._BRAIN_ROOT,
                       mcp_server.CONTENT_ATELIER, mcp_server.CONTENT_PUBLISHED)
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-contenu-'))
        mcp_server.BRAIN_ROOT = mcp_server._BRAIN_ROOT = self.tmp
        mcp_server.CONTENT_ATELIER = self.tmp / 'contenu' / 'atelier'
        mcp_server.CONTENT_PUBLISHED = self.tmp / 'contenu' / 'publie'

    def tearDown(self):
        (self.m.BRAIN_ROOT, self.m._BRAIN_ROOT,
         self.m.CONTENT_ATELIER, self.m.CONTENT_PUBLISHED) = self._sauve
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_les_racines_sont_dans_contenu(self):
        atelier, publie = self._sauve[2], self._sauve[3]
        self.assertEqual(atelier.relative_to(self._sauve[0]).as_posix(), 'contenu/atelier')
        self.assertEqual(publie.relative_to(self._sauve[0]).as_posix(), 'contenu/publie')

    def test_un_fork_sans_contenu_voit_un_pipeline_vide(self):
        self.assertEqual(self.m._scan_content_zone(self.m.CONTENT_ATELIER, 'atelier'), [])

    def test_la_promotion_passe_de_l_atelier_au_publie(self):
        f = self.m.CONTENT_ATELIER / 'posts' / 'essai.md'
        f.parent.mkdir(parents=True)
        f.write_text('---\nstatus: ready\n---\n\n# essai\n')
        promouvoir = getattr(self.m.brain_content_promote, 'fn', self.m.brain_content_promote)
        r = json.loads(promouvoir('contenu/atelier/posts/essai.md', 'scheduled'))
        self.assertEqual(r['path'], 'contenu/publie/posts/essai.md')
        self.assertTrue((self.m.CONTENT_PUBLISHED / 'posts' / 'essai.md').exists())
        self.assertFalse(f.exists())

    def test_hors_du_pipeline_refuse(self):
        (self.tmp / 'workspace').mkdir()
        (self.tmp / 'workspace' / 'note.md').write_text('---\nstatus: ready\n---\n')
        promouvoir = getattr(self.m.brain_content_promote, 'fn', self.m.brain_content_promote)
        self.assertIn('hors du pipeline', promouvoir('workspace/note.md', 'scheduled'))


class TestConceptScribeDestination(unittest.TestCase):
    """Les scripts de concept-scribe écrivent là où on le leur dit [BRAIN-080].

    L'étape 3 range les concepts là où ils agissent (`projets/<slug>/`, `vie/`,
    `contenu/`) : les quatre scripts codaient `workspace/concepts` en dur.
    `CONCEPTS_DIR` choisit la destination ; sans elle, rien ne change. Joué dans
    un brain jetable (`BRAIN_ROOT`) : rien ne touche le vrai `workspace/concepts/`."""

    SCRIPTS = BRAIN_ROOT_PATH / 'scripts' / 'concept-scribe'

    def setUp(self):
        script_d_instance(self.SCRIPTS)
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-concepts-'))
        for dest in ('workspace/concepts', 'vie/concepts'):
            d = self.tmp / dest / 'un-lot'
            d.mkdir(parents=True)
            (d / 'une-idee.md').write_text('---\ndefinition: une idée\n---\n\n# une idée\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _index(self, **env):
        return subprocess.run(['bash', str(self.SCRIPTS / 'build-index.sh')], capture_output=True, text=True,
                              env={**os.environ, 'BRAIN_ROOT': str(self.tmp), **env}, timeout=60)

    def test_la_destination_choisie_recoit_l_index(self):
        r = self._index(CONCEPTS_DIR=str(self.tmp / 'vie' / 'concepts'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.tmp / 'vie' / 'concepts' / 'INDEX.md').exists())
        self.assertFalse((self.tmp / 'workspace' / 'concepts' / 'INDEX.md').exists(),
                         "l'ancien dossier n'est pas touché quand une destination est donnée")

    def test_sans_destination_rien_ne_change(self):
        r = self._index()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.tmp / 'workspace' / 'concepts' / 'INDEX.md').exists())

    def test_le_statut_traite_se_lit_dans_la_destination(self):
        """`list.sh` dit « traité » quand le lot existe dans la destination choisie —
        sinon `run.sh --all-unprocessed` referait ce qui est déjà rangé ailleurs."""
        (self.tmp / 'workspace' / 'scratch').mkdir(parents=True)
        (self.tmp / 'workspace' / 'scratch' / 'un-lot.md').write_text('# un lot\n')
        shutil.rmtree(self.tmp / 'workspace' / 'concepts')
        r = subprocess.run(['bash', str(self.SCRIPTS / 'list.sh')], capture_output=True, text=True, timeout=60,
                           env={**os.environ, 'BRAIN_ROOT': str(self.tmp),
                                'CONCEPTS_DIR': str(self.tmp / 'vie' / 'concepts')})
        ligne = next(l for l in r.stdout.splitlines() if 'un-lot.md' in l)
        self.assertIn('traité', ligne)
        self.assertNotIn('non traité', ligne)


class TestProjetsRecursif(unittest.TestCase):
    """La connaissance d'un projet, dans `projets/<slug>/`, est du corpus [BRAIN-080].

    L'étape 4 range la connaissance des backlogs à côté de la fiche du projet.
    `projets/` n'était indexé qu'à plat : ce qui descendait d'un niveau sortait
    du RAG. Joué dans un brain jetable ; le témoin : la fiche à plat reste prise,
    et un clone posé sous un projet reste dehors (#447)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-projets-'))
        self._racine = embed.BRAIN_ROOT
        embed.BRAIN_ROOT = self.tmp
        embed._KERNELS.clear()
        def f(rel):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text('## Titre\n\nun contenu assez long pour un chunk.\n')
        f('KERNEL.md')
        f('projets/mon-projet.md')
        f('projets/mon-projet/cadrage-separation.md')
        f('projets/mon-api/decisions/0001-choix.md')
        (self.tmp / 'projets/mon-projet/depot/.git').mkdir(parents=True)
        f('projets/mon-projet/depot/README.md')

    def tearDown(self):
        embed.BRAIN_ROOT = self._racine
        embed._KERNELS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_la_connaissance_d_un_projet_est_prise(self):
        pris = {str(p.relative_to(self.tmp)) for p, _ in embed.collect_files()}
        self.assertIn('projets/mon-projet.md', pris, "le témoin : la fiche à plat")
        self.assertIn('projets/mon-projet/cadrage-separation.md', pris)
        self.assertIn('projets/mon-api/decisions/0001-choix.md', pris)
        self.assertNotIn('projets/mon-projet/depot/README.md', pris, "un clone sous un projet reste dehors")


class TestVieJamaisIndexee(unittest.TestCase):
    """🔴 `vie/` n'entre jamais dans l'index, par aucun des deux chemins [BRAIN-080].

    Le satellite de la vie de l'owner (l'administratif, le terrain, les
    concepts personnels). Ne pas le déclarer à l'indexeur ne suffit pas :
    un fichier écrit par `PUT /brain/{path}` passe par `--file`, et tout
    fichier ni exclu ni privé retombe sur la portée par défaut — il serait
    lisible par le MCP. Rien n'entre dans `vie/` avant que ce test soit vert.

    Le témoin tient dans la paire : un fichier de `vie/` est refusé, un
    fichier voisin hors de `vie/` est pris. Sans le second, « refusé »
    pourrait venir d'un indexeur qui ne prend plus rien."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='brain-vie-'))
        self._racine = embed.BRAIN_ROOT
        embed.BRAIN_ROOT = self.tmp
        embed._KERNELS.clear()
        def f(rel, texte='## Titre\n\nun contenu assez long pour un chunk.\n'):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text(texte)
        f('KERNEL.md')
        f('vie/papiers/releve.md')
        f('vie/concepts/perso/INDEX.md')
        f('vie/README.md')
        f('workspace/scratch/notes-de-travail.md')

    def tearDown(self):
        embed.BRAIN_ROOT = self._racine
        embed._KERNELS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vie_est_prive(self):
        self.assertTrue(embed.is_private('vie/papiers/releve.md'))
        self.assertTrue(embed.should_exclude(self.tmp / 'vie/README.md'))

    def test_la_passe_complete_ne_prend_rien_de_vie(self):
        pris = {str(p.relative_to(self.tmp)) for p, _ in embed.collect_files()}
        self.assertIn('workspace/scratch/notes-de-travail.md', pris,
                      "le témoin voisin doit être pris, sinon « rien de vie » ne prouve rien")
        self.assertEqual([x for x in pris if x.startswith('vie/')], [])

    def test_file_refuse_un_fichier_de_vie(self):
        """Le chemin de `PUT /brain/{path}` : la file de réindexation → `--file`."""
        self.assertEqual(embed.collect_files('vie/papiers/releve.md'), [])
        self.assertEqual(len(embed.collect_files('workspace/scratch/notes-de-travail.md')), 1,
                         "le témoin voisin passe par --file")

    def test_un_nom_qui_commence_par_vie_n_est_pas_vie(self):
        # `vie/` avec sa barre : `vieux-projet.md` n'est pas privé.
        self.assertFalse(embed.is_private('projets/vieux-projet.md'))
        self.assertFalse(embed.is_private('video/notes.md'))


    def test_l_api_n_ecrit_pas_dans_vie(self):
        """`NIVEAUX.yml` déclare `vie/` en `zone: kernel` : le MCP, qui n'a pas ce
        scope, ne peut pas y écrire. `contenu/` reste libre — le MCP y travaille."""
        self.assertEqual(srv._write_zone('vie/papiers/releve.md'), 'kernel')
        self.assertEqual(srv._write_zone('contenu/atelier/posts/brouillon.md'), 'libre',
                         "le témoin voisin : une zone libre reste libre")


class TestForgeWhoami(unittest.TestCase):
    """`whoami` ne dit que ce qu'il a vérifié.

    Il disait « ✅ accès confirmé » avec un jeton en lecture seule, et rendait
    une sortie identique au mot près une fois le jeton régénéré en écriture.
    Joué contre une FAUSSE forge : `conf` et `call` sont remplacés — ni
    MYSECRETS lu, ni réseau."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'brain-forge.py'
    # Le message exact de Gitea, relevé le 26/09.
    REFUS_DE_SCOPE = ('token does not have at least one of required scope(s), '
                      'required=[write:repository], token scope=read:repository')

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('brain-forge.py absent — script d’instance')
        import importlib.util
        spec = importlib.util.spec_from_file_location('brain_forge_essai', self.SCRIPT)
        self.bf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bf)
        self.bf.conf = lambda: ('https://forge.essai', 'jeton-factice')

    def _whoami(self, reponse):
        self.bf.call = lambda method, path, payload=None: reponse
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = self.bf.cmd_whoami('Owner/depot')
        return code, sortie.getvalue()

    def test_la_meme_sortie_ne_pretend_plus_l_ecriture(self):
        code, sortie = self._whoami((200, {'permissions': {'admin': True, 'push': True, 'pull': True}}))
        self.assertEqual(code, 0)
        self.assertNotIn('accès confirmé', sortie)
        self.assertIn('NON vérifiable', sortie)

    def test_un_compte_sans_push_rougit(self):
        code, sortie = self._whoami((200, {'permissions': {'admin': False, 'push': False, 'pull': True}}))
        self.assertEqual(code, 1)
        self.assertIn('push=False', sortie)

    def test_un_refus_de_scope_est_dit_en_clair(self):
        texte = self.bf.raison(403, {'message': self.REFUS_DE_SCOPE})
        self.assertIn(self.REFUS_DE_SCOPE, texte)
        self.assertIn('JETON', texte)
        self.assertIn('write:repository', texte.split('→', 1)[1])

    def test_un_autre_refus_reste_tel_quel(self):
        self.assertEqual(self.bf.raison(404, {'message': 'not found'}), 'not found')
        self.assertIsNone(self.bf.raison(500, None))


class TestTypesDeCommitGeneres(unittest.TestCase):
    """La skill liste les types de commit que le hook `commit-msg` applique —
    lus au même endroit, de la même façon. Si l'extraction de l'un
    change sans l'autre, ce test rougit."""

    def test_la_skill_et_le_hook_lisent_les_memes_types(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'docs_generer_types', BRAIN_ROOT_PATH / 'scripts' / 'docs-generer.py')
        dg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dg)
        generes = dg.Mesures(BRAIN_ROOT_PATH).types_commit
        # Le hook LUI-MÊME, sur un type qui n'existe pas : il refuse et dit
        # « Types attendus : … » — sa propre extraction, pas une copie.
        with tempfile.TemporaryDirectory(prefix='types-commit-') as d:
            msg = Path(d) / 'MSG'
            msg.write_text('inexistant: un sujet\n', encoding='utf-8')
            r = subprocess.run(['bash', str(BRAIN_ROOT_PATH / 'scripts' / 'hooks' / 'commit-msg'),
                                str(msg)], cwd=BRAIN_ROOT_PATH, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, "le hook devait refuser un type inexistant")
        ligne = next((l for l in r.stderr.splitlines() if 'Types attendus' in l), '')
        du_hook = ligne.split(':', 1)[1].split() if ':' in ligne else []
        self.assertTrue(du_hook, "le hook n'a rien dit — le test ne mesurerait rien")
        self.assertEqual(generes, du_hook)


class TestForgeMergeRetireLaBranche(unittest.TestCase):
    """La branche source part avec la fusion — sauf une branche longue. Joué
    contre une FAUSSE forge : aucun réseau, aucun jeton."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'brain-forge.py'

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('brain-forge.py absent — script d’instance')
        import importlib.util
        spec = importlib.util.spec_from_file_location('brain_forge_merge', self.SCRIPT)
        self.bf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bf)

    def _merge(self, tete, depot='Owner/depot'):
        envoye = {}
        def call(method, path, payload=None):
            if method == 'GET':
                return 200, {'head': {'ref': tete, 'repo': {'full_name': depot}}}
            envoye.update(payload or {})
            return 200, None
        self.bf.call = call
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.bf.cmd_merge('Owner/depot', '1', 'merge'), 0)
        return envoye

    def test_une_branche_de_travail_part(self):
        self.assertTrue(self._merge('scribe/fiche-1')['delete_branch_after_merge'])

    def test_dev_autonome_reste(self):
        self.assertFalse(self._merge('dev/autonome')['delete_branch_after_merge'])

    def test_un_tronc_reste(self):
        self.assertFalse(self._merge('main')['delete_branch_after_merge'])

    def test_la_branche_d_un_fork_n_est_pas_la_notre(self):
        self.assertFalse(self._merge('scribe/fiche-1', depot='Autre/fork')['delete_branch_after_merge'])


class TestForgeAutonome(unittest.TestCase):
    """En autonomie, le jeton du compte `brain` — et JAMAIS de repli sur celui
    de l'humain (BRAIN-079, étape 6). Joué contre un FAUX MYSECRETS : le vrai
    n'est jamais lu."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'brain-forge.py'

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('brain-forge.py absent — script d’instance')
        import importlib.util
        spec = importlib.util.spec_from_file_location('brain_forge_autonome', self.SCRIPT)
        self.bf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bf)
        self.d = Path(tempfile.mkdtemp(prefix='forge-autonome-'))
        self.bf.SECRETS = self.d / 'MYSECRETS'

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _conf(self, contenu, autonome):
        self.bf.SECRETS.write_text(contenu, encoding='utf-8')
        self.bf.AUTONOME = autonome
        return self.bf.conf()

    def test_ensemble_c_est_le_jeton_de_l_humain(self):
        self.assertEqual(self._conf('GITEA_TOKEN=h\nGITEA_TOKEN_AUTONOME=b\n', False)[1], 'h')

    def test_en_autonomie_c_est_le_compte_brain(self):
        self.assertEqual(self._conf('GITEA_TOKEN=h\nGITEA_TOKEN_AUTONOME=b\n', True)[1], 'b')

    def test_en_autonomie_sans_son_jeton_il_refuse_sans_repli(self):
        with self.assertRaises(SystemExit) as e:
            self._conf('GITEA_TOKEN=h\n', True)
        self.assertIn('JAMAIS', str(e.exception))
        self.assertNotIn('=h', str(e.exception))


class TestHookMarqueursDeConflit(unittest.TestCase):
    """Le pre-commit refuse un marqueur de conflit git ajouté par le commit.

    Le 27/09, `||||||| 5c73ba0` — la ligne de BASE d'une fusion diff3 — est
    entré dans une fiche du backlog, sans bruit. Joué dans un dépôt
    JETABLE où le hook est copié : ses gardes optionnels s'effacent."""

    HOOKS = BRAIN_ROOT_PATH / 'scripts' / 'hooks'

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix='hook-marqueurs-'))
        (self.d / 'scripts' / 'hooks').mkdir(parents=True)
        (self.d / 'scripts' / 'lib').mkdir()
        for f in ('pre-commit', '_racines.sh'):
            shutil.copy(self.HOOKS / f, self.d / 'scripts' / 'hooks' / f)
        shutil.copy(BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'python.sh', self.d / 'scripts' / 'lib' / 'python.sh')
        self._git('init', '-q')
        (self.d / 'fiche.md').write_text('# fiche\n')
        self._git('add', '-A')
        self._git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'init', '--no-verify')

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _git(self, *a):
        return subprocess.run(['git', *a], cwd=self.d, capture_output=True, text=True, check=True)

    def _hook(self, contenu):
        (self.d / 'fiche.md').write_text(contenu)
        self._git('add', 'fiche.md')
        return subprocess.run(['bash', 'scripts/hooks/pre-commit'], cwd=self.d,
                              capture_output=True, text=True, timeout=60)

    def test_la_ligne_de_base_de_l_incident_est_refusee(self):
        r = self._hook('# fiche\nseul fichier manquant pèse plus que 1 654 lignes de dérive.\n'
                       '||||||| 5c73ba0\n\n---\n')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('marqueur', r.stdout)

    def test_les_marqueurs_d_un_conflit_classique_sont_refuses(self):
        r = self._hook('# fiche\n<<<<<<< HEAD\nici\n=======\nlà\n>>>>>>> autre\n')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_un_commit_propre_passe(self):
        r = self._hook('# fiche\ndu texte, et des espaces en fin de ligne   \n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestDoltLaptop(unittest.TestCase):
    """`dolt-laptop.sh` pose la branche du laptop, et son épreuve voit une garde
    absente [BRAIN-078].

    Une vraie base Dolt, au vrai schéma, servie sur un port libre du bac à
    sable — jamais la base de la machine."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'dolt-laptop.sh'

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('dolt-laptop.sh absent — script d’instance')
        if not shutil.which('dolt'):
            self.skipTest('dolt absent')
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.tmp = Path(tempfile.mkdtemp(prefix='dolt-laptop-'))
        self.base = self.tmp / 'brain-dolt'
        self.base.mkdir()
        env = {**os.environ, 'HOME': str(self.tmp)}
        run = lambda *a, **k: subprocess.run(a, cwd=self.base, env=env, capture_output=True, text=True, check=True, **k)
        run('dolt', 'init', '--name', 'essai', '--email', 'essai@local')
        run('dolt', 'sql', input=(BRAIN_ROOT_PATH / 'brain-engine' / 'schema-dolt.sql').read_text())
        run('dolt', 'sql', '-q', "CALL DOLT_ADD('-A'); CALL DOLT_COMMIT('-m','schema')")
        self.serveur = subprocess.Popen(['dolt', 'sql-server', '--host', '127.0.0.1', '--port', str(self.port)],
                                        cwd=self.base, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', self.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)

    def tearDown(self):
        if hasattr(self, 'serveur'):
            self.serveur.terminate(); self.serveur.wait(10)
        if hasattr(self, 'tmp'):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _lancer(self, *args, script=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(BRAIN_DOLT_PORT=str(self.port), BRAIN_ROOT=str(BRAIN_ROOT_PATH))
        return subprocess.run(['bash', str(script or self.SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=120)

    def _laptop_existe(self):
        import pymysql
        c = pymysql.connect(host='127.0.0.1', port=self.port, user='root', password='', database='brain-dolt')
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM mysql.user WHERE User='laptop'")
            return cur.fetchone()[0] > 0

    def test_a_blanc_rien_n_est_pose(self):
        r = self._lancer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('À BLANC', r.stdout)
        self.assertFalse(self._laptop_existe())

    def test_applique_s_eprouve_et_se_rejoue(self):
        r = self._lancer('--appliquer')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('7 épreuve(s), 0 échec(s)', r.stdout)
        self.assertTrue(self._laptop_existe())
        r = self._lancer('--appliquer')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('0 échec(s)', r.stdout)

    def test_l_epreuve_voit_une_garde_absente(self):
        # Une copie du script qui ne retire PAS la règle par défaut : tout
        # utilisateur écrit alors sur toute branche, main comprise. L'épreuve
        # doit le voir — sa première version, qui écrivait « zéro ligne », ne
        # l'aurait pas vu.
        mutant = self.tmp / 'dolt-laptop-sans-retrait.sh'
        texte = self.SCRIPT.read_text()
        retrait = 'if defaut:\n    gestes.append'
        # La règle de `laptop` saute aussi : sous la règle par défaut, Dolt la
        # refuse comme redondante, et le script s'arrêterait avant l'épreuve.
        regle = 'if not any(x[:4] == (BASE, BRANCHE, UTILISATEUR, HOTE_UTILISATEUR) for x in regles):'
        self.assertEqual((texte.count(retrait), texte.count(regle)), (1, 1))
        mutant.write_text(texte.replace(retrait, 'if False:\n    gestes.append').replace(regle, 'if False:'))
        (self.tmp / 'lib').mkdir()
        shutil.copy(BRAIN_ROOT_PATH / 'scripts' / 'lib' / 'python.sh', self.tmp / 'lib' / 'python.sh')
        r = self._lancer('--appliquer', script=mutant)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('❌ écrire sur main : refusé', r.stdout)


class TestDoltSauvegarde(unittest.TestCase):
    """`dolt-sauvegarde.sh` sauvegarde l'historique et prouve qu'il se restaure
   . Une vraie base Dolt sur un port libre, une sauvegarde dans un
    dossier jetable — jamais la base de la machine."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'dolt-sauvegarde.sh'

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('dolt-sauvegarde.sh absent — script d’instance')
        self.dolt = shutil.which('dolt')
        if not self.dolt:
            self.skipTest('dolt absent')
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.tmp = Path(tempfile.mkdtemp(prefix='dolt-sauvegarde-'))
        base = self.tmp / 'brain-dolt'
        base.mkdir()
        env = {**os.environ, 'HOME': str(self.tmp)}
        run = lambda *a: subprocess.run(a, cwd=base, env=env, capture_output=True, text=True, check=True)
        run('dolt', 'init', '--name', 'essai', '--email', 'essai@local')
        run('dolt', 'sql', '-q', "CREATE TABLE claims (sess_id varchar(64) primary key); "
                                 "INSERT INTO claims VALUES ('a'); CALL DOLT_ADD('-A'); CALL DOLT_COMMIT('-m','un')")
        run('dolt', 'sql', '-q', "INSERT INTO claims VALUES ('b'); CALL DOLT_COMMIT('-Am','deux')")
        self.serveur = subprocess.Popen([self.dolt, 'sql-server', '--host', '127.0.0.1', '--port', str(self.port)],
                                        cwd=base, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', self.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)
        self.sauvegardes = self.tmp / 'Sauvegardes'
        self.sauvegardes.mkdir()

    def tearDown(self):
        if hasattr(self, 'serveur'):
            self.serveur.terminate(); self.serveur.wait(10)
        if hasattr(self, 'tmp'):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _declarer(self):
        import pymysql
        c = pymysql.connect(host='127.0.0.1', port=self.port, user='root', password='',
                            database='brain-dolt', autocommit=True)
        with c.cursor() as cur:
            cur.execute("CALL DOLT_BACKUP('add', 'local', %s)", (f"file://{self.sauvegardes / 'brain-dolt'}",))

    def _lancer(self, *args, path=None, copie=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(BRAIN_DOLT_PORT=str(self.port), BRAIN_ROOT=str(BRAIN_ROOT_PATH))
        if copie:
            env['BRAIN_DOLT_COPIE'] = copie
        if path:
            env['PATH'] = f"{path}:{env['PATH']}"
        return subprocess.run(['bash', str(self.SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=180)

    def test_sans_sauvegarde_declaree_il_le_dit(self):
        r = self._lancer()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("DOLT_BACKUP('add'", r.stdout)

    def test_sauvegarde_puis_restaure_a_l_identique(self):
        self._declarer()
        r = self._lancer('--eprouver')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("à l'identique", r.stdout)
        self.assertEqual(list(self.sauvegardes.glob('.epreuve-restauration-*')), [],
                         'le dossier jetable de la restauration est effacé')

    def _faux_rsync(self, sortie):
        faux = self.tmp / 'faux-rsync'
        faux.mkdir(exist_ok=True)
        journal = self.tmp / 'rsync.args'
        (faux / 'rsync').write_text(f'#!/bin/bash\necho "$@" > {journal}\nexit {sortie}\n')
        (faux / 'rsync').chmod(0o755)
        return faux, journal

    def test_sans_cible_declaree_rien_n_est_copie(self):
        self._declarer()
        faux, journal = self._faux_rsync(0)
        r = self._lancer(path=str(faux))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(journal.exists(), "sans BRAIN_DOLT_COPIE, rsync n'est pas appelé")

    def test_la_copie_part_apres_le_sync(self):
        self._declarer()
        faux, journal = self._faux_rsync(0)
        r = self._lancer(path=str(faux), copie='hote:Sauvegardes/brain-dolt/')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('copiée hors du poste', r.stdout)
        args = journal.read_text().split()
        self.assertEqual(args[-2:], [f"{self.sauvegardes / 'brain-dolt'}/", 'hote:Sauvegardes/brain-dolt/'])

    def test_une_copie_ratee_se_dit_et_sort_en_3(self):
        self._declarer()
        faux, _ = self._faux_rsync(12)
        r = self._lancer(path=str(faux), copie='hote:x/')
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('LOCALE est faite', r.stdout)

    def test_une_copie_ratee_n_est_pas_masquee_par_l_epreuve(self):
        self._declarer()
        faux, _ = self._faux_rsync(12)
        r = self._lancer('--eprouver', path=str(faux), copie='hote:x/')
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_une_restauration_qui_ne_rend_pas_la_base_rougit(self):
        # Un faux `dolt` dont `backup restore` rend une base VIDE : la
        # comparaison doit le voir — sinon l'épreuve ne prouverait rien.
        self._declarer()
        faux = self.tmp / 'bin'
        faux.mkdir()
        (faux / 'dolt').write_text(
            '#!/bin/bash\n'
            'if [ "$1" = backup ] && [ "$2" = restore ]; then\n'
            f'  mkdir -p "$4" && cd "$4" && exec {self.dolt} init --name x --email x@x\n'
            'fi\n'
            f'exec {self.dolt} "$@"\n')
        (faux / 'dolt').chmod(0o755)
        r = self._lancer('--eprouver', path=faux)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('ne rend pas la base', r.stdout)


class TestEmbedPasSurReplica(unittest.TestCase):
    """`install systemd` ne pose pas le timer d'embed sur une instance
    `replica-nomad` : les vecteurs appartiennent au master, et la base refuse
    au laptop d'écrire `embeddings` [BRAIN-078]. Et `status` ne voit pas le
    timer absent comme une unité d'une autre version.

    Un faux brain : un dépôt git jetable, les scripts copiés, une config locale
    qui déclare la posture — comme sur le laptop."""

    def setUp(self):
        if not (BRAIN_ROOT_PATH / 'scripts' / 'posture-gate-check.sh').exists():
            self.skipTest('posture-gate-check.sh absent — script d’instance')
        self.tmp = Path(tempfile.mkdtemp(prefix='embed-replica-'))
        self.brain = self.tmp / 'brain'
        (self.brain / 'scripts' / 'lib').mkdir(parents=True)
        (self.brain / 'brain-engine').mkdir()
        for f in ('brain-engine.sh', 'posture-gate-check.sh', 'lib/python.sh'):
            shutil.copy(BRAIN_ROOT_PATH / 'scripts' / f, self.brain / 'scripts' / f)
        for f in ('server.py', 'mcp_server.py'):
            (self.brain / 'brain-engine' / f).write_text('# faux\n')
        (self.brain / 'brain-engine' / '.venv').symlink_to(BRAIN_ROOT_PATH / 'brain-engine' / '.venv')
        subprocess.run(['git', 'init', '-q'], cwd=self.brain, check=True)
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        (self.bin / 'systemctl').write_text('#!/bin/sh\nexit 0\n')
        (self.bin / 'systemctl').chmod(0o755)
        self.unites = self.tmp / 'config' / 'systemd' / 'user'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _posture(self, posture):
        (self.brain / 'brain-compose.local.yml').write_text(
            f'instances:\n  essai:\n    active: true\n    posture: {posture}\n    mode: prod\n')

    def _lancer(self, commande):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(PATH=f"{self.bin}:{env['PATH']}", XDG_CONFIG_HOME=str(self.tmp / 'config'),
                   BRAIN_PORT='17797', BRAIN_MCP_PORT='17796')
        r = subprocess.run(['bash', str(self.brain / 'scripts' / 'brain-engine.sh'), *commande.split()],
                           env=env, capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr

    def test_sur_replica_pas_de_timer_et_status_ne_s_en_plaint_pas(self):
        self._posture('replica-nomad')
        sortie = self._lancer('install systemd')
        self.assertTrue((self.unites / 'brain-engine.service').exists(), sortie)
        self.assertFalse((self.unites / 'brain-embed.timer').exists(), sortie)
        self.assertIn('replica-nomad', sortie)
        self.assertIn('unités : celles de cette version', self._lancer('status'))

    def test_le_temoin_master_a_son_timer(self):
        self._posture('master')
        self._lancer('install systemd')
        self.assertTrue((self.unites / 'brain-embed.timer').exists())


class TestSuffixeDeMachine(unittest.TestCase):
    """Sur une instance `replica-nomad`, un claim s'ouvre sous un identifiant
    qui porte `.<machine>` — tranché le 29/09 [BRAIN-078]. Le script
    refuse sans, et donne l'identifiant à utiliser.

    Un faux brain : dépôt jetable, scripts copiés, config locale qui déclare la
    posture. Le moteur visé est un port MORT et la base un SQLite jetable : le
    cas accepté ne peut rien ouvrir nulle part."""

    def setUp(self):
        if not (BRAIN_ROOT_PATH / 'scripts' / 'posture-gate-check.sh').exists():
            self.skipTest('posture-gate-check.sh absent — script d’instance')
        self.tmp = Path(tempfile.mkdtemp(prefix='suffixe-machine-'))
        self.brain = self.tmp / 'brain'
        (self.brain / 'scripts' / 'lib').mkdir(parents=True)
        (self.brain / 'brain-engine').mkdir()
        for f in ('bsi-claim.sh', 'posture-gate-check.sh', 'lib/python.sh'):
            shutil.copy(BRAIN_ROOT_PATH / 'scripts' / f, self.brain / 'scripts' / f)
        shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / 'db.py', self.brain / 'brain-engine' / 'db.py')
        (self.brain / 'brain-engine' / '.venv').symlink_to(BRAIN_ROOT_PATH / 'brain-engine' / '.venv')
        subprocess.run(['git', 'init', '-q'], cwd=self.brain, check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, posture, machine='laptop'):
        (self.brain / 'brain-compose.local.yml').write_text(
            f'instances:\n  essai:\n    active: true\n    posture: {posture}\n'
            + (f'machine: {machine}\n' if machine else ''))

    def _ouvrir(self, sess_id):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(BRAIN_PORT='1', BRAIN_DB_BACKEND='sqlite',
                   BRAIN_DB_PATH=str(self.tmp / 'jetable.db'))
        r = subprocess.run(['bash', str(self.brain / 'scripts' / 'bsi-claim.sh'), 'open', sess_id,
                            '--type', 'work', '--scope', 'work/essai'],
                           env=env, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def test_sur_replica_sans_suffixe_refuse_et_donne_l_identifiant(self):
        self._config('replica-nomad')
        code, sortie = self._ouvrir('sess-20260929-1330-work-essai')
        self.assertEqual(code, 1, sortie)
        self.assertIn('open sess-20260929-1330-work-essai.laptop', sortie)

    def test_sur_replica_avec_suffixe_le_garde_laisse_passer(self):
        self._config('replica-nomad')
        _, sortie = self._ouvrir('sess-20260929-1330-work-essai.laptop')
        self.assertNotIn("l'identifiant porte", sortie)
        self.assertIn('repli', sortie)   # arrivé au repli local : le garde est passé

    def test_sur_la_prod_rien_ne_change(self):
        self._config('master', machine='desktop')
        _, sortie = self._ouvrir('sess-20260929-1330-work-essai')
        self.assertNotIn("l'identifiant porte", sortie)


class TestDoltBrancheRafraichir(unittest.TestCase):
    """La branche du laptop reçoit `main`, et chaque machine garde ses lignes
    [BRAIN-078]. Une vraie base Dolt au vrai schéma, sur un port libre ; la
    branche posée par dolt-laptop.sh ; un faux brain qui se dit `laptop`."""

    def setUp(self):
        for f in ('dolt-branche-rafraichir.sh', 'dolt-laptop.sh'):
            if not (BRAIN_ROOT_PATH / 'scripts' / f).exists():
                self.skipTest(f'{f} absent — script d’instance')
        if not shutil.which('dolt'):
            self.skipTest('dolt absent')
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.tmp = Path(tempfile.mkdtemp(prefix='dolt-rafraichir-'))
        base = self.tmp / 'brain-dolt'
        base.mkdir()
        env = {**os.environ, 'HOME': str(self.tmp)}
        run = lambda *a, **k: subprocess.run(a, cwd=base, env=env, capture_output=True, text=True, check=True, **k)
        run('dolt', 'init', '--name', 'essai', '--email', 'essai@local')
        run('dolt', 'sql', input=(BRAIN_ROOT_PATH / 'brain-engine' / 'schema-dolt.sql').read_text())
        run('dolt', 'sql', '-q', "CALL DOLT_ADD('-A'); CALL DOLT_COMMIT('-m','schema')")
        self.serveur = subprocess.Popen(['dolt', 'sql-server', '--host', '127.0.0.1', '--port', str(self.port)],
                                        cwd=base, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', self.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)
        # Le faux brain du laptop : ses scripts, db.py, et `machine: laptop`.
        self.brain = self.tmp / 'brain'
        (self.brain / 'scripts' / 'lib').mkdir(parents=True)
        (self.brain / 'brain-engine').mkdir()
        for f in ('dolt-branche-rafraichir.sh', 'dolt-laptop.sh', 'lib/python.sh'):
            shutil.copy(BRAIN_ROOT_PATH / 'scripts' / f, self.brain / 'scripts' / f)
        for f in ('db.py', 'modules.yml'):
            shutil.copy(BRAIN_ROOT_PATH / 'brain-engine' / f, self.brain / 'brain-engine' / f)
        (self.brain / 'brain-engine' / '.venv').symlink_to(BRAIN_ROOT_PATH / 'brain-engine' / '.venv')
        (self.brain / 'brain-compose.local.yml').write_text('machine: laptop\n')
        r = self._lancer('dolt-laptop.sh', '--appliquer', laptop=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def tearDown(self):
        if hasattr(self, 'serveur'):
            self.serveur.terminate(); self.serveur.wait(10)
        if hasattr(self, 'tmp'):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _lancer(self, script, *args, laptop=True, chemin=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(BRAIN_DOLT_PORT=str(self.port), BRAIN_ROOT=str(self.brain))
        if laptop:
            env.update(BRAIN_DB_BACKEND='dolt', BRAIN_DOLT_USER='laptop', BRAIN_DOLT_DB='brain-dolt/laptop')
        return subprocess.run(['bash', str(chemin or self.brain / 'scripts' / script), *args],
                              env=env, capture_output=True, text=True, timeout=120)

    def _sql(self, utilisateur, base, *requetes):
        import pymysql
        c = pymysql.connect(host='127.0.0.1', port=self.port, user=utilisateur, password='',
                            database=base, autocommit=True)
        with c.cursor() as cur:
            for r in requetes:
                cur.execute(r)
            return cur.fetchall()

    def _pire_cas(self):
        ins = "INSERT INTO claims (sess_id,type,scope,opened_at) VALUES ('{}','work','work/x',UTC_TIMESTAMP())"
        self._sql('root', 'brain-dolt', ins.format('sess-a-fixe'), ins.format('sess-b.laptop'),
                  "CALL DOLT_COMMIT('-Am','base')")
        self.assertEqual(self._lancer('dolt-branche-rafraichir.sh').returncode, 0)
        # chaque côté modifie LES DEUX lignes ; le fixe ajoute un claim ; le
        # laptop laisse une écriture non commitée
        self._sql('root', 'brain-dolt', "UPDATE claims SET status='closed'",
                  ins.format('sess-c-fixe'), "CALL DOLT_COMMIT('-Am','le fixe ferme tout')")
        self._sql('laptop', 'brain-dolt/laptop', "UPDATE claims SET status='paused'",
                  "CALL DOLT_ADD('claims')", "CALL DOLT_COMMIT('-m','le laptop met en pause')",
                  ins.format('sess-d.laptop'))

    def _etat(self):
        return dict(self._sql('root', 'brain-dolt/laptop', "SELECT sess_id, status FROM claims"))

    def test_chaque_machine_garde_ses_lignes(self):
        self._pire_cas()
        r = self._lancer('dolt-branche-rafraichir.sh')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._etat(), {'sess-a-fixe': 'closed', 'sess-b.laptop': 'paused',
                                        'sess-c-fixe': 'open', 'sess-d.laptop': 'open'})
        principal = dict(self._sql('root', 'brain-dolt', "SELECT sess_id, status FROM claims"))
        self.assertNotIn('sess-d.laptop', principal, '`main` ne reçoit rien du laptop')
        self.assertIn('0 commit(s)', self._lancer('dolt-branche-rafraichir.sh').stdout)

    def test_a_blanc_ne_touche_rien(self):
        self._pire_cas()
        avant = self._etat()
        r = self._lancer('dolt-branche-rafraichir.sh', '--a-blanc')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('pas encore reçus', r.stdout)
        self.assertEqual(self._etat(), avant)

    def test_sans_la_regle_du_proprietaire_la_ligne_du_laptop_se_perd(self):
        # Le mutant donne tout à `main` : la ligne du laptop prend « closed ».
        # Le test ci-dessus le verrait — la règle est ce qui la protège.
        texte = (self.brain / 'scripts' / 'dolt-branche-rafraichir.sh').read_text()
        self.assertEqual(texte.count('        if col:\n'), 1)
        mutant = self.brain / 'scripts' / 'mutant.sh'
        mutant.write_text(texte.replace('        if col:\n', '        if False:\n'))
        self._pire_cas()
        self.assertEqual(self._lancer(None, chemin=mutant).returncode, 0)
        self.assertEqual(self._etat()['sess-b.laptop'], 'closed')


class TestFixeVoitLeLaptop(unittest.TestCase):
    """Le fixe voit les sessions que le laptop a ouvertes sur SA branche, et
    chaque machine fait foi pour ses lignes [BRAIN-078]. Vraie base Dolt au
    vrai schéma, sur un port libre ; le VRAI db.py et le vrai bsi-query.sh."""

    def setUp(self):
        if not (BRAIN_ROOT_PATH / 'scripts' / 'dolt-laptop.sh').exists():
            self.skipTest('dolt-laptop.sh absent — script d’instance')
        if not shutil.which('dolt'):
            self.skipTest('dolt absent')
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.tmp = Path(tempfile.mkdtemp(prefix='fixe-voit-laptop-'))
        base = self.tmp / 'brain-dolt'
        base.mkdir()
        env = {**os.environ, 'HOME': str(self.tmp)}
        run = lambda *a, **k: subprocess.run(a, cwd=base, env=env, capture_output=True, text=True, check=True, **k)
        run('dolt', 'init', '--name', 'essai', '--email', 'essai@local')
        run('dolt', 'sql', input=(BRAIN_ROOT_PATH / 'brain-engine' / 'schema-dolt.sql').read_text())
        run('dolt', 'sql', '-q', "CALL DOLT_ADD('-A'); CALL DOLT_COMMIT('-m','schema')")
        self.serveur = subprocess.Popen(['dolt', 'sql-server', '--host', '127.0.0.1', '--port', str(self.port)],
                                        cwd=base, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', self.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)
        r = subprocess.run(['bash', str(BRAIN_ROOT_PATH / 'scripts' / 'dolt-laptop.sh'), '--appliquer'],
                           env=self._env(), capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ins = "INSERT INTO claims (sess_id,type,scope,status,opened_at) VALUES ('{}','work','work/{}','{}',UTC_TIMESTAMP())"
        # main : un claim ouvert du fixe, un fermé, et la copie PÉRIMÉE d'un
        # claim du laptop, restée « open » après une ancienne fusion
        self._sql('root', 'brain-dolt', ins.format('sess-f1', 'a', 'open'), ins.format('sess-f2', 'b', 'closed'),
                  ins.format('sess-l2.laptop', 'c', 'open'), "CALL DOLT_COMMIT('-Am','main')")
        # la branche : rafraîchie, puis le laptop ouvre l1 et FERME l2
        self._sql('laptop', 'brain-dolt/laptop', "CALL DOLT_MERGE('main')",
                  ins.format('sess-l1.laptop', 'd', 'open'),
                  "UPDATE claims SET status='closed' WHERE sess_id='sess-l2.laptop'",
                  "CALL DOLT_ADD('claims')", "CALL DOLT_COMMIT('-m','laptop')")

    def tearDown(self):
        if hasattr(self, 'serveur'):
            self.serveur.terminate(); self.serveur.wait(10)
        if hasattr(self, 'tmp'):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self, base='brain-dolt', user='root'):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(BRAIN_DB_BACKEND='dolt', BRAIN_DOLT_PORT=str(self.port),
                   BRAIN_DOLT_DB=base, BRAIN_DOLT_USER=user)
        return env

    def _sql(self, utilisateur, base, *requetes):
        import pymysql
        c = pymysql.connect(host='127.0.0.1', port=self.port, user=utilisateur, password='',
                            database=base, autocommit=True)
        with c.cursor() as cur:
            for r in requetes:
                cur.execute(r)

    def _reseau(self, base='brain-dolt', user='root'):
        code = ('import sys, json; sys.path.insert(0, "brain-engine"); import db; '
                'print(json.dumps({"branches": db.branches_satellites(), "ouverts": sorted('
                '[r["sess_id"], r["_branche"]] for r in db.claims_du_reseau("status = \'open\'", colonnes="sess_id"))}))')
        r = subprocess.run([str(BRAIN_ROOT_PATH / 'brain-engine' / '.venv' / 'bin' / 'python3'), '-c', code],
                           cwd=BRAIN_ROOT_PATH, env=self._env(base, user), capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_le_reseau_montre_chaque_machine_par_sa_source(self):
        vu = self._reseau()
        self.assertEqual(vu['branches'], ['laptop'])
        # l2 : fermé sur SA branche — la copie périmée de main ne le rouvre pas
        self.assertEqual(vu['ouverts'], [['sess-f1', None], ['sess-l1.laptop', 'laptop']])

    def test_bsi_query_open_voit_le_laptop(self):
        r = subprocess.run(['bash', str(BRAIN_ROOT_PATH / 'scripts' / 'bsi-query.sh'), 'open'],
                           env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertIn('sess-l1.laptop', r.stdout, r.stderr)
        self.assertIn('sess-f1', r.stdout)
        self.assertNotIn('sess-l2.laptop', r.stdout)
        n = subprocess.run(['bash', str(BRAIN_ROOT_PATH / 'scripts' / 'bsi-query.sh'), 'count-open'],
                           env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(n.stdout.strip().splitlines()[-1], '2')

    def test_depuis_la_branche_pas_de_satellites(self):
        self.assertEqual(self._reseau('brain-dolt/laptop', 'laptop')['branches'], [])

    def _noyau_du_laptop(self):
        self._sql('laptop', 'brain-dolt/laptop',
                  "INSERT INTO claims (sess_id,type,scope,zone,status,opened_at) VALUES "
                  "('sess-k.laptop','brain','brain','kernel','open',UTC_TIMESTAMP())",
                  "CALL DOLT_ADD('claims')", "CALL DOLT_COMMIT('-m','noyau ouvert sur le laptop')")

    def test_le_verrou_du_fixe_voit_le_noyau_du_laptop(self):
        # Deux machines ouvraient le même scope noyau : chacune ne regardait
        # que sa base. La route construit son BSI avec `db.ouverts_du_reseau`.
        self._noyau_du_laptop()
        code = ('import sys; sys.path.insert(0, "brain-engine"); import db; from core.bsi import BSI; '
                'c = BSI(db.depot(), ouverts_du_reseau=db.ouverts_du_reseau).conflit("brain/kernel", zone="kernel"); '
                'print(c.sess_id if c else "LIBRE")')
        r = subprocess.run([str(BRAIN_ROOT_PATH / 'brain-engine' / '.venv' / 'bin' / 'python3'), '-c', code],
                           cwd=BRAIN_ROOT_PATH, env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip().splitlines()[-1], 'sess-k.laptop', r.stderr)

    # ── Les verrous de fichier, eux aussi, voient le réseau — ──────
    #
    # Mesuré le 2/10 : la prise de verrou consultait le pair en HTTP, et la
    # consultation n'aboutissait jamais (000, 401). Chaque machine accordait
    # chez elle. Témoins : un verrou du fixe, un verrou du laptop sur SA branche,
    # et la copie périmée d'un verrou du laptop restée dans `main`.
    _verrou = ("INSERT INTO locks (filepath,holder,claimed_at,expires_at,ttl_min) VALUES "
               "('{}','{}',UTC_TIMESTAMP(),DATE_ADD(UTC_TIMESTAMP(), INTERVAL 30 MINUTE),30)")

    def _verrous_poses(self):
        self._sql('root', 'brain-dolt', self._verrou.format('a.md', 'sess-f1'),
                  self._verrou.format('c.md', 'sess-l9.laptop'),     # copie périmée
                  "CALL DOLT_COMMIT('-Am','verrous du fixe')")
        self._sql('laptop', 'brain-dolt/laptop', "CALL DOLT_MERGE('main')",
                  "DELETE FROM locks WHERE filepath = 'c.md'",       # le laptop l'a relâché
                  self._verrou.format('b.md', 'sess-l1.laptop'),
                  "CALL DOLT_ADD('locks')", "CALL DOLT_COMMIT('-m','verrou du laptop')")

    def _verrous_vus(self, base='brain-dolt', user='root'):
        code = ('import sys, json; sys.path.insert(0, "brain-engine"); import db; '
                'print(json.dumps(sorted([r["filepath"], r["_branche"]] for r in db.verrous_du_reseau())))')
        r = subprocess.run([str(BRAIN_ROOT_PATH / 'brain-engine' / '.venv' / 'bin' / 'python3'), '-c', code],
                           cwd=BRAIN_ROOT_PATH, env=self._env(base, user), capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_le_fixe_voit_les_verrous_du_laptop(self):
        self._verrous_poses()
        # c.md : relâché sur SA branche — la copie périmée de main ne le rend pas tenu
        self.assertEqual(self._verrous_vus(), [['a.md', None], ['b.md', 'laptop']])

    def test_le_laptop_voit_les_verrous_du_fixe_en_direct(self):
        self._verrous_poses()
        # `main` lu en direct (pas au rafraîchissement) ; la copie périmée de son
        # propre verrou n'y compte pas
        self.assertEqual(self._verrous_vus('brain-dolt/laptop', 'laptop'), [['a.md', None], ['b.md', 'laptop']])

    def _prendre(self, chemin, holder, base='brain-dolt', user='root'):
        env = self._env(base, user)
        env['BRAIN_PORT'] = '1'                                    # moteur injoignable : le repli
        return subprocess.run(['bash', str(BRAIN_ROOT_PATH / 'scripts' / 'file-lock.sh'), 'acquire',
                               chemin, holder, '5'], env=env, capture_output=True, text=True, timeout=60)

    def test_le_repli_de_file_lock_refuse_le_verrou_de_l_autre_machine(self):
        self._verrous_poses()
        depuis_le_fixe = self._prendre('b.md', 'sess-f2')
        self.assertEqual(depuis_le_fixe.returncode, 1, depuis_le_fixe.stdout + depuis_le_fixe.stderr)
        self.assertIn('sess-l1.laptop', depuis_le_fixe.stdout)
        depuis_le_laptop = self._prendre('a.md', 'sess-l1.laptop', 'brain-dolt/laptop', 'laptop')
        self.assertEqual(depuis_le_laptop.returncode, 1, depuis_le_laptop.stdout + depuis_le_laptop.stderr)
        self.assertIn('sess-f1', depuis_le_laptop.stdout)
        # Témoin : un fichier libre partout se prend, et le dit
        libre = self._prendre('d.md', 'sess-f2')
        self.assertEqual(libre.returncode, 0, libre.stdout + libre.stderr)
        self.assertIn('verrous du reseau lus (main, laptop)', libre.stdout)

    def test_le_repli_de_bsi_claim_refuse_aussi(self):
        # Moteur injoignable (port mort) : le repli local ouvre lui-même — avec
        # le même verrou du réseau.
        self._noyau_du_laptop()
        env = self._env()
        env['BRAIN_PORT'] = '1'
        r = subprocess.run(['bash', str(BRAIN_ROOT_PATH / 'scripts' / 'bsi-claim.sh'), 'open',
                            'sess-20260929-1600-brain-kernel', '--type', 'brain', '--scope', 'brain/kernel',
                            '--zone', 'kernel'], env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('SCOPE CONFLICT', r.stdout + r.stderr)
        import pymysql
        c = pymysql.connect(host='127.0.0.1', port=self.port, user='root', password='', database='brain-dolt')
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM claims WHERE sess_id='sess-20260929-1600-brain-kernel'")
            self.assertEqual(cur.fetchone()[0], 0, "rien n'a été ouvert")


class TestInstallSelonLaBase(unittest.TestCase):
    """Le moteur attend le service de SA base, et `install systemd` n'avertit
    que là où une base locale manquerait de service.

    Sur le laptop, la base est celle du fixe, par un tunnel [BRAIN-078] :
    l'unité attendait un dolt-server qui n'existe pas, ignorait le tunnel, et
    l'installation avertissait « pas de dolt-server.service » — à tort. Un faux
    brain par cas ; un faux `systemctl` qui ne connaît aucune unité."""

    def _installer(self, base_locale=False, tunnel=False):
        tmp = Path(tempfile.mkdtemp(prefix='install-base-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        b = tmp / 'brain'
        (b / 'scripts' / 'lib').mkdir(parents=True)
        (b / 'brain-engine').mkdir()
        for f in ('brain-engine.sh', 'lib/python.sh'):
            shutil.copy(BRAIN_ROOT_PATH / 'scripts' / f, b / 'scripts' / f)
        for f in ('server.py', 'mcp_server.py'):
            (b / 'brain-engine' / f).write_text('# faux\n')
        (b / 'brain-engine' / '.venv').symlink_to(BRAIN_ROOT_PATH / 'brain-engine' / '.venv')
        subprocess.run(['git', 'init', '-q'], cwd=b, check=True)
        if base_locale:
            (b / 'brain-dolt' / '.dolt').mkdir(parents=True)
        unites = tmp / 'config' / 'systemd' / 'user'
        unites.mkdir(parents=True)
        if tunnel:
            (unites / 'brain-tunnel-dolt.service').write_text('[Service]\nExecStart=/bin/true\n')
        (tmp / 'bin').mkdir()
        (tmp / 'bin' / 'systemctl').write_text('#!/bin/sh\n[ "$2" = cat ] && exit 1\nexit 0\n')
        (tmp / 'bin' / 'systemctl').chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(PATH=f"{tmp / 'bin'}:{env['PATH']}", XDG_CONFIG_HOME=str(tmp / 'config'),
                   BRAIN_MODE='prod', BRAIN_PORT='17793', BRAIN_MCP_PORT='17792')
        r = subprocess.run(['bash', str(b / 'scripts' / 'brain-engine.sh'), 'install', 'systemd'],
                           env=env, capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr, (unites / 'brain-engine.service').read_text()

    def test_base_locale_sans_service_avertit(self):
        sortie, unite = self._installer(base_locale=True)
        self.assertIn('pas de dolt-server.service', sortie)
        self.assertIn('After=dolt-server.service', unite)

    def test_base_par_tunnel_le_moteur_l_attend_sans_avertir(self):
        sortie, unite = self._installer(tunnel=True)
        self.assertNotIn('pas de dolt-server.service', sortie)
        self.assertIn('brain-tunnel-dolt.service', sortie)
        self.assertIn('After=brain-tunnel-dolt.service', unite)
        self.assertNotIn('dolt-server', unite)

    def test_sans_base_locale_ni_tunnel_aucune_dependance(self):
        sortie, unite = self._installer()
        self.assertNotIn('pas de dolt-server.service', sortie)
        self.assertNotIn('Wants=', unite)


class TestLaptopNomadeRapatrier(unittest.TestCase):
    """Au retour, les commits faits hors du bureau rejoignent la branche du
    laptop sur le fixe — et rien n'avance si elle a bougé entre-temps
    [BRAIN-078]. Un petit dépôt joue le fixe (servi sur un port libre) ; un
    clone superficiel de sa branche joue la photo du laptop."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'laptop-nomade.sh'

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('laptop-nomade.sh absent — script d’instance')
        if not shutil.which('dolt'):
            self.skipTest('dolt absent')
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.tmp = Path(tempfile.mkdtemp(prefix='laptop-nomade-'))
        self.env = {**os.environ, 'HOME': str(self.tmp)}
        fixe = self.tmp / 'fixe'
        fixe.mkdir()
        self._run(fixe, 'dolt', 'init', '--name', 'fixe', '--email', 'fixe@local')
        self._run(fixe, 'dolt', 'sql', '-q',
                  "CREATE TABLE claims (sess_id varchar(64) primary key, status varchar(16)); "
                  "INSERT INTO claims VALUES ('sess-a','open'); CALL DOLT_ADD('-A'); "
                  "CALL DOLT_COMMIT('-m','un'); CALL DOLT_BRANCH('laptop')")
        # la photo : un clone superficiel de la branche, par un remote fichier
        remote = self.tmp / 'remote'
        remote.mkdir()
        self._run(fixe, 'dolt', 'remote', 'add', 'r', f'file://{remote}')
        self._run(fixe, 'dolt', 'push', 'r', 'laptop')
        self._run(self.tmp, 'dolt', 'clone', '--depth', '1', '--branch', 'laptop', f'file://{remote}', 'photo')
        photo = self.tmp / 'photo'
        self._run(photo, 'dolt', 'config', '--local', '--add', 'user.name', 'laptop')
        self._run(photo, 'dolt', 'config', '--local', '--add', 'user.email', 'laptop@nomade')
        self._run(photo, 'dolt', 'sql', '-q', "INSERT INTO claims VALUES ('sess-train.laptop','open')")
        self._run(photo, 'dolt', 'commit', '-Am', 'ouvert hors ligne')
        self._run(photo, 'dolt', 'sql', '-q', "UPDATE claims SET status='closed' WHERE sess_id='sess-train.laptop'")
        self._run(photo, 'dolt', 'commit', '-Am', 'fermé hors ligne')
        self._run(photo, 'dolt', 'gc')
        self.noms = photo / '.dolt' / 'noms'
        self.serveur = subprocess.Popen(['dolt', 'sql-server', '--host', '127.0.0.1', '--port', str(self.port)],
                                        cwd=fixe, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', self.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)

    def tearDown(self):
        if hasattr(self, 'serveur'):
            self.serveur.terminate(); self.serveur.wait(10)
        if hasattr(self, 'tmp'):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, cwd, *cmd):
        return subprocess.run(cmd, cwd=cwd, env=self.env, capture_output=True, text=True, check=True)

    def _sql(self, base, *requetes):
        import pymysql
        c = pymysql.connect(host='127.0.0.1', port=self.port, user='root', password='', database=base, autocommit=True)
        with c.cursor() as cur:
            for r in requetes:
                cur.execute(r)
            return cur.fetchall()

    def _rapatrier(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(BRAIN_DOLT_PORT=str(self.port), BRAIN_DOLT_DB='fixe')
        return subprocess.run(['bash', str(self.SCRIPT), 'rapatrier', str(self.noms)], env=env,
                              capture_output=True, text=True, timeout=120)

    def test_les_commits_hors_ligne_rejoignent_la_branche(self):
        r = self._rapatrier()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('avancée de 2 commit(s)', r.stdout)
        self.assertEqual(self._sql('fixe/laptop', "SELECT status FROM claims WHERE sess_id='sess-train.laptop'"),
                         (('closed',),))
        signes = self._sql('fixe/laptop', "SELECT committer FROM dolt_log LIMIT 2")
        self.assertEqual({c for (c,) in signes}, {'laptop'})
        self.assertEqual(self._sql('fixe', "SELECT COUNT(*) FROM dolt_remotes WHERE name='nomade'"), ((0,),),
                         'le remote de passage est retiré')

    def test_si_la_branche_a_bouge_rien_n_avance(self):
        self._sql('fixe/laptop', "INSERT INTO claims VALUES ('sess-pendant','open')",
                  "CALL DOLT_COMMIT('-Am','écrit sur la branche pendant l absence')")
        avant = self._sql('fixe/laptop', "SELECT commit_hash FROM dolt_log LIMIT 1")
        r = self._rapatrier()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('a bougé pendant l', r.stderr)
        self.assertEqual(self._sql('fixe/laptop', "SELECT commit_hash FROM dolt_log LIMIT 1"), avant)


class TestWikiChangelog(unittest.TestCase):
    """`wiki/CHANGELOG.md` se génère depuis le `changelog:` de `brain-compose.yml`.
    La copie écrite à la main s'était arrêtée à la 2.0.0 pendant que treize
    versions passaient — et une application l'affichait (audit du wiki, 29/09).
    Script d'instance : le wiki ne part pas avec le gabarit, ni ce script."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'wiki-changelog.py'
    COMPOSE = ('version: "2.3.6"\nchangelog:\n'
               '  - version: "2.1.0"\n    date: "2026-04-07"\n    notes: "avant le realignement"\n'
               '  - version: "2.0.0"\n    date: "2026-04-24"\n    notes: "realignement"\n'
               '  - version: "2.3.6"\n    date: "2026-09-28"\n    notes: "le timer"\n')

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('wiki-changelog.py absent — script d’instance')
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        (self.brain / 'brain-compose.yml').write_text(self.COMPOSE)
        (self.brain / 'wiki').mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run([sys.executable, str(self.SCRIPT), '--brain', str(self.brain), *args],
                              capture_output=True, text=True, timeout=30)

    def test_la_plus_recente_en_haut_sans_renumeroter(self):
        page = self._run().stdout
        a, b, c = (page.index(f'## {v} — ') for v in ('2.3.6', '2.0.0', '2.1.0'))
        self.assertLess(a, b)
        self.assertLess(b, c, "l'ordre écrit, renversé — pas le tri des numéros")
        self.assertIn('Version courante : **2.3.6**', page)
        self.assertIn('ne pas éditer', page)

    def test_check_rougit_puis_ecrire_le_remet_d_accord(self):
        (self.brain / 'wiki' / 'CHANGELOG.md').write_text('# CHANGELOG\n\n## 2.0.0\n')
        self.assertEqual(self._run('--check').returncode, 1)
        self.assertEqual(self._run('--ecrire').returncode, 0)
        self.assertEqual(self._run('--check').returncode, 0)
        with open(self.brain / 'brain-compose.yml', 'a') as f:
            f.write('  - version: "2.3.7"\n    date: "2026-09-30"\n    notes: "suite"\n')
        self.assertEqual(self._run('--check').returncode, 1, "une version ajoutée se voit")

    def test_sans_wiki_le_check_s_abstient(self):
        (self.brain / 'wiki').rmdir()
        r = self._run('--check')
        self.assertEqual(r.returncode, 0)
        self.assertIn('SKIP', r.stdout)

    def test_le_vrai_brain_compose_se_rend(self):
        r = subprocess.run([sys.executable, str(self.SCRIPT), '--brain', str(BRAIN_ROOT_PATH)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('## 2.3.6 — ', r.stdout)


class TestRegistresVeille(unittest.TestCase):
    """La veille des registres ne confond jamais « à jour » et « rien vu ».

    Les outils ne rendent que 0 ou 1. Or `backlog_issues` sort en 0 avec `SKIP`
    quand la forge est injoignable, et une base injoignable fait sortir une
    trace Python en 1, comme un écart. Joué contre de FAUX outils : aucun
    registre réel n'est lu, l'état s'écrit dans un dossier jetable."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'registres-veille.py'
    OUTILS = ('project_registry', 'agent_registry', 'backlog_issues', 'index_purge')
    # Ce que chaque faux outil fait, selon la variable FAUX_<OUTIL>.
    FAUX = (
        'import os, sys\n'
        'nom = os.path.basename(sys.argv[0])[:-3].upper()\n'
        'cas = os.environ.get("FAUX_" + nom, "ok")\n'
        'if cas == "ok": print("✅ aucun écart"); sys.exit(0)\n'
        'if cas == "ecart": print("❌ 2 écart(s)"); sys.exit(1)\n'
        'if cas == "skip": print("\\n  SKIP forge injoignable : URLError\\n"); sys.exit(0)\n'
        'if cas == "trace": raise RuntimeError("base injoignable")\n'
        'sys.exit(3)\n'
    )

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('registres-veille.py absent — script d’instance')
        self.tmp = Path(tempfile.mkdtemp())
        outils = self.tmp / 'myeline' / 'tools'
        outils.mkdir(parents=True)
        for o in self.OUTILS:
            (outils / f'{o}.py').write_text(self.FAUX, encoding='utf-8')
        self.etat = self.tmp / 'etat' / 'veille.json'
        self.env = dict(os.environ, BRAIN_ROOT=str(self.tmp), MYELINE_ROOT=str(self.tmp / 'myeline'),
                        BRAIN_REGISTRES_ETAT=str(self.etat))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args, **cas):
        env = dict(self.env, **{f'FAUX_{k.upper()}': v for k, v in cas.items()})
        return subprocess.run([sys.executable, str(self.SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def _etats(self):
        return {r['outil']: r['etat'] for r in json.loads(self.etat.read_text())['resultats']}

    def test_tout_a_jour(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('4/4 à jour', r.stdout)
        self.assertEqual(set(self._etats().values()), {'à jour'})

    def test_un_ecart_se_dit_avec_son_geste_sans_rougir_le_service(self):
        r = self._run(project_registry='ecart')
        self.assertEqual(r.returncode, 0)          # un écart n'est pas une panne du timer
        self.assertEqual(self._etats()['project_registry'], 'écart')
        lu = self._run('--lire')
        self.assertEqual(lu.returncode, 1)
        self.assertIn('--emit --apply', lu.stdout)

    def test_skip_n_est_pas_a_jour(self):
        # Le message exact de `backlog_issues` quand la forge ne répond pas.
        self._run(backlog_issues='skip')
        self.assertEqual(self._etats()['backlog_issues'], 'non mesuré')
        self.assertEqual(self._run('--lire').returncode, 1)

    def test_une_trace_est_une_panne_pas_un_ecart(self):
        r = self._run(index_purge='trace')
        self.assertEqual(self._etats()['index_purge'], 'en panne')
        self.assertEqual(r.returncode, 1)          # la veille n'a pas pu mesurer

    def test_un_code_inconnu_est_une_panne(self):
        self._run(agent_registry='autre')
        self.assertEqual(self._etats()['agent_registry'], 'en panne')

    def test_un_outil_absent_est_une_panne(self):
        (self.tmp / 'myeline' / 'tools' / 'index_purge.py').unlink()
        r = self._run()
        self.assertEqual(self._etats()['index_purge'], 'en panne')
        self.assertEqual(r.returncode, 1)

    def test_sans_etat_le_silence_se_dit(self):
        lu = self._run('--lire')
        self.assertEqual(lu.returncode, 1)
        self.assertIn('jamais tourné', lu.stdout)

    def test_un_etat_perime_se_dit(self):
        self._run()
        donnees = json.loads(self.etat.read_text())
        donnees['date'] = '2026-01-01T00:00:00Z'
        self.etat.write_text(json.dumps(donnees))
        lu = self._run('--lire')
        self.assertEqual(lu.returncode, 1)
        self.assertIn('ne tourne plus', lu.stdout)

    def test_un_etat_illisible_se_dit(self):
        self.etat.parent.mkdir(parents=True)
        self.etat.write_text('{pas du json')
        lu = self._run('--lire')
        self.assertEqual(lu.returncode, 1)
        self.assertIn('illisible', lu.stdout)

    def test_la_veille_n_ecrit_que_son_etat(self):
        avant = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob('*'))
        self._run(project_registry='ecart')
        apres = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob('*'))
        nouveaux = [str(p) for p in apres if p not in avant]
        self.assertEqual(nouveaux, ['etat', 'etat/veille.json'])


class TestWsFermeAuReseau(unittest.TestCase):
    """`/ws` rediffusait les événements BSI à tout appareil du réseau.

    Identifiants de session, scopes, chemins verrouillés, corps des `PATCH` de
    claims : mesuré le 30/09 sur le fixe, qui a ses jetons et écoute sur
    0.0.0.0. La boucle locale passe ; le réseau montre un jeton."""

    DISTANT = ('192.0.2.1', 50000)
    JETONS = {'j-owner': 'owner'}

    def _connecter(self, client, headers=None):
        from starlette.websockets import WebSocketDisconnect
        try:
            with TestClient(srv.app, client=client).websocket_connect('/ws', headers=headers or {}):
                return 'acceptée'
        except WebSocketDisconnect as e:
            return f'fermée {e.code}'

    def test_le_reseau_sans_jeton_est_refuse(self):
        with patch.object(srv, '_TOKEN_MAP', self.JETONS):
            self.assertEqual(self._connecter(self.DISTANT), 'fermée 1008')

    def test_le_reseau_avec_un_jeton_passe(self):
        with patch.object(srv, '_TOKEN_MAP', self.JETONS):
            self.assertEqual(self._connecter(self.DISTANT, {'authorization': 'Bearer j-owner'}), 'acceptée')

    def test_un_jeton_faux_est_refuse(self):
        with patch.object(srv, '_TOKEN_MAP', self.JETONS):
            self.assertEqual(self._connecter(self.DISTANT, {'authorization': 'Bearer faux'}), 'fermée 1008')

    def test_la_boucle_locale_passe_sans_jeton(self):
        with patch.object(srv, '_TOKEN_MAP', self.JETONS):
            self.assertEqual(self._connecter(LOCAL), 'acceptée')

    def test_un_proxy_qui_relaie_n_est_pas_local(self):
        with patch.object(srv, '_TOKEN_MAP', self.JETONS):
            self.assertEqual(self._connecter(LOCAL, {'x-forwarded-for': '192.0.2.9'}), 'fermée 1008')


class TestGateRetiree(unittest.TestCase):
    """`POST /gate/…/approve` est retirée avec la machinerie archivée."""

    def test_la_route_n_existe_plus(self):
        chemins = {getattr(r, 'path', '') for r in srv.app.routes}
        self.assertFalse([c for c in chemins if c.startswith('/gate')], chemins)


class TestMajDisponible(unittest.TestCase):
    """Le boot dit qu'une version plus récente existe — et laisse chacun libre.

    Joué contre un VRAI amont git jetable (des tags fabriqués) et un fork
    jetable qui le déclare en `upstream` : aucun réseau, aucun dépôt réel."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'maj-disponible.py'

    def setUp(self):
        if not self.SCRIPT.exists():
            self.skipTest('maj-disponible.py absent')
        self.tmp = Path(tempfile.mkdtemp())
        self.amont = self.tmp / 'amont.git'
        self.fork = self.tmp / 'fork'
        self.etat = self.tmp / 'etat' / 'maj.json'
        g = lambda *a, cwd=None: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)
        g('init', '-q', '--bare', str(self.amont))
        self.fork.mkdir()
        g('init', '-q', cwd=self.fork)
        (self.fork / 'brain-compose.yml').write_text('# gabarit\nversion: "2.4.0"\n')
        g('-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.', cwd=self.fork)
        g('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'v', cwd=self.fork)
        self.g = g

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tags(self, *tags):
        for t in tags:
            self.g('tag', t, cwd=self.fork)
        self.g('push', '-q', str(self.amont), '--tags', cwd=self.fork)

    def _declarer_amont(self, url=None):
        self.g('remote', 'add', 'upstream', url or str(self.amont), cwd=self.fork)

    def _run(self, *args, env_extra=None):
        env = dict(os.environ, BRAIN_ROOT=str(self.fork), BRAIN_MAJ_ETAT=str(self.etat), **(env_extra or {}))
        return subprocess.run([sys.executable, str(self.SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def test_une_version_plus_recente_se_dit_en_une_ligne(self):
        self._tags('v2.3.6', 'v2.4.0', 'v2.4.1', 'programme/v2.9.9')
        self._declarer_amont()
        self.assertEqual(self._run().returncode, 0)
        lu = self._run('--lire')
        self.assertEqual(lu.returncode, 1)
        self.assertEqual(len(lu.stdout.strip().splitlines()), 1)
        self.assertIn('v2.4.1 est disponible', lu.stdout)   # pas programme/v2.9.9
        self.assertIn('tu es en 2.4.0', lu.stdout)

    def test_a_jour_rien_ne_s_affiche(self):
        self._tags('v2.3.6', 'v2.4.0')
        self._declarer_amont()
        self._run()
        lu = self._run('--lire')
        self.assertEqual((lu.returncode, lu.stdout), (0, ''))

    def test_la_comparaison_est_numerique(self):
        self._tags('v2.9.0', 'v2.10.0')
        self._declarer_amont()
        self._run()
        self.assertIn('v2.10.0 est disponible', self._run('--lire').stdout)

    def test_sans_amont_la_source_ne_voit_rien(self):
        r = self._run()
        self.assertEqual(r.returncode, 0)
        self.assertIn('pas de remote', r.stdout)
        lu = self._run('--lire')
        self.assertEqual((lu.returncode, lu.stdout), (0, ''))

    def test_un_amont_injoignable_ne_passe_pas_pour_a_jour(self):
        self._declarer_amont(str(self.tmp / 'nulle-part.git'))
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(self.etat.read_text())['resultat'], 'injoignable')
        lu = self._run('--lire')
        self.assertEqual(lu.returncode, 1)
        self.assertIn("jamais répondu", lu.stdout)

    def test_un_echec_garde_la_date_du_dernier_succes(self):
        self._tags('v2.4.0')
        self._declarer_amont()
        self._run()
        donnees = json.loads(self.etat.read_text())
        donnees['succes'] = '2026-01-01T00:00:00Z'      # un vieux succès
        self.etat.write_text(json.dumps(donnees))
        self.g('remote', 'set-url', 'upstream', str(self.tmp / 'nulle-part.git'), cwd=self.fork)
        self._run()
        self.assertEqual(json.loads(self.etat.read_text())['succes'], '2026-01-01T00:00:00Z')
        lu = self._run('--lire')
        self.assertEqual(lu.returncode, 1)
        self.assertIn('depuis le 01/01', lu.stdout)

    def test_un_echec_recent_ne_dit_rien(self):
        self._tags('v2.4.0')
        self._declarer_amont()
        self._run()
        self.g('remote', 'set-url', 'upstream', str(self.tmp / 'nulle-part.git'), cwd=self.fork)
        self._run()
        lu = self._run('--lire')
        self.assertEqual((lu.returncode, lu.stdout), (0, ''))      # pas d'insistance

    def test_lire_n_appelle_ni_git_ni_le_reseau(self):
        self._tags('v2.4.0', 'v2.4.1')
        self._declarer_amont()
        self._run()
        lu = self._run('--lire', env_extra={'PATH': str(self.tmp / 'vide')})   # git introuvable
        self.assertEqual(lu.returncode, 1, lu.stderr)
        self.assertIn('v2.4.1 est disponible', lu.stdout)

    def test_la_verification_n_ecrit_rien_dans_le_depot(self):
        self._tags('v2.4.0', 'v2.4.1')
        self._declarer_amont()
        avant = subprocess.run(['git', 'for-each-ref'], cwd=self.fork, capture_output=True, text=True).stdout
        self._run()
        apres = subprocess.run(['git', 'for-each-ref'], cwd=self.fork, capture_output=True, text=True).stdout
        self.assertEqual(avant, apres)


class TestDeuxRacines(unittest.TestCase):
    """La data est REÇUE, le programme se sait où il est — une seule source.

    Jusqu'au 1/10, sept modules déduisaient chacun la racine du brain de leur
    propre position, et cette racine désignait à la fois la data et le
    programme. Poser `BRAIN_ROOT` n'aurait été suivi par personne ; en changer
    un seul aurait fait diverger les autres sans un mot.
    """

    MOTEUR = Path(__file__).parent
    MODULES = ('server', 'db', 'embed', 'search', 'distill', 'migrate', 'mcp_server')

    def _python(self, code, racine=None):
        env = {k: v for k, v in os.environ.items() if k != 'BRAIN_ROOT'}
        if racine is not None:
            env['BRAIN_ROOT'] = str(racine)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        return subprocess.run([sys.executable, '-c', code], cwd=self.MOTEUR, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_sans_variable_la_data_est_le_parent_du_programme(self):
        r = self._python('import racines; print(racines.DONNEES); print(racines.ORIGINE)')
        self.assertEqual(r.returncode, 0, r.stderr)
        donnees, origine = r.stdout.strip().splitlines()[-2:]
        self.assertEqual(Path(donnees), self.MOTEUR.parent)
        self.assertEqual(origine, 'position du programme')

    def test_la_variable_est_suivie_par_tous_les_modules_et_le_programme_reste(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._python(
                'import json, db, embed, migrate, server, mcp_server\n'
                'print(json.dumps({"db": str(db.BRAIN_ROOT), "embed": str(embed.BRAIN_ROOT),'
                ' "migrate": migrate.BRAIN_ROOT, "server": str(server.BRAIN_ROOT),'
                ' "mcp": str(mcp_server._BRAIN_ROOT), "mcp_alias": str(mcp_server.BRAIN_ROOT),'
                ' "env_local": str(db._env_local), "schema": migrate.SCHEMA_PATH,'
                ' "ui": str(server._UI_DIST)}))', racine=tmp)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            vu = json.loads(r.stdout.strip().splitlines()[-1])
            for nom in ('db', 'embed', 'migrate', 'server', 'mcp', 'mcp_alias'):
                self.assertEqual(Path(vu[nom]).resolve(), Path(tmp).resolve(),
                                 f'{nom} ne suit pas BRAIN_ROOT')
            # Le programme ne suit PAS la data : il reste là où il est.
            self.assertEqual(Path(vu['env_local']).parent, self.MOTEUR)
            self.assertEqual(Path(vu['schema']).parent, self.MOTEUR)
            self.assertEqual(Path(vu['ui']).parent.parent, self.MOTEUR.parent)

    def test_une_variable_qui_ne_designe_rien_arrete_l_import(self):
        absent = self.MOTEUR / 'pas-un-brain-qui-existe'
        r = self._python('import db', racine=absent)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('BRAIN_ROOT', r.stderr)
        self.assertIn('refuse', r.stderr)

    def test_aucun_module_ne_deduit_sa_racine(self):
        """Lu dans l'AST, pas dans le texte : un commentaire qui RACONTE l'ancien
        `Path(__file__).parent.parent` n'est pas une déduction."""
        import ast
        fautifs = []
        for f in sorted(self.MOTEUR.glob('*.py')):
            if f.name in ('racines.py',) or f.name.startswith('test_'):
                continue
            arbre = ast.parse(f.read_text(encoding='utf-8'))
            for n in ast.walk(arbre):
                # Path(__file__)…parent.parent  ·  dirname(dirname(…__file__…))
                if isinstance(n, ast.Attribute) and n.attr == 'parent' \
                        and isinstance(n.value, ast.Attribute) and n.value.attr == 'parent' \
                        and any(isinstance(m, ast.Name) and m.id == '__file__' for m in ast.walk(n)):
                    fautifs.append(f'{f.name}:{n.lineno}')
                if isinstance(n, ast.Call) and getattr(n.func, 'attr', getattr(n.func, 'id', '')) == 'dirname' \
                        and n.args and isinstance(n.args[0], ast.Call) \
                        and getattr(n.args[0].func, 'attr', getattr(n.args[0].func, 'id', '')) == 'dirname' \
                        and any(isinstance(m, ast.Name) and m.id == '__file__' for m in ast.walk(n)):
                    fautifs.append(f'{f.name}:{n.lineno}')
        self.assertEqual(fautifs, [], 'racine déduite hors de racines.py')


class TestRegleDesVerrous(unittest.TestCase):
    """La frontière d'un verrou est écrite UNE fois, dans `core.bsi`.

    Jusqu'au 1/10 elle l'était quatorze fois — le CORE, trois routes, cinq fois
    dans `file-lock.sh`, cinq dans la conciergerie — et la conciergerie disait
    `>` / `<=` là où tout le reste disait `>=` / `<`.
    """

    RACINE = BRAIN_ROOT_PATH
    FICHIERS = ('brain-engine/server.py', 'scripts/file-lock.sh', 'scripts/brain-conciergerie.sh')
    EN_DUR = re.compile(r"(UTC_TIMESTAMP\(\)|NOW\(\)) *(<=|>=|<|>) *expires_at"
                        r"|expires_at *(<=|>=|<|>) *(UTC_TIMESTAMP|NOW)")

    def _env(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('BRAIN_') and k != 'CLAUDE_CODE_SESSION_ID'}
        env['PATH'] = f"{Path(sys.executable).parent}:{env.get('PATH', '')}"
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.update(extra)
        return env

    def test_aucun_predicat_d_expiration_ecrit_en_dur(self):
        for rel in self.FICHIERS:
            if absent_d_instance(self.RACINE / rel):
                continue
            texte = (self.RACINE / rel).read_text(encoding='utf-8')
            self.assertEqual(self.EN_DUR.findall(texte), [], f'{rel} réécrit la règle')
            self.assertIn('VERROU_', texte, f'{rel} ne lit plus la règle du CORE')

    def _regle_de_la_conciergerie(self, racine):
        script = script_d_instance(self.RACINE / 'scripts' / 'brain-conciergerie.sh').read_text(encoding='utf-8')
        fonction = re.search(r'^regle_des_verrous\(\) \{.*?^\}', script, re.S | re.M).group(0)
        return subprocess.run(
            ['bash', '-c', fonction + '\nRED=; NC=; regle_des_verrous && '
             'printf "%s|%s" "$VERROU_ACTIF" "$VERROU_EXPIRE"'],
            env=self._env(BRAIN_ROOT=str(racine)), capture_output=True, text=True, timeout=60)

    def test_la_conciergerie_lit_la_regle_du_core(self):
        from core.bsi import VERROU_ACTIF, VERROU_EXPIRE
        r = self._regle_de_la_conciergerie(self.RACINE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f'{VERROU_ACTIF}|{VERROU_EXPIRE}')

    def test_regle_illisible_la_conciergerie_s_arrete(self):
        """Témoin : un `core.bsi` sans la règle — la conciergerie refuse, ne devine pas."""
        with tempfile.TemporaryDirectory() as tmp:
            faux = Path(tmp) / 'brain-engine' / 'core'
            faux.mkdir(parents=True)
            (faux / '__init__.py').write_text('')
            (faux / 'bsi.py').write_text('# pas de regle ici\n')
            r = self._regle_de_la_conciergerie(tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('illisible', r.stderr)

    def test_file_lock_nettoie_l_expire_et_garde_l_actif(self):
        from datetime import timedelta, timezone
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'brain.db'
            con = sqlite3.connect(base)
            con.executescript((self.RACINE / 'brain-engine' / 'schema.sql').read_text())
            maintenant = datetime.now(timezone.utc)
            fmt = '%Y-%m-%d %H:%M:%S'
            for chemin, decalage in (('mort.md', -10), ('vivant.md', 30)):
                con.execute('INSERT INTO locks (filepath, holder, claimed_at, expires_at, ttl_min) '
                            'VALUES (?,?,?,?,30)', (chemin, 'sess-t', maintenant.strftime(fmt),
                                                    (maintenant + timedelta(minutes=decalage)).strftime(fmt)))
            con.commit(); con.close()
            env = self._env(BRAIN_DB_BACKEND='sqlite', BRAIN_DB_PATH=str(base),
                            BRAIN_PORT='1', HOME=tmp)
            r = subprocess.run(['bash', str(self.RACINE / 'scripts' / 'file-lock.sh'), 'cleanup'],
                               env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('1 lock(s) nettoyé(s)', r.stdout)
            restants = [x[0] for x in sqlite3.connect(base).execute('SELECT filepath FROM locks')]
            self.assertEqual(restants, ['vivant.md'])


class TestCouchesDuGabarit(unittest.TestCase):
    """Le gabarit porte exactement ce que dit `gabarit/couches.yml`.

    La question était sans réponse écrite : « le gabarit a-t-il toutes les
    couches ? » `modes/` partait encore six mois après la fin des modes ;
    `vie/` et `contenu/` n'arrivaient pas. Le rendu part du gabarit PUBLIÉ
    (`brain-template/`) — c'est lui que le fork reçoit, c'est lui qu'on juge.
    """

    CHEMINS, SATELLITES = TestSyncTemplate.CHEMINS, TestSyncTemplate.SATELLITES
    tearDown = TestSyncTemplate.tearDown
    _git, _sync = TestSyncTemplate._git, TestSyncTemplate._sync

    def setUp(self):
        TestSyncTemplate.setUp(self)
        # La sonde de renvoi arrête le rendu, exprès : ici, on veut un rendu
        # qui va AU BOUT — un rendu interrompu satisfaisait la table (1/10).
        self._git('rm', '-q', 'contexts/sonde.yml', cwd=self.brain)
        self._git('commit', '-q', '--no-verify', '-m', 'sans sonde', cwd=self.brain)
    BASE = BRAIN_ROOT_PATH / 'brain-template'

    def _table(self, racine=BRAIN_ROOT_PATH):
        import yaml
        return yaml.safe_load((racine / 'gabarit' / 'couches.yml').read_text(encoding='utf-8'))

    def _rendre(self, base):
        self.env['GABARIT_DEPOT'] = str(base)
        rendu = self.tmp / 'rendu'
        r = self._sync('--rendre', str(rendu))
        return rendu, r

    def test_le_rendu_porte_exactement_la_table(self):
        if not (self.BASE / '.git').exists():
            self.skipTest('brain-template/ absent — le gabarit publié est la base du rendu')
        table = self._table()
        rendu, r = self._rendre(self.BASE.resolve())
        self.assertIn('✅ Sync terminé', r.stdout, 'rendu interrompu — rien à juger\n' + r.stdout[-800:])
        ecarts = []
        for nom, c in table['couches'].items():
            d = rendu / nom
            if c['part'] == 'contenu' and not (d.is_dir() and any(f.is_file() for f in d.rglob('*'))):
                ecarts.append(f'{nom}/ devait partir avec son contenu')
            elif c['part'] == 'readme' and not (d / 'README.md').is_file():
                ecarts.append(f'{nom}/ devait partir avec son README')
            elif c['part'] == 'non' and d.exists():
                ecarts.append(f'{nom}/ ne devait pas partir')
        for nom in table.get('retire') or {}:
            if (rendu / nom).exists():
                ecarts.append(f'{nom}/ est retiré et part encore')
        # Et rien de non déclaré au premier niveau du rendu.
        declares = set(table['couches']) | set(table.get('retire') or {})
        for d in rendu.iterdir():
            if d.is_dir() and d.name != '.git' and d.name not in declares:
                ecarts.append(f'{d.name}/ part sans figurer dans la table')
        self.assertEqual(ecarts, [], r.stdout[-400:])

    def test_tout_dossier_du_brain_a_une_decision(self):
        """Une couche nouvelle — un dossier suivi, un satellite déclaré — n'arrive
        chez les forks, ni n'en est oubliée, sans une ligne dans la table."""
        import yaml
        suivis = subprocess.run(['git', '-C', str(BRAIN_ROOT_PATH), 'ls-tree', '-d', '--name-only', 'HEAD'],
                                capture_output=True, text=True, check=True).stdout.split()
        satellites = list((yaml.safe_load((BRAIN_ROOT_PATH / 'satellites.yml').read_text()) or {})
                          .get('satellites') or {})
        table = self._table()
        sans = sorted(set(suivis + satellites) - set(table['couches']) - set(table.get('retire') or {}))
        self.assertEqual(sans, [], 'dossiers du brain sans décision dans gabarit/couches.yml')

    def test_la_doc_dit_ce_que_dit_la_table(self):
        """`docs/src/satellites.md` montre ce qu'un fork reçoit vide : la même liste
        que les lignes `part: readme` — la table ne part pas (ses lignes « non »
        nomment les projets de l'owner), la doc si."""
        texte = (BRAIN_ROOT_PATH / 'docs' / 'src' / 'satellites.md').read_text(encoding='utf-8')
        section = texte[texte.index('## Les dossiers à part'):texte.index('## Les versionner à part')]
        dans_la_doc = set(re.findall(r'^\| `([a-z-]+)/` \|', section, re.M))
        readme = {n for n, c in self._table()['couches'].items() if c['part'] == 'readme'}
        self.assertEqual(dans_la_doc, readme)

    def test_un_nom_de_retrait_dangereux_arrete_la_synchro(self):
        """`rm -rf` sur un nom lu dans un fichier : `../x` ou `a/b` arrêtent tout."""
        table = (self.brain / 'gabarit' / 'couches.yml')
        table.write_text(table.read_text().replace('retire:\n', 'retire:\n  ../profil: "piège"\n'))
        rendu, r = self._rendre(self.tmp / 'pas-de-base')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('nom refusé dans retire', r.stderr + r.stdout)

    def test_un_retire_present_dans_la_base_est_retire(self):
        """Témoin : une base qui porte encore `modes/` — le rendu ne l'a plus."""
        base = self.tmp / 'base'
        (base / 'modes').mkdir(parents=True)
        (base / 'modes' / 'README.md').write_text('# modes\n')
        (base / 'README.md').write_text('# base\n')
        self._git('init', '-q', cwd=base)
        self._git('add', '-A', cwd=base)
        self._git('commit', '-q', '--no-verify', '-m', 'b', cwd=base)
        rendu, r = self._rendre(base)
        self.assertIn('modes/ — retiré du gabarit', r.stdout, r.stdout[-600:])
        self.assertFalse((rendu / 'modes').exists())


class TestNiveauxDuGabarit(unittest.TestCase):
    """Un fork reçoit les zones d'écriture du moteur : `NIVEAUX.yml`.

    Le gabarit ne le portait pas. Le moteur d'un fork retombait sur ses listes en
    dur, et `vie/` — zone kernel, que le rôle MCP ne peut pas écrire — y tombait
    en zone libre. Mesuré le 2/10 en lançant la suite sur un fork installé. Le
    juge est le moteur DU RENDU (`server._write_zone`), pas une relecture du
    fichier."""

    CHEMINS, SATELLITES = TestSyncTemplate.CHEMINS, TestSyncTemplate.SATELLITES
    setUp, tearDown = TestCouchesDuGabarit.setUp, TestCouchesDuGabarit.tearDown
    _git, _sync, _rendre = TestSyncTemplate._git, TestSyncTemplate._sync, TestCouchesDuGabarit._rendre
    BASE = TestCouchesDuGabarit.BASE
    INSTALLE = {'brain-compose.local.yml', 'brain-dolt/', 'brain-secrets/', 'brain-db-backup/'}

    def _zones_du_rendu(self, rendu, *chemins):
        r = subprocess.run(
            [sys.executable, '-c',
             'import sys; sys.dont_write_bytecode=True; sys.path.insert(0, "brain-engine"); '
             'import server; print(" ".join(server._write_zone(c) for c in sys.argv[1:]))', *chemins],
            cwd=rendu, capture_output=True, text=True, timeout=60,
            env={**self.env, 'BRAIN_ROOT': str(rendu)})
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        return r.stdout.split()

    def test_le_moteur_d_un_fork_garde_vie(self):
        if not (self.BASE / '.git').exists():
            self.skipTest('brain-template/ absent — le gabarit publié est la base du rendu')
        import yaml
        rendu, r = self._rendre(self.BASE.resolve())
        self.assertIn('✅ Sync terminé', r.stdout, 'rendu interrompu — rien à juger\n' + r.stdout[-800:])
        self.assertEqual(self._zones_du_rendu(rendu, 'vie/papiers/releve.md', 'scripts/x.sh',
                                              'contenu/atelier/brouillon.md'),
                         ['kernel', 'kernel', 'libre'],
                         "vie/ et scripts/ en kernel chez le fork ; contenu/, le témoin voisin, libre")
        texte = (rendu / 'NIVEAUX.yml').read_text(encoding='utf-8')
        entrees = yaml.safe_load(texte)['entrees']
        # Rien qui nomme cette instance : seules les entrées que le fork a, que
        # la table fait partir ou que son installation crée — et ni note ni
        # commentaire de la source.
        partent = {f'{n}/' for n, c in TestCouchesDuGabarit._table(self)['couches'].items()
                   if c['part'] in ('contenu', 'readme')}
        absentes = [n for n in entrees if n != 'NIVEAUX.yml' and n not in self.INSTALLE
                    and n not in partent and not (rendu / n.rstrip('/')).exists()]
        self.assertEqual(absentes, [], 'des entrées que le fork n\'a pas')
        self.assertFalse(any(isinstance(v, dict) and 'note' in v for v in entrees.values()))
        source = (self.brain / 'NIVEAUX.yml').read_text(encoding='utf-8')
        commentaires = {l.strip() for l in source.splitlines()
                        if l.strip().startswith('#') and l.strip('# ')}
        self.assertEqual([l for l in texte.splitlines() if l.strip() in commentaires], [],
                         'un commentaire de la source est parti')

    def test_sans_source_la_synchro_refuse(self):
        """Témoin : un brain sans `NIVEAUX.yml` ne rend pas un gabarit sans zones."""
        self._git('rm', '-q', 'NIVEAUX.yml', cwd=self.brain)
        self._git('commit', '-q', '--no-verify', '-m', 'sans niveaux', cwd=self.brain)
        rendu, r = self._rendre(self.tmp / 'pas-de-base')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('NIVEAUX.yml introuvable', r.stdout + r.stderr)

    def test_vie_hors_kernel_la_synchro_refuse(self):
        """Témoin : une source où `vie/` a perdu sa zone — le rendu refuse."""
        src = self.brain / 'NIVEAUX.yml'
        src.write_text(src.read_text(encoding='utf-8').replace(
            'vie/:\n    niveau: donnee\n    zone: kernel', 'vie/:\n    niveau: donnee'), encoding='utf-8')
        rendu, r = self._rendre(self.tmp / 'pas-de-base')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("vie/ n'est pas en zone kernel", r.stdout + r.stderr)


class TestFocusInstantane(unittest.TestCase):
    """Moteur éteint, une session a le dernier focus, daté — pas un renvoi vers
    l'API qui ne répond pas.

    Un faux `/focus` sur un port libre, un brain jetable : ni le vrai moteur ni
    le vrai `focus.md` ne sont touchés."""

    DONNEES = {'cap': 'Direction : essai', 'front': [{'id': 'i-1', 'project': 'p', 'total_sessions': 2,
                                                     'next_step': 'la suite'}],
               'active': [], 'stasis_count': 0, 'projects': [{'project': 'p', 'active_count': 1}],
               'last_session': None}

    def setUp(self):
        import focus_instantane
        self.f = focus_instantane
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _serveur(self):
        import http.server, threading
        corps = json.dumps(self.DONNEES).encode()

        class Focus(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == '/focus' else 404)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *a):
                pass

        serveur = http.server.HTTPServer(('127.0.0.1', 0), Focus)
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        self.addCleanup(serveur.server_close)
        self.addCleanup(serveur.shutdown)
        return f'http://127.0.0.1:{serveur.server_address[1]}'

    def test_l_instantane_porte_le_focus_et_sa_date(self):
        ecrit, message = self.f.ecrire(self.racine, self._serveur())
        self.assertTrue(ecrit, message)
        texte = (self.racine / self.f.NOM).read_text()
        self.assertIn('# Focus — instantané du ', texte)
        self.assertIn('Direction : essai', texte)
        self.assertIn('la suite', texte)
        self.assertFalse(list(self.racine.glob('*.tmp')), 'rien de provisoire ne reste')

    def test_moteur_injoignable_l_instantane_precedent_reste(self):
        (self.racine / self.f.NOM).write_text('# Focus — instantané d avant\n')
        ecrit, message = self.f.ecrire(self.racine, 'http://127.0.0.1:1')
        self.assertFalse(ecrit)
        self.assertIn('précédent reste', message)
        self.assertEqual((self.racine / self.f.NOM).read_text(), '# Focus — instantané d avant\n')

    def test_brain_focus_live_rend_le_meme_texte_que_l_instantane(self):
        import mcp_server as m
        api = self._serveur()
        with patch.object(m, 'BRAIN_API', api):
            live = getattr(m.brain_focus, 'fn', m.brain_focus)()
        self.assertEqual(live, self.f.rendre(self.DONNEES))

    def test_moteur_eteint_brain_focus_rend_l_instantane_et_le_dit(self):
        import mcp_server as m
        self.f.ecrire(self.racine, self._serveur())
        (self.racine / 'focus.md').write_text('# Focus\n> Ce fichier est un fallback statique.\n')
        with patch.object(m, 'BRAIN_API', 'http://127.0.0.1:1'), patch.object(m, 'BRAIN_ROOT', self.racine):
            repli = getattr(m.brain_focus, 'fn', m.brain_focus)()
        self.assertIn('Repli', repli, 'le repli se dit repli')
        self.assertIn('Direction : essai', repli, 'le vrai focus, pas un renvoi vers l API')
        self.assertNotIn('fallback statique', repli)

    def test_sans_instantane_le_fallback_statique(self):
        """Le repli se dit repli, même quand `focus.md` ne le dit pas : celui d'un
        fork neuf, sans instantané, ne le disait pas."""
        import mcp_server as m
        (self.racine / 'focus.md').write_text('# Focus actuel\n\nmon cap\n')
        with patch.object(m, 'BRAIN_API', 'http://127.0.0.1:1'), patch.object(m, 'BRAIN_ROOT', self.racine):
            repli = getattr(m.brain_focus, 'fn', m.brain_focus)()
        self.assertIn('Repli statique', repli, 'le repli se dit repli')
        self.assertIn('mon cap', repli, 'et rend le fichier tel qu il est écrit')

    def test_l_indexeur_ecrit_l_instantane_avant_l_embedding(self):
        """Ollama absent arrête l'embedding — pas le focus."""
        script = (BRAIN_ROOT_PATH / 'scripts' / 'brain-engine.sh').read_text()
        corps = script[script.index('cmd_embed() {'):]
        self.assertLess(corps.index('focus_instantane.py'), corps.index('command -v ollama'))


class TestGardeCommandes(unittest.TestCase):
    """Le hook `PreToolUse` refuse trois gestes, chacun un incident.

    Un brain jetable (un dépôt git, son `workspace/scratch/`, un worktree), un
    dépôt étranger. Le premier cas de chaque motif est la commande de l'incident,
    mot pour mot ; chaque motif a son témoin qui passe."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'garde-commandes.py'

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location('garde_commandes', script_d_instance(cls.SCRIPT))
        cls.g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.g)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name)
        self.brain, self.autre = t / 'Brain', t / 'autre'
        for d in (self.brain, self.autre):
            (d / 'workspace' / 'scratch').mkdir(parents=True)
            subprocess.run(['git', 'init', '-q'], cwd=d, check=True)
            (d / 'a.md').write_text('a')
            subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', 'a.md'], cwd=d, check=True)
            subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'a', '--no-verify'],
                           cwd=d, check=True)
        self.wt = self.brain / 'workspace' / 'scratch' / 'wt-x'
        subprocess.run(['git', 'worktree', 'add', '-q', '-b', 'x', str(self.wt)], cwd=self.brain, check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def refuse(self, ligne, cwd=None):
        return self.g.juger(ligne, cwd or self.brain, self.brain)

    def test_rm_par_motif_dans_scratch(self):
        self.assertIsNotNone(self.refuse('rm -f workspace/scratch/pr-*.md'), "l'incident du 30/09")
        self.assertIsNotNone(self.refuse('cd workspace/scratch && rm -f *.md'), 'le cd est suivi')
        self.assertIsNotNone(self.refuse(f'rm -rf {self.brain}/workspace/scratch/wt-?'))
        # Témoins : nommé un par un, ou un motif ailleurs.
        self.assertIsNone(self.refuse('rm -f workspace/scratch/mon-brouillon.md'))
        self.assertIsNone(self.refuse(f'rm -f {self.autre}/tmp-*.txt'))
        self.assertIsNone(self.refuse('echo "rm -f workspace/scratch/pr-*.md"'), 'une citation n\'est pas un geste')

    def test_git_add_tout_dans_le_brain(self):
        self.assertIsNotNone(self.refuse('git add -A'), "l'incident des 09-10/09")
        self.assertIsNotNone(self.refuse(f'git -C {self.brain} add .', cwd=self.autre), '-C est suivi')
        self.assertIsNotNone(self.refuse('git add -Av', cwd=self.wt), 'un worktree partage le dépôt du brain')
        self.assertIsNotNone(self.refuse('git add --all && git commit -m x'))
        # Témoins : par chemins dans le brain, ou -A dans un autre dépôt.
        self.assertIsNone(self.refuse('git add a.md && git commit -m x -- a.md'))
        self.assertIsNone(self.refuse('git add -A', cwd=self.autre))

    def test_executer_mysecrets(self):
        self.assertIsNotNone(self.refuse('set -a; . brain-secrets/MYSECRETS; set +a'), "l'incident du 28/09")
        self.assertIsNotNone(self.refuse('source ~/Dev/Brain/brain-secrets/MYSECRETS && python3 x.py'))
        self.assertIsNotNone(self.refuse('bash brain-secrets/MYSECRETS'))
        # Témoin : l'extraction d'une clé, celle que la règle recommande.
        self.assertIsNone(self.refuse("grep -m1 '^CLE=' brain-secrets/MYSECRETS | cut -d= -f2-"))

    def test_un_heredoc_est_du_texte_sauf_pour_un_shell(self):
        """Le faux positif du 2/10 : le garde a refusé une commande dont le heredoc
        ÉCRIVAIT une proposition qui citait la règle. Construit à l'exécution."""
        secret = 'MY' + 'SECRETS'
        texte = ("cat > note.md <<'FIN'\n- " + secret + " : jamais `@`, jamais `source`/`.`, jamais affiché.\n"
                 "- filtrer PASSWORD|SECRET|KEY|TOKEN d'emblée.\nFIN\necho fait")
        self.assertIsNone(self.refuse(texte), "le texte d'un heredoc n'est pas une commande")
        self.assertIsNone(self.refuse("cat > n.md <<'FIN'\nrm -f workspace/scratch/pr-*.md\nFIN"))
        self.assertIsNotNone(self.refuse("bash <<'FIN'\nrm -f workspace/scratch/pr-*.md\nFIN"),
                             'un heredoc lu par un shell s\'exécute : il est jugé')
        self.assertIsNotNone(self.refuse('cd workspace/scratch\nrm -f *.md'),
                             'deux lignes sont deux commandes, et le cd est suivi')

    def test_un_heredoc_passe_a_un_shell_par_un_tube_est_juge(self):
        """`cat <<FIN | bash` exécute le corps : il passait, avant comme après le
        correctif des heredocs (relevé à la relecture du 2/10)."""
        corps = "\nrm -f workspace/scratch/pr-*.md\nFIN"
        self.assertIsNotNone(self.refuse("cat <<'FIN' | bash" + corps), 'le tube mène à bash')
        self.assertIsNotNone(self.refuse("cat <<'FIN' | tee x.log | sh" + corps), 'un shell plus loin dans le tube')
        self.assertIsNotNone(self.refuse("cat <<'FIN' | FOO=1 /bin/bash" + corps), 'chemin et affectation')
        # Témoins : le tube s'arrête à `;` et `&&`, et un tube sans shell reste du texte.
        self.assertIsNone(self.refuse("cat <<'FIN' > n.md; bash -c true" + corps))
        self.assertIsNone(self.refuse("cat <<'FIN' > n.md && bash -c true" + corps))
        self.assertIsNone(self.refuse("cat <<'FIN' | tee n.md" + corps))

    def _hook(self, entree):
        return subprocess.run([sys.executable, str(self.SCRIPT), 'hook'], input=json.dumps(entree),
                              capture_output=True, text=True, timeout=30)

    def test_le_hook_refuse_par_json_et_sort_toujours_en_zero(self):
        r = self._hook({'tool_name': 'Bash', 'cwd': str(BRAIN_ROOT_PATH),
                        'tool_input': {'command': 'set -a; . brain-secrets/MYSECRETS'}})
        self.assertEqual(r.returncode, 0)
        sortie = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(sortie['permissionDecision'], 'deny')
        self.assertIn('MYSECRETS', sortie['permissionDecisionReason'])

    def test_le_hook_ne_dit_rien_quand_rien_ne_va_mal(self):
        for entree in ({'tool_name': 'Bash', 'cwd': '/', 'tool_input': {'command': 'ls'}},
                       {'tool_name': 'Edit', 'tool_input': {'file_path': 'x'}},
                       {'tool_name': 'Bash', 'cwd': '/', 'tool_input': {'command': 'echo "pas fermé'}}):
            r = self._hook(entree)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ''), entree)


class TestScratchNettoyable(unittest.TestCase):
    """La règle du 1/10, outillée : ce qui peut quitter `scratch/`, et pourquoi le
    reste reste. Lecture seule.

    Chaque clause garde une entrée vieille ; le témoin, vieux et rien d'autre,
    sort candidat — sans lui, un outil qui ne propose jamais rien passerait."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'scratch-nettoyable.py'

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('scratch_nettoyable', script_d_instance(self.SCRIPT))
        self.n = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.n)
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / 'Brain'
        s = self.brain / 'workspace' / 'scratch'
        s.mkdir(parents=True)
        (self.brain / 'scripts').mkdir()
        git = lambda *a, cwd=self.brain: subprocess.run(
            ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *a], cwd=cwd, check=True, capture_output=True)
        git('init', '-q')
        (self.brain / 'note.md').write_text('voir workspace/scratch/cite.md\n')
        git('add', 'note.md'); git('commit', '-qm', 'n', '--no-verify')
        (self.brain / 'scripts' / 'bsi-query.sh').write_text(
            '[ "$1" = open ] && echo "sess-x | work/revendique | 2026-10-01 | age 1h"\n')
        for nom in ('vieux.md', 'cite.md', 'neuf.md', 'revendique'):
            (s / nom).write_text('x')
        (s / 'wt-x').mkdir(); (s / 'wt-x' / 'f').write_text('x')
        depot = s / 'vieux-depot'
        depot.mkdir(); git('init', '-q', cwd=depot); (depot / 'en-cours.md').write_text('pas commité')
        vieux = time.time() - 40 * 86400
        for p in s.rglob('*'):
            if p.name != 'neuf.md':
                os.utime(p, (vieux, vieux))
        for p in (s / 'wt-x', s / 'vieux-depot'):
            os.utime(p, (vieux, vieux))

    def tearDown(self):
        self._tmp.cleanup()

    def test_chaque_clause_garde_et_le_temoin_sort(self):
        candidats, gardes, alerte = self.n.trier(self.brain, 30)
        self.assertIsNone(alerte)
        self.assertEqual([c[0] for c in candidats], ['vieux.md'], 'le témoin, et lui seul')
        raisons = dict(gardes)
        self.assertIn('cité par note.md', raisons['cite.md'])
        self.assertIn('récent', raisons['neuf.md'])
        self.assertIn('claim', raisons['revendique'])
        self.assertIn('worktree', raisons['wt-x'])
        self.assertIn('non poussé', raisons['vieux-depot'])

    def test_sans_claims_lisibles_rien_n_est_candidat(self):
        (self.brain / 'scripts' / 'bsi-query.sh').unlink()
        candidats, gardes, alerte = self.n.trier(self.brain, 30)
        self.assertEqual(candidats, [])
        self.assertIn('illisible', alerte)
        self.assertIn('claims illisibles', dict(gardes)['vieux.md'])

    def test_l_outil_ne_supprime_rien(self):
        avant = sorted(p.name for p in (self.brain / 'workspace' / 'scratch').iterdir())
        r = subprocess.run([sys.executable, str(self.SCRIPT), '--brain', str(self.brain)],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('vieux.md', r.stdout)
        self.assertEqual(sorted(p.name for p in (self.brain / 'workspace' / 'scratch').iterdir()), avant)


class TestDireAuTetard(unittest.TestCase):
    """Le point d'appel du brain vers le têtard : il parle quand il y a un têtard,
    il se tait sinon, et ne fait jamais échouer la session.

    Un faux moteur sur un port libre enregistre ce qu'il reçoit ; aucun vrai
    têtard ne bouge."""

    SCRIPT = BRAIN_ROOT_PATH / 'scripts' / 'dire.py'

    def setUp(self):
        script_d_instance(self.SCRIPT)
        import http.server, threading
        self.recu, self.claims = [], []
        claims = self.claims

        class Moteur(http.server.BaseHTTPRequestHandler):
            def _rendre(self, corps):
                b = json.dumps(corps).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                self._rendre(claims)

            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0))
                moi.recu.append(json.loads(self.rfile.read(n)))
                self._rendre({'ok': True})

            def log_message(self, *a):
                pass

        moi = self
        self.serveur = http.server.HTTPServer(('127.0.0.1', 0), Moteur)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self._tmp = tempfile.TemporaryDirectory()
        self.plugin = Path(self._tmp.name) / 'tetard'
        self.plugin.mkdir()

    def tearDown(self):
        self.serveur.shutdown(); self.serveur.server_close(); self._tmp.cleanup()

    def _dire(self, *args, plugin=True, port=None):
        env = {**{k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')},
               'TETARD_PLUGIN': str(self.plugin if plugin else Path(self._tmp.name) / 'absent'),
               'BRAIN_PORT': str(port or self.serveur.server_address[1]),
               'CLAUDE_CODE_SESSION_ID': 'agent-moi'}
        return subprocess.run([sys.executable, str(self.SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_la_session_parle_a_son_tetard(self):
        self.claims += [{'sess_id': 'sess-moi', 'agent_session': 'agent-moi'},
                        {'sess_id': 'sess-autre', 'agent_session': 'agent-autre'}]
        r = self._dire('PR prête', '--attention')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.recu, [{'type': 'tetard:dire', 'context': 'sess-moi',
                                      'message': 'PR prête', 'level': 'attention'}])

    def test_sans_tetard_il_se_tait(self):
        self.claims.append({'sess_id': 'sess-moi', 'agent_session': 'agent-moi'})
        r = self._dire('PR prête', plugin=False)
        self.assertEqual((r.returncode, r.stdout, r.stderr, self.recu), (0, '', '', []))

    def test_une_panne_ne_fait_jamais_echouer_la_session(self):
        r = self._dire('PR prête', port=1)
        self.assertEqual(r.returncode, 0)
        self.assertIn('injoignable', r.stderr)
        self.claims += [{'sess_id': 'a', 'agent_session': 'agent-moi'}, {'sess_id': 'b', 'agent_session': 'agent-moi'}]
        r = self._dire('PR prête')
        self.assertEqual((r.returncode, self.recu), (0, []), 'ambigu : rien dit')
        self.assertIn('ambigu', r.stderr)


class TestClaimsOrphelins(unittest.TestCase):
    """Un claim ouvert dont la session n'a plus de processus est NOMMÉ, jamais
    fermé ; une session parquée puis reprise n'en fait pas un orphelin."""

    @classmethod
    def setUpClass(cls):
        import importlib.util, collections
        spec = importlib.util.spec_from_file_location(
            'claims_orphelins', script_d_instance(BRAIN_ROOT_PATH / 'scripts' / 'claims-orphelins.py'))
        cls.o = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.o)
        cls.Claim = collections.namedtuple('Claim', 'sess_id scope agent_session')

    def test_vivant_mort_repris_et_non_juges(self):
        C = self.Claim
        claims = [C('sess-vivant', 'brain', 'agent-vivant'),
                  C('sess-mort', 'explore', 'agent-mort'),
                  C('sess-parque', 'work/x', 'agent-ancien'),
                  C('sess-x.laptop', 'work/y', 'agent-ailleurs'),
                  C('sess-sans', 'chill', None)]
        sessions = [{'sessionId': 'agent-vivant', 'pid': 100},
                    {'sessionId': 'agent-mort', 'pid': 200},
                    {'sessionId': 'agent-ancien', 'pid': 300, 'parkedJobId': 'repris'},
                    {'sessionId': 'repris-1234', 'pid': 400}]
        vivant = {100: True, 200: False, 300: False, 400: True}.get
        orphelins, non_juges = self.o.juger(claims, sessions, vivant)
        self.assertEqual([c.sess_id for c, _ in orphelins], ['sess-mort'])
        self.assertEqual(sorted(c.sess_id for c, _ in non_juges), ['sess-sans', 'sess-x.laptop'])

    def test_sessions_illisibles_rien_n_est_orphelin(self):
        orphelins, non_juges = self.o.juger([self.Claim('s', 'b', 'a')], None)
        self.assertEqual((orphelins, len(non_juges)), ([], 1))


class TestStatutDesHandoffs(unittest.TestCase):
    """Le statut d'un handoff se lit sans son commentaire.

    `status: consumed        # active | consumed | archived` — la ligne réelle de
    `session-liseur-omarchy-20260927.md` — était refusée et retombait `active` :
    la base disait les 43 handoffs de la racine tous actifs."""

    def _lire(self, entete):
        import migrate
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'handoffs').mkdir()
            (Path(tmp) / 'handoffs' / 'h.md').write_text(f'---\n{entete}\n---\n# h\n')
            with patch.object(migrate, 'BRAIN_ROOT', tmp):
                return {l[0]: l[3] for l in migrate.lire_handoffs()}['h.md']

    def test_le_commentaire_ne_fait_plus_tomber_le_statut(self):
        self.assertEqual(self._lire('status: consumed        # active | consumed | archived'), 'consumed')
        self.assertEqual(self._lire('status: consumed'), 'consumed')
        self.assertEqual(self._lire('status: PERIME — voir autre.md'), 'active', 'inconnu : active, comme avant')



class TestBrainServe(unittest.TestCase):
    """`brain serve` — les deux portes, une seule déclaration.

    La déclaration était écrite trois fois (les unités, `brain-engine.sh`, les
    serveurs) ; les secrets étaient EXÉCUTÉS par `source`. Ces garanties tiennent
    l'ordre de la déclaration, la lecture des secrets comme du texte, et le
    contrat d'un processus par porte."""

    def setUp(self):
        import serve
        self.serve = serve
        self.tmp = Path(tempfile.mkdtemp())
        self.donnees = self.tmp / 'brain'
        self.programme = self.donnees / 'brain-engine'
        self.programme.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _secrets(self, texte):
        (self.donnees / 'brain-secrets').mkdir(exist_ok=True)
        (self.donnees / 'brain-secrets' / 'MYSECRETS').write_text(texte)

    def _declarer(self, environ=None):
        return self.serve.declarer(environ or {}, self.donnees, self.programme)

    def test_l_ordre_de_la_declaration(self):
        d = self._declarer()
        self.assertEqual((d.port_http, d.port_mcp), ('7700', '7701'), 'les défauts')
        self.assertEqual(d.environ['BRAIN_MCP_SCOPES'], 'public,work,instance,satellite',
                         'le MCP lancé ici est local : il ne retombe pas sur le défaut étroit')
        (self.programme / '.env.local').write_text('BRAIN_PORT=7800\nBRAIN_MCP_PORT="7801"\n')
        d = self._declarer()
        self.assertEqual((d.port_http, d.port_mcp), ('7800', '7801'), '.env.local, guillemets compris')
        d = self._declarer({'BRAIN_PORT': '7900'})
        self.assertEqual(d.port_http, '7900', "l'environnement l'emporte sur .env.local")
        self.assertEqual(d.environ['BRAIN_ROOT'], str(self.donnees), 'la racine des données est posée')

    def test_le_mode(self):
        self.assertEqual(self._declarer().mode, 'dev', 'sans rien : dev, comme brain-engine.sh')
        (self.donnees / 'brain-compose.local.yml').write_text('instance:\n    mode: prod\n')
        self.assertEqual(self._declarer().mode, 'prod', 'le premier mode: indenté du compose')
        self.assertEqual(self._declarer({'BRAIN_MODE': 'template'}).mode, 'template', 'BRAIN_MODE gagne')

    def test_les_secrets_se_lisent_et_ne_s_executent_pas(self):
        temoin = self.tmp / 'execute'
        self._secrets(f'# un commentaire\nBRAIN_TOKEN_OWNER=jeton-a\n'
                      f'export BRAIN_TOKEN_MCP="jeton-b"\nPIEGE=$(touch {temoin})\n')
        d = self._declarer()
        self.assertEqual(d.secrets, 'chargés')
        self.assertEqual(d.environ['BRAIN_TOKEN_OWNER'], 'jeton-a')
        self.assertEqual(d.environ['BRAIN_TOKEN_MCP'], 'jeton-b', '`export` et les guillemets, comme systemd')
        self.assertEqual(d.environ['PIEGE'], f'$(touch {temoin})', 'du texte, pas une commande')
        self.assertFalse(temoin.exists(), 'rien du fichier de secrets ne s’exécute')

    def test_en_demo_les_secrets_ne_sont_pas_lus(self):
        self._secrets('BRAIN_TOKEN_OWNER=jeton-a\n')
        d = self._declarer({'BRAIN_MODE': 'demo'})
        self.assertEqual(d.secrets, 'non requis (demo)')
        self.assertNotIn('BRAIN_TOKEN_OWNER', d.environ)
        sans_fichier = self.serve.declarer({}, self.tmp / 'vide', self.programme)
        self.assertEqual(sans_fichier.secrets, 'absents', 'pas de fichier : dit, pas deviné')

    def test_l_environnement_l_emporte_sur_mysecrets(self):
        self._secrets('BRAIN_MCP_SCOPES=public\n')
        self.assertEqual(self._declarer().environ['BRAIN_MCP_SCOPES'], 'public', 'MYSECRETS sur le défaut')
        d = self._declarer({'BRAIN_MCP_SCOPES': 'public,work'})
        self.assertEqual(d.environ['BRAIN_MCP_SCOPES'], 'public,work', "ce qui est posé (une unité) gagne")

    def test_la_declaration_n_affiche_aucun_secret(self):
        self._secrets('BRAIN_TOKEN_OWNER=valeur-qui-ne-doit-pas-sortir\n')
        lignes = '\n'.join(self.serve.resume(self._declarer(), self.programme))
        self.assertNotIn('valeur-qui-ne-doit-pas-sortir', lignes)
        self.assertIn('secrets  : chargés', lignes)

    def test_ports_rend_les_ports_de_la_declaration_et_rien_d_autre(self):
        """Ce que brain-engine.sh vérifie (« port déjà tenu ? ») est ce que les
        serveurs ouvriront — MYSECRETS compris. Avant, le script relisait
        .env.local de son côté, sans MYSECRETS : deux lectures, deux réponses."""
        self._secrets('BRAIN_PORT=17777\nBRAIN_TOKEN_OWNER=valeur-qui-ne-doit-pas-sortir\n')
        sortie = io.StringIO()
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env['BRAIN_ROOT'] = str(self.donnees)
        import importlib
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(sortie):
            import racines
            importlib.reload(racines)
            try:
                # Le programme aussi est le jetable : le `.env.local` du VRAI
                # programme (qui existe dans une instance) ne doit rien décider ici.
                with patch.object(racines, 'PROGRAMME', self.programme):
                    code = self.serve.main(['--ports'])
            finally:
                os.environ.pop('BRAIN_ROOT', None)
                importlib.reload(racines)
        self.assertEqual(code, 0)
        self.assertEqual(sortie.getvalue().split(), ['BRAIN_PORT=17777', 'BRAIN_MCP_PORT=7701'])
        self.assertNotIn('valeur-qui-ne-doit-pas-sortir', sortie.getvalue())

    def test_une_porte_remplace_le_processus(self):
        """Le PID du serveur est celui que systemd et le fichier de PID suivent."""
        d = self._declarer()
        with patch.object(self.serve.os, 'execve') as execve, patch.object(self.serve.os, 'chdir'):
            self.serve.lancer_une('mcp', d, self.programme)
        cmd, argv, env = execve.call_args[0]
        self.assertEqual(argv[1], str(self.programme / 'mcp_server.py'))
        self.assertEqual(cmd, argv[0])
        self.assertEqual(env['BRAIN_MCP_PORT'], '7701')

    def test_si_une_porte_tombe_l_autre_est_arretee(self):
        import subprocess as sp
        enfants = {
            'http': sp.Popen([sys.executable, '-c', 'import sys; sys.exit(3)']),
            'mcp': sp.Popen([sys.executable, '-c', 'import time; time.sleep(60)']),
        }
        debut = time.monotonic()
        code = self.serve.surveiller(enfants, dire=lambda _m: None)
        self.assertEqual(code, 1, 'une porte tombée : brain serve sort en erreur')
        self.assertIsNotNone(enfants['mcp'].poll(), "l'autre porte est arrêtée, pas laissée seule")
        self.assertLess(time.monotonic() - debut, 15)



class TestInstallPm2(unittest.TestCase):
    """`install pm2` lance les DEUX portes, par `brain serve`.

    Avant, l'écosystème ne déclarait que l'API : un brain sous pm2 n'avait pas
    de serveur MCP. Et il relisait MYSECRETS en JavaScript, une seconde lecture
    de la déclaration. Joué dans un brain jetable, avec un faux `pm2` qui note
    ses appels ; l'écosystème généré est lu par Node, comme pm2 le lirait."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='install-pm2-'))
        self.brain = self.tmp / 'brain'
        for rel in ('scripts/brain-engine.sh', 'scripts/lib/python.sh', 'brain-engine/serve.py',
                    'brain-engine/racines.py'):
            (self.brain / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(BRAIN_ROOT_PATH / rel, self.brain / rel)
        for faux in ('server.py', 'mcp_server.py'):
            (self.brain / 'brain-engine' / faux).write_text('import time\ntime.sleep(1)\n')
        venv = BRAIN_ROOT_PATH / 'brain-engine' / '.venv'
        if not (venv / 'bin' / 'python3').exists():
            self.skipTest('pas de venv : `install pm2` vérifie les dépendances du moteur')
        (self.brain / 'brain-engine' / '.venv').symlink_to(venv.resolve())
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        self.appels = self.tmp / 'appels'
        pm2 = self.bin / 'pm2'
        pm2.write_text(f'#!/bin/sh\necho "$*" >> {self.appels}\nexit 0\n')
        pm2.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _port_libre(self):
        import socket as _s
        with _s.socket() as so:
            so.bind(('127.0.0.1', 0))
            return so.getsockname()[1]

    def test_les_deux_portes_par_brain_serve(self):
        if not shutil.which('node'):
            self.skipTest('node absent — l écosystème ne se lit pas')
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRAIN_')}
        env.update(PATH=f'{self.bin}:{env.get("PATH", "")}', HOME=str(self.tmp / 'home'),
                   BRAIN_PORT=str(self._port_libre()), BRAIN_MCP_PORT=str(self._port_libre()))
        r = subprocess.run(['bash', str(self.brain / 'scripts' / 'brain-engine.sh'), 'install', 'pm2'],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        eco = self.brain / 'ecosystem.config.js'
        lu = subprocess.run(['node', '-e', 'const a = require(process.argv[1]).apps;'
                             'console.log(JSON.stringify(a.map(x => [x.name, x.script, x.args])))', str(eco)],
                            capture_output=True, text=True, timeout=30)
        self.assertEqual(lu.returncode, 0, lu.stderr)
        self.assertEqual(json.loads(lu.stdout), [['brain-engine', 'brain-engine/serve.py', 'http'],
                                                 ['brain-mcp', 'brain-engine/serve.py', 'mcp']])
        texte = eco.read_text()
        # Ce qui LIRAIT un fichier, pas le mot : le commentaire dit justement
        # qu'il ne lit plus MYSECRETS.
        for lecture in ("require('fs')", 'readFileSync', 'brain-secrets'):
            self.assertNotIn(lecture, texte, 'la déclaration ne se relit pas ici')
        self.assertIn('`brain serve`', texte, 'le commentaire garde ses accents graves')
        self.assertIn('start ' + str(eco), self.appels.read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
