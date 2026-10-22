"""
The seasonally adjusted 3-month inflation rate (transform/growth).

Every stored CPI index is NSA, and the Growth & Inflation table's QoQ view
sets its 3-month rate beside seasonally adjusted GDP. What these hold:
  - a pure seasonal pattern on a steady trend comes out as the trend;
  - no figure leans on data from its own year or later (no look-ahead);
  - a missing month removes the windows that span it rather than stretching.
"""
from __future__ import annotations

import math
import unittest

import pandas as pd

from transform.growth import (growth_series, latest_seasonally_adjusted_growth,
                              quarter_average, seasonally_adjusted_growth_series,
                              seasonally_adjusted_levels)

TREND = 0.25 / 100            # 0.25% a month, ~3.04% a year
SEASON = [0.6, -0.4, 0.3, 0.1, -0.2, 0.0, -0.5, 0.2, 0.4, -0.3, 0.1, -0.3]  # % a month, sums to 0


def seasonal_index(years: int = 12) -> pd.DataFrame:
    dates = pd.date_range("2014-01-01", periods=years * 12, freq="MS")
    level, values = 100.0, []
    for d in dates:
        level *= math.exp(TREND + SEASON[d.month - 1] / 100)
        values.append(level)
    return pd.DataFrame({"date": dates, "value": values})


class SeasonalAdjustment(unittest.TestCase):
    def test_a_pure_season_on_a_trend_comes_out_as_the_trend(self):
        df = seasonal_index()
        expected = (math.exp(TREND * 12) - 1) * 100
        self.assertAlmostEqual(latest_seasonally_adjusted_growth(df), round(expected, 2), places=2)
        # The unadjusted rate is visibly off, which is the reason this exists.
        raw = growth_series(df, 3, "M", annualise=4).iloc[-1]["value"]
        self.assertGreater(abs(raw - expected), 1.0)

    def test_no_figure_uses_its_own_year_or_later(self):
        df = seasonal_index()
        before = seasonally_adjusted_growth_series(df)
        shocked = df.copy()
        shocked.loc[shocked["date"] >= "2024-06-01", "value"] *= 1.05
        after = seasonally_adjusted_growth_series(shocked)
        early = lambda g: g[g["date"] < "2024-06-01"].reset_index(drop=True)
        pd.testing.assert_frame_equal(early(before), early(after))

    def test_too_little_history_gives_nothing(self):
        self.assertIsNone(seasonally_adjusted_growth_series(seasonal_index(years=4)))

    def test_a_missing_month_drops_the_windows_that_span_it(self):
        df = seasonal_index(years=14)   # through 2027, so 2026 exists
        df = df[df["date"] != "2025-10-01"]
        g = seasonally_adjusted_growth_series(df)
        months = set(pd.to_datetime(g["date"]).dt.strftime("%Y-%m"))
        for m in ("2025-10", "2025-11", "2025-12", "2026-01"):
            self.assertNotIn(m, months)
        self.assertIn("2026-02", months)


class QuarterGrid(unittest.TestCase):
    """CPI on GDP's quarter: the Growth & Inflation table's CPI column."""

    def test_adjusted_levels_remove_the_season_from_a_level(self):
        sa = seasonally_adjusted_levels(seasonal_index())
        g = growth_series(sa, 1, "M")
        # Every month's change is the trend once the season is out.
        self.assertAlmostEqual(g["value"].tail(24).std(), 0.0, places=6)
        self.assertAlmostEqual(g["value"].iloc[-1], (math.exp(TREND) - 1) * 100, places=6)

    def test_quarter_average_drops_an_incomplete_quarter(self):
        df = seasonal_index()
        df = df[df["date"] != "2025-10-01"]
        q = quarter_average(df)
        quarters = set(pd.to_datetime(q["date"]).dt.strftime("%Y-%m"))
        self.assertNotIn("2025-10", quarters)
        self.assertIn("2025-07", quarters)
        self.assertTrue(all(pd.to_datetime(q["date"]).dt.month.isin([1, 4, 7, 10])))


if __name__ == "__main__":
    unittest.main()
