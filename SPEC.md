# Markets Dashboard — Spec

The consolidated, build-facing design doc: what is in scope, where every
number comes from, and how the thing is put together.

Live at https://randaledd.github.io/markets-dashboard/.

Companion docs: `CLAUDE.md` (working conventions and the last verified run
status) and `DATA-CATALOG.csv` — the reviewed sourcing decision for every
series, which seeds the database's `series_catalog` table and which the
pipeline keeps in step with what is actually stored on every run.
`DATA-CATALOG-ruled-out.csv` records the permanent structural gaps. Endpoint
mechanics and dead ends are in the appendix at the foot of this file.

## Governing constraint

**Descriptive and historical, never prescriptive.** A percentile or z-score
against a series' own history is a fact about that series and is in scope.
Composite scores, "cheap"/"expensive" labels, and buy/sell/overweight framing
are not, anywhere. This disciplines every panel: the cost-of-capital stack
lays out its legs rather than collapsing them into one figure, the regime map
names quadrants after what the data is doing rather than what to do about it,
and the correlation heatmap makes no diversification recommendation.

## Scope decisions (confirmed)

- Regions at full depth: US, UK, Eurozone, Germany, Switzerland, China, Japan,
  Norway. Everything else (broader EM, rest of APAC) is secondary/thin — only
  an MSCI EM proxy is carried, under its own `EM` heading.
- **Refresh: weekly, Saturday morning, on the week's Friday close.** The store
  keeps one observation per completed week for anything published faster than
  that; genuinely monthly, quarterly and annual series keep their own grain.
  No intraday, no daily, no real-time.
- Equity index returns: local/respective currency, no CHF conversion.
- **Eurozone vs. Germany are two different curves, deliberately.** The
  Eurozone row is the ECB's *all-bonds* euro area curve — a blend across euro
  area sovereigns. Germany keeps its own row from the Bundesbank's
  single-issuer Bund curve. The Bund was originally specced as the euro
  benchmark, but that made the two rows duplicates: the ECB's AAA-only curve
  sits within a few basis points of the Bund (3.28 vs 3.22 on 2026-08-27),
  where the all-bonds curve was 3.70 the same day.
- Euro-area sovereign spreads (France/Italy/Spain) sit below the curve table.
  The benchmark leg is **the ECB's own German series, not the Bundesbank
  curve** — mixing the two would push a methodology and vintage gap into the
  spread (ECB had Germany at 3.07 where the Bundesbank daily curve had 3.22).
  Not labelled "periphery": these are core economies.
- Germany has no policy rate of its own — it *is* the ECB's, so the export
  mirrors the euro-area series rather than storing a second copy under a
  German id or showing a blank.
- China equities: CSI 300 (mainland) and Hang Seng (Hong Kong) both shown, not
  merged. The CSI 300 line is a CNY-priced tracker ETF, because Yahoo serves
  the index itself with only 1–5 days of history.
- Oil: Brent only, WTI deliberately dropped.
- Natural gas is carried twice — US Henry Hub and European TTF — because they
  are different markets in different units and one number would be misleading
  for a Zurich-based reader.
- PMI / economic surprise index: dropped entirely (no clean free multi-country
  historical source exists). GDP section is actual growth data only.
- Layout: 7 tabs — Equity Indices, Yield Curves (nominal + real + implied
  inflation + euro spreads), Macroeconomics (policy rates + inflation + GDP),
  Currencies, Commodities, Valuation (+ risk premia), Cross-Asset & Regime,
  plus a Regional Snapshot that inverts the grouping: one region's equities,
  curve, macro, valuation and FX together. Commodities are excluded there —
  they are global.
- Visualization: tables carry current-state data with sparklines. Clicking any
  sparkline expands an inline line chart with selectable lookback
  (3M/YTD/1Y/2Y/3Y/5Y, default 1Y), served from five years of weekly points.
- **Every figure states its definition.** Commodity rows carry exchange,
  contract and unit; GDP is labelled real / chain-linked / local currency /
  seasonally adjusted; inflation expectations carry tenor and index basis.
  Because the stored grain is weekly, so is every derived figure: volatility
  annualises with sqrt(52) and is labelled in weeks (4w/13w), correlation
  windows are 52w/104w, and there is no 1-day change column — a "1D" label
  over weekly data would be a number that does not mean what it says.
- Equity index *levels* deliberately carry no percentile annotation. A price
  percentile on a trending series is always near the 100th and says nothing;
  volatility and drawdown are mean-reverting, so those carry it instead.

