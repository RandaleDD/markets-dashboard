#!/usr/bin/env python3
"""
Pipeline orchestrator. Two modes:

  python pipeline.py --mode live    # real fetches, run by GitHub Actions / your machine
  python pipeline.py --mode sample  # synthetic representative data, for testing the
                                     # frontend/layout without live network access

Writes site/data/latest.json in both modes so the frontend never has to know
which mode produced it (sample runs are marked with "is_sample": true at
the top level so this is never mistaken for real data).
"""
import argparse
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from fetch import sources, universe
from transform.returns import compute_return_metrics, compact_history
from transform.curves import latest_tenor_values, curve_shape
from transform.erp import compute_erp
from transform.cost_of_capital import stack_cost_of_capital
from transform.percentile import percentile_context, has_any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("markets_dashboard.pipeline")

DATA_DIR = Path(__file__).parent / "site" / "data"

# A source that returns HTTP 200 and parses cleanly can still be years out of
# date. "ok" means "fresh enough for its publication cadence"; anything older
# is "stale" so it shows up in source_status instead of passing as current.
# "policy" is deliberately loose (a rate sits unchanged for months, and BIS
# stops emitting observations between moves); "annual" allows for normal
# publication lag on yearly national accounts.
MAX_AGE_DAYS = {"daily": 10, "monthly": 70, "quarterly": 200,
                "policy": 150, "annual": 730}


def _as_of(df):
    if df is None or df.empty:
        return None
    return df.iloc[-1]["date"]


def _series_status(df, cadence="daily"):
    """Returns (status, as_of_iso_or_None) for one fetched series."""
    ts = _as_of(df)
    if ts is None:
        return "failed", None
    age_days = (pd.Timestamp.now() - pd.Timestamp(ts)).days
    return ("stale" if age_days > MAX_AGE_DAYS[cadence] else "ok"), pd.Timestamp(ts).strftime("%Y-%m-%d")


def _latest(df):
    return float(df.iloc[-1]["value"]) if df is not None and not df.empty else None


def _pct_change(df, lag, annualise=1):
    """Growth over `lag` periods, optionally annualised (lag=1 quarter -> **4)."""
    if df is None or len(df) <= lag:
        return None
    prior = float(df.iloc[-1 - lag]["value"])
    if not prior:
        return None
    ratio = float(df.iloc[-1]["value"]) / prior
    if ratio <= 0:
        return None
    return round((ratio ** annualise - 1) * 100, 2)


def _ctx(df, latest_value=None):
    """
    Percentile/z-score context from a source's FULL history, or None.

    Deliberately fed the untrimmed fetch, not compact_history's stored archive:
    the archive only reaches back to this project's launch, so a 10y window
    computed from it cannot resolve (and its "full" would silently mean
    "since we started collecting"). Proven on US 10y — 98th percentile over a
    real 10 years, 42nd over the actual series back to 1962.
    """
    ctx = percentile_context(df, latest_value)
    return ctx if has_any(ctx) else None


def _drawdown_series(df):
    """Drawdown from running peak, as a percentage — mean-reverting, so a
    percentile against its own history is informative."""
    if df is None or len(df) < 2:
        return None
    out = df.dropna(subset=["value"]).sort_values("date").copy()
    out["value"] = (out["value"] / out["value"].cummax() - 1.0) * 100.0
    return out


def _rolling_vol_series(df, window=20):
    """Annualised rolling close-to-close volatility, as a percentage."""
    if df is None or len(df) < window + 2:
        return None
    out = df.dropna(subset=["value"]).sort_values("date").copy()
    out["value"] = out["value"].pct_change().rolling(window).std() * (252 ** 0.5) * 100.0
    return out.dropna(subset=["value"])


# Curve tenors go through one dispatcher so a region only names its source in
# universe.py. Memoised because several regions share underlying downloads.
def _fetch_curve_tenor(cfg, key, cache):
    if not key:
        return None
    src = cfg["source"]
    ck = (src, cfg.get("glc_file"), key)
    if ck in cache:
        return cache[ck]
    if src == "fred":
        df = sources.fetch_fred(key)
    elif src == "bundesbank":
        df = sources.fetch_bundesbank(key)
    elif src == "ecb":
        df = sources.fetch_ecb(key)
    elif src == "boe_glc":
        df = sources.fetch_boe_glc(cfg.get("glc_file", "nominal"), key)
    elif src == "mof":
        df = sources.fetch_mof_jgb(key)
    elif src == "norges":
        df = sources.fetch_norges_curve(key)
    elif src == "chinabond":
        df = sources.fetch_chinabond(key)
    elif src == "snb":
        df = sources.fetch_snb(key)
    else:
        logger.warning("No fetcher registered for curve source %r", src)
        df = None
    cache[ck] = df
    return df


