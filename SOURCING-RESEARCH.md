# Macro data sourcing research — 2026-09-13

Scope: macroeconomic series only — inflation, GDP, yield curves, policy rates,
credit spreads, inflation expectations. Equities, valuation, FX and cross-asset
were explicitly out of scope and are untouched. **No layout or output-format
change is proposed anywhere in this document.**

Two findings overturn entries currently recorded in SPEC.md's dead-ends list.
Both were verified by direct fetch, not inferred.

## Verified from the Mac on 2026-09-13 — read this first

Everything below was re-tested with `requests`, exactly as `fetch/sources.py`
issues it, and then implemented. **Five findings in this document turned out to
be wrong or incomplete.** The body is left unedited as the record of what the
research pass concluded; this block is what was actually true.

| Item | Verdict |
|---|---|
| **0a. Eurostat `prc_hicp_manr`** | **Retired — and so was the proposed fallback.** Both it and ECB `ICP` sit frozen at 2025-12 returning HTTP 200. The ECB payload's own `OBS_COM` says why: both were discontinued **2026-02-04** for the ECOICOP ver.2 changeover. Successors: Eurostat **`prc_hicp_minr`** (`coicop18=TOTAL`, not `coicop=CP00`; index unit `I25` = 2025=100) and the ECB's new **`HICP`** dataflow (`DATA_PROVIDER=4D0`, not `4`). Identical numbers; Eurostat taken, since `fetch_eurostat` already exists. **Implemented.** |
| **0b. World Bank GEM** | **Confirmed, trap and all.** With the range: 142 quarters, 1991Q1 → 2026Q2 = 36,382,853.72, `lastupdated` 2026-09-08. Without it: annual rows, 2026 = 72,551,656 against 2025's 140,133,708 — a half-year masquerading as a year. The fetcher always sends the range and refuses any non-quarterly period. **Implemented.** |
| **0c. SNB `rendeiduebd`** | **Confirmed**, including the overlap that proves succession — continuous daily data through 2025-07-15 → 2025-10-15, the window where `rendoblid` died. 12 tenors, 1988-01-04 onward, last obs 2026-08-31 matching the quoted values exactly. RSS `R10` = 0.581 on 2026-09-11. **One correction: a query with no `fromDate` returns only the LAST MONTH**, not full history. **Implemented.** |
| **0d. ChinaBond** | **Reachable — not a reject.** Plain cold GET, byte-identical with and without a browser UA. **Two corrections: the range cap is 365 days, not 3 months** (a full year returns 249 rows; 366 days returns headers only), and **history starts 2006-03-01, not 2010-01-04.** Both over-range and empty-range fail silently with HTTP 200 and a ~6.4KB headers-only page. **Implemented**, 5y/10y/30y only. |
| **0e. BFS/FSO Swiss CPI cube** | **Clean negative.** Of the 650 database ids the PxWeb v1 root lists, **none begins `px-x-05`** — domain 05 (Prices) is not served by that host at all. The cube was not findable because it is not there. Took SNB `plkopr` per the timebox. |

**Three further corrections found while implementing, each of which would have
shipped a wrong number:**

1. **SSB table 14702 is not Norway's headline CPI.** It is CPI by *delivery
   sector*, and its "consumer goods" aggregate diverges materially from the
   headline — 7.7 against 6.5 in 2023M03, −0.3 against 1.4 in 2020M06. The
   headline index is **table 14710** (one series, base 2025=100, back to
   1920M03 — deeper than the BIS series it replaces), whose derived annual rate
   reproduces the closed table 03013 exactly. Also: the `v2-beta` host returns
   **503**; the v1 host works and is POST-only for data.
2. **SNB `plkopr`'s `VVP` is already in percent** and must NOT be scaled by 100.
   Its 2026-07 value of 0.354234 is bit-identical to what the BIS series held
   for the same month.
