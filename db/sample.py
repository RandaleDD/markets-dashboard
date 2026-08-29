"""
Synthetic data for `pipeline.py --mode sample`.

The point of sample mode is unchanged from before the database: work on the
frontend with no network. What changed is that it now goes through the SAME
path as live -- generate, insert, run the quality checks, export -- rather than
assembling a payload directly. That is deliberate. The old sample path built
`latest.json` by a completely separate route, so it could (and did) drift from
the live shape without anything noticing; now a break in ingest, in the quality
checks or in the export shows up in sample mode too.

It writes to its own database file (`data/markets-sample.db`, gitignored), so a
sample run can never put synthetic numbers into the real store.

Levels are chosen to be plausible for each series so the rendered dashboard
looks like the real thing. They are not real, and every payload built from them
carries `"is_sample": true`.
"""
from __future__ import annotations

import logging
import random

import pandas as pd

from db import registry

logger = logging.getLogger("markets_dashboard.db.sample")

SEED = 42
YEARS = 12

# Plausible starting levels, by series_id. Anything not listed falls back to a
# level inferred from the series' unit, below.
BASE_LEVELS = {
    "equity.US.sp500": 5600, "equity.US.nasdaq100": 19500, "equity.US.russell2000": 2200,
    "equity.UK.ftse100": 8300, "equity.EZ.stoxx600": 520, "equity.DE.dax": 18800,
    "equity.CH.smi": 12200, "equity.CN.csi300": 4.6, "equity.CN.hangseng": 18500,
    "equity.JP.nikkei225": 39500, "equity.NO.osebx": 1500, "equity.EM.msci_em": 42,
    "vol.US.vix": 15,
    "fx.dxy": 103, "fx.eurusd": 1.09, "fx.gbpusd": 1.27, "fx.usdjpy": 152,
    "fx.usdchf": 0.88, "fx.eurchf": 0.96, "fx.usdcny": 7.2, "fx.eurnok": 11.5,
    "commodity.brent": 78, "commodity.natgas_hh": 2.6, "commodity.natgas_ttf": 34,
    "commodity.gold": 2450, "commodity.silver": 29, "commodity.copper": 4.3,
    "commodity.bcom": 22,
    "bond_proxy.IEF": 95, "bond_proxy.TLT": 90,
    "policy_rate.US": 4.50, "policy_rate.UK": 4.25, "policy_rate.EZ": 3.00,
    "policy_rate.CH": 1.00, "policy_rate.CN": 3.10, "policy_rate.JP": 0.50,
    "policy_rate.NO": 4.25,
    "valuation.US.cape": 34.2, "erp.US": 4.23, "sloos.US.ci_large": 5.0,
    "credit.US.ig_oas": 0.79, "credit.US.hy_oas": 2.63,
    "credit.EZ.hy_oas": 2.56, "credit.EM.corp_oas": 1.39,
    "spread_benchmark.DE": 3.07, "spread.FR": 3.6, "spread.IT": 4.0, "spread.ES": 3.8,
}

# A representative curve level per region, so the sample curves keep a shape
# that looks like a yield curve instead of four unrelated random walks.
CURVE_BASE = {
    "curve.US": {"2Y": 4.1, "5Y": 4.0, "10Y": 4.3, "30Y": 4.6},
    "curve.UK": {"2Y": 4.0, "5Y": 4.0, "10Y": 4.4, "30Y": 4.9},
    "curve.EZ": {"2Y": 2.9, "5Y": 3.1, "10Y": 3.7, "30Y": 4.3},
    "curve.DE": {"2Y": 2.3, "5Y": 2.4, "10Y": 2.7, "30Y": 3.1},
    "curve.CH": {"10Y": 0.7},
    "curve.JP": {"2Y": 0.5, "5Y": 0.7, "10Y": 1.1, "30Y": 2.2},
    "curve.NO": {"2Y": 4.4, "5Y": 4.3, "10Y": 4.3},
    "real_yield.US": {"5Y": 1.8, "10Y": 2.0, "30Y": 2.4},
    "real_yield.UK": {"2Y": 0.4, "5Y": 1.0, "10Y": 1.8, "30Y": 2.5},
}

CPI_BASE = {"US": 2.9, "UK": 2.6, "EZ": 2.2, "DE": 2.1, "CH": 0.6,
            "CN": 0.3, "JP": 2.8, "NO": 3.0}


def _base_level(series: registry.Series) -> float:
    if series.series_id in BASE_LEVELS:
        return BASE_LEVELS[series.series_id]
    head = series.series_id.rsplit(".", 1)
    if len(head) == 2 and head[0] in CURVE_BASE:
        by_tenor = CURVE_BASE[head[0]]
        if head[1] in by_tenor:
            return by_tenor[head[1]]
    if series.series_id.startswith("cpi.") and series.series_id.endswith(".index"):
        return 118.0
    if series.series_id.startswith("cpi."):
        return CPI_BASE.get(series.region, 2.5)
    if series.series_id.startswith("gdp."):
        return 100.0            # an index level; growth is derived from it
    if series.series_id.startswith("inflexp."):
        return 2.4
    return 100.0


def _dates(series: registry.Series) -> pd.DatetimeIndex:
    """A date axis at the series' own stored grain, ending at the last Friday."""
    end = pd.Timestamp.now().normalize()
    end = end - pd.Timedelta(days=(end.dayofweek - 4) % 7)  # the most recent Friday
    periodicity = series.periodicity
    if periodicity in ("weekly", "irregular"):
        return pd.date_range(end=end, periods=YEARS * 52, freq="W-FRI")
    if periodicity == "monthly":
        return pd.date_range(end=end.replace(day=1), periods=YEARS * 12, freq="MS")
    if periodicity == "quarterly":
        return pd.date_range(end=end.replace(day=1), periods=YEARS * 4, freq="QS")
    return pd.date_range(end=end.replace(month=12, day=31), periods=YEARS, freq="YE")


def frame_for(series: registry.Series, rng: random.Random) -> pd.DataFrame:
    """A synthetic [date, value] frame with the same shape a fetcher returns."""
    dates = _dates(series)
    base = _base_level(series)
    # A rate wanders in absolute percentage points; a price compounds. Treating
    # a 0.5% policy rate as a price would let it drift to zero and back.
    is_rate = (series.unit or "").strip().startswith("%") or series.series_id.startswith(
        ("policy_rate.", "curve.", "real_yield.", "inflexp.", "spread", "credit.", "cpi."))
    values, level = [], float(base)
    for _ in dates:
        if is_rate:
            level = max(0.01, level + rng.gauss(0, 0.06))
        else:
            level *= 1 + rng.gauss(0, 0.012)
        values.append(round(level, 4))
    return pd.DataFrame({"date": dates, "value": values})


def generate(series: list[registry.Series] | None = None) -> dict[str, pd.DataFrame]:
    """One synthetic frame per registered series, deterministic under SEED."""
    series = series if series is not None else registry.all_series()
    rng = random.Random(SEED)
    return {s.series_id: frame_for(s, rng) for s in series}