def _build_curve(region, cfg, status, cache, prefix):
    """Shared assembly for nominal and real curve tables."""
    tenor_series = {t: _fetch_curve_tenor(cfg, key, cache) for t, key in cfg["tenors"].items()}
    values = latest_tenor_values(tenor_series)
    live = [t for t, df in tenor_series.items() if df is not None]
    wanted = [t for t, key in cfg["tenors"].items() if key]
    cadence = cfg.get("cadence", "daily")
    if not wanted or not live:
        st = "stubbed"
    elif len(live) < len(wanted):
        st = "partial"
    else:
        st = "ok"
        for df in tenor_series.values():
            if df is not None and _series_status(df, cadence)[0] == "stale":
                st = "stale"
                break
    status[f"{prefix}:{region}"] = st
    as_ofs = [_series_status(df, cadence)[1] for df in tenor_series.values() if df is not None]
    context = {t: _ctx(df) for t, df in tenor_series.items() if df is not None}
    context = {t: c for t, c in context.items() if c}
    return {
        "tenors": values,
        "context": context or None,
        **curve_shape(values),
        "as_of": max(as_ofs) if as_ofs else None,
        "source_note": cfg.get("note"),
        "cadence": cadence,
        "lagged": cfg.get("lagged", False),
        "basis": cfg.get("basis"),
    }


