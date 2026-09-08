"""
Flags close themselves once their condition clears.

A flag that stays open after it stops being true is worse than no flag: the
Norway GDP staleness flag raised on 2026-08-29 was still showing on 2026-09-08
against a series that had been fresh for hours, and an indicator that is
permanently red is one you learn to scroll past.

The whole point of the design is the two ways it must NOT close a flag:

  - a check that did not run (no data, too few observations to calibrate, a
    periodicity it does not judge) proves nothing, so it closes nothing
  - a check that runs inside a window must not close findings OUTSIDE that
    window, or a gap that simply aged past GAP_WINDOW_DAYS would be declared
    fixed by a check that had stopped looking at it
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import pandas as pd

from db import quality, registry, store

WEEKLY = registry.Series(
    series_id="test.weekly", category="Test", region="US", description="a weekly price",
    unit="x", cadence="weekly", source="stub", fetcher="stub", bounded=True)

QUARTERLY = registry.Series(
    series_id="test.gdp", category="Test", region="CH", description="a quarterly level",
    unit="x", cadence="quarterly", source="stub", fetcher="stub", bounded=True,
    revisable=True)


def frame(dates, values=None):
    values = values if values is not None else [1.0] * len(dates)
    return pd.DataFrame({"date": pd.to_datetime(dates), "value": values})


class FlagResolution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "t.db")
        store.init_db(self.conn)
        for s in (WEEKLY, QUARTERLY):
            store.upsert_catalog(self.conn, [{
                "series_id": s.series_id, "category": s.category, "region": s.region,
                "description": s.description, "unit": s.unit, "periodicity": s.periodicity,
                "source": s.source, "max_age_days": s.max_age_days, "status": "ok",
                "notes": None}])

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def open_flags(self):
        return store.open_flag_keys(self.conn)

    def reconcile(self, series, flag_type, findings):
        return quality._reconcile(self.conn, self.open_flags(), series.series_id,
                                  flag_type, findings)

    # -- staleness, the case that prompted this ------------------------------
    def test_stale_flag_closes_once_the_series_catches_up(self):
        old = (pd.Timestamp.now().normalize() - timedelta(days=400)).strftime("%Y-%m-%d")
        store.raise_flag(self.conn, QUARTERLY.series_id, old, "stale", "was stale")
        self.assertEqual(len(self.open_flags()), 1)

        fresh = (pd.Timestamp.now().normalize() - timedelta(days=30)).strftime("%Y-%m-%d")
        findings = quality.check_staleness(self.conn, QUARTERLY, frame([fresh]))
        self.assertTrue(findings.evaluated)
        self.assertEqual(findings.found, frozenset(), "not stale, so nothing found")
        self.assertEqual(self.reconcile(QUARTERLY, "stale", findings), 1)
        self.assertEqual(self.open_flags(), set())

    def test_a_still_stale_series_keeps_its_flag(self):
        old = (pd.Timestamp.now().normalize() - timedelta(days=400)).strftime("%Y-%m-%d")
        store.raise_flag(self.conn, QUARTERLY.series_id, old, "stale", "was stale")
        findings = quality.check_staleness(self.conn, QUARTERLY, frame([old]))
        self.assertEqual(findings.found, frozenset({old}))
        self.assertEqual(findings.raised, 0, "already open, so nothing newly raised")
        self.assertEqual(self.reconcile(QUARTERLY, "stale", findings), 0)
        self.assertEqual(len(self.open_flags()), 1, "re-detected, so it must stay open")

    def test_resolved_flag_is_kept_not_deleted(self):
        old = (pd.Timestamp.now().normalize() - timedelta(days=400)).strftime("%Y-%m-%d")
        store.raise_flag(self.conn, QUARTERLY.series_id, old, "stale", "was stale")
        fresh = (pd.Timestamp.now().normalize() - timedelta(days=30)).strftime("%Y-%m-%d")
        self.reconcile(QUARTERLY, "stale",
                       quality.check_staleness(self.conn, QUARTERLY, frame([fresh])))
        row = self.conn.execute(
            "SELECT resolved, detail, raised_at FROM data_quality_flags").fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "was stale", "the finding's text survives closure")
        self.assertIsNotNone(row[2], "and so does when it was first raised")

    # -- the two ways it must not close a flag -------------------------------
    def test_a_check_that_did_not_run_closes_nothing(self):
        old = (pd.Timestamp.now().normalize() - timedelta(days=400)).strftime("%Y-%m-%d")
        store.raise_flag(self.conn, QUARTERLY.series_id, old, "stale", "was stale")
        # An empty fetch is not evidence the series became fresh.
        findings = quality.check_staleness(self.conn, QUARTERLY, None)
        self.assertFalse(findings.evaluated)
        self.assertEqual(self.reconcile(QUARTERLY, "stale", findings), 0)
        self.assertEqual(len(self.open_flags()), 1)

    def test_too_few_observations_to_calibrate_closes_nothing(self):
        store.raise_flag(self.conn, WEEKLY.series_id, "2026-01-02", "outlier", "was odd")
        short = frame(pd.date_range("2026-01-02", periods=5, freq="7D"))
        findings = quality.check_outliers(self.conn, WEEKLY, short)
        self.assertFalse(findings.evaluated)
        self.assertEqual(self.reconcile(WEEKLY, "outlier", findings), 0)
        self.assertEqual(len(self.open_flags()), 1)

    def test_a_finding_older_than_the_window_is_left_alone(self):
        """
        The trap this design exists to avoid: a gap that aged past the check's
        window would otherwise be closed by a check that stopped looking.
        """
        stale_date = (pd.Timestamp.now().normalize()
                      - timedelta(days=quality.GAP_WINDOW_DAYS + 200)).strftime("%Y-%m-%d")
        store.raise_flag(self.conn, WEEKLY.series_id, stale_date, "gap", "an old gap")
        # A clean recent history: the check runs, finds nothing, but its window
        # never reached the flagged date.
        recent = frame(pd.date_range(pd.Timestamp.now().normalize() - timedelta(days=140),
                                     periods=20, freq="7D"))
        findings = quality.check_gaps(self.conn, WEEKLY, recent)
        self.assertTrue(findings.evaluated)
        self.assertEqual(findings.found, frozenset())
        self.assertIsNotNone(findings.since)
        self.assertEqual(self.reconcile(WEEKLY, "gap", findings), 0)
        self.assertEqual(len(self.open_flags()), 1, "outside the window, so untouched")

    def test_a_filled_gap_inside_the_window_does_close(self):
        recent = pd.date_range(pd.Timestamp.now().normalize() - timedelta(days=140),
                               periods=20, freq="7D")
        inside = recent[10].strftime("%Y-%m-%d")
        store.raise_flag(self.conn, WEEKLY.series_id, inside, "gap", "a gap since filled")
        findings = quality.check_gaps(self.conn, WEEKLY, frame(recent))
        self.assertEqual(findings.found, frozenset())
        self.assertEqual(self.reconcile(WEEKLY, "gap", findings), 1)
        self.assertEqual(self.open_flags(), set())

    def test_only_the_matching_series_and_type_are_touched(self):
        old = (pd.Timestamp.now().normalize() - timedelta(days=400)).strftime("%Y-%m-%d")
        store.raise_flag(self.conn, QUARTERLY.series_id, old, "stale", "s")
        store.raise_flag(self.conn, QUARTERLY.series_id, old, "gap", "g")
        store.raise_flag(self.conn, WEEKLY.series_id, old, "stale", "other series")
        fresh = (pd.Timestamp.now().normalize() - timedelta(days=30)).strftime("%Y-%m-%d")
        self.reconcile(QUARTERLY, "stale",
                       quality.check_staleness(self.conn, QUARTERLY, frame([fresh])))
        left = {(sid, ftype) for sid, ftype, _ in self.open_flags()}
        self.assertEqual(left, {(QUARTERLY.series_id, "gap"), (WEEKLY.series_id, "stale")})

    # -- end to end ----------------------------------------------------------
    def test_run_all_reports_what_it_closed(self):
        old = (pd.Timestamp.now().normalize() - timedelta(days=400)).strftime("%Y-%m-%d")
        store.raise_flag(self.conn, QUARTERLY.series_id, old, "stale", "was stale")
        fresh = (pd.Timestamp.now().normalize() - timedelta(days=30)).strftime("%Y-%m-%d")
        store.insert_observations(self.conn, [(QUARTERLY.series_id, fresh, fresh, 1.0)])
        report = quality.run_all(self.conn, [QUARTERLY])
        self.assertEqual(report["flags_resolved_this_run"], {"stale": 1})
        self.assertEqual(report["open_flags"], {})

    def test_a_flag_raised_this_run_is_not_closed_by_it(self):
        very_old = (pd.Timestamp.now().normalize() - timedelta(days=900)).strftime("%Y-%m-%d")
        store.insert_observations(self.conn, [(QUARTERLY.series_id, very_old, very_old, 1.0)])
        report = quality.run_all(self.conn, [QUARTERLY])
        self.assertEqual(report["flags_raised_this_run"], {"stale": 1})
        self.assertEqual(report.get("flags_resolved_this_run"), {})
        self.assertEqual(report["open_flags"], {"stale": 1})


if __name__ == "__main__":
    unittest.main()
