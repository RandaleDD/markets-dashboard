# Source notes — what each endpoint actually returns

This file used to explain why the fetchers had never been run. That premise is
spent: the pipeline was run for real on 2026-08-28 and every endpoint below was
confirmed against a live response. What follows is the record of what was
found, because several of these are non-obvious enough to re-derive painfully.

## The User-Agent trap

There is no single header set that works across these sources, and getting it
wrong fails *silently*.

- **FRED must not get a browser User-Agent.** It sits behind Akamai, which
  tarpits requests whose UA claims to be a browser while the TLS fingerprint is
  Python's: the request hangs until it read-times-out. A tool-shaped UA
  (`python-requests/*`, `curl/*`) returns in ~0.2s. The original code sent
  `Mozilla/5.0 (compatible; markets-dashboard/0.1)` and every FRED series
  failed. An "honest" project UA fails too — it is an allowlist of known tool
  UAs, not a politeness check.
- **BoE and MOF are the exact opposite** — they serve an error page unless the
  UA looks like a browser.

`_get()` therefore takes per-source headers and defaults to requests' own UA.

## Working

| Source | Endpoint | Notes |
|---|---|---|
| Yahoo (yfinance) | `yf.Ticker(t).history(period="max")` | Prices/FX/commodities. The library does Yahoo's cookie+crumb handshake; a bare request to query1/query2 returns 429. **The latest bar often has a NaN close while a session is open** (^GDAXI, ^SSMI, ^HSI, ^N225) — must `dropna`, or a raw `NaN` lands in the JSON and breaks the frontend. |
| FRED | `fredgraph.csv?id=<ID>` | Keyless. `observation_date,<ID>`, missing values as `.`. |
| BIS policy rates | `stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.<area>?format=csv` | **Needs `startPeriod`** — the full history is 57MB for JP and blows the timeout. |
| BIS CPI | `.../WS_LONG_CPI/1.0/M.<area>?format=csv` | Covers all seven regions. Mixes two unit codes in one response: **`771` = YoY %, `628` = index level** — filtering on `unit_measure` is mandatory. |
| Bundesbank | `api.statistiken.bundesbank.de/rest/download/BBSIS/<key>?format=csv&lang=en` | ~9-line metadata preamble before `date,value,flag`; `.` for missing. Tenor is the `R__XX` segment: `R02XX`/`R05XX`/`R10XX`/`R30XX`. |
| BoE | `boeapps/iadb/fromshowcolumns.asp?csv.x=yes&...&UsingCodes=Y` | Browser UA required. `IUDSNZC`/`IUDMNZC`/`IUDLNZC` = 5y/10y/**20y** nominal zero-coupon. There is no 2y or 30y in this set. |
| MOF Japan | `mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv` | Whole 1Y–40Y curve in one file. **Shift-JIS (cp932), not UTF-8**; line 1 is a title row. Current month only (`jgbcm_all.csv` is 404). |
| ECB curve | `data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_<t>?format=csvdata` | `G_N_C` is the ALL-bonds euro area curve; `G_N_A` is AAA-only and tracks the Bund so closely it is a duplicate of Germany. Full history is ~3MB per tenor. |
| ECB per-country | `.../IRS/M.<cc>.L.L40.CI.0000.EUR.N.Z` | Monthly long-term government yield for convergence purposes. Used for euro-area spreads — **both legs must come from this same series**, since ECB's German figure (3.07) differs from Bundesbank's daily curve (3.22). |
| BoE GLC | `.../statistics/yield-curves/latest-yield-curve-data.zip` | Browser UA required. Four xlsx workbooks: nominal, **real**, **inflation**, OIS. Sheet `4. spot curve` holds the long end and `3. spot, short end` the front — the real and inflation books start their long-end sheet past 2y, so **both sheets must be read** to get a 2y. Row index 3 carries maturities in years. |
| Norges Bank | `data.norges-bank.no/api/data/<flow>/<key>?format=csv` | **Semicolon-delimited.** `IR/B.KPRA.SD` is the policy rate; `GOVT_ZEROCOUPON/B.<tenor>` the curve. The published curve **stops at 10 years** — there is no 30y. |
| Shiller CAPE | `img1.wsimg.com/blobby/.../ie_data.xls` | Genuine legacy .xls, needs **xlrd**. The header spans two rows and the upper one contains a second cell reading "CAPE" belonging to the Excess CAPE Yield block — match the lower row, where column 0 is exactly "Date". Dates are fractional (1871.01 = Jan). File currently ends 2024-09. |
| Damodaran ERP | `pages.stern.nyu.edu/~adamodar/pc/datasets/histimpl.xls` | Header on row 6. Use **"Implied ERP (FCFE)"** — "Implied Premium (DDM)" sits to its left and is a different, materially lower measure (1.69% vs 4.23% for 2025). Values are fractions, not percent. |

## Dead or blocked

- **Stooq — unusable.** Every path (`stooq.com`, `stooq.pl`, `^spx`, `spx`)
  returns a JavaScript proof-of-work anti-bot page instead of CSV. Not
  solvable from a headless job. Replaced by Yahoo/yfinance.
- **FRED's OECD-sourced national series are frozen.** They still return
  HTTP 200, which is exactly why the staleness check exists. `*CPIALLMINMEI`
  stops 2025-03/04 (JP: 2021-06), `CPALTT01*` and even `USACPALTT01CTGYM` stop
  2024-12, and `NAEXKP01*Q657S` GDP growth is discontinued. CPI moved to BIS;
  GDP moved to maintained real-GDP level series with growth derived in the
  pipeline.
- **SNB Confederation bond yields — discontinued.** Both the daily
  `rendoblid` and monthly `rendoblim` cubes still return 200 while stopping at
  2025-07, sharing a final publishing date of 2025-09-01. Money-market cubes on
  the same portal (`zimoma`) are current to 2026-08, so the series was retired
  rather than the portal breaking, and no successor cube id responds. Needs a
  different institution (SIX, or the SNB statistical bulletin).
- **ChinaBond — JS-rendered.** `queryGjqxInfo` returns a 956-byte HTML shell
  regardless of parameters, and the `yield_main` XHR paths
  (`getYieldDataForWeb`, `queryTypeValues`) are 404. Would need a headless
  browser or a different institution (CFETS).
- **Yahoo has no CSI 300 index history** — `000300.SS`/`399300.SZ` accept only
  `period=1d/5d`. The CNY-priced mainland tracker ETF `510300.SS` stands in.

## Freshness, not just success

A source returning 200 and parsing cleanly can still be years stale — that is
how the SNB cube and the whole FRED/OECD family present. `pipeline.py` marks
each series `ok` / `stale` / `partial` / `failed` / `stubbed` against a
per-cadence age limit (`MAX_AGE_DAYS`), and carries `as_of` into the JSON.
Read `source_status` after every run; `stale` is not a pass.

## Testing

`python pipeline.py --mode live`, then check `source_status`. Serve the site
over http (`cd site && python3 -m http.server 8000`) — `file://` will not work,
the JSON fetch needs it.


## Added 2026-08-28

- **Euro-area market-implied inflation has no free source.** The practitioner
  standard is the EUR HICPx zero-coupon inflation swap, which is not published
  free. The ECB `FM` dataflow contains no ILS series — its `ILS` codes are
  Israeli shekel — and the Bundesbank REST API exposes no index-linked term
  structure. Shown as unavailable with the reason, rather than substituting a
  survey number into a market-implied column.
- **CFETS (chinamoney.com.cn) is closed too.** Its edge gateway answers
  `{"Error":"Path not found."}` to every path, including plain HTML pages —
  so the last remaining lead for a China curve is dead. China stays blank.
- **UK implied inflation is RPI-based**, because UK linkers reference RPI. It
  runs roughly 0.8-1.0pp above the equivalent CPI rate, so it must never be
  compared directly with US CPI breakevens. The basis is displayed next to
  every figure.

## History depth (added for percentile context, 2026-08-28)

Percentile/z-score context must be computed from each source's **full fetched
history**, never from `compact_history`'s stored archive — that archive only
began accumulating at project launch, so a 10y window cannot resolve from it
and its "full" would silently mean "since we started collecting". Measured on
US 10y: 98th percentile over a real 10 years, but 42nd over the actual series
back to 1962. The archive-derived version could not answer the 10y question
at all.

Several fetchers had `startPeriod` bounds added earlier purely to avoid
timeouts, which capped them below 10 years and made the window unresolvable.
Widened, with measured cost:

| Source | Was | Now | Cost |
|---|---|---|---|
| BIS CBPOL | 3y | 25y | JP 12.7MB / 0.7s (full history was 57MB) |
| BIS CPI | 5y | 25y | 0.02MB |
| ECB curve | 3y | 15y | 2.4MB / 2.1s |
| Norges Bank | 3y | 25y | 1.5MB / 0.8s. Their API only reaches 2015 regardless |
| MOF Japan | current month (~19 rows) | 1974→now | `historical/jgbcme_all.csv`, 1.2MB. **Must be stitched with the current-month file**, which is fresher — the archive ends at the prior month end |

`TIMEOUT` raised 30s → 60s to match the larger payloads.

**Not fixed: the UK curve has no deep history.** The BoE GLC archive exists
(`glcnominalddata.zip`) but is **39MB for nominal alone**, and real and
inflation would need their own, so roughly 120MB per daily run purely to
annotate a percentile. Deliberately skipped — UK curve, real yield and implied
inflation figures carry no context annotation, and the UI hides it rather than
showing "N/A". Revisit only if the archive gets a lighter endpoint.

Also no context: the China curve (unsourced entirely) and non-US ERP
(Damodaran is annual, so a 5y window is 5 observations — below the 24-point
minimum, and it correctly falls back to the full-history window).

## ICE BofA credit spreads (added 2026-08-28)

`BAMLC0A0CM` (US IG OAS), `BAMLH0A0HYM2` (US HY OAS) and `DRTSCILM` (SLOOS
net tightening) all resolve on keyless `fredgraph.csv`.

Two findings worth recording:

- **The OAS series are capped at a rolling ~3 years.** Every ICE BofA spread
  series starts on exactly the same date, three years back, and passing an
  explicit `cosd=1997-01-01` changes nothing. This is an ICE licensing limit
  on FRED's free tier, not a fetch bug. Consequence: percentile context on
  spreads can only resolve the `full` window; 5y and 10y correctly stay hidden.
  `DRTSCILM` is unaffected and returns 1990 onward.
- **Non-US OAS does exist**, contrary to the V2 plan's assumption of US-only.
  `BAMLHE00EHYIOAS` (Euro high yield) and `BAMLEMCBPIOAS` (EM corporate) both
  resolve. No free euro *investment-grade* OAS was found, which is why the
  cost-of-capital stack's credit leg stays US-only — mixing an IG spread for
  one region with an HY spread for another would make the stacks silently
  non-comparable.

## Deploy integrity: asset cache busting (2026-08-28)

GitHub Pages serves both `index.html` and the assets under
`cache-control: max-age=600`, and the assets were referenced with no version
string. A browser could therefore hold a cached `app.js` while picking up
fresh HTML — which is exactly what happened when the Cross-Asset & Regime tab
shipped: the new markup carried the tab button and its empty `<section>`,
the cached JS had no renderer for it, and the panel rendered blank with
nothing wrong in the code or the data.

`pipeline.py:stamp_asset_versions()` now rewrites the asset URLs with a short
content hash on every run. The URL changes only when the file does, so this
adds no churn on runs where the assets are untouched.

**Debugging note for next time:** this machine has no Node, and Homebrew's
node install fails on a missing `simdjson` bottle. `osascript -l JavaScript`
runs JavaScriptCore and will execute `app.js` against a small DOM shim, which
is how the renderer was cleared of blame here — it produced 16KB of correct
HTML while the live page showed nothing.
