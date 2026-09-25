"""The experiment that shows why a raw sample covariance is unusable.

An optimiser is an error maximiser: asked for the portfolio of least risk, it
finds the directions in which the covariance estimate is most *underestimated*
and loads up on them. The fairest test of an estimator is therefore not how
close its entries are to the truth but what happens to the portfolio an
optimiser builds from it.

At the end of every month, each estimator is given the last 252 days of dollar
returns of all five hundred stocks, the fully invested minimum-variance
portfolio is built from it, and two numbers are recorded: the volatility the
estimator *promised* for that portfolio, and the volatility the portfolio then
*delivered* over the following month. A good estimator promises what it
delivers, and delivers little.

With 500 stocks and 252 days the sample covariance is singular (rank 251), so
it promises a portfolio of almost no risk; the pseudo-inverse still produces
weights, and they deliver many times what was promised. Shrinkage repairs most
of that; a factor model, which never estimates 125,250 free parameters, repairs
the rest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from .covariance import (
    factor_minimum_variance_weights,
    ledoit_wolf,
    ledoit_wolf_constant_correlation,
    minimum_variance_weights,
    riskless_portfolio,
    sample_covariance,
)
from .forecast import RollingForecaster
from .universe import UniverseHistory

ESTIMATORS: tuple[str, ...] = ("Sample", "Ledoit-Wolf (identity)", "Ledoit-Wolf (constant correlation)", "Factor model")
WINDOW = 252
HOLDING = 21


@dataclass(frozen=True)
class Trial:
    day: date
    estimator: str
    promised: float  # annualised volatility the estimator forecast
    delivered: float  # annualised realised volatility over the next month
    gross: float  # sum of absolute weights: how extreme the portfolio is


@dataclass(frozen=True)
class EstimatorSummary:
    estimator: str
    promised: float
    delivered: float
    ratio: float  # delivered / promised
    gross: float


def minimum_variance_trials(
    history: UniverseHistory, forecaster: RollingForecaster, *, every: int = 1, limit: int | None = None
) -> list[Trial]:
    """Run the experiment at every ``every``-th month-end with enough history before and after."""
    usd = history.usd_returns
    first_index = forecaster.estimated.first_index
    trials: list[Trial] = []
    candidates = [
        start
        for start in history.month_starts
        if start - first_index > 130 and start >= WINDOW and start + HOLDING <= len(history.days)
    ][::every]
    if limit is not None:
        candidates = candidates[:limit]
    for start in candidates:
        window = usd[start - WINDOW : start]
        future = usd[start : start + HOLDING]
        sample = sample_covariance(window)
        estimates = {
            "Sample": sample,
            "Ledoit-Wolf (identity)": ledoit_wolf(window).covariance,
            "Ledoit-Wolf (constant correlation)": ledoit_wolf_constant_correlation(window).covariance,
        }
        model = forecaster.model(start - first_index)
        exposures = model.exposure_matrix(history.stock_ids)
        specific = np.array([model.specific_variance[stock] for stock in history.stock_ids])
        for name in ESTIMATORS:
            if name == "Factor model":
                weights = factor_minimum_variance_weights(exposures, model.factor_covariance, specific)
                variance = float(
                    weights @ exposures @ model.factor_covariance @ exposures.T @ weights + specific @ weights**2
                )
            else:
                covariance = estimates[name]
                riskless = riskless_portfolio(covariance) if name == "Sample" else None
                weights = riskless if riskless is not None else minimum_variance_weights(covariance)
                variance = 0.0 if riskless is not None else float(weights @ covariance @ weights)
            promised = math.sqrt(max(variance, 0.0) * 252)
            delivered = float(np.std(future @ weights, ddof=1)) * math.sqrt(252)
            trials.append(Trial(history.days[start], name, promised, delivered, float(np.abs(weights).sum())))
    return trials


def summarise(trials: list[Trial]) -> list[EstimatorSummary]:
    rows = []
    for name in ESTIMATORS:
        chosen = [trial for trial in trials if trial.estimator == name]
        if not chosen:
            continue
        promised = float(np.mean([trial.promised for trial in chosen]))
        delivered = float(np.mean([trial.delivered for trial in chosen]))
        rows.append(
            EstimatorSummary(
                name,
                promised,
                delivered,
                delivered / promised if promised > 0 else math.inf,
                float(np.mean([trial.gross for trial in chosen])),
            )
        )
    return rows


def eigenvalue_spectrum(history: UniverseHistory, end: int, window: int = WINDOW) -> tuple[np.ndarray, float]:
    """Eigenvalues of the sample *correlation* matrix of the universe over a window, and q = N / T."""
    data = history.usd_returns[end - window : end]
    correlation = np.corrcoef(data, rowvar=False)
    return np.sort(np.linalg.eigvalsh(correlation))[::-1], data.shape[1] / window
