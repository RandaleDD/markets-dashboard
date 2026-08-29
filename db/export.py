"""
Export: turn what the database currently holds into site/data/latest.json.

Deliberately a separate step from ingest (SPEC.md, "JSON export --
decoupled from fetching"). The number the dashboard shows is always the
database's own answer as of the last run, never a value computed from whatever
this run happened to fetch. That is what lets the ingest step be cheap and
incremental while the export stays comprehensive: every derived metric is
computed over the FULL accumulated history, read back with one local SQL query.

The output shape is unchanged from the pre-database pipeline, so
`site/index.html` and `site/assets/app.js` need no edits -- `tests/
test_export_shape.py` holds that line.

Every `hist[...]` lookup below reads `latest_observations`, so a revised GDP
print is picked up automatically: the view resolves to the newest vintage
without anything here knowing that revisions exist.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from db import registry, store
from fetch import universe
from transform.correlation import rolling_correlation_matrix
from transform.cost_of_capital import stack_cost_of_capital
from transform.curves import curve_shape, latest_tenor_values
from transform.fx_hedging import approx_hedging_cost
from transform.percentile import has_any, percentile_context
from transform.regime import AXIS_DEFINITION, regime_coordinates
from transform.returns import (ANNUALISE, WEEKS_PER_QUARTER, compact_history,
                               compute_return_metrics)

logger = logging.getLogger("markets_dashboard.db.export")

MAX_AGE_DAYS = registry.MAX_AGE_DAYS

# Periods per year, per GDP publication frequency. UK is monthly since the
# switch to ONS's own index, so "year on year" is 12 observations back there
# and 4 for the quarterly regions -- getting this wrong would silently report
# a one-quarter change as an annual one.
PERIODS_PER_YEAR = {"M": 12, "Q": 4, "A": 1}


# ---------------------------------------------------------------------------
# Small helpers over a [date, value] frame. Identical semantics to the ones the
# pre-database pipeline used; the only change is where the frame comes from.
# ---------------------------------------------------------------------------
def _series_status(df, cadence="weekly"):
    """(status, as_of) for one series, against its own publication cadence."""
    if df is None or df.empty:
        return "failed", None
    ts = pd.Timestamp(df.iloc[-1]["date"])
    age_days = (pd.Timestamp.now() - ts).days
    return ("stale" if age_days > MAX_AGE_DAYS[cadence] else "ok"), ts.strftime("%Y-%m-%d")


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
    Percentile/z-score context over the full stored history.

    Before the database this had to be fed the untrimmed fetch, because the
    stored archive only reached back to project launch. That distinction is
    gone: `latest_observations` IS the full history now, and it keeps growing.
    """
    ctx = percentile_context(df, latest_value)
    return ctx if has_any(ctx) else None


def _ctx_if_varies(df):
    """
    _ctx, but only where the series actually moves.

    A percentile is meaningless on a flat line: the Aaa sovereigns (DE, CH, NO)
    carry a country risk premium of exactly 0.00 in all 26 stored years, and
    percentile_context would dutifully report that as the 100th percentile.
    Same reasoning as the deliberate absence of a percentile on index levels.
    """
    if df is None or len(df) < 2:
        return None
    if float(df["value"].astype(float).std(ddof=0)) <= 0.0:
        return None
    return _ctx(df)


def _drawdown_series(df):
    """Drawdown from running peak, in percent -- mean-reverting, so a
    percentile against its own history is informative."""
    if df is None or len(df) < 2:
        return None
    out = df.dropna(subset=["value"]).sort_values("date").copy()
    out["value"] = (out["value"] / out["value"].cummax() - 1.0) * 100.0
    return out


