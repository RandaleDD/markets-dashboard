"""
Low-level fetchers, one function per data source. Each function:
  - takes a source-specific identifier
  - returns a pandas DataFrame with columns ["date", "value"] (or None on failure)
  - never raises — logs a warning and returns None, so one bad source
    doesn't take down the whole pipeline run

IMPORTANT — read NETWORK.md before assuming any of these work as written.
They're built against each source's documented/observed URL format but have
NOT been live-tested from this environment (outbound network here is
allowlisted to package registries only). Treat the first real run — either
your machine or the GitHub Actions workflow — as the actual test.
"""
import logging
import io
from datetime import datetime, timezone

import pandas as pd
import requests

logger = logging.getLogger("markets_dashboard.fetch")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; markets-dashboard/0.1; personal use)"
}
TIMEOUT = 20


def _get(url, params=None):
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a best-effort fetch
        logger.warning("Fetch failed for %s (%s): %s", url, params, exc)
        return None


# ---------------------------------------------------------------------------
# Stooq — prices for equity indices, FX, commodities
# CSV endpoint: https://stooq.com/q/d/l/?s=<symbol>&i=d
# ---------------------------------------------------------------------------
def fetch_stooq(symbol: str) -> pd.DataFrame | None:
    if not symbol:
        return None
    resp = _get("https://stooq.com/q/d/l/", params={"s": symbol, "i": "d"})
    if resp is None or not resp.text or resp.text.strip().startswith("<"):
        logger.warning("Stooq returned no usable data for %s", symbol)
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]
        if "date" not in df.columns or "close" not in df.columns:
            logger.warning("Stooq CSV for %s missing expected columns: %s", symbol, df.columns.tolist())
            return None
        df = df.rename(columns={"close": "value"})[["date", "value"]]
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stooq CSV parse failed for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# FRED — public fredgraph.csv endpoint does NOT require an API key.
# https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
# (A real API key, if Marco gets one free at fred.stlouisfed.org, unlocks
# the richer JSON API — not required for v1.)
# ---------------------------------------------------------------------------
def fetch_fred(series_id: str) -> pd.DataFrame | None:
    if not series_id:
        return None
    resp = _get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]
        value_col = series_id.lower()
        if value_col not in df.columns:
            # FRED sometimes names the column differently from the series id case
            candidates = [c for c in df.columns if c != "date" and c != "observation_date"]
            if not candidates:
                return None
            value_col = candidates[0]
        date_col = "date" if "date" in df.columns else "observation_date"
        df = df.rename(columns={date_col: "date", value_col: "value"})[["date", "value"]]
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna().sort_values("date").reset_index(drop=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FRED CSV parse failed for %s: %s", series_id, exc)
        return None


# ---------------------------------------------------------------------------
# BIS Data Portal — central bank policy rates (CBPOL dataset).
# The portal's programmatic access is SDMX-based (stats.bis.org / data.bis.org
# REST). Exact dataflow/key structure not confirmed live from this
# environment — this function documents the intended shape and needs a
# first-real-run check against the current BIS API docs at data.bis.org/topics/CBPOL.
# ---------------------------------------------------------------------------
def fetch_bis_policy_rate(ref_area: str) -> pd.DataFrame | None:
    # SDMX REST pattern used by most BIS Data Portal datasets:
    #   https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.<ref_area>?format=csv
    # TODO(first real run): confirm exact dataflow id/version and key order
    # against https://data.bis.org/topics/CBPOL — this URL is a best guess
    # from documented BIS SDMX conventions, not a verified endpoint.
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{ref_area}"
    resp = _get(url, params={"format": "csv"})
    if resp is None or not resp.text:
        return None
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]
        date_col = next((c for c in df.columns if "period" in c or c == "date"), None)
        value_col = next((c for c in df.columns if "obs_value" in c or c == "value"), None)
        if not date_col or not value_col:
            return None
        df = df.rename(columns={date_col: "date", value_col: "value"})[["date", "value"]]
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("BIS CBPOL parse failed for %s: %s", ref_area, exc)
        return None