3. **Japan's JSDA is closed as *not comparable*, not merely expensive.** The
   `ER` file is an average compound yield per rating across all maturities and
   the sibling `ES` file is per-bond, so a government leg computed the same way
   does not exist — it would have to be constructed by hand, a different
   computation from the corporate side. Its URLs also encode one business day
   each (~6,000 requests for history), and the host returned connect timeouts
   when polled. The documented column trap is real and confirmed: the field
   after the yield is the **standard deviation**.

Also confirmed as stated: FRED `CPIAUCNS`/`CPIAUCSL` (both at 2026-08 where BIS
had 2026-07); ONS on `www` with a browser UA, and `abmi/pn2` → 2026 Q2 against
`abmi/qna` → 2026 Q1; Eurostat `namq_10_gdp` for CH/NO at 2026-Q2; both
Bundesbank credit legs **through the existing `fetch_bundesbank` unchanged**
(4.38 − 3.45 = 93bp); ECB SPF 1999-Q1 → 2026-Q3, with the moving-tenor trap
mechanically verifiable (in the Q3 round the LT series is bit-identical to the
calendar-2031 series); and OECD `CHN.M.IRLT` at 2026-07 = 1.71.

One documented trap that is worse than described: **FRED silently ignores the
`_PC1` transformation suffix** and returns the level under the base id, so
there is no published US CPI YoY series to fetch. The rate is derived instead.

---

## How this was verified, and what that means for you

Every endpoint below was hit through a fetch tool that **respects robots.txt**,
from a sandbox where raw `curl` is blocked by an egress proxy. Your pipeline's
`requests` client honours neither constraint, so:

- Where this document says **VERIFIED**, data was actually observed, and the
  last observation date quoted is real.
- Where it says **UNVERIFIED (robots)**, the host refused the research tool but
  will almost certainly answer `requests` normally. `api.db.nomics.world`,
  `data-api.ecb.europa.eu`, `sdmx.oecd.org/.../data/`, `api.imf.org` all fall
  here. Treat these as "test from the Mac", not as "unavailable".
- Where it says **UNVERIFIED (other)**, the reason is stated.

Re-test anything marked UNVERIFIED before building on it.

---

## 1. Switzerland's curve — the SNB never retired it

**This is the highest-value correction in this document.** SPEC.md records the
Confederation curve as discontinued in July 2025 with no successor, which is why
the dashboard scrapes TradingEconomics — its only unofficial source, 2y and 10y
only, no history before 2026-08-29.

The curve was not discontinued. It was **moved to a new cube in the same
`ziredev` topic on the same API.** The seven cube ids guessed on 2026-08-29
missed it.

**VERIFIED — SNB cube `rendeiduebd`:**

```
https://data.snb.ch/api/cube/rendeiduebd/data/csv/en?fromDate=2026-01-01&dimSel=D0(CHF)
```

- `D0=CHF` isolates "Swiss Confederation bond issues"; `D1` is maturity.
- **12 tenors:** 1J–10J, 20J, 30J. Covers 2y, 5y, 10y and 30y.
- **Daily**, business days. 21 distinct dates observed in Aug 2026.
- **Last observation 2026-08-31**: 2y 0.078, 5y 0.263, 10y 0.469, 30y 0.590.
- **History back to 1988-01-01** — 38 years, versus the current three weeks.
- Published in a **monthly batch** (`PublishingDate` 2026-09-01 14:30); a query
  into the current month returns headers only.

The proof it is the successor: it has continuous daily data through August and
September 2025, exactly the window where `rendoblid` died. The two overlap and
then one takes over.

**VERIFIED — SNB RSS, to cover the intra-month gap:**

```
https://www.snb.ch/public/rss/en/interestRates
```

RSS-CB 1.2, the cbwiki central-bank standard — structured `<cb:rateName>R10`,
`<cb:value>`, `<cb:period>`, not a styled table. `R10` is the 10y Confederation
spot rate, the same NSS series as the cube. **Last observation 2026-09-11
(0.581).** Window is five business days, so a weekly run always catches it, and
a missed week loses nothing permanently because the cube backfills the month.

