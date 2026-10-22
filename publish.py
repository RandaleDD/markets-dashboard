#!/usr/bin/env python3
"""
Publish what the pipeline just produced, and prove it landed.

The generated artefacts -- the database, `latest.json` and the coverage file --
are NOT committed to main. They live on a `data` branch that always holds
exactly ONE commit with no parent, replaced on every publish:

    markets.db.gz       the store, gzipped (deterministic: mtime=0)
    latest.json         what the site renders
    DATA-COVERAGE.csv   what the store holds, per series
    .github/workflows/pages.yml   a copy of main's, so a push here deploys

Main is code and reviewed prose only. Nothing online keeps old versions of the
data, and nothing needs to: `observations` is append-only, so the current
database already contains every value and every revision it has ever seen.
This checkout keeps its own rolling local snapshots in `data/history/`.

Concurrency is the same optimistic rule the old commit-to-main flow had, made
explicit. `refs/markets/data-base` records which `data` commit this checkout's
database was built on, and every push is `--force-with-lease` against it, so a
push is refused if anyone else -- the Saturday Actions run, another clone --
published in between. Nobody's rows are ever overwritten; the loser re-runs.

`sync()` runs BEFORE fetching: it fast-forwards main (code) and brings the
local database up to the published one. It refuses to replace a local
database holding rows that were never published, because a source that only
serves today's value (the Swiss curve's RSS top-up) cannot be re-fetched for a
past week.

The same module runs on the Mac and inside GitHub Actions. A push from the Mac
starts `pages.yml`; a push made with the Actions token cannot start another
workflow, so `weekly.yml` deploys the site itself. `verify()` polls the live
URL until it serves this run's `generated_at` either way.
"""
from __future__ import annotations

import gzip
import hashlib
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests

logger = logging.getLogger("markets_dashboard.publish")

ROOT = Path(__file__).parent
LIVE_URL = "https://randaledd.github.io/markets-dashboard/data/latest.json"
SITE_URL = "https://randaledd.github.io/markets-dashboard/"
BRANCH = "main"
DATA_BRANCH = "data"
BASE_REF = "refs/markets/data-base"

# Published name on the data branch -> local path. The database is gzipped.
DATA_FILES = {
    "markets.db.gz": "data/markets.db",
    "latest.json": "site/data/latest.json",
    "DATA-COVERAGE.csv": "data/DATA-COVERAGE.csv",
}
DB_PATH = DATA_FILES["markets.db.gz"]
PAGES_WORKFLOW = ".github/workflows/pages.yml"
HISTORY_DIR = "data/history"
KEEP_SNAPSHOTS = 8

# A deploy is two GitHub Actions steps on a shared queue; measured at about a
# minute, and the concurrency group can make it wait behind another one.
VERIFY_TIMEOUT_S = 300
VERIFY_INTERVAL_S = 10


class PublishError(RuntimeError):
    """Something went wrong that a human has to look at."""


def _git(root: Path, *args: str, timeout: int = 120, text: bool = True,
         input: str | None = None) -> subprocess.CompletedProcess:
    """Run git without ever opening an interactive credential prompt: this runs
    unattended from a double-clicked script, where a prompt is a hang."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=text, input=input, env=env, timeout=timeout)


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
    if not is_git_repo(root):
        return "not a git checkout"
    branch = current_branch(root)
    if branch != BRANCH:
        return (f"on branch '{branch}', not '{BRANCH}' — only code on '{BRANCH}' "
                f"may produce the published data")
    return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rev(root: Path, ref: str) -> str | None:
    return _out(_git(root, "rev-parse", "--verify", "--quiet", ref)) or None


def _db_sha_of(root: Path, commit: str | None) -> str | None:
    """The database hash a data commit records in its message."""
    if not commit:
        return None
    for line in _out(_git(root, "log", "-1", "--format=%B", commit)).splitlines():
        if line.startswith("db-sha256: "):
            return line.split(": ", 1)[1].strip()
    return None


def _snapshot(root: Path, label: str) -> None:
    """Keep a gzipped copy of the local database; prune to KEEP_SNAPSHOTS."""
    db = root / DB_PATH
    if not db.exists():
        return
    hist = root / HISTORY_DIR
    hist.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:32]
    (hist / f"markets-{safe}.db.gz").write_bytes(gzip.compress(db.read_bytes(), mtime=0))
    for old in sorted(hist.glob("markets-*.db.gz"), key=lambda p: p.stat().st_mtime)[:-KEEP_SNAPSHOTS]:
        old.unlink()


def _remote_data(root: Path) -> tuple[str, str | None]:
    """('ok', sha) / ('missing', None) / ('offline', None) for origin's data branch."""
    proc = _git(root, "ls-remote", "origin", f"refs/heads/{DATA_BRANCH}")
    if proc.returncode != 0:
        return "offline", None
    line = _out(proc)
    return ("ok", line.split()[0]) if line else ("missing", None)


