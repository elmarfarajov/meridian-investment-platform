"""Covariance estimation, and why the obvious estimator fails.

**The sample covariance** of N assets from T days has N(N+1)/2 parameters. For
five hundred stocks that is 125,250 numbers, estimated from a year of 252 days:
the matrix has rank at most 251, so it is singular, and an optimiser asked for
the minimum-risk portfolio finds one that the sample says is nearly riskless
and that is in fact nothing of the sort. Random matrix theory says exactly how
wrong it is: when N/T = q, the eigenvalues of a sample correlation matrix of
*independent* returns spread over the Marchenko-Pastur interval
``[(1 - sqrt(q))^2, (1 + sqrt(q))^2]`` - for q = 2 far below zero on the left,
which is where the phantom riskless portfolios live.

Three remedies, used together in a factor model:

* **Structure.** A factor model estimates twenty-one factor covariances and
  five hundred specific variances instead of 125,250 free parameters.
* **Shrinkage.** Ledoit and Wolf's estimator pulls the sample covariance
  towards a structured target by the amount that minimises expected loss,
  computed from the data. Used here as the asset-level benchmark the factor
  model is compared against.
* **Exponential weighting.** Risk changes; a forecast built from equal weights
  over a year reacts to a crisis months late. EWMA weights recent days more,
  with a half-life for volatilities shorter than the one for correlations -
  volatility moves fast, correlation structure slowly, and a short half-life
  for correlations with twenty-one factors would itself be noisy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import linalg

from ..core.exceptions import ValidationError

VOL_HALF_LIFE = 42
CORRELATION_HALF_LIFE = 200
SAMPLE_WINDOW = 252


def sample_covariance(returns: np.ndarray) -> np.ndarray:
    """The unbiased sample covariance of the columns of a T x N matrix."""
    if returns.shape[0] < 2:
        raise ValidationError("a covariance needs at least two observations")
    return np.cov(returns, rowvar=False, ddof=1).reshape(returns.shape[1], returns.shape[1])


def decay(half_life: float) -> float:
    return float(0.5 ** (1.0 / half_life))


def ewma_covariance(
    returns: np.ndarray, *, vol_half_life: float = VOL_HALF_LIFE, correlation_half_life: float = CORRELATION_HALF_LIFE
) -> np.ndarray:
    """EWMA covariance of a T x K history, volatilities and correlations on separate half-lives.

    Returns are taken as having mean zero - over a day the mean is negligible
    against the volatility, and estimating it adds noise, as RiskMetrics found.
    """
    state = EwmaState.start(returns.shape[1], vol_half_life, correlation_half_life)
    for row in returns:
        state.update(row)
    return state.covariance()


@dataclass
class EwmaState:
    """A recursively updated EWMA estimator, so a daily backtest costs O(K^2) per day."""

    vol_decay: float
    correlation_decay: float
    squares: np.ndarray  # EWMA of r^2, vol half-life
    cross: np.ndarray  # EWMA of r r', correlation half-life
    weight_vol: float = 0.0  # sum of weights so far, for the start-up correction
    weight_correlation: float = 0.0

    @classmethod
    def start(
        cls, size: int, vol_half_life: float = VOL_HALF_LIFE, correlation_half_life: float = CORRELATION_HALF_LIFE
    ) -> EwmaState:
        return cls(decay(vol_half_life), decay(correlation_half_life), np.zeros(size), np.zeros((size, size)))

    def update(self, row: np.ndarray) -> None:
        clean = np.nan_to_num(row)
        self.squares = self.vol_decay * self.squares + (1 - self.vol_decay) * clean**2
        self.cross = self.correlation_decay * self.cross + (1 - self.correlation_decay) * np.outer(clean, clean)
        self.weight_vol = self.vol_decay * self.weight_vol + (1 - self.vol_decay)
        self.weight_correlation = self.correlation_decay * self.weight_correlation + (1 - self.correlation_decay)

    def variances(self) -> np.ndarray:
        return self.squares / max(self.weight_vol, 1e-12)

    def covariance(self) -> np.ndarray:
        if self.weight_vol == 0:
            raise ValidationError("an EWMA estimate needs at least one observation")
        cross = self.cross / max(self.weight_correlation, 1e-12)
        scale = np.sqrt(np.clip(np.diag(cross), 1e-30, None))
        correlation = cross / np.outer(scale, scale)
        np.fill_diagonal(correlation, 1.0)
        vols = np.sqrt(self.variances())
        return correlation * np.outer(vols, vols)


@dataclass(frozen=True)
class Shrunk:
    covariance: np.ndarray
    intensity: float  # 0 = the sample, 1 = the target
    target: np.ndarray


def ledoit_wolf(returns: np.ndarray) -> Shrunk:
    """Ledoit-Wolf (2004): shrink towards a scaled identity by the optimal intensity.

    Mean-centred returns, the maximum-likelihood sample covariance (divided by T)
    and the closed-form intensity of Ledoit and Wolf's "A well-conditioned
    estimator for large-dimensional covariance matrices". Matches
    scikit-learn's ``LedoitWolf`` to machine precision, which the tests check.
    """
    observations, size = returns.shape
    centred = returns - returns.mean(axis=0)
    sample = centred.T @ centred / observations
    mu = float(np.trace(sample)) / size
    target = mu * np.eye(size)
    delta = float(np.sum((sample - target) ** 2)) / size
    squares = centred**2
    beta_bar = float(np.sum(squares.T @ squares) / observations - np.sum(sample**2)) / (observations * size)
    beta = min(beta_bar, delta)
    intensity = 0.0 if delta == 0 else beta / delta
    return Shrunk((1 - intensity) * sample + intensity * target, intensity, target)


def ledoit_wolf_constant_correlation(returns: np.ndarray) -> Shrunk:
    """Ledoit-Wolf (2003), "Honey, I shrunk the sample covariance matrix": towards constant correlation.

    The target keeps every asset's own variance and replaces each correlation
    by the average one - a better target for stocks than the identity, whose
    returns are all positively correlated.
    """
    observations, size = returns.shape
    centred = returns - returns.mean(axis=0)
    sample = centred.T @ centred / observations
    variances = np.diag(sample)
    vols = np.sqrt(variances)
    correlation = sample / np.outer(vols, vols)
    average = (float(correlation.sum()) - size) / (size * (size - 1))
    target = average * np.outer(vols, vols)
    np.fill_diagonal(target, variances)

    squares = centred**2
    pi_matrix = squares.T @ squares / observations - sample**2
    pi_hat = float(pi_matrix.sum())
    theta_ii = (centred**3).T @ centred / observations - variances[:, None] * sample
    np.fill_diagonal(theta_ii, 0.0)
    rho_hat = float(np.trace(pi_matrix)) + average * float(np.sum((np.outer(1 / vols, vols)) * theta_ii))
    gamma_hat = float(np.sum((sample - target) ** 2))
    kappa = (pi_hat - rho_hat) / gamma_hat if gamma_hat > 0 else 0.0
    intensity = max(0.0, min(1.0, kappa / observations))
    return Shrunk((1 - intensity) * sample + intensity * target, intensity, target)


def marchenko_pastur_bounds(ratio: float, variance: float = 1.0) -> tuple[float, float]:
    """The support of the Marchenko-Pastur law for q = N / T (clipped at zero on the left)."""
    root = math.sqrt(ratio)
    return variance * (1 - root) ** 2, variance * (1 + root) ** 2


def marchenko_pastur_density(values: np.ndarray, ratio: float, variance: float = 1.0) -> np.ndarray:
    """The Marchenko-Pastur density of eigenvalues of a sample correlation matrix of pure noise."""
    low, high = marchenko_pastur_bounds(ratio, variance)
    inside = (values > low) & (values < high)
    density = np.zeros_like(values, dtype=float)
    x = values[inside]
    density[inside] = np.sqrt((high - x) * (x - low)) / (2 * math.pi * variance * ratio * x)
    return density


def correlation_of(covariance: np.ndarray) -> np.ndarray:
    vols = np.sqrt(np.clip(np.diag(covariance), 1e-30, None))
    return covariance / np.outer(vols, vols)


def condition_number(covariance: np.ndarray) -> float:
    eigenvalues = np.linalg.eigvalsh(covariance)
    smallest = float(eigenvalues.min())
    return math.inf if smallest <= 1e-18 else float(eigenvalues.max()) / smallest


def minimum_variance_weights(covariance: np.ndarray) -> np.ndarray:
    """The fully invested minimum-variance portfolio, w = S^-1 1 / 1' S^-1 1 (pseudo-inverse if singular)."""
    ones = np.ones(covariance.shape[0])
    raw = linalg.cho_solve(linalg.cho_factor(covariance), ones)
    return raw / float(ones @ raw)