def _rolling_vol_series(df, window=WEEKS_PER_QUARTER):
    """
    Annualised rolling close-to-close volatility, in percent.

    A quarter-long window of WEEKLY returns, annualised with sqrt(52) -- the
    same horizon and the same units as the headline `realized_vol_13w_pct`, so
    the percentile this feeds is a percentile of the number actually displayed.
    """
    if df is None or len(df) < window + 2:
        return None
    out = df.dropna(subset=["value"]).sort_values("date").copy()
    out["value"] = out["value"].pct_change().rolling(window).std() * float(ANNUALISE) * 100.0
    return out.dropna(subset=["value"])


def _build_curve(region, cfg, hist, status, prefix, id_prefix):
    """Shared assembly for the nominal and real curve tables."""
    tenor_series = {t: hist.get(f"{id_prefix}.{region}.{t}") if key else None
                    for t, key in cfg["tenors"].items()}
    values = latest_tenor_values(tenor_series)
    live = [t for t, df in tenor_series.items() if df is not None]
    wanted = [t for t, key in cfg["tenors"].items() if key]
    # universe.py still describes a curve by how often its SOURCE publishes;
    # anything published daily is stored weekly, so the staleness threshold has
    # to be the stored cadence, not the published one.
    cadence = registry._cadence(cfg)
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
        "unofficial": cfg.get("unofficial", False),
        "basis": cfg.get("basis"),
        # Per-tenor history, so the Rates chart can draw the curve as it stood
        # on any past date rather than only today. Nominal curves only, and
        # three years rather than five: this is the single heaviest thing in
        # the payload, and the real-yield table has no date picker to feed.
        "tenor_history": ({t: compact_history(df, years=3)
                           for t, df in tenor_series.items() if df is not None}
                          if prefix == "curve" else None),
    }


def empty_payload(is_sample: bool) -> dict:
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
        "liquidity": [],
        "fx_hedging": [],
        "regime": {"axis_definition": "", "regions": {}},
        "correlation": {"windows": {}, "note": ""},
        "cost_of_capital": {},
        "cost_of_capital_note": "",
        "valuation": {},
        "equity_risk_premia": {},
        "source_status": {},
        "data_quality": {},
    }


