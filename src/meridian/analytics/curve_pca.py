"""Principal components of yield-curve moves: level, slope and curvature.

Litterman and Scheinkman (1991, *Journal of Fixed Income*) found that three factors
explain nearly all of the variation in Treasury returns. They called them level,
steepness and curvature. The finding has held up for three decades and across
markets. It is why a desk hedges with a handful of instruments rather than one per
maturity, and why key-rate durations are grouped the way they are.

The analysis here is the textbook one:

- daily changes in par yields at fixed tenors, in basis points;
- their covariance matrix;
- its eigenvectors (the loadings) and eigenvalues (the variance each explains).

Eigenvectors have no sign of their own, so each is oriented to match its name:

- the level loading is positive on average;
- the slope loading rises from the short end to the long end;
- the curvature loading is positive in the middle of the curve.

Without this, a chart of the history would flip sign at random from one window to
the next.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from ..core.exceptions import ValidationError

NAMES = ("level", "slope", "curvature")


@dataclass(frozen=True)
class CurvePCA:
    """The components of daily curve changes over a window."""

    labels: tuple[str, ...]
    tenors: tuple[float, ...]
    loadings: np.ndarray  # (tenors x components), unit length columns
    variances: np.ndarray  # eigenvalues, bp^2 per day, descending
    scores: np.ndarray  # (days x components), bp
    days: tuple[date, ...]

    @property
    def explained(self) -> np.ndarray:
        """Share of total variance explained by each component."""
        return self.variances / self.variances.sum()

    @property
    def cumulative(self) -> np.ndarray:
        return np.cumsum(self.explained)

    def volatility_bp(self, component: int, annualise: bool = True) -> float:
        """The standard deviation of a component's daily score, annualised over 252 days by default."""
        daily = float(np.sqrt(self.variances[component]))
        return daily * np.sqrt(252) if annualise else daily


def _orient(loadings: np.ndarray, tenors: np.ndarray) -> np.ndarray:
    oriented = loadings.copy()
    if oriented[:, 0].sum() < 0:  # level: the curve moves up
        oriented[:, 0] *= -1
    if oriented.shape[1] > 1 and oriented[-1, 1] - oriented[0, 1] < 0:  # slope: long end up against short end
        oriented[:, 1] *= -1
    if oriented.shape[1] > 2:  # curvature: the belly up against both wings
        middle = np.argmin(np.abs(np.log(tenors) - np.log(tenors).mean()))
        wings = 0.5 * (oriented[0, 2] + oriented[-1, 2])
        if oriented[middle, 2] - wings < 0:
            oriented[:, 2] *= -1
    return oriented


def curve_pca(
    days: Sequence[date],
    yields: np.ndarray,
    labels: Sequence[str],
    tenors: Sequence[float],
    *,
    components: int = 3,
) -> CurvePCA:
    """PCA of daily changes of a (days x tenors) matrix of yields in decimals."""
    levels = np.asarray(yields, dtype=float)
    if levels.ndim != 2 or levels.shape[1] != len(labels):
        raise ValidationError("Yields must be a (days x tenors) matrix with one label per column")
    if levels.shape[0] < levels.shape[1] + 2:
        raise ValidationError("Too few days for the number of tenors")
    changes = np.diff(levels, axis=0) * 10_000
    centred = changes - changes.mean(axis=0)
    covariance = centred.T @ centred / (len(centred) - 1)
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]
    loadings = _orient(vectors[:, :components], np.asarray(tenors, dtype=float))
    return CurvePCA(
        labels=tuple(labels),
        tenors=tuple(float(t) for t in tenors),
        loadings=loadings,
        variances=values,
        scores=centred @ loadings,
        days=tuple(days[1:]),
    )


def rolling_explained(
    days: Sequence[date],
    yields: np.ndarray,
    labels: Sequence[str],
    tenors: Sequence[float],
    *,
    window: int = 504,
    step: int = 21,
) -> tuple[list[date], np.ndarray]:
    """The share explained by the first three components, in rolling windows of ``window`` days."""
    ends: list[date] = []
    shares: list[np.ndarray] = []
    for end in range(window, len(days), step):
        result = curve_pca(days[end - window : end], yields[end - window : end], labels, tenors)
        ends.append(days[end - 1])
        shares.append(result.explained[:3])
    return ends, np.array(shares)
