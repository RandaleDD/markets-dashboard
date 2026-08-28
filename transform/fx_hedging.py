"""
Approximate cost of hedging foreign-currency exposure back to CHF.

READ THIS BEFORE DISPLAYING THE OUTPUT.

This is NOT a traded cross-currency basis swap quote. Those are interbank OTC
prices and are not published on any free feed (the same class of gap as
euro-area inflation swaps). What this computes is the covered-interest-parity
approximation: the short-rate differential, which is the dominant driver of
hedging cost but not the whole of it.

Two things it therefore omits, both of which matter and both of which the UI
has to say out loud:

  1. **The cross-currency basis itself.** CIP has not held cleanly since 2008.
     The CHF basis is persistently negative, which means the real cost of
     hedging into CHF is typically HIGHER than this differential implies. So
     this figure is better read as a floor than as an estimate.
  2. **The rate used.** Forwards price off money-market/OIS rates, not policy
     rates. Policy rates are the proxy here because they are what the pipeline
     already sources for every region.

Sign convention: positive = a cost, you pay to hedge. Negative = a pickup, you
are paid to hedge. Hedging a higher-yielding currency back to a lower-yielding
one costs roughly the differential, which is why a CHF investor hedging USD
pays while the reverse would earn.
"""
from __future__ import annotations

METHOD_LABEL = ("approximated from the policy-rate differential — "
                "not a traded basis swap quote")

CAVEATS = [
    "Excludes the cross-currency basis, which for CHF is persistently negative "
    "— the true hedging cost is typically higher than this figure, so read it "
    "as a floor rather than an estimate.",
    "Uses policy rates as a proxy; FX forwards actually price off "
    "money-market/OIS rates.",
]


def approx_hedging_cost(foreign_rate=None, chf_rate=None) -> dict:
    """
    foreign_rate / chf_rate: policy rates in percent.

    Returns the approximate annualised cost, in percentage points, of hedging
    foreign-currency exposure back into CHF.
    """
    if foreign_rate is None or chf_rate is None:
        return {"cost_pct": None, "direction": None,
                "method": METHOD_LABEL, "caveats": CAVEATS}
    cost = round(float(foreign_rate) - float(chf_rate), 2)
    return {
        "cost_pct": cost,
        "direction": "cost" if cost > 0 else ("pickup" if cost < 0 else "flat"),
        "method": METHOD_LABEL,
        "caveats": CAVEATS,
    }
