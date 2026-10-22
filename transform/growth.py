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


# ---------------------------------------------------------------------------
# Seasonally adjusted short-horizon inflation.
#
# Every CPI index stored here is NOT seasonally adjusted -- the headline
# convention, and what the YoY rate wants, since a 12-month change cancels the
# season. A 3-month change does not: measured on the stored indices, German
# HICP's latest "quarter annualised" read 6.4%, India's 11.2% and Brazil's
# -0.4%, mostly January sales, monsoon food prices and the like. Set beside
# real GDP, which IS seasonally adjusted, that would make the QoQ view
# inconsistent within one table row.
#
# So the season is removed here, simply and transparently: each calendar
# month's typical log change relative to its year's average, measured over the
# previous YEARS complete calendar years, is subtracted before compounding.
# Only years strictly before the observation's own year are used, so no figure
# ever leans on data published after it. This is a classical additive-in-logs
# seasonal factor, not X-13: it ignores trading days and moving holidays, and
# the result is labelled as adjusted HERE rather than by the agency.
# ---------------------------------------------------------------------------
SA_YEARS = 8
SA_MIN_YEARS = 5


def _seasonal_factors(dlog: pd.Series, year: int, years: int, min_years: int):
    """{calendar month: mean deviation} over complete years before `year`."""
    window = dlog[(dlog.index.year < year) & (dlog.index.year >= year - years)]
    devs = []
    for _, grp in window.groupby(window.index.year):
        if len(grp) != 12:
            continue  # an incomplete year has no meaningful annual mean
        devs.append(grp.groupby(grp.index.month).mean() - grp.mean())
    if len(devs) < min_years:
        return None
    return pd.concat(devs, axis=1).mean(axis=1).to_dict()


def seasonally_adjusted_growth_series(df, months: int = 3, annualise: float = 4,
                                      years: int = SA_YEARS,
                                      min_years: int = SA_MIN_YEARS):
    """
    Percent growth of a MONTHLY, not-seasonally-adjusted index over the last
    `months` months, with each month's seasonal factor removed, compounded by
    `annualise`. A [date, value] frame, or None.

    Months are matched by calendar period, like growth_series: a missing month
    removes every window that spans it rather than stretching one.
    """
    if df is None or df.empty:
        return None
    out = df.dropna(subset=["value"]).sort_values("date")
    out = out[out["value"] > 0]
    if out.empty:
        return None
    periods = pd.to_datetime(out["date"]).dt.to_period("M")
    level = pd.Series(np.log(out["value"].to_numpy(dtype=float)), index=periods.to_numpy())
    level = level[~level.index.duplicated(keep="last")]
    prev = (level.index - 1).map(level)
    dlog = pd.Series(level.to_numpy() - np.asarray(prev, dtype=float),
                     index=level.index.to_timestamp()).dropna()
    if dlog.empty:
        return None
    by_period = pd.Series(dlog.to_numpy(), index=dlog.index.to_period("M"))

    factors_by_year: dict[int, dict | None] = {}
    dates, values = [], []
    for ts in dlog.index:
        if ts.year not in factors_by_year:
            factors_by_year[ts.year] = _seasonal_factors(dlog, ts.year, years, min_years)
        factors = factors_by_year[ts.year]
        if factors is None:
            continue
        p = ts.to_period("M")
        legs = [by_period.get(p - k) for k in range(months)]
        if any(v is None or pd.isna(v) for v in legs):
            continue
        adjusted = sum(v - factors[(p - k).month] for k, v in enumerate(legs))
        dates.append(ts)
        values.append((np.exp(adjusted * annualise) - 1.0) * 100.0)
    if not dates:
        return None
    # Back onto the source's own dates (the first of each month here).
    return pd.DataFrame({"date": dates, "value": values})


def latest_seasonally_adjusted_growth(df, months: int = 3, annualise: float = 4):
    """The newest point of the above, 2dp, or None if the newest month has none."""
    if df is None or df.empty:
        return None
    g = seasonally_adjusted_growth_series(df, months, annualise)
    if g is None:
        return None
    newest = pd.Timestamp(df.dropna(subset=["value"])["date"].max()).to_period("M")
    last = g.iloc[-1]
    if pd.Timestamp(last["date"]).to_period("M") != newest:
        return None
    return round(float(last["value"]), 2)


# ---------------------------------------------------------------------------
# CPI over GDP's own quarter.
#
# A table row that sets real GDP, CPI and nominal GDP side by side only adds
# up if all three cover the same period. GDP's newest figure is a QUARTER
# (Q2: April-June) while CPI's newest is a MONTH a quarter or more later, so a
# "latest" CPI beside a "latest" GDP compares different stretches of time --
# on 2026-10-22, China's June-August CPI (-1.1% annualised) sat beside its Q2
# GDP, against +2.6% for CPI over Q2 itself. These put CPI on the GDP grid:
# the quarter's AVERAGE index level, as national accounts average a quarter.
# ---------------------------------------------------------------------------
def seasonally_adjusted_levels(df, years: int = SA_YEARS, min_years: int = SA_MIN_YEARS):
    """
    A monthly NSA index with its seasonal LEVEL pattern removed, as a
    [date, value] frame. The monthly factors are the ones
    seasonally_adjusted_growth_series uses (previous complete years only);
    cumulated through the year and centred, they give each calendar month's
    typical position above or below the annual average, which is divided out.
    Months whose year has too little history to estimate factors are dropped.
    """
    if df is None or df.empty:
        return None
    out = df.dropna(subset=["value"]).sort_values("date")
    out = out[out["value"] > 0]
    if out.empty:
        return None
    periods = pd.to_datetime(out["date"]).dt.to_period("M")
    level = pd.Series(np.log(out["value"].to_numpy(dtype=float)), index=periods.to_numpy())
    level = level[~level.index.duplicated(keep="last")]
    prev = (level.index - 1).map(level)
    dlog = pd.Series(level.to_numpy() - np.asarray(prev, dtype=float),
                     index=level.index.to_timestamp()).dropna()
    shifts: dict[int, dict | None] = {}
    dates, values = [], []
    for p, v in level.items():
        year = p.year
        if year not in shifts:
            f = _seasonal_factors(dlog, year, years, min_years)
            if f is None:
                shifts[year] = None
            else:
                cum = np.cumsum([f[m] for m in range(1, 13)])
                shifts[year] = {m: cum[m - 1] - cum.mean() for m in range(1, 13)}
        s = shifts[year]
        if s is None:
            continue
        dates.append(p.to_timestamp())
        values.append(float(np.exp(v - s[p.month])))
    return pd.DataFrame({"date": dates, "value": values}) if dates else None


def quarter_average(df):
    """
    Monthly [date, value] -> quarterly averages dated to the quarter's first
    day. A quarter missing any of its three months is dropped rather than
    averaged over two: US CPI has no 2025-10, and a two-month Q4 average would
    put a different quarter's worth of prices under the same label.
    """
    if df is None or df.empty:
        return None
    s = df.dropna(subset=["value"]).set_index(pd.to_datetime(df["date"]))["value"]
    grouped = s.groupby(s.index.to_period("Q"))
    avg = grouped.mean()[grouped.count() == 3]
    if avg.empty:
        return None
    return pd.DataFrame({"date": avg.index.to_timestamp(), "value": avg.to_numpy()})
