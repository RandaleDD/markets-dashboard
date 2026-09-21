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

# A series whose stored values are ALREADY percentages. The unit is what marks
# it (registry.Series.is_rate), and it changes which scale the check reasons on.
RATE = registry.Series(
    series_id="test.cpi", category="Test", region="EZ", description="a revisable rate",
    unit="% YoY", cadence="monthly_national", source="stub", fetcher="stub",
    bounded=True, revisable=True)

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
        self.assertEqual(quality.check_basis_break(self.conn, GDP).raised, 1)
        flag = self.flags()[0]
        self.assertEqual(flag["date"], "2026-01-01", "flag belongs on the oldest revised point")
        self.assertIn("+0.700%", flag["detail"])
        self.assertIn("2025-01-01", flag["detail"], "detail must name where the old basis starts")

    def test_a_single_rescaled_point_is_flagged(self):
        """The euro area only had one point restated, and still needed catching."""
        self.restate(DATES[-1:], 1.00548)
        self.assertEqual(quality.check_basis_break(self.conn, GDP).raised, 1)

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
                self.assertEqual(quality.check_basis_break(self.conn, GDP).raised, 0)

    def test_a_rescaling_of_the_whole_history_is_not_a_break(self):
        """No seam, nothing spliced -- this is the fixed ingest doing its job."""
        self.restate(DATES, 1.00700)
        self.assertEqual(quality.check_basis_break(self.conn, GDP).raised, 0)

    def test_new_dates_alone_are_not_a_break(self):
        """An ordinary run appends a new quarter and restates nothing."""
        store.insert_observations(self.conn, [(GDP.series_id, "2026-07-01", "2026-07-01", 106.0)])
        self.assertEqual(quality.check_basis_break(self.conn, GDP).raised, 0)

    def test_non_revisable_series_are_skipped(self):
        store.insert_observations(self.conn, [
            (PRICE.series_id, d, d, v) for d, v in zip(DATES, BASE)])
        self.assertEqual(quality.check_basis_break(self.conn, PRICE).raised, 0)


class RateBasisBreakTest(unittest.TestCase):
    """
    A rate series is judged on percentage points and on how much of its history
    moved -- never on a ratio.

    On 2026-09-19 the euro area's August HICP was revised 3.3 -> 3.2, an
    entirely ordinary 0.1pp correction of a single print. Measured as a ratio
    that is -3.03%, which sailed past BASIS_BREAK_PCT and raised a flag that
    stayed open for two days claiming the series had been spliced. Meanwhile
    the real event on record -- cpi.DE the week before, when Eurostat changed
    dataflow AND ECOICOP version -- was ALSO about 0.1pp. Magnitude alone
    cannot tell the two apart. The share of history restated can: 0.3% against
    84%.
    """

    # 36 monthly points at a plausible inflation rate, on one basis. Every date
    # must sort BEFORE the restatement vintage below: `newest_vintage` is a
    # max() over the vintage column, and a first print carries its own date as
    # its vintage, so a fixture running past the vintage would make the check
    # treat a first print as the newest vintage and measure nothing.
    DATES = [f"{y}-{m:02d}-01" for y in (2023, 2024, 2025) for m in range(1, 13)]
    BASE = [2.0 + (i % 7) * 0.1 for i in range(36)]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "t.db")
        store.init_db(self.conn)
        store.upsert_catalog(self.conn, [{
            "series_id": RATE.series_id, "category": RATE.category, "region": RATE.region,
            "description": RATE.description, "unit": RATE.unit,
            "periodicity": RATE.periodicity, "source": RATE.source,
            "max_age_days": 70, "status": "ok", "notes": None}])
        store.insert_observations(self.conn, [
            (RATE.series_id, d, d, v) for d, v in zip(self.DATES, self.BASE)])

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def restate(self, dates, delta_pp, vintage="2026-09-19"):
        store.insert_observations(self.conn, [
            (RATE.series_id, d, vintage, self.BASE[self.DATES.index(d)] + delta_pp)
            for d in dates])

    def test_the_series_is_recognised_as_a_rate(self):
        self.assertTrue(RATE.is_rate)
        self.assertFalse(GDP.is_rate, "a level must not take the rate path")

    def test_an_ordinary_one_print_revision_is_not_flagged(self):
        """cpi.EZ, 2026-09-19: 3.3 -> 3.2 on the newest month and nothing else."""
        self.restate(self.DATES[-1:], -0.1)
        findings = quality.check_basis_break(self.conn, RATE)
        self.assertEqual(findings.raised, 0)
        self.assertTrue(findings.evaluated,
                        "must still evaluate, or an open flag could never close")
        self.assertEqual(findings.found, frozenset())

    def test_a_large_one_print_revision_is_flagged(self):
        """0.1pp is noise; 0.6pp on a 2% rate is somebody changing the measure."""
        self.restate(self.DATES[-1:], 0.6)
        self.assertEqual(quality.check_basis_break(self.conn, RATE).raised, 1)

    def test_most_of_history_restated_is_flagged_even_when_small(self):
        """
        The cpi.DE case: a methodology change moved 299 of 355 points by about
        0.1pp each. Too small for the magnitude test, and exactly what the
        share test exists to catch.
        """
        self.restate(self.DATES[6:], 0.1)
        findings = quality.check_basis_break(self.conn, RATE)
        self.assertEqual(findings.raised, 1)
        detail = self.conn.execute(
            "SELECT detail FROM data_quality_flags WHERE flag_type='basis_break'"
        ).fetchone()[0]
        self.assertIn("pp", detail, "a rate's flag must be worded in percentage points")
        self.assertNotIn("%,", detail, "a ratio has no meaning on a rate series")

    def test_a_restatement_of_the_whole_history_is_not_a_break(self):
        """No seam: every point is on the new basis."""
        self.restate(self.DATES, 0.9)
        self.assertEqual(quality.check_basis_break(self.conn, RATE).raised, 0)


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
