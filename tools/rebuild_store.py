#!/usr/bin/env python3
"""
Rebuild markets.db into the current schema.sql layout -- run once, by hand.

Exists for layout changes to `observations`: it became a WITHOUT ROWID table
(2026-10-22), which stores rows inside the primary-key b-tree instead of beside
a second copy of it, and lost its per-row `ingested_at` timestamp, which nothing
read. Together they took the file from 28 MB to under 9. SQLite cannot ALTER a table into that form, and
`store.init_db` must never rebuild the store on its own, so this does it out of
band.

It does not touch the old file's rows. It builds a NEW file from schema.sql,
copies every table across with the ids intact, proves the copy is identical
(row counts for every table, and a two-way EXCEPT over the whole of
`observations`), and only then swaps the new file into place. The old file is
kept beside it as `<name>.pre-rebuild` until you delete it; for the committed
database, git history holds it too.

    python3 tools/rebuild_store.py                      # data/markets.db
    python3 tools/rebuild_store.py --db data/markets-sample.db
"""
from __future__ import annotations

import argparse
from contextlib import closing
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import store  # noqa: E402

# Parents before children, so the foreign keys hold row by row.
TABLES = ("series_catalog", "pipeline_runs", "observations", "data_quality_flags")


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def rebuild(path: Path) -> int:
    if not path.exists():
        print(f"No database at {path}", file=sys.stderr)
        return 1
    with closing(sqlite3.connect(path)) as old:
        if store.is_current_layout(old):
            print(f"{path.name}: already in the current layout, nothing to do.")
            return 0
        if old.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            print(f"{path.name}: integrity_check failed; not touching it.", file=sys.stderr)
            return 1

    new_path = path.with_name(path.name + ".rebuild")
    backup = path.with_name(path.name + ".pre-rebuild")
    if new_path.exists():
        new_path.unlink()

    conn = store.connect(new_path)
    store.init_db(conn)
    conn.execute("ATTACH DATABASE ? AS old", (str(path),))
    with conn:
        for table in TABLES:
            cols = ",".join(c for c in _columns(conn, "main", table)
                            if c in _columns(conn, "old", table))
            conn.execute(f"INSERT INTO main.{table} ({cols}) SELECT {cols} FROM old.{table}")
        # AUTOINCREMENT high-water marks, so a new run_id never reuses a retired one.
        conn.execute("DELETE FROM main.sqlite_sequence")
        conn.execute("INSERT INTO main.sqlite_sequence SELECT * FROM old.sqlite_sequence")

    problems = []
    for table in TABLES:
        a = conn.execute(f"SELECT COUNT(*) FROM old.{table}").fetchone()[0]
        b = conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
        print(f"  {table:20} {a:8,} -> {b:8,}")
        if a != b:
            problems.append(f"{table}: {a} rows became {b}")
    cols = ",".join(c for c in _columns(conn, "main", "observations")
                    if c in _columns(conn, "old", "observations"))
    for left, right in (("old", "main"), ("main", "old")):
        diff = conn.execute(f"SELECT COUNT(*) FROM (SELECT {cols} FROM {left}.observations "
                            f"EXCEPT SELECT {cols} FROM {right}.observations)").fetchone()[0]
        if diff:
            problems.append(f"{diff} observations in {left} are missing from {right}")
    conn.execute("DETACH DATABASE old")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        problems.append("foreign_key_check reports violations")
    if not store.is_current_layout(conn):
        problems.append("the rebuilt table does not match schema.sql")
    conn.close()

    if problems:
        new_path.unlink()
        print("Rebuild ABORTED, original untouched:\n  " + "\n  ".join(problems),
              file=sys.stderr)
        return 1

    before = path.stat().st_size
    os.replace(path, backup)
    os.replace(new_path, path)
    print(f"{path.name}: {before / 2**20:.1f} MB -> {path.stat().st_size / 2**20:.1f} MB. "
          f"Old file kept as {backup.name}; delete it once you are happy.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--db", type=Path, default=store.db_path(),
                    help="database to rebuild (default: the live store)")
    return rebuild(ap.parse_args().db)


if __name__ == "__main__":
    raise SystemExit(main())
