"""
Rolling cross-asset correlation.

Descriptive only, per V2-PLAN.md's governing constraint: this reports how
assets have co-moved over a fixed recent window. It makes no diversification
recommendation and produces no composite score.

Correlations are computed on *returns*, never on price levels. Two trending
price series correlate near 1.0 regardless of whether they actually move
together, which would make the whole grid meaningless.

The returns are weekly, because that is the grain the database stores. Windows
are therefore counted in weeks, and they had to lengthen: the old 60- and
90-trading-day windows are 12 and 18 weekly observations, well under the
minimum overlap below, so every cell would have come back empty. One and two
years of weekly returns is the equivalent horizon at this grain.
"""
from __future__ import annotations

import pandas as pd

# Below roughly 30 overlapping observations the coefficient is too fragile to
# show. At weekly grain that is a bit over half a year, which is why the
# windows below start at a full year.
MIN_OVERLAP = 30


def rolling_correlation_matrix(series_dict: dict, window_weeks: int = 52) -> dict:
    """
    series_dict: {label: DataFrame[date, value]} of weekly price levels.

    Returns labels, a square matrix of Pearson coefficients (None where the
    pair lacks overlap), the window in weeks, and the date range covered.
    """
    frames = {}
    for label, df in series_dict.items():
        if df is None or len(df) < MIN_OVERLAP + 2:
            continue
        s = df.dropna(subset=["value"]).sort_values("date").set_index("date")["value"]
        s = s[~s.index.duplicated(keep="last")]
        frames[label] = s

    labels = list(frames.keys())
    if len(labels) < 2:
        return {"labels": [], "matrix": [], "window_weeks": window_weeks,
                "as_of": None, "start": None, "n_obs": 0}

    # Align on shared weeks — these assets trade on different calendars and a
    # holiday shifts one of them off Friday, so an outer join would manufacture
    # gaps that pandas would then treat as real return observations.
    px = pd.DataFrame(frames).dropna(how="any")
    rets = px.pct_change().dropna(how="any").tail(window_weeks)
    if len(rets) < MIN_OVERLAP:
        return {"labels": labels, "matrix": [[None] * len(labels) for _ in labels],
                "window_weeks": window_weeks, "as_of": None, "start": None,
                "n_obs": int(len(rets))}

    corr = rets.corr(method="pearson")
    matrix = []
    for a in labels:
        row = []
        for b in labels:
            v = corr.loc[a, b] if (a in corr.index and b in corr.columns) else None
            row.append(None if v is None or pd.isna(v) else round(float(v), 3))
        matrix.append(row)

    return {
        "labels": labels,
        "matrix": matrix,
        "window_weeks": window_weeks,
        "as_of": rets.index.max().strftime("%Y-%m-%d"),
        "start": rets.index.min().strftime("%Y-%m-%d"),
        "n_obs": int(len(rets)),
    }
