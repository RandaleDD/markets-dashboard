"""
Real short-rate differentials, from a CHF investor's seat.

WHAT THIS REPLACED, AND WHY (2026-09-21)
----------------------------------------
This took over the slot held by the "cost of hedging back to CHF" table, which
showed a policy-rate differential badly labelled as a hedging cost: it excluded
the cross-currency basis, and it used policy rates where forwards price off
OIS. It was a floor on a number nobody was reading as a floor.

What replaces it is the thing that actually drives a currency over long
horizons: the real rate gap. Nominal rates alone do not, because a high nominal
rate that merely compensates for high inflation is no inducement to hold a
currency -- it is the rate AFTER inflation that attracts capital, and the
inflation differential itself erodes the currency through purchasing power.
Putting both in one figure is the point.

TWO CHOICES WORTH STATING, because both are arguable:

  1. The rate leg is the 2-YEAR GOVERNMENT YIELD, not the policy rate. A policy
     rate is where the central bank is today; the 2y is where the market thinks
     it will be, and FX responds to the expected path rather than to the
     current setting. A policy rate that has sat unchanged for eight months
     carries no information about the next eight, while the 2y has been moving
     the whole time. The cost is that China has no 2y point on its published
     curve, so that row is blank rather than filled from a different tenor.

  2. The inflation leg is the latest CPI year-on-year -- an EX-POST real rate.
     The theoretically better leg is expected inflation, but it exists free for
     only three of eight regions and on three incomparable bases (US market
     breakevens, UK RPI-linked, euro area a survey), which would blank five
     rows to improve three. CPI is available everywhere, and each region's
     index basis is carried with its row because they are not one methodology.
"""
from __future__ import annotations

RATE_LEG_LABEL = "2y government yield"
INFLATION_LEG_LABEL = "latest CPI year-on-year"

METHOD = (
    "Real rate = 2y government yield less the latest CPI year-on-year, then "
    "differenced against Switzerland. The 2y rather than the policy rate "
    "because currencies respond to the expected rate path, not to today's "
    "setting; CPI rather than expected inflation because expectations are "
    "published free for only three of these eight regions, on three bases "
    "that are not comparable."
)

CAVEATS = [
    "Ex-post, not ex-ante: it subtracts inflation that has already happened, "
    "which overstates the real rate where inflation is falling and "
    "understates it where inflation is rising.",
    "Each region's CPI is its own national index (CPI-U, CPI, HICP, LIK, KPI) "
    "— these are not one methodology and the small differences between them "
    "sit inside every figure here.",
    "A long-horizon driver, not a trade signal. Real-rate gaps explain "
    "currency moves over years and routinely point the wrong way for months.",
]


def real_rate(nominal_2y=None, cpi_yoy=None):
    """The ex-post real 2y rate in percentage points, or None if a leg is missing."""
    if nominal_2y is None or cpi_yoy is None:
        return None
    return round(float(nominal_2y) - float(cpi_yoy), 2)


def differential(real_rate_pct=None, home_real_rate_pct=None):
    """
    Foreign real rate less the home (CHF) real rate.

    Positive means the foreign currency offers the higher real return, which
    over long horizons is the direction capital flows -- and, everything else
    equal, the direction the foreign currency appreciates against the franc.
    """
    if real_rate_pct is None or home_real_rate_pct is None:
        return None
    return round(float(real_rate_pct) - float(home_real_rate_pct), 2)
