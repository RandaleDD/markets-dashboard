"""
Keep DATA-CATALOG.csv a true mirror of what the database actually holds.

The catalog is the human-readable record of sourcing DECISIONS -- what each
series is, where it comes from, what is known to be awkward about it. Those
columns are written by a person and this module never touches them.

What it does maintain, after every run, is the other half: what is genuinely
in `data/markets.db` right now. Before this, the catalog could say "full"
history and status "ok" for a series that had quietly stopped updating, and
nothing would contradict it. Now the file answers both questions side by side
-- what we decided, and what we actually have -- in the same spreadsheet
layout, so it can be opened and read without touching the database.

Three rules that make this safe to run unattended:

  - **Human prose is never overwritten.** Description, unit, source endpoint,
    notes, recommended horizon and the source's own native periodicity are
    read, preserved, and written back untouched.
  - **Scope decisions are never overwritten.** `Status` is only ever flipped
    between `ok` and `stale`, and only for a series that has a fetcher. A row
    marked `planned (v2)`, `no source found`, `exists, not free` or
    `descoped` keeps that status forever -- those are judgements about whether
    a series is in scope at all, and a pipeline run has no business changing
    them.
  - **Rows are never removed.** A series that disappears from the registry
    keeps its row and simply reports that it is not in the database.

Series the database holds that the catalog has no row for are appended, so
the mirror is complete in both directions -- that is how the eight
`cpi.<region>.index` siblings, which the catalog folded into their parent
rows, come to be listed.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from db import registry, store

logger = logging.getLogger("markets_dashboard.db.catalog_sync")

CATALOG_CSV = Path(__file__).resolve().parent.parent / "data" / "DATA-CATALOG.csv"

ID_COLUMN = "Identifier"
STATUS_COLUMN = "Status"

# Appended to the right of the human-authored columns, so the existing layout
# is unchanged and the measured facts read as a block.
COVERAGE_COLUMNS = [
    "In database",
    "Stored periodicity",
    "Stored from",
    "Stored to",
    "Stored observations",
    "Freshness",
    "Open data-quality flags",
    "Synced",
]

# The only two statuses this module may write. Everything else is a scope
# decision that belongs to whoever reviewed the sourcing.
LIVE_STATUSES = {"ok", "stale"}


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
    if age <= max_age_days:
        return f"fresh ({age}d old, limit {max_age_days}d)"
    return f"STALE ({age}d old, limit {max_age_days}d)"


def sync(conn, path: Path | None = None) -> dict:
    """Rewrite the coverage columns in place. Returns a short summary."""
    path = Path(path) if path else CATALOG_CSV
    if not path.exists():
        logger.warning("No catalog at %s; nothing to sync", path)
        return {"rows": 0, "updated": 0, "added": 0, "status_changes": []}

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        original_fields = list(reader.fieldnames or [])
        rows = list(reader)

    series = registry.by_id()
    coverage = _coverage(conn)
    flags = _open_flags(conn)
    synced = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    fields = original_fields + [c for c in COVERAGE_COLUMNS if c not in original_fields]
    seen, status_changes, updated = set(), [], 0

    def fill(row: dict, series_id: str) -> None:
        nonlocal updated
        entry = series.get(series_id)
        cover = coverage.get(series_id)
        if cover:
            row["In database"] = "yes"
            row["Stored periodicity"] = entry.periodicity if entry else ""
            row["Stored from"] = cover["first"]
            row["Stored to"] = cover["last"]
            row["Stored observations"] = f"{cover['n']:,}"
            row["Freshness"] = _freshness(cover["last"], entry.max_age_days) if entry else ""
        else:
            row["In database"] = "no"
            for column in ("Stored periodicity", "Stored from", "Stored to",
                           "Stored observations", "Freshness"):
                row[column] = "—"
        row["Open data-quality flags"] = ", ".join(flags.get(series_id, [])) or "—"
        row["Synced"] = synced

        # Status: only ever ok <-> stale, and only where a fetcher exists.
        current = (row.get(STATUS_COLUMN) or "").strip()
        if entry and cover and current in LIVE_STATUSES:
            live = "stale" if row["Freshness"].startswith("STALE") else "ok"
            if live != current:
                row[STATUS_COLUMN] = live
                status_changes.append(f"{series_id}: {current} -> {live}")
        updated += 1

    for row in rows:
        series_id = (row.get(ID_COLUMN) or "").strip()
        seen.add(series_id)
        fill(row, series_id)

    # Series the database holds that the catalog never listed.
    added = []
    for series_id, entry in series.items():
        if series_id in seen:
            continue
        row = {field: "" for field in fields}
        row.update({
            "Category": entry.category, "Region": entry.region or "—",
            ID_COLUMN: series_id, "Description": entry.description,
            "Value unit / format": entry.unit,
            "Native periodicity": entry.native_periodicity or entry.periodicity,
            "Institution / endpoint": entry.source, STATUS_COLUMN: "ok",
            "Notes / quirks": "Added automatically by db/catalog_sync.py: the "
                              "database stores this series but the reviewed "
                              "catalog had no row for it.",
        })
        fill(row, series_id)
        rows.append(row)
        added.append(series_id)

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    in_db = sum(1 for r in rows if r.get("In database") == "yes")
    logger.info("Catalog synced: %d rows, %d in the database, %d added%s",
                len(rows), in_db, len(added),
                (f"; status changes: {', '.join(status_changes)}" if status_changes else ""))
    for change in status_changes:
        logger.warning("Catalog status changed — %s", change)
    return {"rows": len(rows), "in_database": in_db, "added": added,
            "status_changes": status_changes}
