# Network constraint that shaped this build

The cloud sandbox this was originally built in only allows outbound requests
to package registries (pip, npm, etc.) — direct HTTP requests to Stooq, FRED,
BIS, and the various central bank statistics portals all returned 403 at the
proxy level. That meant the fetch code in `fetch/sources.py` was written
against each source's *documented* URL/CSV format, but could not be
live-tested from that environment.

**What this means practically:**

- `fetch_stooq` and `fetch_fred` are the most likely to work as-written — both
  target simple, well-known public CSV endpoints (Stooq's `/q/d/l/` download
  link, FRED's keyless `fredgraph.csv`). Still: run them for real before
  trusting them.
- `fetch_bis_policy_rate` is a best-effort guess at the BIS SDMX REST URL
  pattern — confirm the actual dataflow id/key structure against
  https://data.bis.org/topics/CBPOL before relying on it.
- `fetch_snb`, `fetch_bundesbank`, `fetch_chinabond`, `fetch_jsda`,
  `fetch_boe`, `fetch_ecb`, `fetch_periphery_spread`, `fetch_shiller_cape`,
  `fetch_damodaran_erp`, `fetch_etf_factsheet` are all deliberate stubs —
  each docstring names the confirmed institution/portal (see also
  `sourcing-map.md`), but none has a verified query format yet.

**How to actually test:**

1. Run `python pipeline.py --mode live` somewhere with normal internet
   access (your own machine, or let the GitHub Actions workflow do it).
2. Check `site/data/latest.json`'s `source_status` block — every series is
   marked `ok`, `failed`, or `stubbed`. Anything `failed` means the fetcher
   ran but didn't get usable data back; fix the URL/params in
   `fetch/sources.py` for that source.
3. Iterate source by source. This is expected to take real back-and-forth —
   treat the "first real run" as part of the build, not a bug if things
   don't work on the first try.
