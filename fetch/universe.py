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
    {"id": "ftse_allshare", "region": "UK", "name": "FTSE All-Share", "currency": "GBP",
     "yahoo": "^FTAS",
     "weighting": "Float-adjusted market-cap weighted, ~600 constituents",
     "basis": "Price return — dividends are not included"},
    # AIM is the London growth market: small, illiquid and far more volatile
    # than the All-Share it sits outside. Kept separate for that reason.
    {"id": "ftse_aim", "region": "UK", "name": "FTSE AIM All-Share", "currency": "GBP",
     "yahoo": "^FTAI",
     "weighting": "Float-adjusted market-cap weighted",
     "basis": "Price return — dividends are not included. AIM is London's "
              "growth market: smaller and less liquid than the main market"},
    {"id": "stoxx600", "region": "EZ", "name": "STOXX Europe 600", "currency": "EUR", "yahoo": "^STOXX",
     "weighting": "Free-float market-cap weighted",
     "basis": "Price return — dividends are not included"},
    {"id": "dax", "region": "DE", "name": "DAX", "currency": "EUR", "yahoo": "^GDAXI",
     "weighting": "Free-float market-cap weighted",
     "basis": "TOTAL RETURN — the DAX reinvests dividends, so its level is not "
              "comparable with the price-return indices beside it"},
    # Also a performance index, same as the DAX it sits below.
    {"id": "mdax", "region": "DE", "name": "MDAX", "currency": "EUR", "yahoo": "^MDAXI",
     "weighting": "Free-float market-cap weighted, the 50 mid-caps ranking "
                  "below the DAX",
     "basis": "TOTAL RETURN — like the DAX, the MDAX reinvests dividends, so "
              "its level is not comparable with the price-return indices here"},
    {"id": "smi", "region": "CH", "name": "SMI", "currency": "CHF", "yahoo": "^SSMI",
     "weighting": "Free-float market-cap weighted (constituents capped at 18%)",
     "basis": "Price return — dividends are not included"},
    # The broad Swiss market against the SMI's 20 blue chips. `^SSHI` is the
    # only ticker Yahoo serves for it -- `SSHI.SW` and `^SPI` both 404.
    {"id": "spi", "region": "CH", "name": "Swiss All Share (SPI)", "currency": "CHF",
     "yahoo": "^SSHI",
     "weighting": "Free-float market-cap weighted, essentially every listed "
                  "Swiss company",
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
    # Carried for the equity tab's currency conversion rather than for its own
    # sake: the Hang Seng is the one tracked index whose currency had no cross
    # here, so without this it could not be shown in anything but HKD. NOK
    # needs no entry -- USD/NOK is eurnok / eurusd, both already tracked.
    {"id": "usdhkd", "name": "USD/HKD", "yahoo": "USDHKD=X"},
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
    # A SURVEY, not a breakeven, and badged as such. The practitioner standard
    # for the euro area remains the EUR HICPx zero-coupon inflation swap, which
    # still has no free feed (the ECB FM dataflow's "ILS" codes turned out to be
    # Israeli shekel), so this does not close that gap -- it measures a
    # different thing. A survey mean and a market-implied rate have different
    # biases and must never be averaged or compared as like for like.
    #
    # TENOR NOTE, which the table must carry: SPF publishes no rolling-horizon
    # series. The 1y and 2y here are CONSTRUCTED from its calendar-year point
    # forecasts and are genuinely constant horizons. The "5y" slot holds SPF's
    # published longer-term mean, whose horizon MOVES -- 5 calendar years ahead
    # in the Q3/Q4 rounds, 4 in Q1/Q2 -- so it is not the same tenor as a 5y
    # breakeven and says so in its note.
    "EZ": {"source": "ecb_spf", "basis": "HICP", "kind": "survey",
           "cadence": "quarterly",
           "note": "ECB Survey of Professional Forecasters — a survey mean, "
                   "not a market breakeven, so it is not comparable with the "
                   "US and UK figures above. 1y and 2y are constant horizons "
                   "built from SPF's calendar-year forecasts. The 5y column "
                   "holds SPF's longer-term mean, whose horizon is 5 calendar "
                   "years ahead in Q3/Q4 rounds but 4 in Q1/Q2 — a moving "
                   "tenor, shown here because it is the only long-horizon "
                   "euro-area figure published free. The euro-area inflation "
                   "swap, which would be the market-implied equivalent, is "
                   "still not available free.",
           "tenors": {"1y": "1", "2y": "2", "5y": "lt"}},
}