**Recommendation:** `rendeiduebd` for history and the monthly refresh, RSS `R10`
for the live weekly 10y between batches. **Retire the TradingEconomics scrape
entirely** — it is no longer needed for any tenor. This removes the project's
only unofficial source and the only one that could silently return a wrong
number after a page restyle.

Also worth recording: `rendoeid` is live but is 23 individual bond ISINs with
yield-to-maturity — it would mean fitting your own curve, and is now moot.
The EFV/AFF publishes budget and debt series only, no yields. Both closed.

## 2. China's curve — reachable, from nothing to a full official curve

SPEC.md records ChinaBond as JS-rendered and CFETS as refusing all access. That
is true of the paths tried. **The earlier attempts hit the JavaScript front-end
application path.** The server-rendered endpoints live under `cbweb-pbc-web/pbc/`.

**VERIFIED — ChinaBond `historyQuery`:**

```
https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery
  ?startDate=2026-06-01&endDate=2026-09-11&gjqx=0&qxId=ycqx&locale=en_US
```

- **Server-rendered HTML table.** Fetched cold — no cookies, no session, no
  captcha, no JS, no key. `locale=en_US` gives English headers and curve names.
- Returns three curves; the one you want is *ChinaBond Government Bond Yield
  Curve* (中债国债收益率曲线).
- **8 tenors:** 3M, 6M, 1Y, 3Y, 5Y, 7Y, 10Y, 30Y. Covers 5y/10y/30y. **No 2y** —
  3Y is the nearest point, and that cell should stay blank rather than be
  interpolated.
- **Last observation 2026-09-11**: 5Y 1.4226, 10Y 1.6899, 30Y 2.1460.
- **History back to 2010-01-04**, verified.
- **Range cap:** windows ≤3 months return reliably (~150 rows). A full-year
  range returns headers only. Chunk the backfill.
- Cheap weekly poll: `.../cbweb-pbc-web/pbc/more?locale=en_US` — same 8 tenors,
  current day, also server-rendered.

**Honest caveat: this is still a scrape**, and it should be labelled as one. It
is materially sturdier than the TradingEconomics page — official CCDC/PBoC-
affiliated, explicit labelled column headers, named curves, a path stable enough
that AkShare has depended on it for years — but a restyle would still break it.
Parse by matching the header row and the curve-name string, never by column
position, and assert dates parse and values sit in a sane range.

**Cross-check available:** OECD SDMX carries a monthly China 10y independently:
`sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/CHN.M.IRLT......`
— **VERIFIED 2026-07 = 1.71**, about six weeks behind. Useless as a primary
feed, genuinely useful as a plausibility check on the scrape.

## 3. China quarterly GDP — solved, and it needs no new dependency

China is annual-only today, and that was correct: FRED genuinely has no
quarterly China real GDP (`NGDPRSAXDCCNQ`, `CHNGDPRQPSMEI`, `NAEXKP01CNQ657S`
all 404), and the OECD series that used to carry it (`CHNGDPNQDSMEI`) died in
2023Q3. NBS itself publishes at T+16 days but returns **HTTP 403** to
non-browser clients from outside mainland China — which is exactly a GitHub
Actions runner's situation.

**VERIFIED — World Bank Global Economic Monitor, `source=15`:**

```
https://api.worldbank.org/v2/country/CHN/indicator/NYGDPMKTPSAKN
  ?source=15&format=json&frequency=Q&date=1991Q1:2026Q4
```

- **China real GDP, constant 2010 LCU, seasonally adjusted — a LEVEL**, which
  preserves your "store levels, derive growth ourselves" invariant.
- **2026Q2 present**, `lastupdated: 2026-09-08`. History to **1991Q1**.
- Sanity-checked: implied YoY 2025Q2 +5.14%, 2025Q4 +4.49%, 2026Q2 +4.34% —
  tracks China's published real growth.
