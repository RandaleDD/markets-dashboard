# Markets Dashboard — Spec

Living design doc. Also mirrored (in more discussion-oriented form) in
Marco's "Markets dashboard" Claude project as `content-taxonomy.md`,
`sourcing-map.md`, and `build-plan.md` — this file is the consolidated,
build-facing version.

## Scope decisions (confirmed)
- Regions at full depth: US, UK, Eurozone, Germany, Switzerland, China, Japan,
  Norway (added 2026-08).
  Everything else (broader EM, rest of APAC) is secondary/thin.
- Refresh: daily, end-of-day. No intraday/real-time.
- Equity index returns: local/respective currency, no CHF conversion.
- Eurozone yield curve: **superseded 2026-08.** The Bund was originally the
  euro benchmark, but that made the Eurozone row a duplicate of Germany (ECB
  AAA 10Y 3.28 vs Bund 3.22). The Eurozone row is now the ECB's ALL-bonds euro
  area curve — a genuine multi-sovereign blend (3.70 the same day) — with
  Germany kept alongside as the single-issuer Bund curve. A euro-area sovereign
  spread panel (France/Italy/Spain vs. Bund) sits below; "periphery" was
  dropped as a label since these are core economies.
- China equities: CSI 300 (mainland) and Hang Seng (Hong Kong) both shown,
  not merged.
- Oil: Brent only, WTI deliberately dropped.
- PMI / economic surprise index: dropped entirely (no clean free multi-country
  historical source exists). GDP section is actual growth data only.
- Primary layout: organized by asset class, in 7 tabs — Equity Indices, Yield
  Curves (nominal + real + implied inflation + euro spreads), Macroeconomics
  (policy rates + inflation + GDP), Currencies, Commodities, Valuation
  (+ risk premia), Regional Snapshot — each showing all regions side by side. A secondary "Regional Snapshot" page has a region
  selector showing that region's equities/yield curve/macro/FX in one place
  (commodities excluded there — they're global).
- Visualization: tables carry current-state data with sparklines. Clicking any
  sparkline expands an inline line chart with selectable lookback
  (3M/YTD/1Y/2Y/3Y/5Y, default 1Y). History is stored daily for the most recent
  year and weekly before that, so five years costs ~460 points per series
  rather than ~1260.
- Every figure states its definition: commodity contracts carry exchange and
  unit, GDP is labelled real/chain-linked/local-currency/SA with both YoY and
  annualised QoQ, and inflation expectations carry tenor and index basis
  (CPI vs RPI).

## Data sourcing (confirmed institutions — see NETWORK.md for endpoint status)
| Category | Source |
|---|---|
| Prices/FX/commodities | Yahoo Finance via `yfinance`. Stooq was the original primary but now serves a JS proof-of-work anti-bot challenge on every path and is unusable headlessly — dropped 2026-08. IBKR available for ad hoc checks but not automation-friendly (needs an authenticated session, not a fit for a headless job). |
| Central bank policy rates | BIS Data Portal, `CBPOL` dataset — one source covers Fed/ECB/BoE/SNB/PBoC/BoJ. |
| US yield curve, breakevens, real yields | FRED (`fredgraph.csv`, no API key needed). |
| CPI, all regions | BIS Data Portal, `WS_LONG_CPI` dataflow. FRED's OECD-sourced national CPI series are all frozen (see NETWORK.md), so BIS replaced it — one source, all seven regions, year-on-year percent directly. |
| GDP growth | FRED real-GDP *level* series (`GDPC1`, `CLVMNACSCAB1GQ*`, `NGDPRSAXDCGBQ`, `JPNRGDPEXP`, `NGDPRXDCCNA`); year-on-year growth is derived in the pipeline so every region shares one definition. The OECD `NAEXKP01*` growth series are discontinued. |
| Germany/Eurozone benchmark curve | Deutsche Bundesbank daily Bund term structure. |
| UK curve + breakevens | Bank of England IADB CSV export. Note the IADB nominal zero-coupon set covers 5y/10y/20y only — no 2y or 30y — so those two tenors are blank pending a parse of the BoE GLC yield-curve workbook. |
| Switzerland curve | SNB Data Portal — the `rendoblid` cube is discontinued (last observation 2025-07-31), so this is currently unsourced rather than showing stale data. Needs a successor cube id. |
| China curve | ChinaBond English portal — JS-rendered, no plain-HTTP data endpoint confirmed. Still unsourced. |
| Japan curve | Japan Ministry of Finance JGB interest rate CSV — the full 1Y–40Y curve in one file. Chosen over the originally-specced JSDA OTC reference prices, which are per-bond .xlsx workbooks needing Excel parsing and tenor inference. |
| Eurozone periphery spread (FR/IT/ES vs. Bund) | Banque de France (Webstat/MTS France), Banca d'Italia (Infostat), Banco de España — institutions confirmed, exact series TBD. |
| Eurozone breakeven inflation | ECB Data Portal "inflation-linked" category confirmed to exist; exact SDW series key TBD. |
| US equity valuation (CAPE, ERP) | Shiller (Yale/multpl.com), Damodaran (NYU Stern). |
| Non-US equity valuation | Monthly ETF/index fact sheets (iShares etc.) — P/E, P/B, div yield only, ~1 month lag. No free source anywhere for non-US FCF yield or EV/EBITDA at index level. |

No single source covers everything, free or paid short of a full commercial
terminal — this is a ~6-source stack by design, not an oversight.

## Architecture
Python pipeline (`fetch/` + `transform/`) → static JSON (`site/data/latest.json`)
→ static frontend (`site/`) reading that JSON → GitHub Actions runs the
pipeline daily and redeploys to GitHub Pages. No server to maintain; a public
URL that's accessible from anywhere, matching the original ask.

Two cadences: `daily.yml` (prices, curves, policy rates, breakevens) and
`monthly.yml` (CPI/GDP, valuation metrics — these sources don't move more
often than that anyway).

## Phased roadmap
0. ✅ Scaffold + sample-data pipeline + frontend, visually verified.
1. ✅ Done — prices/FX/commodities (Yahoo), US curve + breakevens + real
   yields (FRED), policy rates and CPI (BIS). All confirmed against live
   responses 2026-08-28; see NETWORK.md for each endpoint's quirks.
2. **In progress** — non-US yield curves. Done: Germany/Eurozone (Bundesbank,
   all four tenors), Japan (MOF, all four), UK (BoE, 5y/10y only).
   Outstanding: UK 2y/30y, Switzerland (SNB cube discontinued), China
   (ChinaBond is JS-rendered).
3. Eurozone periphery spread panel + ECB breakeven series — stubbed,
   institutions confirmed, exact series TBD.
4. Valuation-metrics layer (Shiller/Damodaran US, ETF fact-sheet scrape
   non-US) — stubbed; fact-sheet scraping needs a PDF-table-extraction step
   (e.g. `pdfplumber`), not yet implemented at all.
5. Polish: small-multiple yield curve charts, better sparkline/chart
   treatment per the dataviz skill, mobile layout pass.
6. Stretch: proper IBKR API integration (Client Portal Web API with real
   session auth) to replace yfinance as the live price layer.

## Explicitly out of scope for v1
- Intraday/real-time data.
- PMI / economic surprise index.
- Energy-transition/infrastructure-specific layer.
- CHF-converted equity returns (local currency only).
- Non-US FCF yield / EV-EBITDA (no free source found).
