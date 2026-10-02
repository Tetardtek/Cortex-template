-- brain-engine/schema.sql — le schéma du repli SQLite.
--
-- ⚠️  GÉNÉRÉ par scripts/schema-sqlite-gen.py — ne pas éditer à la main.
--     Source : schema-dolt.sql, lui-même généré depuis la base.
--     La chaîne est base → schema-dolt.sql → schema.sql : une seule
--     déclaration à l'origine. Éditer ici la ferait diverger.
--
-- Toutes les tables, aucune donnée — tranché par l'owner le 06/09 : un fork
-- reçoit tous les modules qu'on propose, vierges.
--
-- Les VUES sont écrites à la main et reprises telles quelles : elles
-- portent leur raisonnement, et celles-ci sont déjà en dialecte SQLite.

PRAGMA journal_mode=WAL;  -- lectures concurrentes sûres (multi-sessions)
PRAGMA foreign_keys=ON;

-- ── 19 tables ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agents (
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT,
    context_tier TEXT DEFAULT 'cold' CHECK (context_tier IS NULL OR context_tier IN ('always','hot','warm','cold')),
    domain TEXT,
    status TEXT DEFAULT 'active' CHECK (status IS NULL OR status IN ('active','stable','draft','deprecated')),
    scope TEXT,
    owner TEXT DEFAULT 'human',
    lifecycle TEXT,
    read_mode TEXT,
    triggers TEXT,
    receives_from TEXT,
    sends_to TEXT,
    zone_access TEXT,
    signals TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS chantiers (
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IS NULL OR status IN ('proposed','active','paused','resolved','abandoned')),
    project TEXT NOT NULL DEFAULT 'brain',
    description TEXT,
    resolved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS claims (
    sess_id TEXT NOT NULL,
    type TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IS NULL OR status IN ('open','closed','stale','paused','waiting_human','failed')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    handoff_level TEXT  CHECK (handoff_level IS NULL OR handoff_level IN ('NO','SEMI','SEMI+','FULL')),
    story_angle TEXT,
    health_score REAL,
    context_at_close INTEGER,
    cold_start_kpi_pass INTEGER,
    ttl_hours INTEGER DEFAULT '4',
    expires_at TEXT,
    instance TEXT,
    parent_sess TEXT,
    satellite_type TEXT,
    satellite_level TEXT,
    theme_branch TEXT,
    zone TEXT,
    mode TEXT,
    result_status TEXT,
    result_json TEXT,
    workflow TEXT,
    workflow_step INTEGER,
    project TEXT,
    result TEXT,
    duration_min INTEGER,
    energy TEXT,
    intention TEXT,
    tags TEXT,
    deliverables TEXT,
    agent_session TEXT,
    PRIMARY KEY (sess_id)
);

CREATE TABLE IF NOT EXISTS claims_archive (
    sess_id TEXT NOT NULL,
    type TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IS NULL OR status IN ('open','closed','stale','paused','waiting_human','failed')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    handoff_level TEXT  CHECK (handoff_level IS NULL OR handoff_level IN ('NO','SEMI','SEMI+','FULL')),
    story_angle TEXT,
    health_score REAL,
    context_at_close INTEGER,
    cold_start_kpi_pass INTEGER,
    ttl_hours INTEGER DEFAULT '4',
    expires_at TEXT,
    instance TEXT,
    parent_sess TEXT,
    satellite_type TEXT,
    satellite_level TEXT,
    theme_branch TEXT,
    zone TEXT,
    mode TEXT,
    result_status TEXT,
    result_json TEXT,
    workflow TEXT,
    workflow_step INTEGER,
    project TEXT,
    result TEXT,
    duration_min INTEGER,
    energy TEXT,
    intention TEXT,
    tags TEXT,
    deliverables TEXT,
    agent_session TEXT,
    archived_at TEXT NOT NULL,
    PRIMARY KEY (sess_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IS NULL OR status IN ('proposed','accepted','deprecated','superseded')),
    scope TEXT,
    date date,
    deciders TEXT,
    depends_on TEXT,
    tags TEXT,
    session TEXT,
    filename TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    project TEXT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS embedding_hits (
    chunk_id TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT '0',
    last_queried_at TEXT,
    PRIMARY KEY (chunk_id)
);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT NOT NULL,
    filepath TEXT NOT NULL,
    title TEXT,
    chunk_text TEXT NOT NULL,
    vector varbinary(4096),
    model TEXT,
    indexed INTEGER DEFAULT '0',
    scope TEXT NOT NULL DEFAULT 'work',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_queried_at TEXT,
    hit_count INTEGER DEFAULT '0',
    permanent INTEGER DEFAULT '0',
    x REAL,
    y REAL,
    z REAL,
    content_hash char(64),
    PRIMARY KEY (chunk_id)
);

CREATE TABLE IF NOT EXISTS handoffs (
    filename TEXT NOT NULL,
    type TEXT,
    projet TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IS NULL OR status IN ('active','consumed','archived')),
    from_sess TEXT,
    consumed_by TEXT,
    created_at TEXT NOT NULL,
    consumed_at TEXT,
    PRIMARY KEY (filename)
);

CREATE TABLE IF NOT EXISTS handoffs_archive (
    filename TEXT NOT NULL,
    type TEXT,
    projet TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IS NULL OR status IN ('active','consumed','archived')),
    from_sess TEXT,
    consumed_by TEXT,
    created_at TEXT NOT NULL,
    consumed_at TEXT,
    archived_at TEXT NOT NULL,
    PRIMARY KEY (filename)
);

