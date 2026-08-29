-- Persistent, APPEND-ONLY store for every series the dashboard tracks.
--
-- The one non-negotiable rule (DATABASE-PLAN.md, "Incremental update logic"):
-- nothing in this project ever issues UPDATE or DELETE against `observations`.
-- A revision is a new row with a later vintage_date, not a changed row. The
-- `latest_observations` view is the only place "the current value" exists,
-- and it is resolved fresh on every read.

CREATE TABLE IF NOT EXISTS series_catalog (
    series_id           TEXT PRIMARY KEY,   -- matches DATA-CATALOG.csv's Identifier column
    category            TEXT NOT NULL,
    region              TEXT,
    description         TEXT NOT NULL,
    unit                TEXT,
    native_periodicity  TEXT,
    source              TEXT,
    max_age_days        INTEGER,            -- staleness threshold, cadence-aware
    status              TEXT NOT NULL,      -- 'ok' | 'stale' | 'planned'
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    series_id     TEXT NOT NULL REFERENCES series_catalog(series_id),
    date          TEXT NOT NULL,            -- ISO 8601, the period the value describes
    vintage_date  TEXT NOT NULL,            -- when this value was OBSERVED as of
    value         REAL NOT NULL,
    ingested_at   TEXT NOT NULL,
    source_run_id INTEGER REFERENCES pipeline_runs(run_id),
    PRIMARY KEY (series_id, date, vintage_date)
);
CREATE INDEX IF NOT EXISTS idx_obs_series ON observations(series_id, date);

-- The ONLY place "current value" is computed. Not stored, not mutated --
-- resolved fresh on every read as "the most recently observed vintage for
-- this (series, date)". Adding a later vintage changes what this view returns
-- without a single UPDATE ever touching the base table.
CREATE VIEW IF NOT EXISTS latest_observations AS
SELECT o.series_id, o.date, o.value, o.vintage_date, o.ingested_at
FROM observations o
WHERE o.vintage_date = (
    SELECT MAX(o2.vintage_date) FROM observations o2
    WHERE o2.series_id = o.series_id AND o2.date = o.date
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    mode        TEXT,                       -- 'live' | 'sample' | 'bootstrap'
    git_sha     TEXT
);

CREATE TABLE IF NOT EXISTS data_quality_flags (
    flag_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL REFERENCES series_catalog(series_id),
    date      TEXT NOT NULL,
    flag_type TEXT NOT NULL,                -- 'gap'|'outlier'|'implausible_level'|'stale'|'curve_inconsistency'
    detail    TEXT,
    raised_at TEXT NOT NULL,
    resolved  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_flags_open ON data_quality_flags(resolved) WHERE resolved = 0;

-- One open flag per (series, date, type). Re-detecting the same condition on a
-- later run must not pile up duplicate rows.
CREATE UNIQUE INDEX IF NOT EXISTS idx_flags_unique
    ON data_quality_flags(series_id, date, flag_type, resolved);
