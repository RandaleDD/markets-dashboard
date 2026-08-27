"""
Derived return/risk metrics from a raw [date, value] price series.
Works on a pandas DataFrame with columns ["date", "value"], sorted ascending.
"""
import numpy as np
import pandas as pd


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

    # Realized volatility (annualized, close-to-close), 20d and 60d windows
    daily_returns = df["value"].pct_change().dropna()
    vol_20d = float(daily_returns.tail(20).std() * np.sqrt(252) * 100.0) if len(daily_returns) >= 20 else None
    vol_60d = float(daily_returns.tail(60).std() * np.sqrt(252) * 100.0) if len(daily_returns) >= 60 else None

    return {
        "as_of": latest_date.strftime("%Y-%m-%d"),
        "level": round(latest_value, 4),
        "chg_1d_pct": _round_or_none(pct_change_since(days_back=1)),
        "chg_1w_pct": _round_or_none(pct_change_since(days_back=7)),
        "chg_mtd_pct": _round_or_none(pct_change_since(months_back=1)),
        "chg_ytd_pct": _round_or_none(pct_change_since(ytd=True)),
        "chg_1y_pct": _round_or_none(pct_change_since(years_back=1)),
        "drawdown_from_ath_pct": round(drawdown_ath, 2),
        "realized_vol_20d_pct": _round_or_none(vol_20d),
        "realized_vol_60d_pct": _round_or_none(vol_60d),
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
