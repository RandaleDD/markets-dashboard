"""
Percentile / z-score context: where does today's reading sit against this
series' own history?

Two things this module deliberately does NOT do, both from V2-PLAN.md's
governing constraint:
  - It never combines series into a composite score.
  - It never labels a reading "cheap", "expensive", or anything directional.
A percentile against a series' own history is a fact about that series. That
is the whole remit.

The history passed in must be the SOURCE's full series as fetched, not the
trimmed archive that `compact_history` stores for the charts. The stored
archive only began accumulating when this project launched, so a "10y
percentile" computed from it would be meaningless for years. These are two
different jobs against the same fetch.
"""
from __future__ import annotations

import pandas as pd

# Below this many observations a percentile is noise dressed up as a number.
# 24 clears a 5y window on quarterly data (20 points would not).
MIN_OBS = 24

# A z-score divides by standard deviation; on a series that has barely moved
# that explodes. Below this the z is reported as None while the percentile,
# which needs no variance, still stands.
MIN_STD = 1e-9

DEFAULT_WINDOWS = (5, 10, "full")


def _window_slice(df: pd.DataFrame, window) -> pd.DataFrame | None:
    """Rows inside the window, or None if the series doesn't actually span it."""
    if window == "full":
        return df
    end = df["date"].max()
    cutoff = end - pd.DateOffset(years=int(window))
    # The series must genuinely reach back that far. A 3-year series must not
    # answer a 10-year question by quietly using the 3 years it has.
    if df["date"].min() > cutoff:
        return None
    return df[df["date"] >= cutoff]


def percentile_context(df: pd.DataFrame, latest_value=None,
                       windows=DEFAULT_WINDOWS, min_obs: int = MIN_OBS) -> dict:
    """
    df: the source's full [date, value] history.
    latest_value: defaults to the last observation in df.

    Returns {"5y": {...}, "10y": {...}, "full": {...}} with a None entry for
    any window the history does not cover. Each resolved entry carries `since`
    and `n` so the UI can state what the number is measured against, per the
    project's "every number states its definition" convention.
    """
    out = {}
    for w in windows:
        out[_label(w)] = None
    if df is None or df.empty:
        return out

    df = df.dropna(subset=["value"]).sort_values("date")
    if df.empty:
        return out
    if latest_value is None:
        latest_value = float(df.iloc[-1]["value"])
    latest_value = float(latest_value)

    for w in windows:
        sub = _window_slice(df, w)
        if sub is None or len(sub) < min_obs:
            continue
        vals = sub["value"].astype(float)
        n = int(len(vals))
        pct = float((vals <= latest_value).sum()) / n * 100.0
        std = float(vals.std(ddof=0))
        z = (latest_value - float(vals.mean())) / std if std > MIN_STD else None
        out[_label(w)] = {
            "pct": round(pct, 1),
            "z": round(z, 2) if z is not None else None,
            "n": n,
            "since": sub["date"].min().strftime("%Y-%m-%d"),
        }
    return out


def _label(window) -> str:
    return "full" if window == "full" else f"{window}y"


def has_any(context: dict | None) -> bool:
    """True when at least one window resolved — used to hide empty annotations."""
    return bool(context) and any(v is not None for v in context.values())
