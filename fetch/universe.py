"""
Single source of truth for what the dashboard tracks: every series, which
region/category it belongs to, and which source module + source-specific
identifier fetches it.

Adding a new series or region = add an entry here. Nothing else should
hardcode ticker/series lists.

Every identifier below was confirmed against a live response — see SPEC.md's endpoint appendix
for each endpoint's quirks.

Every fetchable entry here also carries the `series_id` that keys it in
`data/markets.db` and in DATA-CATALOG.csv. Where the id is mechanical
(`equity.<region>.<id>`, `curve.<region>.<tenor>`) `db/registry.py` derives it;
where the catalog's identifier does not follow from the entry's own fields
(credit spreads, liquidity, the bond proxies) it is spelled out below, because
the catalog identifier is the database key and guessing it in two places is
how the two drift apart.
"""

REGIONS = ["US", "UK", "EZ", "DE", "CH", "CN", "JP", "NO"]

REGION_NAMES = {
    "US": "United States",
    "UK": "United Kingdom",
    "EZ": "Eurozone",
    "DE": "Germany",
    "CH": "Switzerland",
    "CN": "China",
    "JP": "Japan",
    "NO": "Norway",
}

# ---------------------------------------------------------------------------
# 1. Equity indices — source: Yahoo Finance via yfinance.
# Stooq was the original source and is now unusable (JS anti-bot challenge).
# ---------------------------------------------------------------------------
# `weighting` and `basis` drive the tooltip on each index name. They are worth
# stating because two of these are routinely misread: the DAX is a PERFORMANCE
# index (dividends reinvested), so it is not comparable with the price-return
# indices beside it, and the Nikkei 225 is PRICE-weighted, so a high-priced
# constituent moves it regardless of company size. Where the tracked instrument
# is an ETF rather than the index, `basis` says so — a fund price is not an
# index level.
EQUITY_INDICES = [
    {"id": "sp500", "region": "US", "name": "S&P 500", "currency": "USD", "yahoo": "^GSPC",
     "weighting": "Float-adjusted market-cap weighted",
     "basis": "Price return — dividends are not included"},
    {"id": "nasdaq100", "region": "US", "name": "Nasdaq 100", "currency": "USD", "yahoo": "^NDX",
     "weighting": "Modified market-cap weighted (largest holdings capped)",
     "basis": "Price return — dividends are not included"},
    {"id": "russell2000", "region": "US", "name": "Russell 2000", "currency": "USD", "yahoo": "^RUT",
     "weighting": "Float-adjusted market-cap weighted",
     "basis": "Price return — dividends are not included"},
    {"id": "ftse100", "region": "UK", "name": "FTSE 100", "currency": "GBP", "yahoo": "^FTSE",
     "weighting": "Float-adjusted market-cap weighted",
     "basis": "Price return — dividends are not included"},
    {"id": "stoxx600", "region": "EZ", "name": "STOXX Europe 600", "currency": "EUR", "yahoo": "^STOXX",
     "weighting": "Free-float market-cap weighted",
     "basis": "Price return — dividends are not included"},
    {"id": "dax", "region": "DE", "name": "DAX", "currency": "EUR", "yahoo": "^GDAXI",
     "weighting": "Free-float market-cap weighted",
     "basis": "TOTAL RETURN — the DAX reinvests dividends, so its level is not "
              "comparable with the price-return indices beside it"},
    {"id": "smi", "region": "CH", "name": "SMI", "currency": "CHF", "yahoo": "^SSMI",
     "weighting": "Free-float market-cap weighted (constituents capped at 18%)",
     "basis": "Price return — dividends are not included"},
    # Yahoo serves the CSI 300 index itself (000300.SS / 399300.SZ) with only
    # 1d/5d of history — no daily series — so the mainland-listed, CNY-priced
    # tracker ETF stands in. Same convention as msci_em/bcom.
    {"id": "csi300", "region": "CN", "name": "CSI 300 (proxy: 510300.SS ETF)", "currency": "CNY", "yahoo": "510300.SS",
     "weighting": "Free-float market-cap weighted",
     "basis": "Fund price, not the index — a dividend-distributing tracker ETF "
              "stands in because Yahoo serves the CSI 300 itself with only days "
              "of history"},
    {"id": "hangseng", "region": "CN", "name": "Hang Seng", "currency": "HKD", "yahoo": "^HSI",
     "weighting": "Free-float market-cap weighted (constituents capped at 8%)",
     "basis": "Price return — dividends are not included"},
    {"id": "nikkei225", "region": "JP", "name": "Nikkei 225", "currency": "JPY", "yahoo": "^N225",
     "weighting": "PRICE-weighted, not market-cap weighted — a high share price "
                  "moves it more than a large company does",
     "basis": "Price return — dividends are not included"},
    {"id": "osebx", "region": "NO", "name": "OSEBX (Oslo Børs)", "currency": "NOK", "yahoo": "OSEBX.OL",
     "weighting": "Free-float market-cap weighted",
     "basis": "Price return, adjusted for corporate actions"},
    # Secondary tier
    {"id": "msci_em", "region": "EM", "name": "MSCI EM (proxy: EEM ETF)", "currency": "USD", "yahoo": "EEM",
     "weighting": "Free-float market-cap weighted",
     "basis": "Fund price, not the index — a dividend-distributing ETF stands in"},
]

