"""Estimating the model's history: exposures every month, a regression every day.

The output is what a risk vendor delivers each night - factor returns, specific
returns and exposures - from which covariance forecasts are built. Style
exposures are recomputed at the start of each month from the descriptors known
then; industries do not change; currency returns are observed, not estimated.
The first year of the history is spent measuring the first betas and momentum,
so estimation starts one year after the universe does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .exposures import BETA_WINDOW, ExposureMatrix, compute_descriptors, exposures_from
from .factors import CURRENCIES, FactorSet, currency_factor
from .regression import regress
from .universe import UniverseHistory


@dataclass
class FactorReturnHistory:
    """Factor returns, specific returns and exposures, day by day."""

    days: tuple[date, ...]
    first_index: int  # grid index of days[0] in the universe
    factors: FactorSet
    returns: np.ndarray  # T x K, local factors then currencies
    specific: np.ndarray  # T x N
    r_squared: np.ndarray  # T
    t_stats: np.ndarray  # T x K_local
    exposures: dict[int, ExposureMatrix]  # keyed by month start index in the universe
    exposure_month: np.ndarray  # T: the month-start key in force on each day

    def factor(self, name: str) -> np.ndarray:
        return self.returns[:, self.factors.index(name)]

    def exposure_on(self, position: int) -> ExposureMatrix:
        return self.exposures[int(self.exposure_month[position])]

    def position(self, day: date) -> int:
        return self.days.index(day)


def estimate(history: UniverseHistory, *, start_index: int = BETA_WINDOW) -> FactorReturnHistory:
    """Run the monthly exposures and daily regressions over the universe."""
    factor_set = FactorSet.standard()
    local_log = np.log1p(history.local_returns)
    sectors = [stock.sector for stock in history.stocks]
    stock_ids = history.stock_ids
    exposures: dict[int, ExposureMatrix] = {}
    for month, first in enumerate(history.month_starts):
        if first < start_index - 21:
            continue
        caps = history.caps[max(first - 1, 0)]
        descriptors = compute_descriptors(
            local_log, history.caps, history.book_to_price[month], history.return_on_equity[month], max(first, 1)
        )
        exposures[first] = exposures_from(history.days[first], stock_ids, descriptors, sectors, caps)

    starts = np.array(sorted(exposures))
    days = history.days[start_index:]
    count = len(days)
    local_count = len(factor_set.local)
    returns = np.zeros((count, len(factor_set)))
    specific = np.zeros((count, len(stock_ids)))
    r_squared = np.zeros(count)
    t_stats = np.zeros((count, local_count))
    month_key = np.zeros(count, dtype=int)
    for position, grid_index in enumerate(range(start_index, len(history.days))):
        key = int(starts[np.searchsorted(starts, grid_index, side="right") - 1])
        matrix = exposures[key]
        caps = history.caps[grid_index - 1]
        section = regress(history.local_returns[grid_index], matrix.world, matrix.industries, matrix.styles, caps)
        returns[position, :local_count] = section.factor_returns
        specific[position] = section.residuals
        r_squared[position] = section.r_squared
        t_stats[position] = section.t_stats
        month_key[position] = key
    for offset, code in enumerate(CURRENCIES):
        returns[:, local_count + offset] = history.fx_returns[code][start_index:]
        assert factor_set.names[local_count + offset] == currency_factor(code)
    return FactorReturnHistory(
        days=days,
        first_index=start_index,
        factors=factor_set,
        returns=returns,
        specific=specific,
        r_squared=r_squared,
        t_stats=t_stats,
        exposures=exposures,
        exposure_month=month_key,
    )