# ---------------------------------------------------------------------------
# The export itself
# ---------------------------------------------------------------------------
def build_payload(conn, is_sample: bool = False) -> dict:
    """Read the whole database once, then derive everything from that."""
    hist = store.read_all_series(conn)
    status: dict[str, str] = {}
    out = empty_payload(is_sample)

    # --- Equity indices ---
    for idx in universe.EQUITY_INDICES:
        df = hist.get(f"equity.{idx['region']}.{idx['id']}")
        status[f"equity:{idx['id']}"], _ = _series_status(df)
        # A price level's percentile is near-meaningless for a trending series
        # (any index in an uptrend sits at ~100th). Volatility and drawdown are
        # mean-reverting, so those are what carry context here.
        out["equity_indices"].setdefault(idx["region"], []).append({
            "id": idx["id"], "name": idx["name"], "currency": idx["currency"],
            "region": idx["region"],
            # Drives the tooltip on the index name: how it is weighted and
            # whether its level includes dividends.
            "weighting": idx.get("weighting"), "basis": idx.get("basis"),
            **(compute_return_metrics(df) if df is not None else {}),
            "vol_context": _ctx(_rolling_vol_series(df)) if df is not None else None,
            "drawdown_context": _ctx(_drawdown_series(df)) if df is not None else None,
            "history": compact_history(df) if df is not None else [],
        })

    # --- Currencies ---
    for fx in universe.CURRENCIES:
        df = hist.get(f"fx.{fx['id']}")
        status[f"fx:{fx['id']}"], _ = _series_status(df)
        out["currencies"].append({
            "id": fx["id"], "name": fx["name"],
            **(compute_return_metrics(df) if df is not None else {}),
            "context": _ctx(df) if df is not None else None,
            "history": compact_history(df) if df is not None else [],
        })

    # --- Commodities (each carries exchange/contract/unit) ---
    for cm in universe.COMMODITIES:
        df = hist.get(f"commodity.{cm['id']}")
        status[f"commodity:{cm['id']}"], _ = _series_status(df)
        out["commodities"].append({
            "id": cm["id"], "name": cm["name"], "exchange": cm["exchange"],
            "contract": cm["contract"], "unit": cm["unit"],
            **(compute_return_metrics(df) if df is not None else {}),
            "context": _ctx(df) if df is not None else None,
            "history": compact_history(df) if df is not None else [],
        })

    # --- Gold / copper, derived from the two commodities above rather than
    # sourced again. A classic risk gauge: copper is an industrial input and
    # gold is not, so the ratio rises when growth expectations fall. Both legs
    # are the same source and vintage, which is what makes the ratio honest.
    gold_df, copper_df = hist.get("commodity.gold"), hist.get("commodity.copper")
    ratio_df = None
    if gold_df is not None and copper_df is not None:
        merged = gold_df.merge(copper_df, on="date", suffixes=("_g", "_c"))
        merged = merged[merged["value_c"] > 0]
        if not merged.empty:
            ratio_df = pd.DataFrame({"date": merged["date"],
                                     "value": merged["value_g"] / merged["value_c"]})
    status["commodity:gold_copper"] = "ok" if ratio_df is not None else "stubbed"
    out["commodities"].append({
        "id": "gold_copper", "name": "Gold / Copper ratio", "exchange": "COMEX",
        "contract": "Gold front month \u00f7 Copper front month",
        "unit": "ratio (troy oz gold per lb copper)",
        "derived_from": ["commodity.gold", "commodity.copper"],
        **(compute_return_metrics(ratio_df) if ratio_df is not None else {}),
        "context": _ctx(ratio_df) if ratio_df is not None else None,
        "history": compact_history(ratio_df) if ratio_df is not None else [],
    })

    # --- Macro: policy rates. Germany reads the ECB series it mirrors rather
    # than a second stored copy of the same numbers. ---
    for cb in universe.CENTRAL_BANKS:
        df = hist.get(f"policy_rate.{cb.get('mirror_of') or cb['region']}")
        st, as_of = _series_status(df, "policy")
        status[f"cbrate:{cb['region']}"] = st
        out["macro"]["policy_rates"][cb["region"]] = {
            "name": cb["name"], "rate_pct": _latest(df), "as_of": as_of,
            "context": _ctx(df) if df is not None else None}

    # --- Macro: inflation (YoY series, annualised QoQ from the index series) ---
    cpi_frames = {}
    for region in universe.INFLATION_CPI:
        yoy_df = hist.get(f"cpi.{region}")
        idx_df = hist.get(f"cpi.{region}.index")
        cpi_frames[region] = yoy_df
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
    gdp_frames = {}
    for region, cfg in universe.GDP_GROWTH.items():
        df = hist.get(f"gdp.{region}")
        gdp_frames[region] = df
        freq = cfg.get("freq", "Q")
        st, as_of = _series_status(df, cfg.get("cadence", "annual" if freq == "A" else "quarterly"))
        status[f"gdp:{region}"] = st
        out["macro"]["gdp"][region] = {
            "yoy_pct": _pct_change(df, PERIODS_PER_YEAR[freq]),
            # The short-horizon annualised rate: one quarter for quarterly
            # regions, the equivalent three months for monthly UK. An annual
            # series has no such thing, so it stays None.
            "qoq_ann_pct": (_pct_change(df, 1, annualise=4) if freq == "Q"
                            else _pct_change(df, 3, annualise=4) if freq == "M"
                            else None),
            "freq": freq,
            "as_of": as_of,
        }
    out["macro"]["gdp_definition"] = universe.GDP_DEFINITION

    # --- Growth / inflation regime coordinates (pure derivation) ---
    out["regime"]["axis_definition"] = AXIS_DEFINITION
    for region in universe.REGIONS:
        cfg = universe.GDP_GROWTH.get(region, {})
        pts = regime_coordinates(gdp_frames.get(region), cpi_frames.get(region),
                                 cfg.get("freq", "Q"), quarters=8)
        status[f"regime:{region}"] = "ok" if len(pts) >= 2 else "stubbed"
        out["regime"]["regions"][region] = pts

    # --- Nominal and real yield curves ---
    for region, cfg in universe.YIELD_CURVES.items():
        out["yield_curves"][region] = _build_curve(region, cfg, hist, status, "curve", "curve")
    for region, cfg in universe.REAL_YIELD_CURVES.items():
        out["real_yield_curves"][region] = _build_curve(
            region, cfg, hist, status, "realyield", "real_yield")

    # --- Inflation expectations ---
    for region, cfg in universe.INFLATION_EXPECTATIONS.items():
        out["inflation_expectations"][region] = _inflation_expectations(region, cfg, hist, status)

    # --- Euro-area sovereign spreads.
    # Both legs are the same ECB series family and the same vintage, which is
    # the whole point of storing the yields rather than a precomputed spread. ---
    bench = universe.EUROZONE_SPREAD_BENCHMARK
    bench_df = hist.get("spread_benchmark.DE")
    bench_yield = _latest(bench_df)
    bench_st, bench_as_of = _series_status(bench_df, "monthly")
    out["eurozone_spreads"]["benchmark"] = bench["country"]
    out["eurozone_spreads"]["benchmark_yield_pct"] = bench_yield
    out["eurozone_spreads"]["as_of"] = bench_as_of
    out["eurozone_spreads"]["cadence"] = "monthly"
    for entry in universe.EUROZONE_SPREAD_PANEL:
        code = entry["ecb_key"].split(".")[1]
        df = hist.get(f"spread.{code}")
        # Context belongs on the spread's own history, not the yield's -- a
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

    # --- Valuation (CAPE + Damodaran country multiples) and ERP ---
    cape_df = hist.get("valuation.US.cape")
    cape_st, cape_as_of = _series_status(cape_df, "monthly")
    erp_df = hist.get("erp.US")
    erp_st, erp_as_of = _series_status(erp_df, "annual")
    # The mature-market base every Damodaran country risk premium is added to.
    base_erp = _latest(erp_df)

    for entry in universe.VALUATION_PROXIES:
        region = entry["region"]
        is_us = entry.get("cape_source") == "shiller"
        multiples, mult_as_of, mult_st = {}, None, None
        for m in universe.VALUATION_MULTIPLES:
            mdf = hist.get(f"valuation.{region}.{m['id']}")
            value = _latest(mdf)
            if value is None:
                continue
            mult_st, mult_as_of = _series_status(mdf, "annual")
            multiples[m["id"]] = {
                "value": round(value, 2),
                "name": m["name"],
                "context": _ctx_if_varies(mdf),
            }
        if is_us:
            val_status = cape_st
        elif multiples:
            val_status = mult_st
        else:
            val_status = "stubbed"
        status[f"valuation:{region}"] = val_status
        out["valuation"][region] = {
            "name": entry["name"],
            "cape": round(_latest(cape_df), 2) if (is_us and _latest(cape_df) is not None) else None,
            "cape_as_of": cape_as_of if is_us else None,
            "cape_context": (_ctx(cape_df) if is_us and cape_df is not None else None),
            "multiples": multiples or None,
            "multiples_as_of": mult_as_of,
            "multiples_basis": ("Median across listed companies in the country, trailing. "
                                "NOT cyclically adjusted, so not comparable to US CAPE."
                                if multiples else None),
            "note": None if (is_us or multiples) else
                    "Damodaran publishes member states only, with no Eurozone aggregate "
                    "(DATA-CATALOG.csv: valuation.EZ is descoped, not pending).",
        }

    for region in universe.REGIONS:
        if region == "US" and _latest(erp_df) is not None:
            status["erp:US"] = erp_st
            out["equity_risk_premia"]["US"] = {
                "erp_pct": round(_latest(erp_df), 2),
                "country_risk_premium_pct": None,
                "method": "Damodaran implied ERP (FCFE), S&P 500",
                "as_of": erp_as_of,
                "context": _ctx(erp_df),
            }
            continue
        # The stored series is the rating-based COUNTRY risk premium -- a spread
        # over a mature market, and exactly 0.00 for every Aaa sovereign. Adding
        # the mature-market base back on reproduces Damodaran's own "Total Equity
        # Risk Premium" column (UK: 4.23 + 0.776 = 5.006, matching the file), and
        # keeps the displayed number comparable to the US reading beside it.
        # Both legs are Damodaran at the same annual vintage.
        crp_df = hist.get(f"erp.{region}")
        crp = _latest(crp_df)
        if crp is not None and base_erp is not None:
            crp_st, crp_as_of = _series_status(crp_df, "annual")
            status[f"erp:{region}"] = crp_st
            out["equity_risk_premia"][region] = {
                "erp_pct": round(base_erp + crp, 2),
                "country_risk_premium_pct": round(crp, 2),
                "method": ("Damodaran total ERP: US mature-market base (implied, FCFE) "
                           "plus the rating-based country risk premium"),
                "as_of": crp_as_of,
                # The percentile describes the country premium, the part that
                # actually moves; it is suppressed for the Aaa sovereigns whose
                # premium has been flat zero for the whole history.
                "context": _ctx_if_varies(crp_df),
            }
            continue
        # Only the Eurozone reaches here: Damodaran publishes member states with
        # no bloc aggregate, and no other free source exists. Left empty rather
        # than filled with a number built a different way.
        status[f"erp:{region}"] = "stubbed"
        out["equity_risk_premia"][region] = {
            "erp_pct": None,
            "country_risk_premium_pct": None,
            "method": None,
            "as_of": None,
            "context": None,
        }

    # --- Credit spreads (ICE BofA OAS) ---
    stack_credit = {}
    for cs in universe.CREDIT_SPREADS:
        df = hist.get(cs["series_id"])
        st, as_of = _series_status(df)
        status[f"credit:{cs['id']}"] = st
        level = _latest(df)
        out["credit_spreads"].append({
            "id": cs["id"], "region": cs["region"], "name": cs["name"],
            "grade": cs["grade"],
            # Stored in percent; credit is quoted and discussed in basis
            # points, so the display figure is bp and the key says so.
            "spread_bp": round(level * 100) if level is not None else None,
            "basis": "Option-adjusted spread over government bonds — the extra "
                     "yield the index pays, adjusted for issuers' rights to "
                     "call bonds early.",
            "as_of": as_of, "context": _ctx(df) if df is not None else None,
        })
        if cs.get("stack_leg") and level is not None:
            stack_credit[cs["region"]] = round(level, 2)

    # --- Liquidity / lending conditions ---
    for li in universe.LIQUIDITY_INDICATORS:
        df = hist.get(li["series_id"])
        # Quarterly cadence, not the daily default -- see universe.py.
        st, as_of = _series_status(df, li.get("cadence", "quarterly"))
        status[f"liquidity:{li['id']}"] = st
        level = _latest(df)
        prior = float(df.iloc[-2]["value"]) if df is not None and len(df) > 1 else None
        out["liquidity"].append({
            "id": li["id"], "region": li["region"], "name": li["name"],
            "unit": li["unit"], "note": li.get("note"),
            "level": round(level, 1) if level is not None else None,
            "change": round(level - prior, 1) if (level is not None and prior is not None) else None,
            "as_of": as_of, "cadence": li.get("cadence", "quarterly"),
            "context": _ctx(df) if df is not None else None,
        })

    # --- Cross-asset rolling correlations.
    # Six of the eight legs are series stored for other panels; they are read
    # back by series_id rather than fetched or stored a second time. ---
    ca_frames = {}
    for a in universe.CROSS_ASSET_SET:
        df = hist.get(a["series_id"])
        status[f"crossasset:{a['id']}"] = _series_status(df)[0]
        if df is not None:
            ca_frames[a["label"]] = df
    out["correlation"]["note"] = (
        "Pearson correlation of weekly returns, not price levels — two trending "
        "price series correlate near 1.0 whether or not they actually move "
        "together. Computed on weeks these assets share, since they trade on "
        "different calendars and a holiday shifts one of them off Friday.")
    for w in universe.CORRELATION_WINDOWS:
        m = rolling_correlation_matrix(ca_frames, w)
        status[f"correlation:{w}w"] = "ok" if m["labels"] and m["n_obs"] else "stubbed"
        out["correlation"]["windows"][str(w)] = m

    # --- FX hedging cost (CHF investor) ---
    chf_rate = (out["macro"]["policy_rates"].get(universe.FX_HEDGING_HOME_REGION, {}) or {}).get("rate_pct")
    for h in universe.FX_HEDGING:
        foreign = (out["macro"]["policy_rates"].get(h["foreign_region"], {}) or {}).get("rate_pct")
        calc = approx_hedging_cost(foreign, chf_rate)
        status[f"fxhedge:{h['id']}"] = "ok" if calc["cost_pct"] is not None else "stubbed"
        out["fx_hedging"].append({
            "id": h["id"], "name": h["name"], "foreign_ccy": h["foreign_ccy"],
            "foreign_rate_pct": foreign, "chf_rate_pct": chf_rate, **calc,
        })

    # --- Cost-of-capital stack (real risk-free + IG spread + ERP) ---
    out["cost_of_capital_note"] = universe.COST_OF_CAPITAL_NOTE
    for region in universe.REGIONS:
        # NOMINAL 10y, not real. Damodaran's implied ERP -- which now feeds
        # every region -- is computed against the nominal 10y Treasury, so
        # pairing it with a real risk-free removed inflation twice. Nominal
        # also matches standard practice: the risk-free is the government
        # yield in the currency and duration of the cash flows. It fills the
        # table too, since 7 of 8 regions have a nominal 10y where only 2 have
        # a real one.
        nominal = (out["yield_curves"].get(region, {}).get("tenors", {}) or {}).get("10Y")
        erp = (out["equity_risk_premia"].get(region, {}) or {}).get("erp_pct")
        stack = stack_cost_of_capital(nominal, stack_credit.get(region), erp)
        status[f"costcap:{region}"] = ("ok" if stack["complete"]
                                       else "partial" if stack["total_pct"] is not None
                                       else "stubbed")
        out["cost_of_capital"][region] = stack

    out["source_status"] = status
    tally = {}
    for v in status.values():
        tally[v] = tally.get(v, 0) + 1
    logger.info("Export: %d/%d panels ok (%s)", tally.get("ok", 0), len(status),
                ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return out


def _inflation_expectations(region, cfg, hist, status):
    """Market-implied where linkers exist; model-implied or explicit gap otherwise."""
    if cfg.get("kind") == "unavailable" or not cfg.get("source"):
        status[f"inflexp:{region}"] = "stubbed"
        return {"kind": "unavailable", "note": cfg.get("note"), "tenors": {}}

    infix = ".market" if region == "US" else ""
    tenors, sts, context = {}, [], {}
    for label in cfg["tenors"]:
        df = hist.get(f"inflexp.{region}{infix}.{label}")
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
        for label in model["tenors"]:
            v = _latest(hist.get(f"inflexp.{region}.model.{label}"))
            mt[label] = round(v, 2) if v is not None else None
        out["model"] = {"kind": "model", "basis": model.get("basis"), "tenors": mt,
                        "note": "Cleveland Fed model-implied (TIPS + swaps + survey); "
                                "no 1y TIPS breakeven is published."}

    status[f"inflexp:{region}"] = ("failed" if all(x == "failed" for x in sts)
                                   else "stale" if "stale" in sts
                                   else "partial" if "failed" in sts else "ok")
    return out
