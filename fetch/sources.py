"""
Low-level fetchers, one function per data source. Each function:
  - takes a source-specific identifier
  - returns a pandas DataFrame with columns ["date", "value"] (or None on failure)
  - never raises — logs a warning and returns None, so one bad source
    doesn't take down the whole pipeline run

All endpoints below were confirmed against live responses on 2026-08-28 — see
SPEC.md's endpoint appendix for the traps that are not per-series.

A note on User-Agent, because it is genuinely counter-intuitive: there is no
single header set that works everywhere.
  - FRED sits behind Akamai, which tarpits (silently hangs, then read-timeout)
    any request whose UA claims to be a browser while the TLS fingerprint is
    Python's. Tool-shaped UAs — requests' own default, curl/* — are fine.
    So FRED must NOT get a browser UA.
  - The Bank of England and Japan's MOF do the opposite: they return an error
    page unless the UA looks like a browser.
Hence `_get` takes per-source headers and defaults to requests' own UA.

Every fetcher takes an optional `start=` (an ISO date). It is a *hint*, not a
contract: sources with a bounded-query parameter (FRED's `cosd`, SDMX's
`startPeriod`, yfinance's `start`) narrow the request to it, which is what
makes the daily incremental run cheap. Sources without one (Bundesbank, which
accepts `startPeriod` and ignores it; the BoE workbooks; MOF; Shiller;
Damodaran) return their whole small snapshot regardless. Callers must not
assume the returned frame begins at `start` -- `db/ingest.py` filters against
the watermark itself and lets ON CONFLICT DO NOTHING discard the rest.
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
def fetch_yahoo(ticker: str, start: str | None = None) -> pd.DataFrame | None:
    if not ticker:
        return None
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        hist = (tk.history(start=start, auto_adjust=False) if start
                else tk.history(period="max", auto_adjust=False))
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
def fetch_fred(series_id: str, start: str | None = None) -> pd.DataFrame | None:
    if not series_id:
        return None
    # No UA override here — see the module docstring.
    params = {"id": series_id}
    if start:
        params["cosd"] = start  # fredgraph's own "chart observation start date"
    resp = _get("https://fred.stlouisfed.org/graph/fredgraph.csv", params=params)
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
def fetch_bis_policy_rate(ref_area: str, start: str | None = None) -> pd.DataFrame | None:
    if not ref_area:
        return None
    # Without startPeriod the full daily history comes back — 57MB for JP,
    # which blows the request timeout. Three years is ample for a policy rate.
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{ref_area}"
    resp = _get(url, params={"format": "csv", "startPeriod": start or _start_period(years=25)})
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


def fetch_bis_cpi(ref_area: str, unit: str = CPI_UNIT_YOY,
                  start: str | None = None) -> pd.DataFrame | None:
    """unit=771 -> year-on-year percent; unit=628 -> index level."""
    if not ref_area:
        return None
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LONG_CPI/1.0/M.{ref_area}"
    resp = _get(url, params={"format": "csv", "startPeriod": start or _start_period(years=25)})
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
def fetch_bundesbank(series_key: str, start: str | None = None) -> pd.DataFrame | None:
    """
    `start` is accepted and ignored on purpose. Measured 2026-08-29: this
    endpoint returns the identical 10,620-row history (1997 onward) whether or
    not `startPeriod` is passed, so it is a snapshot source in practice. The
    payload is small and the ingest step discards what it already holds.
    """
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
def fetch_ecb(series_key: str, years: int = 15, start: str | None = None) -> pd.DataFrame | None:
    if not series_key:
        return None
    # Without startPeriod the full history comes back — ~3MB per curve tenor,
    # which intermittently blows the read timeout. The dashboard only needs
    # the recent window.
    resp = _get(f"https://data-api.ecb.europa.eu/service/data/{series_key}",
                params={"format": "csvdata", "startPeriod": start or _start_period(years=years)})
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
_GLC_BASE = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/"
_GLC_URL = _GLC_BASE + "latest-yield-curve-data.zip"
_GLC_FILES = {
    "nominal": "GLC Nominal daily data current month.xlsx",
    "real": "GLC Real daily data current month.xlsx",
    "inflation": "GLC Inflation daily data current month.xlsx",
}
# The one-time deep archives. Roughly 89MB across the three, which is why they
# are pulled by bootstrap.py ONCE and never by the daily run -- see
# SPEC.md, "Why the database is committed". Each zip holds one workbook per era
# (1979-1984, 1985-1989, ... 2025 to present).
_GLC_ARCHIVES = {
    "nominal": _GLC_BASE + "glcnominalddata.zip",
    "real": _GLC_BASE + "glcrealddata.zip",
    "inflation": _GLC_BASE + "glcinflationddata.zip",
}


def _glc_spot_sheets(xl_names) -> list:
    """
    The spot-curve sheets, whatever this era's workbook calls them.

    Sheet naming is NOT stable across the archive: workbooks up to 2024 use
    "3. nominal spot, short end" / "4. nominal spot curve", while 2025-to-
    present and the current-month file use "3. spot, short end" /
    "4. spot curve". Matching on the "N. ... spot ..." shape covers both, and
    both sheets are needed because the real and inflation books start their
    long-end sheet well beyond 2 years.
    """
    return [n for n in xl_names
            if n.strip()[:2] in ("3.", "4.") and "spot" in n.lower()]


def _glc_parse(book_bytes: bytes) -> list:
    """[(maturities_row, dated_rows_df), ...] for every spot sheet in a workbook."""
    out = []
    xl = pd.ExcelFile(io.BytesIO(book_bytes))
    for sheet in _glc_spot_sheets(xl.sheet_names):
        try:
            df = xl.parse(sheet_name=sheet, header=None)
        except Exception:  # noqa: BLE001 - a malformed sheet must not lose the others
            continue
        maturities = pd.to_numeric(df.iloc[3], errors="coerce")
        dates = pd.to_datetime(df[0], errors="coerce", format="mixed")
        rows = df[dates.notna()].copy()
        if rows.empty:
            continue
        rows[0] = dates[dates.notna()]
        out.append((maturities, rows))
    return out


def _glc_book(which: str, archive: bool = False):
    """
    Returns [(maturities, dated_rows), ...] for one GLC curve.

    archive=False fetches the small current-month workbook (the daily path).
    archive=True fetches the multi-decade zip -- bootstrap only.
    """
    ck = (which, archive)
    if ck in _GLC_CACHE:
        return _GLC_CACHE[ck]
    _GLC_CACHE[ck] = None
    url = _GLC_ARCHIVES[which] if archive else _GLC_URL
    zk = ("zip", url)
    if zk not in _GLC_CACHE:
        _GLC_CACHE[zk] = None
        if archive:
            logger.info("BoE GLC: downloading the one-time %s archive (~25-39MB)", which)
        resp = _get(url, headers=BROWSER_HEADERS)
        if resp is not None and resp.content:
            try:
                import zipfile
                _GLC_CACHE[zk] = zipfile.ZipFile(io.BytesIO(resp.content))
            except Exception as exc:  # noqa: BLE001
                logger.warning("BoE GLC zip open failed (%s): %s", url, exc)
    zf = _GLC_CACHE.get(zk)
    if zf is None:
        return None
    try:
        if archive:
            # Every era workbook in the zip, oldest first.
            names = sorted(n for n in zf.namelist() if n.lower().endswith(".xlsx"))
        else:
            names = [_GLC_FILES[which]]
        books = []
        for name in names:
            try:
                books.extend(_glc_parse(zf.read(name)))
            except Exception as exc:  # noqa: BLE001
                logger.warning("BoE GLC workbook %s failed: %s", name, exc)
        if not books:
            return None
        _GLC_CACHE[ck] = books
        return books
    except Exception as exc:  # noqa: BLE001
        logger.warning("BoE GLC parse failed for %s: %s", which, exc)
        return None


def fetch_boe_glc(which: str, tenor_years: str, archive: bool = False) -> pd.DataFrame | None:
    """
    which is 'nominal' | 'real' | 'inflation'; tenor_years like '2', '10', '30'.

    archive=True reads the deep multi-decade zip instead of the current-month
    workbook. Only bootstrap.py passes it.
    """
    books = _glc_book(which, archive)
    if not books:
        return None
    try:
        target = float(tenor_years)
        # One workbook per era in the archive, and two sheets per workbook, so
        # the tenor is collected from EVERY block that carries it rather than
        # from the single best-matching one -- picking one block would silently
        # return a single era's slice of the history.
        parts = []
        for maturities, rows in books:
            if not maturities.notna().any():
                continue
            col = (maturities - target).abs().idxmin()
            if abs(float(maturities[col]) - target) > 0.3:
                continue
            part = _frame(rows[0], rows[col])
            if part is not None:
                parts.append(part)
        if not parts:
            logger.warning("BoE GLC %s: no column near %sy", which, tenor_years)
            return None
        df = pd.concat(parts, ignore_index=True)
        # Later blocks win on an overlapping date (the short-end sheet and the
        # long-end sheet both carry ~2y-5y, and eras overlap at their seams).
        df = df.drop_duplicates(subset=["date"], keep="last")
        return _frame(df["date"], df["value"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("BoE GLC tenor extract failed (%s %s): %s", which, tenor_years, exc)
        return None


# ---------------------------------------------------------------------------
# Norges Bank SDMX API — Norwegian policy rate and the zero-coupon government
# curve. Semicolon-delimited CSV. The published curve stops at 10 years.
# ---------------------------------------------------------------------------
_NORGES_CURVE_CACHE = {}


def fetch_norges_curve(tenor: str, start: str | None = None) -> pd.DataFrame | None:
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
                    params={"format": "csv", "startPeriod": start or _start_period(years=25)})
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


# ---------------------------------------------------------------------------
# ONS — UK monthly GDP, from the Office for National Statistics' own time
# series API. Replaces FRED's quarterly NGDPRSAXDCGBQ per DATA-CATALOG.csv.
#
# Two genuine upgrades, both measured 2026-08-29: monthly rather than
# quarterly, and two quarters fresher (ONS carried 2026-06 while FRED's UK
# series stopped at 2026-Q1).
#
# The series is ONS's monthly GVA index. That is what "monthly GDP" IS in the
# UK — ONS estimates it on the output approach and publishes it under the GVA
# label — so the description must say so rather than calling it plain GDP.
# History starts 1997-01; FRED's quarterly series went back to 1955, so this
# trades ~40 years of low-frequency history for frequency and freshness.
# ---------------------------------------------------------------------------
ONS_BASE = "https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries"

_ONS_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
               "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def fetch_ons_timeseries(series_code: str, dataset: str,
                         start: str | None = None) -> pd.DataFrame | None:
    """
    One ONS time series, e.g. series_code='ecy2', dataset='mgdp'.

    `start` is accepted and ignored: the endpoint has no windowing parameter
    and the whole series is a ~70KB JSON document.

    Returns the monthly observations. ONS dates read "1997 JAN", so they are
    parsed against an explicit month map rather than a locale-dependent format.
    """
    if not series_code or not dataset:
        return None
    resp = _get(f"{ONS_BASE}/{series_code.lower()}/{dataset.lower()}/data",
                headers={**BROWSER_HEADERS, "Accept": "application/json"})
    if resp is None or not resp.content:
        return None
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ONS %s/%s: response was not JSON: %s", series_code, dataset, exc)
        return None
    months = payload.get("months") or []
    if not months:
        logger.warning("ONS %s/%s: no monthly observations in response", series_code, dataset)
        return None
    dates, values = [], []
    for row in months:
        parts = str(row.get("date", "")).split()
        if len(parts) != 2 or parts[1].upper() not in _ONS_MONTHS:
            continue
        try:
            dates.append(pd.Timestamp(year=int(parts[0]), month=_ONS_MONTHS[parts[1].upper()], day=1))
        except (TypeError, ValueError):
            continue
        values.append(row.get("value"))
    return _frame(dates, values)


# ---------------------------------------------------------------------------
# Eurostat — euro area real GDP levels, replacing FRED's CLVMNACSCAB1GQEA19
# per DATA-CATALOG.csv.
#
# NOT the catalog's named dataset. teina011 was checked first (2026-08-29) and
# carries only percentage CHANGES over a rolling 12 quarters — no level series
# at all. The pipeline derives every region's growth from levels on purpose
# (FRED's OECD growth series are discontinued; see SPEC.md's endpoint appendix), and 12 points
# cannot answer a percentile window either. namq_10_gdp is the quarterly
# national accounts behind it and gives the level, so it is used instead.
#
# Second, independent reason the switch is right: this is EA20, the current
# euro-area membership. FRED's series is EA19, which has been superseded since
# Croatia joined in 2023.
#
# Response is JSON-stat: `value` is a sparse {flat_index: number} map and the
# time dimension carries {period_label: index}, so the two are joined by index
# rather than by position.
# ---------------------------------------------------------------------------
EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"


def fetch_eurostat(dataset: str, filters: dict | None = None,
                   start: str | None = None) -> pd.DataFrame | None:
    """
    dataset e.g. 'namq_10_gdp'; filters e.g. {"geo": "EA20", "unit": "CLV15_MEUR"}.

    `start` maps to Eurostat's own `sinceTimePeriod`, so this IS a bounded
    source for the daily incremental run.
    """
    if not dataset:
        return None
    params = {"format": "JSON", "lang": "EN", **(filters or {})}
    if start:
        params["sinceTimePeriod"] = str(start)[:7]
    resp = _get(f"{EUROSTAT_BASE}/{dataset}", params=params)
    if resp is None or not resp.content:
        return None
    try:
        payload = resp.json()
        time_index = payload["dimension"]["time"]["category"]["index"]
        values = payload["value"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eurostat %s: unexpected payload: %s", dataset, exc)
        return None
    by_position = {position: label for label, position in time_index.items()}
    dates, nums = [], []
    for flat_index, value in values.items():
        label = by_position.get(int(flat_index))
        if label is None:
            continue
        dates.append(_eurostat_period(label))
        nums.append(value)
    if not dates:
        logger.warning("Eurostat %s: no observations matched the time dimension", dataset)
        return None
    return _frame(dates, nums)


def _eurostat_period(label: str):
    """'2026-Q2' -> the quarter's first day; '2026-07' and '2026' also handled."""
    text = str(label).strip()
    if "Q" in text:
        year, quarter = text.split("-Q")
        return pd.Timestamp(year=int(year), month=(int(quarter) - 1) * 3 + 1, day=1)
    return pd.to_datetime(text, errors="coerce")


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


