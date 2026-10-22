# Markets Dashboard — Spec

Design doc: scope, where every number comes from, how it is built, and why.
Live: https://randaledd.github.io/markets-dashboard/. Companions: `CLAUDE.md`
(the rules, one line each; the reasons are here) and `data/DATA-CATALOG.csv`
(reviewed sourcing per series, incl. permanent gaps marked `no source found`
with reason and date checked; it seeds `series_catalog`). What is actually
stored is the generated `DATA-COVERAGE.csv` on the `data` branch.

## Governing constraint

**Descriptive and historical, never prescriptive.** A percentile or z-score
against a series' own history is in scope. Composite scores, cheap/expensive
labels and buy/sell framing are not, anywhere: the cost-of-capital panel shows
its legs rather than one figure, and the correlation heatmap recommends nothing.

## Scope

- **Regions:** US, UK, Eurozone, Germany, Switzerland, China, Japan, Norway at
  full depth (`universe.REGIONS`); MSCI EM as a proxy under `EM`. **India and
  Brazil are macro-only** (`universe.MACRO_REGIONS`): GDP, CPI, policy rates and
  IMF forecasts on the Macroeconomics tab, no Regional Snapshot. Iterate
  `MACRO_REGIONS`/`MACRO_ORDER` on that tab, `REGIONS`/`REGION_ORDER` elsewhere;
  region charts take at most eight lines (`MAX_LINES`, eight palette colours).
- **Refresh weekly**, Saturday 06:00 UTC, on each completed week's Friday close
  (last session before it, real date kept). Monthly/quarterly/annual series keep
  their own grain. No intraday or daily data. Everything derived is therefore
  weekly: volatility annualises with sqrt(52) and is labelled 4w/13w,
  correlation windows are 52w/104w, and there is no 1-day change.
- **Eurozone and Germany are two curves on purpose.** EZ = ECB all-bonds curve
  (`G_N_C`, a blend of euro sovereigns); DE = Bundesbank Bund curve. ECB AAA
  (`G_N_A`) tracks the Bund within basis points (3.28 vs 3.22, 2026-08-27) and
  would duplicate it.
- **Euro sovereign spreads (FR/IT/ES)** use the ECB's own German series as the
  benchmark leg, not the Bundesbank's (3.07 vs 3.22): both legs from one
  source. Not labelled "periphery". Monthly, permanently (dead ends); a daily
  aggregate `G_N_C − G_N_A` sits beside them.
- Germany has no policy rate of its own; the export mirrors the ECB's.
- China equities: CSI 300 (via CNY tracker ETF `510300.SS`; Yahoo has no index
  history) and Hang Seng, not merged.
- Commodities: Brent and WTI, both named; natural gas twice (Henry Hub, TTF —
  different markets and units).
- Equity returns in local currency by default. **Currency conversion converts
  everything or nothing**: levels, returns, drawdowns and vol are rebuilt from
  converted history; percentiles are dropped (measured on the local
  distribution); a banner states the currency.
- Equity index *levels* carry no percentile (always ~100th on a trending
  series); volatility and drawdown carry it instead.
- **Every figure states its definition**: exchange/contract/unit for
  commodities; real vs nominal, chain-linked, SA, YoY vs annualised for GDP;
  tenor and basis for inflation expectations. Monthly/quarterly figures are
  labelled by PERIOD (`period_label`) beside `as_of`, because agencies date an
  observation to the period's first day (Q2 GDP = `2026-04-01`).
- **Cost of capital:** risk-free = nominal 10y (Damodaran's ERP is measured
  against a nominal yield, so a real one would remove inflation twice; 7 of 8
  regions publish a nominal 10y, 2 a real one). Two rates, formulas stated:
  cost of equity = rf + ERP; cost of debt = rf + IG spread. **No total, no
  WACC** (a sum of both premia describes nothing; a WACC needs leverage and tax
  assumptions not sourced). A rate is blank unless BOTH legs exist.
