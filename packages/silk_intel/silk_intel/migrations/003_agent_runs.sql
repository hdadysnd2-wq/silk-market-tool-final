-- Stage 3 — سجل تشغيلات وكلاء البحث (§4b: صف لكل تشغيلة لشاشة الإدارة M6).
-- Every research-agent run is recorded: status, coverage, timing, reason.

CREATE TABLE IF NOT EXISTS agent_runs (
    id          INTEGER PRIMARY KEY,
    analysis_id INTEGER REFERENCES analyses(id),
    agent       TEXT NOT NULL,
    hs6         TEXT,
    iso3        TEXT,
    status      TEXT NOT NULL CHECK (status IN ('complete','partial','failed')),
    coverage    REAL NOT NULL DEFAULT 0.0,
    started_at  TEXT,
    finished_at TEXT,
    note        TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_lookup ON agent_runs (agent, iso3, started_at);
