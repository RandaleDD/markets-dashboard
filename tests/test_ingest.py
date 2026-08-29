"""
Ingest semantics, against a real SQLite file and a stubbed fetcher.

What these pin down, all of it straight out of SPEC.md:
  - re-ingesting an unchanged series attaches nothing (the "ignore" case)
  - a non-revisable series always writes vintage_date = date (inert mechanism)
  - a restated GDP/CPI figure is APPENDED with today's vintage, the first print
    is still there, and latest_observations resolves to the restatement
  - the watermark comes off latest_observations, so a revision does not move it
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from db import ingest, registry, store


def frame(pairs):
    return pd.DataFrame({"date": pd.to_datetime([d for d, _ in pairs]),
                         "value": [v for _, v in pairs]})


PRICE = registry.Series(
    series_id="test.price", category="Test", region="US", description="a price",
    unit="x", cadence="daily", source="stub", fetcher="stub", bounded=True)

GDP = registry.Series(
    series_id="test.gdp", category="Test", region="US", description="a revisable level",
    unit="x", cadence="quarterly", source="stub", fetcher="stub", bounded=True,
    revisable=True)


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "t.db")
        store.init_db(self.conn)
        store.upsert_catalog(self.conn, [
            {"series_id": s.series_id, "category": "Test", "region": "US",
             "description": s.description, "unit": "x", "native_periodicity": "daily",
             "source": "stub", "max_age_days": 10, "status": "ok", "notes": None}
            for s in (PRICE, GDP)])
        self.run_id = store.start_run(self.conn, "test")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def attach(self, series, pairs):
        rows, revisions = ingest.rows_to_attach(self.conn, series, frame(pairs))
        return store.insert_observations(self.conn, rows, self.run_id), revisions

    # --- non-revisable -----------------------------------------------------
    def test_first_ingest_attaches_everything(self):
        attached, revisions = self.attach(PRICE, [("2026-01-02", 1.0), ("2026-01-03", 2.0)])
        self.assertEqual((attached, revisions), (2, 0))

    def test_reingest_attaches_nothing(self):
        self.attach(PRICE, [("2026-01-02", 1.0), ("2026-01-03", 2.0)])
        attached, _ = self.attach(PRICE, [("2026-01-02", 1.0), ("2026-01-03", 2.0)])
        self.assertEqual(attached, 0, "an unchanged re-fetch must change nothing")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM observations WHERE series_id='test.price'").fetchone()[0], 2)

    def test_vintage_is_inert_for_non_revisable(self):
        self.attach(PRICE, [("2026-01-02", 1.0)])
        # Even a genuinely different value for a stored date cannot overwrite:
        # it collides on the primary key and is discarded.
        attached, _ = self.attach(PRICE, [("2026-01-02", 99.0)])
        self.assertEqual(attached, 0)
        self.assertEqual(store.read_series(self.conn, "test.price").iloc[-1]["value"], 1.0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM observations WHERE vintage_date <> date").fetchone()[0], 0)

    # --- revisable ---------------------------------------------------------
    def test_revision_is_appended_not_overwritten(self):
        self.attach(GDP, [("2026-01-01", 100.0)])
        attached, revisions = self.attach(GDP, [("2026-01-01", 101.5)])
        self.assertEqual((attached, revisions), (1, 1))

        rows = self.conn.execute(
            "SELECT date, vintage_date, value FROM observations "
            "WHERE series_id='test.gdp' ORDER BY vintage_date").fetchall()
        self.assertEqual(len(rows), 2, "the first print must still be there")
        self.assertEqual(rows[0]["value"], 100.0)
        self.assertEqual(rows[0]["vintage_date"], "2026-01-01")
        self.assertEqual(rows[1]["value"], 101.5)
        self.assertEqual(rows[1]["vintage_date"],
                         datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    def test_latest_observations_resolves_to_the_revision(self):
        self.attach(GDP, [("2026-01-01", 100.0)])
        self.attach(GDP, [("2026-01-01", 101.5)])
        df = store.read_series(self.conn, "test.gdp")
        self.assertEqual(len(df), 1, "the view must show one row per date")
        self.assertEqual(df.iloc[0]["value"], 101.5)

    def test_unchanged_revisable_value_offers_no_row(self):
        self.attach(GDP, [("2026-01-01", 100.0)])
        rows, revisions = ingest.rows_to_attach(self.conn, GDP, frame([("2026-01-01", 100.0)]))
        self.assertEqual((rows, revisions), ([], 0))

    def test_watermark_reads_through_the_view(self):
        self.attach(GDP, [("2026-01-01", 100.0), ("2026-04-01", 110.0)])
        self.assertEqual(store.watermark(self.conn, "test.gdp"), "2026-04-01")
        self.attach(GDP, [("2026-01-01", 101.5)])  # a revision to an OLD date
        self.assertEqual(store.watermark(self.conn, "test.gdp"), "2026-04-01",
                         "a revision must not move the watermark")

    def test_empty_fetch_is_survivable(self):
        self.assertEqual(ingest.rows_to_attach(self.conn, PRICE, None), ([], 0))


if __name__ == "__main__":
    unittest.main()
