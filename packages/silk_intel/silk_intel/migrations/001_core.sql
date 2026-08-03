-- M1 — المخطط الموحّد (خطة إعادة البناء §3). SQL محمول SQLite/Postgres.
-- One unified schema: users/roles, reference, FACT STORE, analyses, decisions.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- ── المستخدمون والوصول · users & access ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    name        TEXT,
    role        TEXT NOT NULL CHECK (role IN ('admin','analyst','viewer')),
    pw_hash     TEXT,
    created_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    key_hash    TEXT NOT NULL UNIQUE,
    label       TEXT,
    created_at  TEXT NOT NULL,
    revoked_at  TEXT
);

-- ── المرجع · reference ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS markets (
    iso3        TEXT PRIMARY KEY,
    m49         TEXT,
    name_ar     TEXT,
    name_en     TEXT,
    region      TEXT,
    gcc         INTEGER NOT NULL DEFAULT 0,
    eu          INTEGER NOT NULL DEFAULT 0
);

-- ── مخزن الحقائق · FACT STORE (قابل للاستعلام، يحفظ المصدر) ──────────────────
CREATE TABLE IF NOT EXISTS indicators (
    id           INTEGER PRIMARY KEY,
    iso3         TEXT NOT NULL,
    indicator    TEXT NOT NULL,
    year         INTEGER NOT NULL,
    value        REAL,
    source       TEXT NOT NULL,
    confidence   REAL NOT NULL DEFAULT 0.0,
    note         TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE (iso3, indicator, year, source)
);

CREATE TABLE IF NOT EXISTS trade_flows (
    id            INTEGER PRIMARY KEY,
    hs6           TEXT NOT NULL,
    reporter_iso3 TEXT NOT NULL,
    partner_iso3  TEXT NOT NULL,
    year          INTEGER NOT NULL,
    flow          TEXT NOT NULL CHECK (flow IN ('M','X')),
    value_usd     REAL,
    qty_kg        REAL,
    source        TEXT NOT NULL,
    retrieved_at  TEXT NOT NULL,
    UNIQUE (hs6, reporter_iso3, partner_iso3, year, flow)
);

CREATE TABLE IF NOT EXISTS collection_runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    requested   INTEGER NOT NULL DEFAULT 0,
    fetched     INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    budget_left INTEGER,
    note        TEXT
);

-- ── التحليلات ومخرجاتها · analyses & outputs ─────────────────────────────────
CREATE TABLE IF NOT EXISTS analyses (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    product     TEXT NOT NULL,
    hs6         TEXT,
    year_from   INTEGER,
    year_to     INTEGER,
    status      TEXT NOT NULL DEFAULT 'complete',
    created_at  TEXT NOT NULL,
    result_json TEXT NOT NULL,
    legacy_id   INTEGER
);

CREATE TABLE IF NOT EXISTS analysis_markets (
    id               INTEGER PRIMARY KEY,
    analysis_id      INTEGER NOT NULL REFERENCES analyses(id),
    iso3             TEXT,
    rank             INTEGER,
    total_score      REAL,
    confidence       REAL,
    comp_market_size REAL,
    comp_demand      REAL,
    comp_saudi       REAL,
    comp_competition REAL
);

CREATE TABLE IF NOT EXISTS decisions (
    id               INTEGER PRIMARY KEY,
    analysis_id      INTEGER NOT NULL REFERENCES analyses(id),
    iso3             TEXT NOT NULL,
    verdict          TEXT NOT NULL CHECK (verdict IN ('GO','CONDITIONAL-GO','NO-GO')),
    score            REAL,
    confidence       REAL,
    pillar_market    REAL,
    pillar_competition REAL,
    pillar_regulatory  REAL,
    pillar_profit    REAL,
    conditions_json  TEXT,
    risks_json       TEXT,
    first_steps_json TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES analyses(id),
    kind        TEXT NOT NULL CHECK (kind IN ('full','brief')),
    format      TEXT NOT NULL CHECK (format IN ('docx','md','pdf')),
    path        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    analysis_id INTEGER PRIMARY KEY REFERENCES analyses(id),
    outcome     TEXT NOT NULL,
    note        TEXT,
    recorded_by INTEGER REFERENCES users(id),
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_indicators_lookup ON indicators (iso3, indicator, year);
CREATE INDEX IF NOT EXISTS idx_trade_lookup ON trade_flows (hs6, reporter_iso3, year, flow);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses (created_at);
CREATE INDEX IF NOT EXISTS idx_amarkets_analysis ON analysis_markets (analysis_id);
