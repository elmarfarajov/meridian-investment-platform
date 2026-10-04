"""Value at risk and expected shortfall, four ways.

VaR at 99% is the loss exceeded on one day in a hundred; expected shortfall
(ES) is the average loss on those days. ES is the measure Basel's Fundamental
Review of the Trading Book adopted at 97.5%, because VaR says nothing about how
bad the bad days are, and because ES is sub-additive - diversification never
increases it.

* **Parametric (normal).** ``z * sigma`` from the model's forecast volatility.
  Fast and forward-looking, and too thin in the tails.
* **Cornish-Fisher.** The normal quantile corrected for the skewness and excess
  kurtosis of the portfolio's own history.
* **Historical simulation.** Today's weights applied to each of the last N days'
  returns: fat tails for free, but backward-looking and slow to react.
* **Monte Carlo from the factor model.** Factor returns drawn from a
  multivariate Student-t with the model's covariance, specific returns from
  Student-t with each asset's specific variance: forward-looking *and* fat
  tailed.

All figures are losses, positive numbers, as a fraction of the portfolio's value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

from ..core.exceptions import ValidationError

TAIL_DOF = 5.0


@dataclass(frozen=True)
class RiskEstimate:
    method: str
    confidence: float
    var: float
    es: float


def parametric(sigma: float, confidence: float = 0.99, mean: float = 0.0) -> RiskEstimate:
    if sigma < 0:
        raise ValidationError("volatility cannot be negative")
    quantile = float(stats.norm.ppf(confidence))
    var = quantile * sigma - mean
    es = sigma * float(stats.norm.pdf(quantile)) / (1 - confidence) - mean
    return RiskEstimate("Parametric (normal)", confidence, var, es)


def cornish_fisher(sigma: float, skewness: float, excess_kurtosis: float, confidence: float = 0.99) -> RiskEstimate:
    """The Cornish-Fisher expansion of the quantile; ES by averaging the expanded quantiles in the tail.

    The expansion is a polynomial in the normal quantile, and for large enough
    skewness or kurtosis it stops being increasing: a more extreme probability
    then maps to a *smaller* loss, and the "quantile" is no quantile at all
    (Maillard, 2012). The function checks the expansion is increasing across the
    tail it uses and refuses to answer where it is not.
    """

    def expanded(z: np.ndarray) -> np.ndarray:
        return (
            z
            + (z**2 - 1) * skewness / 6
            + (z**3 - 3 * z) * excess_kurtosis / 24
            - (2 * z**3 - 5 * z) * skewness**2 / 36
        )

    z = float(stats.norm.ppf(1 - confidence))
    tail = (1 - confidence) * (np.arange(200) + 0.5) / 200  # midpoints of the tail's probability slices
    grid = stats.norm.ppf(np.concatenate([tail, [1 - confidence]]))
    values = expanded(grid)
    if np.any(np.diff(values) <= 0):
        raise ValidationError(
            f"skewness {skewness:.2f} and excess kurtosis {excess_kurtosis:.2f} are outside the domain where the "
            "Cornish-Fisher expansion is monotone; its quantile is not a quantile"
        )
    var = -float(expanded(np.array(z))) * sigma
    es = -float(np.mean(values[:-1])) * sigma
    return RiskEstimate("Cornish-Fisher", confidence, var, max(es, var))


def historical(returns: np.ndarray, confidence: float = 0.99) -> RiskEstimate:
    """Empirical quantile of the losses (linear interpolation) and the mean loss beyond it."""
    losses = -np.asarray(returns, dtype=float)
    losses = losses[np.isfinite(losses)]
    if len(losses) < 20:
        raise ValidationError("historical simulation needs at least twenty scenarios")
    var = float(np.quantile(losses, confidence))
    tail = losses[losses >= var]
    return RiskEstimate("Historical simulation", confidence, var, float(tail.mean()))


def monte_carlo(
    exposures: np.ndarray,
    factor_covariance: np.ndarray,
    specific_variance: np.ndarray,
    weights: np.ndarray,
    *,
    confidence: float = 0.99,
    draws: int = 50_000,
    dof: float = TAIL_DOF,
    seed: int = 20260925,
) -> tuple[RiskEstimate, np.ndarray]:
    """Simulate one day of portfolio returns from the factor model with Student-t shocks.

    Multivariate t draws are a Gaussian vector with the model's covariance
    divided by a common chi-squared scale, rescaled so the covariance is the
    model's: in a crash every factor is hit at once, which independent t draws
    would miss.

    Specific returns are drawn independently for every asset held, each a
    Student-t scaled to its own specific variance, and summed with the weights.
    The sum of independent fat-tailed shocks is less fat-tailed than any one of
    them - diversification thins the specific tail - so a single t draw for the
    whole portfolio's specific risk would overstate it.
    """
    rng = np.random.default_rng(seed)
    size = factor_covariance.shape[0]
    chol = np.linalg.cholesky(factor_covariance + 1e-18 * np.eye(size))
    scale = math.sqrt((dof - 2.0) / dof)
    mixing = np.sqrt(dof / rng.chisquare(dof, draws))
    factor_draws = (rng.standard_normal((draws, size)) @ chol.T) * (mixing * scale)[:, None]
    portfolio_exposure = exposures.T @ weights
    systematic = factor_draws @ portfolio_exposure
    held = np.flatnonzero(weights)
    loadings = weights[held] * np.sqrt(specific_variance[held]) * scale
    idiosyncratic = np.zeros(draws)
    for start in range(0, len(held), 64):  # in blocks, so a large book does not build a draws x N matrix at once
        block = loadings[start : start + 64]
        idiosyncratic += rng.standard_t(dof, (draws, len(block))) @ block
    simulated = systematic + idiosyncratic
    estimate = historical(simulated, confidence)
    return RiskEstimate("Monte Carlo (factor model, t)", confidence, estimate.var, estimate.es), simulated


def scale_horizon(estimate: RiskEstimate, days: int) -> RiskEstimate:
    """Square-root-of-time scaling: exact for i.i.d. normal returns, an approximation otherwise."""
    factor = math.sqrt(days)
    return RiskEstimate(
        f"{estimate.method}, {days}-day", estimate.confidence, estimate.var * factor, estimate.es * factor
    )