# ---------------------------------------------------------------------------
# Stubs for sources flagged as "confirm endpoint on first real run" in
# sourcing-map.md. Each returns None today; each has the confirmed
# institution + a TODO for the exact query. Wiring these up is the Phase 2/3
# work — see SPEC.md.
# ---------------------------------------------------------------------------
def fetch_snb(cube: str, params: dict) -> pd.DataFrame | None:
    # data.snb.ch/en/topics/ziredev/cube/rendoblid — SNB Data Portal exposes
    # a documented JSON/CSV API per "cube". TODO: confirm exact cube/dimension
    # codes for the Swiss Confederation bond yield curve.
    logger.info("fetch_snb: not yet wired up (%s, %s)", cube, params)
    return None


def fetch_bundesbank(series_key: str) -> pd.DataFrame | None:
    # bundesbank.de publishes a public time-series database with CSV export
    # per series key. TODO: confirm the exact series key for the daily Bund
    # term-structure curve at each tenor.
    logger.info("fetch_bundesbank: not yet wired up (%s)", series_key)
    return None


def fetch_chinabond(tenor: str) -> pd.DataFrame | None:
    # yield.chinabond.com.cn — English portal, CGB yield curve. TODO: confirm
    # query parameters for programmatic access (vs. the browsable UI).
    logger.info("fetch_chinabond: not yet wired up (%s)", tenor)
    return None


def fetch_jsda(tenor: str) -> pd.DataFrame | None:
    # jsda.or.jp/en/statistics/bonds/prices — reference OTC bond yields.
    # TODO: confirm download format (likely a periodic Excel/CSV release).
    logger.info("fetch_jsda: not yet wired up (%s)", tenor)
    return None


def fetch_boe(series_code: str) -> pd.DataFrame | None:
    # bankofengland.co.uk/boeapps/database — supports CSV export via
    # FromShowColumns.asp with query params. TODO: confirm exact param set
    # for gilt yield curve + "Inflation implied forward" series.
    logger.info("fetch_boe: not yet wired up (%s)", series_code)
    return None


def fetch_ecb(series_key: str) -> pd.DataFrame | None:
    # ECB SDW REST API: https://sdw-wsrest.ecb.europa.eu/service/data/<flow>/<key>
    # TODO: confirm the inflation-linked-swap series key (the browse UI at
    # data.ecb.europa.eu is robots-blocked for automated fetching, but the
    # REST API itself is a separate, queryable endpoint).
    logger.info("fetch_ecb: not yet wired up (%s)", series_key)
    return None


def fetch_periphery_spread(country: str) -> pd.DataFrame | None:
    # France: Banque de France Webstat (MTS France source).
    # Italy: Banca d'Italia Infostat.
    # Spain: Banco de España statistics.
    # TODO: confirm exact series per institution (see universe.py note).
    logger.info("fetch_periphery_spread: not yet wired up (%s)", country)
    return None


def fetch_shiller_cape() -> pd.DataFrame | None:
    # Robert Shiller's Yale data page publishes a downloadable Excel file
    # (ie_data.xls) with the full CAPE history. TODO: confirm current URL —
    # it has moved between econ.yale.edu/~shiller/data.htm and shillerdata.com
    # over time; check both.
    logger.info("fetch_shiller_cape: not yet wired up")
    return None


def fetch_damodaran_erp() -> pd.DataFrame | None:
    # pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histimpl.html
    # publishes a downloadable Excel file of historical implied ERP.
    # TODO: confirm current filename (Damodaran reorganizes his data files
    # periodically through the year).
    logger.info("fetch_damodaran_erp: not yet wired up")
    return None


def fetch_etf_factsheet(ticker: str) -> dict | None:
    # iShares/State Street fact sheets are PDFs, not CSV/JSON — this needs a
    # PDF table-extraction step (e.g. pdfplumber), not a simple HTTP+parse.
    # Deliberately left unimplemented for v1; see SPEC.md Phase 4.
    logger.info("fetch_etf_factsheet: not yet implemented (%s)", ticker)
    return None