- **Layout:** tabs Macroeconomics (Growth & Inflation table, GDP by Region
  chart, Price Levels chart, policy rates), Equity Indices, Rates (curves, euro
  spreads, real yields, implied inflation, credit, cost of capital),
  Currencies, Commodities, Valuation (+ risk premia), Cross-Asset; plus a
  Regional Snapshot per region (no commodities). Equity and Rates open with one
  large chart; tables elsewhere carry sparklines expanding to 3M–5Y charts
  from 5y of weekly points; multiple equity lines are indexed to 100.
- **Growth & Inflation table:** real GDP, CPI, nominal GDP, IMF forecasts this
  year and next; YoY / latest-quarter-annualised switch; values and uncoloured
  arrows only, every detail in the tooltip (add new detail there). CPI is
  measured over **GDP's own quarter** (quarter-average index; `q_*` fields) so
  a row describes one period; the newest monthly print (`yoy_pct`,
  `qoq_ann_pct`) is used everywhere else. Real + CPI need not equal nominal:
  the GDP deflator is not CPI.
- **Price Levels chart:** headline NSA indices rebased to 100 at ONE common
  month matched by date (the newest release among selected regions anchors the
  window; the base is the first month every line has, so a hole moves the base
  rather than being invented). `priceLevelBlock` passes `presliced` because
  `slicePeriod` cuts each line from its own last date. Windows in MONTHS
  (`PL_PERIOD_MONTHS`, YTD from prior December). CHF view uses monthly-average
  FX computed in Python (the payload's FX history is only 5y).
- **Regional Snapshot** has nominal GDP and a 10y-yield-vs-nominal-growth panel
  (r − g headline).

## Data sourcing

What each category uses today. Per-series detail: `DATA-CATALOG.csv`.
Endpoint traps and dead ends: appendix.

| Category | Source | Notes |
|---|---|---|
| Prices, FX, commodities | Yahoo via `yfinance` | 12 indices, VIX, 8 FX pairs, 8 commodities, 2 bond-return proxies. Gold/copper derived |
| Policy rates | BIS `CBPOL`, all 9 rate-setters | Germany mirrors ECB |
| CPI | National offices: FRED (US), ONS (UK), Eurostat `prc_hicp_minr` (EZ/DE), SNB `plkopr` (CH), SSB 14710 (NO); BIS `WS_LONG_CPI` for CN, JP, IN, BR | Off BIS where possible since 2026-09-13 (BIS's newest print runs 27–57 days old). Per-region `basis` (CPI-U, UK CPI, HICP, LIK, KPI…): no single methodology exists. Index-only publishers (US, NO): rate derived. CN stays on BIS (NBS 403s foreign clients); JP (e-Stat needs a secret for 9 days' gain); IN/BR (alternatives staler). **3-month annualised rate is seasonally adjusted here** (`transform/growth`; log-additive monthly factors, prior 8 complete years, no look-ahead; vs BLS SA since 2018: corr 0.98, mean gap 0.5pp), labelled as ours |
| Price levels (chart) | Stored CPI indices; Eurostat HICP for CH/NO (`hicp.CH.index`, `hicp.NO.index`) | One methodology where possible: HICP covers EZ/DE/CH/NO and UK CPI is HICP method; US/JP/CN stay national (and include owner-occupier rent), stated on the chart |
| Real GDP | FRED (US/DE/JP), Eurostat `namq_10_gdp` (EZ), SNB `gdprpq` (CH), ONS `abmi` (UK), SSB 09190 Mainland (NO), World Bank GEM (CN), OECD `DF_QNA` (IN/BR) | All quarterly chain-linked SA. **CH is sport-event adjusted** (FIFA/UEFA/IOC revenue spikes the raw series in tournament quarters: 2026-Q2 2.63% vs 2.15% YoY; Eurostat cannot serve it), the one region with an extra `basis`. **NO is Mainland** (offshore oil made total nominal growth an energy price: +16.7% vs +3.9% annualised, 2026-Q2); IMF forecasts for NO are total-economy, marked. UK monthly GVA kept as `gdp.UK.monthly_nowcast`. Cadence `quarterly_national` (270d) |
| Nominal GDP | The published current-price series, same source as real wherever possible (FRED `GDP`, ONS `ybha`, Eurostat `CP_MEUR`, SSB, FRED `CPMNACSCAB1GQDE`, SNB `gdpap`, FRED `JPNNGDP`, GEM, OECD) | `gdp_nominal.<R>`. Not real + CPI |
| Forecasts; GDP levels USD/PPP | IMF WEO DataMapper (`NGDP_RPCH`, `PCPIPCH`, `NGDPD`, `PPPGDP`; EZ = `EURO`) | One edition for all regions. Edition stored as `imf.weo_edition` (YYYYMM, cadence `semiannual`, carries the block's staleness); years from it on are projections, exported as `projection_from`. Nominal growth forecasts derived from real growth × deflator (`NGDP_D` from IMF SDMX `IMF.RES/WEO`, EZ = `G163`); the SDMX fetcher refuses data unless its real growth matches DataMapper's (guards against mixing editions). No euro-area PPP exists |
| US curve, real yields, breakevens | FRED `fredgraph.csv` | `DGS*`, `DFII*`, `T5YIE`/`T10YIE`/`T5YIFR`; 1y expectation = Cleveland Fed `EXPINF*`, badged model-implied |
| UK curve, real, implied inflation | BoE GLC workbooks | History to 1979 via one-time archive pull |
| EZ curve | ECB `YC` all-bonds | |
| Euro sovereign spreads | ECB `IRS` per-country long-term rates | Monthly; spread derived at export |
| DE curve | Bundesbank daily Bund term structure | |
| JP curve | MOF JGB CSV + 1974 archive | |
| NO curve | Norges Bank `GOVT_ZEROCOUPON` | To 10y; no 30y published |
| CH curve | SNB cube `rendeiduebd` (`D0(CHF)`) + SNB RSS `R10` | History to 1988. Daily data delivered in a monthly batch (cadence `monthly_batch`); RSS keeps the 10y current between batches |
| CN curve | ChinaBond `pbc/historyQuery`, **scraped** | 5y/10y/30y from 2006, no 2y (3y not interpolated). The only scrape. Validated vs OECD `CHN.M.IRLT` |
| EZ inflation expectations | ECB Survey of Professional Forecasters | Badged **survey**, never stacked with market rows. 1y/2y built from calendar-year forecasts; the "5y" is the longer-term mean (4–5y, stated) |
| CH/CN/JP/NO inflation expectations | — | None free. CH/NO permanent (no inflation-linked debt); CN refused (only a diffusion index) |
| Credit OAS | ICE BofA via FRED (US IG/HY, Euro HY, EM corp) | Rolling ~3y only (licensing). OAS is free for USD only |
| Euro & sterling IG spreads | **Constructed:** iShares IEAC/SLXX yield to worst − govt curve at the fund's duration (ECB AAA `G_N_A`; stored BoE curve) | **YTW, not OAS**, never in the US column; legs from different publishers; snapshot endpoint, so history starts 2026-09-21. AAA not all-ratings: the blend already holds sovereign risk (93bp vs 68bp) |
| Corporate − govt (non-OAS) | FRED `BAMLC0A0CMEY` − US 10y; Bundesbank BBSIS | US and DE only, own column, never summed into the stack. Others unavailable with recorded reasons |
| US valuation | Shiller CAPE; Damodaran implied ERP (FCFE) | Shiller's file ends 2024-09 → `stale` |
| Non-US risk premia | Damodaran `ctryprem` | UK/DE/CH/CN/JP/NO from 2000; stores the country premium (0 for Aaa); export adds `erp.US` back. No EZ aggregate |
| Valuation multiples | Damodaran `countrystats` (MEDIANS: P/E, P/B, P/S, EV/EBITDA) for US + six; regional `peEurope`/`pbvEurope`/`vebitdaEurope` for Europe (CAP-WEIGHTED, STOXX 600 row) | From 2020 only (earlier vintages publish means). Never mix the two statistics (US: 22.6 median vs 26.6 aggregate); payload carries a per-region `basis`. No Europe P/S; no EZ aggregate |

No single free source covers this; the spread of sources is by design.

**Known permanent gaps:** CH and CN have no IG credit spread (SNB rating
buckets ended 2025; no broad onshore IG curve in China) → cost of debt
`stubbed`; CH/CN/JP/NO lack a credit spread and EZ lacks an ERP → those
cost-of-capital rows are `partial`. US CPI 2025-10 was never published. Run
`python3 pipeline.py --mode live --no-publish` for current counts.

## Architecture

    fetch/universe.py   what is tracked + how to fetch (single source of truth)
    fetch/sources.py    one fetcher per source; None on failure, never raises
    db/registry.py      one row per STORED series (splits panels, dedupes legs)
    db/catalog.py       DATA-CATALOG.csv x registry -> series_catalog
    db/ingest.py        watermark -> fetch newer -> INSERT OR IGNORE
    db/quality.py       staleness, gaps, outliers, curve, basis breaks -> flags
    db/export.py        latest_observations + transform/ -> latest.json
    db/catalog_sync.py  stored coverage -> DATA-COVERAGE.csv
    publish.py          sync from / publish to the `data` branch; verify live
    stamp_assets.py     ?v= content hashes in index.html (also at deploy)
    pipeline.py         sync -> ingest -> quality -> export -> coverage -> publish
    bootstrap.py        one-time deep seed; never scheduled

SQLite store → JSON export → static frontend on GitHub Pages; GitHub Actions
runs it weekly. No server.

**Ingest and export are separate** so every derived metric (drawdown, vol,
percentiles, spreads) is computed over the full stored history while the fetch
stays incremental. Shipping the DB to the browser (sql.js) was rejected: it
grows every page load and would duplicate `transform/` in JavaScript.

### The store is append-only

No UPDATE or DELETE ever touches `observations` (`tests/test_append_only.py`).
Each candidate row is either ignored (`ON CONFLICT DO NOTHING`) or attached.
The store is a log of everything observed; `latest_observations` is the only
place a "current value" exists.

**Revisions** (GDP, CPI): a changed value is a new row with today's
`vintage_date`; the first print is never touched and the view resolves the
newest. Non-revisable series write `vintage_date = date`. Exception: a
future-dated first print (IMF projections to 2031) is stamped `min(date,
today)`, or it would outrank every later edition forever. IMF projection series
are exempt from `check_basis_break` (`Series.has_projections`), which every new
edition would trip.

**Changing what a series MEANS** (quantity, frequency, index base) cannot be
fixed by appending — differing grids interleave, and shared dates keep the old
value under ON CONFLICT. Use `tools/purge_series.py` and reseed. Never for a
revision.

**Layout:** `observations` is WITHOUT ROWID (rows live in the PK b-tree), with
no secondary index (the PK's `(series_id, date)` prefix serves all lookups) and
no per-row timestamp (`source_run_id` → `pipeline_runs`). 170k rows = 9.7 MB,
1.7 MB gzipped. `tools/rebuild_store.py` converts an old layout once, verifying
the copy. Daily grain was rejected: 98.7 MB at first commit.

Catalog rows the registry no longer produces are removed, or set `retired` when
observations or flags reference them (`store.retire_unregistered`).

### Where the data lives

`main` holds code and reviewed prose. The store, `latest.json` and
`DATA-COVERAGE.csv` are gitignored and published on the **`data` branch: one
parentless commit** (`markets.db.gz`, `latest.json`, `DATA-COVERAGE.csv`, plus
a copy of `data-relay.yml`), replaced each publish. The store is append-only, so
the current file already holds every value and revision; old copies online
served no purpose and caused merge conflicts on generated files. Main's
history was rewritten 2026-10-22 to drop 44 committed DB versions (pre-rewrite
bundle kept in `data/history/`).

- **Concurrency:** each push is `--force-with-lease` against
  `refs/markets/data-base`, the data commit the local store was built on. A
  publisher that lost a race is refused and re-runs; no rows are overwritten.
- **Sync** (before every live run): fast-forward main; download the published
  store if newer; refuse to replace a local store holding unpublished rows
  (sources like the Swiss RSS top-up cannot be re-fetched for a past week). A
  live run with no store stops rather than re-bootstrapping.
- **Snapshots:** each checkout keeps 8 rolling gzipped copies in
  `data/history/` — the only version history, local by design.
- `publish._compact` runs `git gc` once loose objects pass 50 MB (auto-gc
  counts objects, not bytes).

### Deployment

Pages builds from a workflow; nothing reaches the URL otherwise. The site is
main's `site/` + the data branch's `latest.json`, re-stamped at deploy.

- `weekly.yml` runs the pipeline (which publishes `data`) and deploys itself:
  a push made with `GITHUB_TOKEN` cannot start another workflow.
- `pages.yml` deploys main on `site/**` pushes or dispatch. A push to `data`
  runs `data-relay.yml` from the data commit (GitHub reads push workflows from
  the pushed commit), which dispatches `pages.yml` on main because the
  `github-pages` environment accepts main only. The relay has no `paths:`
  filter: on a force-pushed parentless commit it matched nothing, and the
  first Mac publish (2026-10-22) never deployed.
- `publish.verify()` polls the live payload (cache-busted; Pages serves
  `max-age=600`) until it carries this run's `generated_at`.
- Asset URLs always carry `?v=<hash>`: with 10-minute caching, unversioned URLs
  can pair new HTML with old JS and blank a panel.

### Revisable slow series are re-fetched in full (the rebasing trap)

A source can restate its whole history at once (FRED re-chain-linking, a CPI
rebase). Ingest re-asks `OVERLAP_DAYS = 14` before the watermark — several
weekly points but less than one quarterly one — so a rebasing was caught only
on the newest points, splicing two bases into one series. Nothing looked wrong
except growth across the seam: 2026-09-08, Swiss GDP published 3.06% YoY vs
2.63%, euro area 4.03% annualised vs 2.55%. Two guards, both needed:

- `ingest.FULL_REFETCH_CADENCES`: revisable series slower than weekly (all GDP
  and CPI) are re-asked in full every run; unchanged rows cost nothing.
- `quality.check_basis_break`: flags a recent suffix restated by a UNIFORM
  factor (real revisions move quarters by different amounts). Levels are judged
  on relative size (`BASIS_BREAK_PCT` 0.25%); rates (`Series.is_rate`, the CPI
  `% YoY` series) on pp AND share of history restated, since a routine 0.1pp
  revision is −3% in ratio terms (`cpi.EZ` false positive, 0.3% restated, vs
  `cpi.DE` ECOICOP switch, 84%).

`check_outliers` windows by the series' stored grain (`outlier_window_days`),
not a flat 30 days that a quarterly print, dated to its quarter's start and
published ~5 months later, could never enter.

### Freshness and quality flags

HTTP 200 is not "current": every series is age-checked against its cadence
(`registry.MAX_AGE_DAYS`) and `stale` is a failure. Cadences encode
publication lag: `monthly_month_end` 100d (BIS releases the last week of the
month), `monthly_national` 95d, `monthly_lagged` 120d (ONS monthly GDP),
`monthly_batch` 45d, `quarterly_national` 270d (a quarter is dated to its
start and lands 1–2 months after it ends), `semiannual` (IMF).

Flags close themselves when their condition clears (row and `raised_at` kept;
a recurrence opens a new flag), so **an open flag means currently true**. Two
non-closures, held by `tests/test_flag_resolution.py`: a check that did not run
(`evaluated=False`: no data, too short to calibrate) closes nothing; a windowed
check (`GAP_WINDOW_DAYS`) never closes a finding older than its window
(`Findings(raised, found, evaluated, since)`).

### Adding a series

Write its reviewed `DATA-CATALOG.csv` row first (identifiers must be unique;
a duplicate's LAST row silently wins in `series_catalog`; tested), add one
entry to `fetch/universe.py`, then `python3 bootstrap.py --series <id>`. Only
the named ids are touched. Bootstrap reads the deep archives (`archive_kwargs`:
~89 MB BoE GLC zips, ~10 MB Damodaran year files); the weekly run never does.

### Working environment

- `--mode` defaults to `sample` (own gitignored `markets-sample.db`, same
  phases as live) but writes the same `latest.json`: use `--mode live
  --export-only`. `is_sample` marks it; publishing refuses it.
- `export.py` sets `source_status` and `pipeline.py` `data_quality` on the
  payload (`empty_payload()` builds a fresh dict, so forgetting ships none).
- Preview over http (`cd site && python3 -m http.server 8000`).
- No Node (`brew install node` fails). `tools/render_check.py` runs `app.js`
  under `osascript -l JavaScript` with a DOM shim and asserts every table's
  headings align with its cells — the only check that catches a shifted
  column. macOS-only, so a tool, not a CI test.
- `Update Dashboard.command` is Marco's double-click run: keep it working and
  its output plain English.
- Live runs force-push `data`; in a Claude session auto mode may block that, in
  which case Marco runs the double-click script.

## Next steps

None started; roughly in order of value.

1. **Data gaps.** Non-US dividend yields and forward multiples (highest value;
   no free source yet). The remaining expectation and IG-spread gaps are
   source-blocked, not work-blocked.
2. **Data quality.** Per-series plausibility bands (a first bad print on a
   short series passes the relative outlier check; matters most for the
   ChinaBond scrape, which has only its own 0–15% band). Unit-drift detection
   (fraction vs percent has bitten twice, at Damodaran). Cross-series checks
   (a 2s10s spread against its legs).
3. **Usability.** Mobile pass; crosshair readout on the large charts;
   small-multiple curve charts; revisit the thin Valuation tab after 1.
   `payload.regime` is still exported though the regime map left the page.
4. Stretch: IBKR Client Portal API as the price layer (needs an authenticated
   session, so not headless today).

## Out of scope

Intraday/real-time/daily data; PMI and surprise indices (no clean free
multi-country history); energy-transition layer; non-US FCF/dividend yields and
forward multiples until a free source appears; swap curves (only GBP OIS is
free); bank lending surveys (US SLOOS dropped 2026-08-29: single-country,
unused); journaling features.

## Appendix — endpoint reference

Cross-cutting knowledge, expensive to re-derive. Per-series quirks: the
catalog's "Notes / quirks".

### The User-Agent trap

No single header set works, and failures are silent. **FRED must NOT get a
browser UA** (Akamai tarpits a browser UA with Python's TLS fingerprint until
read timeout; tool UAs like `python-requests/*` answer in 0.2s; it is an
allowlist). **BoE and MOF need a browser UA** (else an error page). `_get()`
takes per-source headers, defaulting to requests' UA. One request per curve,
not per tenor (one transient failure made curves `partial`), and bound big
histories with `startPeriod`.

### Parsing traps

| Source | Trap |
|---|---|
| Yahoo | Latest bar often has a NaN close mid-session (^GDAXI, ^SSMI, ^HSI, ^N225): `dropna` or NaN reaches the JSON. FX has Saturday bars (next week's bin). Bare requests 429; yfinance does the cookie/crumb |
| BIS CPI | One response mixes units `771` (YoY %) and `628` (index): filter `unit_measure`. Released last week of the month, dated to month start |
| BIS policy rates | Needs `startPeriod` (unbounded Japan = 57 MB) |
| Bundesbank | ~9-line preamble; `.` = missing; accepts `startPeriod` and ignores it |
| MOF Japan | Shift-JIS (cp932); title row first; stitch current month with `historical/jgbcme_all.csv` |
| Norges Bank | Semicolon CSV; header repeats `TENOR`, so take columns positionally |
| ECB | `G_N_C` all-bonds (EZ row), `G_N_A` AAA (credit leg). Codelists list codes that are not series: `CL_PROVIDER_FM_ID`'s ~120 licensed index codes (`ER00`, `IBOXX*`) 404 on data |
| Shiller | Legacy `.xls` (xlrd); two header rows, upper has a second "CAPE" (Excess CAPE Yield) — match the lower row where col 0 is "Date"; dates fractional (1871.01) |
| Damodaran ERP | Use "Implied ERP (FCFE)", not "Implied Premium (DDM)" left of it (1.69% vs 4.23%). Fractions |
| Damodaran `ctryprem` | `.xls` 2000–2017, `.xlsx` 2018+ (2023 xlsx only), `pc/archives/`; archive `YY` = data year YY, stamped `YY-12-31`. Sheet name changes by era; header as deep as row 20. 2012–2015 have two "Country Risk Premium" columns (2nd is CDS) and the current file `Country Risk Premium3`: take the leftmost positionally. Footnote markers in names 2008–2011. Fractions; Aaa reads 0.0 always, so no magnitude heuristic. UK absent from 2005 |
| Damodaran `countrystats` | Archives 2012–2024, but 2012–2019 are MEANS (3–10× higher) and 2020+ MEDIANS: read medians only. Header row moves (0/1/7/8) |
| Damodaran regional | `Industry Averages` sheet, header row 7 (pe/pbv) or 8 (vebitda); total row `Grand Total` or `Total Market`; plain `Trailing PE` is an unweighted mean (US 57.9) — never use; no P/S |
| ONS | Under `months`, dated `"1997 JAN"`: explicit month map |
| Eurostat | JSON-stat: sparse `{flat_index: value}` joined to the time dimension by index, never position. HICP successor `prc_hicp_minr` uses `coicop18=TOTAL`, unit `I25` |
| SNB cubes | Each cube behaves differently. `gdprpq`/`gdpap` (real/nominal GDP, `D0(WMF)`, `D1(BBIPS)` = sport-adjusted): no `fromDate` → silently last 5 quarters (fetcher supplies `_SNB_GDP_FLOOR`); dates `1980-Q2`. `rendeiduebd` (curve): tenors `10J` not `10Y`; current month returns headers only until the batch lands |
| ChinaBond | Response holds three curves: match header and the government curve by NAME. >365-day queries (or no data) return 200 with headers only → zero rows = failure; backfill one year per request |
| SSB | Use table 14710 (headline CPI), not 14702 (by delivery sector: 7.7 vs 6.5 in 2023M03). v2-beta host 503s; v1 is POST-only and defaults to the latest period only |
| iShares screener | Only `country=gb`+`siteName=ishares-uk`+`userType=individual` works; always gzipped (send `Accept-Encoding`); values `{"d","r"}` — parse raw `yyyymmdd`. Snapshot only; private endpoint, must degrade to `None` |
| OECD `DF_QNA` | 13 positional dimensions; volume code differs by country (IN `Q`, BR `L`), wrong one = empty 200; no China. **Cloudflare**: ~15 calls/hour earned a `403` challenge (2026-10-22). Don't poke it while debugging; never work around it; fetcher degrades to `None` |
| IMF DataMapper | Country path filter ignored (returns all, ~120 kB): cache per indicator. Years are string keys; missing = absent. Edition only in `/indicators` metadata; refuse mixed editions |

### BoE GLC archives

Bootstrap-only (~89 MB); UK curve from 1979 (30y from 2016). Sheet names change
by era (`3. nominal spot, short end` to 2024, `3. spot, short end` after); each
zip holds one workbook per era, so collect a tenor from every block (taking
one block silently returns one era); archives end last month, so bootstrap
follows with a snapshot pass to close the seam.

### Dead ends — do not re-attempt without new information

Method lessons first: **enumerate, don't guess** (SNB's successor curve cube
was missed by seven guessed ids and found by listing the topic; SNB `gdpap` the
same way). **"JavaScript-rendered" describes a path, not a host** (ChinaBond's
front-end path is JS; `cbweb-pbc-web/pbc/` answers a plain GET). **A silent
freeze behind HTTP 200 is the dangerous failure**, not an outage.

- **Retired dataflows still answering 200:** Eurostat `prc_hicp_manr`/`midx`
  and ECB `ICP` frozen at 2025-12 (discontinued 2026-02-04, ECOICOP v2);
  successors `prc_hicp_minr` and ECB `HICP` (`DATA_PROVIDER=4D0`). SNB
  `rendoblid`/`rendoblim` stop 2025-07-31 (successor `rendeiduebd`). FRED's
  OECD-sourced national series are frozen (`*CPIALLMINMEI`, `CPALTT01*`,
  `NAEXKP01*Q657S`). SSB table 03013 closed 2025-12.
- **Aggregators (DBnomics etc.): never as feeds.** DBnomics served BIS US
  policy rate 75bp stale with HTTP 200; its OECD/IMF mirrors lag or are frozen;
  no SNB or Norges Bank. Bespoke parsers fail loudly, which is a feature. The
  OECD API is a cross-check only (`DSD_STES@DF_FINMARK` `IRLT`/`IR3TIB`), except
  IN/BR GDP (`DF_QNA`), where every alternative was a quarter staler.
- **Non-USD IG credit spreads (OAS) are not free, structurally:** the euro,
  sterling and yen IG benchmarks ARE ICE/iBoxx/Bloomberg indices and only ICE's
  US series are free on FRED (release 209 enumerated: 192 series, euro = 4,
  all HY; `BAMLEMEBCRPIEOAS`/`BAMLEMIBHGCRPIOAS` are EM issuers). ECB has no
  corporate bond dataset (all 115 `FM` series checked); BoE no corporate curve;
  BIS, IMF FSI, ESRB no use. Rejected proxies: ECB MIR / BoE lending rates
  (loans), ECB STEP (≤91 days). Hence the constructed YTW spreads.
- **Japan JSDA:** rating-bucket average yields across all maturities, no
  government equivalent, one file per day (~6,000 requests), timeouts. Not
  comparable. (Its column after the yield is a standard deviation, not a spread.)
- **Euro sovereign yields above monthly:** ECB `IRS` has no `D`/`B` frequency;
  Eurostat `irt_lt_mcby_m` is the same monthly figure; three national
  publishers would put a methodology gap inside the spread.
- **Euro market-implied inflation:** EUR HICPx zero-coupon swaps are not free;
  ECB `FM` `ILS` codes are Israeli shekel.
- **Swiss alternatives:** `rendoeid` is 23 individual bonds (we'd fit a curve);
  EFV/AFF budget data only; FRED, Yahoo, worldgovernmentbonds, FT, MarketWatch,
  SIX rejected 2026-08-29; TradingEconomics scrape retired 2026-09-13 (its 2y
  was 0.270 vs SNB 0.078). BFS PxWeb has no prices domain (`px-x-05` absent),
  so Swiss CPI stays on SNB `plkopr`.
- **Swiss sport-event-adjusted GDP on Eurostat:** impossible — `s_adj` is
  `{NSA, SA, CA, SCA}` and no SDMX concept exists; only SECO/SNB publish it.
- **ChinaBond dead paths:** `queryGjqxInfo`, `getYieldDataForWeb`,
  `queryTypeValues`, `cbweb-czb-web`, and CFETS. OECD `CHN.M.IRLT` is monthly
  and ~6 weeks behind: validation only.
- **India/Brazil GDP:** GEM at 2026Q1 (~294 days old on arrival); FRED India
  404s, Brazil nominal a quarter behind real; IBGE SIDRA current prices NSA
  only; BCB SGS 22109 has no nominal sibling.
- **India CPI:** OECD to 2026-05, FRED to 2025-03, MOSPI API "No Data Found"
  for the current base; BIS is freshest.
- **IMF euro-area PPP:** DataMapper `PPPGDP` has no `EURO` (EU is a different
  membership).
- **Stooq:** JS proof-of-work on every path. **S&P EPS workbook:** Akamai 403.
  **multpl.com:** no CSV/API/terms. **Yahoo CSI 300 index:** only 1d/5d history.