def riskless_portfolio(covariance: np.ndarray, tolerance: float = 1e-12) -> np.ndarray | None:
    """A fully invested portfolio the covariance says has *no* risk, if the matrix is singular.

    With more assets than observations the sample covariance has a null space,
    and any fully invested portfolio inside it has a forecast variance of
    exactly zero - the portfolio an optimiser finds. This returns the smallest
    such portfolio (the projection of the equal-weighted one onto the null
    space), or None when the matrix is positive definite.
    """
    values, vectors = np.linalg.eigh(covariance)
    null = vectors[:, values <= values.max() * tolerance]
    if null.shape[1] == 0:
        return None
    ones = np.ones(covariance.shape[0])
    projected = null @ (null.T @ ones)
    total = float(ones @ projected)
    return None if abs(total) < 1e-12 else projected / total


def factor_minimum_variance_weights(
    exposures: np.ndarray, factor_covariance: np.ndarray, specific: np.ndarray
) -> np.ndarray:
    """Minimum-variance weights under V = X F X' + D, inverted by the Woodbury identity.

    ``V^-1 = D^-1 - D^-1 X (F^-1 + X' D^-1 X)^-1 X' D^-1`` needs only a K x K
    inverse, so a model of five thousand stocks and fifty factors is as cheap
    to optimise over as one of fifty stocks - the practical reason commercial
    optimisers work with the factor form and never build V.
    """
    ones = np.ones(exposures.shape[0])
    d_inverse = 1.0 / specific
    scaled = exposures * d_inverse[:, None]
    inner = np.linalg.inv(factor_covariance) + exposures.T @ scaled
    raw = d_inverse * ones - scaled @ np.linalg.solve(inner, scaled.T @ ones)
    return raw / float(ones @ raw)
