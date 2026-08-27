"""
Low-level fetchers, one function per data source. Each function:
  - takes a source-specific identifier
  - returns a pandas DataFrame with columns ["date", "value"] (or None on failure)
  - never raises — logs a warning and returns None, so one bad source
    doesn't take down the whole pipeline run

All endpoints below were confirmed against live responses on 2026-08-28 — see
NETWORK.md for what each one actually returns and which are still unsourced.

A note on User-Agent, because it is genuinely counter-intuitive: there is no
single header set that works everywhere.
  - FRED sits behind Akamai, which tarpits (silently hangs, then read-timeout)
    any request whose UA claims to be a browser while the TLS fingerprint is
    Python's. Tool-shaped UAs — requests' own default, curl/* — are fine.
    So FRED must NOT get a browser UA.
  - The Bank of England and Japan's MOF do the opposite: they return an error
    page unless the UA looks like a browser.
Hence `_get` takes per-source headers and defaults to requests' own UA.
"""
from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

logger = logging.getLogger("markets_dashboard.fetch")

# Sources that reject non-browser clients (BoE, MOF). Do not apply this to FRED.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 30


def _get(url, params=None, headers=None):
    """GET with a per-source header set. headers=None uses requests' default UA."""
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a best-effort fetch
        logger.warning("Fetch failed for %s (%s): %s", url, params, exc)
        return None


def _frame(dates, values) -> pd.DataFrame | None:
    """Build the canonical [date, value] frame, dropping unparseable rows."""
    df = pd.DataFrame({"date": pd.to_datetime(dates, errors="coerce"),
                       "value": pd.to_numeric(values, errors="coerce")})
    df = df.dropna().sort_values("date").reset_index(drop=True)
    return df if not df.empty else None


# ---------------------------------------------------------------------------
# Yahoo Finance (via yfinance) — equity indices, FX, commodities.
#
# Replaces Stooq, which as of 2026-08 serves a JavaScript proof-of-work
# anti-bot challenge instead of CSV on every symbol and path, and so cannot be
# fetched headlessly at all. yfinance is used rather than raw HTTP because
# Yahoo's chart API needs a cookie+crumb handshake that the library does for us
# (a bare request to query1/query2 returns 429).
# ---------------------------------------------------------------------------
def fetch_yahoo(ticker: str) -> pd.DataFrame | None:
    if not ticker:
        return None
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="max", auto_adjust=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Yahoo fetch failed for %s: %s", ticker, exc)
        return None

    if hist is None or hist.empty or "Close" not in hist.columns:
        logger.warning("Yahoo returned no usable data for %s", ticker)
        return None

    # The most recent bar often exists with a NaN close while a session is still
    # open (seen on ^GDAXI/^SSMI/^HSI/^N225). Taking it verbatim would put a raw
    # NaN into the JSON, which is not valid JSON and breaks the frontend.
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        logger.warning("Yahoo data for %s was all-NaN closes", ticker)
        return None

    idx = hist.index
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return _frame(idx, hist["Close"].values)


# ---------------------------------------------------------------------------
# FRED — public fredgraph.csv endpoint, no API key needed.
# Confirmed: returns "observation_date,<SERIES_ID>", missing values as ".".
# ---------------------------------------------------------------------------
def fetch_fred(series_id: str) -> pd.DataFrame | None:
    if not series_id:
        return None
    # No UA override here — see the module docstring.
    resp = _get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]
        date_col = "observation_date" if "observation_date" in df.columns else "date"
        if date_col not in df.columns:
            logger.warning("FRED CSV for %s has no date column: %s", series_id, df.columns.tolist())
            return None
        value_col = series_id.lower()
        if value_col not in df.columns:
            candidates = [c for c in df.columns if c != date_col]
            if not candidates:
                return None
            value_col = candidates[0]
        return _frame(df[date_col], df[value_col])
    except Exception as exc:  # noqa: BLE001
        logger.warning("FRED CSV parse failed for %s: %s", series_id, exc)
        return None


# ---------------------------------------------------------------------------
# BIS Data Portal — central bank policy rates (CBPOL dataset), one source for
# Fed/BoE/ECB/SNB/PBoC/BoJ. SDMX v2 REST, CSV flavour.
# Confirmed working: returns TIME_PERIOD / OBS_VALUE among the SDMX columns.
# ---------------------------------------------------------------------------
def fetch_bis_policy_rate(ref_area: str) -> pd.DataFrame | None:
    if not ref_area:
        return None
    # Without startPeriod the full daily history comes back — 57MB for JP,
    # which blows the request timeout. Three years is ample for a policy rate.
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{ref_area}"
    resp = _get(url, params={"format": "csv", "startPeriod": _start_period(years=3)})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]
        date_col = next((c for c in df.columns if "time_period" in c or c == "date"), None)
        value_col = next((c for c in df.columns if "obs_value" in c or c == "value"), None)
        if not date_col or not value_col:
            logger.warning("BIS CBPOL for %s: unexpected columns %s", ref_area, df.columns.tolist())
            return None
        return _frame(df[date_col], df[value_col])
    except Exception as exc:  # noqa: BLE001
        logger.warning("BIS CBPOL parse failed for %s: %s", ref_area, exc)
        return None


