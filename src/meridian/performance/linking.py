"""Linking single-period effects over many periods: four methods, each exact.

An attribution explains each period's active return ``R_t - B_t`` as a sum of
effects. Over several periods the returns compound but the effects add, so the
plain sum of effects misses the compounding: over a year of daily attribution the
gap is a few basis points, over a century of monthly attribution it is most of
the answer. A linking method rescales each period's effects so that they sum to
the compounded active return ``R - B`` with nothing left over.

The four methods agree on that total and differ in how they share it out:

* **Cariño (1999)** - scales period ``t`` by ``k_t / K``, the ratio of its log
  active return per unit of arithmetic active return to the whole period's.
  Symmetric in time; the industry's default.
* **Menchero (2000)** - scales every period by one constant ``M`` (the
  geometric-average correction), plus a small optimised adjustment proportional
  to the period's active return, chosen to minimise the distortion.
* **GRAP** (the Groupe de Recherche en Attribution de Performance, 1997) - scales
  period ``t`` by the portfolio's growth before it and the benchmark's growth
  after it: an effect earned early is carried by what the portfolio did next.
* **Frongello (2002)** - carries each effect forward with the portfolio's growth
  and adds the benchmark's return on the effects already linked. Unrolled, the
  recursion is GRAP's formula, so each effect's total is the same; what differs
  is that Frongello's running totals are known at every date without the
  benchmark's future returns, which GRAP's factor for an early period needs.

Over a year the methods differ by a few basis points of an effect. Over a
century they move a tenth of the answer between allocation and selection: the
choice of method is a choice, and a report should say which it made.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping, Sequence
from typing import Literal, TypeVar

from ..core.exceptions import ValidationError

LinkMethod = Literal["carino", "menchero", "grap", "frongello"]
METHODS: tuple[LinkMethod, ...] = ("carino", "menchero", "grap", "frongello")
K = TypeVar("K", bound=Hashable)


def compound(rates: Sequence[float]) -> float:
    return math.prod(1.0 + rate for rate in rates) - 1.0


def carino_factor(portfolio: float, benchmark: float) -> float:
    """ln(1+R) - ln(1+B) over R - B; its limit 1/(1+R) where the two are equal."""
    if abs(portfolio - benchmark) < 1e-15:
        return 1.0 / (1.0 + portfolio)
    return (math.log1p(portfolio) - math.log1p(benchmark)) / (portfolio - benchmark)


def _carino(portfolio: Sequence[float], benchmark: Sequence[float]) -> list[float]:
    big_k = carino_factor(compound(portfolio), compound(benchmark))
    return [carino_factor(r, b) / big_k for r, b in zip(portfolio, benchmark, strict=True)]


def _menchero(portfolio: Sequence[float], benchmark: Sequence[float]) -> list[float]:
    count = len(portfolio)
    total_r, total_b = compound(portfolio), compound(benchmark)
    growth_r, growth_b = (1.0 + total_r) ** (1.0 / count), (1.0 + total_b) ** (1.0 / count)
    if abs(growth_r - growth_b) < 1e-15:
        constant = growth_r ** (count - 1)  # the limit of M as R tends to B
    else:
        constant = (total_r - total_b) / (count * (growth_r - growth_b))
    active = [r - b for r, b in zip(portfolio, benchmark, strict=True)]
    squares = sum(value * value for value in active)
    if squares == 0.0:
        return [constant] * count
    adjustment = (total_r - total_b - constant * sum(active)) / squares
    return [constant + adjustment * value for value in active]


def _grap(portfolio: Sequence[float], benchmark: Sequence[float]) -> list[float]:
    count = len(portfolio)
    before = [1.0] * count  # portfolio growth before period t
    after = [1.0] * count  # benchmark growth after period t
    for index in range(1, count):
        before[index] = before[index - 1] * (1.0 + portfolio[index - 1])
    for index in range(count - 2, -1, -1):
        after[index] = after[index + 1] * (1.0 + benchmark[index + 1])
    return [b * a for b, a in zip(before, after, strict=True)]


def multipliers(portfolio: Sequence[float], benchmark: Sequence[float], method: LinkMethod) -> list[float]:
    """Per-period factors for the methods that scale a whole period at once (not Frongello)."""
    if len(portfolio) != len(benchmark) or not portfolio:
        raise ValidationError("linking needs one portfolio and one benchmark return per period")
    if method == "carino":
        return _carino(portfolio, benchmark)
    if method == "menchero":
        return _menchero(portfolio, benchmark)
    if method == "grap":
        return _grap(portfolio, benchmark)
    raise ValidationError(f"{method} does not link by a factor per period")


def link_lines(
    lines: Mapping[K, Sequence[float]],
    portfolio: Sequence[float],
    benchmark: Sequence[float],
    method: LinkMethod = "carino",
) -> dict[K, float]:
    """Link each effect line - one value per period - into its share of the compounded active return.

    When each period's effects sum to that period's active return, the linked
    totals sum to ``compound(portfolio) - compound(benchmark)`` exactly, whichever
    method is used.
    """
    if method not in METHODS:
        raise ValidationError(f"unknown linking method {method!r}; choose from {', '.join(METHODS)}")
    count = len(portfolio)
    if len(benchmark) != count or count == 0:
        raise ValidationError("linking needs one portfolio and one benchmark return per period")
    for key, values in lines.items():
        if len(values) != count:
            raise ValidationError(f"effect line {key!r} has {len(values)} values for {count} periods")
    if method == "frongello":
        linked: dict[K, float] = {}
        for key, values in lines.items():
            growth, carried = 1.0, 0.0  # portfolio growth before t, and this line's linked total so far
            for effect, r, b in zip(values, portfolio, benchmark, strict=True):
                carried += effect * growth + b * carried
                growth *= 1.0 + r
            linked[key] = carried
        return linked
    factors = multipliers(portfolio, benchmark, method)
    return {key: sum(v * f for v, f in zip(values, factors, strict=True)) for key, values in lines.items()}