# ---------------------------------------------------------------------------
# LIVE MODE
# ---------------------------------------------------------------------------
def run_live_pipeline() -> dict:
    status = {}
    out = _empty_payload(False)

    # --- Equity indices ---
    for idx in universe.EQUITY_INDICES:
        df = sources.fetch_yahoo(idx.get("yahoo"))
        status[f"equity:{idx['id']}"], _ = _series_status(df)
        # A price level's percentile is near-meaningless for a trending series
        # (any index in an uptrend sits at ~100th). Volatility and drawdown are
        # mean-reverting, so those are what carry context here.
        out["equity_indices"].setdefault(idx["region"], []).append({
            "id": idx["id"], "name": idx["name"], "currency": idx["currency"],
            **(compute_return_metrics(df) if df is not None else {}),
            "vol_context": _ctx(_rolling_vol_series(df)) if df is not None else None,
            "drawdown_context": _ctx(_drawdown_series(df)) if df is not None else None,
            "history": compact_history(df) if df is not None else [],
        })

    # --- Currencies ---
    for fx in universe.CURRENCIES:
        df = sources.fetch_yahoo(fx.get("yahoo"))
        status[f"fx:{fx['id']}"], _ = _series_status(df)
        out["currencies"].append({
            "id": fx["id"], "name": fx["name"],
            **(compute_return_metrics(df) if df is not None else {}),
            "context": _ctx(df) if df is not None else None,
            "history": compact_history(df) if df is not None else [],
        })

    # --- Commodities (each carries exchange/contract/unit) ---
    for cm in universe.COMMODITIES:
        df = sources.fetch_yahoo(cm.get("yahoo"))
        status[f"commodity:{cm['id']}"], _ = _series_status(df)
        out["commodities"].append({
            "id": cm["id"], "name": cm["name"], "exchange": cm["exchange"],
            "contract": cm["contract"], "unit": cm["unit"],
            **(compute_return_metrics(df) if df is not None else {}),
            "context": _ctx(df) if df is not None else None,
            "history": compact_history(df) if df is not None else [],
        })

    # --- Macro: policy rates ---
    for cb in universe.CENTRAL_BANKS:
        if cb["source"] == "norges":
            df = sources.fetch_norges(cb["norges_key"])
        else:
            df = sources.fetch_bis_policy_rate(cb["bis_ref_area"])
        st, as_of = _series_status(df, "policy")
        status[f"cbrate:{cb['region']}"] = st
        out["macro"]["policy_rates"][cb["region"]] = {
            "name": cb["name"], "rate_pct": _latest(df), "as_of": as_of,
            "context": _ctx(df) if df is not None else None}

    # --- Macro: inflation (YoY from BIS, annualised QoQ from the index) ---
    for region, cfg in universe.INFLATION_CPI.items():
        yoy_df = sources.fetch_bis_cpi(cfg["ref_area"], sources.CPI_UNIT_YOY)
        idx_df = sources.fetch_bis_cpi(cfg["ref_area"], sources.CPI_UNIT_INDEX)
        st, as_of = _series_status(yoy_df, "monthly")
        status[f"cpi:{region}"] = st
        out["macro"]["inflation"][region] = {
            "yoy_pct": round(_latest(yoy_df), 2) if _latest(yoy_df) is not None else None,
            # 3 monthly observations = one quarter, compounded to a yearly rate.
            "qoq_ann_pct": _pct_change(idx_df, 3, annualise=4),
            "as_of": as_of,
            "context": _ctx(yoy_df) if yoy_df is not None else None,
        }

    # --- Macro: GDP (real, chain-linked, local currency, SA) ---
    for region, cfg in universe.GDP_GROWTH.items():
        df = sources.fetch_fred(cfg["series"]) if cfg["source"] == "fred" else None
        st, as_of = _series_status(df, cfg.get("cadence", "quarterly"))
        status[f"gdp:{region}"] = st
        quarterly = cfg.get("freq", "Q") == "Q"
        out["macro"]["gdp"][region] = {
            "yoy_pct": _pct_change(df, 4 if quarterly else 1),
            "qoq_ann_pct": _pct_change(df, 1, annualise=4) if quarterly else None,
            "freq": cfg.get("freq", "Q"),
            "as_of": as_of,
        }
    out["macro"]["gdp_definition"] = universe.GDP_DEFINITION

    # --- Nominal and real yield curves ---
    cache = {}
    for region, cfg in universe.YIELD_CURVES.items():
        out["yield_curves"][region] = _build_curve(region, cfg, status, cache, "curve")
    for region, cfg in universe.REAL_YIELD_CURVES.items():
        out["real_yield_curves"][region] = _build_curve(region, cfg, status, cache, "realyield")

    # --- Inflation expectations ---
    for region, cfg in universe.INFLATION_EXPECTATIONS.items():
        out["inflation_expectations"][region] = _inflation_expectations(region, cfg, status, cache)

    # --- Euro-area sovereign spreads (both legs from the same ECB series) ---
    bench = universe.EUROZONE_SPREAD_BENCHMARK
    bench_df = sources.fetch_ecb(bench["ecb_key"])
    bench_yield = _latest(bench_df)
    bench_st, bench_as_of = _series_status(bench_df, "monthly")
    out["eurozone_spreads"]["benchmark"] = bench["country"]
    out["eurozone_spreads"]["benchmark_yield_pct"] = bench_yield
    out["eurozone_spreads"]["as_of"] = bench_as_of
    out["eurozone_spreads"]["cadence"] = "monthly"
    for entry in universe.EUROZONE_SPREAD_PANEL:
        df = sources.fetch_ecb(entry["ecb_key"])
        # Context belongs on the spread's own history, not the yield's — a
        # spread and its underlying yield sit at very different percentiles.
        spread_hist = None
        if df is not None and bench_df is not None:
            merged = df.merge(bench_df, on="date", suffixes=("_c", "_b"))
            if not merged.empty:
                spread_hist = pd.DataFrame({
                    "date": merged["date"],
                    "value": (merged["value_c"] - merged["value_b"]) * 100.0})
        st, as_of = _series_status(df, "monthly")
        status[f"spread:{entry['country']}"] = st if bench_st != "failed" else "failed"
        y = _latest(df)
        out["eurozone_spreads"]["rows"].append({
            "country": entry["country"], "yield_pct": round(y, 3) if y is not None else None,
            "spread_bp": round((y - bench_yield) * 100, 1)
            if (y is not None and bench_yield is not None) else None,
            "as_of": as_of,
            "context": _ctx(spread_hist) if spread_hist is not None else None,
        })

    # --- Valuation (CAPE) and ERP ---
    cape_df = sources.fetch_shiller_cape()
    cape_st, cape_as_of = _series_status(cape_df, "monthly")
    erp_df = sources.fetch_damodaran_erp()
    erp_st, erp_as_of = _series_status(erp_df, "annual")
    for entry in universe.VALUATION_PROXIES:
        region = entry["region"]
        is_us = entry.get("cape_source") == "shiller"
        status[f"valuation:{region}"] = cape_st if is_us else "stubbed"
        out["valuation"][region] = {
            "name": entry["name"],
            "cape": round(_latest(cape_df), 2) if (is_us and _latest(cape_df) is not None) else None,
            "cape_as_of": cape_as_of if is_us else None,
            "cape_context": (_ctx(cape_df) if is_us and cape_df is not None else None),
            "forward_pe": None, "dividend_yield_pct": None,
            "note": None if is_us else "P/E and dividend yield need ETF fact-sheet parsing (SPEC Phase 4).",
        }

    for region in universe.REGIONS:
        if region == "US" and _latest(erp_df) is not None:
            status["erp:US"] = erp_st
            out["equity_risk_premia"]["US"] = {
                "erp_pct": round(_latest(erp_df), 2),
                "method": "Damodaran implied ERP (FCFE), S&P 500",
                "as_of": erp_as_of,
                "context": _ctx(erp_df),
            }
            continue
        pe = out["valuation"].get(region, {}).get("forward_pe")
        y10 = out["yield_curves"].get(region, {}).get("tenors", {}).get("10Y")
        val = compute_erp(pe, y10)
        status[f"erp:{region}"] = "ok" if val is not None else "stubbed"
        out["equity_risk_premia"][region] = {
            "erp_pct": val,
            "method": "Earnings yield minus 10y govt yield" if val is not None else None,
            "as_of": None,
            "context": None,
        }

    out["source_status"] = status
    # --- Credit spreads (ICE BofA OAS via FRED) ---
    stack_credit = {}
    for cs in universe.CREDIT_SPREADS:
        df = sources.fetch_fred(cs["series"])
        st, as_of = _series_status(df)
        status[f"credit:{cs['id']}"] = st
        level = _latest(df)
        out["credit_spreads"].append({
            "id": cs["id"], "region": cs["region"], "name": cs["name"],
            "grade": cs["grade"], "spread_pct": round(level, 2) if level is not None else None,
            "as_of": as_of, "context": _ctx(df) if df is not None else None,
        })
        if cs.get("stack_leg") and level is not None:
            stack_credit[cs["region"]] = round(level, 2)

    # --- Cost-of-capital stack (real risk-free + IG spread + ERP) ---
    out["cost_of_capital_note"] = universe.COST_OF_CAPITAL_NOTE
    for region in universe.REGIONS:
        real = (out["real_yield_curves"].get(region, {}).get("tenors", {}) or {}).get("10Y")
        erp = (out["equity_risk_premia"].get(region, {}) or {}).get("erp_pct")
        stack = stack_cost_of_capital(real, stack_credit.get(region), erp)
        status[f"costcap:{region}"] = ("ok" if stack["complete"]
                                       else "partial" if stack["total_pct"] is not None
                                       else "stubbed")
        out["cost_of_capital"][region] = stack

    tally = {}
    for v in status.values():
        tally[v] = tally.get(v, 0) + 1
    logger.info("Live pipeline: %d/%d sources ok (%s)", tally.get("ok", 0), len(status),
                ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return out


def _inflation_expectations(region, cfg, status, cache):
    """Market-implied where linkers exist; model-implied or explicit gap otherwise."""
    if cfg.get("kind") == "unavailable" or not cfg.get("source"):
        status[f"inflexp:{region}"] = "stubbed"
        return {"kind": "unavailable", "note": cfg.get("note"), "tenors": {}}

    tenors, sts, context = {}, [], {}
    for label, key in cfg["tenors"].items():
        if cfg["source"] == "fred":
            df = sources.fetch_fred(key)
        elif cfg["source"] == "boe_glc":
            df = sources.fetch_boe_glc(cfg.get("glc_file", "inflation"), key)
        else:
            df = None
        v = _latest(df)
        tenors[label] = round(v, 2) if v is not None else None
        if df is not None:
            c = _ctx(df)
            if c:
                context[label] = c
        sts.append(_series_status(df)[0])

    out = {"kind": cfg.get("kind", "market"), "basis": cfg.get("basis"),
           "note": cfg.get("note"), "tenors": tenors, "context": context or None}

    model = cfg.get("model")
    if model:
        mt = {}
        for label, key in model["tenors"].items():
            v = _latest(sources.fetch_fred(key))
            mt[label] = round(v, 2) if v is not None else None
        out["model"] = {"kind": "model", "basis": model.get("basis"), "tenors": mt,
                        "note": "Cleveland Fed model-implied (TIPS + swaps + survey); "
                                "no 1y TIPS breakeven is published."}

    status[f"inflexp:{region}"] = ("failed" if all(x == "failed" for x in sts)
                                   else "stale" if "stale" in sts
                                   else "partial" if "failed" in sts else "ok")
    return out


def _empty_payload(is_sample: bool) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_sample": is_sample,
        "regions": universe.REGIONS,
        "region_names": universe.REGION_NAMES,
        "chart_periods": universe.CHART_PERIODS,
        "equity_indices": {},
        "currencies": [],
        "commodities": [],
        "macro": {"policy_rates": {}, "inflation": {}, "gdp": {}, "gdp_definition": ""},
        "yield_curves": {},
        "real_yield_curves": {},
        "inflation_expectations": {},
        "eurozone_spreads": {"benchmark": None, "benchmark_yield_pct": None,
                             "as_of": None, "cadence": "monthly", "rows": []},
        "credit_spreads": [],
        "cost_of_capital": {},
        "cost_of_capital_note": "",
        "valuation": {},
        "equity_risk_premia": {},
        "source_status": {},
    }


