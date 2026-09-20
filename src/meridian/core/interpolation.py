"""Interpolation, with the choices a curve actually needs.

A yield curve is quoted at a handful of tenors and used at every date in between,
so the interpolation method is not a detail - it is a modelling decision that
shows up in every discount factor and every forward rate the curve produces.

Three methods are provided, and the differences matter:

*Linear on the rate* is the obvious choice and the worst behaved. It produces a
forward curve with a discontinuity at every pillar, which looks like an arbitrage
opportunity that is not there.

*Log-linear on the discount factor* is equivalent to assuming a constant forward
rate between pillars. The forward curve becomes a step function - still
discontinuous, but piecewise flat and economically interpretable, and the
discount factors stay positive and monotone by construction. This is the default.

*Monotone cubic* (Fritsch-Carlson, the method behind PCHIP) gives a smooth curve
that does not overshoot. A plain cubic spline through market rates will invent
humps between pillars that no trader quoted; the monotonicity filter removes them
at the cost of some smoothness in the second derivative.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from enum import Enum
from itertools import pairwise

from .exceptions import ValidationError


class InterpolationMethod(str, Enum):
    LINEAR = "linear"
    LOG_LINEAR = "log_linear"
    MONOTONE_CUBIC = "monotone_cubic"
    FLAT_FORWARD = "flat_forward"
    PREVIOUS = "previous"


def _validate(xs: Sequence[float], ys: Sequence[float]) -> None:
    if len(xs) != len(ys):
        raise ValidationError("Interpolation needs the same number of x and y values")
    if len(xs) < 2:
        raise ValidationError("Interpolation needs at least two points")
    if any(later <= earlier for earlier, later in pairwise(xs)):
        raise ValidationError("Interpolation x values must be strictly increasing")


class Interpolator:
    """A callable curve through a set of points, flat-extrapolated beyond the ends."""

    method: InterpolationMethod = InterpolationMethod.LINEAR

    def __init__(self, xs: Sequence[float], ys: Sequence[float]) -> None:
        _validate(xs, ys)
        self.xs = tuple(float(x) for x in xs)
        self.ys = tuple(float(y) for y in ys)

    def _bracket(self, x: float) -> tuple[int, int]:
        index = bisect.bisect_left(self.xs, x)
        if index <= 0:
            return 0, 1
        if index >= len(self.xs):
            return len(self.xs) - 2, len(self.xs) - 1
        return index - 1, index

    def __call__(self, x: float) -> float:  # pragma: no cover - overridden
        raise NotImplementedError

    def values(self, points: Sequence[float]) -> list[float]:
        return [self(point) for point in points]

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {len(self.xs)} points>"


class LinearInterpolator(Interpolator):
    method = InterpolationMethod.LINEAR

    def __call__(self, x: float) -> float:
        if x <= self.xs[0]:
            return self.ys[0]
        if x >= self.xs[-1]:
            return self.ys[-1]
        left, right = self._bracket(x)
        weight = (x - self.xs[left]) / (self.xs[right] - self.xs[left])
        return self.ys[left] + weight * (self.ys[right] - self.ys[left])


class LogLinearInterpolator(Interpolator):
    """Linear in the logarithm of y: constant growth, and y can never cross zero."""

    method = InterpolationMethod.LOG_LINEAR

    def __init__(self, xs: Sequence[float], ys: Sequence[float]) -> None:
        super().__init__(xs, ys)
        if any(value <= 0 for value in self.ys):
            raise ValidationError("Log-linear interpolation needs strictly positive values")
        self._logs = tuple(math.log(value) for value in self.ys)

    def __call__(self, x: float) -> float:
        if x <= self.xs[0]:
            return self.ys[0]
        if x >= self.xs[-1]:
            return self.ys[-1]
        left, right = self._bracket(x)
        weight = (x - self.xs[left]) / (self.xs[right] - self.xs[left])
        return math.exp(self._logs[left] + weight * (self._logs[right] - self._logs[left]))


class PreviousInterpolator(Interpolator):
    """Step function: hold the last known value. Used for anything that is only ever observed."""

    method = InterpolationMethod.PREVIOUS

    def __call__(self, x: float) -> float:
        if x <= self.xs[0]:
            return self.ys[0]
        index = bisect.bisect_right(self.xs, x) - 1
        return self.ys[min(index, len(self.ys) - 1)]


class MonotoneCubicInterpolator(Interpolator):
    """Fritsch-Carlson monotone cubic Hermite interpolation.

    Secant slopes are computed first, then the endpoint derivatives are limited so
    that no segment can overshoot. The result is C1, shape-preserving, and free of
    the spurious humps a natural cubic spline produces between market pillars.
    """

    method = InterpolationMethod.MONOTONE_CUBIC

    def __init__(self, xs: Sequence[float], ys: Sequence[float]) -> None:
        super().__init__(xs, ys)
        self._tangents = self._fritsch_carlson()

    def _fritsch_carlson(self) -> tuple[float, ...]:
        count = len(self.xs)
        deltas = [(self.ys[i + 1] - self.ys[i]) / (self.xs[i + 1] - self.xs[i]) for i in range(count - 1)]
        tangents = [0.0] * count
        tangents[0] = deltas[0]
        tangents[-1] = deltas[-1]
        for i in range(1, count - 1):
            if deltas[i - 1] * deltas[i] <= 0:
                tangents[i] = 0.0  # a local extremum: flatten, or the curve overshoots
            else:
                tangents[i] = (deltas[i - 1] + deltas[i]) / 2

        for i, delta in enumerate(deltas):
            if delta == 0:
                tangents[i] = tangents[i + 1] = 0.0
                continue
            alpha = tangents[i] / delta
            beta = tangents[i + 1] / delta
            magnitude = alpha * alpha + beta * beta
            if magnitude > 9:  # project back onto the circle of radius 3
                scale = 3.0 / math.sqrt(magnitude)
                tangents[i] = scale * alpha * delta
                tangents[i + 1] = scale * beta * delta
        return tuple(tangents)

    def __call__(self, x: float) -> float:
        if x <= self.xs[0]:
            return self.ys[0]
        if x >= self.xs[-1]:
            return self.ys[-1]
        left, right = self._bracket(x)
        span = self.xs[right] - self.xs[left]
        t = (x - self.xs[left]) / span
        t2, t3 = t * t, t * t * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        return (
            h00 * self.ys[left]
            + h10 * span * self._tangents[left]
            + h01 * self.ys[right]
            + h11 * span * self._tangents[right]
        )


_INTERPOLATORS: dict[InterpolationMethod, type[Interpolator]] = {
    InterpolationMethod.LINEAR: LinearInterpolator,
    InterpolationMethod.LOG_LINEAR: LogLinearInterpolator,
    InterpolationMethod.MONOTONE_CUBIC: MonotoneCubicInterpolator,
    InterpolationMethod.PREVIOUS: PreviousInterpolator,
    InterpolationMethod.FLAT_FORWARD: LogLinearInterpolator,  # log-linear on DFs is flat forwards
}


def make_interpolator(
    xs: Sequence[float],
    ys: Sequence[float],
    method: InterpolationMethod | str = InterpolationMethod.LINEAR,
) -> Interpolator:
    method = InterpolationMethod(method) if not isinstance(method, InterpolationMethod) else method
    return _INTERPOLATORS[method](xs, ys)


def interpolate(
    xs: Sequence[float],
    ys: Sequence[float],
    x: float,
    method: InterpolationMethod | str = InterpolationMethod.LINEAR,
) -> float:
    return make_interpolator(xs, ys, method)(x)
