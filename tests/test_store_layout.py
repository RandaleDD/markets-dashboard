"""
The physical layout of the store, and what happens to catalog rows the
registry has stopped producing.

`observations` is WITHOUT ROWID with no secondary index (db/schema.sql), and
the committed database must actually be in that form -- CREATE TABLE IF NOT
EXISTS never converts an existing table, so a schema edit alone proves nothing
about the file on disk. tools/rebuild_store.py is the one-time conversion, and
it must carry every row across untouched.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import store  # noqa: E402

OLD_LAYOUT = """
CREATE TABLE series_catalog (series_id TEXT PRIMARY KEY, category TEXT NOT NULL,
    region TEXT, description TEXT NOT NULL, unit TEXT, native_periodicity TEXT,
    source TEXT, max_age_days INTEGER, status TEXT NOT NULL, notes TEXT);
CREATE TABLE observations (series_id TEXT NOT NULL REFERENCES series_catalog(series_id),
    date TEXT NOT NULL, vintage_date TEXT NOT NULL, value REAL NOT NULL,
    ingested_at TEXT NOT NULL, source_run_id INTEGER REFERENCES pipeline_runs(run_id),
    PRIMARY KEY (series_id, date, vintage_date));
CREATE INDEX idx_obs_series ON observations(series_id, date);
CREATE TABLE pipeline_runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT, mode TEXT, git_sha TEXT);
CREATE TABLE data_quality_flags (flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL REFERENCES series_catalog(series_id), date TEXT NOT NULL,
    flag_type TEXT NOT NULL, detail TEXT, raised_at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0);
"""


def _row(sid):
    return {"series_id": sid, "category": "Test", "region": "US", "description": sid,
            "unit": "x", "native_periodicity": "weekly", "source": "stub",
            "max_age_days": 14, "status": "ok", "notes": None}


def _indexes(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'observations'")}


class Layout(unittest.TestCase):
    def test_fresh_store_is_without_rowid_with_no_extra_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(Path(tmp) / "t.db")
            store.init_db(conn)
            self.assertTrue(store.is_current_layout(conn))
            self.assertEqual(_indexes(conn), set())
            conn.close()

    def test_committed_store_has_been_converted(self):
        db = ROOT / "data" / "markets.db"
        if not db.exists():
            self.skipTest("no committed database in this checkout")
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self.assertTrue(store.is_current_layout(conn),
                        "run `python3 tools/rebuild_store.py` and commit the result")
        self.assertEqual(_indexes(conn), set())
        conn.close()

    def test_rebuild_carries_every_row_across(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.executescript(OLD_LAYOUT)
            conn.execute("INSERT INTO series_catalog VALUES "
                         "('a','T',NULL,'a',NULL,NULL,NULL,14,'ok',NULL)")
            conn.execute("INSERT INTO pipeline_runs (run_id, started_at) VALUES (7, 'x')")
            conn.executemany("INSERT INTO observations VALUES ('a', ?, ?, ?, '2026-01-01T00:00', 7)",
                             [("2026-01-02", "2026-01-02", 1.0),
                              ("2026-01-02", "2026-02-01", 1.5),
                              ("2026-01-09", "2026-01-09", 2.0)])
            conn.execute("INSERT INTO data_quality_flags (flag_id, series_id, date, "
                         "flag_type, raised_at) VALUES (40, 'a', '2026-01-02', 'gap', 'x')")
            conn.commit()
            conn.close()

            done = subprocess.run([sys.executable, str(ROOT / "tools" / "rebuild_store.py"),
                                   "--db", str(path)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

            conn = sqlite3.connect(path)
            self.assertTrue(store.is_current_layout(conn))
            self.assertEqual(_indexes(conn), set())
            self.assertNotIn("ingested_at", store._columns(conn))
            self.assertEqual(conn.execute("SELECT date, vintage_date, value FROM observations "
                                          "ORDER BY 1, 2").fetchall(),
                             [("2026-01-02", "2026-01-02", 1.0),
                              ("2026-01-02", "2026-02-01", 1.5),
                              ("2026-01-09", "2026-01-09", 2.0)])
            self.assertEqual(conn.execute("SELECT run_id FROM pipeline_runs").fetchall(), [(7,)])
            self.assertEqual(conn.execute("SELECT flag_id FROM data_quality_flags").fetchall(),
                             [(40,)])
            # The AUTOINCREMENT high-water mark survives, so ids are never reused.
            self.assertEqual(dict(conn.execute("SELECT name, seq FROM sqlite_sequence")),
                             {"pipeline_runs": 7, "data_quality_flags": 40})
            conn.close()
            self.assertTrue((Path(tmp) / "old.db.pre-rebuild").exists())


class RetireUnregistered(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "t.db")
        store.init_db(self.conn)
        store.upsert_catalog(self.conn, [_row(s) for s in
                                         ("live", "gone.empty", "gone.history", "gone.flagged")])
        store.insert_observations(self.conn, [("gone.history", "2026-01-02", "2026-01-02", 1.0)])
        store.raise_flag(self.conn, "gone.flagged", "2026-01-02", "gap", "x")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def status(self):
        return dict(self.conn.execute("SELECT series_id, status FROM series_catalog"))

    def test_unreferenced_rows_go_referenced_rows_are_retired(self):
        result = store.retire_unregistered(self.conn, {"live"})
        self.assertEqual(result, {"removed": ["gone.empty"],
                                  "retired": ["gone.flagged", "gone.history"]})
        self.assertEqual(self.status(), {"live": "ok", "gone.history": "retired",
                                         "gone.flagged": "retired"})
        # The history itself is untouched.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)

    def test_reregistering_brings_a_series_back(self):
        store.retire_unregistered(self.conn, {"live"})
        store.upsert_catalog(self.conn, [_row("live"), _row("gone.history")])
        store.retire_unregistered(self.conn, {"live", "gone.history"})
        self.assertEqual(self.status()["gone.history"], "ok")


if __name__ == "__main__":
    unittest.main()