- **CC BY 4.0, no key, same host and auth model you already use.**
- Same call covers US/UK/DE/JP quarterly GDP, and monthly CPI y/y
  (`CPTOTSAXNZGY`) for all seven countries, current to 2026M07.
- **No euro-area aggregate** — GEM is country-level only. CH and NO lag one
  quarter (2026Q1 when others have Q2).

**Live correctness trap, flagged hard:** `frequency=Q` **is silently ignored
without a `date` range.** Omit the range and the API returns *annual* rows, with
the current year as a partial sum that looks exactly like a real annual figure.
Always pass `date=YYYYQn:YYYYQn`.

Worst-case staleness for China drops from ~15 months to about T+6–8 weeks. GEM
carries no interest rates, bond yields or spreads at all — 36 indicators, all
real-economy.

## 4. Inflation — where currency is genuinely worth buying

BIS `WS_LONG_CPI` releases monthly in the last week, and each print is dated to
the first of the month it describes, so the newest observation sits between 27
and 57 days old (mean ≈ 42). Because you poll weekly, the gain from a faster
source is in *average* staleness, not just arrival lag.

| Region | Proposed source | Verified? | Lag | Gain | Key |
|---|---|---|---|---|---|
| US | FRED `CPIAUCNS` + `CPIAUCSL` | VERIFIED, Aug 2026 | T+11 | −16d | no |
| UK | ONS `D7G7` (YoY) + `D7BT` (index) | VERIFIED, Jul 2026 | T+16 | −11d | no |
| Norway | SSB PxWebApi v2 **table 14702** | VERIFIED, 2026M08 | T+10 | −17d | no |
| Switzerland | SNB cube `plkopr` | VERIFIED, Jul 2026 | T+21 | −6d | no |
| Eurozone | Eurostat `prc_hicp_manr` — **see warning** | disputed | T+1 flash / T+17 | −26d | no |
| Germany | Eurostat `geo=DE` — **see warning** | disputed | T+1 / T+17 | −26d | no |
| Japan | e-Stat | needs `appId` | T+18 | −9d | **yes** |
| China | stay on BIS | 403 from CI | — | — | — |

**Two corrections to leads that turned out stale:**

- **`api.ons.gov.uk` returns 404** — that host is dead. The working path is
  `https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data`.
  Quirks: `months` runs oldest→newest, dates are `"2026 JUL"` not ISO, values
  are **strings**, and `quarters`/`years` arrays must be ignored.
- **SSB table 03013 is CLOSED** (1979M01–2025M12). Norway rebased; the live
  table is **14702**, base 2025=100, history only from 2015M01 — so splice BIS
  or the closed table for the long tail. Default selection returns only the
  latest period, so `valueCodes[Tid]` must be passed explicitly.

**Warning on Eurostat HICP — resolve before building.** Two researchers hit this
independently and disagree. One saw `prc_hicp_manr` structurally valid but
frozen at **2025-12** across six different query strings. The other found
Eurostat's own API reporting `OBS_PERIOD_OVERALL_LATEST: 2025-12`, `updated:
2026-02-06`, and the databrowser titling the dataset **"(1997-2025)"** — which
reads as *retired at source*, not a cache artefact. Meanwhile the euro-area
flash press releases are demonstrably current (Aug 2026 published 1 Sep 2026,
Germany 2.9%), so the data exists; the question is which dataflow it lands in.

Test from the Mac before committing. The likely answer is the **ECB Data
Portal**, which carries the same HICP as flat SDMX-CSV and is far easier to
parse than JSON-stat — UNVERIFIED (robots) but almost certainly fine for
`requests`:

```
https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N.000000.4.ANR?format=csvdata&lastNObservations=24
```

**A real basis change hides in the Germany row.** BIS gives Germany the national
VPI; Eurostat `geo=DE` gives German HICP. They printed identically (+2.9%) in
Aug 2026 and typically differ by ≤0.3pp, but it is a methodology switch and
should be recorded in the catalog notes if taken.

**Japan is a judgement call I'd decline.** Only −9 days, and it is the one
switch that costs a GitHub Actions secret. Leave Japan on BIS unless you want it
current for its own sake.

**Switzerland has a faster tier you may want later.** The BFS/FSO publishes at
**T+3** (Aug 2026 out 3 Sep) versus SNB's T+21. The PxWeb root
`https://www.pxweb.bfs.admin.ch/api/v1/en/` works and lists 600+ database ids,
but the LIK cube id could not be resolved from here, and PxWeb v1 data retrieval
is POST-only — trivial for `requests`, impossible for the research tool. Worth
twenty minutes from the Mac; it would buy another 18 days.

