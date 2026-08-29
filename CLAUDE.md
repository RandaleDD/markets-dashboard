# CLAUDE.md — session anchor

Personal markets dashboard for Marco. CHF-based (Zurich), 8 regions
(US/UK/Eurozone/Germany/Switzerland/China/Japan/Norway) across equities, yield
curves, macro, currencies, commodities and valuation. **Weekly refresh from a
persistent SQLite store**, static site on GitHub Pages, no server to maintain.

Live: https://randaledd.github.io/markets-dashboard/

- `SPEC.md` — scope decisions, the sourcing table (what every category uses and
  where the permanent gaps are), architecture, roadmap. **The sourcing table is
  authoritative; don't restate it here.**
- `NETWORK.md` — what each endpoint actually returns, its quirks, and the dead
  ends already ruled out. Read it before touching `fetch/sources.py`.
- `DATABASE-PLAN.md` — why the store is append-only and how a revision is
  handled. `DATA-CATALOG.csv` is the reviewed sourcing decision per series and
  seeds `series_catalog`; `DATA-CATALOG-ruled-out.csv` records the permanent
  structural gaps.

## Architecture

    fetch/universe.py   what is tracked + how to fetch it (single source of truth)
    db/registry.py      the same thing, one row per STORED series, keyed by the
                        DATA-CATALOG.csv identifier
    db/ingest.py        watermark -> fetch only what's newer -> INSERT OR IGNORE
    db/quality.py       staleness / gaps / outliers / curve consistency -> flags
    db/export.py        latest_observations -> site/data/latest.json
    pipeline.py         ingest -> quality -> export, in that order

`data/markets.db` **is committed** — it is the accumulated history, and the
checkout is how the Actions runner gets yesterday's data instead of
re-bootstrapping. `bootstrap.py` is a one-time seed, never on the schedule.

## Current status
Last verified live run (2026-08-29): **90/121 `ok`, 1 `partial`, 3 `stale`,
27 `stubbed`, 0 `failed`.** Database: 112 series, 128,227 observations,
20.3 MiB. Data quality: 109 fresh, 3 stale, 0 missing; 7 open flags.

`stale` and `stubbed` here are expected, not a to-do list. The 3 stale are real
publication lag (Norway GDP, the Swiss monthly 10y, Shiller's CAPE file ending
2024-09) — UK GDP left that list when it moved to ONS's monthly index. The
27 stubbed are the gaps SPEC.md records as having no free source — the China
curve, six regions' inflation expectations, and non-US valuation and risk
premia. Chasing them again is wasted effort unless a new source appears;
NETWORK.md lists what has already been tried and failed.

The 7 open `data_quality_flags` are all genuine: US CPI is missing 2025-10 (the
release the US shutdown delayed), the BoE's real and inflation 2y points have a
34-week hole in the source, and the 3 stale series above.

Re-run `python3 pipeline.py --mode live` to refresh these numbers before
trusting them — this section is a snapshot and goes stale on its own.

## Working conventions
- One series/region = one entry in `fetch/universe.py`. Never hardcode a
  ticker or series ID anywhere else.
- **`observations` is append-only. No UPDATE, no DELETE, ever.** A revised GDP
  or CPI print is a NEW row with a later `vintage_date`; the first print is
  never touched, and `latest_observations` resolves to the newest vintage on
  read. `tests/test_append_only.py` greps for violations — if it fails, the fix
  is your code, not the test.
- **The stored grain is weekly.** The run is Saturday 06:00 UTC and stores each
  completed week's Friday close (or the last session before it, keeping its
  real date). Anything computed from it is therefore weekly: volatility
  annualises with sqrt(52), the windows are named in weeks, and there is no
  1-day change. Never reintroduce a daily-grain label over weekly data.
- Adding a series = one row in `universe.py`, then
  `python3 bootstrap.py --series <id>`. It never touches the other 111.
- `bootstrap.py` pulls ~89MB of BoE GLC archives. Run it once, by hand. If the
  weekly workflow ever finds `data/markets.db` missing it fails loudly rather
  than silently re-bootstrapping over accumulated history.
- Every fetcher in `fetch/sources.py` returns `None` on failure, never
  raises — the pipeline must survive individual source outages.
- `python3 pipeline.py --mode sample` regenerates synthetic data for frontend
  work without network access. It goes through the *same* ingest -> quality ->
  export phases as live mode, against its own gitignored
  `data/markets-sample.db`, so the no-network path cannot silently rot and
  synthetic numbers can never reach the real store.
- `python3 pipeline.py --export-only` rebuilds `latest.json` from what is
  already stored, with no network at all. Use it when only `transform/` or the
  export changed.
- `python3 pipeline.py --mode live` is the real thing — run it, then serve the
  site over http (`cd site && python3 -m http.server 8000`). `file://` will not
  work; the JSON fetch needs http.
- A failed fetch must degrade to `None`, never a partial or malformed value —
  the frontend's "not yet wired" label is driven by `None` in the JSON, not by
  `source_status`.
- HTTP 200 is not the same as current. Every series is age-checked against
  `MAX_AGE_DAYS` and marked `stale` if it is behind its publication cadence.
  **`stale` is a failure, not a pass.** Give any new fetcher the right cadence.
- Pass headers per-source via `_get(...)`; there is no global set that works.
  FRED breaks if you send a browser User-Agent, BoE and MOF break if you don't.
- Prefer one request per curve over one per tenor, and bound big payloads with
  `startPeriod`. Per-tenor fetching turned a single transient failure into a
  `partial` curve, and unbounded ECB/BIS history hit read timeouts.
- Every displayed number must state its definition — contract and unit for
  commodities, real-vs-nominal and YoY-vs-annualised for GDP, tenor and index
  basis for inflation expectations. An unlabelled number that isn't comparable
  to the ones beside it is a reporting error, not a data point.
- Derived spreads must take both legs from the same source and vintage. ECB's
  German yield differs from the Bundesbank's, so mixing them would put that
  methodology gap into the spread.
- `db/export.py` must set `out["source_status"] = status` before returning —
  `empty_payload()` creates its own empty dict, so forgetting this silently
  ships a payload with no status block. Same for `data_quality`, which
  `pipeline.py` fills in after the export returns.
- `weekly.yml` commits both `site/data/latest.json` and `data/markets.db` on
  every run, so expect merge conflicts on both when pushing local work. Both
  are generated output: take your regenerated version, don't hand-merge them.
  For the database that means re-running the pipeline, never resolving hunks.
- Never reference `assets/*` without the version query string. Pages caches
  assets for 10 minutes, so unversioned URLs can pair fresh HTML with stale JS
  and render a panel blank with nothing wrong in the code.
  `stamp_asset_versions()` maintains these; don't strip them by hand.
- Equity index *levels* deliberately carry no percentile annotation — a price
  percentile on a trending series is always near 100th and says nothing.
  Volatility and drawdown carry it instead. This is accepted, not a gap.
- No Node on this machine (`brew install node` fails on a simdjson bottle).
  To actually execute `site/assets/app.js`, use `osascript -l JavaScript` with
  a DOM shim — `python3 tools/render_check.py` does this and asserts every
  table's column headings still line up with the cells under them. Run it
  after touching `app.js` or after renaming anything in the payload: nothing
  else catches a shifted column, because the page still renders and still
  looks plausible. macOS-only, so it is a tool, not a CI test.
