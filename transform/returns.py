"""
Derived return/risk metrics from a raw [date, value] price series.
Works on a pandas DataFrame with columns ["date", "value"], sorted ascending.

**These are weekly observations.** The dashboard stores one close per completed
week (Friday's, or the last session before it), so every metric here is
computed on weekly steps and the constants say so:

  - Volatility annualises with sqrt(52), not sqrt(252). Using the daily factor
    on weekly returns would overstate volatility by a factor of ~2.2.
  - The windows are named in weeks, because that is what they are. 4w and 13w
    span the same calendar month and quarter that the old 20d and 60d windows
    did, so the figures stay comparable with what the dashboard showed before.
  - There is no 1-day change. On weekly data the shortest real step IS one
    week, and reporting it under a "1D" label would be a number that does not
    mean what it says.

Drawdown is likewise measured on weekly closes, so an intra-week trough that
recovered by Friday does not appear. That is a real limitation of weekly
storage, not an error, and the UI labels the column accordingly.
"""
import numpy as np
import pandas as pd

# Weekly steps, so 52 of them a year.
ANNUALISE = np.sqrt(52)
WEEKS_PER_MONTH = 4
WEEKS_PER_QUARTER = 13


def _value_on_or_before(df: pd.DataFrame, target_date: pd.Timestamp):
    sub = df[df["date"] <= target_date]
    if sub.empty:
        return None
    return sub.iloc[-1]["value"]


def compute_return_metrics(df: pd.DataFrame) -> dict:
    """Returns a dict of level + return/vol/drawdown metrics for the latest date."""
    if df is None or df.empty:
        return {}

    df = df.dropna(subset=["value"]).sort_values("date")
    if df.empty:
        return {}

    latest_row = df.iloc[-1]
    latest_date = latest_row["date"]
    latest_value = float(latest_row["value"])

    def pct_change_since(days_back=None, months_back=None, years_back=None, ytd=False):
        if ytd:
            target = pd.Timestamp(year=latest_date.year, month=1, day=1)
        elif years_back:
            target = latest_date - pd.DateOffset(years=years_back)
        elif months_back:
            target = latest_date - pd.DateOffset(months=months_back)
        elif days_back:
            target = latest_date - pd.Timedelta(days=days_back)
        else:
            return None
        past_value = _value_on_or_before(df, target)
        if past_value is None or past_value == 0:
            return None
        return (latest_value / past_value - 1.0) * 100.0

    # Drawdown from all-time high (within available history)
    running_max = df["value"].cummax()
    drawdown_series = (df["value"] / running_max - 1.0) * 100.0
    drawdown_ath = float(drawdown_series.iloc[-1])

    # Realized volatility (annualized, close-to-close) over 4 and 13 weeks --
    # one month and one quarter, the same horizons the daily 20d/60d windows
    # covered. sqrt(52) because the steps are weekly.
    weekly_returns = df["value"].pct_change().dropna()
    vol_4w = (float(weekly_returns.tail(WEEKS_PER_MONTH).std() * ANNUALISE * 100.0)
              if len(weekly_returns) >= WEEKS_PER_MONTH else None)
    vol_13w = (float(weekly_returns.tail(WEEKS_PER_QUARTER).std() * ANNUALISE * 100.0)
               if len(weekly_returns) >= WEEKS_PER_QUARTER else None)

    return {
        "as_of": latest_date.strftime("%Y-%m-%d"),
        "level": round(latest_value, 4),
        "chg_1w_pct": _round_or_none(pct_change_since(days_back=7)),
        "chg_mtd_pct": _round_or_none(pct_change_since(months_back=1)),
        "chg_ytd_pct": _round_or_none(pct_change_since(ytd=True)),
        "chg_1y_pct": _round_or_none(pct_change_since(years_back=1)),
        "drawdown_from_ath_pct": round(drawdown_ath, 2),
        "realized_vol_4w_pct": _round_or_none(vol_4w),
        "realized_vol_13w_pct": _round_or_none(vol_13w),
    }


def history_for_chart(df: pd.DataFrame, lookback_years: float = 1.0) -> list:
    """Returns [[iso_date, value], ...] trimmed to the lookback window, for charting."""
    if df is None or df.empty:
        return []
    cutoff = df["date"].max() - pd.DateOffset(days=int(365 * lookback_years))
    trimmed = df[df["date"] >= cutoff]
    return [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in zip(trimmed["date"], trimmed["value"])]


def _round_or_none(x, ndigits=2):
    return round(x, ndigits) if x is not None and not (isinstance(x, float) and np.isnan(x)) else None


def compact_history(df: pd.DataFrame, years: float = 5.0) -> list:
    """
    History for the interactive chart: every stored week, out to `years`.

    This used to downsample the tail of the window to Fridays, because the
    stored series were daily and 5 years of daily points for ~30 series roughly
    tripled latest.json. Storage is weekly now, so the series IS already at
    Friday resolution and a second pass would only throw away points the chart
    can actually use.
    """
    if df is None or df.empty:
        return []
    df = df.dropna(subset=["value"]).sort_values("date")
    if df.empty:
        return []
    start = df["date"].max() - pd.DateOffset(days=int(365.25 * years))
    out = df[df["date"] >= start]
    return [[d.strftime("%Y-%m-%d"), round(float(v), 4)]
            for d, v in zip(out["date"], out["value"])]