VOLATILITY_INDICES = [
    {"id": "vix", "region": "US", "name": "VIX", "yahoo": "^VIX",
     "series_id": "vol.US.vix"},
    {"id": "vstoxx", "region": "EZ", "name": "VSTOXX", "yahoo": None, "note": "No confirmed free daily source found — leave blank until sourced."},
]

# ---------------------------------------------------------------------------
# 2. Currencies — Yahoo Finance
# ---------------------------------------------------------------------------
CURRENCIES = [
    {"id": "dxy", "name": "US Dollar Index (DXY)", "yahoo": "DX-Y.NYB"},
    {"id": "eurusd", "name": "EUR/USD", "yahoo": "EURUSD=X"},
    {"id": "gbpusd", "name": "GBP/USD", "yahoo": "GBPUSD=X"},
    {"id": "usdjpy", "name": "USD/JPY", "yahoo": "USDJPY=X"},
    {"id": "usdchf", "name": "USD/CHF", "yahoo": "USDCHF=X"},
    {"id": "eurchf", "name": "EUR/CHF", "yahoo": "EURCHF=X"},
    {"id": "usdcny", "name": "USD/CNY", "yahoo": "USDCNY=X"},
    {"id": "eurnok", "name": "EUR/NOK", "yahoo": "EURNOK=X"},
]

# ---------------------------------------------------------------------------
# 3. Commodities — Yahoo Finance. Oil = Brent only (WTI deliberately dropped).
# Each entry states the exchange, contract and unit: "natural gas" is
# meaningless without saying whether it is US Henry Hub or European TTF, and
# copper is quoted in USD/lb on COMEX but USD/tonne on the LME.
# ---------------------------------------------------------------------------
COMMODITIES = [
    {"id": "brent", "name": "Oil — Brent Crude", "yahoo": "BZ=F",
     "exchange": "ICE", "contract": "Brent Crude, front month", "unit": "USD/bbl"},
    {"id": "wti", "name": "Oil — WTI", "yahoo": "CL=F",
     "exchange": "NYMEX", "contract": "WTI Light Sweet Crude, front month", "unit": "USD/bbl"},
    {"id": "natgas_hh", "name": "Natural Gas — Henry Hub (US)", "yahoo": "NG=F",
     "exchange": "NYMEX", "contract": "Henry Hub Natural Gas, front month", "unit": "USD/MMBtu"},
    {"id": "natgas_ttf", "name": "Natural Gas — TTF (Europe)", "yahoo": "TTF=F",
     "exchange": "ICE", "contract": "Dutch TTF Natural Gas, front month", "unit": "EUR/MWh"},
    {"id": "gold", "name": "Gold", "yahoo": "GC=F",
     "exchange": "COMEX", "contract": "Gold, front month", "unit": "USD/troy oz"},
    {"id": "silver", "name": "Silver", "yahoo": "SI=F",
     "exchange": "COMEX", "contract": "Silver, front month", "unit": "USD/troy oz"},
    {"id": "copper", "name": "Copper", "yahoo": "HG=F",
     "exchange": "COMEX", "contract": "Copper, front month", "unit": "USD/lb"},
    # No confirmed free live broad commodity index — ETF proxy.
    {"id": "bcom", "name": "Broad commodities (proxy: DBC ETF)", "yahoo": "DBC",
     "exchange": "NYSE Arca", "contract": "Invesco DB Commodity Index Tracking Fund", "unit": "USD"},
]

# ---------------------------------------------------------------------------
# 4. Central bank policy rates — BIS CBPOL, every region on one endpoint.
#
# Norway consolidated onto BIS `D.NO` on 2026-08-29 per DATA-CATALOG.csv,
# replacing a separate Norges Bank fetch. Both were checked side by side and
# agree at 4.25; BIS reaches back to 2001. Norges Bank is 1-3 days fresher,
# which does not matter for a rate that sits unchanged for months and is
# checked against a 150-day threshold. Norway's YIELD CURVE still comes from
# Norges Bank directly — only the policy rate moved.
#
# Germany has no policy rate of its own: it IS the ECB's. `mirror_of` says so
# explicitly, so the export reads the EZ series rather than storing a second
# copy of the same numbers under a German id.
# ---------------------------------------------------------------------------
CENTRAL_BANKS = [
    {"region": "US", "name": "Federal Reserve (Fed Funds)", "source": "bis", "bis_ref_area": "US"},
    {"region": "UK", "name": "Bank of England (Bank Rate)", "source": "bis", "bis_ref_area": "GB"},
    {"region": "EZ", "name": "European Central Bank (Deposit Rate)", "source": "bis", "bis_ref_area": "XM"},
    # Germany's policy rate IS the ECB's — mirrored rather than shown blank.
    {"region": "DE", "name": "European Central Bank (Deposit Rate)", "source": "bis",
     "bis_ref_area": "XM", "mirror_of": "EZ"},
    {"region": "CH", "name": "Swiss National Bank (Policy Rate)", "source": "bis", "bis_ref_area": "CH"},
    {"region": "CN", "name": "People's Bank of China", "source": "bis", "bis_ref_area": "CN"},
    {"region": "JP", "name": "Bank of Japan", "source": "bis", "bis_ref_area": "JP"},
    {"region": "NO", "name": "Norges Bank (Key Policy Rate)", "source": "bis", "bis_ref_area": "NO"},
]

