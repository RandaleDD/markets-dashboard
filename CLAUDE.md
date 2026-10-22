# CLAUDE.md

Marco's personal markets dashboard: CHF-based, regions US/UK/EZ/DE/CH/CN/JP/NO
(+IN/BR macro only); equities, curves, macro, FX, commodities, valuation.
Weekly append-only SQLite store → static site on GitHub Pages
(https://randaledd.github.io/markets-dashboard/).

**The why behind every rule is in SPEC.md (Scope, Architecture); read it
before changing what a rule covers.** SPEC.md also has the authoritative
sourcing table and the endpoint appendix (read before touching
`fetch/sources.py`).
`data/DATA-CATALOG.csv` = reviewed sourcing per series; 170 KB, grep it.

## Layout

    fetch/universe.py   what is tracked + how to fetch (single source of truth)
    fetch/sources.py    one fetcher per source
    db/registry.py      one row per stored series, keyed by catalog identifier
    db/ingest.py        watermark -> fetch newer -> INSERT OR IGNORE
    db/quality.py       staleness/gaps/outliers/basis breaks -> flags
    db/export.py        latest_observations -> site/data/latest.json (minified)
    db/catalog_sync.py  stored coverage -> data/DATA-COVERAGE.csv
    publish.py          sync from / publish to `data` branch; verify live
    pipeline.py         sync -> ingest -> quality -> export -> coverage -> publish
    tools/              rebuild_store, purge_series, render_check

## Data flow

- Main = code + reviewed prose. `data/markets.db`, `site/data/latest.json`,
  `data/DATA-COVERAGE.csv` are gitignored; they live on branch `data` as ONE
  parentless commit (plus a copy of `data-relay.yml`), replaced each publish via
  `--force-with-lease` against `refs/markets/data-base`. Never commit them to
  main; never give `data` history. Local snapshots: `data/history/` (keeps 8).
- `python3 pipeline.py --mode live`: downloads newer published store, ingests,
  publishes, waits for the live site (`--no-publish`, `--no-verify`). Refuses
  to overwrite unpublished local rows; stops if no store exists.
  `python3 publish.py --check` → "congruent" if live is current.
- Publishing force-pushes, which auto mode may block in Claude sessions; if so,
  Marco runs `Update Dashboard.command` (his double-click entry point — keep it
  working, output in plain English).
- `weekly.yml` (Sat 06:00 UTC) runs the pipeline and deploys itself. `pages.yml`
  deploys main on `site/**` pushes or dispatch; a push to `data` runs
  `data-relay.yml`, which dispatches `pages.yml` on main (the github-pages
  environment accepts main only; no `paths:` filter, which never matches a
  force-pushed orphan commit).
- `--mode` defaults to `sample` and writes the same `latest.json`: use
  `--mode live --export-only`. Publishing refuses `is_sample` payloads.
- Preview: `cd site && python3 -m http.server 8000` (not `file://`). After
  touching `app.js` or payload keys: `python3 tools/render_check.py` (no Node).
- Main's history was rewritten 2026-10-22 to drop old data copies; pre-rewrite
  bundle in `data/history/`.

## Rules

- **`observations` is append-only: no UPDATE/DELETE, ever.** Revisions are new
  rows with later `vintage_date`; `latest_observations` picks the newest.
  `tests/test_append_only.py` enforces it — fix the code, not the test. Table is
  WITHOUT ROWID, no extra index, no per-row timestamp (`tools/rebuild_store.py`
  converts old layouts).
- **Revisable series slower than weekly are re-fetched in FULL each run**
  (`ingest.FULL_REFETCH_CADENCES`) — never narrow to the watermark (rebasing
  trap: splices two index bases).
- **Grain is weekly** (Friday close, real date kept): vol × sqrt(52), windows in
  weeks, no 1-day change.
- New series: one `universe.py` entry (no ids hardcoded elsewhere); write its
  reviewed catalog row FIRST (ids unique, tested); then
  `python3 bootstrap.py --series <id>`. Bootstrap is one-time, never scheduled.
- Unregistered catalog rows are removed, or `retired` if history references them.
- **Fetchers return `None` on failure** — never raise, never partial values
  (`None` drives the "not yet wired" label).
- **HTTP 200 ≠ current ≠ dataflow alive.** Series are age-checked per cadence;
  `stale` is a failure. If a series stops moving, suspect a retired dataflow;
  ENUMERATE APIs, don't guess ids; a codelist entry isn't a series.
- Headers per source via `_get(...)` (FRED breaks with a browser UA, BoE/MOF
  without). One request per curve, bounded by `startPeriod`.
- Label monthly/quarterly data by PERIOD (`period_label`). Every number states
  its definition (unit, real/nominal, YoY/annualised, tenor, basis).
- Spreads take both legs from one source/vintage. Exception: euro/sterling IG
  spreads are constructed YTW (not OAS, never in the US column, history from
  2026-09-21); euro leg is ECB AAA `G_N_A`.
- Damodaran: country files = MEDIANS, regional = CAP-WEIGHTED; never mix, never
  use the regional `Trailing PE` mean; total row is `Grand Total`/`Total Market`.
- Swiss GDP = SECO sport-event-adjusted (SNB `gdprpq`; needs `fromDate`; dates
  like `1980-Q2`). Swiss curve = SNB `rendeiduebd` (`10J` tenors, monthly
  batch, 10y topped up via RSS).
- China curve is the only scrape (ChinaBond): match header/curve by NAME;
  >365-day queries return an empty 200, so zero rows = failure.
- Euro sovereign spreads are monthly, permanently.
- `check_basis_break`: rates (`Series.is_rate`) judged on pp AND share
  restated; levels on relative size.
- Source switch changing what a series MEANS → `tools/purge_series.py` +
  reseed. Never for a revision.
- Quality flags self-close when cleared; a check that didn't run closes
  nothing; windowed checks never close older findings.
- `assets/*` always carry the `?v=` stamp (`stamp_assets.py`; deploy re-stamps).
- Price-level chart: one common base month matched by date; windows in MONTHS.
  Equity levels get no percentile annotation (by design).
- `export.py` sets `source_status`, `pipeline.py` sets `data_quality`.