# ---------------------------------------------------------------------------
# Damodaran (NYU Stern) country data: ctryprem (country risk premium) and
# countrystats (aggregated country valuation multiples).
#
# Both are keyed by COUNTRY NAME, not any ISO code, so the name -> region map
# below is explicit rather than fuzzy-matched: several Damodaran rows would
# otherwise collide ("China" vs "Chile", "United Kingdom" vs "United Arab
# Emirates"). Names also carry footnote markers in some vintages
# ("Germany [1]" through the 2008-2011 files), which `_dam_country` strips.
#
# Both files are year-stamped archives -- <name><YY>.xls[x] -- where YY is the
# DATA year and the file itself is published the following January (
# ctryprem24.xlsx carries "Date of update: 2025-01-01"). So archive YY is
# stamped YY-12-31, and the undated current file is the most recent completed
# year. That makes the two sequences continuous with no overlap.
#
# Traps, both confirmed against every archive year on 2026-08-29:
#   - The header row moves between vintages (ctryprem: row 6, 7, 17, 19 or 20;
#     countrystats: row 0, 1, 7 or 8), so it MUST be scanned for. The 15-row
#     window fetch_damodaran_erp uses is too narrow -- ctryprem 2002-2008 puts
#     it at row 20.
#   - The sheet name moves too: "Sheet1" (2000), "Country premiums"
#     (2001-2011), "ERPs by country" (2012-now).
#   - ctryprem values are FRACTIONS in every vintage (0.00776 = 0.776%), so
#     they are multiplied by 100 unconditionally. The magnitude heuristic in
#     fetch_damodaran_erp cannot be reused here: Germany, Switzerland and
#     Norway are Aaa and carry a country risk premium of exactly 0.0 in all 26
#     years, so a per-country max would be 0 and prove nothing.
#   - countrystats changed STATISTIC in 2020: 2012-2019 publish "Average of
#     Trailing PE", 2020+ publish "Median Trailing PE". Those are not the same
#     series -- the means run 3-10x higher (Germany 171.3 in 2013 vs 15.9 in
#     2024) -- so only median-basis vintages are accepted. See SPEC.md.
# ---------------------------------------------------------------------------
_DAM_ARCHIVE = "https://pages.stern.nyu.edu/~adamodar/pc/archives/"
_DAM_DATASET = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/"

