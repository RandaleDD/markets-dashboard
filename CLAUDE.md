# CLAUDE.md — session anchor

Personal markets dashboard for Marco. CHF-based (Zurich), covers US/UK/Eurozone/
Germany/Switzerland/China/Japan across equity indices, yield curves, central
bank rates, inflation, real yields, equity risk premia, GDP growth, currencies,
commodities, and equity valuation metrics. Daily EOD refresh, static site on
GitHub Pages, no server to maintain.

Read `SPEC.md` for the full design (content scope, sourcing map, architecture,
phased roadmap). Read `NETWORK.md` before touching `fetch/sources.py` — it
records what every endpoint actually returns and which ones have no free
source at all.

## Current status
Live and deployed at https://randaledd.github.io/markets-dashboard/.
Last verified run: 63/88 sources `ok`, 4 `stale`, 21 `stubbed`, 0 `failed`.

Working: equities/FX/commodities (Yahoo, with clickable multi-period charts),
US curve + TIPS real yields + breakevens (FRED), UK nominal/real/implied-inflation
curves (BoE GLC workbooks), Eurozone all-bonds curve and per-country spreads
(ECB), Bund curve (Bundesbank), JGB curve (MOF), Norwegian curve and policy rate
(Norges Bank), policy rates and CPI for all regions (BIS), GDP (FRED real levels),
US CAPE (Shiller) and ERP (Damodaran).

Still stubbed: Swiss curve beyond a monthly lagged 10y, China curve entirely,
euro-area market-implied inflation, and non-US P/E and dividend yield.

The four `stale` entries are all genuine publication lag, not bugs: UK and
Norway GDP, the Swiss monthly 10y, and Shiller's CAPE file (ends 2024-09).

`NETWORK.md` is the record of what each endpoint actually returns — read it
before touching `fetch/sources.py`. The User-Agent section is not optional:
FRED breaks if you send a browser UA, BoE and MOF break if you don't.

## Working conventions
- One series/region = one entry in `fetch/universe.py`. Never hardcode a
  ticker or series ID anywhere else.
- Every fetcher in `fetch/sources.py` returns `None` on failure, never
  raises — the pipeline must survive individual source outages.
- `python pipeline.py --mode sample` regenerates synthetic data for frontend
  work without needing live network access.
- `python pipeline.py --mode live` is the real thing — run it, then open
  `site/index.html` via a local server (not `file://`, the JSON fetch needs
  http) to check what actually came back.
- Update `source_status` handling in `pipeline.py` if you add a new fetcher —
  the frontend's "not yet wired" stub label is driven by `None` values in the
  JSON, not by `source_status` directly, so make sure a failed fetch degrades
  to `None` rather than a partial/malformed value.
- A source returning HTTP 200 is not the same as a source being current. Every
  series is age-checked against `MAX_AGE_DAYS` and marked `stale` if it's
  behind its publication cadence — `stale` is a failure, not a pass. Give any
  new fetcher the right cadence.
- Sources disagree on headers, so pass them per-source via `_get(...)`; there
  is no global header set that works (see NETWORK.md).
- Every displayed number must state its definition. Contract and unit for
  commodities, real-vs-nominal and YoY-vs-annualised for GDP, tenor and index
  basis for inflation expectations. An unlabelled number that is not comparable
  to the ones beside it is a reporting error, not a data point.
- Derived spreads must take both legs from the same source and vintage —
  ECB's German yield differs from the Bundesbank's, so mixing them would put
  the methodology gap into the spread.
- `pipeline.py` must attach `out["source_status"] = status` before returning;
  `_empty_payload` creates its own empty dict.
