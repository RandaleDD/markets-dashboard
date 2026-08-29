"""
The only module that talks SQL to markets.db.

Append-only by construction: there is no update() and no delete() here, and
`insert_observations` is the sole writer of `observations`. Everything it
writes goes through ON CONFLICT DO NOTHING, so re-ingesting a value the
database already holds costs one index probe and changes nothing.

If you are adding a function to this module and it contains the word UPDATE or
DELETE aimed at `observations`, stop -- that is the one thing DATABASE-PLAN.md
rules out outright. `tests/test_append_only.py` greps for it.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger("markets_dashboard.db")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# The database lives in the repo working tree and IS COMMITTED, alongside
# site/data/latest.json -- see DATABASE-PLAN.md. That is what makes the
# GitHub Actions runner start each day from yesterday's accumulated history
# instead of re-bootstrapping, and git's own commit history is the backup.
DEFAULT_DB_PATH = REPO_ROOT / "data" / "markets.db"


def db_path() -> Path:
    """Override with MARKETS_DB=/some/other.db (used by the tests)."""
    return Path(os.environ.get("MARKETS_DB") or DEFAULT_DB_PATH)


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # The file is committed to git, so a -wal/-shm pair left beside it would be
    # untracked state that changes what the next run sees. Keep it one file.
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


# ---------------------------------------------------------------------------
# series_catalog
# ---------------------------------------------------------------------------
CATALOG_COLUMNS = ("series_id", "category", "region", "description", "unit",
                   "native_periodicity", "source", "max_age_days", "status", "notes")


def upsert_catalog(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """
    series_catalog is metadata, not observations -- it describes what a series
    IS, and correcting a description or a staleness threshold must be possible.
    The append-only rule governs `observations`; this table is deliberately
    outside it.
    """
    payload = [tuple(r.get(c) for c in CATALOG_COLUMNS) for r in rows]
    conn.executemany(
        f"INSERT INTO series_catalog ({','.join(CATALOG_COLUMNS)}) "
        f"VALUES ({','.join('?' * len(CATALOG_COLUMNS))}) "
        f"ON CONFLICT(series_id) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in CATALOG_COLUMNS if c != "series_id"),
        payload)
    conn.commit()
    return len(payload)


def catalog(conn: sqlite3.Connection) -> dict[str, dict]:
    return {r["series_id"]: dict(r) for r in conn.execute("SELECT * FROM series_catalog")}


def catalog_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT series_id FROM series_catalog")}


# ---------------------------------------------------------------------------
# observations -- insert and read. There is deliberately nothing else.
# ---------------------------------------------------------------------------
def watermark(conn: sqlite3.Connection, series_id: str) -> str | None:
    """Newest date already stored for a series, or None if it has nothing yet."""
    row = conn.execute(
        "SELECT MAX(date) FROM latest_observations WHERE series_id = ?", (series_id,)).fetchone()
    return row[0] if row and row[0] else None


def watermarks(conn: sqlite3.Connection) -> dict[str, str]:
    """Every series' watermark in one query -- the daily run needs all of them."""
    return {r[0]: r[1] for r in conn.execute(
        "SELECT series_id, MAX(date) FROM latest_observations GROUP BY series_id")}


def stored_values(conn: sqlite3.Connection, series_id: str) -> dict[str, float]:
    """{date: current value} for a series, as `latest_observations` resolves it."""
    return {r[0]: r[1] for r in conn.execute(
        "SELECT date, value FROM latest_observations WHERE series_id = ?", (series_id,))}


def insert_observations(conn: sqlite3.Connection, rows: list[tuple], run_id: int | None = None) -> int:
    """
    rows: [(series_id, date, vintage_date, value), ...]

    The whole write path. ON CONFLICT DO NOTHING means "already have it" costs
    nothing and changes nothing; only genuinely new (series, date, vintage)
    triples become rows. Returns how many were actually attached.
    """
    if not rows:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    payload = [(sid, _iso(d), _iso(v), float(val), now, run_id) for sid, d, v, val in rows]
    before = conn.total_changes
    conn.executemany(
        "INSERT INTO observations "
        "(series_id, date, vintage_date, value, ingested_at, source_run_id) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(series_id, date, vintage_date) DO NOTHING", payload)
    conn.commit()
    return conn.total_changes - before


def read_series(conn: sqlite3.Connection, series_id: str) -> pd.DataFrame | None:
    """
    Full accumulated history as the canonical [date, value] frame -- the same
    shape `fetch/sources.py` returns, so every transform/ function consumes it
    unchanged.
    """
    df = pd.read_sql_query(
        "SELECT date, value FROM latest_observations WHERE series_id = ? ORDER BY date",
        conn, params=(series_id,))
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)
    return df if not df.empty else None


def read_all_series(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    """
    Every series in one query. The export step needs most of them, and ~110
    round trips of read_series() costs noticeably more than one scan plus a
    groupby.
    """
    df = pd.read_sql_query(
        "SELECT series_id, date, value FROM latest_observations ORDER BY series_id, date", conn)
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna()
    return {sid: g[["date", "value"]].reset_index(drop=True)
            for sid, g in df.groupby("series_id", sort=False) if not g.empty}


def observation_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]


# ---------------------------------------------------------------------------
# pipeline_runs
# ---------------------------------------------------------------------------
def start_run(conn: sqlite3.Connection, mode: str) -> int:
    cur = conn.execute(
        "INSERT INTO pipeline_runs (started_at, mode, git_sha) VALUES (?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), mode, _git_sha()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("UPDATE pipeline_runs SET finished_at = ? WHERE run_id = ?",
                 (datetime.now(timezone.utc).isoformat(), run_id))
    conn.commit()


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001 - a missing git is not a pipeline failure
        return None


# ---------------------------------------------------------------------------
# data_quality_flags
# ---------------------------------------------------------------------------
def raise_flag(conn: sqlite3.Connection, series_id: str, obs_date: str,
               flag_type: str, detail: str) -> bool:
    """
    Record a finding. The unique index on (series_id, date, flag_type, resolved)
    means re-detecting the same condition tomorrow is a no-op rather than a
    second row, so an unfixable gap doesn't grow the table without bound.
    Returns True when this was genuinely new.
    """
    before = conn.total_changes
    conn.execute(
        "INSERT INTO data_quality_flags (series_id, date, flag_type, detail, raised_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (series_id, _iso(obs_date), flag_type, detail, datetime.now(timezone.utc).isoformat()))
    return conn.total_changes > before


def open_flag_tally(conn: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT flag_type, COUNT(*) FROM data_quality_flags WHERE resolved = 0 "
        "GROUP BY flag_type ORDER BY flag_type")}


def open_flags(conn: sqlite3.Connection, limit: int = 500) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT series_id, date, flag_type, detail, raised_at FROM data_quality_flags "
        "WHERE resolved = 0 ORDER BY raised_at DESC, series_id LIMIT ?", (limit,))]


def _iso(d) -> str:
    """Everything stored as a plain ISO date string -- SQLite has no date type."""
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, (datetime, pd.Timestamp)):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.isoformat()
    return pd.Timestamp(d).strftime("%Y-%m-%d")