# Damodaran's country name -> this dashboard's region code. Explicit by
# design; do not replace with a fuzzy match.
DAMODARAN_COUNTRY_NAMES = {
    "united kingdom": "UK",
    "germany": "DE",
    "switzerland": "CH",
    "china": "CN",
    "japan": "JP",
    "norway": "NO",
}

# ctryprem archives confirmed present for 2000-2024; countrystats for
# 2012-2024, but only 2020+ are median-basis and therefore usable.
_CTRYPREM_FIRST_YEAR = 2000
_COUNTRYSTATS_FIRST_YEAR = 2020
_DAM_LAST_ARCHIVE_YEAR = 2024

_DAM_CACHE = {}


def _dam_country(value) -> str:
    """Normalise a Damodaran country cell: strip footnote markers and case."""
    name = re.sub(r"\s*\[\d+\]\s*$", "", str(value).strip())
    return re.sub(r"\s+", " ", name).lower()


# The current file's extension differs per dataset and is stable; hardcoding it
# keeps the weekly run from making a guaranteed-404 request every Saturday.
_DAM_CURRENT_EXT = {"ctryprem": "xlsx", "countrystats": "xls"}


def _dam_book(name: str, year: int | None):
    """
    Download one Damodaran workbook and return it as a pandas ExcelFile.

    year=None is the undated current file; an int is the year-stamped archive.
    Cached per (name, year) so six regions share one download, and pre-seeded
    to None so a failure is not retried once per region.
    """
    ck = (name, year)
    if ck in _DAM_CACHE:
        return _DAM_CACHE[ck]
    _DAM_CACHE[ck] = None
    if year is None:
        first = _DAM_CURRENT_EXT.get(name, "xlsx")
        other = "xls" if first == "xlsx" else "xlsx"
        urls = [f"{_DAM_DATASET}{name}.{first}", f"{_DAM_DATASET}{name}.{other}"]
    else:
        # Extension varies by vintage; .xlsx only appears from 2018.
        urls = [f"{_DAM_ARCHIVE}{name}{year % 100:02d}.xls",
                f"{_DAM_ARCHIVE}{name}{year % 100:02d}.xlsx"]
    for url in urls:
        resp = _get(url, headers=BROWSER_HEADERS)
        if resp is None or not resp.content:
            continue
        try:
            _DAM_CACHE[ck] = pd.ExcelFile(io.BytesIO(resp.content))
            return _DAM_CACHE[ck]
        except Exception as exc:  # noqa: BLE001 - a bad vintage must not lose the others
            logger.warning("Damodaran: %s not readable as Excel: %s", url, exc)
    return None


