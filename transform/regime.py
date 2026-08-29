"""
Growth / inflation regime coordinates.

Descriptive only, per V2-PLAN.md's governing constraint. Quadrant names below
describe what the data is doing, not what anyone should do about it.

**The definition, stated once here and carried into the UI label** (per the
project's "every number states its definition" convention):

    x = change in real GDP year-on-year growth, over one quarter, in pp
    y = change in headline CPI year-on-year, over one quarter, in pp

Both axes are the *change in the rate*, not the rate itself. A region sitting
at +4% growth and slowing appears on the left-hand side, because the question
the map answers is "which direction is this moving", not "how fast is it". The
level is carried alongside each point so the two are never confused.
"""
from __future__ import annotations

import pandas as pd

AXIS_DEFINITION = ("Axes are the one-quarter change in the year-on-year rate, "
                   "in percentage points — direction of travel, not level. "
                   "Levels are shown alongside each point.")

QUADRANTS = {
    "growth_up_infl_up": "Growth rising · inflation rising",
    "growth_up_infl_down": "Growth rising · inflation falling",
    "growth_down_infl_up": "Growth falling · inflation rising",
    "growth_down_infl_down": "Growth falling · inflation falling",
}


def _yoy_from_levels(df: pd.DataFrame, periods_per_year: int) -> pd.DataFrame | None:
    """Year-on-year percent change from a level series."""
    if df is None or len(df) <= periods_per_year:
        return None
    out = df.dropna(subset=["value"]).sort_values("date").copy()
    out["value"] = (out["value"] / out["value"].shift(periods_per_year) - 1.0) * 100.0
    return out.dropna(subset=["value"])


def _to_quarterly(df: pd.DataFrame) -> pd.DataFrame | None:
    """Quarter-end sampling so a monthly CPI series aligns with quarterly GDP."""
    if df is None or df.empty:
        return None
    out = df.dropna(subset=["value"]).sort_values("date").set_index("date")
    out = out.resample("QE").last().dropna(subset=["value"]).reset_index()
    return out if not out.empty else None


# Observations per year, per GDP publication frequency. The UK moved to ONS's
# monthly index, so "year on year" is 12 observations back there -- reading it
# as 4 would report a one-third-of-a-year change as an annual one.
PERIODS_PER_YEAR = {"M": 12, "Q": 4, "A": 1}


def regime_coordinates(gdp_level_df, cpi_yoy_df, gdp_freq: str = "Q",
                       quarters: int = 8) -> list:
    """
    gdp_level_df: real GDP *levels* (the pipeline's GDP source).
    cpi_yoy_df:   CPI already expressed year-on-year (the BIS source).

    Returns the most recent `quarters` aligned points, oldest first.
    """
    gdp_yoy = _yoy_from_levels(gdp_level_df, PERIODS_PER_YEAR.get(gdp_freq, 4))
    g = _to_quarterly(gdp_yoy)
    c = _to_quarterly(cpi_yoy_df)
    if g is None or c is None:
        return []

    merged = g.merge(c, on="date", suffixes=("_g", "_c")).sort_values("date")
    if len(merged) < 2:
        return []

    merged["growth_delta"] = merged["value_g"].diff()
    merged["inflation_delta"] = merged["value_c"].diff()
    merged = merged.dropna(subset=["growth_delta", "inflation_delta"])
    if merged.empty:
        return []

    # An annual GDP source (China) survives quarterly resampling as one point a
    # year, so its "change since the previous point" spans a year, not a
    # quarter. The axis label says quarter, so the point must declare that it
    # is measured differently rather than sit on the same axis unmarked.
    # A monthly source (UK) resamples to genuine quarter-ends, so it is on the
    # same footing as the quarterly regions.
    delta_basis = "year" if gdp_freq == "A" else "quarter"

    return [
        {
            "date": r["date"].strftime("%Y-%m-%d"),
            "delta_basis": delta_basis,
            "growth_yoy": round(float(r["value_g"]), 2),
            "inflation_yoy": round(float(r["value_c"]), 2),
            "growth_delta": round(float(r["growth_delta"]), 2),
            "inflation_delta": round(float(r["inflation_delta"]), 2),
            "quadrant": quadrant_of(r["growth_delta"], r["inflation_delta"]),
        }
        for _, r in merged.tail(quarters).iterrows()
    ]


def quadrant_of(growth_delta, inflation_delta) -> str:
    g = "up" if growth_delta >= 0 else "down"
    i = "up" if inflation_delta >= 0 else "down"
    return f"growth_{g}_infl_{i}"
