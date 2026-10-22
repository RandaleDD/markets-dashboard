"""
The guards on publishing, against a real git repository built per test.

Publishing replaces the single-commit `data` branch. Its silent failure modes:

  * synthetic numbers reaching the live site,
  * a data refresh committing code, or committing to main at all,
  * two publishers (the Saturday job, the Mac) overwriting each other's rows,
  * a sync replacing a local database that holds unpublished rows,
  * the data branch growing a history.

So these tests drive `publish` against a throwaway checkout with a bare remote
rather than mocking git: the thing being tested IS the git behaviour.
"""
from __future__ import annotations

import gzip
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import publish

GENERATED_AT = "2026-09-12T12:00:00+00:00"


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return (proc.stdout or "").strip()


def clone(remote: Path, where: Path) -> Path:
    subprocess.run(["git", "clone", "--quiet", "-b", "main", str(remote), str(where)],
                   check=True)
    git(where, "config", "user.email", "test@example.com")
    git(where, "config", "user.name", "test")
    return where


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.remote = base / "remote.git"
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(self.remote)],
                       check=True)
        seed = base / "seed"
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(seed)], check=True)
        git(seed, "config", "user.email", "test@example.com")
        git(seed, "config", "user.name", "test")
        (seed / "site" / "assets").mkdir(parents=True)
        (seed / "site" / "assets" / "app.js").write_text("// code\n")
        (seed / ".gitignore").write_text("data/\nsite/data/\n")
        (seed / ".github" / "workflows").mkdir(parents=True)
        (seed / ".github" / "workflows" / "pages.yml").write_text("name: deploy\n")
        git(seed, "add", "-A")
        git(seed, "commit", "--quiet", "-m", "code")
        git(seed, "remote", "add", "origin", str(self.remote))
        git(seed, "push", "--quiet", "origin", "main")
        self.repo = clone(self.remote, base / "repo")
        self._run(self.repo, "db v1", GENERATED_AT)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, root: Path, db: str, generated_at: str) -> None:
        """What a pipeline run leaves behind."""
        for rel, text in (("data/markets.db", db),
                          ("site/data/latest.json", json.dumps({"generated_at": generated_at})),
                          ("data/DATA-COVERAGE.csv", "Identifier\nx\n")):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)

    def _publish(self, root=None, generated_at=GENERATED_AT):
        return publish.publish(generated_at, mode="live", root=root or self.repo,
                               verify_deploy=False)

    def _remote_file(self, name: str) -> bytes:
        return subprocess.run(["git", "-C", str(self.remote), "show", f"data:{name}"],
                              capture_output=True, check=True).stdout

    # --- what must never happen --------------------------------------------
    def test_sample_mode_never_publishes(self):
        result = publish.publish(GENERATED_AT, mode="sample", root=self.repo,
                                 verify_deploy=False)
        self.assertFalse(result["published"])
        self.assertEqual(git(self.remote, "branch", "--list", "data"), "")

    def test_a_feature_branch_does_not_publish(self):
        git(self.repo, "checkout", "--quiet", "-b", "try-something")
        self.assertIn("try-something", self._publish()["skipped"])

    def test_main_and_code_are_never_touched(self):
        main_before = git(self.remote, "rev-parse", "main")
        (self.repo / "site" / "assets" / "app.js").write_text("// half-finished\n")
        self._publish()
        self.assertEqual(git(self.remote, "rev-parse", "main"), main_before)
        self.assertIn("app.js", git(self.repo, "status", "--porcelain"))

    def test_the_data_branch_never_grows_a_history(self):
        self._publish()
        self._run(self.repo, "db v2", "newer")
        self._publish(generated_at="newer")
        self.assertEqual(git(self.remote, "rev-list", "--count", "data"), "1")
        self.assertEqual(gzip.decompress(self._remote_file("markets.db.gz")), b"db v2")

    def test_a_rejected_push_asks_for_a_re_run_rather_than_overwriting(self):
        self._publish()
        # Someone else (the Saturday job) published while this run was in flight.
        other = clone(self.remote, Path(self.tmp.name) / "other")
        publish.sync_data(other)
        self._run(other, "the bot's newer database", "bot")
        self._publish(root=other, generated_at="bot")

        self._run(self.repo, "db v2", "mine")
        with self.assertRaises(publish.PublishError) as caught:
            self._publish(generated_at="mine")
        self.assertIn("Re-run", str(caught.exception))
        self.assertEqual(gzip.decompress(self._remote_file("markets.db.gz")),
                         b"the bot's newer database")

    def test_sync_never_replaces_unpublished_rows(self):
        self._publish()
        other = clone(self.remote, Path(self.tmp.name) / "other")
        publish.sync_data(other)
        self._run(other, "the bot's newer database", "bot")
        self._publish(root=other, generated_at="bot")

        (self.repo / "data" / "markets.db").write_text("local rows nobody has seen")
        with self.assertRaises(publish.PublishError):
            publish.sync_data(self.repo)
        self.assertEqual((self.repo / "data" / "markets.db").read_text(),
                         "local rows nobody has seen")

    # --- what must happen ----------------------------------------------------
    def test_publishes_every_artefact_to_the_data_branch(self):
        self.assertTrue(self._publish()["published"])
        self.assertEqual(gzip.decompress(self._remote_file("markets.db.gz")), b"db v1")
        self.assertIn(GENERATED_AT, self._remote_file("latest.json").decode())
        self.assertEqual(self._remote_file("DATA-COVERAGE.csv"), b"Identifier\nx\n")
        # ...plus the deploy workflow, without which a push here deploys nothing.
        self.assertEqual(self._remote_file(".github/workflows/pages.yml"), b"name: deploy\n")

    def test_second_run_with_no_new_data_pushes_nothing(self):
        self._publish()
        tip = git(self.remote, "rev-parse", "data")
        self.assertEqual(self._publish()["skipped"], "no change")
        self.assertEqual(git(self.remote, "rev-parse", "data"), tip)

    def test_a_fresh_checkout_downloads_the_published_data(self):
        self._publish()
        fresh = clone(self.remote, Path(self.tmp.name) / "fresh")
        self.assertIn("downloaded", publish.sync_data(fresh))
        self.assertEqual((fresh / "data" / "markets.db").read_text(), "db v1")
        self.assertIn(GENERATED_AT, (fresh / "site" / "data" / "latest.json").read_text())

    def test_sync_brings_an_unchanged_database_up_to_date(self):
        self._publish()
        other = clone(self.remote, Path(self.tmp.name) / "other")
        publish.sync_data(other)
        self._run(other, "db v2", "bot")
        self._publish(root=other, generated_at="bot")

        self.assertIn("downloaded", publish.sync_data(self.repo))
        self.assertEqual((self.repo / "data" / "markets.db").read_text(), "db v2")
        # ...and the next publish from here is accepted again.
        self._run(self.repo, "db v3", "mine")
        self.assertTrue(self._publish(generated_at="mine")["published"])

    def test_local_snapshots_are_kept_and_pruned(self):
        for i in range(publish.KEEP_SNAPSHOTS + 3):
            self._run(self.repo, f"db v{i}", f"2026-10-{i + 1:02d}T06:00")
            self._publish(generated_at=f"2026-10-{i + 1:02d}T06:00")
        snaps = list((self.repo / "data" / "history").glob("markets-*.db.gz"))
        self.assertEqual(len(snaps), publish.KEEP_SNAPSHOTS)


if __name__ == "__main__":
    unittest.main()
