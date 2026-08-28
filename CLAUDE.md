# CLAUDE.md — session anchor

Personal markets dashboard for Marco. CHF-based (Zurich), 8 regions
(US/UK/Eurozone/Germany/Switzerland/China/Japan/Norway) across equities, yield
curves, macro, currencies, commodities and valuation. Daily EOD refresh, static
site on GitHub Pages, no server to maintain.

Live: https://randaledd.github.io/markets-dashboard/

- `SPEC.md` — scope decisions, the sourcing table (what every category uses and
  where the permanent gaps are), architecture, roadmap. **The sourcing table is
  authoritative; don't restate it here.**
- `NETWORK.md` — what each endpoint actually returns, its quirks, and the dead
  ends already ruled out. Read it before touching `fetch/sources.py`.

## Current status
Last verified live run: **63/88 `ok`, 4 `stale`, 21 `stubbed`, 0 `failed`.**

`stale` and `stubbed` here are expected, not a to-do list. The 4 stale are real
publication lag (UK and Norway GDP, the Swiss monthly 10y, Shiller's CAPE file
ending 2024-09). The 21 stubbed are the gaps SPEC.md records as having no free
source — the China curve, six regions' inflation expectations, and non-US
valuation and risk premia. Chasing them again is wasted effort unless a new
source appears; NETWORK.md lists what has already been tried and failed.

Re-run `python3 pipeline.py --mode live` to refresh these numbers before
trusting them — this section is a snapshot and goes stale on its own.

## Working conventions
- One series/region = one entry in `fetch/universe.py`. Never hardcode a
  ticker or series ID anywhere else.
- Every fetcher in `fetch/sources.py` returns `None` on failure, never
  raises — the pipeline must survive individual source outages.
- `python3 pipeline.py --mode sample` regenerates synthetic data for frontend
  work without network access. It must keep producing the same JSON shape as
  live mode, or the no-network path silently rots.
- `python3 pipeline.py --mode live` is the real thing — run it, then serve the
  site over http (`cd site && python3 -m http.server 8000`). `file://` will not
  work; the JSON fetch needs http.
- A failed fetch must degrade to `None`, never a partial or malformed value —
  the frontend's "not yet wired" label is driven by `None` in the JSON, not by
  `source_status`.
- HTTP 200 is not the same as current. Every series is age-checked against
  `MAX_AGE_DAYS` and marked `stale` if it is behind its publication cadence.
  **`stale` is a failure, not a pass.** Give any new fetcher the right cadence.
- Pass headers per-source via `_get(...)`; there is no global set that works.
  FRED breaks if you send a browser User-Agent, BoE and MOF break if you don't.
- Prefer one request per curve over one per tenor, and bound big payloads with
  `startPeriod`. Per-tenor fetching turned a single transient failure into a
  `partial` curve, and unbounded ECB/BIS history hit read timeouts.
- Every displayed number must state its definition — contract and unit for
  commodities, real-vs-nominal and YoY-vs-annualised for GDP, tenor and index
  basis for inflation expectations. An unlabelled number that isn't comparable
  to the ones beside it is a reporting error, not a data point.
- Derived spreads must take both legs from the same source and vintage. ECB's
  German yield differs from the Bundesbank's, so mixing them would put that
  methodology gap into the spread.
- `pipeline.py` must set `out["source_status"] = status` before returning —
  `_empty_payload()` creates its own empty dict, so forgetting this silently
  ships a payload with no status block.
- `daily.yml` commits the refreshed `latest.json` on every run, so expect merge
  conflicts on that file when pushing local work. It is generated output: take
  your regenerated version, don't hand-merge it.
- Never reference `assets/*` without the version query string. Pages caches
  assets for 10 minutes, so unversioned URLs can pair fresh HTML with stale JS
  and render a panel blank with nothing wrong in the code.
  `stamp_asset_versions()` maintains these; don't strip them by hand.
- Equity index *levels* deliberately carry no percentile annotation — a price
  percentile on a trending series is always near 100th and says nothing.
  Volatility and drawdown carry it instead. This is accepted, not a gap.
- No Node on this machine (`brew install node` fails on a simdjson bottle).
  To actually execute `site/assets/app.js`, use `osascript -l JavaScript` with
  a DOM shim — see NETWORK.md.
