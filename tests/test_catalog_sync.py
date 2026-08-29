"""
The catalog sync must be safe to run unattended, every run, forever.

It writes into a file a person maintains by hand, so the things it must NEVER
do matter more than the things it does:
  - never overwrite human prose (description, notes, endpoint, horizon)
  - never change a scope decision (planned / no source found / descoped)
  - never drop a row
and the thing it must do: tell the truth about what is actually stored.
"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from db import catalog_sync, ingest, registry, store

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
        # A live series, a stale one, and three that are out of scope.
        rows = [_row("equity.US.sp500", "ok"),
                _row("valuation.US.cape", "ok"),          # actually stale in the DB
                _row("valuation.UK", "planned (v2)"),
                _row("curve.CN.10Y", "no source found"),
                _row("valuation.EZ", "descoped")]
        with self.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)

        self.conn = store.connect(Path(self.tmp.name) / "t.db")
        store.init_db(self.conn)
        entries = registry.by_id()
        keep = ["equity.US.sp500", "valuation.US.cape"]
        store.upsert_catalog(self.conn, [
            {"series_id": s, "category": "x", "region": "US", "description": "d",
             "unit": "u", "native_periodicity": "weekly", "source": "s",
             "max_age_days": entries[s].max_age_days, "status": "ok", "notes": None}
            for s in keep])
        run_id = store.start_run(self.conn, "test")
        # sp500: current. cape: years behind, so it must come back STALE.
        fresh = pd.date_range(end=pd.Timestamp.now().normalize(), periods=60, freq="W-FRI")
        store.insert_observations(self.conn, [
            ("equity.US.sp500", d, d, 100.0 + i) for i, d in enumerate(fresh)], run_id)
        old = pd.date_range(end=pd.Timestamp("2024-09-01"), periods=30, freq="MS")
        store.insert_observations(self.conn, [
            ("valuation.US.cape", d, d, 30.0 + i) for i, d in enumerate(old)], run_id)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def read(self):
        with self.csv.open(newline="", encoding="utf-8-sig") as fh:
            return {r["Identifier"]: r for r in csv.DictReader(fh)}

    # --- what it must never do -------------------------------------------
    def test_human_prose_is_untouched(self):
        catalog_sync.sync(self.conn, self.csv)
        for ident, row in self.read().items():
            if row["Notes / quirks"].startswith("Added automatically"):
                continue  # a row the sync itself appended
            self.assertEqual(row["Notes / quirks"], HUMAN_NOTE, ident)
            self.assertEqual(row["Description"], f"desc for {ident}", ident)
            self.assertEqual(row["Institution / endpoint"], f"endpoint for {ident}", ident)
            self.assertEqual(row["Recommended storage horizon"], "full", ident)
            self.assertEqual(row["Native periodicity"], "daily (trading days)", ident)

    def test_scope_decisions_are_never_rewritten(self):
        catalog_sync.sync(self.conn, self.csv)
        rows = self.read()
        self.assertEqual(rows["valuation.UK"]["Status"], "planned (v2)")
        self.assertEqual(rows["curve.CN.10Y"]["Status"], "no source found")
        self.assertEqual(rows["valuation.EZ"]["Status"], "descoped")

    def test_no_row_is_ever_dropped(self):
        before = set(self.read())
        catalog_sync.sync(self.conn, self.csv)
        self.assertTrue(before <= set(self.read()))

    def test_running_twice_is_stable(self):
        catalog_sync.sync(self.conn, self.csv)
        first = self.csv.read_text()
        catalog_sync.sync(self.conn, self.csv)
        self.assertEqual(first, self.csv.read_text(), "sync must be idempotent")

    # --- what it must do --------------------------------------------------
    def test_reports_actual_coverage(self):
        catalog_sync.sync(self.conn, self.csv)
        row = self.read()["equity.US.sp500"]
        self.assertEqual(row["In database"], "yes")
        self.assertEqual(row["Stored observations"], "60")
        self.assertEqual(row["Stored periodicity"], "weekly")
        self.assertTrue(row["Freshness"].startswith("fresh"), row["Freshness"])

    def test_flips_ok_to_stale_on_real_staleness(self):
        result = catalog_sync.sync(self.conn, self.csv)
        self.assertEqual(self.read()["valuation.US.cape"]["Status"], "stale")
        self.assertIn("valuation.US.cape: ok -> stale", result["status_changes"])

    def test_out_of_scope_rows_report_no_coverage(self):
        catalog_sync.sync(self.conn, self.csv)
        row = self.read()["curve.CN.10Y"]
        self.assertEqual(row["In database"], "no")
        self.assertEqual(row["Stored observations"], "—")

    def test_stored_series_missing_from_the_catalog_are_appended(self):
        result = catalog_sync.sync(self.conn, self.csv)
        # Every registry series not already listed gets a row.
        self.assertIn("cpi.US.index", result["added"])
        self.assertIn("cpi.US.index", self.read())


if __name__ == "__main__":
    unittest.main()