def _dam_header(raw, first_col: str, needle) -> int | None:
    """
    Locate the real header row. `needle` is a predicate over the lowered cells.

    Scans 30 rows, not 15: ctryprem's 2002-2008 vintages put the header at
    row 20, under a block of prose and input cells.
    """
    for i in range(min(30, len(raw))):
        row = [str(x).strip().lower() for x in raw.iloc[i].tolist()]
        if first_col in row and needle(row):
            return i
    return None


def _dam_table(xl, sheet_pattern: str, first_col: str, needle):
    """Find the right sheet + header row and return a labelled body frame."""
    if xl is None:
        return None
    sheets = [s for s in xl.sheet_names if re.search(sheet_pattern, s, re.I)] or xl.sheet_names
    for sheet in sheets:
        if re.search(r"lookup|faq|explanation|tax rates|worksheet|sequence", sheet, re.I):
            continue
        try:
            raw = xl.parse(sheet_name=sheet, header=None)
        except Exception:  # noqa: BLE001 - a malformed sheet must not lose the others
            continue
        hdr = _dam_header(raw, first_col, needle)
        if hdr is None:
            continue
        body = raw.iloc[hdr + 1:].copy()
        body.columns = [str(x).strip() for x in raw.iloc[hdr]]
        return body
    return None


