"""
A cadence key is not one setting, it is three, and the dangerous one is silent.

`MAX_AGE_DAYS` is the visible half: get it wrong and a series reads stale, or
stops reading stale when it should. The other two fail quietly. A key missing
from `PERIODICITY_OF_CADENCE` raises a KeyError deep in gap detection; a key
missing from `ingest.FULL_REFETCH_CADENCES` does something worse than raise --
a revisable series slower than weekly quietly reverts to the watermark window,
which is the exact condition that spliced two index bases into one stored GDP
series (see tests/test_basis_break.py and SPEC.md, "The rebasing trap").

Adding `monthly_month_end` for the BIS CPI dataflow in 2026-09 touched all
three. This test is what makes the next one impossible to half-finish.
"""
from __future__ import annotations

import unittest

from db import ingest, registry


class CadenceKeys(unittest.TestCase):
    def test_every_threshold_key_has_a_periodicity(self):
        missing = set(registry.MAX_AGE_DAYS) - set(registry.PERIODICITY_OF_CADENCE)
        self.assertEqual(missing, set(),
                         "cadence(s) with a staleness threshold but no periodicity: "
                         "gap detection will KeyError on them")

    def test_no_orphan_periodicity_keys(self):
        missing = set(registry.PERIODICITY_OF_CADENCE) - set(registry.MAX_AGE_DAYS)
        self.assertEqual(missing, set(),
                         "cadence(s) with a periodicity but no staleness threshold")

    def test_every_cadence_in_use_is_defined(self):
        for series in registry.all_series():
            with self.subTest(series=series.series_id):
                self.assertIn(series.cadence, registry.MAX_AGE_DAYS)
                self.assertIn(series.periodicity,
                              {"weekly", "monthly", "quarterly", "annual", "irregular"})

    def test_every_revisable_slower_than_weekly_series_refetches_in_full(self):
        """The rebasing trap. A revisable series that is not stored weekly must
        be re-asked in full, whatever its cadence is called."""
        for series in registry.all_series():
            if not series.revisable or series.cadence in registry.DOWNSAMPLED_TO_WEEKLY:
                continue
            with self.subTest(series=series.series_id, cadence=series.cadence):
                self.assertTrue(
                    ingest.refetch_in_full(series),
                    f"{series.series_id} is revisable at cadence '{series.cadence}' "
                    "but would be fetched through the watermark window")

    def test_bis_cpi_outlasts_the_gap_between_bis_releases(self):
        """BIS updates WS_LONG_CPI in the last week of each month, and dates
        each print to the first of the month it describes, so the newest one is
        ~85 days old the day before the next release. The threshold has to clear
        that, or every series still on BIS goes red in the back half of every
        month.

        Only China and Japan are left on BIS -- the rest moved to their national
        statistics offices on 2026-09-13 -- so this asks the registry which
        those are rather than naming ids that a later source switch would
        silently retire. That is how this test broke when cpi.US stopped
        existing, which is a failure mode worth not repeating.
        """
        bis = [s for s in registry.all_series()
               if s.series_id.startswith("cpi.") and "WS_LONG_CPI" in s.source]
        self.assertTrue(bis, "no CPI series on BIS -- has the source moved?")
        for series in bis:
            with self.subTest(series=series.series_id):
                self.assertGreater(series.max_age_days, 88)
                # ...and still catch a release BIS actually skipped (~115 days).
                self.assertLess(series.max_age_days, 115)

    def test_national_cpi_outlasts_a_first_of_month_publication_lag(self):
        """A national statistics office publishes month M during month M+1, and
        dates the print to the FIRST of M. So the newest figure's age is the
        publication lag plus a whole month, peaking just before the next
        release: ~71 days for the US at T+11, ~81 for Switzerland at T+21.

        Plain `monthly` at 70 would therefore read stale for the last days of
        every month even when every release is on time -- and `stale` is a
        failure here, not a pass.
        """
        national = [s for s in registry.all_series()
                    if s.cadence == "monthly_national"]
        self.assertTrue(national, "no series on the monthly_national cadence")
        for series in national:
            with self.subTest(series=series.series_id):
                self.assertGreater(series.max_age_days, 85)
                self.assertLess(series.max_age_days, 115)


if __name__ == "__main__":
    unittest.main()
