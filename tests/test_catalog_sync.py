"""
The coverage sync runs unattended every run, forever.

What it must never do: write DATA-CATALOG.csv, which a person maintains.
What it must do: tell the truth about what is stored, in DATA-COVERAGE.csv.
"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from db import catalog_sync, registry, store

FIELDS = ["Category", "Region", "Identifier", "Description", "Value unit / format",
          "Native periodicity", "Source response format", "Max history available",
          "Recommended storage horizon", "Institution / endpoint", "Status",
          "Notes / quirks"]

HUMAN_NOTE = "Hand-written note that must survive: two-row header, match the lower one."


def _row(ident, status, note=HUMAN_NOTE):
    return {f: "" for f in FIELDS} | {
        "Identifier": ident, "Status": status, "Description": f"desc for {ident}",
        "Institution / endpoint": f"endpoint for {ident}", "Notes / quirks": note,
        "Recommended storage horizon": "full", "Native periodicity": "daily (trading days)"}


class CatalogSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv = Path(self.tmp.name) / "DATA-CATALOG.csv"
        self.out = Path(self.tmp.name) / "DATA-COVERAGE.csv"
        rows = [_row("equity.US.sp500", "ok"),
                _row("valuation.US.cape", "ok"),          # actually stale in the DB
                _row("fake.unsourced", "no source found"),
                _row("fake.descoped", "descoped")]
        with self.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)

        self.conn = store.connect(Path(self.tmp.name) / "t.db")
        store.init_db(self.conn)
        entries = registry.by_id()
        store.upsert_catalog(self.conn, [
            {"series_id": s, "category": "x", "region": "US", "description": "d",
             "unit": "u", "native_periodicity": "weekly", "source": "s",
             "max_age_days": entries[s].max_age_days if s in entries else 14,
             "status": "ok", "notes": None}
            for s in ("equity.US.sp500", "valuation.US.cape", "gone.series")])
        run_id = store.start_run(self.conn, "test")
        # sp500: current. cape: years behind, so it must come back stale.
        fresh = pd.date_range(end=pd.Timestamp.now().normalize(), periods=60, freq="W-FRI")
        store.insert_observations(self.conn, [
            ("equity.US.sp500", d, d, 100.0 + i) for i, d in enumerate(fresh)], run_id)
        old = pd.date_range(end=pd.Timestamp("2024-09-01"), periods=30, freq="MS")
        store.insert_observations(self.conn, [
            ("valuation.US.cape", d, d, 30.0 + i) for i, d in enumerate(old)], run_id)
        # Stored history for a series no longer in the registry.
        store.insert_observations(self.conn, [("gone.series", "2026-01-02", "2026-01-02", 1.0)],
                                  run_id)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def sync(self):
        return catalog_sync.sync(self.conn, self.csv, self.out)

    def read(self):
        with self.out.open(newline="", encoding="utf-8") as fh:
            return {r["Identifier"]: r for r in csv.DictReader(fh)}

    def test_the_reviewed_catalog_is_never_written(self):
        before = self.csv.read_bytes()
        self.sync()
        self.assertEqual(self.csv.read_bytes(), before)

    def test_running_twice_is_stable(self):
        self.sync()
        first = self.out.read_text()
        self.sync()
        self.assertEqual(first, self.out.read_text(), "sync must be idempotent")

    def test_reports_actual_coverage(self):
        self.sync()
        row = self.read()["equity.US.sp500"]
        self.assertEqual(row["In database"], "yes")
        self.assertEqual(row["Stored observations"], "60")
        self.assertEqual(row["Stored periodicity"], "weekly")
        self.assertEqual(row["Live status"], "ok")
        self.assertTrue(row["Freshness"].startswith("fresh"), row["Freshness"])

    def test_real_staleness_is_reported(self):
        result = self.sync()
        self.assertEqual(self.read()["valuation.US.cape"]["Live status"], "stale")
        self.assertEqual(self.read()["valuation.US.cape"]["Catalog status"], "ok")
        self.assertIn("valuation.US.cape", result["stale"])

    def test_out_of_scope_rows_report_no_coverage(self):
        self.sync()
        row = self.read()["fake.unsourced"]
        self.assertEqual((row["In database"], row["Live status"], row["Catalog status"]),
                         ("no", "—", "no source found"))

    def test_registered_series_without_a_reviewed_row_are_listed_not_appended(self):
        result = self.sync()
        self.assertIn("cpi.US.index", result["unreviewed"])
        self.assertEqual(self.read()["cpi.US.index"]["Catalog status"], "not in catalog")
        self.assertEqual(self.read()["cpi.US.index"]["Live status"], "missing")

    def test_stored_but_unregistered_history_is_retired(self):
        self.sync()
        self.assertEqual(self.read()["gone.series"]["Live status"], "retired")


class CommittedCatalogTest(unittest.TestCase):
    """
    Invariants of the real data/DATA-CATALOG.csv, not of a fixture.

    The sync tests above run against a temp file, so nothing there can see the
    one thing that actually went wrong: seven identifiers ended up on two rows
    each between 2026-09-13 and 2026-09-19. It happens when a series is
    registered and the pipeline runs before its reviewed row is hand-written --
    catalog_sync appends a generated row, the author then writes the real one,
    and nothing ever removes either.

    That is invisible from the sync's own output, because `seen` prevents a
    third row and both existing rows are refreshed on every run. It is also not
    cosmetic: db/catalog.read_csv_rows keys a dict by identifier, so the LAST
    row wins and the generated metadata displaces the reviewed prose in
    series_catalog. test_no_row_is_ever_dropped above cannot catch it either --
    it compares dict-collapsed sets of identifiers.
    """

    def test_every_identifier_appears_exactly_once(self):
        with catalog_sync.CATALOG_CSV.open(newline="", encoding="utf-8-sig") as fh:
            ids = [(r.get("Identifier") or "").strip()
                   for r in csv.DictReader(fh)
                   if (r.get("Identifier") or "").strip()]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        with catalog_sync.CATALOG_CSV.open(newline="", encoding="utf-8-sig") as fh:
            header = next(csv.reader(fh))
        self.assertNotIn("In database", header,
                         "coverage belongs in DATA-COVERAGE.csv, not the reviewed catalog")
        self.assertEqual(dupes, [], "duplicate rows: the last one silently wins "
                                    "when series_catalog is built, discarding the "
                                    "reviewed prose on the other")


if __name__ == "__main__":
    unittest.main()