# DE, CH, CN, JP and NO were carried here as `unavailable` placeholder entries
# so the table could show an empty row with a reason. Removed 2026-09-21 at
# Marco's request: five permanently blank rows are five rows you learn to
# scroll past, and the same reasoning already lives in DATA-CATALOG.csv where
# it belongs. They never had stored data or a fetcher -- db/registry skipped
# any `unavailable` entry outright -- so nothing was purged with them.
#
# WHY EACH IS BLANK, kept here so the question is not re-asked:
#   DE  reads the euro area figure; there is no free euro-area ILS feed.
#   CH  PERMANENT. The Swiss Confederation issues no inflation-linked debt at
#       all, so there is no breakeven to compute. Do not re-attempt.
#   NO  PERMANENT. Same reason: Norway issues no inflation-linked debt.
#   CN  no accessible CNY inflation-linked market data.
#   JP  JGBi breakevens are not published in a free machine-readable feed.
INFLATION_EXPECTATIONS_UNSOURCED = ("DE", "CH", "CN", "JP", "NO")

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
    # CH went FRED -> Eurostat on 2026-09-13, then Eurostat -> SNB on
    # 2026-09-21. The first move was about provenance: CLVMNACSCAB1GQCH
    # self-reports "Source: Eurostat" with units "Millions of Chained 2010
    # Euros", so Swiss GDP was never Swiss-sourced -- it was Eurostat data
    # passed through FRED with a euro FX conversion layer on top, and it is the
    # exact series that produced the 2026-09-08 rebasing incident.
    #
    # The second move is about what the number MEANS. FIFA, UEFA and the IOC are
    # domiciled in Switzerland and book their licensing revenue here, so a
    # tournament quarter carries a spike that is not Swiss economic activity.
    # SECO compiles a sport-event-adjusted national accounts series precisely
    # for this and quotes it as the headline; Eurostat cannot serve it at any
    # dimension combination, because namq_10_gdp's s_adj codelist is exactly
    # {NSA, SA, CA, SCA} and has no sport-event concept. Verified 2026-09-21:
    # the Eurostat series this replaces reproduces the UNADJUSTED SNB series
    # (BBIP) quarter for quarter, and 2026-Q2 was 2.63% YoY unadjusted against
    # 2.15% adjusted.
    #
    # SNB rather than SECO's own CSV: identical numbers (BBIPS is bit-identical
    # to SECO's `cssa`), but it reuses the cube path already built for the Swiss
    # curve and Swiss CPI and answers in 8kB bounded by fromDate, where SECO's
    # file is an unbounded 4.8MB. See fetch_snb_gdp for the two cube traps.
    #
    # The level is chain-linked CHF millions (ref 2020) where the Eurostat
    # series was a 2015=100 index, so this switch REPLACED the stored history
    # via tools/purge_series.py rather than appending to it.
    "CH": {"source": "snb", "snb_measure": "BBIPS", "freq": "Q",
           "basis": "sport-event adjusted",
           "definition": "SNB gdprpq (SECO national accounts), Swiss real GDP, "
                         "chain-linked volume, seasonally, calendar AND "
                         "sport-event adjusted (CHF m, reference year 2020; "
                         "level, YoY/QoQ derived downstream)."},
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
                  "seasonally adjusted. YoY and annualised QoQ derived from the level series. "
                  "Switzerland is additionally adjusted for major sporting events: FIFA, UEFA "
                  "and the IOC are domiciled there and book their licensing revenue there, so "
                  "the unadjusted series spikes in tournament quarters on revenue that is not "
                  "Swiss economic activity.")

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
# ---------------------------------------------------------------------------
# 7c-bis. CONSTRUCTED investment-grade spreads for the euro and sterling.
#
# No free euro or sterling IG spread is published — see fetch/sources.py's
# iShares banner for the enumeration that establishes this rather than assuming
# it. What follows is built from two stated legs: an IG bond ETF's yield to
# worst, less the government curve interpolated to that ETF's own duration.
#
# It is NOT an option-adjusted spread, so it sits in the non-OAS column beside
# Germany's Bundesbank-derived one and must never be compared with the US OAS.
# Unlike Germany's, the two legs come from DIFFERENT publishers (BlackRock and
# the ECB/BoE), which this project normally refuses for a spread. It is
# accepted here only because the alternative is no euro or sterling figure at
# all, and because both legs are plain yields on a stated duration rather than
# model outputs whose methodologies could diverge invisibly. The UI says so.
#
# The euro government leg is the ECB's AAA curve (G_N_A), NOT the all-ratings
# curve (G_N_C) used for the Eurozone sovereign row. Measured 2026-09-21, AAA
# gives 93bp and all-ratings 68bp, and 93bp is where the euro IG index actually
# trades — because the all-ratings blend already contains peripheral sovereign
# risk, which is not corporate credit risk and must not net out of this.
#
# Duration is stored as its own series rather than hardcoded: it drifts as the
# index rolls, and a fixed assumption would silently decay.
CONSTRUCTED_CREDIT_SPREADS = [
    {
        "region": "EZ",
        "name": "Euro investment grade, spread to government",
        "etf": {"ticker": "IEAC", "fund": "iShares Core € Corp Bond UCITS ETF",
                "yield_series_id": "credit.EZ.ig_ytw",
                "duration_series_id": "credit.EZ.ig_duration"},
        # (years, series_id) — the curve points the duration is interpolated
        # between. IEAC sits near 4.3y, so 4y and 5y bracket it tightly.
        "government": [
            (4.0, "curve.EZ.aaa_4Y", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_4Y"),
            (5.0, "curve.EZ.aaa_5Y", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y"),
        ],
        "government_label": "ECB euro area AAA government curve",
        "note": "iShares Core € Corp Bond (IEAC) yield to worst, less the ECB "
                "AAA euro government curve at the fund's own duration. A "
                "yield-to-worst spread, not an option-adjusted one, and its "
                "two legs come from different publishers — so it is an "
                "estimate of where euro IG trades, not a published index.",
    },
    {
        "region": "UK",
        "name": "Sterling investment grade, spread to government",
        "etf": {"ticker": "SLXX", "fund": "iShares Core £ Corp Bond UCITS ETF",
                "yield_series_id": "credit.UK.ig_ytw",
                "duration_series_id": "credit.UK.ig_duration"},
        # Reuses the BoE GLC points already stored for the curve panel. SLXX
        # sits near 5.45y, so this interpolates just inside the 5y point.
        "government": [
            (5.0, "curve.UK.5Y", None),
            (10.0, "curve.UK.10Y", None),
        ],
        "government_label": "BoE nominal gilt curve",
        "note": "iShares Core £ Corp Bond (SLXX) yield to worst, less the BoE "
                "nominal gilt curve interpolated to the fund's own duration. A "
                "yield-to-worst spread, not an option-adjusted one, and its "
                "two legs come from different publishers — so it is an "
                "estimate of where sterling IG trades, not a published index.",
    },
]

# unavailable rather than pending: each was checked and closed, not skipped.
CORPORATE_SPREAD_UNAVAILABLE = {
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

# The note lives in transform/cost_of_capital.NOTE, beside the formulae it
# describes. It used to be duplicated here and had drifted badly out of date --
# it still claimed a real inflation-linked risk-free leg long after the code
# moved to the nominal 10y, and app.js quietly worked around it by hardcoding a
# different note of its own. One definition, in one place, read by both.

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
# 7d. Real short-rate differentials, from a CHF investor's seat.
#
# Replaced the FX hedging-cost table on 2026-09-21. That table was a policy-
# rate differential labelled as a hedging cost, excluding the cross-currency
# basis and using policy rates where forwards price off OIS — a floor that read
# like an estimate. See transform/real_rates.py for what replaced it and for
# the two arguable choices it makes (2y rather than policy rate, CPI rather
# than expected inflation).
# ---------------------------------------------------------------------------
REAL_RATE_HOME_REGION = "CH"

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
    # Labelled Europe, not Eurozone, and deliberately: the multiples behind it
    # are Damodaran's pan-EUROPEAN aggregate, and STOXX Europe 600 is itself
    # pan-European (17 countries, the UK and Switzerland among them). A
    # EUROZONE aggregate still does not exist and is still descoped.
    {"region": "EZ", "name": "STOXX Europe 600", "valuation_scope": "Europe",
     "cape_source": None},
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

# Which regions take their MULTIPLES from countrystats.xls. The US joined on
# 2026-09-21: the file has always carried a "United States" row on exactly the
# same median basis, and its absence here was a config gap that left the S&P
# 500 showing CAPE and nothing else. It is deliberately NOT in
# DAMODARAN_REGIONS above, which is the country-risk-premium list -- the US ERP
# comes from histimpl.xls and its rating-based CRP is 0.00 by construction.
VALUATION_MULTIPLE_REGIONS = ["US"] + DAMODARAN_REGIONS

# Europe, for the STOXX 600 row, from Damodaran's REGIONAL industry-average
# files rather than countrystats. Two things about this that must reach the UI:
#
#   1. It is EUROPE, not the euro area. That is the right match here -- STOXX
#      Europe 600 spans 17 countries including the UK and Switzerland -- but it
#      means the row is labelled "Europe" and not "Eurozone". The old
#      `descoped` reasoning stands for a EUROZONE aggregate, which still does
#      not exist; this is a different, wider aggregate that does.
#   2. It is a DIFFERENT STATISTIC from every other row. countrystats publishes
#      medians across companies; these files publish cap-weighted aggregates
#      (US median trailing P/E 22.6 against an aggregate 26.6, and an unweighted
#      mean of 57.9 which is why the plain "Trailing PE" column is not used).
#      Cap-weighted is the right analogue for an INDEX multiple, but it is not
#      comparable with the medians beside it, so the basis travels with the
#      figure -- see `basis` in the valuation payload.
#
# The aggregate row is labelled "Grand Total" in some of these files and
# "Total Market" in others, so the fetcher matches either. There is no P/S
# column in any of them, so Europe carries no P/S.
DAMODARAN_EUROPE_FILES = {
    "pe": {"file": "peEurope", "sheet": "Industry Averages", "header": 7,
           "column": "Aggregate Mkt Cap/ Trailing Net Income (only money making firms)"},
    "pb": {"file": "pbvEurope", "sheet": "Industry Averages", "header": 7,
           "column": "PBV"},
    "ev_ebitda": {"file": "vebitdaEurope", "sheet": "Industry Averages", "header": 8,
                  "column": "EV/EBITDA"},
}
DAMODARAN_EUROPE_REGION = "EZ"
VALUATION_BASIS = {
    "median": "Median across listed companies in that country (Damodaran "
              "countrystats). Not cyclically adjusted, so not comparable to "
              "the US CAPE beside it.",
    "aggregate": "Cap-weighted aggregate across listed companies in Europe "
                 "(Damodaran regional files) — a different statistic from the "
                 "medians in the other rows, and not comparable with them.",
}

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
