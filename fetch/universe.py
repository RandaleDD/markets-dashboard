"""
Single source of truth for what the dashboard tracks: every series, which
region/category it belongs to, and which source module + source-specific
identifier fetches it.

Adding a new series or region = add an entry here. Nothing else should
hardcode ticker/series lists.
"""

REGIONS = ["US", "UK", "EZ", "DE", "CH", "CN", "JP"]

REGION_NAMES = {
    "US": "United States",
    "UK": "United Kingdom",
    "EZ": "Eurozone",
    "DE": "Germany",
    "CH": "Switzerland",
    "CN": "China",
    "JP": "Japan",
}

# ---------------------------------------------------------------------------
# 1. Equity indices — source: Yahoo Finance via yfinance.
# Every ticker below was confirmed against a live response on 2026-08-28.
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
    # tracker ETF stands in. Same convention as msci_em/bcom below.
    {"id": "csi300", "region": "CN", "name": "CSI 300 (proxy: 510300.SS ETF)", "currency": "CNY", "yahoo": "510300.SS"},
    {"id": "hangseng", "region": "CN", "name": "Hang Seng", "currency": "HKD", "yahoo": "^HSI"},
    {"id": "nikkei225", "region": "JP", "name": "Nikkei 225", "currency": "JPY", "yahoo": "^N225"},
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
]

# ---------------------------------------------------------------------------
# 3. Commodities — Yahoo Finance. Oil = Brent only (WTI deliberately dropped).
# ---------------------------------------------------------------------------
COMMODITIES = [
    {"id": "brent", "name": "Brent Crude", "yahoo": "BZ=F"},
    {"id": "natgas", "name": "Natural Gas", "yahoo": "NG=F"},
    {"id": "gold", "name": "Gold", "yahoo": "GC=F"},
    {"id": "silver", "name": "Silver", "yahoo": "SI=F"},
    {"id": "copper", "name": "Copper", "yahoo": "HG=F"},
    # No confirmed free live broad commodity index — flagged in sourcing map.
    {"id": "bcom", "name": "Bloomberg Commodity Index (proxy: DBC ETF)", "yahoo": "DBC"},
]

# ---------------------------------------------------------------------------
# 4. Central bank policy rates — BIS Data Portal CBPOL dataset (one source
# for all of these). Central bank code -> BIS reference area code.
# ---------------------------------------------------------------------------
CENTRAL_BANKS = [
    {"region": "US", "name": "Federal Reserve (Fed Funds)", "bis_ref_area": "US"},
    {"region": "UK", "name": "Bank of England (Bank Rate)", "bis_ref_area": "GB"},
    {"region": "EZ", "name": "European Central Bank (Deposit Rate)", "bis_ref_area": "XM"},
    {"region": "CH", "name": "Swiss National Bank (Policy Rate)", "bis_ref_area": "CH"},
    {"region": "CN", "name": "People's Bank of China", "bis_ref_area": "CN"},
    {"region": "JP", "name": "Bank of Japan", "bis_ref_area": "JP"},
]

# ---------------------------------------------------------------------------
# 5. Government yield curves — one entry per region, pointing at the source
# confirmed in sourcing-map.md. US via FRED fredgraph.csv (no key needed).
# Non-US sources are largely UNVERIFIED endpoint mechanics — see NETWORK.md.
# ---------------------------------------------------------------------------
YIELD_CURVES = {
    "US": {
        "source": "fred",
        "tenors": {"2Y": "DGS2", "5Y": "DGS5", "10Y": "DGS10", "30Y": "DGS30"},
    },
    "UK": {
        "source": "boe",
        "note": "Bank of England IADB nominal zero-coupon gilt yields. The "
                "IADB short/medium/long codes cover 5y/10y/20y only — there is "
                "no 2y or 30y series in that set, so those two tenors stay "
                "blank until the BoE GLC yield-curve workbook is parsed.",
        "tenors": {"2Y": None, "5Y": "IUDSNZC", "10Y": "IUDMNZC", "30Y": None},
    },
    "DE": {
        "source": "bundesbank",
        "note": "Deutsche Bundesbank daily term structure on listed Federal "
                "securities (Svensson). Literal single-issuer Bund curve.",
        "tenors": {
            "2Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R02XX.R.A.A._Z._Z.A",
            "5Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R05XX.R.A.A._Z._Z.A",
            "10Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A",
            "30Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R30XX.R.A.A._Z._Z.A",
        },
    },
    # SPEC.md: the Bund curve *is* the Eurozone benchmark shown, so EZ mirrors
    # DE rather than fetching the ECB AAA aggregate. Same keys, fetched once
    # and reused by the pipeline.
    "EZ": {
        "source": "bundesbank",
        "note": "Mirrors the German Bund curve — the Eurozone benchmark per SPEC.md.",
        "mirrors": "DE",
        "tenors": {
            "2Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R02XX.R.A.A._Z._Z.A",
            "5Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R05XX.R.A.A._Z._Z.A",
            "10Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A",
            "30Y": "D.I.ZST.ZI.EUR.S1311.B.A604.R30XX.R.A.A._Z._Z.A",
        },
    },
    "CH": {
        "source": "snb",
        "note": "SNB discontinued the Confederation bond yield series: both "
                "the daily 'rendoblid' and monthly 'rendoblim' cubes still "
                "respond but stop at 2025-07, sharing a final publishing date "
                "of 2025-09-01 (money-market cubes on the same portal remain "
                "current, so this is the series being retired, not an outage). "
                "Left unsourced rather than showing year-old yields as today's.",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
    },
    "CN": {
        "source": "chinabond",
        "note": "ChinaBond English portal (yield.chinabond.com.cn) is "
                "JS-rendered; no plain-HTTP data endpoint confirmed yet.",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
    },
    "JP": {
        "source": "mof",
        "note": "Japan Ministry of Finance JGB interest rate CSV — the whole "
                "1Y-40Y curve in one file (chosen over JSDA's per-bond xlsx).",
        "tenors": {"2Y": "2Y", "5Y": "5Y", "10Y": "10Y", "30Y": "30Y"},
    },
}

