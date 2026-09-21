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
    publish.py          commits the generated artefacts, pushes, and waits for
                        Pages to actually serve them
    pipeline.py         sync -> ingest -> quality -> export -> catalog sync ->
                        publish, in that order

`data/markets.db` **is committed** — it is the accumulated history, and the
checkout is how the Actions runner gets yesterday's data instead of
re-bootstrapping. `bootstrap.py` is a one-time seed, never on the schedule.

## Current status
Last verified live run (2026-09-21): **125/133 `ok`, 5 `partial`, 1 `stale`,
2 `stubbed`, 0 `failed`.** Database: 171 tracked series, 160k observations.
`site/data/latest.json` is ~1.14 MB.

The 2026-09-21 pass did eight requested changes and closed three long-standing
gaps in the process:

- **Swiss GDP** moved to SECO's sport-event-adjusted series (SNB `gdprpq`,
  `D1(BBIPS)`) — FIFA/UEFA/IOC book licensing revenue in Switzerland, so the
  unadjusted series spikes in tournament quarters.
- **US and Europe valuation multiples** now exist. The US was a CONFIG gap, not
  a data gap: `countrystats.xls` always had a "United States" row. Europe comes
  from Damodaran's regional files for the STOXX Europe 600 row and is a
  cap-weighted aggregate, a different statistic from the country medians and
  labelled as one.
- **Euro and sterling IG credit spreads** are CONSTRUCTED (iShares ETF yield to
  worst less a duration-matched government curve), because nothing free
  publishes them. 93bp and 108bp at launch. No history — they deepen weekly
  from 2026-09-21.

Known limits, none of them a to-do list:

- **1 stale** — Shiller's CAPE file, ending 2024-09.
- **2 stubbed** — Switzerland and China have no IG credit spread and no
  prospect of one (SNB's rating buckets died with the 2025 cut; China has no
  broad onshore IG corporate curve).
- **5 partial** — cost-of-capital stacks missing one of their two rates. CH,
  CN, JP and NO have a cost of equity but no credit spread; EZ has a cost of
  debt but no ERP (no euro-area aggregate exists).
- **Euro sovereign spreads are monthly and always will be.** The ECB `IRS`
  legs have no daily variant and no single publisher offers free daily
  per-country euro sovereign yields. A daily aggregate measure
  (`G_N_C − G_N_A`, 29bp) sits beside them.
- **4 open flags**: US CPI missing 2025-10, a 34-week hole in the BoE's real
  and inflation 2y points, and Shiller's CAPE. All three are real and none is
  fixable here.

Re-run `python3 pipeline.py --mode live` to refresh these numbers before
trusting them — this section is a snapshot and goes stale on its own.

## Working conventions
- One series/region = one entry in `fetch/universe.py`. Never hardcode a
  ticker or series ID anywhere else.
- **A revisable series slower than weekly is re-fetched in FULL every run**
  (`db/ingest.FULL_REFETCH_CADENCES` — the 9 GDP and 14 CPI series). Do not
  "optimise" this back to the watermark window. A source that re-chain-links a
  level series rescales its whole history at once; a 14-day window reaches back
  less than one quarterly observation, so the rebasing lands on the tail only
  and splices two bases into one stored series. Nothing looks wrong — the
  damage is in the growth rate computed across the seam. This is not
  hypothetical: it published Swiss GDP at 3.06% YoY against 2.63%. See SPEC.md,
  "The rebasing trap". `db/quality.check_basis_break` catches a recurrence.
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
  local payload with synthetic numbers: the separate database protects the
  store, not the JSON. Always write `--mode live --export-only`. Re-running
  `--mode live` repairs it, and `latest.json` carries `is_sample` to tell you
  which is on disk. Sample numbers cannot reach the *live site* — `publish.py`
  refuses any mode but `live`, and `publish.py --check` refuses a payload
  carrying `is_sample` — but they can and do overwrite the local file.
- **A live run publishes itself.** `pipeline.py --mode live` fast-forwards onto
  `origin/main` before fetching, and after writing the JSON it commits the
  generated artefacts, pushes, and polls the live URL until it serves the same
  `generated_at`. The file on disk and the file on the site are the same file
  at two points in time, so a run that stops locally leaves two dashboards
  disagreeing. `--no-publish` opts out; `--no-verify` pushes without waiting.
  `python3 publish.py --check` answers "is the live site current?" on its own,
  and exits non-zero when it is not.
