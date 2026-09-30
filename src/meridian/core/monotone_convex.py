"""Monotone convex interpolation of forward rates (Hagan and West, 2006).

A curve bootstrapped with log-linear discount factors has piecewise flat forwards: a
staircase that jumps at every pillar. A cubic spline on zero rates smooths the steps,
but its forwards overshoot and can go negative between perfectly ordinary quotes.
Hagan and West set out what a curve builder should demand of an interpolator:

1. **it reprices the inputs**: the average forward over each interval equals the
   discrete forward the quotes imply, so every instrument prices back exactly;
2. **the forward curve is continuous**;
3. **it is local**: a change in one quote moves the forwards only near that quote,
   so a hedge in one instrument does not leak into distant ones;
4. **the forwards stay positive** when the discrete forwards are positive;
5. **it is monotone** wherever the discrete forwards are.

Their method meets all five. Instantaneous forwards at the nodes are weighted
averages of neighbouring discrete forwards. Within each interval a correction
``g(x)``, which integrates to zero, is chosen from four quadratic shapes according
to the signs of its end values. The integral of ``g`` is known in closed form, so
discount factors need no numerical quadrature.

Reference: P. S. Hagan and G. West, "Interpolation Methods for Curve
Construction", *Applied Mathematical Finance* 13(2), 2006, pp. 89-129; and
"Methods for Constructing a Yield Curve", *Wilmott Magazine*, May 2008.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from itertools import pairwise

from .exceptions import ValidationError


class MonotoneConvex:
    """Forwards between node times ``0 = t_0 < t_1 < ... < t_n``, from zero rates at ``t_1..t_n``.

    The rates are continuously compounded. ``integral(t)`` is ``r(t) * t``, from which
    ``DF(t) = exp(-integral(t))``, and ``forward(t)`` is the instantaneous forward.
    Beyond the last node the forward is held at its last value.
    """

    def __init__(self, times: Sequence[float], rates: Sequence[float], *, positive: bool = True) -> None:
        if len(times) != len(rates) or not times:
            raise ValidationError("Monotone convex needs one rate per node and at least one node")
        if times[0] <= 0 or any(later <= earlier for earlier, later in pairwise(times)):
            raise ValidationError("Monotone convex nodes must be positive and strictly increasing")
        self.times = (0.0, *(float(value) for value in times))
        self.integrals = (0.0, *(float(t) * float(r) for t, r in zip(times, rates, strict=True)))
        n = len(times)
        # discrete forwards f^d_i on [t_{i-1}, t_i], i = 1..n (index 0 unused)
        self.discrete = [0.0] + [
            (self.integrals[i] - self.integrals[i - 1]) / (self.times[i] - self.times[i - 1]) for i in range(1, n + 1)
        ]
        self.nodes = self._node_forwards(positive)

    def _node_forwards(self, positive: bool) -> list[float]:
        t, fd = self.times, self.discrete
        n = len(t) - 1
        f = [0.0] * (n + 1)
        if n == 1:
            f[0] = f[1] = fd[1]
            return f
        for i in range(1, n):
            left, right = t[i] - t[i - 1], t[i + 1] - t[i]
            f[i] = (left * fd[i + 1] + right * fd[i]) / (left + right)
        f[0] = fd[1] - 0.5 * (f[1] - fd[1])
        f[n] = fd[n] - 0.5 * (f[n - 1] - fd[n])
        if positive:  # Hagan-West's collar: keeps the forwards positive when the inputs are
            f[0] = min(max(f[0], 0.0), 2 * fd[1])
            for i in range(1, n):
                f[i] = min(max(f[i], 0.0), 2 * min(fd[i], fd[i + 1]))
            f[n] = min(max(f[n], 0.0), 2 * fd[n])
        return f

    def _interval(self, time: float) -> int:
        return min(max(bisect.bisect_left(self.times, time), 1), len(self.times) - 1)

    @staticmethod
    def _g(x: float, g0: float, g1: float) -> tuple[float, float]:
        """The correction and its integral from 0 to x, for end values g0 and g1."""
        if g0 == 0 and g1 == 0:
            return 0.0, 0.0
        if (g0 < 0 and -0.5 * g0 <= g1 <= -2 * g0) or (g0 > 0 and -0.5 * g0 >= g1 >= -2 * g0):
            # region (i): a plain quadratic already stays within its bounds
            value = g0 * (1 - 4 * x + 3 * x * x) + g1 * (-2 * x + 3 * x * x)
            integral = g0 * (x - 2 * x * x + x**3) + g1 * (-(x * x) + x**3)
            return value, integral
        if (g0 < 0 and g1 > -2 * g0) or (g0 > 0 and g1 < -2 * g0):
            # region (ii): flat, then a quadratic up to g1
            eta = (g1 + 2 * g0) / (g1 - g0)
            if x <= eta:
                return g0, g0 * x
            s = (x - eta) / (1 - eta)
            return g0 + (g1 - g0) * s * s, g0 * x + (g1 - g0) * (x - eta) ** 3 / (3 * (1 - eta) ** 2)
        if (g0 > 0 and 0 > g1 > -0.5 * g0) or (g0 < 0 and 0 < g1 < -0.5 * g0):
            # region (iii): a quadratic from g0, then flat at g1
            eta = 3 * g1 / (g1 - g0)
            if x < eta:
                s = (eta - x) / eta
                return g1 + (g0 - g1) * s * s, g1 * x + (g0 - g1) * (eta**3 - (eta - x) ** 3) / (3 * eta * eta)
            return g1, g1 * x + (g0 - g1) * eta / 3
        # region (iv): g0 and g1 share a sign - two quadratics meeting at a level A
        eta = g1 / (g1 + g0)
        level = -g0 * g1 / (g0 + g1)
        if x < eta:
            s = (eta - x) / eta
            return level + (g0 - level) * s * s, level * x + (g0 - level) * (eta**3 - (eta - x) ** 3) / (3 * eta * eta)
        s = (x - eta) / (1 - eta)
        return (
            level + (g1 - level) * s * s,
            level * x + (g0 - level) * eta / 3 + (g1 - level) * (x - eta) ** 3 / (3 * (1 - eta) ** 2),
        )

    def _evaluate(self, time: float) -> tuple[float, float]:
        if time <= 0:
            return self.nodes[0], 0.0
        last = len(self.times) - 1
        if time >= self.times[last]:
            forward = self.nodes[last]
            return forward, self.integrals[last] + forward * (time - self.times[last])
        i = self._interval(time)
        start, end = self.times[i - 1], self.times[i]
        span = end - start
        x = (time - start) / span
        g, big_g = self._g(x, self.nodes[i - 1] - self.discrete[i], self.nodes[i] - self.discrete[i])
        return self.discrete[i] + g, self.integrals[i - 1] + self.discrete[i] * (time - start) + span * big_g

    def forward(self, time: float) -> float:
        """The instantaneous forward rate at a time."""
        return self._evaluate(time)[0]

    def integral(self, time: float) -> float:
        """The integral of the forward from 0 to ``time``: ``r(t) * t``."""
        return self._evaluate(time)[1]

    def zero_rate(self, time: float) -> float:
        """The continuously compounded zero rate at a time."""
        if time <= 0:
            return self.nodes[0]
        return self.integral(time) / time
