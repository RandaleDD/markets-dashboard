# Markets Dashboard — Database Plan

Status: plan, not yet built. Replaces the current architecture (each pipeline
run re-fetches and rebuilds `site/data/latest.json` from scratch) with a
persistent, **append-only** SQLite database that accumulates history over
time and is never rewritten. Grounded in the reviewed data catalog
(`markets-dashboard-data-catalog.xlsx` / `DATA-CATALOG.csv`, 116 fetchable
series across 18 categories after the sourcing review) — that catalog's
"ok" / "stale" / "planned (v2)" rows are what seeds this database; its
"no source found" / "descoped" / "exists, not free" rows are not fetched
and have no table rows.

**Two decisions already made, stated here so they aren't re-litigated:**
GitHub Actions stays the executor — it runs on schedule whether or not any
machine is on, and that reliability matters more than running locally.
The database file is **committed to the repo** on every run, same as
`latest.json` is today — that makes it "local" in every synced clone, and
git's own commit history is the backup mechanism (every commit is a full,
dated, retrievable snapshot, stored both locally and on GitHub). No separate
backup folder or script.

## Operating model — the whole point, stated plainly

Three phases, and the database's job in each is different:

**a) Build once, from today's definitions.** The bootstrap run (see
"Bootstrap" below) seeds `observations` from every fetchable series in the
current catalog, pulling as much history as each source will give up for
free. This happens once, not on a schedule. The schema doesn't hard-code the
116-series list anywhere, so the catalog **can grow later** — adding a new
series later is adding a row to `series_catalog` and running its own
backfill, and it does not touch, re-fetch, or re-derive anything that's
already stored for the other 115.

**b) Every day after that, only attach — never overwrite.** The daily run
asks each series "what's the newest thing I already have?", fetches only
what might be newer, and for each candidate row: if it's already in the
database, **do nothing** (not even a no-op write); if it's genuinely new,
**insert it**. There is no code path anywhere in this design that updates or
deletes a row in `observations`. Not for corrections, not for revisions, not
for anything — see "Schema" below for exactly how a GDP revision is handled
as a *new* row rather than a changed one. This is deliberate: the database
is a log of everything ever observed, not a cache of current values.

**c) The dashboard shows what the database currently holds.** Every day's
run ends by asking the database "what's the latest known value for every
series" and writing that out as `site/data/latest.json` — the same file the
static frontend already reads. The dashboard itself doesn't query the
database directly (see "Why not query the database from the browser" under
JSON export, below, for why that's a real alternative that was considered
and set aside) — but the number the dashboard shows is always exactly the
database's own answer as of the last run, never a value computed some other
way.

## Why a database, specifically

Three problems with today's architecture, all solved by the same change:

1. **Every run re-fetches full history it already has.** `pipeline.py`
   currently rebuilds `latest.json` from a fresh pull each time. A database
   flips this: a run asks "what's the latest date I have for this series?"
   and fetches only what's newer — matching what NETWORK.md already
   documents as the working pattern for the UK curve (backfill once, small
   snapshot after) and simply extending it to every series.
2. **History only exists as far back as the JSON archive goes.** The
   percentile/z-score work (V2-PLAN.md item 1) already had to solve this
   once by pulling deep history at fetch time — but that history lived only
   in memory for the duration of one run, then vanished. A database makes
   accumulated history durable and queryable, which is what percentile
   context, the correlation heatmap, and the regime map all actually need.
3. **No structured place to record data-quality findings.** Today,
   `source_status` is a pass/fail snapshot of one run. A database can hold a
   running log of gaps, outliers and staleness over time, which is the only
   way to answer "how complete is this, really" as a trend rather than a
   single number.

## Schema

One SQLite file, `data/markets.db`, four tables.

