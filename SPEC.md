# Markets Dashboard — Spec

The consolidated, build-facing design doc: what is in scope, where every
number comes from, and how the thing is put together.

Live at https://randaledd.github.io/markets-dashboard/.

Companion docs: `CLAUDE.md` (working conventions and the last verified run
status) and `data/DATA-CATALOG.csv` — the reviewed sourcing decision for
every series, which seeds the database's `series_catalog` table. What is
actually stored is written beside it, to the generated `DATA-COVERAGE.csv`, on
every run. Permanent
structural gaps are rows in it too, marked `no source found` with the reason
and the date last checked. Endpoint mechanics and dead ends are in the
appendix at the foot of this file.

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
- **India and Brazil are macro-only (2026-10-22).** GDP (real and nominal),
  CPI, policy rates and IMF forecasts, on the Macroeconomics tab alone
  (`universe.MACRO_REGIONS`). No equity index, curve, currency or valuation
  row is sourced for them, so they are deliberately NOT in `REGIONS` and have
  no Regional Snapshot. Widening them to full regions is a separate decision.
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
- Layout: 7 tabs — Macroeconomics (regime map + GDP + inflation + policy
  rates), Equity Indices, Rates (curves + euro spreads + real yields + implied
  inflation + credit + cost of capital), Currencies, Commodities, Valuation
  (+ risk premia), Cross-Asset — plus a Regional Snapshot that inverts the
  grouping: one region's equities, curve, macro, valuation and FX on one page.
  Commodities are excluded there, being global. Macroeconomics leads because
  it is the context everything else is read against.
- Visualization: the Equity and Rates tabs each open with one large chart above
  their table — index selection and lookback on the first, region selection and
  an as-of date on the second. Elsewhere, tables carry sparklines that expand
  into a line chart (3M/YTD/1Y/2Y/3Y/5Y, default 1Y) from five years of weekly
  points. Two or more equity lines are always indexed to 100 at the start of
  the window: they sit in different currencies at different levels, so nothing
  else makes them comparable.
- **Every figure states its definition.** Commodity rows carry exchange,
  contract and unit; GDP is labelled real / chain-linked / local currency /
  seasonally adjusted; inflation expectations carry tenor and index basis.
  Because the stored grain is weekly, so is every derived figure: volatility
  annualises with sqrt(52) and is labelled in weeks (4w/13w), correlation
  windows are 52w/104w, and there is no 1-day change column — a "1D" label
  over weekly data would be a number that does not mean what it says.
- **The cost-of-capital risk-free leg is the nominal 10y, not a real yield.**
  The equity risk premium beside it is Damodaran's implied ERP, itself measured
  against a nominal government yield, so a real risk-free would remove
  inflation twice. It is also the textbook convention — the risk-free is the
  government yield in the currency and duration of the cash flows — and it
  fills the table, since 7 of 8 regions publish a nominal 10y where only 2
  publish a real one.
- **There is no "total" cost of capital, and no WACC.** The tab shows two
  rates, each with its formula stated: cost of equity = risk-free + ERP, and
  cost of debt = risk-free + IG credit spread. It used to show a single "Total"
  that summed risk-free + credit spread + ERP, which is none of the three
  things a reader would take it for — it counts the risk-free once and then
  stacks two premia belonging to two different claims on the same firm. A real
  WACC would need a leverage assumption and a tax rate, neither of which this
  project sources, so it shows two well-defined numbers rather than one
  invented one. A rate is blank unless BOTH its legs are sourced: a half-built
  discount rate is worse than a blank, because it looks usable.
- **Currency conversion on the equity tab converts everything or nothing.**
  Selecting USD/GBP/EUR/CHF rebuilds levels, every return, drawdown and
  volatility from the converted history — a return in another currency is a
  different number, not the local number with a footnote. Percentile context is
  dropped when converted, because it was measured on the local-currency
  distribution. The selected currency is stated in a banner above both the
  chart and the table, because it silently changes every figure on the tab.
- Equity index *levels* deliberately carry no percentile annotation. A price
  percentile on a trending series is always near the 100th and says nothing;
  volatility and drawdown are mean-reverting, so those carry it instead.

## Data sourcing

Endpoint mechanics, quirks and dead ends are in the appendix below; the
per-series record is `data/DATA-CATALOG.csv`. This table is what each category
actually uses today.

