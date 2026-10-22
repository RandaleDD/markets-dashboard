"""
Write data/DATA-COVERAGE.csv: what the database actually holds, per series.

DATA-CATALOG.csv is the human-readable record of sourcing DECISIONS and is
written only by a person. Until 2026-10-22 this module rewrote coverage columns
INTO it after every run, which made a hand-maintained file churn weekly, made
it ~200 KB, and could append generated rows that silently displaced reviewed
ones (seven duplicate pairs in Sep 2026). Now the measured half lives in its
own generated file, published with the data on the `data` branch and never
committed to main, and the reviewed file is read-only to the pipeline.

One row per identifier in the union of the catalog, the registry and the
store, in catalog order, so the two files line up when read side by side.
`Live status` is the measured answer: `ok`, `stale`, `missing` (registered,
nothing stored), `retired` (stored, no longer registered) or `—` (out of scope).
A registered series with no reviewed catalog row is logged, not appended:
write its row by hand.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from db import registry, store

logger = logging.getLogger("markets_dashboard.db.catalog_sync")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CATALOG_CSV = DATA_DIR / "DATA-CATALOG.csv"
COVERAGE_CSV = DATA_DIR / "DATA-COVERAGE.csv"

ID_COLUMN = "Identifier"
STATUS_COLUMN = "Status"

COVERAGE_COLUMNS = [
    "Identifier",
    "Category",
    "Region",
    "Catalog status",
    "Live status",
    "In database",
    "Stored periodicity",
    "Stored from",
    "Stored to",
    "Stored observations",
    "Freshness",
    "Open data-quality flags",
    "Synced",
]

def _coverage(conn) -> dict[str, dict]:
    """One pass over the view for every series' first/last date and count."""
    df = pd.read_sql_query(
        "SELECT series_id, MIN(date) AS first, MAX(date) AS last, COUNT(*) AS n "
        "FROM latest_observations GROUP BY series_id", conn)
    return {r.series_id: {"first": r.first, "last": r.last, "n": int(r.n)}
            for r in df.itertuples()}


def _open_flags(conn) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for series_id, flag_type, count in conn.execute(
            "SELECT series_id, flag_type, COUNT(*) FROM data_quality_flags "
            "WHERE resolved = 0 GROUP BY series_id, flag_type ORDER BY series_id, flag_type"):
        out.setdefault(series_id, []).append(
            flag_type if count == 1 else f"{flag_type} x{count}")
    return out


def _freshness(last: str | None, max_age_days: int) -> str:
    if not last:
        return "—"
    age = (pd.Timestamp.now().normalize() - pd.Timestamp(last).normalize()).days
    if age < 0:
        # Only a series carrying projections ends in the future (the IMF WEO);
        # its freshness is the edition's, recorded on imf.weo_edition.
        return f"projections to {pd.Timestamp(last).year} (age: see imf.weo_edition)"
    if age <= max_age_days:
        return f"fresh ({age}d old, limit {max_age_days}d)"
    return f"STALE ({age}d old, limit {max_age_days}d)"


def sync(conn, catalog_path: Path | None = None, out_path: Path | None = None) -> dict:
    """Rewrite the coverage file from the store. Never writes the catalog."""
    catalog_path = Path(catalog_path) if catalog_path else CATALOG_CSV
    out_path = Path(out_path) if out_path else COVERAGE_CSV
    reviewed: list[dict] = []
    if catalog_path.exists():
        with catalog_path.open(newline="", encoding="utf-8-sig") as fh:
            reviewed = [r for r in csv.DictReader(fh) if (r.get(ID_COLUMN) or "").strip()]

    series = registry.by_id()
    coverage = _coverage(conn)
    flags = _open_flags(conn)
    synced = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    ids = [r[ID_COLUMN].strip() for r in reviewed]
    by_id = {r[ID_COLUMN].strip(): r for r in reviewed}
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    for series_id in duplicates:
        logger.warning("DATA-CATALOG.csv has %d rows for %s; the LAST one wins when "
                       "series_catalog is built. Delete the other.",
                       ids.count(series_id), series_id)
    unreviewed = [sid for sid in series if sid not in by_id]
    if unreviewed:
        logger.warning("Registered but missing from DATA-CATALOG.csv (write their "
                       "reviewed rows): %s", ", ".join(unreviewed))
    order = list(dict.fromkeys(ids + unreviewed + sorted(set(coverage) - set(ids) - set(series))))

    rows, stale = [], []
    for series_id in order:
        entry, cover, cat = series.get(series_id), coverage.get(series_id), by_id.get(series_id, {})
        row = {"Identifier": series_id,
               "Category": cat.get("Category") or (entry.category if entry else ""),
               "Region": cat.get("Region") or ((entry.region or "—") if entry else ""),
               "Catalog status": (cat.get(STATUS_COLUMN) or "").strip() or "not in catalog",
               "Open data-quality flags": ", ".join(flags.get(series_id, [])) or "—",
               "Synced": synced}
        if cover:
            row.update({"In database": "yes",
                        "Stored periodicity": entry.periodicity if entry else "",
                        "Stored from": cover["first"], "Stored to": cover["last"],
                        "Stored observations": f"{cover['n']:,}",
                        "Freshness": _freshness(cover["last"], entry.max_age_days) if entry else ""})
        else:
            row.update({c: "—" for c in ("Stored periodicity", "Stored from", "Stored to",
                                         "Stored observations", "Freshness")})
            row["In database"] = "no"
        if entry and cover:
            row["Live status"] = "stale" if row["Freshness"].startswith("STALE") else "ok"
        elif entry:
            row["Live status"] = "missing"
        elif cover:
            row["Live status"] = "retired"
        else:
            row["Live status"] = "—"
        if row["Live status"] == "stale":
            stale.append(series_id)
        rows.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COVERAGE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    in_db = sum(1 for r in rows if r["In database"] == "yes")
    logger.info("Coverage written: %d series, %d in the database, %d stale%s",
                len(rows), in_db, len(stale), f" ({', '.join(stale)})" if stale else "")
    return {"rows": len(rows), "in_db": in_db, "stale": stale,
            "unreviewed": unreviewed, "duplicates": duplicates}
