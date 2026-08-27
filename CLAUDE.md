# CLAUDE.md — session anchor

Personal markets dashboard for Marco. CHF-based (Zurich), covers US/UK/Eurozone/
Germany/Switzerland/China/Japan across equity indices, yield curves, central
bank rates, inflation, real yields, equity risk premia, GDP growth, currencies,
commodities, and equity valuation metrics. Daily EOD refresh, static site on
GitHub Pages, no server to maintain.

Read `SPEC.md` for the full design (content scope, sourcing map, architecture,
phased roadmap). Read `NETWORK.md` before touching `fetch/sources.py` — it
explains why those fetchers were written without live testing and what "first
real run" verification looks like.

## Current status
Live pipeline is real. Last verified run: 50/66 sources `ok`, 1 `stale`,
15 `stubbed`, 0 `failed`.

Working: equity indices / FX / commodities (Yahoo via `yfinance` — Stooq is
dead, it serves a JS anti-bot challenge now), US yield curve + breakevens +
real yields (FRED), policy rates and CPI for all regions (BIS), German/Eurozone
Bund curve (Bundesbank, all four tenors), Japan curve (MOF, all four), UK curve
(BoE, 5y and 10y only), GDP growth (FRED real-GDP levels, YoY derived in the
pipeline).

Still stubbed: Swiss curve (SNB cube discontinued), China curve (ChinaBond is
JS-rendered), UK 2y/30y, Eurozone periphery spreads, ECB/BoE breakevens, and
the whole valuation layer (Shiller/Damodaran/ETF fact sheets).

`NETWORK.md` is now the record of what each endpoint actually returns — read it
before touching `fetch/sources.py`. The User-Agent section in particular is not
optional: FRED breaks if you send a browser UA, BoE and MOF break if you don't.

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