| Category | Source | State |
|---|---|---|
| Prices / FX / commodities | Yahoo Finance via `yfinance` | Live — 12 indices, VIX, 8 FX pairs, 8 commodities (Brent and WTI both, named so neither reads as plain "oil"), 2 bond-return proxies (US and euro governments). Gold/copper is derived from two of these rather than sourced again |
| Central bank policy rates | BIS Data Portal `CBPOL`, all 9 rate-setters on one endpoint (7 core + India, Brazil) | Live. Norway consolidated off Norges Bank onto `D.NO` 2026-08-29; Germany mirrors the ECB rate |
| CPI, all 8 regions | **Each country's own statistics office** — FRED (US), ONS (UK), Eurostat `prc_hicp_minr` (EZ/DE), SNB `plkopr` (CH), SSB table 14710 (NO); BIS `WS_LONG_CPI` for CN and JP only | Live. Moved off the single BIS dataflow 2026-09-13: BIS releases in the last week of each month and dates each print to the first of that month, so its newest figure ran 27–57 days old. Each region carries an explicit `basis` (US CPI-U, UK CPI, EA/DE HICP, CH LIK, CN CPI, JP CPI, NO KPI) because these cannot be put on one methodology — HICP does not exist for the US, China or Japan. Where a publisher prints only an index (US, NO) the annual rate is derived. China stays on BIS because the NBS returns 403 to non-browser clients from outside the mainland; Japan because e-Stat would buy 9 days for the price of an Actions secret. **India (all-India CPI combined) and Brazil (IPCA) joined on BIS 2026-10-22**; India runs a month behind the other BIS series and reads `stale` in the back half of the month exactly as Japan does — the OECD (May) and FRED (March) were further behind, and MOSPI's API returned no data for the current base. **The 3-month annualised rate is seasonally adjusted in the export** (`transform/growth.seasonally_adjusted_growth_series`): every stored index is NSA, and an unadjusted 3-month change is mostly the season (India 11.2% NSA vs 5.2% adjusted, 2026-07). Classical log-additive monthly factors from the previous 8 complete calendar years, no look-ahead; against BLS's own SA series (CPIAUCSL) since 2018, correlation 0.98 and mean absolute gap 0.5pp. Labelled "seasonally adjusted here", never as the agency's. **In the Growth & Inflation table CPI is measured over GDP's own quarter** (the quarter's average index: YoY on the NSA index, QoQ annualised on the seasonally adjusted level, `transform/growth.seasonally_adjusted_levels`; against BLS's CPIAUCSL quarterly averages since 2018, correlation 0.99, mean gap 0.3pp), because GDP's newest figure is a quarter and CPI's a month a quarter later — China's June–August CPI (−1.1% annualised) had been sitting beside its Q2 GDP. The newest monthly print stays in the cell's small print and everywhere else |
| Price levels, cross-region (Macroeconomics chart) | The stored CPI **index** levels, except **Eurostat `prc_hicp_minr` HICP for CH and NO** (`hicp.CH.index` from 2004-12, `hicp.NO.index` from 2000-01) | Live from 2026-10-16. A different question from the CPI row above, so a different index choice: the YoY table shows the print each market trades (LIK, KPI), while a chart laying eight price levels side by side puts as many as possible on ONE methodology. HICP covers EZ/DE/CH/NO, and the UK's ONS CPI is HICP methodology (Eurostat dropped the UK after Brexit), which makes five of eight. US CPI-U, JP and CN stay national (no HICP exists), and the US and Japan include imputed owner-occupier rent, which HICP excludes. The chart says this rather than implying one basket. All eight are headline, all-items, **NSA**. The frontend rebases every line to 100 at **one common month**: the window is anchored on the newest release among the selected regions, and the base is the first month in it that every selected line has, so the US 2025-10 hole moves the base for everyone rather than being invented. A CHF view multiplies each level by CHF per local unit (the **monthly average** of the stored weekly FX closes), exported from Python because the payload's FX history is only 5y weekly and this chart reaches 20y |
| GDP growth | FRED level series for US/DE/JP; **Eurostat `namq_10_gdp`** for EZ and NO; **SNB cube `gdprpq`** (`D0(WMF),D1(BBIPS)`) for Switzerland; **ONS `abmi`/`pn2`** quarterly for the UK; **World Bank GEM** for China | Live, and all eight regions are quarterly chain-linked on one definition. CH and NO left FRED 2026-09-13 because `CLVMNACSCAB1GQ*` self-reports "Source: Eurostat" with a euro FX conversion layer on top — it was never nationally sourced, and it is the series that caused the rebasing incident. **CH then left Eurostat for the SNB on 2026-09-21, to get the SPORT-EVENT ADJUSTED series** — FIFA, UEFA and the IOC are domiciled in Switzerland and book their licensing revenue there, so the unadjusted series spikes in tournament quarters on revenue that is not Swiss activity (2026-Q2: 2.63% YoY unadjusted vs 2.15% adjusted). It is the one region carrying an extra adjustment, so it carries an explicit `basis` on the dashboard. The UK moved off its monthly GVA index, which is kept as `gdp.UK.monthly_nowcast`. China moved from annual to quarterly. **Norway moved to SSB MAINLAND GDP 2026-10-22** (table 09190, `bnpb.nr23_9fn`, real and nominal, SA): total GDP's offshore oil and gas made its nominal growth a reading on energy prices (+16.7% annualised in 2026-Q2 against +3.9% for the mainland). It carries a `Mainland` basis tag, and its IMF forecasts remain total-economy. Purged and reseeded, not appended over. **India and Brazil (2026-10-22) are on the OECD's quarterly national accounts (SDMX `DF_QNA`), calendar and seasonally adjusted** — the one place the OECD is a feed rather than a cross-check (see dead ends): GEM had both at 2026Q1, past the staleness threshold on arrival, where the OECD had 2026Q2, and it carries the matching current-price series, so real and nominal share one source. All GDP series are on cadence `quarterly_national` (270 days): under plain `quarterly` (200) every GDP series read stale from mid-October on a schedule, because a quarter is dated to its first day and the next one lands ~1–2 months after IT ends |
| Nominal GDP | The PUBLISHED current-price series, same source as each region's real series wherever it publishes one: FRED `GDP` (US), ONS `ybha`/`pn2` (UK), Eurostat `namq_10_gdp` `CP_MEUR` EA20, SSB table 09190 Mainland `PriserSesJust` (NO), FRED `CPMNACSCAB1GQDE` (DE), **SNB cube `gdpap`** `D0(WMF),D1(BBIPS)` (CH, sport-event adjusted), FRED `JPNNGDP` (JP), GEM `NYGDPMKTPSACN` (CN), OECD QNA `V` (IN, BR) | Live from 2026-10-22, `gdp_nominal.<R>`. NOT real growth plus CPI: nominal GDP is deflated by the GDP deflator, which prices what an economy produces, where CPI prices what households buy — they part ways when the terms of trade move (Norway's oil, China's producer-price deflation). Feeds the Growth & Inflation table and the snapshot's 10y-vs-nominal-growth panel |
| Growth & inflation forecasts; GDP levels (USD, PPP) | **IMF World Economic Outlook**, DataMapper API (keyless JSON): `NGDP_RPCH`, `PCPIPCH`, `NGDPD`, `PPPGDP` for all ten regions (euro area = the IMF's `EURO` aggregate) | Live from 2026-10-22, `imf.<R>.<key>` plus `imf.weo_edition`. One publisher and one edition for every region, which is what makes forecasts comparable. Actuals and projections share one annual column and the API marks neither; the edition (from the indicators metadata) sets the boundary — years from its year on are projections — and is stored as its own series, which also carries the block's staleness (cadence `semiannual`). Projection series are exempt from `check_basis_break`, which every new edition would otherwise trip, and a future-dated first print is stamped with today's vintage (see Revisions). **No euro-area PPP exists** in the DataMapper — catalogued `no source found`. **Nominal growth forecasts** are derived, one way for every region, from real growth and the **GDP deflator** (`NGDP_D`, `imf.<R>.deflator`) served by the IMF's **SDMX API** (`api.imf.org`, dataflow `IMF.RES/WEO`, euro area = `G163`): the DataMapper has nominal GDP only in US dollars and no deflator, and SDMX has no national-currency GDP for the euro area. Within 0.05pp of the IMF's own national-currency growth where published. `fetch_imf_sdmx` refuses its response unless SDMX real growth matches the DataMapper's for all ten regions, so two editions are never mixed while the APIs update on different days. Norway's IMF figures are total economy beside Mainland actuals, and the table marks them |
| US yield curve, real yields, breakevens | FRED (`fredgraph.csv`, no API key) | Live — nominal `DGS*`, real `DFII5/10/30`, breakevens `T5YIE`/`T10YIE`/`T5YIFR` |
| US 1y inflation expectation | Cleveland Fed `EXPINF*` via FRED | Live, badged **model**-implied — no 1y TIPS breakeven is published |
| UK curve, real yields, implied inflation | Bank of England GLC workbooks | Live, all four tenors, **history back to 1979** from the one-time archive pull |
| Eurozone curve | ECB Data Portal `YC`, all-bonds euro area curve | Live, all four tenors |
| Euro-area sovereign spreads (FR/IT/ES) | ECB Data Portal `IRS` per-country long-term rates | Live, monthly. Both legs from this same series; the spread is derived at export |
| Germany curve | Deutsche Bundesbank daily Bund term structure | Live, all four tenors |
| Japan curve | Japan MOF JGB CSV, current month stitched with the 1974 archive | Live, all four tenors |
| Norway curve | Norges Bank `GOVT_ZEROCOUPON` | Live to 10y — **no 30y is published**, so that cell stays blank |
| Switzerland curve | **SNB cube `rendeiduebd`** (`dimSel=D0(CHF)`), plus the SNB interest-rate RSS feed for the live 10y | Live, all four tenors, **history to 1988-01-04**. The SNB never retired this curve — it moved cubes, and the earlier conclusion was wrong (see dead ends). Replaced the TradingEconomics scrape 2026-09-13, which **removes the project's only unofficial source**. The cube publishes daily observations in a monthly BATCH, hence the `monthly_batch` cadence; `R10` from the RSS feed keeps the 10y current between batches |
| China curve | **ChinaBond `cbweb-pbc-web/pbc/historyQuery`**, scraped | Live at 5y/10y/30y, history to 2006-03-01. Server-rendered and answers a plain cold GET — the earlier "JS-rendered" finding was about the front-end path, not the host. **Labelled a scrape**: official CCDC/PBoC-affiliated and parsed by header and curve name rather than position, but a restyle still breaks it. There is **no 2y** on this curve and 3Y is deliberately not interpolated into that slot. Validated against OECD `CHN.M.IRLT` |
| Euro-area inflation expectations | **ECB Survey of Professional Forecasters**, quarterly from 1999Q1 | Live, badged **survey**-based, never stacked with the market-implied rows. Not a substitute for the market measure: the EUR HICPx zero-coupon swap is still unpublished free. SPF has no rolling-horizon series, so the 1y and 2y are constructed from its calendar-year forecasts; the 5y slot holds its longer-term mean, whose tenor **moves between 4 and 5 years** by round and says so |
| CH / CN / JP / NO inflation expectations | — | **No free source**, and CH and NO are permanent: neither government issues inflation-linked debt at all. China is refused on definition — the only measure is a PBoC diffusion index of respondents expecting higher prices, not a percentage |
| Credit spreads (OAS) | ICE BofA OAS via FRED (US IG/HY, Euro HY, EM corporate) | Live. Capped at a rolling ~3 years by ICE licensing, so only the `full` percentile window resolves. **OAS is not free for any currency but the dollar**, and that is structural — see dead ends |
| Euro & sterling IG spreads | **Constructed**: iShares IEAC / SLXX yield to worst, less a government curve interpolated to the fund's own duration (ECB AAA `G_N_A` for the euro, the stored BoE gilt curve for sterling) | Live from 2026-09-21. Nothing free publishes these — see dead ends — so they are built rather than found, and they are **yield-to-worst spreads, not OAS**, sitting in the non-OAS column and never beside the US figure. Reading 93bp and 108bp at launch, where those indices actually trade. Two departures from house rules, both deliberate and both stated in the UI: the two legs come from DIFFERENT publishers, and the series has **no history** — it deepens one weekly point at a time from the day it shipped. The euro leg is the AAA curve, not the all-ratings one used for the sovereign row: all-ratings already contains peripheral sovereign risk, which is not corporate risk and must not net out (93bp against 68bp) |
| Corporate spread to government (non-OAS) | FRED `BAMLC0A0CMEY` less the stored US 10y; **Bundesbank BBSIS** corporate less general government | Live for US and DE only, in its own labelled Cost of Capital column. A **different quantity** from an OAS — not option-adjusted, not duration-matched — so it is never summed into the stack or counted toward coverage. The US is computed on both bases so the column is internally consistent (80bp OAS against 73bp non-OAS on 2026-09-10). UK/EZ/CH/CN/JP/NO read unavailable, each with a recorded reason |
| Liquidity / lending | — | **Dropped 2026-08-29.** The Fed's SLOOS was the only region with a keyless feed, and a single-country lending panel was not being used |
| US equity valuation | Shiller CAPE (`ie_data.xls`); Damodaran implied ERP (FCFE) | Live. Shiller's file currently ends 2024-09, so it reports `stale` |
| Non-US equity risk premia | Damodaran `ctryprem.xlsx` (rating-based country risk premium) | Live for UK/DE/CH/CN/JP/NO, annual, back to 2000 from the year-stamped archives. Stores the **country** premium, which is 0.00 for every Aaa sovereign; `db/export.py` adds the mature-market base (`erp.US`) back on for display. No Eurozone aggregate exists, so `erp.EZ` is descoped |
| Equity valuation multiples | Damodaran `countrystats.xls` (median trailing P/E, P/B, P/S, EV/EBITDA) for seven regions; the regional `peEurope`/`pbvEurope`/`vebitdaEurope` files for Europe | Live, annual, **2020 onward only** — the 2012-2019 archives publish means rather than medians, and splicing the two would put a methodology break mid-series. Not cyclically adjusted, so not comparable to the US CAPE. **The US joined 2026-09-21**: `countrystats.xls` had always carried a "United States" row on the same median basis, and its absence was a config gap that left the S&P 500 showing CAPE and nothing else. **Europe joined the same day** for the STOXX Europe 600 row, and is a CAP-WEIGHTED AGGREGATE rather than a median — a different statistic, labelled as such on the row, and not comparable with the country rows (for the US the two bases read 26.6 and 22.6). A EUROZONE aggregate still does not exist and stays descoped; Europe is deliberately the wider set, which is what STOXX Europe 600 actually spans. Europe carries no P/S — the regional files publish none |

Fifteen institutions and two acknowledged scrapes (ChinaBond, and nothing else since the TradingEconomics retirement), and still gaps. No single source covers this, free or
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
    db/catalog_sync.py  what IS stored -> data/DATA-COVERAGE.csv (generated)
    transform/          derived metrics, consumed by the export
    publish.py          sync from / publish to the single-commit `data` branch
    stamp_assets.py     asset version stamps in index.html (also run at deploy)
    pipeline.py         sync -> ingest -> quality -> export -> coverage -> publish
    bootstrap.py        one-time seed; never on the schedule

A persistent SQLite store (`data/markets.db`) → a JSON export
(`site/data/latest.json`) → a static frontend reading that JSON → GitHub
Actions running the pipeline weekly and redeploying to GitHub Pages. No server
to maintain; a public URL accessible from anywhere.

### Deployment: two workflows, two branches

Pages here is set to build **from a workflow**, so nothing reaches the live URL
unless a workflow puts it there — for a long period none did, and pushes to
`main` silently changed nothing anyone could see while the site served an old
build. The deployed site is main's `site/` plus `latest.json` from the `data`
branch, version-stamped by `stamp_assets.py` at deploy time.

`weekly.yml` runs the pipeline (which replaces the `data` branch) and then
deploys itself, because it pushes with `GITHUB_TOKEN` and GitHub refuses to let
a token-authored push start another workflow. `pages.yml` covers every other
case: a push to `main` touching the site, a push to `data` from the Mac, or a
manual run. After any push, `publish.verify()` checks the live URL actually
changed.

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

**A projection's first print is stamped with today, not its own date.** A
revisable first print normally gets `vintage_date = date`. The IMF WEO stores
projections to 2031, and a `vintage_date` of 2031-01-01 would outrank every
later edition's revision (each stamped with the day it arrived), so the view
would serve the first forecast forever. `rows_to_attach` stamps
`min(date, today)`, which is inert for every series that is never
future-dated; `tests/test_ingest.py` holds it.

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

### Where the database lives: the `data` branch, one commit, no history

Until 2026-10-22 `data/markets.db` and `latest.json` were committed to `main`
every week. That kept a full copy of every past version online for no
purpose — the store is append-only, so the CURRENT file already contains
every value and every revision it has ever seen — and it made generated files
a standing source of merge conflicts. Now (`publish.py`):

- `main` holds code and reviewed prose only; the generated files are
  gitignored.
- The `data` branch holds exactly one parentless commit — `markets.db.gz`,
  `latest.json`, `DATA-COVERAGE.csv` — replaced on every publish with
  `--force-with-lease` against the commit the local database was built on
  (`refs/markets/data-base`). A publisher that lost a race is refused and
  re-runs; nobody's rows are overwritten.
- Before a run, `sync_data` downloads the published store if it is newer, and
  refuses to replace a local one holding unpublished rows. A live run with no
  store at all stops rather than re-bootstrapping over the real one.
- Each checkout keeps rolling local snapshots in `data/history/` (8, ~2 MB
  each). That is the only version history, and it is local by design.

The main history was rewritten on 2026-10-22 to remove the 44 committed
database versions and the old payloads; a bundle of the pre-rewrite repository
was kept locally.

This is also why the grain is weekly rather than daily. At daily grain the
store was 585,503 observations and 98.7 MiB — and GitHub hard-rejects any file
over 100 MiB, so it was 1.3 MiB from being unpushable on its first commit. At
weekly it was 130,542 observations and 20.9 MiB. The 2026-10-22 slimming
(WITHOUT ROWID, no duplicate index, no per-row `ingested_at`) took 170k
observations to 9.7 MiB, 1.7 MiB gzipped as published.

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
7. ✅ Dashboard rework (2026-08-29). House palette, Macroeconomics leading,
   "Rates" and "Cross-Asset" renamed, the regime map moved to Macro with a
   how-to-read-it note, chart-led Equity and Rates tabs, index tooltips stating
   weighting and return basis, the inflation table rebuilt on the curve tenor
   columns, credit in basis points, a nominal cost-of-capital stack, and the
   Regional Snapshot rebuilt as a cheat sheet. Also the Pages deploy workflow
   that had been missing, without which pushing never updated the live site.

### Next steps

Three strands, roughly in order of value. None is started.

8. **Fill the data gaps.** Largely addressed 2026-09-13; what remains is
   genuinely blocked rather than pending.
   - ~~**Non-US investment-grade credit spreads.**~~ **Closed, with a partial
     answer.** This was recorded as the single highest-value gap on the
     assumption that one source would turn seven `partial` stacks into `ok`.
     That source does not exist free, and the reason is structural: the euro,
     sterling and yen IG benchmarks *are* the ICE, iBoxx and Bloomberg indices,
     and ICE licenses only its US series to FRED. What was available instead is
     the plainer corporate-minus-government spread, now live for the US and
     Germany in its own labelled column. Five regions read **unavailable**,
     each with a recorded reason. See dead ends before re-opening this.
   - ~~**A real Swiss source.**~~ **Done.** SNB cube `rendeiduebd`: four tenors,
     38 years, official. The scrape is retired.
   - ~~**China curve.**~~ **Done.** ChinaBond `historyQuery`, 5y/10y/30y back to
     2006. Still a scrape, and labelled as one.
   - ~~**Euro-area inflation expectations.**~~ **Partly done.** The ECB SPF is
     live as a clearly-badged *survey*. The market-implied measure — the EUR
     HICPx zero-coupon swap — is still unpublished free, so the gap it was
     meant to fill is narrowed, not closed.
   - **Non-US dividend yields and forward multiples**, which would make the
     Valuation tab more than trailing multiples and a risk premium. **This is
     now the highest-value remaining gap.**
   - **CH / CN / JP / NO inflation expectations** remain blocked on sources
     that do not exist free rather than on work. CH and NO are permanent.
     China is refused on definition, not availability. Do not re-attempt
     without new information; see dead ends.

9. **Data cleanliness.** `db/quality.py` checks staleness, gaps, outliers and
   curve consistency. What it does not yet do:
   - **Plausibility bands per series.** Nothing would presently catch a yield
     of 40% or a P/E of 4,000 — the outlier check is relative to a series' own
     history, so a first bad print on a short series passes. This matters most
     for the scraped **China** curve — the Swiss one is no longer scraped —
     where a page restyle could silently return the wrong number rather than
     failing. `fetch_chinabond_curve` carries a hard 0-15% band of its own as a
     first line of defence, but that is per-fetcher rather than per-series and
     is exactly the ad-hoc arrangement this step should generalise.
   - **Unit-drift detection.** A source switching between fractions and percent
     is the failure mode that has bitten this project most (Damodaran twice),
     and it is currently caught only by fetcher-specific heuristics.
   - **Cross-series consistency.** Nothing asserts that a 2s10s spread agrees
     with its own legs, or that a derived ratio moves when its inputs do.
   - ~~**Flag lifecycle.**~~ **Done** — `quality.py` retires a flag when its
     condition no longer holds, and since 2026-09-13 also when the series
     itself leaves the registry, which a source switch can do. Both halves are
     held by `tests/test_flag_resolution.py`.

10. **Layout, readability, usability.** The 2026-08-29 rework covered structure
    and colour; what remains is craft:
    - A **mobile pass** — the tables are still desktop-shaped.
    - **Crosshair and hover readout** on the two large charts, so a line can be
      read at a date rather than estimated against the axis.
    - **Small-multiple curve charts** — all eight regions at a glance rather
      than one overlay at a time.
    - The **Valuation tab is still thin**, and will stay thin until step 8
      lands. Its layout should be revisited once it has more to show.

11. Stretch: IBKR Client Portal Web API to replace yfinance as the price layer.
    Usable for ad hoc checks today but needs an authenticated session, so it is
    not a fit for a headless job.

## Appendix — endpoint reference

Absorbed from the former `NETWORK.md`. Per-series quirks now live in
`data/DATA-CATALOG.csv`'s "Notes / quirks" column. What is kept here is the cross-cutting knowledge that
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
| BIS CPI | One response mixes two unit codes: **`771` = YoY %, `628` = index level**. Filtering on `unit_measure` is mandatory, or the two get silently interleaved. **Released once a month, in the last week** (verified against BIS's calendar 2026-09-12: 27 Aug brought July, 24 Sep brings August), and each print is dated to the first of the month it describes — so the newest one is ~57 days old on arrival and ~85 the day before the next release. Hence cadence `monthly_month_end` (100d), not `monthly` (70d), which turned all 16 CPI series red in the back half of every month |
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
| iShares product screener | The euro and sterling IG credit legs. `country=gb` + `siteName=ishares-uk` + `userType=individual` is the ONLY combination returning 200 — `country=uk` 500s for every siteName, and `userType=professional` 500s. Always gzipped, so `Accept-Encoding: gzip` is mandatory or the body is binary noise. Values are `{"d": display, "r": raw}` pairs and `navAmountAsOf` is `{"d": "Sept 18, 2026", "r": 20260918}` — parse the raw yyyymmdd, never the prose. **It is a SNAPSHOT: one as-of date per fund, no history at all**, so the stored series begins the day it ships. Undocumented private endpoint; it will break without notice and must degrade to `None` when it does |
| Damodaran regional files | `peEurope.xls` / `pbvEurope.xls` / `vebitdaEurope.xls`, sheet `Industry Averages`. Header row 7 for pe/pbv, 8 for vebitda. The aggregate row is `Grand Total` in some files and `Total Market` in others — including inconsistently within the regional set — so match either. These publish CAP-WEIGHTED AGGREGATES, not the medians `countrystats` publishes: for the US the two read 26.6 and 22.6, and the file's plain `Trailing PE` column is an unweighted mean reading 57.9 and must never be used. No P/S column exists in any of them |
| SNB cube `gdprpq` (GDP) | **Do not assume one SNB cube behaves like another** — this one differs from `rendeiduebd` in two ways, both silent. (1) A query with **no `fromDate` returns HTTP 200 carrying only the last FIVE QUARTERS** (9 lines against 189). That is worse here than for the curve: GDP is quarterly, so `refetch_in_full()` is true and `ingest.fetch_one` passes `start=None` every run — `fetch_snb_gdp` therefore supplies its own floor (`_SNB_GDP_FLOOR`) rather than relying on a caller. (2) The `Date` column is a **quarter label** (`1980-Q2`), not the ISO date `rendeiduebd` and `plkopr` return, so it goes through `_period_start` before `_frame`. `D0(WMF)` is the level in chain-linked CHF millions (ref 2020); `D1(BBIPS)` is sport-event adjusted and `D1(BBIP)` is not |

| SNB cube `gdpap` (nominal GDP) | `gdprpq`'s current-prices sibling, found by ENUMERATING `/api/cube/gdpap/dimensions/en` after guessed ids 404'd. Identical D0/D1 codes and the same two traps, so `fetch_snb_gdp` takes a `cube=` argument rather than a second fetcher |
| OECD SDMX (`DF_QNA`) | The key is positional, thirteen dimensions. The VOLUME price-base code differs by country — India `Q` (constant 2022-23 prices), Brazil `L` (chain-linked) — and the wrong one returns an empty body with HTTP 200. China is absent from the dataflow. **Cloudflare**: after ~15 calls in an hour on 2026-10-22 it began answering `403` with `cf-mitigated: challenge`; a bot challenge is not something to work around, so the fetcher degrades to `None` and the stored history carries the series. The weekly run makes four calls |
| IMF DataMapper | The path's country filter is **ignored** — `/NGDP_RPCH/USA` returns every economy (~120kB) — so `fetch_imf_weo` caches one response per indicator per process. Years are string keys and a missing year is absent, not null. The edition is ONLY in `/indicators` metadata (`"World Economic Outlook (October 2026)"`); the edition fetcher refuses a response whose indicators name different editions |

### The BoE GLC archives

`bootstrap.py` is the only thing that pulls these (~89MB across nominal, real
and inflation). They give the UK curve history back to 1979-01-05 — 2y/5y/10y;
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

### Flags close themselves

`data_quality_flags` is a log of findings, not a list of chores, so an entry
has to mean "currently true". Every check re-runs each pipeline run and any
open flag it no longer finds is marked `resolved`; the row and its `raised_at`
survive, and the same condition recurring later opens a new flag rather than
reopening the old one.

The care is all in what must NOT be closed, because both mistakes look like
success:

- **A check that did not run proves nothing.** No data arrived, a series is too
  short to calibrate an outlier scale against, a policy rate has no cadence to
  judge — each returns `evaluated=False` and closes nothing. Silence is not
  evidence that a condition cleared.
- **A windowed check has no opinion outside its window.** The gap check looks
  back `GAP_WINDOW_DAYS`; without a bound, a real unfixed gap would be closed
  the day it aged out, by a check that had merely stopped looking at it. Each
  check reports the oldest date it examined, and resolution ignores anything
  older.

`transform`-level findings carry the same shape: `Findings(raised, found,
evaluated, since)` in `db/quality.py`, where `raised` is what the run log
reports and `found` is every date the condition currently holds — a flag
re-detected today raises nothing but must stay open.

### The rebasing trap — why slow revisable series are re-fetched in full

A source can restate its **whole history at once**. When FRED re-chain-links a
real-GDP level series it rescales every point by the same factor; the same
happens when a statistical agency moves a CPI index to a new base year. The
values change, but nothing about the series looks wrong afterwards.

This defeats an incremental ingest in a way that is worth spelling out, because
the symptom appears nowhere near the cause. `OVERLAP_DAYS = 14` re-asks for a
fortnight before the watermark, which is several observations for a weekly
series and **less than one** for a quarterly one. So a rebasing was seen only
on the newest point or two — the ones the window happened to reach — and the
stored history became **part old basis, part new**. Each half is perfectly well
behaved. There is no outlier, no gap, no staleness. The damage lands one layer
downstream, in a growth rate computed across the seam, which reports the
rebasing as economic growth.

It happened on 2026-09-08: FRED rescaled `CLVMNACSCAB1GQCH` by +0.70% and
Eurostat's `namq_10_gdp` by +0.55%, and only the last two quarters and the last
quarter respectively were picked up. Swiss GDP published 3.06% YoY against a
current-vintage 2.63%, and the euro area 4.03% annualised against 2.55%.

Two things now hold the line, and both are needed:

- `db/ingest.FULL_REFETCH_CADENCES` — a **revisable** series that publishes
  slower than weekly is re-asked in full every run, never narrowed by the
  watermark. That is the 8 GDP series and the 16 CPI series. They are a few
  hundred rows each, the request is one call either way, and everything
  unchanged hits `ON CONFLICT DO NOTHING`. A rebasing then arrives as new
  vintages across the whole history, and `latest_observations` resolves one
  consistent basis.
- `db/quality.check_basis_break` — flags a series whose newest vintage restated
  only a recent suffix by a **uniform** factor over `BASIS_BREAK_PCT` (0.25%).
  The tell is the shape, not the size: a genuine national-accounts revision
  moves consecutive quarters by different amounts, a rebasing moves them all by
  the same one. Calibrated to fire on the two above and stay silent on the same
  day's real revisions to DE, JP and NO (all under 0.13%).

Note also that `db/quality.check_outliers` was **structurally unable** to see
any of this: its window was a flat 30 days, and a quarterly observation is
dated to the first day of the quarter it describes and published two months
after that quarter ends, so the newest GDP print is routinely 160 days old and
could never enter the window at all. The window is now measured in the series'
own terms — see `outlier_window_days`, which keys off the stored grain
(`store_weekly`) rather than the staleness threshold, because a policy rate is
allowed to be 150 days stale but is stored weekly like a price.

### Dead ends — do not re-attempt without new information

- **Stooq** serves a JavaScript proof-of-work anti-bot page instead of CSV on
  every path. Not solvable headlessly. Replaced by Yahoo.

- **No free euro or sterling INVESTMENT-GRADE credit spread is published.**
  Established rather than assumed, 2026-09-21: FRED's euro coverage is four
  HIGH-YIELD series and it carries no sterling ICE BofA series of any kind; the
  ECB has no corporate-bond dataflow at all, and all 115 public series in its
  `FM` dataflow were enumerated with zero corporate among them. The `ER00` and
  `IBOXX` codes that appear in `CL_PROVIDER_FM_ID` are internal — data queries
  against them 404. ICE, iBoxx and Bloomberg license these indices and the ECB
  licenses rather than republishes them. The BoE publishes only government,
  commercial-bank-liability and OIS curves, no corporate. **What replaced the
  gap is a CONSTRUCTION, not a find** — see `universe.CONSTRUCTED_CREDIT_SPREADS`.

- **No free per-country euro sovereign yield exists above monthly.** The
  spread panel's ECB `IRS` legs are the Maastricht convergence-criterion yield;
  `D.` and `B.` frequencies return nothing, and Eurostat's `irt_lt_mcby_m`
  mirror is the same monthly figure to the decimal. So that table will always
  read behind the daily curves beside it, and sourcing France, Italy and Spain
  from three national publishers would put a cross-publisher methodology gap
  inside the spread. The aggregate `G_N_C − G_N_A` measure is the same quantity
  at daily frequency and is shown beside it.

- **S&P Global's index EPS workbook** (`sp-500-eps-est.xlsx`) is Akamai-blocked:
  HTTP 403 even with a full browser UA and Referer. It would have been the
  best index-level P/E source. `multpl.com` has the number but no CSV, no API
  and no stated terms.

- **Eurostat cannot serve a sport-event-adjusted GDP.** Checked 2026-09-21:
  `namq_10_gdp`'s `s_adj` codelist is exactly `{NSA, SA, CA, SCA}`, and the
  SDMX codelist carries no sport-event concept at all — there is no dimension
  combination that reaches it, so this is a structural absence rather than a
  code that was missed. The adjustment is a SECO construction, and only SECO
  and its redistributors publish it. Switzerland's GDP therefore sits on the
  SNB rather than on the same endpoint as the euro area and Norway.
- **FRED's OECD-sourced national series are frozen.** They still return
  HTTP 200 — which is exactly why the staleness check exists. `*CPIALLMINMEI`
  stops 2025-03/04 (JP: 2021-06), `CPALTT01*` stops 2024-12, `NAEXKP01*Q657S`
  growth is discontinued. CPI moved to BIS; GDP to level series with growth
  derived here.
- ~~**SNB Confederation bond yields are discontinued.**~~ **CORRECTED
  2026-09-13: they were never discontinued. The curve MOVED CUBES.** The
  original entry was right that `rendoblid` and `rendoblim` stop at 2025-07-31
  while returning 200, and right that seven candidate successor ids 404ed on
  2026-08-29. It was wrong to conclude there was no successor: it is
  **`rendeiduebd`**, in the same `ziredev` topic on the same API, with
  `dimSel=D0(CHF)` isolating Swiss Confederation issues and `D1` carrying the
  maturity in years-German (`10J`, not `10Y`). Twelve tenors, `1J`–`10J`, `20J`
  and `30J`, daily, back to 1988-01-04.
  The proof it is the successor, not a different series: it has continuous
  daily data straight through August and September 2025, exactly the window
  where `rendoblid` died. The two overlap and then one takes over.
  **The lesson worth keeping is about method, not Switzerland.** Guessing cube
  ids found nothing seven times; the cube was found by listing what the topic
  actually contains. When a series on an enumerable API appears to vanish,
  enumerate before concluding.
  Still closed, and still true: `rendoeid` is live but is 23 individual bond
  ISINs with yields to maturity, so using it would mean fitting a curve
  ourselves; the EFV/AFF publishes budget and debt series only; and FRED, Yahoo,
  worldgovernmentbonds, FT, MarketWatch and SIX were all checked on 2026-08-29
  and rejected for the reasons recorded then. The TradingEconomics scrape they
  forced has been **retired** — it was the project's only unofficial source,
  and on 2026-09-11 it had the Swiss 2y at 0.270 against the SNB curve's 0.078.
- ~~**ChinaBond is JS-rendered and CFETS refuses all access.**~~ **CORRECTED
  2026-09-13: ChinaBond is reachable. The earlier attempts hit the JavaScript
  FRONT-END path.** The server-rendered endpoints live under
  `cbweb-pbc-web/pbc/` and answer a plain cold GET — no cookies, no session, no
  captcha, no key, and byte-identical with and without a browser User-Agent:

      /cbweb-pbc-web/pbc/historyQuery?startDate=&endDate=&gjqx=0&qxId=ycqx&locale=en_US

  Eight tenors (3M/6M/1Y/3Y/5Y/7Y/10Y/30Y, and **no 2Y**), history to
  2006-03-01. Everything recorded about `queryGjqxInfo`, `getYieldDataForWeb`,
  `queryTypeValues`, `cbweb-czb-web` and CFETS remains true — those paths are
  still dead. They were simply not the only paths.
  Its own traps, since this is a scrape and will break eventually: the response
  carries **three** curves, so match the government one by its name string and
  never by position; a query wider than **365 days** returns HTTP 200 with a
  headers-only page, as does a range with no data, so zero rows must be treated
  as failure; and the backfill therefore walks one calendar year per request.
  Cross-check against OECD SDMX `CHN.M.IRLT`, which is monthly and ~6 weeks
  behind — useful for validation, useless as a feed.
  **Same lesson as the SNB entry:** "the site is JavaScript-rendered" is a
  statement about one path, not about a host.
- **Euro-area MARKET-implied inflation has no free source.** Still true. The
  practitioner standard is the EUR HICPx zero-coupon inflation swap; the ECB
  `FM` dataflow has no ILS series — its `ILS` codes are Israeli shekel. Note
  that since 2026-09-13 the euro area does carry a SURVEY-based expectation
  from the ECB SPF. That is a different quantity, not a substitute, and is
  badged separately for exactly that reason.
- **Eurostat `prc_hicp_manr`/`prc_hicp_midx` and the ECB `ICP` dataset are
  retired, and both still return HTTP 200.** Discovered 2026-09-13. Both sit
  frozen at **2025-12** while answering every query normally; Eurostat's
  databrowser titles the dataset "(1997-2025)". The reason is in the ECB
  payload's own `OBS_COM` field: both were discontinued on **2026-02-04** for
  the ECOICOP ver.2 changeover. The successors are Eurostat
  **`prc_hicp_minr`** — whose item dimension is `coicop18=TOTAL`, not
  `coicop=CP00`, and whose index unit is `I25` (2025=100), not `I15` — and the
  ECB's new **`HICP`** dataflow, which needs `DATA_PROVIDER=4D0`, not `4`. They
  carry identical numbers.
  This is the clearest example here of the failure mode that actually damages a
  dashboard: not an outage, but a **silent freeze behind a 200**, from an
  official publisher. The staleness check with a correct cadence is the only
  thing that catches it.
- **SSB table 14702 is not Norway's headline CPI**, despite being the obvious
  successor to the closed table 03013 (1979M01–2025M12). It is CPI by
  **delivery sector**, and its "consumer goods" aggregate diverges materially
  from the headline: 7.7 against 6.5 in 2023M03, −0.3 against 1.4 in 2020M06.
  The headline index is **table 14710** — one series, no consumption-group
  dimension to pick wrongly, base 2025=100, back to 1920M03. Also: the
  `pxwebapi/v2-beta` host returns 503; the v1 host works and its data retrieval
  is POST-only, and its default selection returns only the latest period.
- **BFS/FSO does not serve Swiss prices on its PxWeb API.** It publishes CPI at
  T+3, against the SNB's T+21, so it is worth wanting. But of the 650 database
  ids the PxWeb v1 root lists, **not one begins `px-x-05`** — domain 05
  (Prices) is simply not there. Checked 2026-09-13. Swiss CPI stays on SNB
  cube `plkopr`.
- **No free investment-grade credit spread exists for any currency but the
  dollar**, and the reason is structural rather than an oversight: the euro,
  sterling and yen IG benchmarks ARE the ICE, iBoxx and Bloomberg indices, and
  ICE licenses only its US series to FRED for free redistribution. FRED release
  `rid=209` was enumerated in full — 192 series — and euro coverage is exactly
  four, all high yield. Two near-misses are traps: `BAMLEMEBCRPIEOAS` is
  EUR-denominated but **EM issuers**, `BAMLEMIBHGCRPIOAS` is IG-rated but **EM
  issuers**. BIS has no corporate credit data at all; the ECB has no corporate
  bond yield dataset (`FM` is government/money-market, `YC` the sovereign
  curve, `STP` short-term paper, `MIR` bank lending); IMF FSI is bank soundness
  ratios; the ESRB dashboard's spread panels are iBoxx/ICE-derived. Rejected as
  proxies and not to be substituted: ECB MIR and BoE effective lending rates
  (bank loan rates to largely unrated borrowers, not bond spreads), IG ETF
  yields, and ECB STEP (a real credit spread, but at overnight-to-91-day
  maturities against a 10y leg, last updated 2026-05-12). What IS free is the
  plainer corporate-minus-government spread, for Germany via Bundesbank BBSIS —
  a different quantity from an OAS, so it lives in its own labelled column.
- **Japan's JSDA gives a rating matrix, not a spread, and not a curve.** The
  `ER` file is an average compound yield per rating across ALL maturities, and
  the sibling `ES` file is per-bond, so a government leg computed the same way
  does not exist — it would have to be constructed by hand, which is a
  different computation from the corporate side. Its URLs also encode one
  business day each (`ER260911.csv`), so history would cost ~6,000 requests,
  and the host returned connect timeouts when polled on 2026-09-13. Closed as
  **not comparable**, not merely expensive. Its parsing trap, since someone
  will try again: the column after the yield looks like a spread and is the
  **standard deviation** — the order is (rating, compound yield, standard
  deviation, number of issues, number of reporting members). JSDA publishes no
  spread.
- **DBnomics and aggregators generally: do not consolidate onto them.** Tested
  2026-09-13, `BIS/WS_CBPOL/M.US` returns **2025-06 = 4.375%** with HTTP 200
  where the true current value from BIS is 2026-08 = 3.625% — 75bp wrong,
  well-formed, no error. Its BIS fetcher broke on the BIS data-portal migration
  over a year ago and has served the stale mirror ever since; its OECD mirror
  is ~3 months behind and its IMF mirror frozen at September 2025. It carries
  neither SNB nor Norges Bank, so Switzerland and Norway could never have been
  consolidated onto it anyway. The general point: an outage is the BENIGN
  failure — loud and obviously a bug. What damages a dashboard is a silent
  freeze, and an aggregator adds a scraping step that can rot with nobody on
  either side noticing. Bespoke parsers fail noisily, which is a monitoring
  feature disguised as a maintenance cost. The OECD's own SDMX API is worth
  having as a **cross-check** (`DSD_STES@DF_FINMARK` gives `IRLT`/`IR3TIB` for
  all eight regions), never as a feed; its CPI dataflow is ~9 months stale for
  CH and NO. **One deliberate exception (2026-10-22): India and Brazil GDP**,
  real and nominal, from `DF_QNA` — no national source offers both legs
  seasonally adjusted in one place, and every alternative was a quarter
  staler (below). It sits behind Cloudflare; see the parsing traps.
- **India/Brazil GDP alternatives, measured 2026-10-22.** World Bank GEM
  (`NYGDPMKTPSAKN`/`SACN`): both at 2026Q1, ~294 days old on arrival. FRED:
  `NGDPRSAXDCINQ`/`NGDPSAXDCINQ` 404; Brazil real `NGDPRSAXDCBRQ` is at
  2026Q2 but its nominal sibling only 2026Q1. IBGE SIDRA publishes current
  prices NSA only. BCB SGS 22109 (SA volume index) answers, but has no nominal
  sibling.
- **India CPI alternatives, measured 2026-10-22.** OECD `DF_PRICES_ALL` ends
  2026-05, FRED `INDCPIALLMINMEI` 2025-03, MOSPI's API returns "No Data Found"
  for the current base. BIS (2026-07) is the freshest free source.
- **No euro-area PPP GDP at the IMF.** DataMapper `PPPGDP` covers the groups
  ADVEC, AS5, DA, OEMDC, EU, WE, MECA and WEOWORLD; `EURO` is absent though it
  carries every other indicator used here. The EU is a different membership
  and a sum of members' PPP figures is not something the IMF publishes.
- **Yahoo has no CSI 300 index history** — `000300.SS`/`399300.SZ` accept only
  `period=1d/5d`. The CNY-priced tracker ETF `510300.SS` stands in.

## Appendix — working notes (moved from CLAUDE.md, 2026-10-22)

The full reasoning behind the one-line rules in CLAUDE.md, kept verbatim when
CLAUDE.md was cut to its rules to save session tokens. Read the relevant entry
before changing the thing it describes. Dated statements are as of writing.

### Status snapshot as of 2026-10-16

Last verified live run (2026-10-22, `--no-publish`): **152/162 `ok`, 5
`partial`, 3 `stale` (Shiller CAPE, JP and IN CPI via BIS), 2 `stubbed`, 0
`failed`.** Database: 233 stored series, 169k observations.
`site/data/latest.json` is ~1.9 MB (~195 KB gzipped). That run the OECD
answered with a Cloudflare challenge (see below), so India and Brazil GDP were
carried on stored data.

2026-10-22 reworked the **Macroeconomics tab**:
- The growth/inflation **regime map is gone from the page**; `payload.regime`
  is still exported and nothing reads it.
- **India and Brazil are macro-only regions** (`universe.MACRO_REGIONS`, the
  eight plus IN/BR). They appear on the Macroeconomics tab and nowhere else;
  `REGIONS`, every other tab and the snapshot selector stay at eight.
- One **Growth & Inflation** table replaced the GDP and Inflation tables: real
  GDP, CPI, **nominal GDP** (the published current-price series,
  `gdp_nominal.*`, not real + CPI), and IMF forecasts for this year and next,
  with a YoY / latest-quarter-annualised switch and uncoloured trend arrows.
- A **GDP by Region** chart from the IMF WEO (`imf.*`): Real (indexed only),
  Nominal USD or PPP, absolute or indexed, projections dashed.
- The **Regional Snapshot** gained a nominal GDP line and a **10-year yield vs
  nominal growth** panel with r − g as its headline.

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

### Conventions, in full

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
  current file and never touches them. Run bootstrap once, by hand. A live run
  that finds no store and cannot download one stops loudly rather than
  silently re-bootstrapping over accumulated history.
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
- **The price-level chart rebases on ONE common month, matched by date.**
  `slicePeriod` cuts each line back from its own last date, and the regions'
  latest releases differ by up to two months, so `dateChart`'s default slice
  would give each region a different base. `priceLevelBlock` picks the base
  itself and passes `presliced`. Its windows are in MONTHS (`PL_PERIOD_MONTHS`;
  YTD is based on the prior December), because a day-count "3M" on month-start
  dates quietly becomes two months.
- **India and Brazil are `MACRO_REGIONS`, not `REGIONS`.** Iterate
  `MACRO_ORDER` (app.js) or `universe.MACRO_REGIONS` (Python) for anything on
  the Macroeconomics tab, and `REGION_ORDER` / `REGIONS` everywhere else. A
  region chart there takes at most eight regions at once (`MAX_LINES`): the
  palette has eight series colours, and ten regions would otherwise put two
  lines in one colour.
- **The IMF WEO block stores projections, and three things follow.** Years
  from the stored edition's year on (`imf.weo_edition`, value YYYYMM) are
  projections; the export ships that boundary as `projection_from` so the
  frontend never guesses it. A future-dated first print is stamped with
  today's vintage (`db/ingest.rows_to_attach`), or the first forecast would
  outrank every revision forever. And `Series.has_projections` exempts these
  series from `check_basis_break`, which every new edition would trip. The
  edition series alone carries the block's staleness (`semiannual`).
- **CPI's 3-month annualised rate is seasonally adjusted HERE**, because every
  stored CPI index is NSA (`transform/growth.seasonally_adjusted_growth_series`:
  classical monthly factors from the previous 8 complete years, no
  look-ahead). It sits beside SA GDP in the same table row, and the
  unadjusted figure is mostly the season. Label it as ours, never the agency's.
- **In the Growth & Inflation table, CPI is on GDP's quarter** (`q_*` fields:
  the quarter's average index, SA for QoQ), not the newest month, so the
  three history cells in a row describe the same three months. The newest
  monthly print is `yoy_pct`/`qoq_ann_pct` and stays the figure everywhere
  else. Even aligned, real + CPI need not equal nominal: the GDP deflator is
  not CPI.
- **IMF nominal growth forecasts are derived** (real growth x deflator growth),
  the deflator coming from the IMF SDMX API (`imf.<R>.deflator`) because the
  DataMapper has no deflator and no national-currency GDP. The SDMX fetcher
  refuses to store anything unless its real growth matches the DataMapper's,
  which is the guard against pairing two WEO editions; keep it.
- **The Growth & Inflation table shows values and arrows only**; every detail
  (period, the other horizon, percentile, basis, source) is in the value's
  tooltip. Add new detail there, not under the number.
- **Norway GDP is MAINLAND (SSB 09190), real and nominal**, since 2026-10-22,
  tagged `Mainland`; total GDP's oil and gas made nominal growth an energy
  price. Its IMF forecasts are total-economy and say so.
- **GDP is on cadence `quarterly_national` (270 days)**, not `quarterly`
  (200): a quarter is dated to its first day and the next one lands 1-2 months
  after it ENDS, so under 200 every GDP series read stale from mid-October on
  a schedule.
- **The OECD SDMX API feeds India and Brazil GDP and nothing else**, and sits
  behind Cloudflare: a burst of manual calls earned a `403` bot challenge on
  2026-10-22. Do not poke it repeatedly while debugging, and never try to get
  around the challenge; the fetcher degrades to `None` and stored history
  carries the series.
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

## Explicitly out of scope

- Intraday / real-time / daily data.
- PMI / economic surprise index.
- Energy-transition/infrastructure-specific layer.
- Non-US free-cash-flow yield, dividend yields, and forward (as opposed to
  trailing) multiples — no free source found. Non-US EV/EBITDA left this list
  on 2026-08-29: Damodaran's `countrystats.xls` publishes it, and it is now
  stored for UK/DE/CH/CN/JP/NO alongside P/E, P/B and P/S.
- Swap curves. The BoE publishes a genuine GBP OIS curve (it ships inside the
  zip already downloaded weekly), but USD swaps died on FRED in 2016 and there
  is no free EUR/CHF/JPY curve, so a "swaps by country" table would have one
  row. Revisit if a multi-country free source appears.
- Bank lending surveys — see the sourcing table.
- Journaling / knowledge-base features — deferred to their own project.