# ---------------------------------------------------------------------------
# 5. Government yield curves — nominal.
#
# EZ uses the ECB's ALL-BONDS euro area curve (G_N_C), deliberately not the
# AAA curve (G_N_A): AAA tracks the Bund almost exactly (3.28 vs 3.22 on
# 2026-08-27), which made the old EZ row a duplicate of Germany. The
# all-bonds curve is a genuine multi-sovereign blend (3.70 on the same day).
# ---------------------------------------------------------------------------
YIELD_CURVES = {
    "US": {
        "source": "fred", "cadence": "daily",
        "tenors": {"2Y": "DGS2", "5Y": "DGS5", "10Y": "DGS10", "30Y": "DGS30"},
    },
    "UK": {
        "source": "boe_glc", "cadence": "daily",
        "note": "Bank of England GLC nominal spot curve (commercial-bank "
                "liability curve workbook), full 0.5y-40y term structure.",
        "tenors": {"2Y": "2", "5Y": "5", "10Y": "10", "30Y": "30"},
        "glc_file": "nominal",
    },
    "EZ": {
        "source": "ecb", "cadence": "daily",
        "note": "ECB euro area yield curve, ALL government bonds (a blend "
                "across euro area sovereigns), not the AAA-only curve.",
        "tenors": {
            "2Y": "YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_2Y",
            "5Y": "YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_5Y",
            "10Y": "YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_10Y",
            "30Y": "YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_30Y",
        },
    },
    "DE": {
        "source": "bundesbank", "cadence": "daily",
        "note": "Deutsche Bundesbank daily term structure on listed Federal "
                "securities (Svensson). Literal single-issuer Bund curve.",
        "tenors": {
            "2Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R02XX.R.A.A._Z._Z.A",
            "5Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R05XX.R.A.A._Z._Z.A",
            "10Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A",
            "30Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R30XX.R.A.A._Z._Z.A",
        },
    },
    "CH": {
        # The SNB never retired this curve — it moved cubes. `rendoblid`
        # stopped on 2025-07-31 and `rendeiduebd` carries it forward, with
        # continuous daily data through the Aug-Sep 2025 window where the old
        # cube ended. Verified 2026-09-13; SPEC.md's dead-ends entry was wrong.
        # Retiring the TradingEconomics scrape here removes the project's only
        # unofficial source.
        #
        # The cube publishes in a MONTHLY BATCH, so it gets a monthly cadence:
        # judged as daily it would go stale every month by construction. The
        # RSS R10 series below is the one judged as current.
        "source": "snb", "cadence": "monthly_batch",
        "note": "SNB cube rendeiduebd, Swiss Confederation bond issues "
                "(dimSel D0=CHF), daily spot rates back to 1988-01-04. "
                "Published in a monthly batch; the SNB interest-rate RSS "
                "feed carries the 10y between batches.",
        # D1 is the SNB's own maturity label, in years-German: 10J, not 10Y.
        "tenors": {"2Y": "2J", "5Y": "5J", "10Y": "10J", "30Y": "30J"},
    },
    "CN": {
        # Server-rendered after all: the earlier attempts hit ChinaBond's
        # JavaScript front-end path, not the `cbweb-pbc-web/pbc/` endpoints
        # underneath it, which answer a plain cold GET. Verified 2026-09-13;
        # SPEC.md's dead-ends entry was wrong.
        #
        # ChinaBond publishes 3M/6M/1Y/3Y/5Y/7Y/10Y/30Y. Only the three that
        # fit the dashboard's shared tenor columns are stored; there is no 2Y
        # point at all, and 3Y is deliberately NOT interpolated into that slot.
        "source": "chinabond", "cadence": "daily",
        "note": "ChinaBond government bond yield curve (中债国债收益率曲线), "
                "server-rendered HTML — a scrape, though an official "
                "CCDC/PBoC-affiliated one. History to 2006-03-01. There is "
                "no 2y point on this curve.",
        "tenors": {"2Y": None, "5Y": "5Y", "10Y": "10Y", "30Y": "30Y"},
    },
    "JP": {
        "source": "mof", "cadence": "daily",
        "note": "Japan Ministry of Finance JGB interest rate CSV — the whole "
                "1Y-40Y curve in one file (chosen over JSDA's per-bond xlsx).",
        "tenors": {"2Y": "2Y", "5Y": "5Y", "10Y": "10Y", "30Y": "30Y"},
    },
    "NO": {
        "source": "norges", "cadence": "daily",
        "note": "Norges Bank zero-coupon government yields. The published "
                "curve stops at 10 years — there is no 30y point.",
        "tenors": {"2Y": "2Y", "5Y": "5Y", "10Y": "10Y", "30Y": None},
    },
}

