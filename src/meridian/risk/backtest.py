"""One-day VaR forecasts for a single return series, every day, using only what was known the evening before.

Four forecasters, the ones a market-risk function would put side by side:

* **Normal with EWMA volatility** - RiskMetrics (1996): ``s2' = lambda s2 + (1 - lambda) r^2``
  with lambda 0.94, and the normal quantile. The industry's reference point.
* **Historical simulation** - the empirical quantile of the last 500 returns.
  Fat tails for free; blind to a change in volatility until it is in the window,
  and then for 500 days afterwards.
* **Filtered historical simulation** - Barone-Adesi, Giannopoulos and Vosper
  (1999): the last 500 returns divided by the EWMA volatility of their own day,
  their empirical quantile scaled by today's volatility. The tails of history,
  the volatility of now.
* **GARCH(1,1) with Student-t innovations** - refitted once a year on the
  trailing four years with ``arch``, filtered forward daily; the t quantile scaled
  to unit variance.

Each function returns the VaR as a positive loss for every day, NaN until the
forecaster has the history it needs, so that day ``t``'s forecast uses returns up
to ``t - 1`` only.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .garch import fit_garch, garch_filter

RISKMETRICS_LAMBDA = 0.94
HISTORY_WINDOW = 500
GARCH_WINDOW = 1000
GARCH_REFIT = 252


def ewma_volatility(returns: np.ndarray, decay: float = RISKMETRICS_LAMBDA, warm_up: int = 60) -> np.ndarray:
    """Day ``t``'s EWMA volatility forecast from returns before ``t``; seeded with the first ``warm_up`` days."""
    forecasts = np.full(len(returns), np.nan)
    variance = float(np.mean(returns[:warm_up] ** 2))
    for day in range(warm_up, len(returns)):
        forecasts[day] = math.sqrt(variance)
        variance = decay * variance + (1.0 - decay) * returns[day] ** 2
    return forecasts


def normal_var(returns: np.ndarray, confidence: float = 0.99, decay: float = RISKMETRICS_LAMBDA) -> np.ndarray:
    return float(stats.norm.ppf(confidence)) * ewma_volatility(returns, decay)


def historical_var(returns: np.ndarray, confidence: float = 0.99, window: int = HISTORY_WINDOW) -> np.ndarray:
    forecasts = np.full(len(returns), np.nan)
    for day in range(window, len(returns)):
        forecasts[day] = -float(np.quantile(returns[day - window : day], 1.0 - confidence))
    return forecasts


def filtered_historical_var(
    returns: np.ndarray, confidence: float = 0.99, window: int = HISTORY_WINDOW, decay: float = RISKMETRICS_LAMBDA
) -> np.ndarray:
    volatility = ewma_volatility(returns, decay)
    standardised = returns / volatility
    forecasts = np.full(len(returns), np.nan)
    for day in range(window + 60, len(returns)):
        quantile = float(np.quantile(standardised[day - window : day], 1.0 - confidence))
        forecasts[day] = -quantile * volatility[day]
    return forecasts


def garch_var(
    returns: np.ndarray, confidence: float = 0.99, window: int = GARCH_WINDOW, refit_every: int = GARCH_REFIT
) -> tuple[np.ndarray, np.ndarray, list[tuple[int, float, float, float]]]:
    """GARCH-t VaR, the volatility forecast behind it, and each refit as (day, alpha, beta, degrees of freedom)."""
    forecasts = np.full(len(returns), np.nan)
    volatility = np.full(len(returns), np.nan)
    fits: list[tuple[int, float, float, float]] = []
    variance = float(np.var(returns[:window]))
    for day in range(1, window):  # warm the state with RiskMetrics until the first fit
        variance = RISKMETRICS_LAMBDA * variance + (1 - RISKMETRICS_LAMBDA) * returns[day - 1] ** 2
    for start in range(window, len(returns), refit_every):
        stop = min(start + refit_every, len(returns))
        fit = fit_garch(returns[start - window : start])
        fits.append((start, fit.alpha, fit.beta, fit.dof))
        dof = max(fit.dof, 2.05)
        quantile = -float(stats.t.ppf(1.0 - confidence, dof)) * math.sqrt((dof - 2.0) / dof)
        segment = garch_filter(returns[start:stop], fit, variance, returns[start - 1] ** 2)
        volatility[start:stop] = segment
        forecasts[start:stop] = quantile * segment
        variance = float(segment[-1] ** 2)
    return forecasts, volatility, fits
