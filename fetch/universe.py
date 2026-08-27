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
# 1. Equity indices — source: Stooq (primary) / yfinance (fallback)
# Stooq symbol format confirmed against Stooq's own documentation as of the
# last time this file was authored; NOT live-tested from this environment
# (see NETWORK.md) — verify on first real pipeline run.
# ---------------------------------------------------------------------------
EQUITY_INDICES = [
    {"id": "sp500", "region": "US", "name": "S&P 500", "currency": "USD", "stooq": "^spx"},
    {"id": "nasdaq100", "region": "US", "name": "Nasdaq 100", "currency": "USD", "stooq": "^ndq"},
    {"id": "russell2000", "region": "US", "name": "Russell 2000", "currency": "USD", "stooq": "^rut"},
    {"id": "ftse100", "region": "UK", "name": "FTSE 100", "currency": "GBP", "stooq": "^ftm"},
    {"id": "stoxx600", "region": "EZ", "name": "STOXX Europe 600", "currency": "EUR", "stooq": "^stoxx"},
    {"id": "dax", "region": "DE", "name": "DAX", "currency": "EUR", "stooq": "^dax"},
    {"id": "smi", "region": "CH", "name": "SMI", "currency": "CHF", "stooq": "^smi"},
    {"id": "csi300", "region": "CN", "name": "CSI 300", "currency": "CNY", "stooq": "000300.sh"},
    {"id": "hangseng", "region": "CN", "name": "Hang Seng", "currency": "HKD", "stooq": "^hsi"},
    {"id": "nikkei225", "region": "JP", "name": "Nikkei 225", "currency": "JPY", "stooq": "^nkx"},
    # Secondary tier
    {"id": "msci_em", "region": "EM", "name": "MSCI EM (proxy: EEM ETF)", "currency": "USD", "stooq": "eem.us"},
]

VOLATILITY_INDICES = [
    {"id": "vix", "region": "US", "name": "VIX", "stooq": "^vix"},
    {"id": "vstoxx", "region": "EZ", "name": "VSTOXX", "stooq": None, "note": "No confirmed free daily source found — leave blank until sourced."},
]

# ---------------------------------------------------------------------------
# 2. Currencies — Stooq
# ---------------------------------------------------------------------------
CURRENCIES = [
    {"id": "dxy", "name": "US Dollar Index (DXY)", "stooq": "usdx.f"},
    {"id": "eurusd", "name": "EUR/USD", "stooq": "eurusd"},
    {"id": "gbpusd", "name": "GBP/USD", "stooq": "gbpusd"},
    {"id": "usdjpy", "name": "USD/JPY", "stooq": "usdjpy"},
    {"id": "usdchf", "name": "USD/CHF", "stooq": "usdchf"},
    {"id": "eurchf", "name": "EUR/CHF", "stooq": "eurchf"},
    {"id": "usdcny", "name": "USD/CNY", "stooq": "usdcny"},
]

# ---------------------------------------------------------------------------
# 3. Commodities — Stooq. Oil = Brent only (WTI deliberately dropped).
# ---------------------------------------------------------------------------
COMMODITIES = [
    {"id": "brent", "name": "Brent Crude", "stooq": "cb.f"},
    {"id": "natgas", "name": "Natural Gas", "stooq": "ng.f"},
    {"id": "gold", "name": "Gold", "stooq": "xauusd"},
    {"id": "silver", "name": "Silver", "stooq": "xagusd"},
    {"id": "copper", "name": "Copper", "stooq": "hg.f"},
    # No confirmed free live broad commodity index — flagged in sourcing map.
    {"id": "bcom", "name": "Bloomberg Commodity Index (proxy: DBC ETF)", "stooq": "dbc.us"},
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
        "note": "Bank of England yield-curve statistics or UK DMO daily gilt "
                "export (dmo.gov.uk/data/ExportReport?reportCode=D4H). "
                "Exact query params TBD on first real run.",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
    },
    "DE": {
        "source": "bundesbank",
        "note": "Deutsche Bundesbank 'Daily term structure on listed Federal "
                "securities' (literal Bund curve). Bundesbank publishes a "
                "public time-series database (SDMX-style); exact series keys "
                "TBD on first real run.",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
    },
    "CH": {
        "source": "snb",
        "note": "SNB Data Portal, 'Yields on bond issues' cube "
                "(data.snb.ch/en/topics/ziredev/cube/rendoblid).",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
    },
    "CN": {
        "source": "chinabond",
        "note": "ChinaBond English portal (yield.chinabond.com.cn) CGB yield curve.",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
    },
    "JP": {
        "source": "jsda",
        "note": "Japan Securities Dealers Association reference OTC bond "
                "yields (jsda.or.jp/en/statistics/bonds/prices).",
        "tenors": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
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
    "US": {"source": "fred", "headline": "CPIAUCSL", "core": "CPILFESL", "core_pce": "PCEPILFE"},
    "UK": {"source": "fred", "headline": "GBRCPIALLMINMEI", "core": None},
    "EZ": {"source": "fred", "headline": "CP0000EZ19M086NEST", "core": None},
    "DE": {"source": "fred", "headline": "DEUCPIALLMINMEI", "core": None},
    "CH": {"source": "fred", "headline": "CHECPIALLMINMEI", "core": None},
    "CN": {"source": "fred", "headline": "CHNCPIALLMINMEI", "core": None},
    "JP": {"source": "fred", "headline": "JPNCPIALLMINMEI", "core": None},
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
    "US": {"source": "fred", "series": "A191RL1Q225SBEA"},  # real GDP, QoQ annualized
    "UK": {"source": "fred", "series": "NAEXKP01GBQ657S"},
    "EZ": {"source": "fred", "series": "NAEXKP01EZQ657S"},
    "DE": {"source": "fred", "series": "NAEXKP01DEQ657S"},
    "CH": {"source": "fred", "series": "NAEXKP01CHQ657S"},
    "CN": {"source": "fred", "series": "NAEXKP01CNQ657S"},
    "JP": {"source": "fred", "series": "NAEXKP01JPQ657S"},
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