- **Publishing commits the generated artefacts and nothing else.** Never
  `git add -A` there: `publish.GENERATED` is the whole list, plus
  `site/index.html` and *only* when the asset stamp is the one thing that
  changed in it. Code is committed deliberately, not swept into a data
  refresh, and `tests/test_publish.py` holds that line against a real
  throwaway checkout. It also stands down inside GitHub Actions, where
  `weekly.yml` does its own commit — two committers would race.
- `--mode live` is the real thing. To preview, serve over http
  (`cd site && python3 -m http.server 8000`) — `file://` breaks the JSON fetch.
- A failed fetch must degrade to `None`, never a partial or malformed value —
  the frontend's "not yet wired" label is driven by `None` in the JSON, not by
  `source_status`.
- **A quality flag closes itself when its condition clears.** `db/quality`
  re-checks every run and resolves any open flag it no longer finds; the row is
  kept with its original `raised_at`, so the history stays readable. Two things
  it must never do, both held by `tests/test_flag_resolution.py`: a check that
  did not run (no data, too few observations to calibrate) closes nothing, and
  a windowed check never closes a finding OLDER than the window it examined —
  otherwise a gap that simply aged past `GAP_WINDOW_DAYS` would be declared
  fixed by a check that had stopped looking at it. A permanently-red indicator
  is one you learn to scroll past, so **an open flag means currently true**.
- **HTTP 200 does not mean the dataflow still exists.** Eurostat's
  `prc_hicp_manr` and the ECB's `ICP` dataset were both discontinued on
  2026-02-04 and both still answer every query normally, frozen at 2025-12.
  Their successors need different dimension codes, not just a different id
  (`coicop18=TOTAL` not `coicop=CP00`; `DATA_PROVIDER=4D0` not `4`). When a
  series stops moving, check whether the dataflow was retired before assuming
  the data is late — and when a series appears to vanish from an enumerable
  API, ENUMERATE rather than guessing ids. Guessing missed the SNB's successor
  cube seven times; listing the topic found it immediately.
- HTTP 200 is not the same as current. Every series is age-checked against
  `MAX_AGE_DAYS` and marked `stale` if it is behind its publication cadence.
  **`stale` is a failure, not a pass.** Give any new fetcher the right cadence.
- Pass headers per-source via `_get(...)`; there is no global set that works.
  FRED breaks if you send a browser User-Agent, BoE and MOF break if you don't.
- Prefer one request per curve over one per tenor, and bound big payloads with
  `startPeriod`. Per-tenor fetching turned a single transient failure into a
  `partial` curve, and unbounded ECB/BIS history hit read timeouts.
- **A quarterly or monthly figure is labelled by its PERIOD, not by the date it
  is filed under.** Agencies date an observation to the first day of the period
  it covers, so Q2 2026 GDP is stored as `2026-04-01` and July's CPI as
  `2026-07-01`. Showing only that date reads as months-stale data when it is
  the newest release there is. `db/export._period_label` derives `period_label`
  beside `as_of`, and the Macroeconomics tables show both.
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
- **Pushing to `main` does not publish the site by itself.** Pages is set to
  build from a workflow, so `.github/workflows/pages.yml` is what deploys
  `site/`. It triggers on push *and* on `weekly.yml` completing — the weekly
  job commits with `GITHUB_TOKEN`, and a token-authored push cannot start
  another workflow, so the push trigger alone would never fire for the Saturday
  run. The push trigger is also filtered to `site/**`: a commit that changes
  only the pipeline deploys nothing, which is why `publish.py` always has
  `site/data/latest.json` in the push (its `generated_at` changes every run).
  Confirming, not assuming, is `publish.verify()`'s job — it polls the live
  payload, with a cache-busting query string because Pages serves
  `max-age=600` and an edge cache will happily answer with the old file.
- **The China curve is the one scrape here** (ChinaBond, 5y/10y/30y, no 2y).
  Parse it by matching the header row by NAME and the government curve by its
  name string — the response carries three curves and matching on position
  would silently return a corporate one. A query wider than 365 days returns
  HTTP 200 with a headers-only page, so zero rows means failure, and the
  backfill walks one calendar year per request.
