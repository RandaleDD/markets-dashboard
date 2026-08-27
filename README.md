# Markets Dashboard

Personal daily markets dashboard — equity indices, yield curves, central bank
rates, inflation, real yields, equity risk premia, GDP growth, currencies,
commodities, and equity valuation metrics across US/UK/Eurozone/Germany/
Switzerland/China/Japan. Static site, refreshed daily via GitHub Actions,
hosted free on GitHub Pages.

See `SPEC.md` for the full design and `NETWORK.md` for an important caveat:
the data fetchers were written but not live-tested (see below for why), so
treat the first real run as part of the setup, not a sign something's wrong.

## Setup (one-time)

1. **Create a GitHub repo** and push this folder to it:
   ```bash
   cd markets-dashboard
   git init
   git add .
   git commit -m "Initial scaffold"
   gh repo create markets-dashboard --private --source=. --push
   # or: create the repo on github.com, then git remote add origin <url> && git push -u origin main
   ```

2. **Enable GitHub Pages**: repo Settings → Pages → Source: "GitHub Actions".

3. **(Optional) Add a FRED API key**: not required — the pipeline uses FRED's
   keyless `fredgraph.csv` endpoint — but if you later want the richer JSON
   API, get a free key at https://fred.stlouisfed.org/docs/api/api_key.html
   and add it as a repo secret named `FRED_API_KEY`.

4. **First run**: Actions tab → "Daily data refresh" → "Run workflow" (manual
   trigger). Check the run log — the pipeline logs which sources succeeded
   (`ok`), failed, or are still stubbed. Expect some `failed` entries on the
   first run; see NETWORK.md for how to iterate on those.

5. Your dashboard will be live at `https://<your-username>.github.io/markets-dashboard/`
   (or wherever Pages reports — check the Actions run summary).

## Local development

```bash
pip install -r requirements.txt
python pipeline.py --mode sample   # synthetic data, no network needed
# or
python pipeline.py --mode live     # real fetches — needs normal internet access

cd site && python3 -m http.server 8000
# open http://localhost:8000 — must be served over http, not file://,
# since the page fetches data/latest.json
```

## Why some data is missing on first launch

Not every source has a confirmed, working fetcher yet — see `SPEC.md`'s
phased roadmap and `fetch/sources.py`'s TODOs. The frontend shows
"not yet wired" for anything that isn't live yet rather than a fake number,
so what you see is always honest about what's real.