```sql
CREATE TABLE series_catalog (
    series_id           TEXT PRIMARY KEY,   -- e.g. 'curve.US.10Y', matches the data catalog's Identifier column
    category             TEXT NOT NULL,
    region                TEXT,
    description           TEXT NOT NULL,
    unit                  TEXT,
    native_periodicity    TEXT,
    source                TEXT,
    max_age_days          INTEGER,          -- staleness threshold; cadence-aware, not one global number
    status                TEXT NOT NULL,    -- 'ok' | 'stale' | 'planned' — only fetchable rows get imported here at all
    notes                 TEXT
);

CREATE TABLE observations (
    series_id        TEXT NOT NULL REFERENCES series_catalog(series_id),
    date              TEXT NOT NULL,        -- ISO 8601, the period the value describes
    vintage_date      TEXT NOT NULL,        -- the date this value was OBSERVED as of — see "Revisions" below
    value             REAL NOT NULL,
    ingested_at       TEXT NOT NULL,
    source_run_id     INTEGER REFERENCES pipeline_runs(run_id),
    PRIMARY KEY (series_id, date, vintage_date)
);
CREATE INDEX idx_obs_series ON observations(series_id, date);

-- The ONLY place "current value" is computed. Not stored, not mutated —
-- resolved fresh on every read as "the most recently observed vintage for
-- this (series, date)". Adding a later vintage changes what this view
-- returns without a single UPDATE ever touching the base table.
CREATE VIEW latest_observations AS
SELECT o.series_id, o.date, o.value, o.vintage_date, o.ingested_at
FROM observations o
WHERE o.vintage_date = (
    SELECT MAX(o2.vintage_date) FROM observations o2
    WHERE o2.series_id = o.series_id AND o2.date = o.date
);

CREATE TABLE pipeline_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    mode          TEXT,                    -- 'live' | 'sample'
    git_sha       TEXT
);

CREATE TABLE data_quality_flags (
    flag_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id    TEXT NOT NULL REFERENCES series_catalog(series_id),
    date         TEXT NOT NULL,
    flag_type    TEXT NOT NULL,            -- 'gap' | 'outlier' | 'implausible_level' | 'stale' | 'curve_inconsistency'
    detail       TEXT,
    raised_at    TEXT NOT NULL,
    resolved     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_flags_open ON data_quality_flags(resolved) WHERE resolved = 0;
```

`series_catalog` is populated once by importing the reviewed xlsx catalog's
fetchable rows (a short one-off script, not hand-typed) — the xlsx stays the
human-readable source of truth for *decisions about* sourcing; the DB table
is its machine-readable mirror for the pipeline to query against.

### Revisions — why `vintage_date` exists

