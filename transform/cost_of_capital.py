"""
Cost of equity and cost of debt: the two discount rates you can actually build
from what this dashboard sources, each stated as a formula.

Descriptive only, per SPEC.md's governing constraint. This states what the
market is charging for each layer of risk. It makes no claim about whether
that is attractive, and produces no composite score.

WHAT THIS REPLACED, AND WHY (2026-09-21)
----------------------------------------
Until now this returned a single `total_pct` = risk_free + credit_spread + erp,
labelled "Total". That number was not a cost of capital of any kind:

  - It is not a WACC. A WACC weights the cost of debt and the cost of equity by
    leverage and tax-affects the debt leg. There is no leverage, no tax rate and
    no weighting anywhere in this project, so a WACC cannot be built from what
    is sourced -- it would require inventing an assumed capital structure.
  - It is not a cost of equity, which is risk_free + erp. Adding a credit
    spread on top charges equity for bondholders' default risk as well.
  - It is not a cost of debt, which is risk_free + credit_spread. Adding an ERP
    on top charges debt for equity risk.

Summing all three counts the risk-free rate once and then stacks two premia
that belong to two different claims on the same firm. So it is replaced by the
two figures that ARE well defined, each carrying its formula:

    cost of equity = risk-free + equity risk premium
    cost of debt   = risk-free + investment-grade credit spread

The risk-free leg is the NOMINAL 10y government yield, deliberately. Damodaran's
implied ERP is itself measured against a nominal government yield, so pairing it
with a real rate would remove inflation twice.
"""
from __future__ import annotations

LEG_LABELS = {
    "risk_free": "Risk-free (nominal 10y)",
    "credit_spread": "IG credit spread",
    "erp": "Equity risk premium",
}

COLUMN_FORMULAE = {
    "cost_of_equity": "risk-free (nominal 10y) + equity risk premium",
    "cost_of_debt": "risk-free (nominal 10y) + IG credit spread",
}

# The non-OAS corporate spread is shown BESIDE the legs, never inside them. It
# is a second measurement of the same layer of risk on a different definition
# -- a yield difference with no option adjustment -- so using it would mix two
# bases in one column. It is supplementary and reported only.
# See universe.CORPORATE_SPREADS_TO_GOVT and CONSTRUCTED_CREDIT_SPREADS.
SUPPLEMENTARY_LABELS = {
    "credit_spread_to_govt": "Corporate spread to govt (non-OAS)",
}

NOTE = (
    "Two discount rates, each built only from legs sourced for that region, "
    "and each shown with its formula rather than as an unexplained total. "
    "Cost of equity = risk-free + equity risk premium. Cost of debt = "
    "risk-free + IG credit spread. Both use the NOMINAL 10y government yield "
    "as the risk-free leg: the equity risk premium beside it is itself "
    "measured against a nominal yield, so pairing it with a real rate would "
    "remove inflation twice. Neither is a WACC — that would need a leverage "
    "assumption and a tax rate, neither of which this dashboard sources, so "
    "no weighted figure is shown rather than an invented one."
)


def stack_cost_of_capital(risk_free=None, credit_spread=None, erp=None,
                          credit_spread_to_govt=None) -> dict:
    """
    Each leg in percentage points, any of them None.

    Returns the legs plus the two derived rates. A rate is None unless BOTH of
    its legs are present -- a half-built discount rate is worse than a blank,
    because it looks like a number you could use. `complete` means both rates
    resolved; `available_columns` says which did.

    `credit_spread_to_govt` rides along as a supplementary measurement: it is
    reported and never used in either formula.
    """
    legs = {"risk_free": risk_free, "credit_spread": credit_spread, "erp": erp}

    def add(a, b):
        return round(a + b, 2) if a is not None and b is not None else None

    cost_of_equity = add(risk_free, erp)
    cost_of_debt = add(risk_free, credit_spread)
    rates = {"cost_of_equity": cost_of_equity, "cost_of_debt": cost_of_debt}
    available = [k for k, v in rates.items() if v is not None]
    missing = [k for k, v in legs.items() if v is None]
    return {
        "legs": legs,
        **rates,
        "formulae": dict(COLUMN_FORMULAE),
        "available_columns": available,
        # True only when both discount rates could be built.
        "complete": len(available) == len(rates),
        # Empty when neither rate resolved -- the caller drops the row.
        "has_any": bool(available),
        "missing_legs": missing,
        "missing_labels": [LEG_LABELS[k] for k in missing],
        "supplementary": {"credit_spread_to_govt": credit_spread_to_govt},
    }
