#!/usr/bin/env python3
"""
Pipeline orchestrator. Two modes:

  python pipeline.py --mode live    # real fetches, run by GitHub Actions / your machine
  python pipeline.py --mode sample  # synthetic representative data, for testing the
                                     # frontend/layout without live network access

Writes data/latest.json in both modes so the frontend never has to know
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
from transform.returns import compute_return_metrics, history_for_chart
from transform.curves import latest_tenor_values, curve_shape
from transform.erp import compute_erp

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("markets_dashboard.pipeline")

DATA_DIR = Path(__file__).parent / "site" / "data"


# ---------------------------------------------------------------------------
# LIVE MODE
# ---------------------------------------------------------------------------

# A source that returns HTTP 200 and parses cleanly can still be years out of
# date — the SNB bond-yield cube is the cautionary example. So "ok" means
# "fresh enough for its publication cadence", and anything older is "stale"
# so it shows up in source_status instead of quietly passing as current.
# "policy" is deliberately loose: a central bank rate legitimately sits
# unchanged for months, and BIS stops emitting observations between moves.
# "annual" allows for normal publication lag on yearly national accounts.
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
    status = "stale" if age_days > MAX_AGE_DAYS[cadence] else "ok"
    return status, pd.Timestamp(ts).strftime("%Y-%m-%d")


# Curve tenors are fetched through one dispatcher so a region only has to name
# its source in universe.py. Memoised because EZ mirrors DE's Bund keys and
# would otherwise refetch every tenor a second time.
_CURVE_FETCHERS = {
    "fred": lambda k: sources.fetch_fred(k),
    "bundesbank": lambda k: sources.fetch_bundesbank(k),
    "boe": lambda k: sources.fetch_boe(k),
    "mof": lambda k: sources.fetch_mof_jgb(k),
    "snb": lambda k: sources.fetch_snb(k),
    "chinabond": lambda k: sources.fetch_chinabond(k),
}


def _fetch_curve_tenor(source, key, cache):
    if not key:
        return None
    fetcher = _CURVE_FETCHERS.get(source)
    if fetcher is None:
        logger.warning("No fetcher registered for curve source %r", source)
        return None
    ck = (source, key)
    if ck not in cache:
        cache[ck] = fetcher(key)
    return cache[ck]


def run_live_pipeline() -> dict:
    status = {}
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_sample": False,
        "regions": universe.REGIONS,
        "region_names": universe.REGION_NAMES,
        "equity_indices": {},
        "currencies": [],
        "commodities": [],
        "central_bank_rates": {},
        "yield_curves": {},
        "eurozone_spread_panel": [],
        "inflation": {},
        "breakeven_inflation": {},
        "real_yields": {},
        "gdp_growth": {},
        "equity_risk_premia": {},
        "valuation": {},
        "source_status": status,
    }

    # --- Equity indices ---
    for idx in universe.EQUITY_INDICES:
        df = sources.fetch_yahoo(idx.get("yahoo"))
        status[f"equity:{idx['id']}"], _ = _series_status(df)
        metrics = compute_return_metrics(df) if df is not None else {}
        out["equity_indices"].setdefault(idx["region"], []).append({
            "id": idx["id"], "name": idx["name"], "currency": idx["currency"],
            **metrics,
            "history_1y": history_for_chart(df, 1.0) if df is not None else [],
        })

    # --- Currencies ---
    for fx in universe.CURRENCIES:
        df = sources.fetch_yahoo(fx.get("yahoo"))
        status[f"fx:{fx['id']}"], _ = _series_status(df)
        metrics = compute_return_metrics(df) if df is not None else {}
        out["currencies"].append({"id": fx["id"], "name": fx["name"], **metrics,
                                  "history_1y": history_for_chart(df, 1.0) if df is not None else []})

    # --- Commodities ---
    for cm in universe.COMMODITIES:
        df = sources.fetch_yahoo(cm.get("yahoo"))
        status[f"commodity:{cm['id']}"], _ = _series_status(df)
        metrics = compute_return_metrics(df) if df is not None else {}
        out["commodities"].append({"id": cm["id"], "name": cm["name"], **metrics,
                                   "history_1y": history_for_chart(df, 1.0) if df is not None else []})

    # --- Central bank policy rates ---
    for cb in universe.CENTRAL_BANKS:
        df = sources.fetch_bis_policy_rate(cb["bis_ref_area"])
        st, as_of = _series_status(df, "policy")
        status[f"cbrate:{cb['region']}"] = st
        latest = float(df.iloc[-1]["value"]) if df is not None and not df.empty else None
        out["central_bank_rates"][cb["region"]] = {"name": cb["name"], "rate_pct": latest,
                                                    "as_of": as_of}

    # --- Yield curves ---
    curve_cache = {}
    for region, cfg in universe.YIELD_CURVES.items():
        tenor_series = {t: _fetch_curve_tenor(cfg["source"], key, curve_cache)
                        for t, key in cfg["tenors"].items()}
        values = latest_tenor_values(tenor_series)
        shape = curve_shape(values)
        live = [t for t, df in tenor_series.items() if df is not None]
        wanted = [t for t, key in cfg["tenors"].items() if key]
        if not wanted or not live:
            st = "stubbed"
        elif len(live) < len(wanted):
            st = "partial"
        else:
            # A curve is only as fresh as its stalest tenor.
            st = "ok"
            for df in tenor_series.values():
                if df is not None and _series_status(df)[0] == "stale":
                    st = "stale"
                    break
        status[f"curve:{region}"] = st
        as_ofs = [_series_status(df)[1] for df in tenor_series.values() if df is not None]
        out["yield_curves"][region] = {"tenors": values, **shape,
                                       "as_of": max(as_ofs) if as_ofs else None,
                                       "source_note": cfg.get("note")}

    # --- Eurozone spread panel (stub) ---
    for entry in universe.EUROZONE_SPREAD_PANEL:
        status[f"spread:{entry['country']}"] = "stubbed"
        out["eurozone_spread_panel"].append({
            "country": entry["country"], "institution": entry["institution"],
            "spread_vs_bund_bp": None,
        })

    # --- Inflation (CPI) ---
    # BIS returns year-on-year percent directly, so there is no index
    # arithmetic here any more (see universe.INFLATION_CPI for why).
    for region, cfg in universe.INFLATION_CPI.items():
        df = sources.fetch_bis_cpi(cfg["ref_area"]) if cfg["source"] == "bis" else None
        st, as_of = _series_status(df, "monthly")
        status[f"cpi:{region}"] = st
        yoy = round(float(df.iloc[-1]["value"]), 2) if df is not None and not df.empty else None
        out["inflation"][region] = {"headline_cpi_yoy_pct": yoy, "as_of": as_of}

    # --- Breakeven inflation ---
    for region, cfg in universe.BREAKEVEN_INFLATION.items():
        if cfg.get("source") == "fred":
            vals, sts = {}, []
            for tenor_key in ("5y", "10y", "5y5y_fwd"):
                series_id = cfg.get(tenor_key)
                df = sources.fetch_fred(series_id) if series_id else None
                vals[tenor_key] = float(df.iloc[-1]["value"]) if df is not None and not df.empty else None
                if series_id:
                    sts.append(_series_status(df)[0])
            status[f"breakeven:{region}"] = ("failed" if all(x == "failed" for x in sts)
                                             else "stale" if "stale" in sts
                                             else "partial" if "failed" in sts else "ok")
            out["breakeven_inflation"][region] = vals
        else:
            status[f"breakeven:{region}"] = "stubbed"
            out["breakeven_inflation"][region] = {"note": cfg.get("note")}

    # --- Real yields ---
    for region, cfg in universe.REAL_YIELDS.items():
        if cfg.get("source") == "fred":
            df = sources.fetch_fred(cfg["10y"])
            st, as_of = _series_status(df)
            status[f"realyield:{region}"] = st
            val = float(df.iloc[-1]["value"]) if df is not None and not df.empty else None
            out["real_yields"][region] = {"10y_pct": val, "as_of": as_of,
                                          "history": history_for_chart(df, 20.0) if df is not None else []}
        else:
            status[f"realyield:{region}"] = "stubbed"
            out["real_yields"][region] = {"note": cfg.get("note")}

    # --- GDP growth ---
    # Sources are real GDP *levels*; growth is derived here so every region is
    # on the same year-on-year definition.
    for region, cfg in universe.GDP_GROWTH.items():
        df = sources.fetch_fred(cfg["series"]) if cfg["source"] == "fred" else None
        st, as_of = _series_status(df, cfg.get("cadence", "quarterly"))
        status[f"gdp:{region}"] = st
        lag = 4 if cfg.get("freq", "Q") == "Q" else 1  # periods in one year
        val = None
        if df is not None and len(df) > lag:
            prior = float(df.iloc[-1 - lag]["value"])
            if prior:
                val = round((float(df.iloc[-1]["value"]) / prior - 1) * 100, 2)
        out["gdp_growth"][region] = {"latest_pct": val, "as_of": as_of}

    # --- Valuation (stub for v1 live pipeline; Phase 4 work) ---
    for entry in universe.VALUATION_PROXIES:
        status[f"valuation:{entry['region']}"] = "stubbed"
        out["valuation"][entry["region"]] = {"name": entry["name"], "forward_pe": None,
                                              "cape": None, "dividend_yield_pct": None}

    # --- Equity risk premia (computed once valuation + yields are live) ---
    for region in universe.REGIONS:
        pe = out["valuation"].get(region, {}).get("forward_pe")
        y10 = out["yield_curves"].get(region, {}).get("tenors", {}).get("10Y")
        out["equity_risk_premia"][region] = {"erp_pct": compute_erp(pe, y10)}

    tally = {}
    for v in status.values():
        tally[v] = tally.get(v, 0) + 1
    logger.info("Live pipeline: %d/%d sources ok (%s)",
                tally.get("ok", 0), len(status),
                ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return out


# ---------------------------------------------------------------------------
# SAMPLE MODE — synthetic but structurally realistic data, so the frontend
# and layout can be built/tested without live network access.
# ---------------------------------------------------------------------------
def run_sample_pipeline() -> dict:
    rng = random.Random(42)
    today = datetime.now(timezone.utc)

    def fake_history(base, vol_pct, days=380):
        vals = []
        v = base
        for i in range(days, 0, -1):
            v *= (1 + rng.gauss(0, vol_pct / 100))
            d = today - timedelta(days=i)
            vals.append([d.strftime("%Y-%m-%d"), round(v, 2)])
        return vals

    def fake_metrics(base, vol_pct=1.0):
        hist = fake_history(base, vol_pct)
        level = hist[-1][1]
        return {
            "as_of": today.strftime("%Y-%m-%d"),
            "level": level,
            "chg_1d_pct": round(rng.gauss(0, 0.6), 2),
            "chg_1w_pct": round(rng.gauss(0, 1.5), 2),
            "chg_mtd_pct": round(rng.gauss(0, 2.5), 2),
            "chg_ytd_pct": round(rng.gauss(5, 8), 2),
            "chg_1y_pct": round(rng.gauss(8, 12), 2),
            "drawdown_from_ath_pct": round(-abs(rng.gauss(4, 4)), 2),
            "realized_vol_20d_pct": round(abs(rng.gauss(14, 4)), 2),
            "realized_vol_60d_pct": round(abs(rng.gauss(15, 4)), 2),
            "history_1y": hist,
        }

    out = {
        "generated_at": today.isoformat(),
        "is_sample": True,
        "regions": universe.REGIONS,
        "region_names": universe.REGION_NAMES,
        "equity_indices": {},
        "currencies": [],
        "commodities": [],
        "central_bank_rates": {},
        "yield_curves": {},
        "eurozone_spread_panel": [],
        "inflation": {},
        "breakeven_inflation": {},
        "real_yields": {},
        "gdp_growth": {},
        "equity_risk_premia": {},
        "valuation": {},
        "source_status": {},
    }

    base_levels = {"sp500": 5600, "nasdaq100": 19500, "russell2000": 2200, "ftse100": 8300,
                   "stoxx600": 520, "dax": 18800, "smi": 12200, "csi300": 3700,
                   "hangseng": 18500, "nikkei225": 39500, "msci_em": 42}
    for idx in universe.EQUITY_INDICES:
        m = fake_metrics(base_levels.get(idx["id"], 1000))
        out["equity_indices"].setdefault(idx["region"], []).append({
            "id": idx["id"], "name": idx["name"], "currency": idx["currency"], **m,
        })

    fx_base = {"dxy": 103, "eurusd": 1.09, "gbpusd": 1.27, "usdjpy": 152, "usdchf": 0.88,
               "eurchf": 0.96, "usdcny": 7.2}
    for fx in universe.CURRENCIES:
        out["currencies"].append({"id": fx["id"], "name": fx["name"],
                                   **fake_metrics(fx_base.get(fx["id"], 1), vol_pct=0.4)})

    cmd_base = {"brent": 78, "natgas": 2.6, "gold": 2450, "silver": 29, "copper": 4.3, "bcom": 22}
    for cm in universe.COMMODITIES:
        out["commodities"].append({"id": cm["id"], "name": cm["name"],
                                    **fake_metrics(cmd_base.get(cm["id"], 100), vol_pct=1.2)})

    cb_rates = {"US": 4.50, "UK": 4.25, "EZ": 3.00, "CH": 1.00, "CN": 3.10, "JP": 0.50}
    for cb in universe.CENTRAL_BANKS:
        out["central_bank_rates"][cb["region"]] = {"name": cb["name"], "rate_pct": cb_rates.get(cb["region"])}

    curve_base = {"US": {"2Y": 4.1, "5Y": 4.0, "10Y": 4.3, "30Y": 4.6},
                  "UK": {"2Y": 4.0, "5Y": 4.0, "10Y": 4.4, "30Y": 4.9},
                  "DE": {"2Y": 2.3, "5Y": 2.4, "10Y": 2.7, "30Y": 3.1},
                  "CH": {"2Y": 0.4, "5Y": 0.5, "10Y": 0.7, "30Y": 1.0},
                  "CN": {"2Y": 1.6, "5Y": 1.8, "10Y": 2.1, "30Y": 2.4},
                  "JP": {"2Y": 0.5, "5Y": 0.7, "10Y": 1.1, "30Y": 2.2}}
    for region in universe.REGIONS:
        tenors = curve_base.get(region, {"2Y": None, "5Y": None, "10Y": None, "30Y": None})
        shape = {}
        if tenors.get("2Y") is not None and tenors.get("10Y") is not None:
            shape["2s10s_bp"] = round((tenors["10Y"] - tenors["2Y"]) * 100, 1)
        out["yield_curves"][region] = {"tenors": tenors, **shape}
        if region == "EZ":
            out["yield_curves"][region]["tenors"] = curve_base["DE"]  # Bund is the EZ benchmark

    for entry in universe.EUROZONE_SPREAD_PANEL:
        out["eurozone_spread_panel"].append({"country": entry["country"],
                                              "institution": entry["institution"],
                                              "spread_vs_bund_bp": round(abs(rng.gauss(60, 30)), 1)})

    cpi_base = {"US": 2.9, "UK": 2.6, "EZ": 2.2, "DE": 2.1, "CH": 0.6, "CN": 0.3, "JP": 2.8}
    for region in universe.REGIONS:
        out["inflation"][region] = {"headline_cpi_yoy_pct": cpi_base.get(region)}

    out["breakeven_inflation"] = {
        "US": {"5y": 2.3, "10y": 2.35, "5y5y_fwd": 2.4},
        "UK": {"note": "stubbed — BoE source not yet wired"},
        "EZ": {"note": "stubbed — ECB source not yet wired"},
    }
    out["real_yields"] = {"US": {"10y_pct": 2.0, "history": fake_history(2.0, 3.0, days=3650)},
                           "UK": {"note": "stubbed — BoE source not yet wired"}}

    gdp_base = {"US": 2.3, "UK": 1.1, "EZ": 0.9, "DE": 0.4, "CH": 1.3, "CN": 4.8, "JP": 0.7}
    for region in universe.REGIONS:
        out["gdp_growth"][region] = {"latest_pct": gdp_base.get(region)}

    val_base = {"US": (22.5, 34.2, 1.3), "UK": (13.1, None, 3.4), "EZ": (14.8, None, 3.0),
                "DE": (13.9, None, 3.1), "CH": (18.2, None, 2.6), "CN": (11.4, None, 2.5),
                "JP": (16.7, None, 2.1)}
    for entry in universe.VALUATION_PROXIES:
        pe, cape, dy = val_base.get(entry["region"], (None, None, None))
        out["valuation"][entry["region"]] = {"name": entry["name"], "forward_pe": pe,
                                              "cape": cape, "dividend_yield_pct": dy}

    for region in universe.REGIONS:
        pe = out["valuation"].get(region, {}).get("forward_pe")
        y10 = out["yield_curves"].get(region, {}).get("tenors", {}).get("10Y")
        out["equity_risk_premia"][region] = {"erp_pct": compute_erp(pe, y10)}

    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["live", "sample"], default="sample")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    data = run_live_pipeline() if args.mode == "live" else run_sample_pipeline()

    out_path = DATA_DIR / "latest.json"
    out_path.write_text(json.dumps(data, indent=2))
    logger.info("Wrote %s (%d bytes, mode=%s)", out_path, out_path.stat().st_size, args.mode)


if __name__ == "__main__":
    main()
