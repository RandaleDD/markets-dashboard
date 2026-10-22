#!/usr/bin/env python3
"""
Pipeline orchestrator. Three phases, in this order, every run:

    ingest  -> quality -> export -> sync the catalog

  python3 pipeline.py --mode live    # fetch what's new, rebuild the JSON,
                                     # and publish it to the live site
  python3 pipeline.py --mode sample  # same phases against synthetic data,
                                     # for frontend work with no network
  python3 pipeline.py --export-only  # rebuild the JSON from what's stored

A live run PUBLISHES by default: before fetching it fast-forwards main and
downloads the published database from the `data` branch if it is newer;
afterwards it replaces that branch with this run's artefacts and waits for the
Pages deploy to serve them (see publish.py). `--no-publish` stops at the local
write.
Sample runs never publish, whatever the flags say -- see publish.py.

The database is the source of truth (see SPEC.md). Ingest attaches
only what is genuinely new to `data/markets.db` and never rewrites anything;
export then rebuilds `site/data/latest.json` from what the database currently
holds, over the FULL accumulated history, regardless of how much of it arrived
today. That split is what makes updates cheap without making the derived
metrics shallow -- the old pipeline re-fetched every series' whole history on
every run and still had no history older than the run itself.

Cadence: the run is weekly, on Saturday, and stores each completed week's
Friday close. `--mode live` on any other day is harmless -- it just finds the
current week incomplete and attaches nothing for the weekly series.

Sample mode writes to its OWN database file so synthetic numbers can never
reach the real one, and goes through the identical three phases so the
no-network path cannot silently drift from the live one.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import publish as publisher
from stamp_assets import stamp_asset_versions
from db import catalog, catalog_sync, export, ingest, quality, registry, store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("markets_dashboard.pipeline")

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "site" / "data"
SAMPLE_DB = ROOT / "data" / "markets-sample.db"


def _seed_sample(conn, run_id: int) -> None:
    """Insert synthetic observations through the real insert path."""
    from db import sample

    frames = sample.generate()
    total = 0
    for series in registry.all_series():
        df = frames.get(series.series_id)
        if df is None:
            continue
        if series.store_weekly:
            df = ingest.to_weekly(df)
        rows, _ = ingest.rows_to_attach(conn, series, df)
        total += store.insert_observations(conn, rows, run_id)
    logger.info("Sample: %d synthetic observations attached", total)


def run(mode: str, export_only: bool = False, db_path: str | None = None,
        out_path: str | None = None, do_publish: bool = True,
        do_sync: bool = True, verify_deploy: bool = True) -> dict:
    # Sync BEFORE fetching, not after: the Saturday Actions run publishes a
    # newer database, and a run started behind it would be refused at publish.
    # On a fresh checkout (and every Actions run) this is what downloads the
    # database in the first place.
    problems = []
    if do_sync and do_publish and not publisher.skip_reason(mode):
        try:
            logger.info("Sync: %s", publisher.sync())
        except publisher.PublishError as exc:
            # Not fatal: the run still produces correct local data. It is the
            # publish at the end that will not be able to land, and it says so.
            logger.error("Sync: FAILED — %s", exc)
            problems.append("sync")

    path = db_path or (SAMPLE_DB if mode == "sample" else store.db_path())
    if mode == "live" and not export_only and not Path(path).exists():
        # A live run on an empty store would quietly re-bootstrap ~100 MB of
        # archives into a NEW history and then publish it over the real one.
        raise SystemExit(f"{path} is missing and could not be downloaded from the "
                         f"'{publisher.DATA_BRANCH}' branch. Seed it with bootstrap.py "
                         f"only if the published store is truly gone.")
    conn = store.connect(path)
    store.init_db(conn)

    # series_catalog is refreshed every run so a metadata edit in
    # DATA-CATALOG.csv lands without a separate step. It touches no observations.
    rows, report = catalog.build_rows()
    store.upsert_catalog(conn, rows)
    store.retire_unregistered(conn, {r["series_id"] for r in rows})
    if report["catalog_missing_fetcher"]:
        catalog.log_report(report)

    run_id = store.start_run(conn, mode)
    try:
        if not export_only:
            if mode == "sample":
                _seed_sample(conn, run_id)
            else:
                ingest.ingest_all(conn, run_id)

        dq = quality.run_all(conn)
        payload = export.build_payload(conn, is_sample=(mode == "sample"))
        # The completeness report rides along with the JSON so "how complete
        # are we" is answerable from the artefact, not only from the run log.
        payload["data_quality"] = {
            k: v for k, v in dq.items() if k != "series_detail"}
        payload["data_quality"]["open_flag_examples"] = store.open_flags(conn, limit=25)

        # Write what the database actually holds to DATA-COVERAGE.csv, beside
        # (never into) the reviewed DATA-CATALOG.csv. Sample runs are skipped:
        # their coverage is synthetic.
        if mode != "sample":
            catalog_sync.sync(conn)
    finally:
        store.finish_run(conn, run_id)
        conn.close()

    target = Path(out_path) if out_path else DATA_DIR / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, separators=(",", ":")))
    logger.info("Wrote %s (%.0f KB, mode=%s, db=%s)", target,
                target.stat().st_size / 1024, mode, path)
    stamp_asset_versions()

    # A run that stops here leaves the dashboard on screen and the one at the
    # URL disagreeing, so publish is part of the run, not a step to remember.
    # It is a no-op for sample runs and off main -- publish.py decides.
    # `out_path` means the payload went somewhere other than the site, so
    # there is nothing on the site to publish.
    if do_publish and out_path is None:
        try:
            publisher.publish(payload["generated_at"], mode=mode,
                              verify_deploy=verify_deploy)
        except publisher.PublishError as exc:
            # The data is safely on disk and in the database; only the push
            # failed. Say so loudly, but do not throw away a good run.
            logger.error("Publish: FAILED — %s", exc)
            problems.append("publish")
    payload_problems[:] = problems
    return payload


# What went wrong in the last run(), so main() can exit non-zero: the weekly
# workflow must not deploy a payload whose data never reached the data branch.
payload_problems: list[str] = []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["live", "sample"], default="sample")
    parser.add_argument("--export-only", action="store_true",
                        help="Skip fetching; rebuild latest.json from the database.")
    parser.add_argument("--db", default=None, help="Database path override.")
    parser.add_argument("--no-publish", action="store_true",
                        help="Write locally only; do not push to the live site.")
    parser.add_argument("--no-sync", action="store_true",
                        help="Skip the fast-forward onto origin/main first.")
    parser.add_argument("--no-verify", action="store_true",
                        help="Push without waiting for the Pages deploy to land.")
    args = parser.parse_args()
    run(args.mode, export_only=args.export_only, db_path=args.db,
        do_publish=not args.no_publish, do_sync=not args.no_sync,
        verify_deploy=not args.no_verify)
    if payload_problems:
        raise SystemExit(f"Finished locally, but {' and '.join(payload_problems)} failed "
                         f"(see the log above).")


if __name__ == "__main__":
    main()
