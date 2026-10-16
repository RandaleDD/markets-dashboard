"""
Growth rates take their base from the CALENDAR, not from a position.

FRED's US CPI (CPIAUCNS) has no 2025-10 observation and never will. A
positional `shift(12)` across that hole measured thirteen months, and the
dashboard published Sep 2026 US CPI at 4.0% YoY -- 336.94 against Aug 2025's
323.976 -- where the true figure, against Sep 2025's 324.8, is 3.7%. Nothing
looked wrong: 4.0% is a plausible inflation print.

The rule held here: lag N means the observation exactly N periods earlier, and
a missing base drops the point rather than widening the window.
"""
from __future__ import annotations

import unittest

import pandas as pd

from db import export
from transform import regime
from transform.growth import growth_series, latest_growth


def _monthly(start, values, skip=()):
    dates = pd.date_range(start, periods=len(values), freq="MS")
    rows = [(d, v) for d, v in zip(dates, values) if d.strftime("%Y-%m") not in skip]
    return pd.DataFrame(rows, columns=["date", "value"])


class MonthlyHoleTest(unittest.TestCase):
    # Jan 2025 .. Dec 2026, index rising 1 a month from 100 (so the YoY across
    # any exact 12 months is 12 / base), with Oct 2025 missing.
    def setUp(self):
        self.values = [100.0 + i for i in range(24)]
        self.df = _monthly("2025-01-01", self.values, skip={"2025-10"})
        self.yoy = growth_series(self.df, 12, "M").set_index("date")["value"]

    def test_yoy_whose_base_is_the_hole_is_dropped(self):
        # Oct 2026's base is Oct 2025, which does not exist.
        self.assertNotIn(pd.Timestamp("2026-10-01"), self.yoy.index)

    def test_yoy_either_side_of_the_hole_is_exact(self):
        # Sep 2026 against Sep 2025 (index 8 -> 20), and Nov 2026 against Nov
        # 2025 (10 -> 22). A positional shift would have used Aug 2025 for
        # Sep 2026 -- the 13-month window this test exists to forbid.
        self.assertAlmostEqual(self.yoy[pd.Timestamp("2026-09-01")], (120 / 108 - 1) * 100)
        self.assertAlmostEqual(self.yoy[pd.Timestamp("2026-11-01")], (122 / 110 - 1) * 100)
        self.assertEqual(len(self.yoy), 11)  # Jan..Dec 2026 less Oct

    def test_latest_is_none_when_its_own_base_is_missing(self):
        upto_oct = self.df[self.df["date"] <= "2026-10-01"]
        self.assertIsNone(latest_growth(upto_oct, 12, "M"))
        # ...and it is not the September figure standing in for it.
        upto_sep = self.df[self.df["date"] <= "2026-09-01"]
        self.assertEqual(latest_growth(upto_sep, 12, "M"), round((120 / 108 - 1) * 100, 2))

    def test_short_lag_annualised_respects_the_hole(self):
        q = growth_series(self.df, 3, "M", annualise=4).set_index("date")["value"]
        self.assertNotIn(pd.Timestamp("2026-01-01"), q.index)  # base Oct 2025
        self.assertAlmostEqual(q[pd.Timestamp("2026-02-01")], ((113 / 110) ** 4 - 1) * 100)

    def test_export_helpers_take_the_calendar_lag(self):
        self.assertIsNone(export._pct_change(self.df[self.df["date"] <= "2026-10-01"], 12, "M"))
        g = export._growth_series(self.df, 12, "M").set_index("date")["value"]
        self.assertAlmostEqual(g[pd.Timestamp("2026-09-01")], (120 / 108 - 1) * 100)


class NoGapUnchangedTest(unittest.TestCase):
    """Where nothing is missing, calendar and positional lags must agree."""

    def _positional(self, df, lag, annualise=1):
        ratio = df["value"] / df["value"].shift(lag)
        return ((ratio ** annualise - 1) * 100).dropna().reset_index(drop=True)

    def test_monthly_quarterly_annual(self):
        cases = [
            (_monthly("2020-01-01", [100 * 1.003 ** i for i in range(60)]), 12, "M", 1),
            (_monthly("2020-01-01", [100 * 1.003 ** i for i in range(60)]), 3, "M", 4),
            (pd.DataFrame({"date": pd.date_range("2015-01-01", periods=40, freq="QS"),
                           "value": [50 + i * 0.7 for i in range(40)]}), 4, "Q", 1),
            (pd.DataFrame({"date": pd.date_range("2015-01-01", periods=40, freq="QS"),
                           "value": [50 + i * 0.7 for i in range(40)]}), 1, "Q", 4),
            (pd.DataFrame({"date": pd.date_range("2000-01-01", periods=20, freq="YS"),
                           "value": [10 + i for i in range(20)]}), 1, "A", 1),
        ]
        for df, lag, freq, ann in cases:
            with self.subTest(freq=freq, lag=lag):
                got = growth_series(df, lag, freq, ann)["value"].reset_index(drop=True)
                pd.testing.assert_series_equal(got, self._positional(df, lag, ann),
                                               check_names=False)

    def test_quarterly_hole_dropped_in_regime_yoy(self):
        df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=16, freq="QS"),
                           "value": [100.0 + i for i in range(16)]})
        df = df[df["date"] != pd.Timestamp("2022-04-01")]
        yoy = regime._yoy_from_levels(df, "Q").set_index("date")["value"]
        self.assertNotIn(pd.Timestamp("2023-04-01"), yoy.index)
        self.assertAlmostEqual(yoy[pd.Timestamp("2023-07-01")], (114 / 110 - 1) * 100)


if __name__ == "__main__":
    unittest.main()
