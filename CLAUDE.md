# CLAUDE.md — session anchor

Personal markets dashboard for Marco. CHF-based (Zurich), 8 regions
(US/UK/EZ/DE/CH/CN/JP/NO; IN/BR for macro only) across equities, curves, macro,
FX, commodities and valuation. Weekly refresh from an append-only SQLite store,
static site on GitHub Pages. Live: https://randaledd.github.io/markets-dashboard/

Kept short on purpose: it is loaded into every session. **The reasoning behind
each rule below is in SPEC.md, "Appendix — working notes"** — read the entry
before changing the thing it covers. SPEC.md also holds the sourcing table
(authoritative), the architecture, and the endpoint appendix (User-Agent trap,
parsing traps, dead ends) — read that before touching `fetch/sources.py`.
`data/DATA-CATALOG.csv` is the reviewed sourcing decision per series (170 KB:
grep it, don't read it whole).

## Where things live

    fetch/universe.py   what is tracked + how to fetch it (single source of truth)
    db/registry.py      one row per STORED series, keyed by the catalog identifier
    db/ingest.py        watermark -> fetch only what's newer -> INSERT OR IGNORE
    db/quality.py       staleness / gaps / outliers / basis breaks -> flags
    db/export.py        latest_observations -> site/data/latest.json (minified)
    db/catalog_sync.py  what IS stored -> data/DATA-COVERAGE.csv
    publish.py          sync from / publish to the `data` branch, verify live
    pipeline.py         sync -> ingest -> quality -> export -> coverage -> publish

- **Main holds code and reviewed prose only.** `data/markets.db`,
  `site/data/latest.json` and `data/DATA-COVERAGE.csv` are gitignored and live
  on the `data` branch: ONE parentless commit, replaced on every publish with
  `--force-with-lease` against `refs/markets/data-base`. Never commit them to
  main and never give `data` a history. Local snapshots: `data/history/` (8).
- `python3 pipeline.py --mode live` downloads the published store if newer,
  ingests, and publishes (`--no-publish`, `--no-verify` opt out). It refuses to
  replace a local store with unpublished rows, and stops if there is no store.
  `python3 publish.py --check` says whether the live site is current.
- `weekly.yml` (Sat 06:00 UTC) runs the same pipeline and deploys itself;
  `pages.yml` deploys on pushes to main (`site/**`) or `data`.
- `Update Dashboard.command` is Marco's double-click entry point. Keep it
  working and its output in plain English.
- `--mode` defaults to `sample`, and every mode writes the same
  `site/data/latest.json` — always write `--mode live --export-only`.
  `publish.py` refuses sample payloads (`is_sample`).
- Preview over http (`cd site && python3 -m http.server 8000`); `file://`
  breaks the fetch. No Node here: after touching `app.js` or renaming payload
  keys, run `python3 tools/render_check.py`.

## Rules (why: SPEC.md appendix)

- **`observations` is append-only. No UPDATE, no DELETE, ever.** A revision is
  a new row with a later `vintage_date`; `latest_observations` resolves the
  newest. `tests/test_append_only.py` greps for violations — fix your code,
  not the test. It is WITHOUT ROWID with no secondary index and no per-row
  timestamp; convert an old-layout store once with `tools/rebuild_store.py`.
- **Revisable series slower than weekly are re-fetched in FULL every run**
  (`ingest.FULL_REFETCH_CADENCES`). Never "optimise" to the watermark window:
  a re-chain-linked level would splice two bases (the rebasing trap).
- **The stored grain is weekly** (each completed week's Friday close, real
  date kept). Volatility annualises with sqrt(52); no 1-day change, ever.
- One series = one entry in `universe.py`; never hardcode an id elsewhere.
  Add: write its reviewed DATA-CATALOG.csv row FIRST (identifiers must be
  unique, a test enforces it), then `python3 bootstrap.py --series <id>`.
  `bootstrap.py` is a one-time seed (~100 MB of archives), never scheduled.
- Unregistered catalog rows are removed, or set `retired` if history
  references them (`store.retire_unregistered`).
- **Fetchers return `None` on failure, never raise, never a partial value.**
  The frontend's "not yet wired" label is driven by `None`.
- **HTTP 200 is neither "current" nor "the dataflow still exists".** Every
  series is age-checked against its cadence; `stale` is a failure. When a
  series stops moving, check for a retired dataflow, and ENUMERATE an API
  rather than guessing ids. A code in a codelist is not a series.
- Pass headers per source via `_get(...)` (FRED breaks with a browser UA; BoE
  and MOF break without one). One request per curve, bounded with
  `startPeriod`.
- **Label monthly/quarterly figures by PERIOD** (`period_label`), not the
  filing date. Every displayed number states its definition (unit, real vs
  nominal, YoY vs annualised, tenor, basis).
- **Derived spreads take both legs from one source and vintage.** The euro and
  sterling IG spreads are the stated exception: constructed, yield-to-worst
  not OAS, never in the US column, no history before 2026-09-21; euro leg is
  ECB AAA `G_N_A`, not all-ratings.
- **Damodaran: country files are MEDIANS, regional files are CAP-WEIGHTED
  aggregates** — never mix, never use the regional plain `Trailing PE` mean.
  Aggregate row is `Grand Total` or `Total Market`.
- **Swiss GDP is SECO's sport-event-adjusted series** (SNB `gdprpq`, needs
  `fromDate`; dates arrive as `1980-Q2`). **The Swiss curve is SNB
  `rendeiduebd`** (`10J` tenors, monthly batch, 10y topped up from RSS).
- **The China curve is the one scrape** (ChinaBond): match header and curve
  by NAME; >365-day queries return an empty 200, so zero rows = failure.
- **Euro sovereign spreads are monthly and always will be.**
- `check_basis_break` judges a rate (`Series.is_rate`) on pp AND share of
  history restated, a level on relative size.
- **A source switch that changes what a series MEANS** (quantity, frequency,
  index base) needs `tools/purge_series.py` and a reseed — never for a revision.
- **A quality flag closes itself when its condition clears**; a check that did
  not run closes nothing, and a windowed check never closes an older finding.
- Never reference `assets/*` without the `?v=` stamp (`stamp_assets.py` keeps
  them; the deploy re-stamps).
- The price-level chart rebases on ONE common month matched by date, windows
  in MONTHS. Equity index levels carry no percentile annotation (accepted).
- `export.py` must set `source_status` (and `pipeline.py` `data_quality`)
  before returning.
