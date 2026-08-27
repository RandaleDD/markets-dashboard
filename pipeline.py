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
        df = sources.fetch_stooq(idx.get("stooq"))
        status[f"equity:{idx['id']}"] = "ok" if df is not None else "failed"
        metrics = compute_return_metrics(df) if df is not None else {}
        out["equity_indices"].setdefault(idx["region"], []).append({
            "id": idx["id"], "name": idx["name"], "currency": idx["currency"],
            **metrics,
            "history_1y": history_for_chart(df, 1.0) if df is not None else [],
        })

    # --- Currencies ---
    for fx in universe.CURRENCIES:
        df = sources.fetch_stooq(fx.get("stooq"))
        status[f"fx:{fx['id']}"] = "ok" if df is not None else "failed"
        metrics = compute_return_metrics(df) if df is not None else {}
        out["currencies"].append({"id": fx["id"], "name": fx["name"], **metrics})

    # --- Commodities ---
    for cm in universe.COMMODITIES:
        df = sources.fetch_stooq(cm.get("stooq"))
        status[f"commodity:{cm['id']}"] = "ok" if df is not None else "failed"
        metrics = compute_return_metrics(df) if df is not None else {}
        out["commodities"].append({"id": cm["id"], "name": cm["name"], **metrics})

    # --- Central bank policy rates ---
    for cb in universe.CENTRAL_BANKS:
        df = sources.fetch_bis_policy_rate(cb["bis_ref_area"])
        status[f"cbrate:{cb['region']}"] = "ok" if df is not None else "failed"
        latest = None
        if df is not None and not df.empty:
            latest = float(df.iloc[-1]["value"])
        out["central_bank_rates"][cb["region"]] = {"name": cb["name"], "rate_pct": latest}

    # --- Yield curves ---
    for region, cfg in universe.YIELD_CURVES.items():
        tenor_series = {}
        for tenor, series_id in cfg["tenors"].items():
            if cfg["source"] == "fred" and series_id:
                tenor_series[tenor] = sources.fetch_fred(series_id)
            else:
                tenor_series[tenor] = None  # non-US sources not yet wired, see universe.py notes
        values = latest_tenor_values(tenor_series)
        shape = curve_shape(values)
        status[f"curve:{region}"] = "ok" if any(v is not None for v in values.values()) else "stubbed"
        out["yield_curves"][region] = {"tenors": values, **shape,
                                        "source_note": cfg.get("note")}

    # --- Eurozone spread panel (stub) ---
    for entry in universe.EUROZONE_SPREAD_PANEL:
        status[f"spread:{entry['country']}"] = "stubbed"
        out["eurozone_spread_panel"].append({
            "country": entry["country"], "institution": entry["institution"],
            "spread_vs_bund_bp": None,
        })

    # --- Inflation (CPI) ---
    for region, cfg in universe.INFLATION_CPI.items():
        df = sources.fetch_fred(cfg["headline"]) if cfg["source"] == "fred" else None
        status[f"cpi:{region}"] = "ok" if df is not None else "failed"
        yoy = None
        if df is not None and len(df) > 12:
            latest = df.iloc[-1]["value"]
            year_ago = df.iloc[-13]["value"]
            if year_ago:
                yoy = round((latest / year_ago - 1) * 100, 2)
        out["inflation"][region] = {"headline_cpi_yoy_pct": yoy}

    # --- Breakeven inflation ---
    for region, cfg in universe.BREAKEVEN_INFLATION.items():
        if cfg.get("source") == "fred":
            vals = {}
            for tenor_key in ("5y", "10y", "5y5y_fwd"):
                series_id = cfg.get(tenor_key)
                df = sources.fetch_fred(series_id) if series_id else None
                vals[tenor_key] = float(df.iloc[-1]["value"]) if df is not None and not df.empty else None
            status[f"breakeven:{region}"] = "ok" if any(vals.values()) else "failed"
            out["breakeven_inflation"][region] = vals
        else:
            status[f"breakeven:{region}"] = "stubbed"
            out["breakeven_inflation"][region] = {"note": cfg.get("note")}

    # --- Real yields ---
    for region, cfg in universe.REAL_YIELDS.items():
        if cfg.get("source") == "fred":
            df = sources.fetch_fred(cfg["10y"])
            status[f"realyield:{region}"] = "ok" if df is not None else "failed"
            val = float(df.iloc[-1]["value"]) if df is not None and not df.empty else None
            out["real_yields"][region] = {"10y_pct": val,
                                           "history": history_for_chart(df, 20.0) if df is not None else []}
        else:
            status[f"realyield:{region}"] = "stubbed"
            out["real_yields"][region] = {"note": cfg.get("note")}

    # --- GDP growth ---
    for region, cfg in universe.GDP_GROWTH.items():
        df = sources.fetch_fred(cfg["series"]) if cfg["source"] == "fred" else None
        status[f"gdp:{region}"] = "ok" if df is not None else "failed"
        val = float(df.iloc[-1]["value"]) if df is not None and not df.empty else None
        out["gdp_growth"][region] = {"latest_pct": val}

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

    ok_count = sum(1 for v in status.values() if v == "ok")
    logger.info("Live pipeline: %d/%d sources ok", ok_count, len(status))
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
