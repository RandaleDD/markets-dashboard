"""
Hand-run repair: purge a series' observations so a new source can reseed it.

WHY THIS EXISTS, AND WHY IT IS NOT A LICENCE TO WRITE MORE OF THEM
------------------------------------------------------------------
`observations` is append-only. No UPDATE, no DELETE, ever -- that rule is the
project's one non-negotiable constraint, and `tests/test_append_only.py` greps
`db/*.py`, `pipeline.py` and `bootstrap.py` to keep it that way. This script
sits outside that scope deliberately: it is run by hand, it is not part of any
pipeline, and nothing imports it.

The invariant exists to protect economic VINTAGES: the first print of a GDP or
CPI figure must survive every later revision, so the history stays readable.
That is not what this removes. It exists for the one case the append-only model
cannot express -- when a series id starts meaning something DIFFERENT, because
its source changed to a different quantity, frequency or index base. Appending
cannot fix that, for two mechanical reasons:

  - New observations only displace old ones on dates they share. Where the
    grids differ the two sources INTERLEAVE, leaving one series carrying two
    methodologies at alternating dates.
  - Where they do share a date they also tend to share a vintage_date, and the
    insert path is ON CONFLICT DO NOTHING, so the old value WINS.

Both were measured, on the two migrations this was written for:

  curve.CH.*  2026-09-13. Held OECD monthly averages (dated to the first of
              each month) and TradingEconomics quotes, under an id that means
              "SNB Confederation spot rate". Against the SNB's Friday grid only
              53 of 465 post-1988 dates would ever have been superseded. And
              TradingEconomics had the 2y at 0.270 where the SNB curve had
              0.078, so leaving it would have kept a wrong number as current.

  gdp.CN      2026-09-13. Held ANNUAL real GDP totals from FRED under an id
              that now means a quarterly level from the World Bank GEM. Both
              date a year's first period to YYYY-01-01, so the annual figure
              sat on Q1's date: 2025-01-01 was 134,569,020 annual against
              34,475,330 for the quarter. A ~4x difference, silently.

In both cases what is deleted is a MIS-FILING under the id, not a vintage of
the series the id now names. `data/markets.db` is committed, so
`git checkout -- data/markets.db` reverses any of this completely.

    python3 tools/purge_series.py --prefix curve.CH. --dry-run
    python3 tools/purge_series.py --prefix curve.CH. --apply

Always reseed immediately afterwards -- that is the half that matters:

    python3 bootstrap.py --series <id> [--series <id> ...]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "markets.db"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prefix", required=True,
                    help="series_id prefix to purge, e.g. 'curve.CH.' or 'gdp.CN'")
    ap.add_argument("--apply", action="store_true", help="actually delete")
    ap.add_argument("--dry-run", action="store_true", help="report and change nothing")
    args = ap.parse_args()
    if args.apply == args.dry_run:
        ap.error("pass exactly one of --apply or --dry-run")
    prefix = args.prefix

    if not DB.exists():
        print(f"No database at {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT series_id, COUNT(*), MIN(date), MAX(date) FROM observations "
        "WHERE series_id LIKE ? GROUP BY series_id ORDER BY series_id", (prefix + "%",)
    ).fetchall()
    if not rows:
        print(f"Nothing to do: no observations match {prefix}*.")
        return 0

    total = 0
    for series_id, count, first, last in rows:
        print(f"  {series_id:16} {count:6} rows  {first} -> {last}")
        total += count
    print(f"  {'TOTAL':16} {total:6} rows")

    if args.dry_run:
        print("\nDry run -- nothing deleted. Re-run with --apply to proceed.")
        return 0

    conn.execute("DELETE FROM observations WHERE series_id LIKE ?", (prefix + "%",))
    conn.commit()
    left = conn.execute("SELECT COUNT(*) FROM observations WHERE series_id LIKE ?",
                        (prefix + "%",)).fetchone()[0]
    print(f"\nDeleted {total} rows; {left} observations matching {prefix}* remain.")
    print("Now reseed, or the series is simply empty:")
    for series_id, *_ in rows:
        print(f"  python3 bootstrap.py --series {series_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