# Eurozone periphery spread panel vs. Bund — institution confirmed, exact
# series not yet pinned down (see sourcing-map.md "first-week tasks").
EUROZONE_SPREAD_PANEL = [
    {"country": "France", "institution": "Banque de France (Webstat, source category 'Banque de France, MTS France')"},
    {"country": "Italy", "institution": "Banca d'Italia (Infostat database)"},
    {"country": "Spain", "institution": "Banco de España (Spanish securities markets statistics)"},
]

# ---------------------------------------------------------------------------
# 6. Inflation — FRED for CPI hub + US breakevens; BoE for UK breakevens;
# ECB for eurozone breakevens (exact series TBD).
# ---------------------------------------------------------------------------
INFLATION_CPI = {
    # BIS WS_LONG_CPI, not FRED: every FRED OECD-sourced national CPI series
    # is frozen (UK/DE stop 2025-03, CH/CN 2025-04, JP 2021-06, and even the
    # US CPALTT01 variant stops 2024-12). BIS covers all seven regions in one
    # dataflow and is current to the prior month. Values are already
    # year-on-year percent, so no index arithmetic is needed.
    "US": {"source": "bis", "ref_area": "US", "note": "FRED CPIAUCSL remains available for US core/PCE detail."},
    "UK": {"source": "bis", "ref_area": "GB"},
    "EZ": {"source": "bis", "ref_area": "XM"},
    "DE": {"source": "bis", "ref_area": "DE"},
    "CH": {"source": "bis", "ref_area": "CH"},
    "CN": {"source": "bis", "ref_area": "CN"},
    "JP": {"source": "bis", "ref_area": "JP"},
}

BREAKEVEN_INFLATION = {
    "US": {"source": "fred", "5y": "T5YIE", "10y": "T10YIE", "5y5y_fwd": "T5YIFR"},
    "UK": {"source": "boe", "note": "BoE 'Inflation implied forward' series (RIMF05/RIMF10/RIMF20). Exact download format TBD."},
    "EZ": {"source": "ecb", "note": "ECB Data Portal 'Inflation-linked' category confirmed to exist; exact SDW series key TBD — query via sdw-wsrest.ecb.europa.eu."},
}

REAL_YIELDS = {
    "US": {"source": "fred", "10y": "DFII10"},
    "UK": {"source": "boe", "note": "BoE real gilt yield curve, same statistics page as nominal."},
    # DE/EZ: derive as nominal (Bundesbank) minus breakeven (ECB) once both are wired.
}

# ---------------------------------------------------------------------------
# 7. GDP growth — FRED hub (OECD-sourced for non-US).
# ---------------------------------------------------------------------------
GDP_GROWTH = {
    # FRED's NAEXKP01*Q657S growth series are discontinued, so these are real
    # GDP *level* series and the pipeline derives year-on-year growth from
    # them. Doing it uniformly also makes the regions comparable, which mixing
    # a US QoQ-annualised rate with everyone else's YoY would not.
    "US": {"source": "fred", "series": "GDPC1", "freq": "Q"},
    "UK": {"source": "fred", "series": "NGDPRSAXDCGBQ", "freq": "Q"},
    "EZ": {"source": "fred", "series": "CLVMNACSCAB1GQEA19", "freq": "Q"},
    "DE": {"source": "fred", "series": "CLVMNACSCAB1GQDE", "freq": "Q"},
    "CH": {"source": "fred", "series": "CLVMNACSCAB1GQCH", "freq": "Q"},
    "JP": {"source": "fred", "series": "JPNRGDPEXP", "freq": "Q"},
    # Only an annual real-GDP series is available for China on FRED; the
    # quarterly OECD one is discontinued. Cadence is set accordingly so the
    # freshness check doesn't flag normal annual publication lag as stale.
    "CN": {"source": "fred", "series": "NGDPRXDCCNA", "freq": "A", "cadence": "annual"},
}

# ---------------------------------------------------------------------------
# 8. Equity valuation metrics — US solid (Shiller/Damodaran), non-US
# realistically limited to monthly ETF/index fact sheets (P/E, P/B, div
# yield only). See sourcing-map.md for the full honest assessment.
# ---------------------------------------------------------------------------
VALUATION_PROXIES = [
    {"region": "US", "name": "S&P 500", "cape_source": "shiller", "etf_proxy": None},
    {"region": "UK", "name": "FTSE 100", "cape_source": None, "etf_proxy": "ewu.us"},
    {"region": "EZ", "name": "STOXX 600", "cape_source": None, "etf_proxy": "ezu.us"},
    {"region": "DE", "name": "DAX", "cape_source": None, "etf_proxy": "ewg.us"},
    {"region": "CH", "name": "SMI", "cape_source": None, "etf_proxy": "ewl.us"},
    {"region": "CN", "name": "CSI 300 / Hang Seng", "cape_source": None, "etf_proxy": "mchi.us"},
    {"region": "JP", "name": "Nikkei 225", "cape_source": None, "etf_proxy": "ewj.us"},
]
