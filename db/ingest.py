"""
Incremental ingest: ask what we already have, fetch only what might be newer,
attach what is genuinely new.

Per DATABASE-PLAN.md there are exactly two outcomes for every candidate row --
**ignore it** (already stored) or **attach it** (new). There is no third case,
and no UPDATE or DELETE anywhere in this path. `insert_observations`'s
ON CONFLICT DO NOTHING is what makes "ignore" free.

The watermark drives the request, not the insert. A bounded source is asked for
`watermark - OVERLAP_DAYS` onward; an unbounded one hands back its whole small
snapshot either way. Both then go through the identical insert, so correctness
never depends on the source honouring the window.

**Weekly storage.** The dashboard runs on Saturdays and keeps one observation
per completed week -- the last actual close on or before that week's Friday --
for every source that publishes faster than that. `to_weekly` does the
reduction before anything reaches the insert, so the weekly grain is a property
of what is stored, not of how it is later read. Two consequences worth naming:
an incomplete week is never stored (so a mid-week run adds nothing rather than
planting a Wednesday row that Friday would sit beside), and in a week whose
Friday was a holiday the stored row keeps its real date, a Thursday, rather
than being relabelled.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from db import registry, store
from fetch import sources

logger = logging.getLogger("markets_dashboard.db.ingest")

# Re-ask for a couple of weeks before the watermark so a late-arriving
# correction to a recent print is seen, and so a skipped Saturday run is
# backfilled by the next one. Costs nothing: anything unchanged hits
# ON CONFLICT. Must stay >= one week now that storage is weekly.
OVERLAP_DAYS = 14

# Two floats parsed from the same CSV text are bit-identical, so this only has
# to absorb formatting noise (a source switching 2.30 to 2.3000001). Anything
# larger is a real restatement and earns a new vintage.
REVISION_TOLERANCE = 1e-9


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reduce a faster-than-weekly frame to one row per COMPLETED week.

    Each observation is assigned to the Friday that ends its week, and the last
    observation in each bin wins -- so a normal week stores Friday's close, and
    a week whose Friday was a market holiday stores Thursday's, under its own
    real date. Bins whose Friday has not happened yet are dropped, which is
    what keeps a mid-week run from storing a partial week that the Saturday run
    would then have to sit beside.
    """
    if df is None or df.empty:
        return df
    frame = df.dropna(subset=["value"]).sort_values("date")
    dates = pd.to_datetime(frame["date"])
    # Monday(0)->+4, Friday(4)->+0, Saturday(5)->+6 (i.e. next week's Friday).
    week_end = dates + pd.to_timedelta((4 - dates.dt.dayofweek) % 7, unit="D")
    frame = frame.assign(_week_end=week_end.values)
    frame = frame[frame["_week_end"] <= pd.Timestamp.now().normalize()]
    if frame.empty:
        return frame.drop(columns=["_week_end"])
    return (frame.groupby("_week_end", as_index=False, sort=True)
            .tail(1).drop(columns=["_week_end"]).reset_index(drop=True))


@dataclass
class SeriesResult:
    series_id: str
    fetched: int = 0          # rows the source returned
    attached: int = 0         # rows genuinely new to the database
    revisions: int = 0        # of those, restatements of an existing date
    latest: str | None = None  # newest date the source offered
    failed: bool = False

    @property
    def outcome(self) -> str:
        if self.failed:
            return "failed"
        return "ok" if self.fetched else "empty"


def fetch_one(series: registry.Series, start: str | None = None,
              deep: bool = False) -> pd.DataFrame | None:
    """
    Call the registry-named fetcher. Never raises: every fetcher in
    fetch/sources.py returns None on failure, and this preserves that contract
    so one dead source cannot take down a run.
    """
    kwargs = dict(series.archive_kwargs if (deep and series.archive_kwargs)
                  else series.fetch_kwargs)
    if start and series.bounded:
        kwargs["start"] = start
    fn = getattr(sources, series.fetcher, None)
    if fn is None:
        logger.warning("%s: no fetcher named %s", series.series_id, series.fetcher)
        return None
    try:
        return fn(**kwargs)
    except Exception as exc:  # noqa: BLE001 - a fetcher that raises is a bug, not a run-ender
        logger.warning("%s: fetcher %s raised: %s", series.series_id, series.fetcher, exc)
        return None


