"""
Single source of truth for what the dashboard tracks: every series, which
region/category it belongs to, and which source module + source-specific
identifier fetches it.

Adding a new series or region = add an entry here. Nothing else should
hardcode ticker/series lists.

Every identifier below was confirmed against a live response — see NETWORK.md
for each endpoint's quirks.
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
EQUITY_INDICES = [
    {"id": "sp500", "region": "US", "name": "S&P 500", "currency": "USD", "yahoo": "^GSPC"},
    {"id": "nasdaq100", "region": "US", "name": "Nasdaq 100", "currency": "USD", "yahoo": "^NDX"},
    {"id": "russell2000", "region": "US", "name": "Russell 2000", "currency": "USD", "yahoo": "^RUT"},
    {"id": "ftse100", "region": "UK", "name": "FTSE 100", "currency": "GBP", "yahoo": "^FTSE"},
    {"id": "stoxx600", "region": "EZ", "name": "STOXX Europe 600", "currency": "EUR", "yahoo": "^STOXX"},
    {"id": "dax", "region": "DE", "name": "DAX", "currency": "EUR", "yahoo": "^GDAXI"},
    {"id": "smi", "region": "CH", "name": "SMI", "currency": "CHF", "yahoo": "^SSMI"},
    # Yahoo serves the CSI 300 index itself (000300.SS / 399300.SZ) with only
    # 1d/5d of history — no daily series — so the mainland-listed, CNY-priced
    # tracker ETF stands in. Same convention as msci_em/bcom.
    {"id": "csi300", "region": "CN", "name": "CSI 300 (proxy: 510300.SS ETF)", "currency": "CNY", "yahoo": "510300.SS"},
    {"id": "hangseng", "region": "CN", "name": "Hang Seng", "currency": "HKD", "yahoo": "^HSI"},
    {"id": "nikkei225", "region": "JP", "name": "Nikkei 225", "currency": "JPY", "yahoo": "^N225"},
    {"id": "osebx", "region": "NO", "name": "OSEBX (Oslo Børs)", "currency": "NOK", "yahoo": "OSEBX.OL"},
    # Secondary tier
    {"id": "msci_em", "region": "EM", "name": "MSCI EM (proxy: EEM ETF)", "currency": "USD", "yahoo": "EEM"},
]

VOLATILITY_INDICES = [
    {"id": "vix", "region": "US", "name": "VIX", "yahoo": "^VIX"},
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
    {"id": "brent", "name": "Brent Crude", "yahoo": "BZ=F",
     "exchange": "ICE", "contract": "Brent Crude, front month", "unit": "USD/bbl"},
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
# 4. Central bank policy rates — BIS CBPOL for most, Norges Bank for Norway.
# ---------------------------------------------------------------------------
CENTRAL_BANKS = [
    {"region": "US", "name": "Federal Reserve (Fed Funds)", "source": "bis", "bis_ref_area": "US"},
    {"region": "UK", "name": "Bank of England (Bank Rate)", "source": "bis", "bis_ref_area": "GB"},
    {"region": "EZ", "name": "European Central Bank (Deposit Rate)", "source": "bis", "bis_ref_area": "XM"},
    # Germany's policy rate IS the ECB's — mirrored rather than shown blank.
    {"region": "DE", "name": "European Central Bank (Deposit Rate)", "source": "bis", "bis_ref_area": "XM"},
    {"region": "CH", "name": "Swiss National Bank (Policy Rate)", "source": "bis", "bis_ref_area": "CH"},
    {"region": "CN", "name": "People's Bank of China", "source": "bis", "bis_ref_area": "CN"},
    {"region": "JP", "name": "Bank of Japan", "source": "bis", "bis_ref_area": "JP"},
    {"region": "NO", "name": "Norges Bank (Key Policy Rate)", "source": "norges", "norges_key": "IR/B.KPRA.SD"},
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
        "source": "fred", "cadence": "monthly",
        "note": "SNB retired its Confederation bond yield cubes in 2025 "
                "(see NETWORK.md). Only a monthly 10y OECD series remains, "
                "which lags roughly two months — flagged in the UI so it is "
                "never read as a daily quote.",
        "lagged": True,
        "tenors": {"2Y": None, "5Y": None, "10Y": "IRLTLT01CHM156N", "30Y": None},
    },
    "CN": {
        "source": "chinabond", "cadence": "daily",
        "note": "ChinaBond is JS-rendered and CFETS (chinamoney.com.cn) "
                "rejects all programmatic access. No free source found.",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
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
# 6. Inflation — BIS WS_LONG_CPI. One dataflow covers every region and returns
# both the YoY rate (unit 771) and the index level (unit 628) in one response,
# so annualised QoQ is derived from the same fetch.
# ---------------------------------------------------------------------------
INFLATION_CPI = {
    "US": {"source": "bis", "ref_area": "US"},
    "UK": {"source": "bis", "ref_area": "GB"},
    "EZ": {"source": "bis", "ref_area": "XM"},
    "DE": {"source": "bis", "ref_area": "DE"},
    "CH": {"source": "bis", "ref_area": "CH"},
    "CN": {"source": "bis", "ref_area": "CN"},
    "JP": {"source": "bis", "ref_area": "JP"},
    "NO": {"source": "bis", "ref_area": "NO"},
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
    "UK": {"source": "fred", "series": "NGDPRSAXDCGBQ", "freq": "Q"},
    "EZ": {"source": "fred", "series": "CLVMNACSCAB1GQEA19", "freq": "Q"},
    "DE": {"source": "fred", "series": "CLVMNACSCAB1GQDE", "freq": "Q"},
    "CH": {"source": "fred", "series": "CLVMNACSCAB1GQCH", "freq": "Q"},
    "JP": {"source": "fred", "series": "JPNRGDPEXP", "freq": "Q"},
    "NO": {"source": "fred", "series": "CLVMNACSCAB1GQNO", "freq": "Q"},
    # Only an annual real-GDP series exists for China on FRED, so YoY only.
    "CN": {"source": "fred", "series": "NGDPRXDCCNA", "freq": "A", "cadence": "annual"},
}
GDP_DEFINITION = ("Real (chain-linked volume), national currency, not PPP, "
                  "seasonally adjusted. YoY and annualised QoQ derived from the level series.")

# ---------------------------------------------------------------------------
# 8. Equity valuation + equity risk premium.
# ---------------------------------------------------------------------------
VALUATION_PROXIES = [
    {"region": "US", "name": "S&P 500", "cape_source": "shiller", "etf_proxy": None},
    {"region": "UK", "name": "FTSE 100", "cape_source": None, "etf_proxy": "ewu.us"},
    {"region": "EZ", "name": "STOXX 600", "cape_source": None, "etf_proxy": "ezu.us"},
    {"region": "DE", "name": "DAX", "cape_source": None, "etf_proxy": "ewg.us"},
    {"region": "CH", "name": "SMI", "cape_source": None, "etf_proxy": "ewl.us"},
    {"region": "CN", "name": "CSI 300 / Hang Seng", "cape_source": None, "etf_proxy": "mchi.us"},
    {"region": "JP", "name": "Nikkei 225", "cape_source": None, "etf_proxy": "ewj.us"},
    {"region": "NO", "name": "OSEBX", "cape_source": None, "etf_proxy": "enor.us"},
]

# Chart lookback windows offered by the frontend.
CHART_PERIODS = ["3M", "YTD", "1Y", "2Y", "3Y", "5Y"]