# Real (inflation-linked) yield curves.
REAL_YIELD_CURVES = {
    "US": {"source": "fred", "cadence": "daily", "basis": "TIPS (CPI-linked)",
           "tenors": {"2Y": None, "5Y": "DFII5", "10Y": "DFII10", "30Y": "DFII30"}},
    "UK": {"source": "boe_glc", "cadence": "daily", "basis": "index-linked gilts (RPI-linked)",
           "glc_file": "real",
           "tenors": {"2Y": "2", "5Y": "5", "10Y": "10", "30Y": "30"}},
}

# Euro-area sovereign spreads vs. Bund. Both legs come from the SAME ECB
# series so the spread is not contaminated by methodology or vintage
# differences — ECB's own German figure (3.07 for 2026-07) differs from the
# Bundesbank daily curve (3.22), so mixing the two would be wrong.
EUROZONE_SPREAD_BENCHMARK = {"country": "Germany", "ecb_key": "IRS/M.DE.L.L40.CI.0000.EUR.N.Z"}
EUROZONE_SPREAD_PANEL = [
    {"country": "France", "ecb_key": "IRS/M.FR.L.L40.CI.0000.EUR.N.Z"},
    {"country": "Italy", "ecb_key": "IRS/M.IT.L.L40.CI.0000.EUR.N.Z"},
    {"country": "Spain", "ecb_key": "IRS/M.ES.L.L40.CI.0000.EUR.N.Z"},
]

# ---------------------------------------------------------------------------
# 6. Inflation — the national headline print, from each country's own
# statistics office wherever one is reachable keylessly.
#
# This moved off a single BIS dataflow on 2026-09-13. BIS releases WS_LONG_CPI
# once a month in the last week, and each print is dated to the first of the
# month it describes, so its newest observation is between 27 and 57 days old.
# Going direct to the publisher cuts that by 6-17 days per region, and because
# the dashboard polls weekly the gain is in AVERAGE staleness, not just in the
# arrival lag.
#
# ON COMPARABILITY, which is the real constraint here: there is no single
# methodology that covers all eight. HICP does not exist for the US, China or
# Japan. So each region stores its own headline national print -- the number
# its market actually trades -- and every entry carries an explicit `basis`
# saying which. Do NOT "harmonise" the UK onto CPIH: it adds owner-occupier
# housing costs and stops being comparable to the rest.
#
# Two regions stay on BIS deliberately:
#   - China, because data.stats.gov.cn returns HTTP 403 to non-browser clients
#     from outside the mainland, which is a GitHub Actions runner exactly.
#   - Japan, because e-Stat would buy only 9 days and is the one switch here
#     that costs an Actions secret.
#
# Where a source publishes only the index, the annual rate is derived from it
# downstream. That is the direction this project prefers anyway: store what is
# published, derive the growth.
# ---------------------------------------------------------------------------
INFLATION_CPI = {
    # FRED serves CPIAUCNS (NSA) as a level only -- there is no published YoY
    # series, and the "_PC1" graph suffix is silently ignored, returning the
    # level under the base id. So the rate is derived. History to 1913-01.
    "US": {"source": "fred", "basis": "CPI-U", "cadence": "monthly_national",
           "index": "CPIAUCNS",
           "definition": "US CPI-U, all urban consumers, not seasonally "
                         "adjusted — the basis every other region here is on."},
    # api.ons.gov.uk is DEAD (404 on every path); www.ons.gov.uk is the host.
    # ONS publishes both legs, so neither is derived.
    "UK": {"source": "ons", "basis": "CPI", "cadence": "monthly_national",
           "ons_dataset": "mm23", "index": "d7bt", "yoy": "d7g7",
           "definition": "UK CPI (not CPIH: CPIH adds owner-occupier housing "
                         "costs and is not comparable to the others)."},
    # Eurostat retired prc_hicp_manr and prc_hicp_midx on 2026-02-04 for the
    # ECOICOP ver.2 changeover -- both sit frozen at 2025-12 while returning
    # HTTP 200. The ECB discontinued its mirror ICP dataset the same day. The
    # successor is prc_hicp_minr, whose item dimension is coicop18=TOTAL (not
    # coicop=CP00) and whose index unit is I25 (2025=100, not 2015=100).
    "EZ": {"source": "eurostat", "basis": "HICP", "cadence": "monthly_national",
           "eurostat_dataset": "prc_hicp_minr", "geo": "EA",
           "definition": "Euro area HICP, all-items."},
    # Germany moves from BIS's national VPI to HICP. A real methodology
    # switch: they printed identically at +2.9% in Aug 2026 and typically
    # differ by <=0.3pp, but it is a different index and is recorded as such.
    "DE": {"source": "eurostat", "basis": "HICP", "cadence": "monthly_national",
           "eurostat_dataset": "prc_hicp_minr", "geo": "DE",
           "definition": "German HICP, all-items — NOT the national VPI that "
                         "the BIS series carried."},
    "CH": {"source": "snb", "basis": "LIK", "cadence": "monthly_national",
           "index": "LD2010100", "yoy": "VVP",
           "definition": "Swiss LIK (Landesindex der Konsumentenpreise)."},
    # Table 14710, NOT 14702. 14702 is CPI by DELIVERY SECTOR and its "consumer
    # goods" aggregate is not the headline: measured 2026-09-13 it printed 7.7
    # against the headline's 6.5 in 2023M03. 14710 is the headline index, base
    # 2025=100, back to 1920M03 -- deeper than the BIS series it replaces.
    "NO": {"source": "ssb", "basis": "KPI", "cadence": "monthly_national",
           "table": "14710", "index": "KpiIndMnd",
           "definition": "Norwegian KPI, all-items."},
    "CN": {"source": "bis", "basis": "CPI", "ref_area": "CN",
           "definition": "China headline CPI (BIS: the NBS refuses "
                         "non-browser clients from outside the mainland)."},
    "JP": {"source": "bis", "basis": "CPI", "ref_area": "JP",
           "definition": "Japan headline CPI."},
}

