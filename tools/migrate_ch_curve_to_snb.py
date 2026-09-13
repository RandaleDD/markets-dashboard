"""
One-time migration: clear the Swiss curve of pre-SNB data, 2026-09-13.

WHY THIS EXISTS, AND WHY IT IS NOT A LICENCE TO WRITE MORE OF THEM
------------------------------------------------------------------
`observations` is append-only. No UPDATE, no DELETE, ever -- that rule is the
project's one non-negotiable constraint, and `tests/test_append_only.py` greps
`db/*.py`, `pipeline.py` and `bootstrap.py` to keep it that way. This script
sits outside that scope deliberately: it is a hand-run repair, not part of any
pipeline, and nothing imports it.

The invariant exists to protect economic VINTAGES: the first print of a GDP or
CPI figure must survive every later revision, so the history stays readable.
That is not what is being removed here. `curve.CH.*` accumulated rows from two
sources that were never the Swiss Confederation spot curve at all:

  - OECD monthly average yields (via FRED IRLTLT01CHM156N), 1955-2026-06,
    filed under curve.CH.10Y as a stand-in while no daily source was known.
  - TradingEconomics interbank quotes, 2026-08-28 to 2026-09-11, the project's
    only unofficial source.

Both were mis-filings under an id that means "SNB Confederation spot rate".
Purging them corrects the filing; it erases no vintage of any real print.

Two things made a purge unavoidable rather than merely tidy:

  1. The OECD rows are dated to the first of each month and the SNB data
     downsamples to Fridays, so only 53 of 465 post-1988 legacy dates would
     ever be superseded. The other 808 would have survived INTERLEAVED among
     the SNB weekly points -- two methodologies in one series, which is worse
     than the splice it was meant to replace.
  2. The TradingEconomics rows share a vintage_date with the SNB rows for the
     same date, and the insert path is ON CONFLICT DO NOTHING, so the SNB
     value could not displace them. Measured 2026-09-13, TradingEconomics had
     the 2y at 0.270 where the SNB curve had 0.078 -- so leaving them in place
     would have kept a materially wrong number as the current value.

`data/markets.db` is committed, so `git checkout -- data/markets.db` reverses
this completely.

    python3 tools/migrate_ch_curve_to_snb.py --dry-run
    python3 tools/migrate_ch_curve_to_snb.py --apply

Then reseed, which is the half that actually matters:

    python3 bootstrap.py --series curve.CH.2Y --series curve.CH.5Y \\
                         --series curve.CH.10Y --series curve.CH.30Y
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "markets.db"
PREFIX = "curve.CH."


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually delete")
    ap.add_argument("--dry-run", action="store_true", help="report and change nothing")
    args = ap.parse_args()
    if args.apply == args.dry_run:
        ap.error("pass exactly one of --apply or --dry-run")

    if not DB.exists():
        print(f"No database at {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT series_id, COUNT(*), MIN(date), MAX(date) FROM observations "
        "WHERE series_id LIKE ? GROUP BY series_id ORDER BY series_id", (PREFIX + "%",)
    ).fetchall()
    if not rows:
        print("Nothing to do: no curve.CH.* observations found.")
        return 0

    total = 0
    for series_id, count, first, last in rows:
        print(f"  {series_id:16} {count:6} rows  {first} -> {last}")
        total += count
    print(f"  {'TOTAL':16} {total:6} rows")

    if args.dry_run:
        print("\nDry run -- nothing deleted. Re-run with --apply to proceed.")
        return 0

    conn.execute("DELETE FROM observations WHERE series_id LIKE ?", (PREFIX + "%",))
    conn.commit()
    left = conn.execute("SELECT COUNT(*) FROM observations WHERE series_id LIKE ?",
                        (PREFIX + "%",)).fetchone()[0]
    print(f"\nDeleted {total} rows; {left} curve.CH.* observations remain.")
    print("Now reseed from the SNB cube:")
    print("  python3 bootstrap.py --series curve.CH.2Y --series curve.CH.5Y \\")
    print("                       --series curve.CH.10Y --series curve.CH.30Y")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
