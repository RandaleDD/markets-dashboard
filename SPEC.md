# Markets Dashboard — Spec

Living design doc. Also mirrored (in more discussion-oriented form) in
Marco's "Markets dashboard" Claude project as `content-taxonomy.md`,
`sourcing-map.md`, and `build-plan.md` — this file is the consolidated,
build-facing version.

Live at https://randaledd.github.io/markets-dashboard/.

## Scope decisions (confirmed)
- Regions at full depth: US, UK, Eurozone, Germany, Switzerland, China, Japan,
  Norway. Everything else (broader EM, rest of APAC) is secondary/thin — only
  an MSCI EM proxy is carried, under its own `EM` heading.
- Refresh: daily, end-of-day. No intraday/real-time.
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
  Currencies, Commodities, Valuation (+ risk premia), Regional Snapshot. Each
  table shows all regions side by side. Regional Snapshot inverts that: a
  region selector showing one region's equities, curve, macro, valuation and
  FX together, grouped the same way as the tabs. Commodities are excluded
  there — they are global.
- Visualization: tables carry current-state data with sparklines. Clicking any
  sparkline expands an inline line chart with selectable lookback
  (3M/YTD/1Y/2Y/3Y/5Y, default 1Y). History is stored daily for the most recent
  year and weekly before that, so five years costs ~460 points per series
  rather than ~1260.
- **Every figure states its definition.** Commodity rows carry exchange,
  contract and unit; GDP is labelled real / chain-linked / local currency /
  seasonally adjusted with both YoY and annualised QoQ; inflation expectations
  carry tenor and index basis. An unlabelled number sitting next to ones it
  isn't comparable with is a reporting error, not a data point.

## Data sourcing
Endpoint mechanics, quirks and dead ends are in `NETWORK.md`. This table is
what each category actually uses today.

| Category | Source | State |
|---|---|---|
| Prices / FX / commodities | Yahoo Finance via `yfinance` | Live, all 12 indices, 8 FX pairs, 7 commodities |
| Central bank policy rates | BIS Data Portal `CBPOL` (7 regions); Norges Bank for Norway | Live. Germany mirrors the ECB rate rather than showing a blank |
| CPI, all 8 regions | BIS Data Portal `WS_LONG_CPI` | Live. Returns YoY and the index level in one response, so annualised QoQ is derived from the same fetch |
| GDP growth | FRED real-GDP *level* series (`GDPC1`, `CLVMNACSCAB1GQ*`, `NGDPRSAXDCGBQ`, `JPNRGDPEXP`, `NGDPRXDCCNA`) | Live. YoY and annualised QoQ derived in the pipeline so every region shares one definition. China is annual-only |
| US yield curve, real yields, breakevens | FRED (`fredgraph.csv`, no API key) | Live — nominal `DGS*`, real `DFII5/10/30`, breakevens `T5YIE`/`T10YIE`/`T5YIFR` |
| US 1y inflation expectation | Cleveland Fed `EXPINF*` via FRED | Live, badged **model**-implied — no 1y TIPS breakeven is published |
| UK curve, real yields, implied inflation | Bank of England GLC workbooks (one zip, nominal + real + inflation) | Live, all four tenors. Replaced the IADB series, which only publish 5y/10y/20y |
| Eurozone curve | ECB Data Portal `YC`, all-bonds euro area curve | Live, all four tenors |
| Euro-area sovereign spreads (FR/IT/ES) | ECB Data Portal `IRS` per-country long-term rates | Live, monthly. Both legs from this same series |
| Germany curve | Deutsche Bundesbank daily Bund term structure | Live, all four tenors |
| Japan curve | Japan MOF JGB interest rate CSV | Live, all four tenors. Chosen over the originally-specced JSDA OTC prices, which are per-bond xlsx needing tenor inference |
| Norway curve | Norges Bank `GOVT_ZEROCOUPON` | Live to 10y — **no 30y is published**, so that cell stays blank |
| Switzerland curve | FRED `IRLTLT01CHM156N` | 10y only, monthly and ~2 months behind, flagged as such in the UI. The SNB retired its own curve |
| China curve | — | **No free source.** ChinaBond is JS-rendered and CFETS rejects all programmatic access |
| Euro-area / CH / CN / JP / NO inflation expectations | — | **No free source.** The practitioner standard is the zero-coupon inflation swap, which is not published free |
| US equity valuation | Shiller CAPE (`ie_data.xls`); Damodaran implied ERP (FCFE) | Live. Shiller's file currently ends 2024-09, so it reports `stale` |
| Non-US equity valuation | Monthly ETF/index fact sheets | **Not implemented.** PDF table extraction, still Phase 4 |

Ten institutions, and still gaps. No single source covers this, free or paid
short of a full commercial terminal — the spread of sources is by design, not
an oversight.

## Architecture
Python pipeline (`fetch/` + `transform/`) → static JSON (`site/data/latest.json`)
→ static frontend (`site/`) reading that JSON → GitHub Actions runs the
pipeline daily and redeploys to GitHub Pages. No server to maintain; a public
URL accessible from anywhere, matching the original ask.

`daily.yml` does all the work: it runs the full pipeline, commits the
refreshed `latest.json`, and deploys the site. `monthly.yml` exists but is
**still a placeholder that runs an echo** — the original plan was to split
slow-moving series (CPI, GDP, valuation) onto a monthly cadence, but the daily
job fetches all of them and the split has not been needed. Anything claiming
two live cadences is out of date.

The daily commit of `latest.json` is deliberate: it builds a dated archive of
what was known on each day, which matters for GDP and CPI figures that get
revised later. It is not needed for the site to deploy (Pages serves the
workflow artifact), and it is the reason local edits conflict with bot commits.

## Phased roadmap
0. ✅ Scaffold + sample-data pipeline + frontend.
1. ✅ Prices/FX/commodities (Yahoo), US curve + breakevens + real yields
   (FRED), policy rates and CPI (BIS).
2. ✅ Non-US yield curves. Germany (Bundesbank), Japan (MOF), UK (BoE GLC),
   Eurozone (ECB), Norway (Norges Bank), all at full tenor coverage where the
   source publishes it. Switzerland is degraded to a monthly 10y and China is
   unsourced — both because no free source exists, not because of pending work.
3. ✅ Euro-area sovereign spread panel (ECB, FR/IT/ES). The ECB breakeven half
   of this phase is **closed as not possible** — there is no free euro-area
   inflation-swap feed.
4. **In progress** — valuation layer. US is live (Shiller CAPE, Damodaran
   ERP). Non-US P/E and dividend yield still need ETF fact-sheet PDF
   extraction (e.g. `pdfplumber`), which is not implemented.
5. Polish: small-multiple yield curve charts, further chart treatment per the
   dataviz skill, mobile layout pass.
6. Stretch: proper IBKR API integration (Client Portal Web API with real
   session auth) to replace yfinance as the live price layer. IBKR is usable
   for ad hoc checks today but needs an authenticated session, so it is not a
   fit for a headless job.

## Explicitly out of scope for v1
- Intraday/real-time data.
- PMI / economic surprise index.
- Energy-transition/infrastructure-specific layer.
- CHF-converted equity returns (local currency only).
- Non-US FCF yield / EV-EBITDA (no free source found).