- **Swiss GDP is the SPORT-EVENT ADJUSTED series** (SNB cube `gdprpq`,
  `D0(WMF),D1(BBIPS)`, which is SECO's `cssa`). FIFA, UEFA and the IOC are
  domiciled in Switzerland and book their licensing revenue there, so the
  ordinary series spikes in tournament quarters on revenue that is not Swiss
  economic activity — 2026-Q2 printed 2.63% YoY unadjusted against 2.15%
  adjusted, and the sign of the gap flips between quarters, so it does not
  cancel out of a growth rate. Eurostat cannot serve this at any dimension
  combination (SPEC.md, dead ends), which is why CH alone among the eight is
  not on `namq_10_gdp`. It is the one region carrying an extra adjustment, so
  it is the one region with a `basis` label beside its number in the GDP table.
  The cube has two traps of its own, both unlike the Swiss curve's: no
  `fromDate` silently returns five quarters, and dates arrive as `1980-Q2`
  rather than ISO. See `fetch_snb_gdp`.
- **Switzerland's curve is official again.** The SNB never retired it; it moved
  to cube `rendeiduebd` (`dimSel=D0(CHF)`, tenors in years-German — `10J`, not
  `10Y`), which retired the TradingEconomics scrape on 2026-09-13. The cube
  publishes daily data in a MONTHLY BATCH, so it carries the `monthly_batch`
  cadence and the 10y alone is topped up from the SNB's RSS feed (`R10`) to
  stay current between batches. `curve.CH.*` is no longer `irregular` and gap
  detection applies normally.
- **The euro and sterling IG credit spreads are CONSTRUCTED, not sourced.**
  An iShares ETF's yield to worst less a government curve interpolated to that
  ETF's own duration. Nothing free publishes these — SPEC.md's dead ends has
  the enumeration that proves it rather than assuming it. Three things follow:
  they are **yield-to-worst spreads, not OAS**, and must never share a column
  with the US figure; their two legs come from **different publishers**, which
  this project otherwise refuses for a spread; and they have **no history**,
  because the iShares endpoint is a snapshot — they deepen one weekly point at
  a time from 2026-09-21. The euro government leg is the ECB **AAA** curve
  (`G_N_A`), not the all-ratings curve the Eurozone sovereign row uses: the
  all-ratings blend already contains peripheral sovereign risk, which is not
  corporate credit risk and must not net out of a corporate spread (93bp
  against 68bp). Two curves, two purposes, each right for its own.
- **`ER00`, `IBOXX*` and friends appear in ECB codelists but 404 on data.**
  `CL_PROVIDER_FM_ID` enumerates ~120 licensed index codes the ECB does not
  disseminate. A code existing in a codelist is not a series existing.
- **Damodaran publishes two different statistics and they must not be mixed.**
  `countrystats.xls` gives the MEDIAN across companies in a country;
  `peEurope`/`pbvEurope`/`vebitdaEurope` give CAP-WEIGHTED AGGREGATES across a
  region. For the US those read 22.6 and 26.6, and the regional files' plain
  `Trailing PE` column is an unweighted mean reading 57.9 — never use it. The
  aggregate row is `Grand Total` in some files and `Total Market` in others.
  The valuation payload carries a per-region `basis` so the difference travels
  with the figure.
- **`check_basis_break` uses a different scale for a rate than for a level.**
  A level is judged on the RELATIVE size of a partial restatement
  (`BASIS_BREAK_PCT`, 0.25%); a series whose unit is already a percentage
  (`registry.Series.is_rate` — the six CPI `% YoY` series) is judged on
  percentage points AND on the share of history restated. The ratio test is
  meaningless on a rate: a routine 0.1pp revision to a 3.3% inflation print is
  −3.03%, which is how `cpi.EZ` spent two days flagged for an ordinary
  correction. The SHARE half is the load-bearing one — the only two rate-series
  events on record are both ~0.1pp, and what separates the real one (`cpi.DE`,
  Eurostat's ECOICOP v2 switch, 84% of history restated) from the false one
  (`cpi.EZ`, 0.3%) is how much moved, not how far.
- **`data/DATA-CATALOG.csv` identifiers must be unique**, and
  `tests/test_catalog_sync.py` now enforces it against the committed file. Seven
  pairs accumulated in Sep 2026: registering a series and running the pipeline
  before hand-writing its reviewed row makes `catalog_sync` append a generated
  one, and nothing ever removes it. It is invisible from the sync's own output
  — both rows get refreshed forever — and `db/catalog.read_csv_rows` keys a
  dict by identifier, so the LAST row wins and the generated metadata silently
  displaces the reviewed prose in `series_catalog`. **Write the reviewed row
  before the first run, not after.**
- **A source switch that changes what a series MEANS cannot be fixed by
  appending**, and `tools/purge_series.py` is the hand-run repair for it. New
  rows only displace old ones on dates they share, so differing grids
  interleave; where they do share a date they usually share a `vintage_date`
  too, and ON CONFLICT DO NOTHING then keeps the OLD value. Purge and reseed
  when the quantity, frequency or index base changes — never for a revision,
  which is what the append-only rule exists to protect.
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