# Inflation expectations. Every entry states its tenor and its index basis,
# because these are NOT comparable across regions otherwise: UK linkers
# reference RPI, which historically runs ~0.8-1.0pp above CPI, so an
# unlabelled UK number looks alarming next to CPI-based peers.
INFLATION_EXPECTATIONS = {
    "US": {
        "source": "fred", "basis": "CPI", "kind": "market",
        "tenors": {"5y": "T5YIE", "10y": "T10YIE", "5y5y_fwd": "T5YIFR"},
        # No 1y TIPS breakeven is published; the Cleveland Fed model series
        # (TIPS + swaps + survey) is the standard stand-in for the short end.
        "model": {"source": "fred", "kind": "model", "basis": "CPI",
                  "tenors": {"1y": "EXPINF1YR", "5y": "EXPINF5YR", "10y": "EXPINF10YR"}},
    },
    "UK": {
        "source": "boe_glc", "glc_file": "inflation", "basis": "RPI", "kind": "market",
        "note": "BoE implied inflation curve is RPI-based (UK linkers reference "
                "RPI), typically ~0.8-1.0pp above the equivalent CPI rate.",
        "tenors": {"2y": "2", "5y": "5", "10y": "10"},
    },
    "EZ": {"source": None, "kind": "unavailable",
           "note": "The practitioner standard is the EUR HICPx zero-coupon "
                   "inflation swap, which has no free feed. The ECB FM dataflow "
                   "carries no ILS series."},
    "DE": {"source": None, "kind": "unavailable", "note": "See Eurozone — no free euro-area ILS feed."},
    "CH": {"source": None, "kind": "unavailable", "note": "No CHF inflation-linked bond market of usable size."},
    "CN": {"source": None, "kind": "unavailable", "note": "No accessible CNY inflation-linked market data."},
    "JP": {"source": None, "kind": "unavailable", "note": "JGBi breakevens are not published in a free machine-readable feed."},
    "NO": {"source": None, "kind": "unavailable", "note": "No NOK inflation-linked bond market."},
}