**On comparability:** you cannot get all eight on one methodology — HICP does
not exist for the US, China or Japan. Store each region's headline national
print (the number markets actually trade) and carry a `basis` column: US CPI-U,
UK CPI, EA/DE HICP, CH LIK, CN CPI, JP CPI, NO KPI. Do **not** switch the UK to
CPIH — it adds owner-occupier housing costs and stops being comparable.

## 5. GDP — small gains, one worthwhile removal

Most of this is already optimal and should be left alone. **Eurozone and Germany
at Eurostat `namq_10_gdp` T+30 cannot be beaten**, and the flash genuinely
populates that table — the 30 July 2026 flash release names `namq_10_gdp` as its
source dataset. **US at FRED `GDPC1` T+29 already captures the BEA advance**;
nothing free is faster. BEA's own API rejects `UserID=Guest`, so FRED is the
keyless path.

Three changes worth making:

**Switzerland and Norway: FRED → Eurostat.** Both are VERIFIED at 2026-Q2 via
`namq_10_gdp` with `geo=CH` / `geo=NO`, `unit=CLV_I15`, `s_adj=SCA`. The lag
gain is ~zero; the reason is different. `CLVMNACSCAB1GQCH` **self-reports
"Source: Eurostat", units "Millions of Chained 2010 Euros"** — your Swiss GDP was
never Swiss-sourced. It is Eurostat data passed through FRED with a **euro FX
conversion layer** bolted on. That is the exact series that produced the
2026-09-08 rebasing incident. Going direct removes both the intermediary and a
currency conversion, and puts CH/NO on the identical definition and code path as
EA/DE.

**UK: add `abmi/pn2` alongside the monthly index.** Chained volume £m SA, 1955-Q1
→ 2026-Q2, T+43 — the same grain as the other seven.
**Do not use `abmi/qna`**: verified to return 2026-**Q1** for the identical
series id, a full quarter staler. The dataset suffix, not the series id,
controls the vintage.

Keep the monthly GDP index, but demote it. It is more current in information
terms (July data on 11 Sept) and a genuinely useful nowcast — but it is
GVA-based ("Gross Value Added - Monthly (Index 1dp): CVM SA"), and mixing it
into a YoY comparison against seven quarterly chain-linked series is exactly the
definitional seam that produces a wrong headline.

**Japan: optional.** ESRI direct
(`esri.cao.go.jp/jp/sna/data/data_list/sokuhou/files/2026/qe262/tables/gaku-jk2621.csv`,
VERIFIED, chained 2020 yen, 1994-Q1→2026-Q2) saves ~1 day and removes an
intermediary, but the URL encodes the release (`qe262` = 2026 Q2) and must be
constructed each quarter. Marginal. If you stay on FRED, confirm the series is
ESRI-sourced and not `NAEXKP01JPQ*`.

**The rebasing trap, re-checked per source.** Every recommended GDP source
serves full history in one request of a few hundred rows — Eurostat ~194,
FRED ~318, ONS ~286, ESRI ~130, SSB ~194. **There is no cost argument for
incremental windows anywhere in this set**, so `FULL_REFETCH_CADENCES` should
cover all of them. One nuance worth encoding: a pure rebase (rescaling by a
constant) leaves growth rates unchanged, so a "did the base year change?" guard
is insufficient. Your Swiss error was a genuine **re-chain-linking**, which
moves growth. Only full re-fetch is safe.

