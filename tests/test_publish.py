"""
The guards on publishing, against a real git repository built per test.

Publishing is the one step here that reaches the outside world, and three of
its failure modes are silent rather than loud:

  * synthetic numbers reaching the live site (the sample database protects the
    store, nothing else protects the JSON),
  * a `git add -A` sweeping an unfinished code edit into a data refresh,
  * a second committer inside GitHub Actions racing weekly.yml's own push.

So these tests drive `publish` against a throwaway checkout with a bare remote
rather than mocking git: the thing being tested IS the git behaviour.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import publish

GENERATED_AT = "2026-09-12T12:00:00+00:00"


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    return (proc.stdout or "").strip()


class PublishGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.remote = base / "remote.git"
        self.repo = base / "repo"
        subprocess.run(["git", "init", "--quiet", "--bare", str(self.remote)], check=True)
        subprocess.run(["git", "clone", "--quiet", str(self.remote), str(self.repo)],
                       check=True)
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "test")
        git(self.repo, "checkout", "--quiet", "-b", "main")

        (self.repo / "site" / "data").mkdir(parents=True)
        (self.repo / "data").mkdir(parents=True)
        self._write("site/data/latest.json", json.dumps({"generated_at": "old"}))
        self._write("data/markets.db", "binary-ish")
        self._write("data/DATA-CATALOG.csv", "a,b\n1,2\n")
        self._write("site/index.html", '<script src="assets/app.js?v=aaaaaaaaaa"></script>\n')
        self._write("site/assets/app.js", "// code\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "--quiet", "-m", "seed")
        git(self.repo, "push", "--quiet", "-u", "origin", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def _refresh_data(self) -> None:
        """What a pipeline run leaves behind."""
        self._write("site/data/latest.json", json.dumps({"generated_at": GENERATED_AT}))
        self._write("data/markets.db", "binary-ish, but newer")

    # --- the three silent failure modes ------------------------------------
    def test_sample_mode_never_publishes(self):
        self._refresh_data()
        result = publish.publish(GENERATED_AT, mode="sample", root=self.repo,
                                 verify_deploy=False)
        self.assertFalse(result["published"])
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only"), "",
                         "a sample run staged the generated data")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"),
                         git(self.repo, "rev-parse", "origin/main"),
                         "a sample run committed")

    def test_github_actions_never_publishes(self):
        self._refresh_data()
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
            result = publish.publish(GENERATED_AT, mode="live", root=self.repo,
                                     verify_deploy=False)
        self.assertIn("Actions", result["skipped"])

    def test_unrelated_code_edits_are_never_committed(self):
        self._refresh_data()
        self._write("site/assets/app.js", "// half-finished edit\n")
        publish.publish(GENERATED_AT, mode="live", root=self.repo, verify_deploy=False)
        committed = git(self.repo, "show", "--name-only", "--format=", "HEAD").split()
        self.assertIn("data/markets.db", committed)
        self.assertNotIn("site/assets/app.js", committed)
        self.assertIn("site/assets/app.js",
                      git(self.repo, "status", "--porcelain"))

    # --- the happy path -----------------------------------------------------
    def test_publishes_the_generated_artefacts_and_pushes(self):
        self._refresh_data()
        result = publish.publish(GENERATED_AT, mode="live", root=self.repo,
                                 verify_deploy=False)
        self.assertTrue(result["published"])
        self.assertEqual(set(result["staged"]),
                         {"site/data/latest.json", "data/markets.db"})
        # On the REMOTE, which is what Pages would deploy from.
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"),
                         git(self.repo, "rev-parse", "origin/main"))
        self.assertIn(GENERATED_AT, git(self.repo, "show", "origin/main:site/data/latest.json"))

    def test_second_run_with_no_new_data_pushes_nothing(self):
        self._refresh_data()
        publish.publish(GENERATED_AT, mode="live", root=self.repo, verify_deploy=False)
        before = git(self.repo, "rev-parse", "HEAD")
        result = publish.publish(GENERATED_AT, mode="live", root=self.repo,
                                 verify_deploy=False)
        self.assertFalse(result["published"])
        self.assertEqual(before, git(self.repo, "rev-parse", "HEAD"))

    # --- index.html: a stamp is data, markup is code ------------------------
    def test_asset_stamp_alone_is_published(self):
        self._refresh_data()
        self._write("site/index.html", '<script src="assets/app.js?v=bbbbbbbbbb"></script>\n')
        publish.publish(GENERATED_AT, mode="live", root=self.repo, verify_deploy=False)
        self.assertIn("site/index.html",
                      git(self.repo, "show", "--name-only", "--format=", "HEAD").split())

    def test_hand_edited_markup_is_not_published(self):
        self._refresh_data()
        self._write("site/index.html",
                    '<script src="assets/app.js?v=bbbbbbbbbb"></script>\n<p>WIP</p>\n')
        publish.publish(GENERATED_AT, mode="live", root=self.repo, verify_deploy=False)
        self.assertNotIn("site/index.html",
                         git(self.repo, "show", "--name-only", "--format=", "HEAD").split())

    # --- branches and divergence -------------------------------------------
    def test_a_feature_branch_does_not_publish(self):
        git(self.repo, "checkout", "--quiet", "-b", "try-something")
        self._refresh_data()
        result = publish.publish(GENERATED_AT, mode="live", root=self.repo,
                                 verify_deploy=False)
        self.assertIn("try-something", result["skipped"])

    def test_a_rejected_push_asks_for_a_re_run_rather_than_merging(self):
        # Someone else (the Saturday job) pushed while this run was in flight.
        other = Path(self.tmp.name) / "other"
        subprocess.run(["git", "clone", "--quiet", str(self.remote), str(other)], check=True)
        git(other, "config", "user.email", "bot@example.com")
        git(other, "config", "user.name", "bot")
        (other / "data" / "markets.db").write_text("the bot's newer database")
        git(other, "commit", "--quiet", "-am", "weekly refresh")
        git(other, "push", "--quiet", "origin", "main")

        self._refresh_data()
        with self.assertRaises(publish.PublishError) as caught:
            publish.publish(GENERATED_AT, mode="live", root=self.repo,
                            verify_deploy=False)
        self.assertIn("Re-run", str(caught.exception))

    def test_sync_fast_forwards_before_a_run(self):
        other = Path(self.tmp.name) / "other2"
        subprocess.run(["git", "clone", "--quiet", str(self.remote), str(other)], check=True)
        git(other, "config", "user.email", "bot@example.com")
        git(other, "config", "user.name", "bot")
        (other / "data" / "DATA-CATALOG.csv").write_text("a,b\n9,9\n")
        git(other, "commit", "--quiet", "-am", "catalog from the runner")
        git(other, "push", "--quiet", "origin", "main")

        self.assertIn("fast-forwarded", publish.sync(root=self.repo))
        self.assertEqual((self.repo / "data" / "DATA-CATALOG.csv").read_text(),
                         "a,b\n9,9\n")


if __name__ == "__main__":
    unittest.main()
