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

from typing import NamedTuple

from db import registry, store

logger = logging.getLogger("markets_dashboard.db.quality")

# How far back each check looks. See the module docstring for why these exist.
GAP_WINDOW_DAYS = 730       # two years of cadence gaps
OUTLIER_WINDOW_DAYS = 30    # only values that arrived recently can still be wrong
CURVE_WINDOW_DAYS = 30


def outlier_window_days(series: registry.Series) -> int:
    """
    How far back the outlier check looks, in this series' own terms.

    A flat 30 days is right for weekly storage and silently useless for
    anything slower: a quarterly observation is dated to the first day of the
    quarter it describes and published two months after it ends, so the newest
    GDP print is routinely 160 days old and could never enter a 30-day window
    at all. The check was not lenient on quarterly series, it was unreachable
    for them -- a level break of any size was invisible.

    One publication interval plus the usual slack puts the newest observation
    of every cadence inside the window: 230 days for quarterly, 760 for annual.

    The test is `store_weekly`, not the staleness threshold. A policy rate is
    allowed to be 150 days old before it counts as stale -- a rate legitimately
    sits unchanged for months -- but it is STORED weekly like a price, so its
    observations are 7 days apart and 30 days already covers several of them.
    What the window has to span is the gap between stored observations, which
    is what the grain tells you and the staleness threshold does not.
    """
    if series.store_weekly:
        return OUTLIER_WINDOW_DAYS
    return series.max_age_days + OUTLIER_WINDOW_DAYS

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
# Damodaran fraction-vs-percent mix-up SPEC.md's endpoint appendix records), not
# genuine volatility. A 2008-scale weekly equity move lands near 8; a
# factor-of-ten unit error lands in the hundreds.
OUTLIER_Z = 12.0
# 0.6745 is the 75th percentile of the standard normal: it rescales MAD so the
# threshold is readable on the same scale as an ordinary z-score.
MAD_TO_SIGMA = 0.6745

# A revision this large, applied uniformly to consecutive observations, is a
# rebasing rather than a restatement of the underlying estimate. Sits above the
# genuine quarter-specific GDP revisions seen in the store (max +0.122%) and
# below the chain-link rescalings that caused the problem (+0.548%, +0.700%).
BASIS_BREAK_PCT = 0.25

# The two tests above are RELATIVE, which is the right scale for a level and
# the wrong one for a series that is already a rate in percentage points: a
# routine 0.1pp revision to a 3.3% inflation print is -3.03% in ratio terms and
# sails past BASIS_BREAK_PCT. That is exactly what happened to cpi.EZ on
# 2026-09-19, when the euro area's August HICP went 3.3 -> 3.2 and raised a
# flag for an ordinary revision of a single print.
#
# So a rate series is judged on two other tests, either of which is enough:
#
#   1. MAGNITUDE, in percentage points rather than as a ratio.
#   2. SHARE of history restated. This one is load-bearing, because magnitude
#      alone cannot separate the only two rate-series events on record -- both
#      are about 0.1pp:
#
#        cpi.DE 2026-09-13   299 restated,  56 untouched   84%   REAL (Eurostat
#                                                                changed dataflow
#                                                                and ECOICOP version)
#        cpi.EZ 2026-09-19     1 restated, 355 untouched  0.3%   ordinary revision
#
#      A methodology or base change restates a large block and leaves the rest;
#      an ordinary revision touches the newest print. The share is what tells
#      them apart, so dropping this test would silence the real one.
RATE_BASIS_BREAK_PP = 0.5
RATE_BASIS_BREAK_SHARE = 0.5

# A real yield curve, including any inversion ever printed, spans well under
# this between its shortest and longest tenor. Catches a stray 50.0 where 5.0
# was meant without touching a genuine curve shape.
MAX_CURVE_SPREAD_PP = 10.0