CREATE TABLE IF NOT EXISTS intention_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IS NULL OR relation IN ('blocks','depends_on'))
);

CREATE TABLE IF NOT EXISTS intention_sessions (
    intention_id TEXT NOT NULL,
    sess_id TEXT NOT NULL,
    linked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intention_tags (
    intention_id TEXT NOT NULL,
    tag TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intentions (
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IS NULL OR status IN ('identified','active','stasis','done','archived')),
    project TEXT,
    domain TEXT,
    scope TEXT,
    priority TEXT DEFAULT 'medium' CHECK (priority IS NULL OR priority IN ('high','medium','low','none')),
    brief TEXT,
    next_step TEXT,
    stasis_reason TEXT,
    tenant TEXT,
    ttl_days INTEGER DEFAULT '60',
    front INTEGER DEFAULT '0',
    front_order INTEGER,
    agents TEXT,
    adrs TEXT,
    total_sessions INTEGER DEFAULT '0',
    total_duration INTEGER DEFAULT '0',
    last_touched TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT NOT NULL,
    holder TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ttl_min INTEGER NOT NULL DEFAULT '60',
    UNIQUE (filepath)
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IS NULL OR status IN ('planned','cadrage','dev','active','prod','pause','archived')),
    deploy TEXT,
    stack TEXT,
    url_prod TEXT,
    repo TEXT,
    tenant TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS sessions (
    sess_id TEXT NOT NULL,
    date TEXT NOT NULL,
    type TEXT,
    mode TEXT,
    handoff_level TEXT,
    tokens_used INTEGER,
    context_peak_pct INTEGER,
    context_at_close INTEGER,
    duration_min INTEGER,
    commits INTEGER,
    todos_closed INTEGER,
    saturation_flag INTEGER,
    health_score REAL,
    cold_start_kpi_pass INTEGER,
    notes TEXT,
    PRIMARY KEY (sess_id)
);

CREATE TABLE IF NOT EXISTS sessions_archive (
    sess_id TEXT NOT NULL,
    date TEXT NOT NULL,
    type TEXT,
    mode TEXT,
    handoff_level TEXT,
    tokens_used INTEGER,
    context_peak_pct INTEGER,
    context_at_close INTEGER,
    duration_min INTEGER,
    commits INTEGER,
    todos_closed INTEGER,
    saturation_flag INTEGER,
    health_score REAL,
    cold_start_kpi_pass INTEGER,
    notes TEXT,
    archived_at TEXT NOT NULL,
    PRIMARY KEY (sess_id)
);

CREATE TABLE IF NOT EXISTS signals (
    sig_id TEXT NOT NULL,
    from_sess TEXT,
    to_sess TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IS NULL OR type IN ('READY_FOR_REVIEW','REVIEWED','BLOCKED_ON','HANDOFF','CHECKPOINT','INFO')),
    projet TEXT,
    payload TEXT,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IS NULL OR state IN ('pending','delivered','archived')),
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    PRIMARY KEY (sig_id)
);

CREATE TABLE IF NOT EXISTS signals_archive (
    sig_id TEXT NOT NULL,
    from_sess TEXT,
    to_sess TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IS NULL OR type IN ('READY_FOR_REVIEW','REVIEWED','BLOCKED_ON','HANDOFF','CHECKPOINT','INFO')),
    projet TEXT,
    payload TEXT,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IS NULL OR state IN ('pending','delivered','archived')),
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    archived_at TEXT NOT NULL,
    PRIMARY KEY (sig_id)
);

-- ── 0 index ─────────────────────────────────────────────



-- ── Vues utilitaires ─────────────────────────────────────────────────────────

CREATE VIEW IF NOT EXISTS v_open_claims AS
    SELECT sess_id, scope, opened_at,
           ROUND((julianday('now') - julianday(opened_at)) * 24, 1) AS age_hours
    FROM claims
    WHERE status = 'open'
    ORDER BY opened_at DESC;

CREATE VIEW IF NOT EXISTS v_stale_claims AS
    SELECT sess_id, scope, opened_at,
           ROUND((julianday('now') - julianday(opened_at)) * 24, 1) AS age_hours
    FROM claims
    WHERE status = 'open'
      AND julianday('now') > julianday(opened_at, '+4 hours')
    ORDER BY age_hours DESC;

CREATE VIEW IF NOT EXISTS v_active_locks AS
    SELECT filepath, holder, claimed_at, expires_at,
           CASE WHEN julianday('now') < julianday(expires_at) THEN 'active' ELSE 'expired' END AS lock_status
    FROM locks
    ORDER BY claimed_at DESC;

CREATE VIEW IF NOT EXISTS v_cold_start_kpi AS
    SELECT
        COUNT(*) AS total_no_handoff,
        SUM(CASE WHEN cold_start_kpi_pass = 1 THEN 1 ELSE 0 END) AS passes,
        ROUND(
            100.0 * SUM(CASE WHEN cold_start_kpi_pass = 1 THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN cold_start_kpi_pass IS NOT NULL THEN 1 ELSE 0 END), 0),
        1) AS pass_rate_pct
    FROM sessions
    WHERE handoff_level = 'NO';

CREATE VIEW IF NOT EXISTS v_metabolism_7d AS
    SELECT
        date,
        type,
        AVG(health_score) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS health_7d_avg,
        SUM(CASE WHEN type='build-brain' THEN 1 ELSE 0 END)
            OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS build_7d,
        SUM(CASE WHEN type='use-brain' THEN 1 ELSE 0 END)
            OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS use_7d
    FROM sessions
    ORDER BY date DESC;