**FRED's frozen-OECD trap independently reproduced:** `NAEXKP01CHQ657S` returns
HTTP 200 with data, units "Growth rate previous period", last updated
2026-06-15, last observation **2026-Q1** — a full quarter stale while Eurostat
and SECO both have Q2. Your warning is correct.

## 6. Credit spreads — the honest answer is 2 of 7, not 7 of 7

SPEC.md calls this the single highest-value gap: seven of eight cost-of-capital
stacks lack the IG credit leg, and one source would fix them all.

**That source does not exist free.** The reason is structural, not an oversight:
euro, sterling and yen IG benchmarks *are* the ICE BofA, iBoxx and Bloomberg
indices. ICE licenses its **US** series to FRED for free redistribution and does
not license the others. No official publisher can republish what it does not own
— the ECB itself licenses rather than publishes them.

Confirmed by enumeration, not by search: FRED release `rid=209` was read in full
— **192 series**. Euro coverage is exactly four series, all high yield (`HE00`).
**No euro IG, no GBP series of any kind, no JPY, no developed-Asia IG.** Two
near-misses are traps: `BAMLEMEBCRPIEOAS` is EUR-denominated but **EM issuers**,
`BAMLEMIBHGCRPIOAS` is IG-rated but **EM issuers**. Neither is a Eurozone proxy.
BIS has no corporate credit data at all (full dataflow list enumerated). The ECB
has no corporate bond yield dataset (`FM` is government/money-market, `YC` is the
sovereign curve, `STP` is short-term paper, `MIR` is bank lending). IMF FSI is
bank soundness ratios. The ESRB dashboard's spread panels are iBoxx/ICE-derived.

**Two regions are genuinely fixable, on a different basis:**

**Germany — Bundesbank, VERIFIED, daily, 47 years of history.** Keyless SDMX:
```
https://api.statistiken.bundesbank.de/rest/data/BBSIS/<key>?format=sdmx&lastNObservations=N
```
- Corporate: `D.I.UMR.RD.EUR.X2000.B.A.A.R.A.A._Z._Z.A` → **2026-09-10 = 4.38%**
- Public: `D.I.UMR.RD.EUR.S13.B.A.A.R.A.A._Z._Z.A` → **2026-09-10 = 3.45%**
- Spread 93bp. History from **1979-01-02**, far deeper than ICE's 3-year window.
- Note the daily corporate series is **not listed on the Bundesbank web page**;
  the API serves it anyway. Also: monthly Aug = 4.06 vs daily 10 Sep = 4.38 is a
  large one-month move that was not reconciled — sanity-check on first run.

**Japan — JSDA rating matrix, VERIFIED, daily, back to 2002.**
`https://market.jsda.or.jp/en/statistics/bonds/prices/otc/files/2026/ER260911.csv`,
government leg in the sibling `ES260911.csv`.
**Parsing trap worth the whole paragraph:** the column after the yield looks
like a spread and is **not** — JSDA's column order is *(rating, compound yield,
**standard deviation**, number of issues, number of reporting members)*. JSDA
publishes no spread; you construct it.

**Both are spread-to-government, not OAS**, not option-adjusted, not
duration-matched. Under your own discipline — every figure states its definition,
and a number not comparable to the ones beside it is a reporting error — these
cannot go in the same column as `BAMLC0A0CM`. Give them their own labelled
column ("corporate spread to govt, non-OAS"), or additionally compute the US on
the same non-OAS basis so one column is internally consistent.

**Rejected as proxies, explicitly:** ECB MIR cost of borrowing and BoE effective
lending rates are **bank loan rates, not bond spreads** — apples-to-oranges
twice over (a level not a spread; a loan to largely unrated SMEs, not a market
OAS on rated public debt). An IG ETF yield fails the same way and adds cash drag
and licensing questions. ECB STEP *is* a real credit spread but at overnight-to-
91-day maturities, against your 10y risk-free leg, and was last updated
2026-05-12. If you want bank lending rates, they belong in their own panel.

