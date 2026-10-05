"""A sector limit on a century of the US market.

Day 6 checked one account over two years. Here the same engine and register run
on Kenneth French's twelve industries (``marketdata.french``) every month since July
1926, with a mandate a sector fund or a UCITS-style index product might carry:

    rule sector_40 "Any one industry" hard        max weight by sector <= 40% warn at 35%
    rule top_heavy "Industries above 20% together" soft  sum weight by sector above 20% <= 60%

- :func:`index_register` holds the market as it is - an index fund that never
  trades - so every breach is **passive**, opened and closed by the market: which
  industries the cap-weighted market pushed over the line, when, and for how long.
- :func:`capped_comparison` runs the remedy index providers sell for exactly this:
  a capped index, rebalanced every month to market weights with no industry above
  35% (the excess shared pro rata among the rest). It never breaches; the question
  is what the cap cost, in return and in tracking error against the market.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np

from ..compliance.engine import ComplianceReport, check
from ..compliance.language import Mandate
from ..compliance.monitor import Breach, build_register
from ..compliance.parser import parse_mandate
from ..compliance.snapshot import Holding, Snapshot
from ..marketdata.french import INDUSTRY_NAMES, FrenchHistory, french_history

MANDATE_TEXT = """
mandate "US equity sector limits" version 1 effective 1926-07-01

rule sector_40 "Any one industry" hard
    max weight by sector <= 40% warn at 35%

rule top_heavy "Industries above 20% together" soft
    sum weight by sector above 20% <= 60%
"""
CAP = 0.35


def mandate() -> Mandate:
    return parse_mandate(MANDATE_TEXT)


def snapshot(history: FrenchHistory, month: date, weights: dict[str, float]) -> Snapshot:
    holdings = tuple(
        Holding(name, weight, {"asset_class": "equity", "sector": INDUSTRY_NAMES[name], "issuer": name})
        for name, weight in weights.items()
    )
    return Snapshot(month, 1.0, holdings)


@lru_cache(maxsize=1)
def index_reports() -> tuple[ComplianceReport, ...]:
    """The mandate checked on the market's own weights at the start of every month."""
    history = french_history()
    rules = mandate()
    return tuple(check(rules, snapshot(history, month, history.weights(month))) for month in history.months)


def index_register() -> list[Breach]:
    """Every breach the market itself caused: an index fund trades nothing, so each is passive."""
    return build_register(list(index_reports()), {})


def cap_weights(weights: dict[str, float], cap: float = CAP) -> dict[str, float]:
    """Market weights with none above ``cap``: the excess shared pro rata among the uncapped, until none is over.

    The method of capped indices (MSCI's 10/40 and 25/50 indices, for instance): a
    capped constituent sits exactly at the cap and the others keep their
    proportions among themselves.
    """
    if cap * len(weights) < 1.0 - 1e-12:
        raise ValueError(f"a cap of {cap:.0%} cannot hold {len(weights)} constituents summing to one")
    capped: dict[str, float] = {}
    free = dict(weights)
    while True:
        budget = 1.0 - cap * len(capped)
        total = sum(free.values())
        scaled = {name: value / total * budget for name, value in free.items()}
        over = {name for name, value in scaled.items() if value > cap + 1e-12}
        if not over:
            return {**dict.fromkeys(capped, cap), **scaled}
        for name in over:
            capped[name] = cap
            del free[name]


@dataclass(frozen=True)
class CappedComparison:
    months: tuple[date, ...]
    market: np.ndarray  # monthly returns of the cap-weighted market (rebuilt)
    capped: np.ndarray  # monthly returns of the capped index
    binding: np.ndarray  # whether the cap bound that month
    turnover: np.ndarray  # one-way turnover of each month's rebalance, capped index

    @property
    def tracking_error(self) -> float:
        return float(np.std(self.capped - self.market, ddof=1) * math.sqrt(12))

    def annual(self, rates: np.ndarray) -> float:
        return float(np.prod(1.0 + rates) ** (12.0 / len(rates)) - 1.0)

    @property
    def months_binding(self) -> int:
        return int(self.binding.sum())

    def growth(self) -> tuple[float, float]:
        return float(np.prod(1.0 + self.market)), float(np.prod(1.0 + self.capped))


@lru_cache(maxsize=1)
def capped_comparison(cap: float = CAP) -> CappedComparison:
    history = french_history()
    market, capped, binding, turnover = [], [], [], []
    held: dict[str, float] | None = None
    for month in history.months:
        weights = history.weights(month)
        target = cap_weights(weights, cap)
        data = history.data[month]
        if held is not None:
            turnover.append(0.5 * sum(abs(target[name] - held.get(name, 0.0)) for name in target))
        else:
            turnover.append(0.0)
        market.append(sum(weights[name] * data[name].value_weighted for name in weights))
        capped.append(sum(target[name] * data[name].value_weighted for name in target))
        binding.append(max(weights.values()) > cap + 1e-12)
        # weights drift with the month's returns before the next rebalance
        grown = {name: target[name] * (1.0 + data[name].value_weighted) for name in target}
        total = sum(grown.values())
        held = {name: value / total for name, value in grown.items()}
    return CappedComparison(history.months, np.array(market), np.array(capped), np.array(binding), np.array(turnover))