# ---------------------------------------------------------------------------
# 7. GDP — real, chain-linked volumes, national currency (NOT PPP),
# seasonally adjusted. Growth is derived in the pipeline so every region is on
# the same definition; FRED's OECD growth series are discontinued.
# ---------------------------------------------------------------------------
GDP_GROWTH = {
    "US": {"source": "fred", "series": "GDPC1", "freq": "Q"},
    # ONS quarterly chained volume, the same grain and definition as the other
    # seven. The monthly GVA index that used to sit here is kept as a UK-only
    # supplementary nowcast (UK_GDP_NOWCAST below) rather than as THE UK GDP
    # series: it is GVA-based, and mixing an output-approach index into a YoY
    # comparison against seven quarterly chain-linked series is exactly the
    # definitional seam that produces a wrong headline.
    #
    # The DATASET SUFFIX, not the series code, controls the vintage. Measured
    # 2026-09-13, abmi/pn2 returned 2026 Q2 while abmi/qna returned 2026 Q1 for
    # the identical series id -- a full quarter staler, silently. Do not
    # "simplify" this to qna.
    "UK": {"source": "ons", "ons_series": "abmi", "ons_dataset": "pn2", "freq": "Q",
           "ons_frequency": "quarters",
           "definition": "ONS quarterly GDP, chained volume measure, "
                         "seasonally adjusted (£m, 2022 = 100 chained)."},
    # Eurostat's own quarterly national accounts. NOT the catalog's teina011,
    # which carries only percentage changes over a rolling 12 quarters — the
    # pipeline needs LEVELS to derive growth on one common definition. Also
    # EA20 (the current membership) where FRED's series is the superseded EA19.
    "EZ": {"source": "eurostat", "eurostat_dataset": "namq_10_gdp", "freq": "Q",
           "eurostat_filters": {"geo": "EA20", "unit": "CLV15_MEUR",
                                "s_adj": "SCA", "na_item": "B1GQ", "freq": "Q"}},
    "DE": {"source": "fred", "series": "CLVMNACSCAB1GQDE", "freq": "Q"},
    # CH and NO went direct to Eurostat on 2026-09-13. The lag gain is about
    # zero; the reason is that CLVMNACSCAB1GQCH self-reports "Source: Eurostat"
    # with units "Millions of Chained 2010 Euros" -- Swiss GDP was never
    # Swiss-sourced. It was Eurostat data passed through FRED with a euro FX
    # conversion layer on top, and it is the exact series that produced the
    # 2026-09-08 rebasing incident. Going direct removes the intermediary AND
    # the currency conversion, and puts CH/NO on the same code path as EA/DE.
    #
    # CLV_I15 rather than EA/DE's CLV15_MEUR deliberately: it is a pure index
    # with no currency in it at all, which is the whole point for two countries
    # that do not use the euro. Both are chain-linked volume levels, so the
    # growth rates derived from them are on identical definitions.
    "CH": {"source": "eurostat", "eurostat_dataset": "namq_10_gdp", "freq": "Q",
           "eurostat_filters": {"geo": "CH", "unit": "CLV_I15",
                                "s_adj": "SCA", "na_item": "B1GQ", "freq": "Q"}},
    "JP": {"source": "fred", "series": "JPNRGDPEXP", "freq": "Q"},
    "NO": {"source": "eurostat", "eurostat_dataset": "namq_10_gdp", "freq": "Q",
           "eurostat_filters": {"geo": "NO", "unit": "CLV_I15",
                                "s_adj": "SCA", "na_item": "B1GQ", "freq": "Q"}},
    # Quarterly at last. FRED has no free quarterly real GDP for China (its
    # candidates all 404, and the OECD series that used to carry it died in
    # 2023Q3), and the NBS returns HTTP 403 to non-browser clients from outside
    # the mainland -- a GitHub Actions runner's exact situation. The World Bank
    # Global Economic Monitor carries it: a constant-2010-LCU seasonally
    # adjusted LEVEL back to 1991Q1, keyless, on a host already used here.
    # Worst-case staleness drops from ~15 months to about T+6-8 weeks.
    "CN": {"source": "worldbank_gem", "country": "CHN",
           "indicator": "NYGDPMKTPSAKN", "freq": "Q"},
}
# The UK monthly GVA index, demoted from the GDP row above. It is more current
# in information terms (July data on 11 September) and a genuinely useful
# nowcast, but it is a different measure on a different grain, so it is
# published as its own labelled series rather than mixed into the comparison.
UK_GDP_NOWCAST = {
    "region": "UK", "series_id": "gdp.UK.monthly_nowcast",
    "ons_series": "ecy2", "ons_dataset": "mgdp", "cadence": "monthly_lagged",
    "definition": "ONS monthly GVA index (the output-approach measure published "
                  "as UK monthly GDP), chain-linked volume, seasonally "
                  "adjusted. Index, 2022 = 100. A nowcast, not comparable to "
                  "the quarterly chain-linked series in the GDP table.",
}

GDP_DEFINITION = ("Real (chain-linked volume), national currency, not PPP, "
                  "seasonally adjusted. YoY and annualised QoQ derived from the level series.")

# ---------------------------------------------------------------------------
# 7b. Credit spreads — ICE BofA option-adjusted spreads via FRED.
#
# NOTE: FRED serves only a rolling ~3-year window for these, even when an
# explicit start date back to 1997 is requested — an ICE licensing limit, not
# a bug. So percentile context on these can only ever resolve the "full"
# window, and 5y/10y correctly stay hidden.
#
# `stack_leg` marks the one series used as the credit leg of the
# cost-of-capital stack. Only investment grade qualifies: mixing an IG spread
# for one region with a high-yield spread for another would make the stacks
# silently non-comparable.
# ---------------------------------------------------------------------------
CREDIT_SPREADS = [
    {"id": "us_ig", "region": "US", "name": "US investment grade credit spread",
     "series": "BAMLC0A0CM", "grade": "IG", "stack_leg": True,
     "series_id": "credit.US.ig_oas"},
    {"id": "us_hy", "region": "US", "name": "US high yield credit spread",
     "series": "BAMLH0A0HYM2", "grade": "HY", "stack_leg": False,
     "series_id": "credit.US.hy_oas"},
    {"id": "eu_hy", "region": "EZ", "name": "Euro high yield credit spread",
     "series": "BAMLHE00EHYIOAS", "grade": "HY", "stack_leg": False,
     "series_id": "credit.EZ.hy_oas"},
    {"id": "em_corp", "region": "EM", "name": "EM corporate credit spread",
     "series": "BAMLEMCBPIOAS", "grade": "IG/HY blend", "stack_leg": False,
     "series_id": "credit.EM.corp_oas"},
]