**Verdict: implement Germany and Japan; label the five remaining regions
unavailable and stop looking.** SNB's `rendoblid` rating buckets would have been
perfect for Switzerland and died with the same 2025 cut.

## 7. Inflation expectations — one good addition, clearly labelled

Eurozone, Japan and China are the live questions; Switzerland and Norway remain
permanent structural gaps (neither government issues inflation-linked debt), and
that is confirmed rather than assumed.

**Implement: ECB Survey of Professional Forecasters.** Dataflow `SPF`, quarterly,
**history from 1999Q1**, lag ~3–4 weeks. Latest round Q3 2026, published 24 July
2026: 2026 2.7%, 2027 2.2%, 2028 2.0%, longer-term 2.0%. Real series keys:
`SPF.Q.U2.HICP.POINT.LT.Q.AVG` (longer-term mean), `SPF.Q.U2.HICP.POINT.2026.Q.AVG`
(calendar year). A no-SDMX bulk path exists:
`ecb.europa.eu/stats/prices/indic/forecast/shared/files/SPF_individual_forecasts.zip`.

**One trap that matters for a dashboard labelling tenor on every figure:** the
"longer-term" horizon is **5 calendar years ahead in Q3/Q4 rounds but 4 years
ahead in Q1/Q2**. The tenor moves between rounds and must be handled explicitly,
not averaged over.

**Also available:** the EC Business and Consumer Survey carries a *quantitative*
consumer inflation expectation, monthly, EU and euro-area — but its download URL
embeds a vintage stamp (`nace2_ecfin_2607` = 2026-07) that changes each release
and must be resolved at runtime. ECB CES is monthly but only ~6 years of history
and runs persistently well above both breakevens and SPF.

**The cross-cutting warning.** Adding SPF moves you from "US + UK market-implied,
everyone else blank" to "US + UK market-implied, EZ **survey-based**, rest
blank". That is an honest improvement, but a survey mean and a market breakeven
are different quantities with different biases. They must be separated visually
or by column, never stacked in one column with a footnote.

**Japan:** a JGB breakeven **cannot** be built from what you already download —
the JSDA `ES` file contains only T-bills and conventional JGBs, no linkers, and
MOF publishes the JGBi Ref Index but not yields. The one unexplored lead is the
Japanese-language JSDA full reference-price file. If a JGBi breakeven is ever
built, flag that JGBi carry a **deflation floor** which biases breakevens upward
at low inflation, and that JGBi liquidity is thin.

**China: do not implement.** The only measure is the PBoC Urban Depositor Survey,
which is a **diffusion index of respondents expecting higher prices, not a
percentage** — PDF-only, opaque hashed URLs. It cannot be labelled as an
inflation expectation in percent and would violate your comparability rule.

**Confirmed still impossible free:** euro-area 5y5y ILS (the ECB writes about it
and does not publish it), and any Chinese, Swiss or Norwegian breakeven.

## 8. Aggregators — do not consolidate. The evidence is unusually clear.

You asked whether fewer sources would be better. Tested properly, the answer is
no, and one result settles it.

**DBnomics serves a 14-month-old Fed funds rate with HTTP 200.** Observed
2026-09-13: `BIS/WS_CBPOL/M.US` returns **2025-06 = 4.375%**. The true current
value from the BIS API is **2026-08 = 3.625%** — 75bp wrong, well-formed, no
error. `D.CN` is stale by the same ~14 months. Its BIS fetcher broke on the BIS
data-portal migration and has been dead for over a year while continuing to
serve the old mirror. Its OECD mirror is ~3 months behind; its IMF mirror is
frozen at September 2025, before the IMF's November 2025 migration. DBnomics
also does not carry SNB or Norges Bank at all, so Switzerland and Norway could
never have been consolidated onto it regardless. Operated by CEPREMAP with an
explicit disclaimer that it is "not responsible for the accuracy or continued
availability of the source data".

