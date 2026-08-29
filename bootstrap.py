#!/usr/bin/env python3
"""
One-time seed of data/markets.db. NOT part of the daily run.

    python3 bootstrap.py                      # every series, full history
    python3 bootstrap.py --series curve.UK.10Y --series gdp.UK
    python3 bootstrap.py --skip-archives      # everything except the 89MB BoE zips

What "one-time" buys, per DATABASE-PLAN.md: this is the only run that pulls the
Bank of England's deep GLC archives (glcnominalddata.zip ~39MB plus the real
and inflation zips, ~89MB together, 1979 onward). Every run after this reads
only the small current-month workbook. The same applies in spirit to every
other source -- bootstrap asks for everything the source will give, the daily
run asks for what is newer than the watermark.

Re-running is safe but pointless: every row it re-fetches is already stored, so
ON CONFLICT DO NOTHING discards it and nothing changes. Use `--series` to seed
one newly-added series without touching the other 111 (DATABASE-PLAN.md,
"Adding a new series later").
"""
from __future__ import annotations

import argparse
import logging
import sys

from db import catalog, ingest, registry, store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("markets_dashboard.bootstrap")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series", action="append", default=None,
                        help="Backfill only this series_id (repeatable).")
    parser.add_argument("--skip-archives", action="store_true",
                        help="Skip the deep BoE GLC archives; those series seed "
                             "from the current-month workbook instead.")
    parser.add_argument("--db", default=None, help="Database path (default data/markets.db).")
    args = parser.parse_args()

    path = args.db or store.db_path()
    conn = store.connect(path)
    store.init_db(conn)

    rows, report = catalog.build_rows()
    store.upsert_catalog(conn, rows)
    catalog.log_report(report)
    logger.info("series_catalog: %d series registered", len(rows))

    wanted = registry.all_series()
    if args.series:
        known = {s.series_id for s in wanted}
        unknown = [sid for sid in args.series if sid not in known]
        if unknown:
            logger.error("Unknown series_id(s): %s", ", ".join(unknown))
            return 2
        wanted = [s for s in wanted if s.series_id in set(args.series)]

    before = store.observation_count(conn)
    run_id = store.start_run(conn, "bootstrap")

    archived = [s for s in wanted if s.archive_kwargs]
    if args.skip_archives:
        logger.info("Skipping deep archives for %d series", len(archived))
        plain = [s for s in wanted if not s.archive_kwargs]
        results = ingest.ingest_all(conn, run_id, plain, deep=True) if plain else {}
        if archived:
            results.update(ingest.ingest_all(conn, run_id, archived, deep=False))
    else:
        results = ingest.ingest_all(conn, run_id, wanted, deep=True)
        # The BoE archives are cut at the end of the PREVIOUS month -- measured
        # 2026-08-29, they ended 2026-07-31 while the current-month workbook
        # held August. A deep-only bootstrap would therefore seed a curve that
        # is a month stale on day one, so the snapshot pass runs straight after
        # and closes the seam. Everything it re-offers is discarded on conflict.
        if archived:
            logger.info("Closing the archive seam: current-month snapshot for "
                        "%d archive-backed series", len(archived))
            for sid, r in ingest.ingest_all(conn, run_id, archived, deep=False).items():
                if sid in results and not r.failed:
                    results[sid].attached += r.attached
                    results[sid].latest = max(filter(None, (results[sid].latest, r.latest)),
                                              default=None)

    store.finish_run(conn, run_id)
    after = store.observation_count(conn)

    failed = sorted(sid for sid, r in results.items() if r.failed)
    logger.info("Bootstrap complete: %d observations stored (+%d this run) "
                "across %d series", after, after - before, len(results))
    if failed:
        logger.warning("%d series returned nothing: %s", len(failed), ", ".join(failed))
    logger.info("Database: %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
