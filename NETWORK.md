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
- **SNB `rendoblid` cube — discontinued.** Still responds, but its last
  observation is 2025-07-31 (published 2025-09-01). Deliberately left
  unsourced rather than showing year-old yields as current. Needs a successor
  cube id.
- **ChinaBond — JS-rendered.** `yield.chinabond.com.cn` returns an HTML shell;
  the documented `queryGjqxInfo` path serves no data to a plain HTTP client.
  Needs the underlying XHR endpoint identified.
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