class Findings(NamedTuple):
    """
    What one check concluded about one series.

    `raised` is how many flags this run newly opened -- what the run log
    reports. `found` is every observation date the condition is currently true
    for, whether or not a flag already existed. The two differ, and resolution
    needs the second: a flag re-detected today must stay open even though it
    raised nothing, and an open flag the check did NOT find is a condition that
    has gone away.

    `evaluated` and `since` are what stop resolution from closing a finding the
    check never actually looked at:

      - A check that bailed out -- no data, too few observations to calibrate a
        scale, a periodicity it does not judge -- returns `evaluated=False`,
        and nothing of its type is closed. Silence is not evidence.
      - A windowed check returns the oldest date it examined in `since`, so a
        gap that has aged past GAP_WINDOW_DAYS keeps its flag instead of being
        declared fixed by a check that simply stopped looking at it.
      - `since=None` with `evaluated=True` means the whole series was examined,
        so every open flag of that type is fair game.
    """
    raised: int = 0
    found: frozenset = frozenset()
    evaluated: bool = False
    since: str | None = None


NOT_EVALUATED = Findings()


def _reconcile(conn, open_keys, series_id: str, flag_type: str, f: Findings) -> int:
    """Close the open flags of one type whose condition this run did not find."""
    if not f.evaluated:
        return 0
    closed = 0
    for sid, ftype, date in open_keys:
        if sid != series_id or ftype != flag_type or date in f.found:
            continue
        if f.since is not None and date < f.since:
            continue  # older than the window this check examined
        closed += int(store.resolve_flag(conn, sid, date, ftype))
    return closed


def run_all(conn, series: list[registry.Series] | None = None) -> dict:
    """Every check, flags written, and the completeness report returned."""
    series = series if series is not None else registry.all_series()
    raised = {"stale": 0, "gap": 0, "outlier": 0, "basis_break": 0,
              "curve_inconsistency": 0}

    resolved = dict.fromkeys(raised, 0)

    hist = store.read_all_series(conn)
    # Snapshot the open set before anything is raised, so a flag opened by this
    # very run is never a candidate for closure by it.
    open_keys = store.open_flag_keys(conn)

    for s in series:
        df = hist.get(s.series_id)
        for kind, findings in (("stale", check_staleness(conn, s, df)),
                               ("gap", check_gaps(conn, s, df)),
                               ("outlier", check_outliers(conn, s, df)),
                               ("basis_break", check_basis_break(conn, s))):
            raised[kind] += findings.raised
            resolved[kind] += _reconcile(conn, open_keys, s.series_id, kind, findings)

    curve = check_curve_consistency(conn, series, hist)
    for series_id, findings in curve.items():
        raised["curve_inconsistency"] += findings.raised
        resolved["curve_inconsistency"] += _reconcile(
            conn, open_keys, series_id, "curve_inconsistency", findings)

    # Flags against series the registry no longer knows about. A series id
    # disappears when a source switch retires it -- cpi.US lost its stored YoY
    # leg on 2026-09-13 when the US moved to FRED, which publishes the index
    # only and leaves the rate to be derived. No check will ever run against
    # that id again, so its open flags could never close on their own, and a
    # flag that cannot close is precisely the permanently-red indicator this
    # module exists to avoid. This is NOT the "a check did not run, so close
    # nothing" case that tests/test_flag_resolution.py guards: there is no
    # check to run, because there is no series.
    live_ids = {s.series_id for s in series}
    for series_id, kind, obs_date in sorted(open_keys):
        if series_id in live_ids:
            continue
        store.resolve_flag(conn, series_id, obs_date, kind)
        resolved[kind] = resolved.get(kind, 0) + 1
        logger.info("Resolved %s flag on %s: the series is no longer in the "
                    "registry", kind, series_id)
    conn.commit()

    report = completeness(conn, series, hist)
    report["flags_raised_this_run"] = {k: v for k, v in raised.items() if v}
    report["flags_resolved_this_run"] = {k: v for k, v in resolved.items() if v}
    report["open_flags"] = store.open_flag_tally(conn)
    logger.info("Quality: %d fresh, %d stale, %d missing of %d series; "
                "flags raised this run: %s; resolved: %s; open flags: %s",
                report["fresh"], report["stale"], report["missing"], report["series"],
                report["flags_raised_this_run"] or "none",
                report["flags_resolved_this_run"] or "none",
                report["open_flags"] or "none")
    return report


