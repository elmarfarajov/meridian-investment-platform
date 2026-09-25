"""Specific risk: what is left of each stock once the factors have taken their share.

A stock's specific variance is forecast from its own specific returns, with an
exponentially weighted average on a 63-day half-life.

**Bayesian shrinkage** (as in Barra's USE4) is implemented and was tested. It
pulls each forecast towards the average of stocks of similar size, by more the
further it is from that average:

    s_shrunk = v * s_bar + (1 - v) * s,      v = q |s - s_bar| / (dev + q |s - s_bar|)

where ``s_bar`` is the capitalisation-weighted mean specific volatility of the
stock's size decile and ``dev`` the dispersion within the decile. It is a cure
for noisy estimates. Here two tests rejected it: on the estimation universe it
widened the spread of the stocks' own bias statistics several times over,
because the differences between stocks are real and persistent and 63 days
measure them well; on the account it pulled the tracking error forecast a fifth
too low, because the universe's size deciles are the wrong prior for the
account's mega-caps. It is off by default and kept, with its evidence, as the
documented alternative (ADR 0025).
"""

from __future__ import annotations

import numpy as np

SPECIFIC_HALF_LIFE = 63
SHRINKAGE_Q = 0.3
SIZE_BUCKETS = 10


def bayesian_shrink(
    vols: np.ndarray, caps: np.ndarray, *, q: float = SHRINKAGE_Q, buckets: int = SIZE_BUCKETS
) -> np.ndarray:
    """Shrink specific volatilities towards the cap-weighted mean of their size decile."""
    order = np.argsort(caps)
    groups = np.array_split(order, buckets)
    shrunk = vols.copy()
    for group in groups:
        if len(group) == 0:
            continue
        weights = caps[group] / caps[group].sum()
        mean = float(weights @ vols[group])
        dispersion = float(np.sqrt(np.mean((vols[group] - mean) ** 2)))
        distance = np.abs(vols[group] - mean)
        intensity = q * distance / (dispersion + q * distance) if dispersion > 0 else np.zeros(len(group))
        shrunk[group] = intensity * mean + (1 - intensity) * vols[group]
    return shrunk


def shrink_against(
    vol: float,
    cap: float,
    universe_vols: np.ndarray,
    universe_caps: np.ndarray,
    *,
    q: float = SHRINKAGE_Q,
    buckets: int = SIZE_BUCKETS,
) -> float:
    """Shrink one asset outside the estimation universe towards the universe's size decile it would fall in."""
    known = np.isfinite(universe_vols)
    vols, caps = universe_vols[known], universe_caps[known]
    order = np.argsort(caps)
    groups = np.array_split(order, buckets)
    edges = [float(caps[group].max()) for group in groups if len(group)]
    bucket = next((position for position, edge in enumerate(edges) if cap <= edge), len(edges) - 1)
    group = groups[bucket]
    weights = caps[group] / caps[group].sum()
    mean = float(weights @ vols[group])
    dispersion = float(np.sqrt(np.mean((vols[group] - mean) ** 2)))
    distance = abs(vol - mean)
    intensity = q * distance / (dispersion + q * distance) if dispersion > 0 else 0.0
    return intensity * mean + (1 - intensity) * vol


class SpecificRisk:
    """A recursive EWMA of squared specific returns, one per stock."""

    def __init__(self, count: int, half_life: float = SPECIFIC_HALF_LIFE) -> None:
        self.decay = 0.5 ** (1.0 / half_life)
        self.squares = np.zeros(count)
        self.weight = np.zeros(count)

    def update(self, residuals: np.ndarray) -> None:
        present = np.isfinite(residuals)
        clean = np.where(present, residuals, 0.0)
        self.squares = np.where(present, self.decay * self.squares + (1 - self.decay) * clean**2, self.squares)
        self.weight = np.where(present, self.decay * self.weight + (1 - self.decay), self.weight)

    def variances(self, caps: np.ndarray | None = None, *, shrink: bool = False) -> np.ndarray:
        raw = np.where(self.weight > 0, self.squares / np.maximum(self.weight, 1e-12), np.nan)
        if not shrink or caps is None:
            return raw
        vols = np.sqrt(raw)
        known = np.isfinite(vols)
        shrunk = vols.copy()
        shrunk[known] = bayesian_shrink(vols[known], caps[known])
        return shrunk**2