# ---------------------------------------------------------------------------
# sync: before a run
# ---------------------------------------------------------------------------
def sync_code(root: Path = ROOT) -> str:
    """Fast-forward main onto origin. Fast-forward only -- divergence is a real
    question and not one to answer automatically."""
    if not is_git_repo(root) or current_branch(root) != BRANCH:
        return "skipped"
    if _git(root, "fetch", "--quiet", "origin", BRANCH).returncode != 0:
        return "offline"
    behind = _out(_git(root, "rev-list", "--count", f"HEAD..origin/{BRANCH}"))
    if behind in ("", "0"):
        return "code already current"
    pull = _git(root, "pull", "--ff-only", "--autostash", "--quiet", "origin", BRANCH)
    if pull.returncode != 0:
        raise PublishError(
            f"could not fast-forward onto origin/{BRANCH} ({behind} commit(s) behind): "
            f"{(pull.stderr or '').strip()}. Nothing was changed.")
    return f"fast-forwarded {behind} commit(s)"


def sync_data(root: Path = ROOT) -> str:
    """Bring the local database up to the published one, never over unpublished rows."""
    if not is_git_repo(root):
        return "skipped"
    state, remote = _remote_data(root)
    if state != "ok":
        return ("offline" if state == "offline" else
                "no data branch yet — this checkout's database is the only copy")
    if _git(root, "fetch", "--quiet", "origin",
            f"+refs/heads/{DATA_BRANCH}:refs/remotes/origin/{DATA_BRANCH}").returncode != 0:
        return "offline"
    base = _rev(root, BASE_REF)
    local = _sha256(root / DB_PATH)
    if local is not None and local == _db_sha_of(root, remote):
        _git(root, "update-ref", BASE_REF, remote)
        return "data already current"
    if base == remote:
        return "data already current (local rows not yet published)"
    if local is not None and local != _db_sha_of(root, base):
        raise PublishError(
            f"this checkout's database has rows that were never published, and "
            f"origin/{DATA_BRANCH} has moved on since. Neither is replaced. To keep "
            f"the published one, move {DB_PATH} aside and re-run.")

    if local is not None:
        _snapshot(root, f"replaced-{time.strftime('%Y%m%d-%H%M%S')}")
    for published, rel in DATA_FILES.items():
        blob = _git(root, "cat-file", "blob", f"{remote}:{published}", text=False)
        if blob.returncode != 0:
            continue
        data = gzip.decompress(blob.stdout) if published.endswith(".gz") else blob.stdout
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".download")
        tmp.write_bytes(data)
        os.replace(tmp, target)
    _git(root, "update-ref", BASE_REF, remote)
    subject = _out(_git(root, "log", "-1", "--format=%s", remote))
    return f"downloaded the published data ({subject})"


def sync(root: Path = ROOT) -> str:
    return f"{sync_code(root)}; {sync_data(root)}"


# ---------------------------------------------------------------------------
# publish: after a run
# ---------------------------------------------------------------------------
def _data_tree(root: Path) -> str:
    entries = []
    with tempfile.TemporaryDirectory() as tmp:
        for published, rel in sorted(DATA_FILES.items()):
            src = root / rel
            if not src.exists():
                continue
            if published.endswith(".gz"):
                gz = Path(tmp) / published
                gz.write_bytes(gzip.compress(src.read_bytes(), mtime=0))
                src = gz
            sha = _out(_git(root, "hash-object", "-w", str(src)))
            entries.append(f"100644 blob {sha}\t{published}\n")
    # GitHub reads a push-triggered workflow FROM THE PUSHED COMMIT. Without
    # main's pages.yml in this tree, a push to `data` from the Mac would start
    # no deploy at all. It is a copy; main's is the one that is edited.
    workflow = _rev(root, f"HEAD:{PAGES_WORKFLOW}")
    if workflow:
        inner = _out(_git(root, "mktree", input=f"100644 blob {workflow}\tpages.yml\n"))
        outer = _out(_git(root, "mktree", input=f"040000 tree {inner}\tworkflows\n"))
        entries.append(f"040000 tree {outer}\t.github\n")
    return _out(_git(root, "mktree", input="".join(entries)))


