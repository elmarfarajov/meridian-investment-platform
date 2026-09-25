"""Validating a risk model: is the forecast the right size, and are the misses independent?

**Bias statistics.** If a volatility forecast is right, a return divided by the
forecast made the evening before - the standardised outcome ``z`` - has standard
deviation one. Over a window of T days the bias statistic is the standard
deviation of the z's. For a correct model it lies within ``1 +/- sqrt(2/T)``
about 95% of the time (the approximate standard error of a sample standard
deviation); above the band the model under-forecast risk, below it
over-forecast. A rolling bias statistic shows *when* a model was wrong; the
mean rolling absolute deviation from one (MRAD) summarises how wrong on
average, and is the headline measure in commercial model reviews.

**Value at risk backtests.** A 99% one-day VaR should be exceeded on about 1%
of days, and exceedances should not cluster.

* Kupiec's proportion-of-failures test: is the number of exceptions consistent
  with the VaR level? A likelihood ratio, chi-squared with one degree of
  freedom.
* Christoffersen's independence test: is an exception more likely the day after
  an exception? Clustering means the model reacts too slowly to a change in
  volatility. The conditional-coverage test adds the two.
* The Basel traffic light: over 250 days, up to four exceptions of a 99% VaR is
  green, five to nine yellow (with a rising capital multiplier), ten or more
  red.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

from ..core.exceptions import ValidationError


# ---------------------------------------------------------------------------- bias statistics
def bias_statistic(z_scores: np.ndarray) -> float:
    """The standard deviation of standardised outcomes (mean included, as in the literature)."""
    clean = z_scores[np.isfinite(z_scores)]
    if len(clean) < 2:
        raise ValidationError("a bias statistic needs at least two outcomes")
    return float(np.std(clean, ddof=1))


def confidence_band(observations: int) -> tuple[float, float]:
    """The approximate 95% band of a bias statistic over ``observations`` days for a correct model."""
    half_width = 1.96 * math.sqrt(1.0 / (2.0 * observations))
    return 1.0 - half_width, 1.0 + half_width


def rolling_bias(z_scores: np.ndarray, window: int = 126) -> np.ndarray:
    """The bias statistic over each trailing window; NaN until a full window is available."""
    output = np.full(len(z_scores), np.nan)
    for end in range(window, len(z_scores) + 1):
        output[end - 1] = np.std(z_scores[end - window : end], ddof=1)
    return output


def mrad(z_scores: np.ndarray, window: int = 126) -> float:
    """Mean rolling absolute deviation of the bias statistic from one."""
    rolling = rolling_bias(z_scores, window)
    return float(np.nanmean(np.abs(rolling - 1.0)))


@dataclass(frozen=True)
class BiasSummary:
    name: str
    observations: int
    bias: float
    low: float
    high: float
    mrad: float
    within_band: float  # share of rolling windows whose bias lies in the band

    @property
    def verdict(self) -> str:
        if self.bias > self.high:
            return "under-forecasts"
        if self.bias < self.low:
            return "over-forecasts"
        return "unbiased"


def summarise_bias(name: str, z_scores: np.ndarray, window: int = 126) -> BiasSummary:
    clean = z_scores[np.isfinite(z_scores)]
    low, high = confidence_band(len(clean))
    rolling = rolling_bias(clean, window)
    window_low, window_high = confidence_band(window)
    valid = rolling[np.isfinite(rolling)]
    inside = float(np.mean((valid >= window_low) & (valid <= window_high))) if len(valid) else math.nan
    return BiasSummary(name, len(clean), bias_statistic(clean), low, high, mrad(clean, window), inside)


# ---------------------------------------------------------------------------- VaR backtests
@dataclass(frozen=True)
class CoverageTest:
    name: str
    statistic: float
    p_value: float

    @property
    def rejected(self) -> bool:
        return self.p_value < 0.05


def _log_likelihood(exceptions: int, observations: int, probability: float) -> float:
    safe = min(max(probability, 1e-15), 1 - 1e-15)
    return exceptions * math.log(safe) + (observations - exceptions) * math.log(1 - safe)


def kupiec(exceptions: int, observations: int, coverage: float = 0.99) -> CoverageTest:
    """Kupiec's proportion-of-failures likelihood ratio (chi-squared, one degree of freedom)."""
    if observations <= 0 or not 0 <= exceptions <= observations:
        raise ValidationError("exceptions must lie between zero and the number of observations")
    expected = 1 - coverage
    observed = exceptions / observations
    statistic = -2 * (
        _log_likelihood(exceptions, observations, expected) - _log_likelihood(exceptions, observations, observed)
    )
    return CoverageTest("Kupiec proportion of failures", statistic, float(stats.chi2.sf(statistic, 1)))


def christoffersen(hits: np.ndarray) -> CoverageTest:
    """Christoffersen's independence test on a 0/1 series of exceptions (chi-squared, one degree of freedom)."""
    hits = np.asarray(hits, dtype=int)
    previous, current = hits[:-1], hits[1:]
    n00 = int(np.sum((previous == 0) & (current == 0)))
    n01 = int(np.sum((previous == 0) & (current == 1)))
    n10 = int(np.sum((previous == 1) & (current == 0)))
    n11 = int(np.sum((previous == 1) & (current == 1)))
    pi01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    pi11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)

    def term(count: int, probability: float) -> float:
        return count * math.log(probability) if count and probability > 0 else 0.0

    restricted = term(n00 + n10, 1 - pi) + term(n01 + n11, pi)
    unrestricted = term(n00, 1 - pi01) + term(n01, pi01) + term(n10, 1 - pi11) + term(n11, pi11)
    statistic = max(-2 * (restricted - unrestricted), 0.0)
    return CoverageTest("Christoffersen independence", statistic, float(stats.chi2.sf(statistic, 1)))


def conditional_coverage(hits: np.ndarray, coverage: float = 0.99) -> CoverageTest:
    """Kupiec plus Christoffersen: right number of exceptions, and not clustered (two degrees of freedom)."""
    pof = kupiec(int(np.sum(hits)), len(hits), coverage)
    independence = christoffersen(hits)
    statistic = pof.statistic + independence.statistic
    return CoverageTest("Christoffersen conditional coverage", statistic, float(stats.chi2.sf(statistic, 2)))


#: Basel Committee (1996) backtesting framework: exceptions in 250 days of a 99% VaR -> zone, plus factor.
BASEL_PLUS_FACTOR = {5: 0.40, 6: 0.50, 7: 0.65, 8: 0.75, 9: 0.85}


@dataclass(frozen=True)
class TrafficLight:
    exceptions: int
    zone: str  # green, yellow or red
    multiplier: float  # the capital multiplier, 3 plus the plus factor


def traffic_light(exceptions: int) -> TrafficLight:
    if exceptions <= 4:
        return TrafficLight(exceptions, "green", 3.0)
    if exceptions <= 9:
        return TrafficLight(exceptions, "yellow", 3.0 + BASEL_PLUS_FACTOR[exceptions])
    return TrafficLight(exceptions, "red", 4.0)


def exceptions(returns: np.ndarray, var: np.ndarray) -> np.ndarray:
    """1 where the loss exceeded the VaR (VaR given as a positive loss), else 0."""
    return (-np.asarray(returns) > np.asarray(var)).astype(int)
