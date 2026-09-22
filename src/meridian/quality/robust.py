"""Robust statistics for spotting bad prints.

The obvious outlier test - flag a return more than k standard deviations from
the mean - fails in exactly the situation it is needed for. One bad tick of
+40% inflates the standard deviation so much that the tick itself no longer
looks extreme (*masking*), and a burst of genuine volatility makes ordinary
days look like outliers (*swamping*).

The median and the median absolute deviation (MAD) do not have that problem.
Half the window can be garbage before the median moves, which is a breakdown
point of 50% against the mean's 0%. Scaling the MAD by 1.4826 makes it an
unbiased estimate of the standard deviation when the data are normal, so a
robust z-score reads on the same scale as the classical one - it just cannot
be talked out of its answer by the outlier it is judging.

The rolling versions here only look *backwards*: the score for day ``t`` uses
the window ending at ``t - 1``. A quality check that uses tomorrow's data to
judge today's print could not have run on the day.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

#: Makes the MAD a consistent estimator of the standard deviation for normal data (1 / Phi^-1(3/4)).
MAD_SCALE = 1.4826


def median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median of an empty sequence")
    return float(np.median(np.asarray(values, dtype=float)))


def mad(values: Sequence[float], *, scaled: bool = True) -> float:
    """Median absolute deviation from the median, scaled to a standard deviation by default."""
    data = np.asarray(values, dtype=float)
    if data.size == 0:
        raise ValueError("MAD of an empty sequence")
    deviation = float(np.median(np.abs(data - np.median(data))))
    return deviation * MAD_SCALE if scaled else deviation


def robust_zscores(values: Sequence[float]) -> list[float]:
    """Each value's distance from the median in units of the scaled MAD, over the whole sample."""
    data = np.asarray(values, dtype=float)
    if data.size == 0:
        return []
    centre = float(np.median(data))
    scale = mad(values)
    if scale == 0:
        return [0.0 if value == centre else math.copysign(math.inf, value - centre) for value in data.tolist()]
    return [float(value) for value in ((data - centre) / scale).tolist()]


def classical_zscores(values: Sequence[float]) -> list[float]:
    """The textbook z-score, kept for comparison: it is what the robust version is argued against."""
    data = np.asarray(values, dtype=float)
    if data.size < 2:
        return [0.0] * int(data.size)
    deviation = float(data.std(ddof=1))
    if deviation == 0:
        return [0.0] * int(data.size)
    return [float(value) for value in ((data - data.mean()) / deviation).tolist()]


def rolling_robust_z(values: Sequence[float], window: int = 60, *, min_periods: int = 20) -> list[float | None]:
    """Backward-looking robust z-score: day ``t`` is scored against days ``t-window .. t-1``.

    ``None`` means there was not yet enough history to judge. A zero MAD - a
    window of identical values, which is itself a staleness symptom - scores any
    departure as infinitely far away rather than dividing by zero.
    """
    if window < 3 or min_periods < 3:
        raise ValueError("a robust window needs at least three observations")
    data = np.asarray(values, dtype=float)
    scores: list[float | None] = []
    for index in range(data.size):
        history = data[max(0, index - window) : index]
        if history.size < min_periods:
            scores.append(None)
            continue
        centre = float(np.median(history))
        scale = float(np.median(np.abs(history - centre))) * MAD_SCALE
        difference = float(data[index]) - centre
        if scale == 0:
            scores.append(0.0 if difference == 0 else math.copysign(math.inf, difference))
        else:
            scores.append(difference / scale)
    return scores


def rolling_classical_z(values: Sequence[float], window: int = 60, *, min_periods: int = 20) -> list[float | None]:
    """Backward-looking classical z-score, for the side-by-side comparison."""
    data = np.asarray(values, dtype=float)
    scores: list[float | None] = []
    for index in range(data.size):
        history = data[max(0, index - window) : index]
        if history.size < min_periods:
            scores.append(None)
            continue
        deviation = float(history.std(ddof=1))
        scores.append(0.0 if deviation == 0 else (float(data[index]) - float(history.mean())) / deviation)
    return scores


def hampel_filter(values: Sequence[float], window: int = 7, threshold: float = 3.0) -> tuple[list[float], list[int]]:
    """Replace points far from their centred rolling median with that median.

    The centred window makes this a *cleaning* tool for history, not a live
    check - it looks at both sides of each point. Returns the cleaned values and
    the indexes that were replaced.
    """
    data = np.asarray(values, dtype=float)
    cleaned = data.copy()
    replaced: list[int] = []
    half = window // 2
    for index in range(data.size):
        low, high = max(0, index - half), min(data.size, index + half + 1)
        neighbourhood = data[low:high]
        centre = float(np.median(neighbourhood))
        scale = float(np.median(np.abs(neighbourhood - centre))) * MAD_SCALE
        if scale > 0 and abs(float(data[index]) - centre) > threshold * scale:
            cleaned[index] = centre
            replaced.append(index)
    return cleaned.tolist(), replaced