# ---------------------------------------------------------------------------
# 7c. Corporate spread to government, NOT option-adjusted.
#
# WHY A SECOND, SEPARATELY LABELLED MEASURE RATHER THAN MORE ROWS ABOVE: the
# ICE series above are option-adjusted spreads, and OAS is not free for any
# currency but the dollar. FRED release rid=209 was enumerated in full -- 192
# series -- and euro coverage is exactly four, all high yield. There is no euro
# IG, no sterling series of any kind, no yen, no developed-Asia IG. That is
# structural, not an oversight: the euro, sterling and yen IG benchmarks ARE
# the ICE, iBoxx and Bloomberg indices, and ICE licenses only its US series to
# FRED for free redistribution. The ECB licenses them rather than publishing
# them. Two near-misses are traps and must not be substituted:
# BAMLEMEBCRPIEOAS is EUR-denominated but EM issuers, and BAMLEMIBHGCRPIOAS is
# IG-rated but EM issuers. Neither is a euro area proxy.
#
# What IS available free is the plainer measure: a corporate yield minus a
# government yield, no option adjustment and no duration matching. That is a
# DIFFERENT QUANTITY from an OAS -- it does not strip out issuers' call rights,
# and it compares portfolios of unequal duration -- so under this project's own
# rule (every figure states its definition; a number not comparable to the ones
# beside it is a reporting error) it cannot sit in the OAS column. It gets its
# own labelled column, and the US is additionally computed on this basis so
# that the column is internally consistent rather than a US OAS beside
# non-US approximations.
#
# Each entry names the two legs and both come from ONE publisher at one
# vintage, so the methodology gap between publishers never enters the spread.
# ---------------------------------------------------------------------------
CORPORATE_SPREADS_TO_GOVT = [
    {
        "region": "US",
        "name": "US investment grade, spread to government",
        # ICE BofA US Corporate index EFFECTIVE YIELD, not the OAS series.
        "corporate": {"source": "fred", "series": "BAMLC0A0CMEY",
                      "series_id": "credit.US.ig_yield"},
        # The 10y Treasury already stored for the curve panel, reused rather
        # than fetched twice, so the leg subtracted here is the same number the
        # cost-of-capital table shows as its risk-free leg.
        "government": {"source": "stored", "series_id": "curve.US.10Y"},
        "note": "ICE BofA US Corporate effective yield less the 10y Treasury. "
                "Not option-adjusted and not duration-matched — a deliberately "
                "plainer measure than credit.US.ig_oas, computed so this column "
                "has a consistent basis across regions.",
    },
    {
        "region": "DE",
        "name": "German corporate, spread to government",
        # Both legs are Bundesbank BBSIS daily yields on debt securities
        # outstanding, computed the same way on the same universe basis, back
        # to 1979. The daily corporate series is not listed on the Bundesbank
        # web page; the API serves it anyway.
        "corporate": {"source": "bundesbank",
                      "series": "D.I.UMR.RD.EUR.X2000.B.A.A.R.A.A._Z._Z.A",
                      "series_id": "credit.DE.corp_yield"},
        "government": {"source": "bundesbank",
                       "series": "D.I.UMR.RD.EUR.S13.B.A.A.R.A.A._Z._Z.A",
                       "series_id": "credit.DE.govt_yield"},
        "note": "Bundesbank yields on outstanding debt securities: corporate "
                "less general government. One publisher, one methodology, one "
                "vintage, so no cross-publisher gap enters the spread.",
    },
]

# Regions with no free corporate spread on ANY basis, and why. These read as
# unavailable rather than pending: each was checked and closed, not skipped.
CORPORATE_SPREAD_UNAVAILABLE = {
    "UK": "No free sterling corporate bond index exists on any basis. The "
          "benchmark is iBoxx/ICE, licensed. BoE effective lending rates are "
          "bank loan rates to largely unrated borrowers, not bond spreads, and "
          "are explicitly rejected as a proxy.",
    "EZ": "No free euro INVESTMENT-GRADE series exists (FRED release 209 "
          "enumerated in full: euro coverage is four high-yield series). ECB "
          "MIR is bank lending rates, not bond spreads; ECB STEP is a real "
          "credit spread but at overnight-to-91-day maturities and was last "
          "updated 2026-05-12. Both rejected.",
    "CH": "The SNB's rendoblid rating buckets would have been exactly right "
          "and died with the same 2025 cut that moved the curve.",
    "CN": "No free onshore corporate curve beyond ChinaBond's AAA financial "
          "and CP&Note curves, which are not a broad IG corporate index.",
    "JP": "JSDA publishes an OTC reference-price rating matrix (average "
          "compound yield per rating, all maturities) but no spread, and no "
          "government leg computed the same way — the sibling file is "
          "per-bond, so the government side would have to be constructed by "
          "hand, which is a different computation from the corporate side. "
          "Its URLs also encode one business day each, so history would cost "
          "~6,000 requests, and the host returned connect timeouts when "
          "polled on 2026-09-13. Closed as not comparable rather than as "
          "merely expensive.",
    "NO": "No free Norwegian corporate bond index. Nordic Bond Pricing is "
          "commercial.",
}

COST_OF_CAPITAL_NOTE = (
    "Real risk-free (10y inflation-linked) + investment-grade credit spread + "
    "equity risk premium. A real discount rate, because the risk-free leg is "
    "real — do not compare it with a nominal yield. Legs are summed only where "
    "each is sourced for that region; a partial stack shows what it has and "
    "says which legs are missing."
)

# ---------------------------------------------------------------------------
# 7c. Liquidity / lending conditions.
#
# Dropped 2026-08-29 at Marco's request: the Fed's SLOOS was the only region
# with a keyless feed, and a single-country lending panel was not being used.
# The already-stored sloos.US.ci_large rows stay in the database — the store is
# append-only — they are simply no longer fetched or displayed.
# ---------------------------------------------------------------------------
LIQUIDITY_INDICATORS = []

