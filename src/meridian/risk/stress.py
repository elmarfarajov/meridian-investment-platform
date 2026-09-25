"""Stress tests: what today's portfolio would lose if a bad week happened again.

VaR describes an ordinary bad day; a stress test asks about a specific
extraordinary one. Two kinds are run against the portfolio's current factor
exposures:

* **Historical replays** - the factor returns of a past crisis window,
  compounded, applied to today's exposures: "if February 2020 happened to this
  portfolio".
* **Hypothetical shocks** - a move chosen by the risk committee, specified on a
  few factors: a 20% fall in world equities, a sharp rotation from momentum
  into value, a dollar rally.

Stock-specific returns are left out: a stress test is about the systematic
exposures a portfolio has chosen, and specific returns in a replayed window
would be those of other stocks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np

from ..core.exceptions import ValidationError
from .estimation import FactorReturnHistory
from .factors import CURRENCIES, FactorSet, currency_factor, group_of


@dataclass(frozen=True)
class Scenario:
    name: str
    kind: str  # "historical" or "hypothetical"
    shocks: dict[str, float]  # factor -> return over the scenario
    description: str = ""
    start: date | None = None
    end: date | None = None


@dataclass(frozen=True)
class StressResult:
    scenario: Scenario
    portfolio: float
    benchmark: float
    by_group: dict[str, float]  # portfolio P&L by factor group

    @property
    def active(self) -> float:
        return self.portfolio - self.benchmark


def historical_scenario(
    history: FactorReturnHistory, name: str, start: date, end: date, description: str = ""
) -> Scenario:
    """The factors' compounded returns over a past window."""
    chosen = [index for index, day in enumerate(history.days) if start <= day <= end]
    if not chosen:
        raise ValidationError(f"no factor returns between {start} and {end}")
    compounded = np.prod(1.0 + history.returns[chosen], axis=0) - 1.0
    shocks = {factor: float(value) for factor, value in zip(history.factors.names, compounded, strict=True)}
    return Scenario(name, "historical", shocks, description, history.days[chosen[0]], history.days[chosen[-1]])


def hypothetical_scenarios() -> list[Scenario]:
    dollar_rally = {currency_factor(code): -0.08 for code in CURRENCIES}
    return [
        Scenario(
            "Equities -20%", "hypothetical", {"World": -0.20}, "A fall of a fifth in world equities, nothing else"
        ),
        Scenario(
            "Value rotation",
            "hypothetical",
            {"Value": 0.06, "Momentum": -0.10, "Information Technology": -0.05},
            "Last year's winners sold for cheap stocks, as in November 2020",
        ),
        Scenario("Dollar rally", "hypothetical", dollar_rally, "Every currency falls 8% against the dollar"),
        Scenario(
            "Tech sell-off",
            "hypothetical",
            {"World": -0.05, "Information Technology": -0.15, "Momentum": -0.04},
            "Technology falls 15% relative to a market down 5%",
        ),
        Scenario(
            "Flight to quality",
            "hypothetical",
            {"World": -0.10, "Quality": 0.03, "Beta": -0.06, "Size": 0.02},
            "Markets fall a tenth, high-beta stocks most, profitable large companies least",
        ),
    ]


def apply(scenario: Scenario, factors: FactorSet, portfolio: np.ndarray, benchmark: np.ndarray) -> StressResult:
    """P&L of a scenario for portfolio and benchmark factor exposures (fractions of value)."""
    shocks = np.array([scenario.shocks.get(name, 0.0) for name in factors.names])
    by_group: dict[str, float] = {}
    for index, name in enumerate(factors.names):
        by_group[group_of(name)] = by_group.get(group_of(name), 0.0) + float(portfolio[index] * shocks[index])
    return StressResult(scenario, float(portfolio @ shocks), float(benchmark @ shocks), by_group)


def run_all(
    scenarios: list[Scenario], factors: FactorSet, portfolio: np.ndarray, benchmark: np.ndarray
) -> list[StressResult]:
    return [apply(scenario, factors, portfolio, benchmark) for scenario in scenarios]


def scenario_table(results: list[StressResult]) -> list[Mapping[str, object]]:
    return [
        {
            "scenario": result.scenario.name,
            "kind": result.scenario.kind,
            "portfolio": result.portfolio,
            "benchmark": result.benchmark,
            "active": result.active,
        }
        for result in results
    ]
