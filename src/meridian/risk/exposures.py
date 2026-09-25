"""From what can be observed about a stock to its exposures.

A fundamental model does not estimate exposures from a stock's past returns
against the factors - that would need a long history and would be slow to
notice that a company has changed. It computes them from characteristics, the
*descriptors*, observed at the start of the day:

* **Beta** - the slope of the stock's return on the market's over the last
  year, weighted towards recent days and shrunk towards one (Vasicek): a beta
  measured with a large standard error is pulled most.
* **Size** - the logarithm of market capitalisation.
* **Value** - the logarithm of book-to-price.
* **Momentum** - the stock's return over the last twelve months, excluding the
  most recent month, where short-term reversal dominates.
* **Quality** - return on equity, an accounting ratio.

Each descriptor is winsorised and standardised (:func:`standardise`): the
capitalisation-weighted market has zero exposure to every style, and one unit is
one cross-sectional standard deviation. Industry exposures are one for the
stock's GICS sector and zero elsewhere; the world exposure is one for every
stock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from .factors import INDUSTRIES, STYLES

TRADING_DAYS = 252
BETA_WINDOW = 252
BETA_HALF_LIFE = 63
MOMENTUM_WINDOW = 252
MOMENTUM_LAG = 21


def standardise(values: np.ndarray, caps: np.ndarray, limit: float = 3.0) -> np.ndarray:
    """Cap-weighted mean zero, equal-weighted standard deviation one, winsorised at ``limit``.

    The convention of commercial models: the capitalisation-weighted market has
    zero exposure to every style, so a style is a tilt away from the market, and
    a unit of exposure is one cross-sectional standard deviation. Winsorising
    before and re-centring after keeps one extreme stock from setting the scale
    for all the others.
    """
    weights = caps / caps.sum()
    centred = values - float(weights @ values)
    scale = float(centred.std())
    if scale == 0.0 or not math.isfinite(scale):
        return np.zeros_like(values)
    scores = np.clip(centred / scale, -limit, limit)
    scores = scores - float(weights @ scores)
    spread = float(scores.std())
    return scores / spread if spread > 0 else scores


def ewma_weights(length: int, half_life: float) -> np.ndarray:
    """Exponential weights over ``length`` observations, oldest first, summing to one."""
    decay = 0.5 ** (1.0 / half_life)
    weights = decay ** np.arange(length - 1, -1, -1, dtype=float)
    return weights / weights.sum()


def historical_beta(
    returns: np.ndarray, market: np.ndarray, *, half_life: float = BETA_HALF_LIFE
) -> tuple[np.ndarray, np.ndarray]:
    """Weighted least-squares beta of each column of ``returns`` on ``market``, with its standard error."""
    weights = ewma_weights(len(market), half_life)
    market_mean = float(weights @ market)
    centred_market = market - market_mean
    variance = float(weights @ centred_market**2)
    means = weights @ returns
    centred = returns - means
    beta = (weights * centred_market) @ centred / variance
    residual = centred - np.outer(centred_market, beta)
    effective = 1.0 / float(np.sum(weights**2))
    residual_variance = (weights @ residual**2) * effective / max(effective - 2.0, 1.0)
    error = np.sqrt(residual_variance / (variance * effective))
    return beta, error


def vasicek_shrink(beta: np.ndarray, error: np.ndarray, caps: np.ndarray) -> np.ndarray:
    """Pull each beta towards the cross-sectional mean in proportion to its own uncertainty."""
    weights = caps / caps.sum()
    prior_mean = float(weights @ beta)
    prior_variance = float(np.var(beta))
    return (prior_variance * beta + error**2 * prior_mean) / (prior_variance + error**2)


@dataclass(frozen=True)
class Descriptors:
    """The raw characteristics of each stock on one day, before standardisation."""

    beta: np.ndarray
    size: np.ndarray
    value: np.ndarray
    momentum: np.ndarray
    quality: np.ndarray

    def matrix(self) -> np.ndarray:
        return np.column_stack([self.beta, self.size, self.value, self.momentum, self.quality])


@dataclass(frozen=True)
class ExposureMatrix:
    """Exposures of a set of assets to the local factors (world, industries, styles) on one day."""

    day: date
    assets: tuple[str, ...]
    world: np.ndarray  # N, ones
    industries: np.ndarray  # N x industries
    styles: np.ndarray  # N x styles
    caps: np.ndarray  # N, the weights of the standardisation
    raw: np.ndarray | None = None  # N x styles, the descriptors before standardisation

    def local(self) -> np.ndarray:
        """The N x (1 + industries + styles) matrix the regression uses."""
        return np.column_stack([self.world, self.industries, self.styles])

    def style(self, name: str) -> np.ndarray:
        return self.styles[:, STYLES.index(name)]


def compute_descriptors(
    local_log: np.ndarray,
    caps: np.ndarray,
    book_to_price: np.ndarray,
    return_on_equity: np.ndarray,
    day_index: int,
) -> Descriptors:
    """The descriptors known at the start of ``day_index``: everything up to the previous close.

    ``local_log`` is T x N daily log returns in local currency; ``caps`` T x N
    capitalisations. The market for the beta regression is the cap-weighted
    universe itself.
    """
    last = day_index  # rows < day_index are known
    start = max(0, last - BETA_WINDOW)
    history = local_log[start:last]
    weights = caps[np.maximum(np.arange(start, last) - 1, 0)]  # each day weighted by the previous close
    market = np.einsum("tn,tn->t", weights / weights.sum(axis=1, keepdims=True), history)
    current_caps = caps[last - 1]
    if len(history) > 20:
        raw_beta, error = historical_beta(history, market)
        beta = vasicek_shrink(raw_beta, error, current_caps)
    else:
        beta = np.ones(local_log.shape[1])
    momentum_end = max(0, last - MOMENTUM_LAG)
    momentum_start = max(0, last - MOMENTUM_WINDOW)
    momentum = local_log[momentum_start:momentum_end].sum(axis=0)
    return Descriptors(
        beta=beta,
        size=np.log(current_caps),
        value=np.log(book_to_price),
        momentum=momentum,
        quality=return_on_equity,
    )


def exposures_from(
    day: date,
    assets: tuple[str, ...],
    descriptors: Descriptors,
    sectors: list[str],
    caps: np.ndarray,
) -> ExposureMatrix:
    """Standardise the descriptors against the estimation universe and add the industries."""
    raw = descriptors.matrix()
    styles = np.column_stack([standardise(raw[:, k], caps) for k in range(raw.shape[1])])
    industries = np.zeros((len(assets), len(INDUSTRIES)))
    for row, sector in enumerate(sectors):
        industries[row, INDUSTRIES.index(sector)] = 1.0
    return ExposureMatrix(day, assets, np.ones(len(assets)), industries, styles, caps, raw)


def standardise_against(
    values: np.ndarray, reference: np.ndarray, reference_caps: np.ndarray, limit: float = 3.0
) -> np.ndarray:
    """Exposures for assets outside the estimation universe, on the universe's own scale.

    A stock the account holds but the regression does not use is measured with
    the estimation universe's cap-weighted mean and standard deviation, so an
    exposure of one means the same thing for every asset in the report.
    """
    weights = reference_caps / reference_caps.sum()
    centre = float(weights @ reference)
    scale = float((reference - centre).std())
    if scale == 0.0:
        return np.zeros_like(values)
    return np.clip((values - centre) / scale, -limit, limit)
