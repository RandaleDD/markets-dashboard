# CLAUDE.md — session anchor

Personal markets dashboard for Marco. CHF-based (Zurich), 8 regions
(US/UK/Eurozone/Germany/Switzerland/China/Japan/Norway) across equities, yield
curves, macro, currencies, commodities and valuation. **Weekly refresh from a
persistent SQLite store**, static site on GitHub Pages, no server to maintain.

Live: https://randaledd.github.io/markets-dashboard/

- `SPEC.md` — scope decisions, the sourcing table, the architecture (why the
  store is append-only, how a revision is handled), the roadmap, and an
  **endpoint reference appendix**: the User-Agent trap, per-source parsing
  traps, the BoE archive traps, and the dead ends. Read that appendix before
  touching `fetch/sources.py`. **The sourcing table is authoritative; don't
  restate it here.**
- `data/DATA-CATALOG.csv` — the reviewed sourcing decision per series, and
  the live mirror of what the database holds: `db/catalog_sync.py` rewrites
  its coverage columns after every run. It seeds `series_catalog`. Permanent
  structural gaps are rows in it like any other, marked `no source found`
  with the reason and the date last checked in their notes — Swiss and
  Norwegian inflation expectations, where neither government issues
  inflation-linked debt, so there is nothing to source.

## Architecture

    fetch/universe.py   what is tracked + how to fetch it (single source of truth)
    db/registry.py      the same thing, one row per STORED series, keyed by the
                        DATA-CATALOG.csv identifier
    db/ingest.py        watermark -> fetch only what's newer -> INSERT OR IGNORE
    db/quality.py       staleness / gaps / outliers / curve consistency -> flags
    db/export.py        latest_observations -> site/data/latest.json
    db/catalog_sync.py  writes what IS stored back into DATA-CATALOG.csv
    pipeline.py         ingest -> quality -> export -> sync, in that order

`data/markets.db` **is committed** — it is the accumulated history, and the
checkout is how the Actions runner gets yesterday's data instead of
re-bootstrapping. `bootstrap.py` is a one-time seed, never on the schedule.

## Current status
Last verified live run (2026-08-29): **104/122 `ok`, 7 `partial`, 2 `stale`,
9 `stubbed`, 0 `failed`.** Database: 143 tracked series, 130,542 observations,
20.9 MiB (145 series have stored rows — two are retired but keep their
history). Data quality: 141 fresh, 2 stale, 0 missing; 6 open flags.
`site/data/latest.json` is 842 KB.

None of the non-`ok` states is a to-do list:

- **2 stale** — real publication lag: Norway GDP, and Shiller's CAPE file
  ending 2024-09. Switzerland left this list on 2026-08-29 when its curve moved
  to a daily source.
- **9 stubbed** — no free source exists: the China curve, six regions'
  inflation expectations, and the two Eurozone equity panels, which are
  `descoped` rather than pending because Damodaran publishes member states with
  no bloc aggregate.
- **7 partial** — every cost-of-capital stack except the US. All have the
  risk-free and ERP legs; only the US has an IG credit spread. `missing_legs`
  in the payload names what each lacks.
- **6 open flags** — all genuine: US CPI missing 2025-10 (the release the
  shutdown delayed), a 34-week hole in the BoE's real and inflation 2y points,
  and the 2 stale series above.

Chasing the stubbed set again is wasted effort unless a new source appears;
SPEC.md's dead ends list what has been tried.

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
  `python3 bootstrap.py --series <id>` (repeatable). It backfills only the ids
  named and leaves every other stored series untouched.
- `bootstrap.py` pulls the deep archives: ~89MB of BoE GLC zips, plus ~10MB
  across 25 `ctryprem` and 5 `countrystats` year-stamped Damodaran files. All
  are `archive_kwargs` paths, so the weekly run reads only each source's
  current file and never touches them. Run bootstrap once, by hand. If the
  weekly workflow ever finds `data/markets.db` missing it fails loudly rather
  than silently re-bootstrapping over accumulated history.
- Every fetcher in `fetch/sources.py` returns `None` on failure, never
  raises — the pipeline must survive individual source outages.
- `--mode sample` regenerates synthetic data for offline frontend work through
  the *same* phases as live mode, against its own gitignored
  `data/markets-sample.db` — so the no-network path cannot rot and synthetic
  numbers never reach the real **store**.
- **`--mode` defaults to `sample`, and every mode writes the same
  `site/data/latest.json`.** A bare `--export-only` therefore overwrites the
  published payload with synthetic numbers: the separate database protects the
  store, not the JSON. Always write `--mode live --export-only`. Re-running
  `--mode live` repairs it, and `latest.json` carries `is_sample` to tell you
  which is on disk.
- `--mode live` is the real thing. To preview, serve over http
  (`cd site && python3 -m http.server 8000`) — `file://` breaks the JSON fetch.
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
- `weekly.yml` commits `site/data/latest.json`, `data/markets.db` and
  `data/DATA-CATALOG.csv` every run, so expect merge conflicts on all three
  when pushing local work. All are generated output: take your regenerated
  version, never hand-merge — for the database that means re-running the
  pipeline, not resolving hunks.
- `data/DATA-CATALOG.csv` is half hand-written, half generated. `db/catalog_sync.py`
  owns the coverage columns to the right and may flip `Status` between `ok`
  and `stale`; it must never touch the prose columns or a scope decision
  (`planned (v2)`, `no source found`, `exists, not free`, `descoped`).
  `tests/test_catalog_sync.py` holds that line.
- **Pushing to `main` does not publish the site.** Pages is set to build from
  a workflow, so `.github/workflows/pages.yml` is what deploys `site/`. It
  triggers on push *and* on `weekly.yml` completing — the weekly job commits
  with `GITHUB_TOKEN`, and a token-authored push cannot start another workflow,
  so the push trigger alone would never fire for the Saturday run. After a
  push, confirm the live URL changed rather than assuming it did.
- Switzerland's curve is the **one unofficial source** here (TradingEconomics,
  scraped, 2y and 10y only). The SNB retired its own curve in July 2025 with no
  successor. It returns today's value only, so history builds forward one run
  at a time, and `curve.CH.10Y` holds OECD monthly prints before the switch —
  which is why it is marked `irregular` and opts out of gap detection.
- `Update Dashboard.command` is Marco's double-click entry point: sync, fetch,
  publish, preview. Keep it working and keep its output in plain English — it
  is the one file here meant to be used without reading any code.
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
