"""The model run forward in time: every evening a forecast, every next day an outcome.

A backtest of a risk model has to be honest about time. On each day the
forecaster may use factor and specific returns up to the previous close and the
exposures known that morning; the day's return is then compared with the
forecast. :class:`RollingForecaster` does exactly that, recursively, so a ten
year backtest over five hundred stocks takes seconds.

Three covariance forecasters are run side by side:

* **EWMA** - the production choice: half-life 42 days for volatilities and 200
  for correlations, specific risk by EWMA on a 63-day half-life.
* **Sample** - equal weights over the last 252 days, the textbook estimator.
* **Truth** - the generator's own conditional covariance, available only
  because the universe is synthetic: the best any forecaster could do.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .covariance import CORRELATION_HALF_LIFE, SAMPLE_WINDOW, VOL_HALF_LIFE, EwmaState
from .estimation import FactorReturnHistory
from .factors import FactorSet
from .model import FactorRiskModel
from .specific import SPECIFIC_HALF_LIFE, SpecificRisk
from .universe import UniverseHistory

WARM_UP = 126  # days of factor returns before the first forecast is scored

WeightRule = Callable[[int], np.ndarray]  # universe grid index -> N weights


@dataclass
class ForecastTrack:
    """One portfolio's forecasts and outcomes, day by day."""

    name: str
    days: list[date] = field(default_factory=list)
    forecast: dict[str, list[float]] = field(default_factory=dict)  # method -> daily volatility
    realised: list[float] = field(default_factory=list)

    def standardised(self, method: str) -> np.ndarray:
        """Each day's outcome over its forecast: the z-scores a bias statistic is built from."""
        return np.asarray(self.realised) / np.asarray(self.forecast[method])


@dataclass
class SampleState:
    """An equal-weighted rolling window, updated by adding the new day and dropping the oldest."""

    window: int
    rows: list[np.ndarray] = field(default_factory=list)

    def update(self, row: np.ndarray) -> None:
        self.rows.append(np.nan_to_num(row))
        if len(self.rows) > self.window:
            self.rows.pop(0)

    def covariance(self) -> np.ndarray:
        data = np.vstack(self.rows)
        return data.T @ data / len(data)  # mean taken as zero, as in the EWMA

    def variances(self) -> np.ndarray:
        data = np.vstack(self.rows)
        return np.mean(data**2, axis=0)


