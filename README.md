# Markets Dashboard

Personal markets dashboard — equity indices, yield curves, central bank rates,
inflation and inflation expectations, real yields, credit spreads, equity risk
premia, GDP growth, currencies, commodities, valuation, cross-asset
correlation and a growth/inflation regime map, across
US/UK/Eurozone/Germany/Switzerland/China/Japan/Norway.

Static site, refreshed weekly by GitHub Actions, hosted free on GitHub Pages.
CHF-based reader in Zurich; no server to maintain.

- `SPEC.md` — scope, sourcing table, architecture, roadmap.
- `NETWORK.md` — what each endpoint actually returns and what has been ruled out.
- `CLAUDE.md` — working conventions and the last verified run status.
- `DATA-CATALOG.csv` — the reviewed sourcing decision for every series.

## How it works

A persistent, **append-only** SQLite store (`data/markets.db`, committed to
this repo) accumulates history. Each run:

1. **Ingest** — for every series, ask the database what the newest stored
   observation is, fetch only what is newer, and insert it. Nothing is ever
   updated or deleted; a revised GDP or CPI print is *appended* with a later
   `vintage_date` and the original stays.
2. **Quality** — staleness, gaps, outliers and curve consistency, written to
   `data_quality_flags`.
3. **Export** — rebuild `site/data/latest.json` from the database, over the
   full accumulated history.

The stored grain is **weekly**: one observation per completed week, the Friday
close or the last session before it. Everything derived is therefore weekly —
volatility annualises with sqrt(52), windows are named in weeks.

## Setup (one-time)

1. **Seed the database.** It is committed, so a fresh clone already has it and
   this is only needed when starting from nothing:

   ```bash
   pip install -r requirements.txt
   python3 bootstrap.py          # ~10 min; pulls ~89MB of BoE archives once
   ```

   Bootstrap is never run on a schedule. To add a single new series later,
   after adding its row to `fetch/universe.py`:

   ```bash
   python3 bootstrap.py --series curve.US.10Y
   ```

2. **Enable GitHub Pages**: repo Settings → Pages → Source: "GitHub Actions".

3. **First run**: Actions tab → "Weekly data refresh" → "Run workflow". After
   that it runs itself every Saturday at 06:00 UTC.

A `FRED_API_KEY` repo secret is optional and not required — the pipeline uses
FRED's keyless `fredgraph.csv` endpoint.

## Local development

```bash
python3 pipeline.py --mode sample   # synthetic data, no network, own database
python3 pipeline.py --mode live     # fetch what's new, then rebuild the JSON
python3 pipeline.py --export-only   # rebuild the JSON from what's stored

cd site && python3 -m http.server 8000
# open http://localhost:8000 — must be http, not file://, since the page
# fetches data/latest.json
```

Checks:

```bash
python3 -m unittest discover -s tests -t .   # includes the append-only guard
python3 tools/render_check.py                # macOS only; catches shifted table columns
```

## What is deliberately missing

The frontend shows "not yet wired" rather than a fake number, so what you see
is always honest about what is real. The gaps are recorded in `SPEC.md` and
`DATA-CATALOG-ruled-out.csv` — the China yield curve, most regions'
inflation expectations, and non-US valuation multiples. Most are permanent:
Switzerland and Norway issue no inflation-linked debt at all, so there is no
instrument to source, free or paid.
