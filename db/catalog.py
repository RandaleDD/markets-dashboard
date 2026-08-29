"""
Load `series_catalog` by joining DATA-CATALOG.csv against `db/registry.py`.

The two describe different things and both are needed:

  - **DATA-CATALOG.csv** is the human-reviewed record of sourcing *decisions* --
    what each series is, its unit, its native periodicity, which institution
    publishes it, what is known to be broken about it, and whether it is in
    scope at all. It is the source of truth for the metadata.
  - **db/registry.py** (via fetch/universe.py) is what the code can actually
    fetch today. It is the source of truth for which rows become table rows.

A row is imported when the catalog says it is in scope AND a fetcher exists.
Concretely:

  - `ok` / `stale`   -> imported.
  - `planned (v2)`   -> imported only if a fetcher already exists. Credit
                        spreads, SLOOS and the two bond proxies shipped in
                        V2 Phases C and F but the catalog still labels them
                        planned; the Damodaran country valuation and country
                        risk premium rows genuinely have no fetcher and stay
                        out until one is written.
  - `no source found` / `exists, not free` / `descoped` -> never imported.
    These have nothing to store, and a catalog row with no observations behind
    it would be counted as an incomplete series forever.

`status` in the database is the CATALOG's standing assessment, not a live
result. Whether a series is fresh right now is answered by the staleness check
against `max_age_days` and written to `data_quality_flags` -- never by this
column.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from db import registry

logger = logging.getLogger("markets_dashboard.db.catalog")

CATALOG_CSV = Path(__file__).resolve().parent.parent / "data" / "DATA-CATALOG.csv"

IN_SCOPE = {"ok", "stale"}
CONDITIONAL = {"planned (v2)"}          # in scope only once a fetcher exists
OUT_OF_SCOPE = {"no source found", "exists, not free", "descoped"}

# DATA-CATALOG.csv's status vocabulary -> the schema's.
STATUS_MAP = {"ok": "ok", "stale": "stale", "planned (v2)": "planned"}


def read_csv_rows() -> dict[str, dict]:
    """{identifier: row} for every row in the reviewed catalog."""
    with CATALOG_CSV.open(newline="", encoding="utf-8-sig") as fh:
        return {r["Identifier"].strip(): r
                for r in csv.DictReader(fh) if r.get("Identifier", "").strip()}


def build_rows() -> tuple[list[dict], dict]:
    """
    Returns (series_catalog rows, a report of how the two sides lined up).

    The report is not decoration: a catalog row that is in scope with no
    fetcher, or a fetchable series with no catalog row, is drift between the
    reviewed sourcing decisions and the code, and it should be visible on
    every bootstrap rather than discovered months later.
    """
    csv_rows = read_csv_rows()
    series = registry.all_series()
    rows, report = [], {
        "matched": [], "registry_only": [], "catalog_missing_fetcher": [],
        "out_of_scope": [], "source_divergence": [],
    }

    for s in series:
        cat = csv_rows.get(s.series_id)
        if cat is None:
            # No catalog row: the sibling series the catalog folds into one
            # line (cpi.<R>.index shares its parent's row). Registry metadata
            # stands in, and the join is reported so a genuine omission shows.
            report["registry_only"].append(s.series_id)
        else:
            report["matched"].append(s.series_id)
            declared = (cat.get("Institution / endpoint") or "").strip()
            if declared and not _same_source(declared, s.source):
                report["source_divergence"].append(
                    {"series_id": s.series_id, "catalog": declared, "pipeline": s.source})

        status = STATUS_MAP.get((cat or {}).get("Status", "").strip(), "ok")
        rows.append({
            "series_id": s.series_id,
            "category": (cat or {}).get("Category") or s.category,
            "region": (cat or {}).get("Region") or s.region,
            "description": (cat or {}).get("Description") or s.description,
            "unit": (cat or {}).get("Value unit / format") or s.unit,
            "native_periodicity": (cat or {}).get("Native periodicity") or s.periodicity,
            # What the pipeline actually calls, which is the thing a future
            # reader needs when a fetch breaks. Divergence from the catalog's
            # named endpoint is recorded in notes rather than hidden.
            "source": s.source,
            "max_age_days": s.max_age_days,
            "status": status,
            "notes": _notes(cat, s),
        })

    fetchable = {s.series_id for s in series}
    for ident, row in csv_rows.items():
        status = (row.get("Status") or "").strip()
        if ident in fetchable:
            continue
        if status in OUT_OF_SCOPE:
            report["out_of_scope"].append(ident)
        elif status in IN_SCOPE or status in CONDITIONAL:
            report["catalog_missing_fetcher"].append({"series_id": ident, "status": status})

    return rows, report


def _same_source(catalog_source: str, pipeline_source: str) -> bool:
    """
    Loose match on the institution, ignoring how each side spells the endpoint.

    "FRED, fredgraph.csv?id=DGS2" and "FRED, DGS2" are the same decision; only
    a different institution or a different series id is worth reporting.
    """
    def tokens(text):
        return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split()
                if len(t) > 2 and t not in {"csv", "xls", "xlsx", "format", "com", "org",
                                            "http", "https", "data", "api", "the", "and"}}
    a, b = tokens(catalog_source), tokens(pipeline_source)
    return bool(a & b)


def _notes(cat: dict | None, s: registry.Series) -> str:
    parts = []
    if cat and (cat.get("Notes / quirks") or "").strip():
        parts.append(cat["Notes / quirks"].strip())
    if cat is None:
        parts.append("No standalone DATA-CATALOG.csv row — folded into its "
                     "parent series' catalog line; metadata from db/registry.py.")
    if s.revisable:
        parts.append("Revisable: a restated value is appended with today's "
                     "vintage_date, never written over the first print.")
    if s.archive_kwargs:
        parts.append("History seeded once from the source's deep archive; the "
                     "daily run reads only the current snapshot.")
    if not s.bounded:
        parts.append("Snapshot source: no bounded-query parameter, so the daily "
                     "run refetches the whole (small) payload and ON CONFLICT "
                     "discards what is already stored.")
    return " ".join(parts) or None


def log_report(report: dict) -> None:
    logger.info("Catalog join: %d matched, %d registry-only, %d catalog rows "
                "in scope with no fetcher, %d explicitly out of scope",
                len(report["matched"]), len(report["registry_only"]),
                len(report["catalog_missing_fetcher"]), len(report["out_of_scope"]))
    for item in report["catalog_missing_fetcher"]:
        logger.warning("Catalog row %s (%s) has no fetcher — not stored",
                       item["series_id"], item["status"])
    for item in report["source_divergence"]:
        logger.warning("Source divergence for %s: catalog says %r, pipeline uses %r",
                       item["series_id"], item["catalog"], item["pipeline"])