GDP and CPI get revised after first release; the project's own SPEC.md
already flagged this ("the daily commit of `latest.json`... builds a dated
archive... which matters for GDP and CPI figures that get revised later").
Confirmed 2026-08-28: never overwrite, ever — a revision is new information,
not a correction to erase the old value, so it is **appended as an
additional row**, and the row that held the first-reported figure is never
touched again. `vintage_date` is what makes that possible without treating
every series as revisable: for a series that never gets revised (a price, a
yield, a policy rate), the fetch logic always writes `vintage_date = date`,
so in practice it's one INSERT per new date, exactly like any other series —
the mechanism is there but inert. Only GDP/CPI/SLOOS's fetch logic
consciously uses it: compare a newly-fetched value against
`latest_observations` for that date; if it's genuinely different, INSERT a
new row with today's date as `vintage_date`. Nothing is ever flipped,
updated, or deleted — the old row simply stops being the one the
`latest_observations` view resolves to, because a newer `vintage_date` now
exists for that `(series_id, date)`.

## Incremental update logic — insert or ignore, nothing else

Per series, each run does exactly one of two things to every candidate row
it fetches: **ignore it** (already have it) or **attach it** (genuinely
new). There is no third case.

1. `SELECT MAX(date) FROM latest_observations WHERE series_id = ?` — the
   watermark. Cheap, indexed, reads through the view so revisable series
   resolve correctly too.
2. Fetch only what's newer, using whichever of two patterns the source
   supports (this splits the existing fetchers into two camps, already
   implicit in the data catalog's "Recommended storage horizon" column):
   - **Bounded-query sources** (FRED, BIS, ECB, Bundesbank, Norges Bank —
     everything with a `startPeriod`/`cosd`-style parameter): fetch from
     `watermark - small overlap buffer` (a few days, to catch late-arriving
     revisions to recent prints) to today. Cheap, and NETWORK.md's own
     "history depth" work already established these sources' widened
     `startPeriod` values.
   - **Snapshot-only sources** (UK GLC workbooks, MOF's current-month CSV,
     Damodaran's xls files): fetch the small current file every run
     regardless of watermark — there's no bounded-query option — and rely on
     step 3 to cheaply discard whatever it already has.
3. For every fetched `(date, value)`: `INSERT INTO observations
   (series_id, date, vintage_date, value, ingested_at, source_run_id)
   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(series_id, date, vintage_date) DO
   NOTHING`. Nothing new for that date → the conflict fires → **ignored**,
   zero rows changed. Something new → **attached**, one row inserted. For
   non-revisable series `vintage_date = date`, so this alone is the entire
   update logic. For GDP/CPI/SLOOS, the fetch logic first checks whether the
   fetched value differs from what `latest_observations` currently shows for
   that date — if so it's attached with today's date as `vintage_date`
   (a revision); if not, the same `ON CONFLICT DO NOTHING` on the unchanged
   `(series_id, date, vintage_date)` handles it identically to any other
   series.
4. No UPDATE statement and no DELETE statement exists anywhere in this
   design's interaction with `observations`. That is not an implementation
   detail — it is the requirement.

## Bootstrap (one-time, not part of the daily run)

Before incremental updates make sense, every series needs its available
history pulled once. This is the same work NETWORK.md's "History depth"
section already did for percentile context — this plan generalizes it to
be the seed for the database rather than a one-run-only fetch:

- Most sources: pull full history in one run using the widened
  `startPeriod`/`cosd` values NETWORK.md already recorded.
- **UK curves (nominal, real, inflation)**: pull `glcnominalddata.zip` and
  its real/inflation equivalents once (~39MB+ each) — this is the specific
  one-time cost Marco approved earlier in this conversation. After this run,
  the daily fetch only ever touches the small current-snapshot workbook.
- **Japan**: stitch `historical/jgbcme_all.csv` (1974→prior month) with the
  current-month file, as NETWORK.md already describes.
- **Damodaran files** (US CAPE, US and non-US ERP, non-US valuation
  multiples): confirm at build time whether prior-year files are archived
  the way `ctryprem.xlsx`'s are (`ctryprem00.xls` through `ctryprem25.xlsx`
  already confirmed to exist) — if so, backfill each year found; if a file
  truly has no archive, it starts as a single current-snapshot row and
  accumulates its own history one row per day going forward, same as any
  newly-added series would.
- **Credit spreads (`BAMLC0A0CM`, `BAMLH0A0HYM2`, etc.)**: the ICE OAS
  series are capped at ~3 years regardless of the request window (confirmed
  in NETWORK.md) — bootstrap pulls what's available, and that's the ceiling
  for as long as FRED's free tier stays that way.

Run this once, by hand or as a one-off workflow dispatch — not on the daily
schedule.

### Adding a new series later

This is the "can be expanded on later" half of the requirement, and it
costs nothing extra to support because of how the schema is shaped: add one
row to `series_catalog`, run a backfill scoped to just that `series_id` (the
same bootstrap logic, called for one series instead of all 116), and the
daily run picks it up automatically from the next run onward — its watermark
query just returns nothing until the backfill has run, which is
indistinguishable from any other series before its first data point. No
migration, no touching `observations` rows that belong to any other series.
This is exactly how the six V2-PLAN.md credit-spread/SLOOS/bond-proxy series
and the newly-added Damodaran-sourced rows should be brought in when their
fetchers are built — one series at a time, never a batch rebuild.

## JSON export — decoupled from fetching

`pipeline.py` splits into two steps that no longer have to happen in the
same breath:

1. **Ingest**: run every fetcher, insert-or-ignore into `observations`, as
   above.
2. **Export**: query the database for the current state of everything and
   build `site/data/latest.json` from *that* — not from whatever the ingest
   step happened to fetch this run. `transform/returns.py`,
   `transform/curves.py`, `transform/erp.py` and the new
   `transform/percentile.py` (V2-PLAN.md item 1) all read their input as
   `SELECT date, value FROM latest_observations WHERE series_id = ? ORDER BY
   date` — full accumulated history, every time, regardless of how much of
   it came from today's fetch versus yesterday's versus the one-time
   backfill.

This split is what actually delivers "efficient updating without pulling
full histories every time": the *ingest* step is cheap and incremental, and
the *export* step is comprehensive and cheap too, because it's a local SQL
query, not a network fetch. The frontend-facing shape of `latest.json`
doesn't need to change, so `site/assets/app.js` needs no rework for this
phase.

### Why not query the database from the browser

The literal reading of "the dashboard, when opened, pulls the latest data
from the database" could mean shipping `markets.db` itself to the browser
and querying it live with something like sql.js (a WASM SQLite build),
skipping the JSON export step entirely. Considered and set aside, for two
concrete reasons rather than by default: it means shipping the whole
accumulating database file on every page load (already tens of MB after a
few years of daily history across 116+ series, and only growing, since nothing
is ever deleted), and it means reimplementing `transform/`'s derived-metric
logic — drawdown, realized vol, percentile/z-score, curve spreads — a second
time in JavaScript, in a project whose SPEC.md explicitly chose "no server
to maintain" and a Python pipeline for exactly this kind of computation.
The export step delivers the same outcome — what the dashboard shows is
always the database's own current answer, refreshed daily — without either
cost. Worth revisiting only if the frontend ever needs to show something the
daily export genuinely can't anticipate (e.g. an arbitrary user-chosen date
range against full history); nothing in the current design needs that.

## Data-quality routines

Run after every ingest, before export, results written to
`data_quality_flags` and summarized in the run log (extending the
`source_status` convention already used, not replacing it).

- **Staleness**: `today - MAX(date)` per series against `max_age_days`
  (cadence-aware — already exists as a concept, now DB-backed instead of
  computed fresh each run). Existing logic, just needs its input source
  swapped.
- **Gaps**: for a series' expected cadence, flag any interval between
  consecutive stored dates that exceeds tolerance — business-day-aware for
  daily series (a 3-day gap over a weekend isn't a gap; five missed
  business days is), calendar-aware for monthly/quarterly (a skipped
  expected month or quarter is a gap regardless of weekends).
- **Outliers**: flag a new value more than N standard deviations from that
  series' own recent period-over-period change distribution — this reuses
  the same statistics the percentile/z-score engine already computes
  (V2-PLAN.md item 1), rather than hand-tuning a bound per series. Catches
  real data errors (a misplaced decimal, a unit mix-up like the
  Damodaran-ERP fraction-vs-percent gotcha NETWORK.md already hit once)
  without false-flagging genuine volatility, since the threshold is
  self-calibrating to each series' own history rather than a fixed number.
- **Curve consistency**: within one yield curve snapshot, flag if any tenor
  differs from its curve-mates by an implausible absolute margin (catches a
  parsing bug like a stray `50.0` where `5.0` was meant — real curve shapes,
  including inversions, stay well inside this).
- **Completeness report**: after each run, count fresh-vs-stale-vs-gapped
  against the full `series_catalog`, and count open flags by type. Written
  to the run log the way `source_status` already is, so "how complete are
  we" stays visible in every Actions run rather than requiring a separate
  query.

## Sequencing

1. Schema + a one-off script importing the reviewed xlsx catalog's
   fetchable rows into `series_catalog`.
2. Refactor `fetch/sources.py`'s functions to accept a watermark and return
   only new/changed rows, rather than always returning full history —
   wrapping the existing, already-verified fetch logic, not rewriting it.
3. Bootstrap run — pull full available history for every series, once.
4. Rebuild `pipeline.py`'s export step to read from the database instead of
   from in-memory fetch results; verify `latest.json`'s shape is byte-for-
   byte compatible so the frontend needs no changes yet.
5. Data-quality routines, wired into every run.
6. Point `daily.yml` at the new ingest-then-export flow, commit
   `data/markets.db` alongside `latest.json` as today, and do one real
   end-to-end run to confirm the whole thing before trusting it.