## Data sourcing

Endpoint mechanics, quirks and dead ends are in the appendix below; the
per-series record is `DATA-CATALOG.csv`. This table is what each category
actually uses today.

| Category | Source | State |
|---|---|---|
| Prices / FX / commodities | Yahoo Finance via `yfinance` | Live — 12 indices, VIX, 8 FX pairs, 7 commodities, 2 bond-return proxies |
| Central bank policy rates | BIS Data Portal `CBPOL`, all 7 regions on one endpoint | Live. Norway consolidated off Norges Bank onto `D.NO` 2026-08-29; Germany mirrors the ECB rate |
| CPI, all 8 regions | BIS Data Portal `WS_LONG_CPI` | Live. Returns YoY and the index level in one response under different unit codes, so both are stored and annualised QoQ is derived |
| GDP growth | FRED real-GDP *level* series for US/DE/CH/JP/NO/CN; **ONS** monthly index for the UK; **Eurostat `namq_10_gdp`** for the euro area | Live. YoY and annualised QoQ derived in the pipeline so every region shares one definition. China is annual-only |
| US yield curve, real yields, breakevens | FRED (`fredgraph.csv`, no API key) | Live — nominal `DGS*`, real `DFII5/10/30`, breakevens `T5YIE`/`T10YIE`/`T5YIFR` |
| US 1y inflation expectation | Cleveland Fed `EXPINF*` via FRED | Live, badged **model**-implied — no 1y TIPS breakeven is published |
| UK curve, real yields, implied inflation | Bank of England GLC workbooks | Live, all four tenors, **history back to 1979** from the one-time archive pull |
| Eurozone curve | ECB Data Portal `YC`, all-bonds euro area curve | Live, all four tenors |
| Euro-area sovereign spreads (FR/IT/ES) | ECB Data Portal `IRS` per-country long-term rates | Live, monthly. Both legs from this same series; the spread is derived at export |
| Germany curve | Deutsche Bundesbank daily Bund term structure | Live, all four tenors |
| Japan curve | Japan MOF JGB CSV, current month stitched with the 1974 archive | Live, all four tenors |
| Norway curve | Norges Bank `GOVT_ZEROCOUPON` | Live to 10y — **no 30y is published**, so that cell stays blank |
| Switzerland curve | FRED `IRLTLT01CHM156N` | 10y only, monthly and ~2 months behind, flagged as such. The SNB retired its own curve |
| China curve | — | **No free source.** ChinaBond is JS-rendered and CFETS rejects all programmatic access |
| Euro-area / CH / CN / JP / NO inflation expectations | — | **No free source.** The practitioner standard is the zero-coupon inflation swap, which is not published free. CH and NO are permanent: neither government issues inflation-linked debt at all |
| Credit spreads | ICE BofA OAS via FRED (US IG/HY, Euro HY, EM corporate) | Live. Capped at a rolling ~3 years by ICE licensing, so only the `full` percentile window resolves |
| Liquidity / lending | Fed Senior Loan Officer Survey (`DRTSCILM`) via FRED | Live, quarterly, US only — no keyless euro-area equivalent found |
| US equity valuation | Shiller CAPE (`ie_data.xls`); Damodaran implied ERP (FCFE) | Live. Shiller's file currently ends 2024-09, so it reports `stale` |
| Non-US equity risk premia | Damodaran `ctryprem.xlsx` (rating-based country risk premium) | Live for UK/DE/CH/CN/JP/NO, annual, back to 2000 from the year-stamped archives. Stores the **country** premium, which is 0.00 for every Aaa sovereign; `db/export.py` adds the mature-market base (`erp.US`) back on for display. No Eurozone aggregate exists, so `erp.EZ` is descoped |
| Non-US equity valuation | Damodaran `countrystats.xls` (median trailing P/E, P/B, P/S, EV/EBITDA) | Live for the same six regions, annual, **2020 onward only** — the 2012-2019 archives publish means rather than medians, and splicing the two would put a methodology break mid-series. Not cyclically adjusted, so not comparable to the US CAPE. `valuation.EZ` is descoped |

Eleven institutions, and still gaps. No single source covers this, free or
paid short of a full commercial terminal — the spread of sources is by design.

