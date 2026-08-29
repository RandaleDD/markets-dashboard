"""
Data-quality routines, run after ingest and before export.

Findings are written to `data_quality_flags` rather than only logged, which is
the point of having the table: `source_status` answers "is this series fresh
right now", and it is a fresh answer every run with no memory. A flag persists,
so "how complete is this, really" can be asked as a trend.

Three of the four checks are deliberately bounded to a recent window. On a
database seeded with 47 years of UK gilt curve, an unbounded gap check would
raise flags for closures in 1983, and a recent, actionable finding would be
invisible among them. History that is already stored cannot be fixed by a
future fetch; what matters is whether the data arriving NOW is sound. The
windows are named constants below.

Everything here reads the stored grain, which is weekly for any source that
publishes faster than that (see `db/ingest.to_weekly`). So "a gap" means a
missing WEEK, and the outlier check is calibrated on week-over-week changes.

Thresholds are self-calibrating wherever a fixed number would be a guess: the
outlier check measures each series against its own change distribution using a
median/MAD z-score, so a quiet policy rate and a volatile gas future are judged
on their own terms and neither needs hand-tuning.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from db import registry, store

logger = logging.getLogger("markets_dashboard.db.quality")

# How far back each check looks. See the module docstring for why these exist.
GAP_WINDOW_DAYS = 730       # two years of cadence gaps
OUTLIER_WINDOW_DAYS = 30    # only values that arrived recently can still be wrong
CURVE_WINDOW_DAYS = 30

# Storage is weekly, so consecutive observations sit ~7 days apart. Allowing 14
# tolerates the one case that is not a fault -- a week whose Friday was a market
# holiday shifts its stored date to the Thursday, which can stretch one interval
# to 8 days and shorten the next. A genuine missing week exceeds this.
MAX_WEEK_GAP_DAYS = 14

# Below this many observations a change distribution is not worth calibrating
# against, so the outlier check stays silent rather than guessing.
OUTLIER_MIN_OBS = 60
# Calibrate the scale on the recent past, not on all of it. These series are
# not stationary in level: the S&P 500 has grown 444x since 1928, so the median
# absolute WEEKLY move is 1.35 points measured over the full history and 86
# points measured over 2026. A full-history scale makes every recent week an
# outlier -- measured, and the reason this window exists.
OUTLIER_CALIBRATION_OBS = 260   # ~5 years of weekly observations
# Modified z-score threshold. Deliberately high: these series are fat-tailed by
# nature and the check is hunting DATA errors (a misplaced decimal, the
# Damodaran fraction-vs-percent mix-up NETWORK.md already hit once), not
# genuine volatility. A 2008-scale weekly equity move lands near 8; a
# factor-of-ten unit error lands in the hundreds.
OUTLIER_Z = 12.0
# 0.6745 is the 75th percentile of the standard normal: it rescales MAD so the
# threshold is readable on the same scale as an ordinary z-score.
MAD_TO_SIGMA = 0.6745

# A real yield curve, including any inversion ever printed, spans well under
# this between its shortest and longest tenor. Catches a stray 50.0 where 5.0
# was meant without touching a genuine curve shape.
MAX_CURVE_SPREAD_PP = 10.0


def run_all(conn, series: list[registry.Series] | None = None) -> dict:
    """Every check, flags written, and the completeness report returned."""
    series = series if series is not None else registry.all_series()
    raised = {"stale": 0, "gap": 0, "outlier": 0, "curve_inconsistency": 0}

    hist = store.read_all_series(conn)
    for s in series:
        df = hist.get(s.series_id)
        raised["stale"] += check_staleness(conn, s, df)
        raised["gap"] += check_gaps(conn, s, df)
        raised["outlier"] += check_outliers(conn, s, df)
    raised["curve_inconsistency"] += check_curve_consistency(conn, series, hist)
    conn.commit()

    report = completeness(conn, series, hist)
    report["flags_raised_this_run"] = {k: v for k, v in raised.items() if v}
    report["open_flags"] = store.open_flag_tally(conn)
    logger.info("Quality: %d fresh, %d stale, %d missing of %d series; "
                "flags raised this run: %s; open flags: %s",
                report["fresh"], report["stale"], report["missing"], report["series"],
                report["flags_raised_this_run"] or "none", report["open_flags"] or "none")
    return report


# ---------------------------------------------------------------------------
# Staleness -- cadence-aware, using each series' own max_age_days.
# ---------------------------------------------------------------------------
def check_staleness(conn, series: registry.Series, df) -> int:
    if df is None or df.empty:
        return 0
    last = pd.Timestamp(df.iloc[-1]["date"])
    age = (pd.Timestamp.now().normalize() - last.normalize()).days
    if age <= series.max_age_days:
        return 0
    return int(store.raise_flag(
        conn, series.series_id, last.strftime("%Y-%m-%d"), "stale",
        f"{age}d since the last observation, threshold {series.max_age_days}d "
        f"for a {series.cadence} series"))


# ---------------------------------------------------------------------------
# Gaps -- business-day-aware for daily series, calendar-aware for the rest.
# ---------------------------------------------------------------------------
def check_gaps(conn, series: registry.Series, df) -> int:
    periodicity = series.periodicity
    if periodicity == "irregular" or df is None or len(df) < 2:
        # A policy rate genuinely has no cadence: BIS stops emitting
        # observations between decisions, so every quiet stretch would flag.
        return 0

    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=GAP_WINDOW_DAYS)
    dates = pd.to_datetime(df["date"])
    recent = dates[dates >= cutoff]
    if len(recent) < 2:
        return 0

    raised = 0
    if periodicity == "weekly":
        for previous, current in zip(recent[:-1], recent[1:]):
            span = (current - previous).days
            if span > MAX_WEEK_GAP_DAYS:
                raised += int(store.raise_flag(
                    conn, series.series_id, current.strftime("%Y-%m-%d"), "gap",
                    f"{span - 7} days beyond the expected weekly step between "
                    f"{previous:%Y-%m-%d} and {current:%Y-%m-%d} "
                    f"(~{span // 7 - 1} week(s) with no observation)"))
    else:
        step = {"monthly": 1, "quarterly": 3, "annual": 12}[periodicity]
        periods = recent.dt.year * 12 + recent.dt.month
        for (prev_p, prev_d), (cur_p, cur_d) in zip(
                zip(periods[:-1], recent[:-1]), zip(periods[1:], recent[1:])):
            missed = (cur_p - prev_p) // step - 1
            if missed >= 1:
                raised += int(store.raise_flag(
                    conn, series.series_id, cur_d.strftime("%Y-%m-%d"), "gap",
                    f"{missed} expected {periodicity} period(s) missing between "
                    f"{prev_d:%Y-%m-%d} and {cur_d:%Y-%m-%d}"))
    return raised


# ---------------------------------------------------------------------------
# Outliers -- self-calibrating against the series' own change distribution.
# ---------------------------------------------------------------------------
def check_outliers(conn, series: registry.Series, df) -> int:
    """
    Flag a value whose step from the previous observation is wildly out of
    scale for this series' own recent behaviour.

    Two things make the threshold self-calibrating rather than hand-tuned per
    series, and both are needed:

      - **Relative changes for anything strictly positive.** A price index is
        not stationary in level, so absolute point-changes are measured on a
        scale that no longer exists. Percent changes are stationary enough to
        calibrate against. Rates, spreads and premia can sit at or below zero,
        where a percent change is meaningless or explosive, so those keep
        absolute changes -- they are already in comparable units (pp).
      - **A trailing calibration window.** Even in percent terms, volatility
        regimes shift; scaling against the last few years is what makes a
        threshold mean the same thing in 1974 and 2026.
    """
    if df is None or len(df) < OUTLIER_MIN_OBS:
        return 0
    frame = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    relative = bool((frame["value"] > 0).all())
    changes = frame["value"].pct_change() if relative else frame["value"].diff()

    scale_of = changes.tail(OUTLIER_CALIBRATION_OBS)
    median = float(scale_of.median(skipna=True))
    mad = float((scale_of - median).abs().median(skipna=True))
    if not np.isfinite(mad) or mad <= 0:
        return 0  # a series that barely moves has no scale to judge against

    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=OUTLIER_WINDOW_DAYS)
    z = MAD_TO_SIGMA * (changes - median) / mad
    recent = frame[(pd.to_datetime(frame["date"]) >= cutoff) & (z.abs() > OUTLIER_Z)]
    units = "%" if relative else "pp"
    raised = 0
    for i, row in recent.iterrows():
        step = changes.loc[i] * (100.0 if relative else 1.0)
        raised += int(store.raise_flag(
            conn, series.series_id, pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
            "outlier",
            f"value {row['value']:.6g} moved {step:+.4g}{units} from the previous "
            f"observation; modified z={z.loc[i]:+.1f} against this series' own last "
            f"{min(len(scale_of), OUTLIER_CALIBRATION_OBS)} changes "
            f"(threshold {OUTLIER_Z})"))
    return raised


# ---------------------------------------------------------------------------
# Curve consistency -- one snapshot of one curve has to hang together.
# ---------------------------------------------------------------------------
def check_curve_consistency(conn, series: list[registry.Series], hist: dict) -> int:
    """
    Within one date's yield curve, flag a tenor that sits an implausible
    distance from its curve-mates. Real curve shapes, inversions included, stay
    well inside MAX_CURVE_SPREAD_PP; a parsing slip does not.
    """
    families: dict[str, list[str]] = {}
    for s in series:
        if s.series_id.startswith(("curve.", "real_yield.")):
            prefix, region, _tenor = s.series_id.split(".", 2)
            families.setdefault(f"{prefix}.{region}", []).append(s.series_id)

    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=CURVE_WINDOW_DAYS)
    raised = 0
    for family, ids in families.items():
        frames = {sid: hist[sid] for sid in ids if hist.get(sid) is not None}
        if len(frames) < 3:
            continue  # a two-point "curve" has no mates to be inconsistent with
        wide = pd.concat(
            [f.set_index("date")["value"].rename(sid) for sid, f in frames.items()],
            axis=1).dropna(how="any")
        wide = wide[wide.index >= cutoff]
        for obs_date, row in wide.iterrows():
            if float(row.max() - row.min()) <= MAX_CURVE_SPREAD_PP:
                continue
            median = float(row.median())
            worst = (row - median).abs().idxmax()
            raised += int(store.raise_flag(
                conn, worst, pd.Timestamp(obs_date).strftime("%Y-%m-%d"),
                "curve_inconsistency",
                f"{worst}={row[worst]:.4g} sits {abs(row[worst] - median):.4g}pp from "
                f"the {family} curve median ({median:.4g}); curve spans "
                f"{float(row.max() - row.min()):.4g}pp, threshold {MAX_CURVE_SPREAD_PP}pp"))
    return raised


# ---------------------------------------------------------------------------
# Completeness -- the running answer to "how complete is this, really".
# ---------------------------------------------------------------------------
def completeness(conn, series: list[registry.Series], hist: dict) -> dict:
    """
    Counted against the full `series_catalog`, so a series that has never
    returned anything is visible as missing rather than simply absent.
    """
    fresh = stale = missing = 0
    detail = {}
    gapped = {r[0] for r in conn.execute(
        "SELECT DISTINCT series_id FROM data_quality_flags "
        "WHERE resolved = 0 AND flag_type = 'gap'")}
    now = pd.Timestamp.now().normalize()
    for s in series:
        df = hist.get(s.series_id)
        if df is None or df.empty:
            missing += 1
            detail[s.series_id] = {"state": "missing", "as_of": None, "n": 0}
            continue
        last = pd.Timestamp(df.iloc[-1]["date"])
        age = (now - last.normalize()).days
        state = "stale" if age > s.max_age_days else "fresh"
        fresh += state == "fresh"
        stale += state == "stale"
        detail[s.series_id] = {
            "state": state, "as_of": last.strftime("%Y-%m-%d"), "n": int(len(df)),
            "since": pd.Timestamp(df.iloc[0]["date"]).strftime("%Y-%m-%d"),
            "age_days": int(age), "max_age_days": s.max_age_days,
            "gapped": s.series_id in gapped,
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "series": len(series), "fresh": fresh, "stale": stale, "missing": missing,
        "gapped": len(gapped & set(detail)),
        "observations": store.observation_count(conn),
        "series_detail": detail,
    }
