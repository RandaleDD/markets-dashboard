#!/usr/bin/env python3
"""
Publish what the pipeline just produced, and prove it landed.

The database and `site/data/latest.json` are generated artefacts that are
COMMITTED -- the checkout is how the Actions runner gets yesterday's data, and
`site/` is what GitHub Pages serves. So "the local file" and "the published
file" are the same file at two points in time, and they drift apart the moment
a run finishes without a push. That drift is silent: the local dashboard looks
refreshed, the live one is whatever was last pushed.

This module closes that gap. `publish()` commits the generated artefacts and
pushes; the push matches `pages.yml`'s `paths: site/**` filter, which is what
actually redeploys the site (pushing to main is NOT enough on its own if the
change misses that filter). `verify()` then polls the live URL until the
published payload carries the same `generated_at` as the one on disk, because
a push that started a deploy is not the same thing as a deploy that finished.

Four things it deliberately refuses to do:

  * publish sample data. `--mode sample` numbers are synthetic; the separate
    sample database protects the store, nothing protects the JSON, and this is
    the last gate before synthetic numbers reach the live site.
  * run inside GitHub Actions. `weekly.yml` has its own commit-and-push step
    with the bot identity, and two of them would race.
  * commit anything that is not a generated artefact. Never `git add -A`: a
    half-finished edit to `app.js` is not data, and it is not published by a
    data refresh.
  * resolve a conflict on the generated files. If the remote moved underneath
    the run, the fix is to re-run the pipeline on top of it -- see CLAUDE.md.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

import requests

logger = logging.getLogger("markets_dashboard.publish")

ROOT = Path(__file__).parent
LIVE_URL = "https://randaledd.github.io/markets-dashboard/data/latest.json"
SITE_URL = "https://randaledd.github.io/markets-dashboard/"
BRANCH = "main"

# The generated artefacts, and nothing else. `site/index.html` is here only
# because `pipeline.stamp_asset_versions()` rewrites its `?v=` query strings;
# it is staged only when that stamp is the ONLY thing that changed in it.
GENERATED = ("site/data/latest.json", "data/markets.db", "data/DATA-CATALOG.csv")
STAMPED = "site/index.html"

# A deploy is two GitHub Actions steps on a shared queue; measured at about a
# minute, and the concurrency group can make it wait behind another one.
VERIFY_TIMEOUT_S = 300
VERIFY_INTERVAL_S = 10


class PublishError(RuntimeError):
    """Something went wrong that a human has to look at."""


def _git(root: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run git without ever opening an interactive credential prompt: this runs
    unattended from a double-clicked script, where a prompt is a hang."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, env=env, timeout=timeout)


def _out(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "").strip()


def is_git_repo(root: Path = ROOT) -> bool:
    return _git(root, "rev-parse", "--git-dir").returncode == 0


def current_branch(root: Path = ROOT) -> str:
    return _out(_git(root, "rev-parse", "--abbrev-ref", "HEAD"))


def skip_reason(mode: str, root: Path = ROOT) -> str | None:
    """Why this run must not publish, or None if it may. Checked before any
    work, so the caller can say so once rather than failing late."""
    if mode != "live":
        return "sample data is never published"
    if os.environ.get("GITHUB_ACTIONS"):
        return "running in GitHub Actions, where weekly.yml does the commit"
    if not is_git_repo(root):
        return "not a git checkout"
    branch = current_branch(root)
    if branch != BRANCH:
        return (f"on branch '{branch}', not '{BRANCH}' — Pages only ever "
                f"deploys '{BRANCH}'")
    return None


def _only_asset_stamp_changed(root: Path) -> bool:
    """True when the only edit to index.html is the asset version stamp.

    Anything else in that file is hand-written markup, which is a code change
    and gets committed deliberately, not swept into a data refresh.
    """
    diff = _out(_git(root, "diff", "HEAD", "--unified=0", "--", STAMPED))
    if not diff:
        return False
    changed = [ln for ln in diff.splitlines()
               if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    return bool(changed) and all(re.search(r"assets/[\w.]+\?v=[0-9a-f]+", ln)
                                 for ln in changed)


def _dirty(root: Path, path: str) -> bool:
    return bool(_out(_git(root, "status", "--porcelain", "--", path)))


def stage(root: Path = ROOT) -> list[str]:
    """Stage the generated artefacts that actually changed. Returns their paths."""
    staged = []
    for rel in GENERATED:
        if (root / rel).exists() and _dirty(root, rel):
            _git(root, "add", "--", rel)
            staged.append(rel)
    if _dirty(root, STAMPED) and _only_asset_stamp_changed(root):
        _git(root, "add", "--", STAMPED)
        staged.append(STAMPED)
    return staged


def unpublished_changes(root: Path = ROOT) -> list[str]:
    """Tracked files changed but NOT published by this module -- code, mostly.
    Reported so a refresh never leaves the impression it pushed those too."""
    lines = _out(_git(root, "status", "--porcelain", "--untracked-files=no")).splitlines()
    paths = [ln[3:].strip() for ln in lines if ln]
    return sorted(p for p in paths if p not in GENERATED and p != STAMPED)


def sync(root: Path = ROOT) -> str:
    """Fast-forward onto the remote BEFORE fetching data.

    The Saturday Actions run pushes a newer database; starting a local run
    behind it means either a wasted run or a conflict on a binary file at push
    time. Fast-forward only -- if local and remote have genuinely diverged,
    that is a real question and not one to answer automatically.
    """
    if not is_git_repo(root) or current_branch(root) != BRANCH:
        return "skipped"
    if _git(root, "fetch", "--quiet", "origin", BRANCH, timeout=120).returncode != 0:
        return "offline"
    behind = _out(_git(root, "rev-list", "--count", f"HEAD..origin/{BRANCH}"))
    if behind in ("", "0"):
        return "already current"
    # --autostash because a half-published previous run leaves the generated
    # files modified, and `git checkout -- data/markets.db` is not an option:
    # uncommitted observations are real history, and the sources that only
    # serve today's value (the Swiss curve) cannot be re-fetched for a past
    # week. Stash, fast-forward, put them back.
    pull = _git(root, "pull", "--ff-only", "--autostash", "--quiet", "origin", BRANCH)
    if pull.returncode != 0:
        raise PublishError(
            f"could not fast-forward onto origin/{BRANCH} ({behind} commit(s) "
            f"behind): {(pull.stderr or '').strip()}. Nothing was changed. If the "
            "two have genuinely diverged, sort that out before publishing — do "
            "not hand-merge the generated files.")
    return f"fast-forwarded {behind} commit(s)"


def _push(root: Path) -> subprocess.CompletedProcess:
    return _git(root, "push", "origin", BRANCH, timeout=180)


def publish(generated_at: str, mode: str = "live", root: Path = ROOT,
            verify_deploy: bool = True) -> dict:
    """Commit the generated artefacts, push, and confirm the site caught up."""
    reason = skip_reason(mode, root)
    if reason:
        logger.info("Publish: skipped — %s", reason)
        return {"published": False, "skipped": reason}

    staged = stage(root)
    others = unpublished_changes(root)
    if not staged:
        ahead = _out(_git(root, "rev-list", "--count", f"origin/{BRANCH}..HEAD"))
        if ahead in ("", "0"):
            logger.info("Publish: nothing changed — the live site already has this run")
            result = {"published": False, "skipped": "no change", "others": others}
            if verify_deploy:
                result["verified"] = verify(generated_at)
            return result
        logger.info("Publish: no new data, but %s commit(s) were never pushed", ahead)
    else:
        message = (f"Weekly data refresh {generated_at[:10]} "
                   f"({generated_at[11:16]} UTC, run from Mac)")
        commit = _git(root, "commit", "--quiet", "-m", message)
        if commit.returncode != 0:
            raise PublishError(f"git commit failed: {_out(commit)}{commit.stderr}")
        logger.info("Publish: committed %s", ", ".join(staged))

    push = _push(root)
    if push.returncode != 0:
        stderr = (push.stderr or "").strip()
        if "rejected" in stderr or "fetch first" in stderr:
            raise PublishError(
                "the remote moved while this run was in flight (the Saturday job, "
                "most likely). Re-run `python3 pipeline.py --mode live`: it will "
                "fast-forward first and rebuild on top of the newer database. Do "
                "not merge the generated files by hand.")
        raise PublishError(f"git push failed: {stderr}")
    logger.info("Publish: pushed to origin/%s — Pages is deploying", BRANCH)

    result = {"published": True, "staged": staged, "others": others}
    if others:
        logger.info("Publish: %d other changed file(s) were NOT published (%s)",
                    len(others), ", ".join(others[:4]))
    if verify_deploy:
        result["verified"] = verify(generated_at)
    return result


def live_generated_at(timeout: int = 20) -> str | None:
    """The `generated_at` the live site is currently serving, or None.

    Pages serves with max-age=600, so a bare request can be answered from an
    edge cache that predates the deploy. The query string is what makes this a
    read of the live object rather than of that cache.
    """
    try:
        resp = requests.get(LIVE_URL, params={"cachebust": str(time.time())},
                            headers={"Cache-Control": "no-cache"}, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("generated_at")
    except Exception as exc:  # noqa: BLE001 -- a failed check is never fatal
        logger.debug("Live payload not readable: %s", exc)
        return None


def verify(generated_at: str, timeout_s: int = VERIFY_TIMEOUT_S) -> bool:
    """Poll the live payload until it is the one on disk. A push starts a
    deploy; only this says the deploy finished."""
    deadline = time.time() + timeout_s
    while True:
        live = live_generated_at()
        if live == generated_at:
            logger.info("Publish: live site is serving this run (%s) — %s",
                        generated_at, SITE_URL)
            return True
        if time.time() >= deadline:
            logger.warning(
                "Publish: pushed, but after %ds the live site still serves %s "
                "instead of %s. The deploy may still be queued — check the "
                "Actions tab, then reload %s",
                timeout_s, live or "nothing readable", generated_at, SITE_URL)
            return False
        time.sleep(VERIFY_INTERVAL_S)


def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Publish the generated dashboard artefacts, or check whether "
                    "the live site already matches the local ones.")
    parser.add_argument("--check", action="store_true",
                        help="Compare local and live, change nothing.")
    parser.add_argument("--no-verify", action="store_true",
                        help="Push without waiting for the deploy to land.")
    args = parser.parse_args()

    local_path = ROOT / "site" / "data" / "latest.json"
    payload = json.loads(local_path.read_text())
    local, is_sample = payload.get("generated_at"), payload.get("is_sample")

    if is_sample:
        raise SystemExit("site/data/latest.json holds SAMPLE data — refusing to "
                         "publish it. Re-run: python3 pipeline.py --mode live")

    if args.check:
        live = live_generated_at()
        print(f"local: {local}\nlive:  {live or 'unreadable'}")
        print("congruent" if live == local else "DIFFERENT — the live site is behind")
        raise SystemExit(0 if live == local else 1)

    publish(local, mode="live", verify_deploy=not args.no_verify)


if __name__ == "__main__":
    main()
