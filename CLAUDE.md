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
Repo scaffolded, sample-data pipeline + frontend working end-to-end and
visually verified. Live fetchers written for Stooq (prices/FX/commodities)
and FRED (US yields/breakevens/real yields/CPI/GDP) — UNTESTED against live
data, see NETWORK.md. BIS policy-rate fetcher written but endpoint format is
a best guess, needs confirming. Non-US yield curves (SNB/Bundesbank/
ChinaBond/JSDA/BoE-DMO), the Eurozone periphery spread panel, ECB breakeven,
and the equity-valuation layer (Shiller/Damodaran/ETF fact sheets) are all
stubbed in `fetch/sources.py` with the confirmed institution + a TODO —
that's the next work, see SPEC.md's phased roadmap.

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
