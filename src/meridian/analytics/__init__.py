"""Analytics: the quantitative layer.

Everything here works in ``float``. That is a deliberate boundary, not an
oversight: this layer solves, integrates and differentiates, and exact decimal
arithmetic in an iterative solver buys nothing while costing a great deal. Values
that become cash amounts are converted back to ``Decimal`` at the boundary, which
is where :class:`meridian.core.money.Money` takes over. See ADR 0008.
"""

from .bonds import CashFlow, FixedRateBond, portfolio_duration, price_yield_curve
from .curves import CurvePoint, YieldCurve, bootstrap_par_curve, flat_curve, tenor_label
from .solvers import bisect, find_bracket, newton, solve

__all__ = [
    "CashFlow",
    "CurvePoint",
    "FixedRateBond",
    "YieldCurve",
    "bisect",
    "bootstrap_par_curve",
    "find_bracket",
    "flat_curve",
    "newton",
    "portfolio_duration",
    "price_yield_curve",
    "solve",
    "tenor_label",
]
