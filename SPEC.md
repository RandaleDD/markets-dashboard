# Markets Dashboard — Spec

Living design doc. Also mirrored (in more discussion-oriented form) in
Marco's "Markets dashboard" Claude project as `content-taxonomy.md`,
`sourcing-map.md`, and `build-plan.md` — this file is the consolidated,
build-facing version.

## Scope decisions (confirmed)
- Regions at full depth: US, UK, Eurozone, Germany, Switzerland, China, Japan.
  Everything else (broader EM, rest of APAC) is secondary/thin.
- Refresh: daily, end-of-day. No intraday/real-time.
- Equity index returns: local/respective currency, no CHF conversion.
- Eurozone yield curve: Germany's Bund curve is the benchmark shown directly
  (Deutsche Bundesbank, literal single-issuer curve — not the ECB's AAA-rated
  aggregate). A separate periphery spread panel (France/Italy/Spain vs. Bund)
  sits alongside it.
- China equities: CSI 300 (mainland) and Hang Seng (Hong Kong) both shown,
  not merged.
- Oil: Brent only, WTI deliberately dropped.
- PMI / economic surprise index: dropped entirely (no clean free multi-country
  historical source exists). GDP section is actual growth data only.
- Primary layout: organized by asset class (10 sections), each showing all
  regions side by side. A secondary "Regional Snapshot" page has a region
  selector showing that region's equities/yield curve/macro/FX in one place
  (commodities excluded there — they're global).
- Visualization: tables carry current-state data with sparklines; full line
  charts where history shape is the point (equity levels, real yields, ERP,
  CAPE). Lookback: 1Y default, except CAPE/Shiller and real yields, which
  need a multi-decade baseline to mean anything.

## Data sourcing (confirmed institutions — see NETWORK.md for endpoint status)
| Category | Source |
|---|---|
| Prices/FX/commodities | Stooq (primary, automation-friendly), yfinance (fallback). IBKR available for ad hoc checks but not automation-friendly (needs an authenticated session, not a fit for a headless job). |
| Central bank policy rates | BIS Data Portal, `CBPOL` dataset — one source covers Fed/ECB/BoE/SNB/PBoC/BoJ. |
| US yield curve, breakevens, real yields, CPI, GDP | FRED (`fredgraph.csv`, no API key needed). |
| Germany/Eurozone benchmark curve | Deutsche Bundesbank daily Bund term structure. |
| UK curve + breakevens | Bank of England yield-curve statistics (also has UK DMO as a second option for the curve alone). |
| Switzerland curve | SNB Data Portal. |
| China curve | ChinaBond English portal. |
| Japan curve | JSDA reference OTC bond yields. |
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
1. **In progress** — US core (FRED) + BIS policy rates + Stooq prices, written
   but not live-tested (see NETWORK.md). This is the first thing to verify
   for real.
2. Non-US yield curves (SNB, Bundesbank, ChinaBond, JSDA, BoE/DMO) — stubbed,
   most fragmented category, budget the most time here.
3. Eurozone periphery spread panel + ECB breakeven series — stubbed,
   institutions confirmed, exact series TBD.
4. Valuation-metrics layer (Shiller/Damodaran US, ETF fact-sheet scrape
   non-US) — stubbed; fact-sheet scraping needs a PDF-table-extraction step
   (e.g. `pdfplumber`), not yet implemented at all.
5. Polish: small-multiple yield curve charts, better sparkline/chart
   treatment per the dataviz skill, mobile layout pass.
6. Stretch: proper IBKR API integration (Client Portal Web API with real
   session auth) to replace Stooq/yfinance as the live price layer.

## Explicitly out of scope for v1
- Intraday/real-time data.
- PMI / economic surprise index.
- Energy-transition/infrastructure-specific layer.
- CHF-converted equity returns (local currency only).
- Non-US FCF yield / EV-EBITDA (no free source found).