def _dam_col_index(body, predicate) -> int | None:
    """
    Position of the FIRST column whose name satisfies `predicate`.

    Positional, not by label, because several vintages repeat a column name:
    ctryprem 2012-2015 carry two columns both headed "Country Risk Premium",
    and the current file has "Country Risk Premium" beside "Country Risk
    Premium3". The leftmost is the rating-based measure the catalog asks for;
    the later ones are the CDS-based variant. Selecting by label would hand
    back both as a Series.
    """
    for i, col in enumerate(body.columns):
        if predicate(str(col).strip()):
            return i
    return None


def _dam_pick(body, region: str, col_idx: int | None):
    """The one value for `region` out of a country-keyed Damodaran table."""
    target = next((n for n, r in DAMODARAN_COUNTRY_NAMES.items() if r == region), None)
    if target is None or body is None or col_idx is None:
        return None
    key = body.iloc[:, 0].map(_dam_country)
    hit = body[key == target]
    if hit.empty:
        return None
    value = pd.to_numeric(hit.iloc[0, col_idx], errors="coerce")
    return None if pd.isna(value) else float(value)


def fetch_damodaran_crp(region: str, archive: bool = False) -> pd.DataFrame | None:
    """
    Country risk premium for one region, Damodaran's rating-based method.

    This is NOT the earnings-yield-implied construct fetch_damodaran_erp
    computes for erp.US -- it is the sovereign-rating default spread scaled to
    equity, and it is zero for every Aaa sovereign. db/export.py adds the
    mature-market base (erp.US) back on for display.

    archive=True walks the year-stamped files back to 2000 -- bootstrap only.
    """
    years = list(range(_CTRYPREM_FIRST_YEAR, _DAM_LAST_ARCHIVE_YEAR + 1)) if archive else []
    dates, values = [], []
    try:
        for year in years + [None]:
            body = _dam_table(
                _dam_book("ctryprem", year),
                r"erps by country|country premiums|sheet1",
                "country",
                lambda row: any(c == "country risk premium" for c in row),
            )
            if body is None:
                continue
            idx = _dam_col_index(body, lambda c: c.lower() == "country risk premium")
            value = _dam_pick(body, region, idx)
            if value is None:
                continue
            stamp = _DAM_LAST_ARCHIVE_YEAR + 1 if year is None else year
            dates.append(f"{stamp}-12-31")
            # Fractions in every vintage. Unconditional: an all-Aaa country is
            # 0.0 throughout, so a magnitude heuristic would have nothing to test.
            values.append(value * 100.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Damodaran CRP parse failed for %s: %s", region, exc)
        return None
    if not dates:
        logger.warning("Damodaran CRP: nothing parsed for %s", region)
        return None
    return _frame(dates, values)


def fetch_damodaran_country_multiple(region: str, column: str,
                                     archive: bool = False) -> pd.DataFrame | None:
    """
    One aggregated valuation multiple for one region, from countrystats.

    `column` is the bare metric name ("Trailing PE", "PBV", ...); the sheet
    spells it "median(Trailing PE)" or "Median Trailing PE" depending on
    vintage. Only median-basis vintages (2020 onward) are read -- see the
    banner above for why the 2012-2019 mean-basis files are excluded.
    """
    years = list(range(_COUNTRYSTATS_FIRST_YEAR, _DAM_LAST_ARCHIVE_YEAR + 1)) if archive else []
    wanted = column.strip().lower()
    dates, values = [], []

    def _is_median(col: str) -> bool:
        # Accept "median(Trailing PE)" and "Median Trailing PE"; reject the
        # pre-2020 "Average of Trailing PE" outright.
        low = col.lower()
        if "median" not in low:
            return False
        tail = re.sub(r"[^a-z0-9/ ]", " ", low).split("median", 1)[-1]
        return re.sub(r"\s+", " ", tail).strip() == wanted

    try:
        for year in years + [None]:
            body = _dam_table(
                _dam_book("countrystats", year),
                r"sheet1|industry|country",
                "country",
                lambda row: any("trailing pe" in c for c in row),
            )
            if body is None:
                continue
            idx = _dam_col_index(body, _is_median)
            if idx is None:
                if year is not None:
                    logger.info("Damodaran countrystats %s: no median-basis %r column, skipped",
                                year, column)
                continue
            value = _dam_pick(body, region, idx)
            if value is None:
                continue
            stamp = _DAM_LAST_ARCHIVE_YEAR + 1 if year is None else year
            dates.append(f"{stamp}-12-31")
            values.append(value)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Damodaran countrystats parse failed for %s %s: %s", region, column, exc)
        return None
    if not dates:
        logger.warning("Damodaran countrystats: nothing parsed for %s %s", region, column)
        return None
    return _frame(dates, values)