def _start_period(years=3):
    """SDMX startPeriod value, used to keep BIS payloads to a sane size."""
    return (pd.Timestamp.now() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# BIS Data Portal — consumer prices (WS_LONG_CPI dataflow).
#
# This replaces FRED for CPI. FRED's OECD-sourced national CPI series
# (*CPIALLMINMEI, CPALTT01*, and the USA* variants) have all been frozen —
# they still return HTTP 200 but stop between 2021 and 2025 depending on the
# country, which is precisely the failure the staleness check exists to catch.
# BIS covers all seven dashboard regions in one dataflow, current to last month.
#
# The response mixes two unit_measure codes for the same period:
#   771 = year-on-year percent change   <- what the dashboard shows
#   628 = index level
# so filtering on unit_measure is mandatory, not cosmetic.
# ---------------------------------------------------------------------------
CPI_UNIT_YOY = "771"


def fetch_bis_cpi(ref_area: str) -> pd.DataFrame | None:
    if not ref_area:
        return None
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LONG_CPI/1.0/M.{ref_area}"
    resp = _get(url, params={"format": "csv", "startPeriod": _start_period(years=5)})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]
        if "unit_measure" not in df.columns:
            logger.warning("BIS CPI for %s: no unit_measure column", ref_area)
            return None
        yoy = df[df["unit_measure"].astype(str) == CPI_UNIT_YOY]
        if yoy.empty:
            logger.warning("BIS CPI for %s: no year-on-year rows (unit %s)", ref_area, CPI_UNIT_YOY)
            return None
        return _frame(yoy["time_period"], yoy["obs_value"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("BIS CPI parse failed for %s: %s", ref_area, exc)
        return None


# ---------------------------------------------------------------------------
# Deutsche Bundesbank — daily term structure on listed Federal securities
# (the literal single-issuer Bund curve, Svensson method). This is also the
# Eurozone benchmark curve per SPEC.md, not the ECB AAA aggregate.
#
# Response is a CSV with a ~9-line metadata preamble, then "date,value,flag"
# rows, with "." for missing observations.
# ---------------------------------------------------------------------------
def fetch_bundesbank(series_key: str) -> pd.DataFrame | None:
    if not series_key:
        return None
    resp = _get(f"https://api.statistiken.bundesbank.de/rest/download/BBSIS/{series_key}",
                params={"format": "csv", "lang": "en"})
    if resp is None or not resp.content:
        return None
    try:
        lines = resp.content.decode("utf-8-sig", errors="replace").split("\n")
        start = next((i for i, ln in enumerate(lines) if re.match(r"^\d{4}-\d{2}-\d{2},", ln)), None)
        if start is None:
            logger.warning("Bundesbank %s: no data rows found after preamble", series_key)
            return None
        df = pd.read_csv(io.StringIO("\n".join(lines[start:])), header=None,
                         usecols=[0, 1], names=["date", "value"])
        return _frame(df["date"], df["value"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bundesbank parse failed for %s: %s", series_key, exc)
        return None


# ---------------------------------------------------------------------------
# Bank of England — Interactive Statistical Database (IADB) CSV export.
# Confirmed: needs a browser UA, returns "DATE,<SERIESCODE>" with dd Mon yyyy
# dates. Covers the nominal gilt curve at 5y/10y/20y and Bank Rate.
# ---------------------------------------------------------------------------
def fetch_boe(series_code: str) -> pd.DataFrame | None:
    if not series_code:
        return None
    params = {
        "csv.x": "yes",
        "Datefrom": "01/Jan/2000",
        "Dateto": "now",
        "SeriesCodes": series_code,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    resp = _get("https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp",
                params=params, headers=BROWSER_HEADERS)
    if resp is None or not resp.text:
        return None
    try:
        text = resp.text.strip()
        if "," not in text.split("\n")[0]:
            logger.warning("BoE %s: no CSV returned (got %r)", series_code, text[:80])
            return None
        df = pd.read_csv(io.StringIO(text))
        if df.shape[1] < 2:
            return None
        return _frame(df.iloc[:, 0], df.iloc[:, 1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("BoE parse failed for %s: %s", series_code, exc)
        return None


# ---------------------------------------------------------------------------
# Japan — Ministry of Finance JGB interest rate CSV. One request returns the
# whole 1Y..40Y curve for the current month, so it is fetched once per run and
# cached rather than re-downloaded per tenor.
#
# Chosen over the JSDA OTC reference prices named in SPEC.md: JSDA publishes
# per-bond .xlsx workbooks that would need Excel parsing and tenor inference,
# where MOF publishes the curve itself. Note the file is Shift-JIS (cp932),
# not UTF-8, and line 1 is a title row.
# ---------------------------------------------------------------------------
_MOF_CACHE = {}
_MOF_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"


def _mof_table() -> pd.DataFrame | None:
    if "table" in _MOF_CACHE:
        return _MOF_CACHE["table"]
    _MOF_CACHE["table"] = None
    resp = _get(_MOF_URL, headers=BROWSER_HEADERS)
    if resp is None or not resp.content:
        return None
    try:
        text = None
        for enc in ("cp932", "shift_jis", "latin-1"):
            try:
                text = resp.content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return None
        df = pd.read_csv(io.StringIO(text), skiprows=1)
        df.columns = [str(c).strip() for c in df.columns]
        _MOF_CACHE["table"] = df
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("MOF JGB parse failed: %s", exc)
        return None


def fetch_mof_jgb(tenor: str) -> pd.DataFrame | None:
    """tenor is a MOF column label such as '2Y', '5Y', '10Y', '30Y'."""
    df = _mof_table()
    if df is None or tenor not in df.columns:
        if df is not None:
            logger.warning("MOF JGB: tenor %s not in columns %s", tenor, list(df.columns)[:6])
        return None
    return _frame(df[df.columns[0]], df[tenor])


# ---------------------------------------------------------------------------
# Still unsourced. Each returns None so the pipeline degrades to a "not yet
# wired" cell rather than shipping wrong or stale numbers. See NETWORK.md.
# ---------------------------------------------------------------------------
def fetch_snb(cube: str, params: dict | None = None) -> pd.DataFrame | None:
    # data.snb.ch exposes a documented per-cube CSV API, but the Confederation
    # bond yield series has been retired: the daily 'rendoblid' and monthly
    # 'rendoblim' cubes both still return 200 while stopping at 2025-07, with a
    # shared final publishing date of 2025-09-01. Money-market cubes on the
    # same portal (e.g. 'zimoma') are current, so this is a discontinued
    # series, not an outage, and no successor cube id responds.
    # Returning None deliberately: a visibly missing Swiss curve beats a
    # year-old one presented as today's. Needs a different institution
    # (SIX Swiss Exchange or the SNB statistical bulletin).
    logger.info("fetch_snb: no live source (cube %s discontinued/stale)", cube)
    return None


def fetch_chinabond(tenor: str) -> pd.DataFrame | None:
    # yield.chinabond.com.cn returns a JS-rendered HTML shell. queryGjqxInfo
    # serves a 956-byte shell regardless of parameters, and the yield_main
    # XHR paths (getYieldDataForWeb, queryTypeValues) are 404. No plain-HTTP
    # data endpoint found. TODO: needs either a headless browser or a
    # different institution (CFETS) — neither is worth it for one curve yet.
    logger.info("fetch_chinabond: not yet wired up (%s)", tenor)
    return None


def fetch_ecb(series_key: str) -> pd.DataFrame | None:
    # ECB SDMX REST (data-api.ecb.europa.eu). Phase 3 work — the eurozone
    # breakeven series key is still TBD.
    logger.info("fetch_ecb: not yet wired up (%s)", series_key)
    return None


def fetch_periphery_spread(country: str) -> pd.DataFrame | None:
    # France: Banque de France Webstat. Italy: Banca d'Italia Infostat.
    # Spain: Banco de España. Phase 3 work — exact series still TBD.
    logger.info("fetch_periphery_spread: not yet wired up (%s)", country)
    return None


def fetch_shiller_cape() -> pd.DataFrame | None:
    # Shiller's ie_data.xls (shillerdata.com / econ.yale.edu). Phase 4.
    logger.info("fetch_shiller_cape: not yet wired up")
    return None


def fetch_damodaran_erp() -> pd.DataFrame | None:
    # pages.stern.nyu.edu/~adamodar histimpl spreadsheet. Phase 4.
    logger.info("fetch_damodaran_erp: not yet wired up")
    return None


def fetch_etf_factsheet(ticker: str) -> dict | None:
    # iShares/SSGA fact sheets are PDFs; needs a pdfplumber step. Phase 4.
    logger.info("fetch_etf_factsheet: not yet implemented (%s)", ticker)
    return None