# ---------------------------------------------------------------------------
# Staleness -- cadence-aware, using each series' own max_age_days.
# ---------------------------------------------------------------------------
def check_staleness(conn, series: registry.Series, df) -> Findings:
    """
    Staleness is a statement about the series as a whole, not about one
    observation, so it is examined without a date window: `since=None`. That
    also closes the flag when a series goes stale, then catches up on a LATER
    date -- the old flag names a date the series has moved past, and only the
    current one can still be true.
    """
    if df is None or df.empty:
        return NOT_EVALUATED  # nothing arrived, so nothing is proven either way
    last = pd.Timestamp(df.iloc[-1]["date"])
    age = (pd.Timestamp.now().normalize() - last.normalize()).days
    if age <= series.max_age_days:
        return Findings(evaluated=True)
    date = last.strftime("%Y-%m-%d")
    raised = int(store.raise_flag(
        conn, series.series_id, date, "stale",
        f"{age}d since the last observation, threshold {series.max_age_days}d "
        f"for a {series.cadence} series"))
    return Findings(raised=raised, found=frozenset({date}), evaluated=True)


# ---------------------------------------------------------------------------
# Gaps -- business-day-aware for daily series, calendar-aware for the rest.
# ---------------------------------------------------------------------------
def check_gaps(conn, series: registry.Series, df) -> Findings:
    periodicity = series.periodicity
    if periodicity == "irregular" or df is None or len(df) < 2:
        # A policy rate genuinely has no cadence: BIS stops emitting
        # observations between decisions, so every quiet stretch would flag.
        return NOT_EVALUATED

    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=GAP_WINDOW_DAYS)
    since = cutoff.strftime("%Y-%m-%d")
    dates = pd.to_datetime(df["date"])
    recent = dates[dates >= cutoff]
    if len(recent) < 2:
        return NOT_EVALUATED

    found = set()
    raised = 0
    if periodicity == "weekly":
        for previous, current in zip(recent[:-1], recent[1:]):
            span = (current - previous).days
            if span > MAX_WEEK_GAP_DAYS:
                found.add(current.strftime("%Y-%m-%d"))
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
                found.add(cur_d.strftime("%Y-%m-%d"))
                raised += int(store.raise_flag(
                    conn, series.series_id, cur_d.strftime("%Y-%m-%d"), "gap",
                    f"{missed} expected {periodicity} period(s) missing between "
                    f"{prev_d:%Y-%m-%d} and {cur_d:%Y-%m-%d}"))
    return Findings(raised=raised, found=frozenset(found), evaluated=True, since=since)


# ---------------------------------------------------------------------------
# Outliers -- self-calibrating against the series' own change distribution.
# ---------------------------------------------------------------------------
def check_outliers(conn, series: registry.Series, df) -> Findings:
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
        return NOT_EVALUATED
    frame = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    relative = bool((frame["value"] > 0).all())
    changes = frame["value"].pct_change() if relative else frame["value"].diff()

    scale_of = changes.tail(OUTLIER_CALIBRATION_OBS)
    median = float(scale_of.median(skipna=True))
    mad = float((scale_of - median).abs().median(skipna=True))
    if not np.isfinite(mad) or mad <= 0:
        # A series that barely moves has no scale to judge against -- and no
        # standing to close a flag raised when it did have one.
        return NOT_EVALUATED

    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=outlier_window_days(series))
    z = MAD_TO_SIGMA * (changes - median) / mad
    recent = frame[(pd.to_datetime(frame["date"]) >= cutoff) & (z.abs() > OUTLIER_Z)]
    units = "%" if relative else "pp"
    found = frozenset(pd.Timestamp(d).strftime("%Y-%m-%d") for d in recent["date"])
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
    return Findings(raised=raised, found=found, evaluated=True,
                    since=cutoff.strftime("%Y-%m-%d"))


