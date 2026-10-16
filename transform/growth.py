"""
Growth rates over a CALENDAR lag, not a positional one.

"Twelve observations back" and "twelve months back" are the same thing only
while a series has no holes. US CPI has none for 2025-10 -- a permanent gap in
FRED's CPIAUCNS -- and a positional `shift(12)` across it silently measured
thirteen months: Sep 2026 published at 4.0% YoY against a true 3.7%. So the
lag here is counted in PERIODS OF THE SERIES' OWN FREQUENCY, and the base is
looked up by period. When the base period is missing the result for that date
is dropped, never quietly taken from a longer window.

Dates are matched by the period they fall in, not by exact timestamp, because
agencies file a period under its first day but nothing here should depend on
that convention holding.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Publication frequency (the "M"/"Q"/"A" used throughout universe.py) -> the
# pandas period alias. "A" is deprecated in pandas for annual periods.
_PERIOD_ALIAS = {"M": "M", "Q": "Q", "A": "Y"}


def growth_series(df, lag: int, freq: str, annualise: float = 1):
    """
    Percent growth of each observation over the one exactly `lag` periods of
    `freq` earlier, optionally compounded (`annualise=4` turns a quarter's
    growth into a yearly rate). Returns a [date, value] frame, or None.

    A date whose base period has no observation is dropped, as is any
    non-positive ratio (which has no meaningful growth rate).
    """
    if df is None or df.empty:
        return None
    if freq not in _PERIOD_ALIAS:
        raise ValueError(f"unknown frequency {freq!r}; expected one of {sorted(_PERIOD_ALIAS)}")
    out = df.dropna(subset=["value"]).sort_values("date").copy()
    if out.empty:
        return None
    periods = pd.to_datetime(out["date"]).dt.to_period(_PERIOD_ALIAS[freq])
    # One observation per period; if a source ever filed two, the later wins,
    # the same rule a positional lookup on the sorted frame would have applied.
    by_period = pd.Series(out["value"].to_numpy(), index=periods.to_numpy())
    by_period = by_period[~by_period.index.duplicated(keep="last")]
    base = (periods - lag).map(by_period)
    ratio = out["value"].to_numpy() / base.to_numpy(dtype=float)
    ratio = pd.Series(ratio, index=out.index)
    # A zero base gives inf, which is no more a growth rate than a negative one.
    out["value"] = (ratio.where((ratio > 0) & np.isfinite(ratio)) ** annualise - 1.0) * 100.0
    out = out.dropna(subset=["value"])
    return out if not out.empty else None


def latest_growth(df, lag: int, freq: str, annualise: float = 1):
    """
    `growth_series` at the series' newest observation, rounded to 2dp -- or
    None when that observation's base period is missing. It is never the
    growth at an older date standing in for the newest one.
    """
    if df is None or df.empty:
        return None
    g = growth_series(df, lag, freq, annualise)
    if g is None:
        return None
    newest = df.dropna(subset=["value"])["date"].max()
    last = g.iloc[-1]
    if pd.Timestamp(last["date"]) != pd.Timestamp(newest):
        return None
    return round(float(last["value"]), 2)
