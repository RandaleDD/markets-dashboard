# Markets Dashboard — V2 Plan

Status: plan, not yet built. Turns the 7 confirmed items from
`v2-enhancements.md` (Cowork project doc) into sourcing, computation, and
frontend work items with a sequence. Written against the actual current
state of `fetch/universe.py`, `transform/`, and `site/index.html` — every
"new source" call below is a genuine gap, not a guess.

**Governing constraint, repeated because it disciplines every item below:**
this dashboard stays descriptive/historical, never prescriptive. Percentile
and z-score context against a series' own history is a fact about that
series and is in scope. Composite scores, "cheap/expensive" labels, and
buy/sell/overweight framing are not, anywhere.

**Not in this plan:** the journaling/knowledge-base idea is explicitly
deferred to its own project (per `v2-enhancements.md`) — do not start it
alongside this work.

## 1. Percentile / z-score context — do first, everything else benefits

**Why first:** pure computation on data already being fetched, zero new
sourcing risk, and Marco called it the single highest-value item.

**The one real design decision:** compute percentile/z-score against each
source's full available history at fetch time, in the pipeline — *not*
against `compact_history`'s stored 1y-daily/5y-weekly archive. The site's own
JSON archive only started accumulating the day this project launched, so a
"10y percentile" sourced from it would be meaningless for years. FRED, BIS,
the Bundesbank, MOF, and Yahoo all serve deep history on the same request
shape already used — pull the long series once, compute the stat, store only
the resulting percentile/z-score (a few numbers) in `latest.json`, and keep
`compact_history`'s trimmed series doing exactly what it does today for the
chart. These are two different jobs against the same fetch and should not be
conflated.

- **Data:** none new. Existing fetchers, called with a longer lookback.
- **Computation:** new `transform/percentile.py`. One function —
  `percentile_context(df, latest_value, windows=[5, 10, "full"])` — returning
  `{"5y": {"pct": .., "z": ..}, "10y": {...}, "full": {...}}`, `None` per
  window when history doesn't reach that far back (e.g. Norway's curve,
  sourced only since Norges Bank's API existed). Guard against near-zero
  variance producing a huge/undefined z-score.
- **Frontend:** no new panel. Every headline number across every existing
  tab gains a small inline annotation ("78th pctl, 10y") wherever a window
  resolved to a value; hidden, not "N/A", where it didn't.
- **Sequencing note:** land this with *one* real series end-to-end (e.g. US
  10y yield) before wiring all ~88, so the "full-history vs. stored-archive"
  distinction gets caught by a real run rather than assumed correct.

## 2. Cost-of-capital panel

Stacks real risk-free yield + credit spread + ERP per region — the literal
inputs to discounting long-duration private assets.

- **Data required:**
  - Real risk-free yield: already live for US (`DFII10`) and UK (BoE GLC
    real curve). No free real-yield series exists for EZ/DE/CH/CN/JP/NO —
    same gap `SPEC.md` already documents for inflation expectations, so this
    panel will show 2 of 8 regions at launch, not a new failure.
  - Credit spread: **new.** FRED carries ICE BofA OAS series free and
    keyless, same `fetch_fred` fetcher already used — `BAMLC0A0CM` (US IG),
    `BAMLH0A0HYM2` (US HY). US-only; no free non-US OAS series found in this
    pass. Add both to `universe.py` under a new `CREDIT_SPREADS` block.
  - ERP: already live for US (Damodaran), stubbed elsewhere per `SPEC.md`.
- **Computation:** extend `transform/erp.py` or add
  `transform/cost_of_capital.py` with `stack_cost_of_capital(real_yield,
  credit_spread, erp) -> dict`, simple sum, `None`-safe per leg so a region
  with 2 of 3 legs still shows what it has rather than dropping the row.
- **Frontend:** new panel inside the **Yield Curves** tab (it's a yield-curve
  derivative, not new macro data) — or **Macroeconomics** if that reads
  cleaner once built; either is defensible, pick one and be consistent with
  where ERP already lives today.
- **Sequencing:** after item 1, before item 3 (shares the new OAS fetch).

## 3. Credit / liquidity cycle layer

Elevates IG/HY spreads to a headline panel, adds SLOOS as a liquidity proxy.

- **Data required:**
  - IG/HY OAS: same two FRED series as item 2 — no duplicate fetch, just
    surfaced in two places.
  - SLOOS: **new**, but same fetcher. FRED carries the Fed's Senior Loan
    Officer survey net-tightening series keyless — `DRTSCILM` (C&I loans,
    large/medium firms) is the standard headline one. Quarterly, US-only
    (SLOOS has no free non-US equivalent — ECB runs its own Bank Lending
    Survey but not on a keyless feed found in this pass).
- **Computation:** none beyond level + change, which `transform/returns.py`'s
  `compute_return_metrics` already does generically — SLOOS just needs to
  not break on quarterly-cadence data (check `MAX_AGE_DAYS` staleness logic
  uses the series' actual cadence, not a daily assumption, or every reading
  will show `stale`).
- **Frontend:** new panel in **Macroeconomics** tab, below policy rates —
  labelled explicitly as US-only, not left to look like a gap.
- **Sequencing:** right after item 2 (shares the fetch, same FRED pattern).

## 4. FX hedging cost context

CHF investor's actual cost of hedging USD/EUR fund exposure back to CHF.

- **Data required:** **no clean free source for actual cross-currency basis
  swap quotes** — that's an interbank OTC market, not published free
  anywhere found in this pass (same category of gap as the euro-area
  inflation swap). The practical substitute: approximate via covered interest
  rate parity — the policy-rate differential between CHF and USD/EUR is
  already being fetched (`CENTRAL_BANKS` in `universe.py`) and is the
  dominant driver of hedging cost even though it isn't the traded basis
  itself.
