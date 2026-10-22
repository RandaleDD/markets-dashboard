#!/usr/bin/env python3
"""
Pin site/index.html's asset URLs to a content hash. Standard library only, so
the Pages deploy can run it with no install: `python3 stamp_assets.py`.

Runs after every pipeline write and again at deploy time, so the stamp the
site is served with is always the one for the app.js it is served with, even
when a code commit forgot to include the updated index.html.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

logger = logging.getLogger("markets_dashboard.stamp")

ROOT = Path(__file__).parent


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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stamp_asset_versions()