def publish(generated_at: str, mode: str = "live", root: Path = ROOT,
            verify_deploy: bool = True) -> dict:
    """Replace the data branch with this run's artefacts and confirm the site caught up."""
    reason = skip_reason(mode, root)
    if reason:
        logger.info("Publish: skipped — %s", reason)
        return {"published": False, "skipped": reason}
    if not (root / DB_PATH).exists():
        raise PublishError(f"no {DB_PATH} to publish")

    base = _rev(root, BASE_REF)
    tree = _data_tree(root)
    if base and _rev(root, f"{base}^{{tree}}") == tree:
        logger.info("Publish: nothing changed — the live site already has this run")
        result = {"published": False, "skipped": "no change"}
        if verify_deploy:
            result["verified"] = verify(generated_at)
        return result

    where = "GitHub Actions" if os.environ.get("GITHUB_ACTIONS") else "Mac"
    message = (f"Data {generated_at[:10]} ({generated_at[11:16]} UTC, run from {where})\n\n"
               f"db-sha256: {_sha256(root / DB_PATH)}\n")
    commit = _git(root, "commit-tree", tree, "-m", message)
    if commit.returncode != 0:
        raise PublishError(f"git commit-tree failed: {commit.stderr.strip()}")
    new = _out(commit)

    # The lease: the remote data branch must still be exactly the commit this
    # database was built on (or must not exist yet, for the very first publish).
    lease = f"--force-with-lease=refs/heads/{DATA_BRANCH}:{base or ''}"
    push = _git(root, "push", "--quiet", lease, "origin",
                f"{new}:refs/heads/{DATA_BRANCH}", timeout=180)
    if push.returncode != 0:
        stderr = (push.stderr or "").strip()
        if "stale info" in stderr or "rejected" in stderr or "fetch first" in stderr:
            raise PublishError(
                "someone else published while this run was in flight (the Saturday "
                "job, most likely). Re-run `python3 pipeline.py --mode live`: it "
                "will download the newer database first and rebuild on top of it.")
        raise PublishError(f"git push failed: {stderr}")
    _git(root, "update-ref", BASE_REF, new)
    _git(root, "update-ref", f"refs/remotes/origin/{DATA_BRANCH}", new)
    logger.info("Publish: replaced origin/%s with this run — Pages is deploying", DATA_BRANCH)
    _snapshot(root, generated_at[:16])
    _compact(root)

    result = {"published": True, "commit": new}
    if verify_deploy:
        result["verified"] = verify(generated_at)
    return result


# Each publish writes a new ~2 MB blob into the LOCAL object store, and git's
# auto-gc counts objects, not bytes, so it never fires on its own. Superseded
# data commits are unreachable once BASE_REF moves on, so a gc both packs the
# repository and drops them. (Before the data branch, the committed database
# took the local .git to 209 MB against 11 MB packed.)
LOOSE_LIMIT_KB = 50 * 1024


def _compact(root: Path) -> None:
    """Pack the local repository once loose objects pass LOOSE_LIMIT_KB. Best effort."""
    try:
        counts = dict(line.split(": ", 1) for line in
                      _out(_git(root, "count-objects", "-v")).splitlines() if ": " in line)
        if int(counts.get("size", 0)) < LOOSE_LIMIT_KB:
            return
        if _git(root, "gc", "--quiet", timeout=600).returncode == 0:
            logger.info("Publish: packed the local git history (loose objects were %d MB)",
                        int(counts["size"]) // 1024)
    except (ValueError, OSError, subprocess.SubprocessError):
        pass


def live_generated_at(timeout: int = 20) -> str | None:
    """The `generated_at` the live site is currently serving, or None."""
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

    local_path = ROOT / DATA_FILES["latest.json"]
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