# ---------------------------------------------------------------------------
# Basis breaks -- a rebasing picked up on only part of a series.
# ---------------------------------------------------------------------------
def check_basis_break(conn, series: registry.Series) -> Findings:
    """
    Flag a series whose newest vintage restated only its recent tail by what
    looks like a uniform rescaling of the whole thing.

    This is the failure `db/ingest.FULL_REFETCH_CADENCES` exists to prevent,
    and it is worth detecting independently because it is invisible everywhere
    else. When a source re-chain-links a level series, every point moves by
    essentially the same factor. If the request window only reached the last
    point or two, only those are restated, and `latest_observations` then
    resolves a history that is part old base and part new -- a level series
    with a step in it that no check on levels would call odd, because each half
    is perfectly well behaved. The damage lands one layer downstream, in a
    growth rate computed across the seam.

    The tell is the shape of the revision, not its size: a genuine national-
    accounts revision moves consecutive quarters by different amounts, while a
    rebasing moves them by the same one. So the check asks two questions --
    does the newest vintage stop short of the start of history, and is the
    median rescaling on the points it did reach bigger than a real revision
    plausibly is.

    Calibrated against what the store held on 2026-09-08: it fires on CH
    (+0.700% / +0.711%, the two ratios agreeing to four decimals) and EZ
    (+0.548%), and stays silent on the same day's genuine revisions to DE
    (+0.019% / +0.122%), JP (+0.029% / +0.111%) and NO (-0.027% / -0.030%).

    All of that describes a LEVEL. A series that is already a rate takes a
    different pair of tests -- percentage points, and the share of history
    restated -- because a ratio is the wrong scale when the denominator is a
    2-3% inflation print. See RATE_BASIS_BREAK_PP for the calibration and for
    the two real events it was fitted to. The check still runs on rate series
    and still returns `evaluated=True`: returning NOT_EVALUATED instead would
    strand any open flag forever, since `_reconcile` closes nothing on a check
    that did not run.
    """
    if not series.revisable:
        return NOT_EVALUATED

    rows = conn.execute(
        "SELECT date, value, vintage_date FROM observations "
        "WHERE series_id = ? ORDER BY date, vintage_date", (series.series_id,)).fetchall()
    if not rows:
        return NOT_EVALUATED  # nothing stored yet says nothing about the basis

    newest_vintage = max(r[2] for r in rows)
    # Dates the newest vintage touched, and what each was restated FROM.
    restated = {}
    original = {}
    for date, value, vintage in rows:
        if vintage == newest_vintage:
            restated[date] = value
        elif date not in original or vintage > original[date][0]:
            original[date] = (vintage, value)

    revised = {d: (restated[d], original[d][1]) for d in restated if d in original}
    # Everything below examines the whole series, so `since` stays None and a
    # break that has been repaired -- by the full re-fetch putting every point
    # on one basis -- closes its own flag on the next run.
    whole = Findings(evaluated=True)
    if not revised:
        return whole  # every restated date is a first print, nothing was rebased

    # Untouched history older than the oldest restated date is what makes this
    # a seam rather than a clean re-statement of the whole series.
    oldest_revised = min(revised)
    untouched = [d for d in original if d < oldest_revised and d not in restated]
    if not untouched:
        return whole

    if series.is_rate:
        # A rate is judged on percentage points and on how much of the history
        # moved, never on a ratio -- see RATE_BASIS_BREAK_PP above for why.
        deltas = [abs(new - old) for new, old in revised.values()]
        median_pp = float(np.median(deltas)) if deltas else 0.0
        share = len(revised) / float(len(revised) + len(untouched))
        by_size = median_pp >= RATE_BASIS_BREAK_PP
        by_share = share >= RATE_BASIS_BREAK_SHARE
        if not (by_size or by_share):
            return whole
        why = (f"a median {median_pp:.3f}pp" if by_size
               else f"a median {median_pp:.3f}pp across {share * 100:.0f}% of its history")
        detail = (
            f"vintage {newest_vintage} restated the {len(revised)} most recent "
            f"observation(s) by {why}, but left {len(untouched)} earlier "
            f"observation(s) back to {min(untouched)} on the previous basis. "
            f"This series is already a rate, so the concern is a methodology or "
            f"index-base change restating part of the history and leaving the "
            f"rest: the two halves are then not the same measure. Re-ingest the "
            f"full history for this series.")
    else:
        ratios = [new / old for new, old in revised.values() if old]
        if not ratios:
            return whole
        median_ratio = float(np.median(ratios))
        if abs(median_ratio - 1.0) * 100.0 < BASIS_BREAK_PCT:
            return whole
        detail = (
            f"vintage {newest_vintage} restated the {len(revised)} most recent "
            f"observation(s) by a median {(median_ratio - 1) * 100:+.3f}%, but left "
            f"{len(untouched)} earlier observation(s) back to {min(untouched)} on the "
            f"previous basis. A uniform rescaling of only part of a series splices two "
            f"bases together, and any growth rate spanning {oldest_revised} reports the "
            f"rebasing as change. Re-ingest the full history for this series.")

    raised = int(store.raise_flag(
        conn, series.series_id, oldest_revised, "basis_break", detail))
    return Findings(raised=raised, found=frozenset({oldest_revised}), evaluated=True)