- **Computation:** new `transform/fx_hedging.py`:
  `approx_hedging_cost(base_ccy_rate, chf_rate) -> float` (simple
  differential, annualized). **Must be labelled "approximated from policy
  rate differential, not a traded basis swap quote"** wherever it's shown —
  this is exactly the kind of unlabelled-number risk `CLAUDE.md`'s
  conventions already warn about, and here the approximation itself is
  the caveat, not just the unit.
- **Frontend:** new panel in **Currencies** tab, CHF vs. USD and CHF vs. EUR
  only (the two Marco actually named).
- **Sequencing:** after items 2-3. No new fetches, but the labelling is the
  hard part and deserves unhurried attention — don't rush this one to hit a
  sequencing target.

## 5. Growth/inflation regime quadrant map

Two-axis chart, rising/falling growth × rising/falling inflation, all 8
regions plotted as points migrating over time.

- **Data required:** none new. GDP growth (`GDP_GROWTH`) and CPI YoY
  (`INFLATION_CPI`) are both already live for all 8 regions.
- **Computation:** new `transform/regime.py`:
  `regime_coordinates(gdp_growth_series, cpi_yoy_series) -> [{date, growth_delta, inflation_delta}, ...]`
  — "rising/falling" needs a defined window (e.g. QoQ change in the YoY
  rate, not the level) — pick one, state it in the code comment, and carry
  it into the UI label so it's inspectable, per the "every number states its
  definition" convention.
- **Frontend:** genuinely new — a scatter/quadrant chart with 8 labelled
  points and a way to scrub through time (even a simple date slider over the
  last ~8 quarters). This is real frontend work, not a table. New standalone
  tab, **"Regime Map"**, or fold into a new combined tab with item 6 (see
  sequencing) — decide once item 6's scope is also clear.
- **Sequencing:** after item 1 (percentile engine can annotate the axes,
  e.g. "growth: 3rd percentile" adds useful context to a quadrant position),
  independent of items 2-4.

## 6. Rolling cross-asset correlation heatmap

Equities vs. bonds vs. gold vs. USD, 60-90 day rolling window.

- **Data required:**
  - Equities: already live (use a broad regional proxy, e.g. S&P 500 for US,
    or an aggregate — decide one representative series per bloc rather than
    all 12 indices, or the heatmap becomes unreadable).
  - Gold, USD (DXY): already live.
  - Bonds: **new.** No bond price series exists yet — the pipeline only
    fetches *yields*, not tradeable bond returns. Needs a government-bond
    total-return proxy via `yfinance`, same convention already used for
    `csi300`/`bcom` (ETF standing in for an index) — e.g. `IEF` (7-10y UST)
    or `TLT` (20y+ UST) added to a new `BOND_PROXIES` block in
    `universe.py`. This is the one item in the whole plan needing a genuinely
    new instrument, not just a new series from an existing source.
- **Computation:** new `transform/correlation.py`:
  `rolling_correlation_matrix(series_dict, window_days=60) -> matrix` —
  pairwise Pearson on daily returns, `None` where either leg has insufficient
  history in the window.
- **Frontend:** new chart type not in the site today — a heatmap grid.
  Consult the dataviz skill for a heatmap component before building one from
  scratch. Pairs with item 5 in a new tab (working name **"Cross-Asset &
  Regime"**) since both are cross-region comparison views that don't belong
  inside any single existing region-by-region tab.
- **Sequencing:** last — it's the only item needing a new instrument *and* a
  new chart type *and* new rolling-window computation together. Doing it
  last means the pipeline conventions (staleness handling, `source_status`,
  percentile engine) are already proven on five simpler items first.

## 7. Cross-sectional valuation scorecard

CAPE and ERP for all 8 regions side by side, instead of buried per-region.

- **Data required:** none new, but genuinely thin today — CAPE is US-only
  (Shiller) and ERP is US-only (Damodaran); non-US P/E via ETF fact sheets is
  still Phase 4 and unimplemented (`SPEC.md`). **This scorecard will show 1
  of 8 regions at launch.** Build it anyway — it's cheap and it's the
  natural place non-US valuation lands the moment Phase 4 ships — but say so
  in the panel itself rather than let a near-empty chart look broken.
- **Computation:** none new — reads the same CAPE/ERP fields
  `transform/erp.py` already produces, just reshapes them across regions
  instead of within one.
- **Frontend:** new panel inside the existing **Valuation** tab, above or
  beside the current per-region rows.
- **Sequencing:** cheap, do it alongside item 2 (same tab, same data).

## Rough sequencing (dependency-ordered, not time-boxed)

| Phase | Items | Why this grouping |
|---|---|---|
| A | 1 (percentile/z-score) | Foundation; every later item can lean on it |
| B | 2 (cost-of-capital), 7 (valuation scorecard) | Near-zero new sourcing, same tabs as existing panels |
| C | 3 (credit/liquidity) | Shares item 2's new OAS fetch |
| D | 4 (FX hedging cost) | No new fetch, but labelling needs care — don't rush |
| E | 5 (regime map) | No new sourcing, but real new frontend chart type |
| F | 6 (correlation heatmap) | Only item needing a new instrument + new chart type together; do last |

## Before writing code
Confirm `BAMLC0A0CM`/`BAMLH0A0HYM2`/`DRTSCILM` still resolve on
`fredgraph.csv` and log whatever's actually returned in `NETWORK.md`'s
format (this project's convention: record quirks and dead ends as they're
found, not just successes) — these three are the only genuinely new fetches
this whole plan introduces; everything else is new computation on data
already flowing.