## Architecture

    fetch/universe.py   what is tracked + how to fetch it (single source of truth)
    fetch/sources.py    one function per source; returns None on failure, never raises
    db/registry.py      the same universe, one row per STORED series, keyed by
                        the DATA-CATALOG.csv identifier
    db/catalog.py       joins DATA-CATALOG.csv to the registry -> series_catalog
    db/ingest.py        watermark -> fetch only what's newer -> INSERT OR IGNORE
    db/quality.py       staleness / gaps / outliers / curve consistency -> flags
    db/export.py        latest_observations -> site/data/latest.json
    transform/          derived metrics, consumed by the export
    pipeline.py         ingest -> quality -> export, in that order
    bootstrap.py        one-time seed; never on the schedule

A persistent SQLite store (`data/markets.db`) → a JSON export
(`site/data/latest.json`) → a static frontend reading that JSON → GitHub
Actions running the pipeline weekly and redeploying to GitHub Pages. No server
to maintain; a public URL accessible from anywhere.

### The store is append-only. This is the requirement, not an implementation detail.

No `UPDATE` and no `DELETE` exists in any path that touches `observations`.
Each run asks each series "what is the newest thing I already have?", fetches
only what might be newer, and for every candidate row does exactly one of two
things: **ignore it** (already stored — `ON CONFLICT DO NOTHING`, zero rows
changed) or **attach it**. There is no third case. `tests/test_append_only.py`
greps the source for violations.

The database is therefore a log of everything ever observed, not a cache of
current values. `latest_observations` is the only place "the current value"
exists, and it is resolved fresh on every read.

### Revisions — why `vintage_date` exists

GDP, CPI and SLOOS get revised after first release. A revision is new
information, not a correction that erases the old value, so it is **appended
as an additional row** stamped with today's `vintage_date`, and the row
holding the first print is never touched again. The view then resolves to the
newer vintage because one now exists for that `(series_id, date)` — nothing is
flipped, updated or deleted.

For a series that never gets revised (a price, a yield, a policy rate) the
ingest writes `vintage_date = date`, so the mechanism is present but inert and
each new date is a single insert like any other.

### Why ingest and export are separate steps

Ingest is cheap and incremental; export is comprehensive and also cheap,
because it is a local SQL query rather than a network fetch. Every derived
metric — drawdown, realized volatility, percentile/z-score, curve spreads — is
computed over the *full accumulated history* regardless of how much of it
arrived this week. Before the database, percentile context had to re-fetch
each source's entire history every run purely to annotate one number.

**Why not ship the database to the browser** (sql.js/WASM) and skip the export?
Considered and set aside for two concrete reasons: it means shipping the whole
accumulating file on every page load, and it means reimplementing all of
`transform/` a second time in JavaScript, in a project that deliberately chose
a Python pipeline and no server. Worth revisiting only if the frontend ever
needs something the weekly export genuinely cannot anticipate.

### Why the database is committed

`weekly.yml` commits `data/markets.db` alongside `latest.json`. The checkout
*is* the accumulated history — without it the runner would have no watermark
and would silently re-bootstrap over the store, so the job fails loudly if the
file is missing. Git's own history is the backup: every commit is a full,
dated, retrievable snapshot held both locally and on GitHub.

This is also why the grain is weekly rather than daily. At daily grain the
store was 585,503 observations and 98.7 MiB — and GitHub hard-rejects any file
over 100 MiB, so it was 1.3 MiB from being unpushable on its first commit. At
weekly it is 128,227 observations and 20.3 MiB, growing ~2 MiB a year.

### Adding a series later

One row in `fetch/universe.py`, then `python3 bootstrap.py --series <id>`.
The weekly run picks it up from then on; its watermark simply returns
nothing until the backfill runs, which is indistinguishable from any other
series before its first data point. No migration, and no row belonging to any
other series is touched.

## Roadmap

0. ✅ Scaffold, sample-data pipeline, frontend.
1. ✅ Prices/FX/commodities (Yahoo), US curve + breakevens + real yields
   (FRED), policy rates and CPI (BIS).
2. ✅ Non-US yield curves — Germany (Bundesbank), Japan (MOF), UK (BoE GLC),
   Eurozone (ECB), Norway (Norges Bank), at full tenor coverage where the
   source publishes it. Switzerland is degraded to a monthly 10y and China is
   unsourced — because no free source exists, not because of pending work.
3. ✅ Euro-area sovereign spread panel (ECB, FR/IT/ES). The ECB breakeven half
   is **closed as not possible** — there is no free euro-area inflation-swap
   feed.
