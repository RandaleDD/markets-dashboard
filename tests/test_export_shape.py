"""
The JSON contract the frontend reads.

`site/assets/app.js` consumes `latest.json` by key. Nothing type-checks that
boundary at runtime, so a renamed key or a dropped block shows up as a blank
panel on the live page with nothing wrong in the code -- which has already
happened once on this project (see NETWORK.md, "Deploy integrity").

These run against sample mode, so they need no network and no live database.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TOP_LEVEL = {
    "generated_at", "is_sample", "regions", "region_names", "chart_periods",
    "equity_indices", "currencies", "commodities", "macro", "yield_curves",
    "real_yield_curves", "inflation_expectations", "eurozone_spreads",
    "credit_spreads", "liquidity", "fx_hedging", "regime", "correlation",
    "cost_of_capital", "cost_of_capital_note", "valuation",
    "equity_risk_premia", "source_status", "data_quality",
}

# Weekly storage renamed these. If one comes back, something has regressed to
# daily-grain assumptions and the label on the page would be wrong.
RETIRED_KEYS = {"chg_1d_pct", "realized_vol_20d_pct", "realized_vol_60d_pct", "window_days"}


class ExportShape(unittest.TestCase):
    payload = None

    @classmethod
    def setUpClass(cls):
        import pipeline

        # Its own database AND its own output file: a test must not overwrite
        # the real site/data/latest.json as a side effect.
        cls.tmp = tempfile.TemporaryDirectory()
        cls.payload = pipeline.run("sample", db_path=str(Path(cls.tmp.name) / "s.db"),
                                   out_path=str(Path(cls.tmp.name) / "latest.json"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_top_level_keys(self):
        self.assertEqual(set(self.payload), TOP_LEVEL)

    def test_marked_as_sample(self):
        self.assertIs(self.payload["is_sample"], True)

    def test_is_json_serialisable_without_nan(self):
        # A raw NaN is not valid JSON and breaks the frontend's fetch outright.
        text = json.dumps(self.payload)
        self.assertNotRegex(text, r"\bNaN\b")
        self.assertNotRegex(text, r"\bInfinity\b")

    def test_no_retired_keys_anywhere(self):
        text = json.dumps(self.payload)
        for key in RETIRED_KEYS:
            self.assertNotIn(f'"{key}"', text, f"{key} is a daily-grain leftover")

    def test_equity_rows_carry_what_app_js_reads(self):
        rows = [r for rows in self.payload["equity_indices"].values() for r in rows]
        self.assertTrue(rows)
        for row in rows:
            for key in ("id", "name", "currency", "level", "chg_1w_pct", "chg_ytd_pct",
                        "drawdown_from_ath_pct", "realized_vol_13w_pct", "history"):
                self.assertIn(key, row, f"equity row {row.get('id')} is missing {key}")

    def test_correlation_reports_its_window_in_weeks(self):
        windows = self.payload["correlation"]["windows"]
        self.assertTrue(windows)
        for matrix in windows.values():
            self.assertIn("window_weeks", matrix)
            self.assertNotIn("window_days", matrix)

    def test_curves_carry_every_region(self):
        self.assertEqual(set(self.payload["yield_curves"]), set(self.payload["regions"]))

    def test_data_quality_block_is_populated(self):
        dq = self.payload["data_quality"]
        for key in ("series", "fresh", "stale", "missing", "observations"):
            self.assertIn(key, dq)
        self.assertEqual(dq["series"], dq["fresh"] + dq["stale"] + dq["missing"])

    def test_app_js_reads_only_keys_the_export_emits(self):
        """Every DATA.<key> app.js touches must exist in the payload."""
        js = (ROOT / "site" / "assets" / "app.js").read_text()
        for key in set(re.findall(r"\bDATA\.([A-Za-z_][A-Za-z0-9_]*)", js)):
            self.assertIn(key, self.payload, f"app.js reads DATA.{key}, export omits it")


if __name__ == "__main__":
    unittest.main()