class RollingForecaster:
    """Runs the factor model forward over an estimated history."""

    def __init__(
        self,
        history: UniverseHistory,
        estimated: FactorReturnHistory,
        *,
        vol_half_life: float = VOL_HALF_LIFE,
        correlation_half_life: float = CORRELATION_HALF_LIFE,
        specific_half_life: float = SPECIFIC_HALF_LIFE,
    ) -> None:
        self.history = history
        self.estimated = estimated
        self.factors: FactorSet = estimated.factors
        self.currency = history.currency_matrix()
        self.ewma = EwmaState.start(len(self.factors), vol_half_life, correlation_half_life)
        self.sample = SampleState(SAMPLE_WINDOW)
        self.specific = SpecificRisk(len(history.stocks), specific_half_life)
        self.specific_sample = SampleState(SAMPLE_WINDOW)
        self.position = 0  # next row of the estimated history to absorb

    def full_exposures(self, position: int) -> np.ndarray:
        """N x K exposures in force on a day: local factors from the monthly matrix, currencies one-hot."""
        matrix = self.estimated.exposure_on(position)
        return np.column_stack([matrix.local(), self.currency])

    def absorb(self, position: int) -> None:
        """Add one day's factor and specific returns to the estimators."""
        self.ewma.update(self.estimated.returns[position])
        self.sample.update(self.estimated.returns[position])
        self.specific.update(self.estimated.specific[position])
        self.specific_sample.update(self.estimated.specific[position])

    def model(self, position: int, method: str = "ewma") -> FactorRiskModel:
        """The model as it stood on the morning of ``position`` (after absorbing everything before it)."""
        self._advance_to(position)
        grid_index = self.estimated.first_index + position
        caps = self.history.caps[grid_index - 1]
        exposures = self.full_exposures(position)
        covariance, specific = self._estimates(method, caps)
        stock_ids = self.history.stock_ids
        return FactorRiskModel(
            as_of=self.estimated.days[position],
            factors=self.factors,
            factor_covariance=covariance,
            exposures={stock: exposures[row] for row, stock in enumerate(stock_ids)},
            specific_variance={stock: float(specific[row]) for row, stock in enumerate(stock_ids)},
            description=f"{method}: vol half-life {VOL_HALF_LIFE}d, correlation {CORRELATION_HALF_LIFE}d",
        )

    def factor_covariance(self, position: int, method: str = "ewma") -> np.ndarray:
        """The factor covariance forecast on the morning of ``position``."""
        self._advance_to(position)
        return self.ewma.covariance() if method == "ewma" else self.sample.covariance()

    def _advance_to(self, position: int) -> None:
        if position < self.position:
            raise ValueError("the forecaster only moves forward in time")
        while self.position < position:
            self.absorb(self.position)
            self.position += 1

    def _estimates(self, method: str, caps: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if method == "ewma":
            return self.ewma.covariance(), self.specific.variances(caps, shrink=False)
        if method == "sample":
            return self.sample.covariance(), self.specific_sample.variances()
        raise ValueError(f"unknown forecaster {method!r}")

    def run(
        self,
        portfolios: dict[str, WeightRule],
        *,
        methods: tuple[str, ...] = ("ewma", "sample", "truth"),
        start: int = WARM_UP,
    ) -> dict[str, ForecastTrack]:
        """Forecast each portfolio every day from ``start`` and record the outcome."""
        tracks = {name: ForecastTrack(name, forecast={method: [] for method in methods}) for name in portfolios}
        usd = self.history.usd_returns
        for position in range(start, len(self.estimated.days)):
            self._advance_to(position)
            grid_index = self.estimated.first_index + position
            caps = self.history.caps[grid_index - 1]
            exposures = self.full_exposures(position)
            weights = np.column_stack([rule(grid_index) for rule in portfolios.values()])  # N x P
            realised = usd[grid_index] @ weights
            x = exposures.T @ weights  # K x P
            variances: dict[str, np.ndarray] = {}
            for method in methods:
                if method == "truth":
                    variances[method] = self.history.true_variances(grid_index, weights)
                else:
                    covariance, specific = self._estimates(method, caps)
                    variances[method] = (
                        np.einsum("kp,kl,lp->p", x, covariance, x) + np.nan_to_num(specific) @ weights**2
                    )
            day = self.estimated.days[position]
            for column, name in enumerate(portfolios):
                track = tracks[name]
                track.days.append(day)
                track.realised.append(float(realised[column]))
                for method in methods:
                    track.forecast[method].append(math.sqrt(max(float(variances[method][column]), 1e-18)))
        return tracks

    def factor_z_scores(self, *, start: int = WARM_UP, method: str = "ewma") -> dict[str, np.ndarray]:
        """Each factor's return over its own forecast volatility, day by day."""
        state = EwmaState.start(len(self.factors), VOL_HALF_LIFE, CORRELATION_HALF_LIFE) if method == "ewma" else None
        sample = SampleState(SAMPLE_WINDOW)
        rows: list[np.ndarray] = []
        for position, row in enumerate(self.estimated.returns):
            if position >= start:
                variances = state.variances() if state is not None else sample.variances()
                rows.append(row / np.sqrt(np.maximum(variances, 1e-18)))
            if state is not None:
                state.update(row)
            sample.update(row)
        stacked = np.vstack(rows)
        return {name: stacked[:, index] for index, name in enumerate(self.factors.names)}

    def specific_z_scores(self, *, start: int = WARM_UP, shrink: bool = False) -> np.ndarray:
        """Every stock's specific return over its forecast specific volatility (T x N)."""
        risk = SpecificRisk(len(self.history.stocks))
        rows: list[np.ndarray] = []
        for position, row in enumerate(self.estimated.specific):
            if position >= start:
                caps = self.history.caps[self.estimated.first_index + position - 1]
                rows.append(row / np.sqrt(risk.variances(caps, shrink=shrink)))
            risk.update(row)
        return np.vstack(rows)