# ---------------------------------------------------------------------------
# 7d. FX hedging cost, from a CHF investor's seat — the two pairs Marco named.
# See transform/fx_hedging.py for why this is an approximation and what it
# leaves out; the caveats must travel with the number to the UI.
# ---------------------------------------------------------------------------
FX_HEDGING = [
    {"id": "usd_chf", "name": "USD exposure hedged to CHF", "foreign_region": "US", "foreign_ccy": "USD"},
    {"id": "eur_chf", "name": "EUR exposure hedged to CHF", "foreign_region": "EZ", "foreign_ccy": "EUR"},
]
FX_HEDGING_HOME_REGION = "CH"

# ---------------------------------------------------------------------------
# 7e. Cross-asset set for the rolling correlation heatmap.
#
# One representative series per bloc rather than all 12 equity indices — a
# 12x12 grid of near-identical equity pairs is unreadable and says nothing.
#
# The bond proxies are the only genuinely new instrument in the V2 plan: the
# pipeline fetches yields everywhere but no tradeable bond *return*, and a
# yield cannot be correlated against equity returns. ETFs stand in, the same
# convention already used for csi300 and bcom.
# ---------------------------------------------------------------------------
# Six of the eight legs are series the database already stores for other
# panels, so they name that `series_id` and are NOT fetched or stored a second
# time. Only the two bond proxies are new instruments, and they carry their own
# catalog ids.
CROSS_ASSET_SET = [
    {"id": "eq_us", "label": "US equities", "yahoo": "^GSPC", "series_id": "equity.US.sp500"},
    {"id": "eq_eu", "label": "Europe equities", "yahoo": "^STOXX", "series_id": "equity.EZ.stoxx600"},
    {"id": "eq_jp", "label": "Japan equities", "yahoo": "^N225", "series_id": "equity.JP.nikkei225"},
    {"id": "eq_em", "label": "EM equities", "yahoo": "EEM", "series_id": "equity.EM.msci_em"},
    {"id": "bond_ust", "label": "UST 7-10y", "yahoo": "IEF", "series_id": "bond_proxy.IEF"},
    {"id": "bond_eur", "label": "Euro govt bonds", "yahoo": "IEGA.AS",
     "series_id": "bond_proxy.IEGA"},
    {"id": "gold", "label": "Gold", "yahoo": "GC=F", "series_id": "commodity.gold"},
    {"id": "oil", "label": "Oil (Brent)", "yahoo": "BZ=F", "series_id": "commodity.brent"},
]
# In WEEKS, since storage is weekly: one year and two years.
CORRELATION_WINDOWS = [52, 104]

# ---------------------------------------------------------------------------
# 8. Equity valuation + equity risk premium.
# ---------------------------------------------------------------------------
# `cape_source` is the discriminator the export uses: CAPE is US-only, because
# it needs a long cyclically-adjusted earnings history that exists for the
# S&P 500 and not for these other indices. The rest of the row is the index
# label shown beside each region's multiples.
VALUATION_PROXIES = [
    {"region": "US", "name": "S&P 500", "cape_source": "shiller"},
    {"region": "UK", "name": "FTSE 100", "cape_source": None},
    {"region": "EZ", "name": "STOXX 600", "cape_source": None},
    {"region": "DE", "name": "DAX", "cape_source": None},
    {"region": "CH", "name": "SMI", "cape_source": None},
    {"region": "CN", "name": "CSI 300 / Hang Seng", "cape_source": None},
    {"region": "JP", "name": "Nikkei 225", "cape_source": None},
    {"region": "NO", "name": "OSEBX", "cape_source": None},
]

# Damodaran's country files cover these six of the eight regions. The US is
# sourced separately (Shiller CAPE + histimpl implied ERP) and the Eurozone is
# deliberately absent: countrystats.xls and ctryprem.xlsx carry member states
# only, with no bloc aggregate, and substituting Germany's figure for the bloc
# is the same error as reading the Bundesbank curve as the ECB's. Both EZ rows
# are `descoped` in DATA-CATALOG.csv, not planned.
DAMODARAN_REGIONS = ["UK", "DE", "CH", "CN", "JP", "NO"]

# The aggregated multiples taken from countrystats.xls. `column` is the bare
# metric as Damodaran spells it; the fetcher matches the median-basis variant
# ("median(Trailing PE)" / "Median Trailing PE") and rejects the pre-2020
# mean-basis columns outright.
VALUATION_MULTIPLES = [
    {"id": "pe", "column": "Trailing PE", "name": "trailing P/E"},
    {"id": "pb", "column": "PBV", "name": "price / book"},
    {"id": "ps", "column": "PS", "name": "price / sales"},
    {"id": "ev_ebitda", "column": "EV/EBITDA", "name": "EV / EBITDA"},
]

# Chart lookback windows offered by the frontend.
CHART_PERIODS = ["3M", "YTD", "1Y", "2Y", "3Y", "5Y"]
