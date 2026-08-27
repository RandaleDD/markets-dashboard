"""Equity risk premium: regional earnings yield minus regional 10y govt yield."""
from __future__ import annotations


def compute_erp(forward_pe: float | None, govt_10y_yield_pct: float | None) -> float | None:
    """
    forward_pe: forward P/E ratio (e.g. 21.5)
    govt_10y_yield_pct: 10y government yield in percent (e.g. 4.2)
    Returns ERP in percentage points, or None if inputs are missing/invalid.
    """
    if not forward_pe or forward_pe <= 0 or govt_10y_yield_pct is None:
        return None
    earnings_yield_pct = (1.0 / forward_pe) * 100.0
    return round(earnings_yield_pct - govt_10y_yield_pct, 2)