4. ✅ Percentile/z-score context, cost-of-capital stack, credit and liquidity
   layer, FX hedging cost, growth/inflation regime map, cross-asset
   correlation heatmap, valuation scorecard.
5. ✅ Persistent append-only store, incremental ingest, data-quality flags,
   weekly cadence.
6. ✅ Non-US valuation and risk premia from Damodaran's `countrystats.xls`
   and `ctryprem.xlsx`, for UK/DE/CH/CN/JP/NO. This replaced the older plan to
   parse ETF fact-sheet PDFs, which needed `pdfplumber` and gave less.
   Delivered as **30 series, not the 12 originally catalogued**: the country
   risk premium is one series per region, but `countrystats.xls` carries four
   distinct multiples (P/E, P/B, P/S, EV/EBITDA) and a single `valuation.<R>`
   id could only ever have held one of them, so each is its own series.
   Both Eurozone rows stay `descoped`: Damodaran publishes member states with
   no bloc aggregate, and Germany's figure is not a stand-in for it — the same
   line already drawn between the Bundesbank and ECB curves.
7. Polish: small-multiple yield curve charts, further chart treatment, mobile
   layout pass.
8. Stretch: IBKR Client Portal Web API to replace yfinance as the price layer.
   Usable for ad hoc checks today but needs an authenticated session, so it is
   not a fit for a headless job.

## Appendix — endpoint reference

Absorbed from the former `SPEC.md's endpoint appendix`. Per-series quirks now live in
`DATA-CATALOG.csv`'s "Notes / quirks" column, which the pipeline keeps in step
with the database. What is kept here is the cross-cutting knowledge that
belongs to no single series and is expensive to re-derive.

### The User-Agent trap

There is no single header set that works across these sources, and getting it
wrong fails *silently*.

- **FRED must not get a browser User-Agent.** It sits behind Akamai, which
  tarpits requests whose UA claims to be a browser while the TLS fingerprint is
  Python's: the request hangs until it read-times-out. A tool-shaped UA
  (`python-requests/*`, `curl/*`) returns in ~0.2s. An "honest" project UA
  fails too — it is an allowlist of known tool UAs, not a politeness check.
- **The Bank of England and Japan's MOF are the exact opposite** — they serve
  an error page unless the UA looks like a browser.

`_get()` therefore takes per-source headers and defaults to requests' own UA.

### Parsing traps worth keeping

| Source | Trap |
|---|---|
| Yahoo (yfinance) | The latest bar often carries a **NaN close while a session is open** (^GDAXI, ^SSMI, ^HSI, ^N225) — must `dropna`, or a raw `NaN` lands in the JSON and breaks the frontend. Yahoo also emits a **Saturday bar for FX pairs**, which belongs to the following week's bin. The library does Yahoo's cookie+crumb handshake; a bare request returns 429 |
| BIS CPI | One response mixes two unit codes: **`771` = YoY %, `628` = index level**. Filtering on `unit_measure` is mandatory, or the two get silently interleaved |
| BIS policy rates | **Needs `startPeriod`** — unbounded history is 57MB for Japan and blows the timeout |
| Bundesbank | ~9-line metadata preamble before `date,value,flag`; `.` for missing. **Accepts `startPeriod` and ignores it** — measured, it returns the identical 10,620-row history either way |
| MOF Japan | **Shift-JIS (cp932), not UTF-8**, and line 1 is a title row. The current-month file must be stitched with `historical/jgbcme_all.csv` for history back to 1974 |
| Norges Bank | **Semicolon-delimited** CSV, and the header repeats `TENOR` for both the code and its label, so columns must be taken positionally |
| ECB | Two euro-area curve flavours: `G_N_C` (all bonds, used) and `G_N_A` (AAA-only, which tracks the Bund so closely it duplicates Germany) |
| Shiller CAPE | Genuine legacy `.xls`, needs **xlrd**. The header spans two rows and the upper one contains a second cell reading "CAPE" belonging to the Excess CAPE Yield block — match the lower row, where column 0 is exactly "Date". Dates are fractional (1871.01 = Jan) |
| Damodaran ERP | Use **"Implied ERP (FCFE)"**. "Implied Premium (DDM)" sits to its left and is a different, materially lower measure (1.69% vs 4.23% for 2025). Values are fractions, not percent |
| Damodaran `ctryprem` | Archives are `ctryprem<YY>.xls` for 2000-2017 and `.xlsx` from 2018 (2023 is xlsx-only), under `pc/archives/`; the undated `pc/datasets/ctryprem.xlsx` is the most recent completed year. **Archive `YY` is data year `YY`, published the following January** — `ctryprem24.xlsx` carries "Date of update: 2025-01-01" — so it is stamped `YY-12-31`. The sheet name moves (`Sheet1` 2000, `Country premiums` 2001-2011, `ERPs by country` 2012-now) and the header row sits as deep as **row 20**, so the 15-row scan used for `histimpl.xls` is too narrow. 2012-2015 carry **two columns both headed "Country Risk Premium"** (the second is CDS-based), and the current file adds `Country Risk Premium3` — take the leftmost, positionally, or pandas hands back a Series. Country names carry footnote markers (`Germany [1]`) in the 2008-2011 files. Values are fractions in every vintage, and the magnitude heuristic used for `histimpl.xls` **cannot** be reused: DE/CH/NO are Aaa and read exactly 0.0 in all 26 years, so a per-country max proves nothing. The UK is genuinely absent from `ctryprem05.xls` |
| Damodaran `countrystats` | Archived as `countrystats<YY>.xls` for **2012-2024** — the catalog previously recorded this depth as unconfirmed; it is confirmed. But the file changed statistic in the 2020 vintage: 2012-2019 publish `Average of <metric>`, 2020+ publish `Median <metric>`, and the means run 3-10x higher (Germany trailing P/E 171.3 in 2013 vs 15.9 in 2024). **Only median-basis vintages are read**, so history starts 2020. Header row moves between rows 0, 1, 7 and 8; column count swings from 20 to 256 |
| ONS | Observations are under `months`, dated `"1997 JAN"` — parse against an explicit month map, not a locale format |
| Eurostat | JSON-stat: `value` is a sparse `{flat_index: number}` map and the time dimension carries `{period_label: index}`, so the two join by index, never by position |

