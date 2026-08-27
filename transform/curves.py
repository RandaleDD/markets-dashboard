"""Yield curve shape metrics: 2s10s, 3m10y spreads, and curve-point extraction."""


def latest_tenor_values(tenor_series: dict) -> dict:
    """
    tenor_series: {"2Y": df_or_None, "5Y": df_or_None, "10Y": df_or_None, "30Y": df_or_None}
    Returns {"2Y": latest_value_or_None, ...}
    """
    out = {}
    for tenor, df in tenor_series.items():
        if df is None or df.empty:
            out[tenor] = None
        else:
            out[tenor] = round(float(df.dropna(subset=["value"]).iloc[-1]["value"]), 3)
    return out


def curve_shape(latest_values: dict) -> dict:
    two_y = latest_values.get("2Y")
    ten_y = latest_values.get("10Y")
    result = {"2s10s_bp": None, "3m10y_bp": None}
    if two_y is not None and ten_y is not None:
        result["2s10s_bp"] = round((ten_y - two_y) * 100, 1)
    # 3m10y needs a 3-month bill series, not in the base tenor set — left
    # None until a 3M series is wired up per region.
    return result


def spread_vs_benchmark(country_yield: float, benchmark_yield: float) -> float | None:
    if country_yield is None or benchmark_yield is None:
        return None
    return round((country_yield - benchmark_yield) * 100, 1)  # basis points
