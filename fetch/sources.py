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
TIMEOUT = 60


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
    resp = _get(url, params={"format": "csv", "startPeriod": _start_period(years=25)})
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
CPI_UNIT_YOY = "771"   # year-on-year percent change
CPI_UNIT_INDEX = "628"  # index level


def fetch_bis_cpi(ref_area: str, unit: str = CPI_UNIT_YOY) -> pd.DataFrame | None:
    """unit=771 -> year-on-year percent; unit=628 -> index level."""
    if not ref_area:
        return None
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LONG_CPI/1.0/M.{ref_area}"
    resp = _get(url, params={"format": "csv", "startPeriod": _start_period(years=25)})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]
        if "unit_measure" not in df.columns:
            logger.warning("BIS CPI for %s: no unit_measure column", ref_area)
            return None
        sub = df[df["unit_measure"].astype(str) == str(unit)]
        if sub.empty:
            logger.warning("BIS CPI for %s: no rows for unit %s", ref_area, unit)
            return None
        return _frame(sub["time_period"], sub["obs_value"])
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
_MOF_HISTORY_URL = ("https://www.mof.go.jp/english/policy/jgbs/reference/"
                    "interest_rate/historical/jgbcme_all.csv")


def _mof_read(url: str) -> pd.DataFrame | None:
    """One MOF JGB csv. Shift-JIS (cp932), with a title row above the header."""
    resp = _get(url, headers=BROWSER_HEADERS)
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
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("MOF JGB parse failed for %s: %s", url, exc)
        return None


