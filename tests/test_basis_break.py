"""
The basis-break check, against a store built to contain the failure it exists
to catch.

On 2026-09-08 FRED re-chain-linked its Swiss real-GDP series, rescaling every
point by ~+0.70%. The weekly run's request window reached back 14 days -- less
than one quarterly observation -- so only the newest two points were re-offered
and restated, and the stored history became part old base and part new. No
check saw it: each half of the level series is perfectly well behaved, and the
damage only appears one layer downstream, in a growth rate computed across the
seam. Swiss GDP printed 3.06% YoY where the current vintage says 2.63%.

`db/ingest.FULL_REFETCH_CADENCES` stops it happening. This check is what
notices if it happens anyway -- a source that truncates a response, or a
cadence added without thinking about revisions.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from db import quality, registry, store

GDP = registry.Series(
    series_id="test.gdp", category="Test", region="CH", description="a revisable level",
    unit="x", cadence="quarterly", source="stub", fetcher="stub", bounded=True,
    revisable=True)

PRICE = registry.Series(
    series_id="test.price", category="Test", region="US", description="a price",
    unit="x", cadence="weekly", source="stub", fetcher="stub", bounded=True)

DATES = ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01", "2026-04-01"]
BASE = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]


class BasisBreakTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "t.db")
        store.init_db(self.conn)
        for s in (GDP, PRICE):
            store.upsert_catalog(self.conn, [{
                "series_id": s.series_id, "category": s.category, "region": s.region,
                "description": s.description, "unit": s.unit, "periodicity": s.periodicity,
                "source": s.source, "max_age_days": 10, "status": "ok", "notes": None}])
        # First prints: vintage_date == date, the whole history on one basis.
        store.insert_observations(self.conn, [
            (GDP.series_id, d, d, v) for d, v in zip(DATES, BASE)])

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def restate(self, dates, factor, vintage="2026-09-08"):
        store.insert_observations(self.conn, [
            (GDP.series_id, d, vintage, BASE[DATES.index(d)] * factor) for d in dates])

    def flags(self):
        return [dict(zip(("series_id", "date", "detail"), r)) for r in self.conn.execute(
            "SELECT series_id, date, detail FROM data_quality_flags WHERE flag_type='basis_break'")]

    def test_partial_rescaling_is_flagged(self):
        """The failure itself: a uniform +0.70% applied to the tail only."""
        self.restate(DATES[-2:], 1.00700)
        self.assertEqual(quality.check_basis_break(self.conn, GDP), 1)
        flag = self.flags()[0]
        self.assertEqual(flag["date"], "2026-01-01", "flag belongs on the oldest revised point")
        self.assertIn("+0.700%", flag["detail"])
        self.assertIn("2025-01-01", flag["detail"], "detail must name where the old basis starts")

    def test_a_single_rescaled_point_is_flagged(self):
        """The euro area only had one point restated, and still needed catching."""
        self.restate(DATES[-1:], 1.00548)
        self.assertEqual(quality.check_basis_break(self.conn, GDP), 1)

    def test_ordinary_revisions_are_not_flagged(self):
        """
        The same day's genuine national-accounts revisions moved DE by +0.019%
        and +0.122%, JP by +0.029% and +0.111%, NO by -0.027% and -0.030%.
        A check that fires on those is a check nobody reads.
        """
        for factor in (1.00019, 1.00122, 0.99973, 1.00111):
            with self.subTest(factor=factor):
                self.setUp()
                self.restate(DATES[-2:], factor)
                self.assertEqual(quality.check_basis_break(self.conn, GDP), 0)

    def test_a_rescaling_of_the_whole_history_is_not_a_break(self):
        """No seam, nothing spliced -- this is the fixed ingest doing its job."""
        self.restate(DATES, 1.00700)
        self.assertEqual(quality.check_basis_break(self.conn, GDP), 0)

    def test_new_dates_alone_are_not_a_break(self):
        """An ordinary run appends a new quarter and restates nothing."""
        store.insert_observations(self.conn, [(GDP.series_id, "2026-07-01", "2026-07-01", 106.0)])
        self.assertEqual(quality.check_basis_break(self.conn, GDP), 0)

    def test_non_revisable_series_are_skipped(self):
        store.insert_observations(self.conn, [
            (PRICE.series_id, d, d, v) for d, v in zip(DATES, BASE)])
        self.assertEqual(quality.check_basis_break(self.conn, PRICE), 0)


class OutlierWindowTest(unittest.TestCase):
    """
    The outlier check was unreachable for anything slower than weekly: a flat
    30-day window against a quarterly observation that is routinely 160 days
    old when it is the newest one published.
    """

    def test_window_covers_the_newest_observation_of_every_slow_series(self):
        for s in registry.all_series():
            if s.store_weekly:
                continue
            with self.subTest(series=s.series_id):
                self.assertGreater(quality.outlier_window_days(s), s.max_age_days,
                                   "a fresh observation must be able to enter the window")

    def test_series_stored_weekly_keep_the_tight_window(self):
        """
        Including policy rates. They are allowed to be 150 days old before
        counting as stale, but they are STORED weekly, so their observations
        are a week apart and 30 days already spans several.
        """
        for cadence in ("weekly", "policy"):
            s = next(x for x in registry.all_series() if x.cadence == cadence)
            with self.subTest(cadence=cadence):
                self.assertTrue(s.store_weekly)
                self.assertEqual(quality.outlier_window_days(s), quality.OUTLIER_WINDOW_DAYS)

    def test_quarterly_window_reaches_a_newly_published_quarter(self):
        """
        The concrete case: GDP for a quarter is dated to that quarter's first
        day and published about two months after it ends, so the newest print
        is ~160 days old. Under the old flat 30 days it could never be checked.
        """
        q = next(s for s in registry.all_series() if s.cadence == "quarterly")
        self.assertGreater(quality.outlier_window_days(q), 160)


if __name__ == "__main__":
    unittest.main()