# ---------------------------------------------------------------------------
# SAMPLE MODE — synthetic but structurally realistic, so the frontend can be
# built and tested without live network access. Must produce the same shape as
# live mode or the no-network path silently rots.
# ---------------------------------------------------------------------------
def run_sample_pipeline() -> dict:
    rng = random.Random(42)
    today = datetime.now(timezone.utc)
    out = _empty_payload(True)

    def fake_history(base, vol_pct, days=1830):
        vals, v = [], base
        for i in range(days, 0, -1):
            v *= (1 + rng.gauss(0, vol_pct / 100))
            d = today - timedelta(days=i)
            # Weekly before the last year, daily after — mirrors compact_history.
            if i > 365 and d.weekday() != 4:
                continue
            vals.append([d.strftime("%Y-%m-%d"), round(v, 4)])
        return vals

    def fake_ctx(seed_hi=True):
        pct = rng.uniform(55, 99) if seed_hi else rng.uniform(2, 60)
        return {w: {"pct": round(pct + rng.gauss(0, 6), 1), "z": round(rng.gauss(0.5, 0.8), 2),
                    "n": rng.randint(300, 3000), "since": "2016-01-04"}
                for w in ("5y", "10y", "full")}

    def fake_metrics(base, vol_pct=1.0):
        hist = fake_history(base, vol_pct)
        return {
            "as_of": today.strftime("%Y-%m-%d"), "level": hist[-1][1],
            "chg_1d_pct": round(rng.gauss(0, 0.6), 2), "chg_1w_pct": round(rng.gauss(0, 1.5), 2),
            "chg_mtd_pct": round(rng.gauss(0, 2.5), 2), "chg_ytd_pct": round(rng.gauss(5, 8), 2),
            "chg_1y_pct": round(rng.gauss(8, 12), 2),
            "drawdown_from_ath_pct": round(-abs(rng.gauss(4, 4)), 2),
            "realized_vol_20d_pct": round(abs(rng.gauss(14, 4)), 2),
            "realized_vol_60d_pct": round(abs(rng.gauss(15, 4)), 2),
            "history": hist,
            "vol_context": fake_ctx(False),
            "drawdown_context": fake_ctx(),
            "context": fake_ctx(),
        }

    base_levels = {"sp500": 5600, "nasdaq100": 19500, "russell2000": 2200, "ftse100": 8300,
                   "stoxx600": 520, "dax": 18800, "smi": 12200, "csi300": 4.6,
                   "hangseng": 18500, "nikkei225": 39500, "osebx": 1500, "msci_em": 42}
    for idx in universe.EQUITY_INDICES:
        out["equity_indices"].setdefault(idx["region"], []).append({
            "id": idx["id"], "name": idx["name"], "currency": idx["currency"],
            **fake_metrics(base_levels.get(idx["id"], 1000))})

    fx_base = {"dxy": 103, "eurusd": 1.09, "gbpusd": 1.27, "usdjpy": 152, "usdchf": 0.88,
               "eurchf": 0.96, "usdcny": 7.2, "eurnok": 11.5}
    for fx in universe.CURRENCIES:
        out["currencies"].append({"id": fx["id"], "name": fx["name"],
                                  **fake_metrics(fx_base.get(fx["id"], 1), vol_pct=0.4)})

    cmd_base = {"brent": 78, "natgas_hh": 2.6, "natgas_ttf": 34, "gold": 2450,
                "silver": 29, "copper": 4.3, "bcom": 22}
    for cm in universe.COMMODITIES:
        out["commodities"].append({
            "id": cm["id"], "name": cm["name"], "exchange": cm["exchange"],
            "contract": cm["contract"], "unit": cm["unit"],
            **fake_metrics(cmd_base.get(cm["id"], 100), vol_pct=1.2)})

    cb_rates = {"US": 4.50, "UK": 4.25, "EZ": 3.00, "DE": 3.00, "CH": 1.00,
                "CN": 3.10, "JP": 0.50, "NO": 4.25}
    for cb in universe.CENTRAL_BANKS:
        out["macro"]["policy_rates"][cb["region"]] = {
            "name": cb["name"], "rate_pct": cb_rates.get(cb["region"]),
            "as_of": today.strftime("%Y-%m-%d"), "context": fake_ctx()}

    cpi_base = {"US": 2.9, "UK": 2.6, "EZ": 2.2, "DE": 2.1, "CH": 0.6,
                "CN": 0.3, "JP": 2.8, "NO": 3.0}
    gdp_base = {"US": 2.3, "UK": 1.1, "EZ": 0.9, "DE": 0.4, "CH": 1.3,
                "CN": 4.8, "JP": 0.7, "NO": 1.2}
    for region in universe.REGIONS:
        out["macro"]["inflation"][region] = {
            "yoy_pct": cpi_base.get(region),
            "qoq_ann_pct": round((cpi_base.get(region) or 0) + rng.gauss(0, 0.5), 2),
            "as_of": today.strftime("%Y-%m-01"), "context": fake_ctx()}
        out["macro"]["gdp"][region] = {
            "yoy_pct": gdp_base.get(region),
            "qoq_ann_pct": None if region == "CN" else round((gdp_base.get(region) or 0) + rng.gauss(0, 0.8), 2),
            "freq": "A" if region == "CN" else "Q", "as_of": today.strftime("%Y-%m-01")}
    out["macro"]["gdp_definition"] = universe.GDP_DEFINITION

    curve_base = {"US": {"2Y": 4.1, "5Y": 4.0, "10Y": 4.3, "30Y": 4.6},
                  "UK": {"2Y": 4.0, "5Y": 4.0, "10Y": 4.4, "30Y": 4.9},
                  "EZ": {"2Y": 2.9, "5Y": 3.1, "10Y": 3.7, "30Y": 4.3},
                  "DE": {"2Y": 2.3, "5Y": 2.4, "10Y": 2.7, "30Y": 3.1},
                  "CH": {"2Y": None, "5Y": None, "10Y": 0.7, "30Y": None},
                  "CN": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
                  "JP": {"2Y": 0.5, "5Y": 0.7, "10Y": 1.1, "30Y": 2.2},
                  "NO": {"2Y": 4.4, "5Y": 4.3, "10Y": 4.3, "30Y": None}}
    for region, cfg in universe.YIELD_CURVES.items():
        tenors = curve_base.get(region, {"2Y": None, "5Y": None, "10Y": None, "30Y": None})
        out["yield_curves"][region] = {
            "tenors": tenors, **curve_shape(tenors), "as_of": today.strftime("%Y-%m-%d"),
            "context": {t: fake_ctx() for t, v in tenors.items() if v is not None} or None,
            "source_note": cfg.get("note"), "cadence": cfg.get("cadence", "daily"),
            "lagged": cfg.get("lagged", False), "basis": None}

    real_base = {"US": {"2Y": None, "5Y": 1.8, "10Y": 2.0, "30Y": 2.4},
                 "UK": {"2Y": 0.4, "5Y": 1.0, "10Y": 1.8, "30Y": 2.5}}
    for region, cfg in universe.REAL_YIELD_CURVES.items():
        t = real_base[region]
        out["real_yield_curves"][region] = {
            "tenors": t, **curve_shape(t), "as_of": today.strftime("%Y-%m-%d"),
            "source_note": None, "cadence": "daily", "lagged": False, "basis": cfg.get("basis")}

    for region, cfg in universe.INFLATION_EXPECTATIONS.items():
        if cfg.get("kind") == "unavailable":
            out["inflation_expectations"][region] = {"kind": "unavailable", "note": cfg.get("note"), "tenors": {}}
        elif region == "US":
            out["inflation_expectations"][region] = {
                "kind": "market", "basis": "CPI", "note": None,
                "tenors": {"5y": 2.3, "10y": 2.35, "5y5y_fwd": 2.4},
                "model": {"kind": "model", "basis": "CPI",
                          "tenors": {"1y": 2.4, "5y": 2.5, "10y": 2.5},
                          "note": "Cleveland Fed model-implied."}}
        else:
            out["inflation_expectations"][region] = {
                "kind": "market", "basis": cfg.get("basis"), "note": cfg.get("note"),
                "tenors": {"2y": 3.9, "5y": 3.5, "10y": 3.3}}

    out["eurozone_spreads"].update({
        "benchmark": "Germany", "benchmark_yield_pct": 3.07,
        "as_of": today.strftime("%Y-%m-01"), "cadence": "monthly",
        "rows": [{"country": e["country"], "yield_pct": round(3.07 + abs(rng.gauss(0.6, 0.3)), 3),
                  "spread_bp": round(abs(rng.gauss(60, 30)), 1), "as_of": today.strftime("%Y-%m-01")}
                 for e in universe.EUROZONE_SPREAD_PANEL]})

    for entry in universe.VALUATION_PROXIES:
        is_us = entry["region"] == "US"
        out["valuation"][entry["region"]] = {
            "name": entry["name"], "cape": 34.2 if is_us else None,
            "cape_as_of": today.strftime("%Y-%m-01") if is_us else None,
            "cape_context": fake_ctx() if is_us else None,
            "forward_pe": None, "dividend_yield_pct": None,
            "note": None if is_us else "P/E and dividend yield need ETF fact-sheet parsing (SPEC Phase 4)."}
    cs_base = {"us_ig": 0.79, "us_hy": 2.63, "eu_hy": 2.56, "em_corp": 1.39}
    for cs in universe.CREDIT_SPREADS:
        out["credit_spreads"].append({
            "id": cs["id"], "region": cs["region"], "name": cs["name"], "grade": cs["grade"],
            "spread_pct": cs_base.get(cs["id"]), "as_of": today.strftime("%Y-%m-%d"),
            "context": fake_ctx()})
    out["cost_of_capital_note"] = universe.COST_OF_CAPITAL_NOTE
    for region in universe.REGIONS:
        real = (out["real_yield_curves"].get(region, {}).get("tenors", {}) or {}).get("10Y")
        erp = 4.23 if region == "US" else None
        credit = 0.79 if region == "US" else None
        out["cost_of_capital"][region] = stack_cost_of_capital(real, credit, erp)

    for region in universe.REGIONS:
        out["equity_risk_premia"][region] = (
            {"erp_pct": 4.23, "method": "Damodaran implied ERP (FCFE), S&P 500",
             "as_of": "2025-12-31", "context": fake_ctx()}
            if region == "US" else {"erp_pct": None, "method": None, "as_of": None})

    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["live", "sample"], default="sample")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    data = run_live_pipeline() if args.mode == "live" else run_sample_pipeline()

    out_path = DATA_DIR / "latest.json"
    out_path.write_text(json.dumps(data, indent=2))
    logger.info("Wrote %s (%.0f KB, mode=%s)", out_path, out_path.stat().st_size / 1024, args.mode)


if __name__ == "__main__":
    main()
