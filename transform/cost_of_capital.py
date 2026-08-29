"""
Cost-of-capital stack: the literal inputs to discounting a long-duration
asset, laid out leg by leg rather than collapsed into one figure.

Descriptive only, per SPEC.md's governing constraint. This states what the
market is charging for each layer of risk. It makes no claim about whether
that is attractive, and produces no composite score.
"""
from __future__ import annotations

LEG_LABELS = {
    "real_risk_free": "Real risk-free (10y)",
    "credit_spread": "IG credit spread",
    "erp": "Equity risk premium",
}


def stack_cost_of_capital(real_risk_free=None, credit_spread=None, erp=None) -> dict:
    """
    Each leg in percentage points, any of them None.

    Returns the legs, their sum over whatever is present, and an explicit list
    of what is missing — a region with two of three legs shows those two
    rather than dropping out of the table, but the total is then not
    comparable with a complete stack and has to say so.
    """
    legs = {"real_risk_free": real_risk_free, "credit_spread": credit_spread, "erp": erp}
    present = {k: v for k, v in legs.items() if v is not None}
    missing = [k for k, v in legs.items() if v is None]
    total = round(sum(present.values()), 2) if present else None
    return {
        "legs": legs,
        "total_pct": total,
        "complete": not missing,
        "missing_legs": missing,
        "missing_labels": [LEG_LABELS[k] for k in missing],
    }