### The BoE GLC archives

`bootstrap.py` is the only thing that pulls these (~89MB across nominal, real
and inflation). They give the UK curve history back to 1979-01-02 — 2y/5y/10y;
the 30y only reaches 2016, because the BoE did not publish that point earlier.
Three traps, all silent:

- **Sheet names are not stable across eras.** Workbooks up to 2024 use
  `3. nominal spot, short end` / `4. nominal spot curve`; the 2025-to-present
  workbook and the current-month file use `3. spot, short end` /
  `4. spot curve`.
- **Each zip holds one workbook per era**, so a tenor must be collected from
  every block and concatenated. Taking the single best-matching block returns
  one era's slice of the history and looks plausible.
- **The archives are cut at the end of the previous month**, so bootstrap runs
  a snapshot pass straight after the deep pass to close the seam.

### Dead ends — do not re-attempt without new information

- **Stooq** serves a JavaScript proof-of-work anti-bot page instead of CSV on
  every path. Not solvable headlessly. Replaced by Yahoo.
- **FRED's OECD-sourced national series are frozen.** They still return
  HTTP 200 — which is exactly why the staleness check exists. `*CPIALLMINMEI`
  stops 2025-03/04 (JP: 2021-06), `CPALTT01*` stops 2024-12, `NAEXKP01*Q657S`
  growth is discontinued. CPI moved to BIS; GDP to level series with growth
  derived here.
- **SNB Confederation bond yields are discontinued.** Both `rendoblid` and
  `rendoblim` return 200 while stopping at 2025-07. Money-market cubes on the
  same portal are current, so the series was retired, not the portal broken.
- **ChinaBond is JS-rendered** (`queryGjqxInfo` returns a 956-byte shell) and
  **CFETS answers `{"Error":"Path not found."}` to every path**, including
  plain HTML. The China curve has no remaining lead short of a headless
  browser.
- **Euro-area market-implied inflation has no free source.** The practitioner
  standard is the EUR HICPx zero-coupon inflation swap. The ECB `FM` dataflow
  has no ILS series — its `ILS` codes are Israeli shekel.
- **Yahoo has no CSI 300 index history** — `000300.SS`/`399300.SZ` accept only
  `period=1d/5d`. The CNY-priced tracker ETF `510300.SS` stands in.

## Explicitly out of scope

- Intraday / real-time / daily data.
- PMI / economic surprise index.
- Energy-transition/infrastructure-specific layer.
- CHF-converted equity returns (local currency only).
- Non-US FCF yield / EV-EBITDA (no free source found).
- Journaling / knowledge-base features — deferred to their own project.