**The general lesson, which is the part worth keeping:** outage is the *benign*
failure — loud, immediate, obviously a bug. The failure that actually damages a
dashboard is **silent freeze**, and an aggregator is strictly worse there,
because it adds a scraping step that can rot with nobody on either side
noticing. Your twelve bespoke parsers fail *noisily*: a moved header row or a
wrong User-Agent throws, and you find out. The parsing traps you resent are,
perversely, a monitoring feature.

Do not over-learn it, though — **official sources freeze silently too.** Eurostat
may have retired `prc_hicp_manr` at source with a clean 200 (§4). FRED's OECD
mirrors do it constantly. The real defence is not source topology at all; it is
the staleness check in `db/quality.py` with flag reconciliation. That control is
worth more than any sourcing decision here, and it should cover every series
with a correct expected cadence.

**The one aggregator worth adding: the OECD's own SDMX API** — not as a
replacement, as a cross-check. VERIFIED keyless, and current where FRED's OECD
mirror is frozen: `DSD_STES@DF_FINMARK` gives long-term (`IRLT`) and short-term
(`IR3TIB`) rates for **all eight regions including CHN and EA20, at 2026-08**.
It costs almost no new parsing surface because you already parse BIS SDMX. Use
it to validate the two scraped curves, not to feed them. Note its CPI dataflow
is **9 months stale for CH and NO**, so it is not a CPI source.

**Everything else in the multilateral space, checked and rejected:** the IMF has
no verified free sub-annual data path (legacy `dataservices.imf.org` is DNS-dead,
`sdmxcentral` returns 501 for data, `api.imf.org` is documented but unverifiable
here and its key boundary is undocumented — do not build on it). UNECE works but
its CPI is at 2026M03 and GDP at 2025Q4, and it has no China or Japan. UNdata's
data service 500s. UNCTAD has no API. ESCAP, AMRO, AfDB, EBRD, IDB have no
relevant coverage. ADB is annual. **BIS you already use, and use correctly** —
one request for seven policy rates, and its terms permit unrestricted use with
citation, though it reserves the right to rate-limit by IP, so keep volume
modest.

---

## Recommended order of work

Sequenced by value per unit of effort. Nothing here changes layout or output
format; items 1–3 are additive or swap a feed behind an existing series.

1. **Swiss curve → SNB `rendeiduebd` + RSS `R10`.** Retires the only unofficial
   source, buys 38 years of history and 12 tenors, closes a known fragility.
2. **China curve → ChinaBond `historyQuery`.** Fills a total gap: 8 tenors back
   to 2010. Label as a scrape; validate against OECD `CHN.M.IRLT`.
3. **China GDP → World Bank GEM `source=15`.** Annual → quarterly, same host and
   auth model you already use. Mind the `date`-range trap.
4. **CPI currency for US, Norway, UK, Switzerland.** All keyless, all verified.
   Use the corrected ONS host and SSB table 14702.
5. **Eurozone/Germany CPI** — only after resolving whether `prc_hicp_manr` is
   retired at source. ECB `ICP` is the likely landing place.
6. **GDP: CH and NO off FRED onto Eurostat; add UK `abmi/pn2`.** Removes the FX
   conversion layer from the series that caused the rebasing incident.
7. **Credit: Bundesbank (DE) and JSDA (JP)**, in their own non-OAS column.
8. **ECB SPF**, in its own survey-labelled column.

## Test from the Mac before building

All UNVERIFIED (robots) and likely fine with `requests`:
`data-api.ecb.europa.eu` (HICP `ICP`, and SPF), `sdmx.oecd.org/.../data/`,
`api.worldbank.org` GEM (verified via a different path, but re-run the exact
query), and the BFS PxWeb LIK cube id for the faster Swiss CPI tier.

Genuinely open question, not a tooling artefact: **is Eurostat `prc_hicp_manr`
retired?** That one changes the euro-area recommendation.
