#!/usr/bin/env python3
"""
Pipeline orchestrator. Three phases, in this order, every run:

    ingest  -> quality -> export -> sync the catalog

  python3 pipeline.py --mode live    # fetch what's new, rebuild the JSON,
                                     # and publish it to the live site
  python3 pipeline.py --mode sample  # same phases against synthetic data,
                                     # for frontend work with no network
  python3 pipeline.py --export-only  # rebuild the JSON from what's stored

A live run PUBLISHES by default: it fast-forwards onto origin/main before
fetching, then commits and pushes the generated artefacts and waits for the
Pages deploy to serve them, so the file on disk and the file on the live site
are never two different things. `--no-publish` stops at the local write.
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
import hashlib
import json
import logging
import re
from pathlib import Path

import publish as publisher
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
    # Sync BEFORE fetching, not after: the Saturday Actions run pushes a newer
    # database, and a local run started behind it either wastes the fetch or
    # collides at push time on a binary file.
    if do_sync and do_publish and not publisher.skip_reason(mode):
        try:
            logger.info("Sync: %s", publisher.sync())
        except publisher.PublishError as exc:
            # Not fatal: the run still produces correct local data. It is the
            # push at the end that will not be able to land, and it says so.
            logger.error("Sync: FAILED — %s", exc)

    path = db_path or (SAMPLE_DB if mode == "sample" else store.db_path())
    conn = store.connect(path)
    store.init_db(conn)

    # series_catalog is refreshed every run so a metadata edit in
    # DATA-CATALOG.csv lands without a separate step. It touches no observations.
    rows, report = catalog.build_rows()
    store.upsert_catalog(conn, rows)
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

        # Write back what the database actually holds, so DATA-CATALOG.csv is
        # a readable mirror of the store rather than a record that can drift
        # away from it. Sample runs are skipped: they would stamp synthetic
        # coverage onto the reviewed catalog.
        if mode != "sample":
            catalog_sync.sync(conn)
    finally:
        store.finish_run(conn, run_id)
        conn.close()

    target = Path(out_path) if out_path else DATA_DIR / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2))
    logger.info("Wrote %s (%.0f KB, mode=%s, db=%s)", target,
                target.stat().st_size / 1024, mode, path)
    stamp_asset_versions()

    # The artefacts are committed files and the live site is a checkout of
    # them, so a run that stops here has produced two different truths. Publish
    # is therefore part of the run, not a step to remember afterwards. It is a
    # no-op for sample runs, inside Actions, and off main -- publish.py decides.
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
    return payload


def stamp_asset_versions() -> None:
    """
    Pin index.html's asset URLs to a content hash.

    GitHub Pages serves both index.html and assets with cache-control
    max-age=600 and the assets were referenced with no version string, so a
    browser could hold a cached app.js while picking up fresh HTML. That pairs
    new markup — a new tab and its empty section — with old JS that has no
    renderer for it, and the panel renders blank with nothing wrong in the
    code. Hashing means the URL only changes when the file does, so this adds
    no churn on runs where the assets are untouched.
    """
    site = ROOT / "site"
    index = site / "index.html"
    if not index.exists():
        return
    html = original = index.read_text()
    for asset in ("app.js", "style.css"):
        path = site / "assets" / asset
        if not path.exists():
            continue
        digest = hashlib.md5(path.read_bytes()).hexdigest()[:10]
        html = re.sub(rf"assets/{re.escape(asset)}(\?v=[0-9a-f]+)?",
                      f"assets/{asset}?v={digest}", html)
    if html != original:
        index.write_text(html)
        logger.info("Stamped asset versions in %s", index.name)


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


if __name__ == "__main__":
    main()