# ---------------------------------------------------------------------------
# Curve consistency -- one snapshot of one curve has to hang together.
# ---------------------------------------------------------------------------
def check_curve_consistency(conn, series: list[registry.Series], hist: dict) -> dict:
    """
    Within one date's yield curve, flag a tenor that sits an implausible
    distance from its curve-mates. Real curve shapes, inversions included, stay
    well inside MAX_CURVE_SPREAD_PP; a parsing slip does not.

    Returns Findings per series_id rather than a count, because a flag here is
    filed against the OFFENDING TENOR rather than the curve, so resolution has
    to be reckoned per tenor too. Every tenor of a family that was examined
    gets an entry, including the ones that came out clean -- those are exactly
    the ones whose old flags should now close.
    """
    families: dict[str, list[str]] = {}
    for s in series:
        if s.series_id.startswith(("curve.", "real_yield.")):
            prefix, region, _tenor = s.series_id.split(".", 2)
            families.setdefault(f"{prefix}.{region}", []).append(s.series_id)

    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=CURVE_WINDOW_DAYS)
    since = cutoff.strftime("%Y-%m-%d")
    out: dict[str, Findings] = {}
    raised: dict[str, int] = {}
    found: dict[str, set] = {}
    for family, ids in families.items():
        frames = {sid: hist[sid] for sid in ids if hist.get(sid) is not None}
        if len(frames) < 3:
            continue  # a two-point "curve" has no mates to be inconsistent with
        for sid in frames:
            raised.setdefault(sid, 0)
            found.setdefault(sid, set())
        wide = pd.concat(
            [f.set_index("date")["value"].rename(sid) for sid, f in frames.items()],
            axis=1).dropna(how="any")
        wide = wide[wide.index >= cutoff]
        for obs_date, row in wide.iterrows():
            if float(row.max() - row.min()) <= MAX_CURVE_SPREAD_PP:
                continue
            median = float(row.median())
            worst = (row - median).abs().idxmax()
            found[worst].add(pd.Timestamp(obs_date).strftime("%Y-%m-%d"))
            raised[worst] += int(store.raise_flag(
                conn, worst, pd.Timestamp(obs_date).strftime("%Y-%m-%d"),
                "curve_inconsistency",
                f"{worst}={row[worst]:.4g} sits {abs(row[worst] - median):.4g}pp from "
                f"the {family} curve median ({median:.4g}); curve spans "
                f"{float(row.max() - row.min()):.4g}pp, threshold {MAX_CURVE_SPREAD_PP}pp"))
    for sid, n in raised.items():
        out[sid] = Findings(raised=n, found=frozenset(found[sid]),
                            evaluated=True, since=since)
    return out


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
