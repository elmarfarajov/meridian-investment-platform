"""Tax-loss harvesting through a century of the US market.

Day 7 measured tax alpha on markets simulated from a factor model. Here the four
managers of :mod:`..optimisation.backtest` run through history: Kenneth French's
twelve industries (``marketdata.french``), one decade at a time, from the 1930s
to the 2020s, under today's tax code.

- **The universe** is the twelve industries, held as an investor holds sector
  funds. Each price is the industry's cumulative value-weighted return.
- **The index** is the market's own weighting. Each month end the target is
  each industry's share of the market's value then: drift plus the firms that
  listed, merged and failed. That reconstitution is what forces an indexer to
  trade.
- **The risk model** is the industries' covariance over the 60 months before the
  decade starts (the 54 there are, for the 1930s). It is known on the first day and held fixed, so nothing is
  looked up in the future.
- **The tax code** is today's: 37% and 20% plus the 3.8% net investment income
  tax, $3,000 of ordinary income, and 30-day wash sales. The client realises
  short-term gains elsewhere, 2% of the account a year, which harvested losses
  offset.

Two simplifications, the same for every manager. The returns include
dividends, treated as reinvested untaxed, so the gains standing in an account
are larger than a taxed investor's. And twelve industries are far less dispersed
than the thousands of stocks a direct-indexing account holds, so the losses to
harvest here are the market's and the sectors', not single stocks'. What this
measures is when harvesting pays, decade by decade, not how much a stock-level
account would add.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np

from ..marketdata.french import FrenchHistory, french_history
from ..optimisation.backtest import TRADING_DAYS_PER_MONTH, Market, PathOutcome, SimulationConfig, TaxAlphaBacktest
from ..optimisation.rebalance import RiskView

ESTIMATION_MONTHS = 60
MINIMUM_MONTHS = 36
WINDOW_YEARS = 10
#: the first day of each decade's backtest: the last month end before it
DECADES: tuple[date, ...] = tuple(date(year - 1, 12, 31) for year in range(1931, 2021, 10))
LATEST = date(2015, 12, 31)  # the ten years to December 2025, overlapping the 2010s


@dataclass(frozen=True)
class Window:
    start: date  # the month end the account is funded
    end: date
    market: Market
    risk: RiskView

    @property
    def label(self) -> str:
        return f"{self.start.year + 1}-{self.end.year}"


def returns_matrix(history: FrenchHistory, months: tuple[date, ...]) -> np.ndarray:
    return np.array([[history.data[month][name].value_weighted for name in history.industries] for month in months])


def risk_view(history: FrenchHistory, start: date, benchmark: np.ndarray) -> RiskView:
    """The industries' covariance over the 60 months to ``start`` (36 at least), daily, with no specific risk."""
    months = tuple(month for month in history.months if month <= start)[-ESTIMATION_MONTHS:]
    if len(months) < MINIMUM_MONTHS:
        raise ValueError(f"{start}: needs {MINIMUM_MONTHS} months of history before it")
    covariance = np.cov(returns_matrix(history, months), rowvar=False) / TRADING_DAYS_PER_MONTH
    n = len(history.industries)
    return RiskView(
        keys=history.industries,
        exposures=np.eye(n),
        factor_covariance=covariance,
        specific=np.full(n, 1e-10),
        benchmark=benchmark,
    )


def window(start: date, years: int = WINDOW_YEARS, history: FrenchHistory | None = None) -> Window:
    """``years`` of history from the month end ``start``: the market and the risk model known on that day."""
    history = history or french_history()
    end = date(start.year + years, 12, 31) if start.month == 12 else date(start.year + years, start.month, start.day)
    months = tuple(month for month in history.months if start < month <= end)
    following = tuple(month for month in history.months if month > end)
    # the target at each month end is the market's weighting at the start of the next month
    target_months = (*months, following[0]) if following else months
    targets = np.array([[history.weights(month)[name] for name in history.industries] for month in target_months])
    returns = returns_matrix(history, months)
    if not following:  # the last month end of the data: the weights the month's returns drifted to
        drifted = targets[-1] * (1 + returns[-1])
        targets = np.vstack([targets, drifted / drifted.sum()])
    risk = risk_view(history, start, targets[0])
    volatility = np.sqrt(np.diag(risk.factor_covariance))
    market = Market.from_history(history.industries, [start, *months], returns, targets, volatility)
    return Window(start, months[-1], market, risk)


#: a sector fund's account: funded once, the spread of a liquid ETF, volume no trade could move
CONFIG = SimulationConfig(nav=5_000_000.0, daily_volume=5_000_000_000.0, spread_bps=2.0)


def run_window(item: Window, progress: Callable[[str], None] | None = None) -> PathOutcome:
    return TaxAlphaBacktest(item.risk, CONFIG).run_market(item.market, progress=progress)


@dataclass(frozen=True)
class DecadeResult:
    """One decade, four managers: returns before and after tax, and how much of the difference is tax."""

    label: str
    start: date
    end: date
    outcome: PathOutcome

    @property
    def months(self) -> int:
        return len(self.outcome.days) - 1

    def _annual(self, growth: float) -> float:
        return float(growth ** (12 / self.months) - 1)

    def index_return(self) -> float:
        return self._annual(float(np.prod(1 + self.outcome.index_returns)))

    def pre_tax(self, strategy: str) -> float:
        """Annual time-weighted return before tax, trading costs included."""
        return self._annual(self.outcome[strategy].pre_tax_growth)

    def after_tax(self, strategy: str) -> float:
        """Annual return after tax, on liquidation at the end (every remaining gain taxed)."""
        return self._annual(self.outcome[strategy].liquidation_value / CONFIG.nav)

    def tax_drag(self, strategy: str) -> float:
        return self.pre_tax(strategy) - self.after_tax(strategy)

    def tax_share(self, strategy: str) -> float:
        """The share of the pre-tax return that tax took."""
        return self.tax_drag(strategy) / self.pre_tax(strategy)

    def tax_saved(self, strategy: str, against: str = "tax-blind") -> float:
        """Tax alpha: the drag avoided against ``against``, tracking luck apart."""
        return self.tax_drag(against) - self.tax_drag(strategy)

    def tracking_difference(self, strategy: str, against: str = "tax-blind") -> float:
        """The pre-tax return over ``against``: what the trades that saved tax did to the return itself."""
        return self.pre_tax(strategy) - self.pre_tax(against)

    def harvested(self, strategy: str) -> float:
        """Losses realised over the decade, as a share of the starting value."""
        return self.outcome[strategy].harvested / CONFIG.nav

    def tracking_error(self, strategy: str) -> float:
        """Realised: the annualised standard deviation of the monthly return over the index's."""
        return float(np.std(self.outcome.active_returns(strategy), ddof=1) * np.sqrt(12))


@lru_cache(maxsize=1)
def decades() -> tuple[DecadeResult, ...]:
    """The four managers through each decade since 1931, and through the ten years to 2025."""
    history = french_history()
    results = []
    for start in (*DECADES, LATEST):
        item = window(start, history=history)
        results.append(DecadeResult(item.label, item.start, item.end, run_window(item)))
    return tuple(results)
