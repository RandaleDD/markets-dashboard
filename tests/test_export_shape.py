"""
The JSON contract the frontend reads.

`site/assets/app.js` consumes `latest.json` by key. Nothing type-checks that
boundary at runtime, so a renamed key or a dropped block shows up as a blank
panel on the live page with nothing wrong in the code -- which has already
happened once on this project (see SPEC.md, "Deploy integrity").

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
    "credit_spreads", "corporate_spreads_to_govt",
    "corporate_spread_unavailable", "liquidity", "real_rates", "regime",
    "correlation",
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

    def test_price_levels_carry_what_app_js_reads(self):
        pl = self.payload["macro"]["price_levels"]
        for key in ("periods", "regions", "history", "note", "chf_note"):
            self.assertIn(key, pl)
        local, chf = pl["history"]["local"], pl["history"]["chf"]
        # The macro tab's regions, not the dashboard's eight: India and Brazil
        # are on the Price Levels chart too.
        self.assertEqual(set(local), set(self.payload["macro"]["regions"]))
        for region, points in local.items():
            self.assertIn("basis", pl["regions"][region])
            # Month starts, ascending: the chart's common-base logic matches
            # dates exactly across regions, so a mid-month date would never
            # line up with anyone.
            dates = [d for d, _ in points]
            self.assertEqual(dates, sorted(dates))
            self.assertTrue(all(d.endswith("-01") for d in dates), region)
        # Switzerland measured in CHF is Switzerland -- nothing to convert.
        self.assertEqual(chf["CH"], local["CH"])
        # Every other region's CHF series is a different quantity, not a copy.
        self.assertNotEqual(chf["US"], local["US"])

    def test_macro_regions_extend_the_eight_and_nothing_else_does(self):
        macro = self.payload["macro"]["regions"]
        self.assertEqual(macro[:len(self.payload["regions"])], self.payload["regions"])
        self.assertIn("IN", macro)
        self.assertIn("BR", macro)
        # Macro-only means macro-only: no snapshot region, curve or index.
        self.assertNotIn("IN", self.payload["regions"])
        self.assertNotIn("IN", self.payload["yield_curves"])

    def test_gdp_rows_carry_nominal_growth(self):
        gdp = self.payload["macro"]["gdp"]
        self.assertEqual(set(gdp), set(self.payload["macro"]["regions"]))
        for region, row in gdp.items():
            for key in ("yoy_pct", "qoq_ann_pct", "nominal_yoy_pct",
                        "nominal_qoq_ann_pct", "nominal_period_label"):
                self.assertIn(key, row, f"{region} GDP row is missing {key}")
            self.assertIsNotNone(row["nominal_yoy_pct"], region)

    def test_cpi_carries_figures_on_gdps_quarter(self):
        macro = self.payload["macro"]
        for region, row in macro["inflation"].items():
            for key in ("q_yoy_pct", "q_qoq_ann_pct", "q_period_label"):
                self.assertIn(key, row, f"{region} CPI row is missing {key}")
            # Labelled with GDP's quarter, which is the whole point.
            self.assertEqual(row["q_period_label"], macro["gdp"][region]["period_label"], region)

    def test_forecasts_carry_what_app_js_reads(self):
        fc = self.payload["macro"]["forecasts"]
        for key in ("edition", "projection_from", "years", "regions", "definition"):
            self.assertIn(key, fc)
        self.assertEqual(len(fc["years"]), 2)
        self.assertEqual(set(fc["regions"]), set(self.payload["macro"]["regions"]))
        for region, row in fc["regions"].items():
            for leg in ("gdp", "nominal", "cpi"):
                self.assertEqual(set(row[leg]), {str(y) for y in fc["years"]}, region)

    def test_gdp_levels_carry_what_app_js_reads(self):
        gl = self.payload["macro"]["gdp_levels"]
        for key in ("periods", "projection_from", "history", "note", "units"):
            self.assertIn(key, gl)
        for measure in ("real_index", "nominal_usd", "ppp"):
            series = gl["history"][measure]
            expected = set(self.payload["macro"]["regions"]) - set(
                gl.get("unavailable", {}).get(measure, []))
            self.assertEqual(set(series), expected, measure)
            for region, points in series.items():
                years = [int(d[:4]) for d, _ in points]
                # Consecutive years, every one a January 1st: the chart's
                # common base matches dates exactly across regions.
                self.assertEqual(years, list(range(years[0], years[-1] + 1)), region)
                self.assertTrue(all(d.endswith("-01-01") for d, _ in points))
                # Projections are in the series, past the boundary.
                self.assertGreaterEqual(years[-1], gl["projection_from"], region)

    def test_snapshot_history_carries_ten_year_and_nominal_growth(self):
        h = self.payload["macro"]["history"]
        for region in self.payload["regions"]:
            self.assertTrue(h["yield_10y"].get(region), region)
            self.assertTrue(h["gdp_nominal_yoy"].get(region), region)

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