def _mof_table() -> pd.DataFrame | None:
    if "table" in _MOF_CACHE:
        return _MOF_CACHE["table"]
    _MOF_CACHE["table"] = None
    current = _mof_read(_MOF_URL)
    history = _mof_read(_MOF_HISTORY_URL)
    frames = [f for f in (history, current) if f is not None and not f.empty]
    if not frames:
        return None
    # Current month wins on any overlapping date.
    df = pd.concat(frames, ignore_index=True)
    date_col = df.columns[0]
    df["_d"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_d"]).drop_duplicates(subset=["_d"], keep="last")
    df = df.sort_values("_d").drop(columns=["_d"]).reset_index(drop=True)
    _MOF_CACHE["table"] = df
    return df


def fetch_mof_jgb(tenor: str) -> pd.DataFrame | None:
    """tenor is a MOF column label such as '2Y', '5Y', '10Y', '30Y'."""
    df = _mof_table()
    if df is None or tenor not in df.columns:
        if df is not None:
            logger.warning("MOF JGB: tenor %s not in columns %s", tenor, list(df.columns)[:6])
        return None
    return _frame(df[df.columns[0]], df[tenor])


# ---------------------------------------------------------------------------
# ECB Data Portal (data-api.ecb.europa.eu). Used for the euro area yield curve
# and for per-country long-term government bond yields.
#
# The euro area curve comes in two flavours: G_N_A (AAA-rated issuers only)
# and G_N_C (all government bonds). We use G_N_C — AAA tracks the Bund almost
# exactly, which made the old Eurozone row a duplicate of Germany.
# ---------------------------------------------------------------------------
def fetch_ecb(series_key: str, years: int = 15) -> pd.DataFrame | None:
    if not series_key:
        return None
    # Without startPeriod the full history comes back — ~3MB per curve tenor,
    # which intermittently blows the read timeout. The dashboard only needs
    # the recent window.
    resp = _get(f"https://data-api.ecb.europa.eu/service/data/{series_key}",
                params={"format": "csvdata", "startPeriod": _start_period(years=years)})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().upper() for c in df.columns]
        if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
            logger.warning("ECB %s: unexpected columns %s", series_key, df.columns.tolist())
            return None
        return _frame(df["TIME_PERIOD"], df["OBS_VALUE"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("ECB parse failed for %s: %s", series_key, exc)
        return None


# ---------------------------------------------------------------------------
# Bank of England GLC yield curves. One zip holds four workbooks — nominal,
# real and implied-inflation spot curves plus OIS — so it is downloaded once
# per run and every tenor read from the cached parse.
#
# Layout per workbook, sheet "4. spot curve": row index 3 carries maturities
# in years, and dated observation rows follow. This replaces the IADB series,
# which only publish 5y/10y/20y and have no 2y or 30y.
# ---------------------------------------------------------------------------
_GLC_CACHE = {}
_GLC_URL = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip"
_GLC_FILES = {
    "nominal": "GLC Nominal daily data current month.xlsx",
    "real": "GLC Real daily data current month.xlsx",
    "inflation": "GLC Inflation daily data current month.xlsx",
}


def _glc_book(which: str):
    """Returns (maturities_series, dated_rows_df) for one GLC workbook."""
    if which in _GLC_CACHE:
        return _GLC_CACHE[which]
    _GLC_CACHE[which] = None
    if "zip" not in _GLC_CACHE:
        _GLC_CACHE["zip"] = None
        resp = _get(_GLC_URL, headers=BROWSER_HEADERS)
        if resp is not None and resp.content:
            try:
                import zipfile
                _GLC_CACHE["zip"] = zipfile.ZipFile(io.BytesIO(resp.content))
            except Exception as exc:  # noqa: BLE001
                logger.warning("BoE GLC zip open failed: %s", exc)
    zf = _GLC_CACHE.get("zip")
    if zf is None:
        return None
    try:
        name = _GLC_FILES[which]
        # The real and inflation workbooks start their long-end sheet well
        # beyond 2 years, so both sheets are read and concatenated to give one
        # continuous maturity axis per date.
        books = []
        for sheet in ("3. spot, short end", "4. spot curve"):
            try:
                df = pd.read_excel(io.BytesIO(zf.read(name)), sheet_name=sheet, header=None)
            except Exception:  # noqa: BLE001 - sheet may not exist in every workbook
                continue
            maturities = pd.to_numeric(df.iloc[3], errors="coerce")
            dates = pd.to_datetime(df[0], errors="coerce", format="mixed")
            rows = df[dates.notna()].copy()
            if rows.empty:
                continue
            rows[0] = dates[dates.notna()]
            books.append((maturities, rows))
        if not books:
            return None
        _GLC_CACHE[which] = books
        return books
    except Exception as exc:  # noqa: BLE001
        logger.warning("BoE GLC parse failed for %s: %s", which, exc)
        return None


def fetch_boe_glc(which: str, tenor_years: str) -> pd.DataFrame | None:
    """which is 'nominal' | 'real' | 'inflation'; tenor_years like '2', '10', '30'."""
    books = _glc_book(which)
    if not books:
        return None
    try:
        target = float(tenor_years)
        best = None
        for maturities, rows in books:
            if not maturities.notna().any():
                continue
            col = (maturities - target).abs().idxmin()
            gap = abs(float(maturities[col]) - target)
            if best is None or gap < best[0]:
                best = (gap, rows, col)
        if best is None or best[0] > 0.3:
            logger.warning("BoE GLC %s: no column near %sy", which, tenor_years)
            return None
        _, rows, col = best
        return _frame(rows[0], rows[col])
    except Exception as exc:  # noqa: BLE001
        logger.warning("BoE GLC tenor extract failed (%s %s): %s", which, tenor_years, exc)
        return None


# ---------------------------------------------------------------------------
# Norges Bank SDMX API — Norwegian policy rate and the zero-coupon government
# curve. Semicolon-delimited CSV. The published curve stops at 10 years.
# ---------------------------------------------------------------------------
_NORGES_CURVE_CACHE = {}


def fetch_norges_curve(tenor: str) -> pd.DataFrame | None:
    """
    One tenor of the Norwegian zero-coupon government curve.

    The whole curve comes back in a single request, so it is fetched once per
    run and cached. Doing a request per tenor made the curve report "partial"
    whenever any one of them failed transiently, which is exactly what
    happened on a GitHub runner.
    """
    if not tenor:
        return None
    if "table" not in _NORGES_CURVE_CACHE:
        _NORGES_CURVE_CACHE["table"] = None
        resp = _get("https://data.norges-bank.no/api/data/GOVT_ZEROCOUPON/B.",
                    params={"format": "csv", "startPeriod": _start_period(years=25)})
        if resp is not None and resp.text:
            try:
                df = pd.read_csv(io.StringIO(resp.text), sep=";")
                # The header repeats "TENOR" for both the code and its label,
                # so columns are taken positionally rather than by name.
                cols = [c.strip().upper() for c in df.columns]
                df.columns = [f"{c}_{i}" for i, c in enumerate(cols)]
                tenor_col = next(c for c in df.columns if c.startswith("TENOR_"))
                time_col = next(c for c in df.columns if c.startswith("TIME_PERIOD"))
                val_col = next(c for c in df.columns if c.startswith("OBS_VALUE"))
                _NORGES_CURVE_CACHE["table"] = df[[tenor_col, time_col, val_col]].rename(
                    columns={tenor_col: "tenor", time_col: "date", val_col: "value"})
            except Exception as exc:  # noqa: BLE001
                logger.warning("Norges curve parse failed: %s", exc)
    table = _NORGES_CURVE_CACHE.get("table")
    if table is None:
        return None
    sub = table[table["tenor"].astype(str).str.upper() == tenor.upper()]
    if sub.empty:
        logger.warning("Norges curve: tenor %s not present", tenor)
        return None
    return _frame(sub["date"], sub["value"])


def fetch_norges(key: str) -> pd.DataFrame | None:
    """key is a dataflow path such as 'IR/B.KPRA.SD' or 'GOVT_ZEROCOUPON/B.10Y'."""
    if not key:
        return None
    resp = _get(f"https://data.norges-bank.no/api/data/{key}",
                params={"format": "csv", "startPeriod": _start_period(years=25)})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text), sep=";")
        df.columns = [c.strip().upper() for c in df.columns]
        if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
            logger.warning("Norges %s: unexpected columns %s", key, df.columns.tolist())
            return None
        return _frame(df["TIME_PERIOD"], df["OBS_VALUE"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Norges parse failed for %s: %s", key, exc)
        return None


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


# ---------------------------------------------------------------------------
# Robert Shiller's CAPE dataset (shillerdata.com, served from a wsimg blob).
# Genuine legacy .xls, so this needs xlrd rather than openpyxl. The "Data"
# sheet carries a fractional date (1871.01 = Jan 1871) and CAPE in a column
# whose header row sits several rows down, so the header is located by
# scanning rather than assumed.
# ---------------------------------------------------------------------------
SHILLER_URL = "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/downloads/ie_data.xls"


def fetch_shiller_cape() -> pd.DataFrame | None:
    resp = _get(SHILLER_URL, headers=BROWSER_HEADERS)
    if resp is None or not resp.content:
        return None
    try:
        raw = pd.read_excel(io.BytesIO(resp.content), sheet_name="Data", header=None)
        # The header spans two rows. The upper one also contains a cell reading
        # "CAPE" belonging to the Excess CAPE Yield block on the right, so match
        # the lower row precisely: column 0 is exactly "Date" there.
        hdr = None
        for i in range(min(15, len(raw))):
            if str(raw.iloc[i, 0]).strip().upper() == "DATE":
                hdr = i
                break
        if hdr is None:
            logger.warning("Shiller: could not locate header row")
            return None
        cape_col = None
        for j in range(raw.shape[1]):
            if str(raw.iloc[hdr, j]).strip().upper() == "CAPE":
                cape_col = j
                break
        if cape_col is None:
            logger.warning("Shiller: no exact CAPE column on header row %s", hdr)
            return None
        body = raw.iloc[hdr + 1:]
        # Fractional dates: 1871.01 is Jan 1871, 1871.1 is Oct 1871.
        d = pd.to_numeric(body[0], errors="coerce")
        keep = d.notna()
        d = d[keep]
        year = d.astype(int)
        month = ((d - year) * 100).round().astype(int).clip(1, 12)
        dates = pd.to_datetime(dict(year=year, month=month, day=1), errors="coerce")
        return _frame(dates, body[cape_col][keep])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shiller CAPE parse failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Damodaran (NYU Stern) implied US equity risk premium history.
# ---------------------------------------------------------------------------
DAMODARAN_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/histimpl.xls"


def fetch_damodaran_erp() -> pd.DataFrame | None:
    resp = _get(DAMODARAN_URL, headers=BROWSER_HEADERS)
    if resp is None or not resp.content:
        return None
    try:
        raw = pd.read_excel(io.BytesIO(resp.content), sheet_name=0, header=None)
        hdr = None
        for i in range(min(15, len(raw))):
            row = [str(x).strip().lower() for x in raw.iloc[i].tolist()]
            if "year" in row and any("implied" in c for c in row):
                hdr = i
                break
        if hdr is None:
            logger.warning("Damodaran: could not locate header row")
            return None
        df = raw.iloc[hdr + 1:].copy()
        df.columns = [str(x).strip() for x in raw.iloc[hdr]]
        year_col = next(c for c in df.columns if c.strip().lower() == "year")
        # Column order matters: "Implied Premium (DDM)" sits to the left of the
        # headline "Implied ERP (FCFE)" and is a different, lower measure.
        cols = [str(c) for c in df.columns]
        erp_col = next((c for c in cols if c.strip().lower() == "implied erp (fcfe)"), None)
        if erp_col is None:
            erp_col = next((c for c in cols if "implied erp" in c.lower()), None)
        if erp_col is None:
            erp_col = next(c for c in cols if "implied" in c.lower() and "premium" in c.lower())
        years = pd.to_numeric(df[year_col], errors="coerce")
        dates = pd.to_datetime(years.dropna().astype(int).astype(str) + "-12-31", errors="coerce")
        vals = pd.to_numeric(df[erp_col], errors="coerce").loc[years.dropna().index]
        # Damodaran stores these as fractions (0.0433), the dashboard wants percent.
        out = _frame(dates, vals)
        if out is not None and out["value"].abs().max() < 1.0:
            out["value"] = out["value"] * 100.0
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Damodaran ERP parse failed: %s", exc)
        return None


def fetch_etf_factsheet(ticker: str) -> dict | None:
    # iShares/SSGA fact sheets are PDFs; needs a pdfplumber step. Phase 4.
    logger.info("fetch_etf_factsheet: not yet implemented (%s)", ticker)
    return None
