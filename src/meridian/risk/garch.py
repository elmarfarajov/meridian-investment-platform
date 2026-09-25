"""GARCH(1,1) against EWMA: forecasting the volatility of one factor.

EWMA is a GARCH(1,1) with no mean reversion: ``s2' = (1 - lambda) r^2 + lambda s2``.
GARCH adds a long-run variance the forecast is pulled back towards,
``s2' = omega + alpha r^2 + beta s2``, which matters after a spike - EWMA
forgets the crisis at its fixed rate, GARCH knows volatility tends to come back
to normal. The price is three parameters estimated by maximum likelihood,
which need years of data and can wander.

The model is fitted with the ``arch`` package (Student-t innovations), refitted
every month on the trailing four years, and filtered forward day by day with
the latest parameters in between - the way a production system would run it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from arch import arch_model

from ..core.exceptions import ValidationError

FIT_WINDOW = 1000
REFIT_EVERY = 21
SCALE = 100.0  # arch is best conditioned on returns in percent


@dataclass(frozen=True)
class GarchFit:
    omega: float  # daily variance units
    alpha: float
    beta: float
    dof: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def long_run_volatility(self) -> float:
        """Annualised unconditional volatility, omega / (1 - alpha - beta)."""
        if self.persistence >= 1:
            return math.inf
        return math.sqrt(self.omega / (1 - self.persistence) * 252)


def fit_garch(returns: np.ndarray) -> GarchFit:
    """Maximum-likelihood GARCH(1,1) with Student-t innovations and zero mean."""
    if len(returns) < 250:
        raise ValidationError("a GARCH fit needs at least a year of daily returns")
    model = arch_model(returns * SCALE, mean="Zero", vol="GARCH", p=1, q=1, dist="t", rescale=False)
    result = model.fit(disp="off", show_warning=False)
    params = result.params
    return GarchFit(
        float(params["omega"]) / SCALE**2, float(params["alpha[1]"]), float(params["beta[1]"]), float(params["nu"])
    )


def garch_forecasts(
    returns: np.ndarray, *, start: int = FIT_WINDOW, refit_every: int = REFIT_EVERY
) -> tuple[np.ndarray, list[GarchFit]]:
    """One-day-ahead volatility forecasts from ``start`` on (NaN before), and the fits used."""
    forecasts = np.full(len(returns), np.nan)
    fits: list[GarchFit] = []
    fit: GarchFit | None = None
    variance = float(np.var(returns[:start]))
    for day in range(1, len(returns)):
        if day >= start and (fit is None or (day - start) % refit_every == 0):
            fit = fit_garch(returns[max(0, day - FIT_WINDOW) : day])
            fits.append(fit)
        if fit is not None:
            variance = fit.omega + fit.alpha * returns[day - 1] ** 2 + fit.beta * variance
            forecasts[day] = math.sqrt(variance)
        else:
            variance = 0.94 * variance + 0.06 * returns[day - 1] ** 2  # warm the state before the first fit
    return forecasts, fits


def ewma_forecasts(returns: np.ndarray, half_life: float) -> np.ndarray:
    """One-day-ahead EWMA volatility forecasts (NaN on the first day)."""
    lam = 0.5 ** (1.0 / half_life)
    forecasts = np.full(len(returns), np.nan)
    state, weight = 0.0, 0.0
    for day in range(1, len(returns)):
        state = lam * state + (1 - lam) * returns[day - 1] ** 2
        weight = lam * weight + (1 - lam)
        forecasts[day] = math.sqrt(state / weight)
    return forecasts


def rolling_forecasts(returns: np.ndarray, window: int = 252) -> np.ndarray:
    """Equal-weighted forecasts over the trailing window (NaN until it is full)."""
    forecasts = np.full(len(returns), np.nan)
    squares = np.concatenate([[0.0], np.cumsum(returns**2)])
    for day in range(window, len(returns)):
        forecasts[day] = math.sqrt((squares[day] - squares[day - window]) / window)
    return forecasts