def rows_to_attach(conn, series: registry.Series, df: pd.DataFrame) -> tuple[list[tuple], int]:
    """
    Turn a fetched frame into (series_id, date, vintage_date, value) tuples.

    For a non-revisable series `vintage_date = date`, so the vintage mechanism
    is present but inert and this is one candidate row per date. For GDP, CPI
    and SLOOS the fetched value is compared against what `latest_observations`
    currently resolves to: unchanged means nothing is offered at all, and a
    genuine restatement is offered as a NEW row stamped with today's vintage.
    The first print is never touched.
    """
    if df is None or df.empty:
        return [], 0

    frame = df.dropna(subset=["value"]).sort_values("date")
    if not series.revisable:
        return [(series.series_id, d, d, float(v))
                for d, v in zip(frame["date"], frame["value"])], 0

    stored = store.stored_values(conn, series.series_id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out, revisions = [], 0
    for d, v in zip(frame["date"], frame["value"]):
        iso = pd.Timestamp(d).strftime("%Y-%m-%d")
        value = float(v)
        previous = stored.get(iso)
        if previous is None:
            out.append((series.series_id, iso, iso, value))
        elif abs(previous - value) > max(REVISION_TOLERANCE, abs(previous) * REVISION_TOLERANCE):
            out.append((series.series_id, iso, today, value))
            revisions += 1
            logger.info("%s: %s restated %.6g -> %.6g, appended as vintage %s",
                        series.series_id, iso, previous, value, today)
        # else: identical to what we hold -> not even offered to the insert
    return out, revisions


def ingest_series(conn, series: registry.Series, run_id: int,
                  watermark: str | None = None, deep: bool = False) -> SeriesResult:
    start = None
    if not deep and watermark and series.bounded:
        start = (pd.Timestamp(watermark) - timedelta(days=OVERLAP_DAYS)).strftime("%Y-%m-%d")

    df = fetch_one(series, start=start, deep=deep)
    result = SeriesResult(series_id=series.series_id)
    if df is None or df.empty:
        result.failed = True
        return result

    if series.store_weekly:
        df = to_weekly(df)
        if df is None or df.empty:
            # Everything the source offered belongs to a week that has not
            # finished yet -- not a failure, just nothing to store today.
            return result

    result.fetched = len(df)
    result.latest = pd.Timestamp(df["date"].max()).strftime("%Y-%m-%d")
    rows, revisions = rows_to_attach(conn, series, df)
    result.attached = store.insert_observations(conn, rows, run_id)
    result.revisions = revisions
    return result


def ingest_all(conn, run_id: int, series: list[registry.Series] | None = None,
               deep: bool = False) -> dict[str, SeriesResult]:
    """
    One pass over every registered series.

    `deep=True` is the bootstrap: no watermark narrowing, and archive-backed
    sources (the BoE GLC zips) read their deep archive instead of the current
    snapshot. The daily run leaves it False.
    """
    series = series if series is not None else registry.all_series()
    marks = store.watermarks(conn)
    results: dict[str, SeriesResult] = {}
    for i, s in enumerate(series, 1):
        result = ingest_series(conn, s, run_id, marks.get(s.series_id), deep=deep)
        results[s.series_id] = result
        logger.info("[%3d/%d] %-28s %-7s fetched=%-6d attached=%-6d latest=%s",
                    i, len(series), s.series_id, result.outcome,
                    result.fetched, result.attached, result.latest or "-")
    attached = sum(r.attached for r in results.values())
    failed = [sid for sid, r in results.items() if r.failed]
    revised = sum(r.revisions for r in results.values())
    logger.info("Ingest: %d rows attached across %d series (%d revisions); %d failed%s",
                attached, len(results), revised, len(failed),
                (": " + ", ".join(failed)) if failed else "")
    return results
