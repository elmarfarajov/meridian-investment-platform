"""Parametric yield curves: Nelson-Siegel (1987) and Svensson (1994).

A bootstrapped curve passes through every quote, including the noise in them. A
parametric curve does not try to. Four or six numbers describe the whole term
structure, and each has an economic reading:

- ``beta0`` is the **level**: the rate the curve tends to at very long maturities;
- ``beta1`` is the **slope**: the short end sits at ``beta0 + beta1``;
- ``beta2`` is a **hump** (curvature) peaking around maturity ``tau1``;
- ``beta3`` and ``tau2`` (Svensson's addition) are a second hump, for the long end.

The zero-coupon yield, continuously compounded, is::

    y(t) = b0 + b1 * L(t/tau1) + b2 * (L(t/tau1) - exp(-t/tau1)) + b3 * (L(t/tau2) - exp(-t/tau2))
    L(x) = (1 - exp(-x)) / x

The instantaneous forward is ``b0 + b1 e^(-t/tau1) + b2 (t/tau1) e^(-t/tau1) + b3 (t/tau2) e^(-t/tau2)``.

This is the model the Federal Reserve Board publishes daily (Gurkaynak, Sack and
Wright, 2007), and most central banks report a variant of it to the BIS. Two checks
keep it honest here. The formula reproduces the Fed's published yields from its
published parameters. And a curve fitted to the Treasury's own par yields is set
beside the Fed's fit of the same market on the same day.

Fitting minimises squared **par-yield** errors - the quantity actually quoted - so
each trial curve is converted to par yields before it is compared. The problem is
linear in the betas for fixed taus, which gives a reliable start: a grid over the
taus, with the betas by linear least squares on the bootstrapped zero rates. A
bounded Levenberg-Marquardt-style refinement follows (``scipy.optimize.least_squares``,
trust-region reflective). The Svensson fit is famous for multiple local minima; the
grid is what makes it repeatable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import least_squares

from ..core.exceptions import ValidationError


def _loading(x: np.ndarray) -> np.ndarray:
    """(1 - e^-x) / x, with its limit 1 at x = 0."""
    out = np.ones_like(x)
    small = np.abs(x) < 1e-8
    out[~small] = -np.expm1(-x[~small]) / x[~small]
    return out


@dataclass(frozen=True, slots=True)
class NelsonSiegelSvensson:
    """A Svensson curve; with ``beta3 = 0`` it is Nelson-Siegel. Rates are decimals, taus years."""

    beta0: float
    beta1: float
    beta2: float
    beta3: float = 0.0
    tau1: float = 1.5
    tau2: float = 10.0

    @property
    def is_nelson_siegel(self) -> bool:
        return self.beta3 == 0.0

    @property
    def parameters(self) -> tuple[float, float, float, float, float, float]:
        return (self.beta0, self.beta1, self.beta2, self.beta3, self.tau1, self.tau2)

    def loadings(self, times: Sequence[float] | np.ndarray) -> np.ndarray:
        """The (n x 4) matrix of factor loadings, so that zero yields = loadings @ betas."""
        t = np.asarray(times, dtype=float)
        x1, x2 = t / self.tau1, t / self.tau2
        l1, l2 = _loading(x1), _loading(x2)
        return np.column_stack([np.ones_like(t), l1, l1 - np.exp(-x1), l2 - np.exp(-x2)])

    def zero_rates(self, times: Sequence[float] | np.ndarray) -> np.ndarray:
        """Continuously compounded zero yields."""
        return self.loadings(times) @ np.array([self.beta0, self.beta1, self.beta2, self.beta3])

    def zero_rate(self, time: float) -> float:
        return float(self.zero_rates([time])[0])

    def forwards(self, times: Sequence[float] | np.ndarray) -> np.ndarray:
        """Instantaneous forward rates."""
        t = np.asarray(times, dtype=float)
        e1, e2 = np.exp(-t / self.tau1), np.exp(-t / self.tau2)
        return self.beta0 + self.beta1 * e1 + self.beta2 * (t / self.tau1) * e1 + self.beta3 * (t / self.tau2) * e2

    def discount_factors(self, times: Sequence[float] | np.ndarray) -> np.ndarray:
        t = np.asarray(times, dtype=float)
        return np.exp(-self.zero_rates(t) * t)

    def par_yields(self, tenors: Sequence[float] | np.ndarray, frequency: int = 2) -> np.ndarray:
        """Bond-equivalent par yields, the way the Treasury quotes its curve.

        Inside one coupon period the par yield is the money-market rate on a simple
        basis; beyond it, the coupon that prices a bond paying ``frequency`` times a
        year to par.
        """
        result = []
        step = 1.0 / frequency
        for tenor in np.asarray(tenors, dtype=float):
            if tenor <= step + 1e-9:
                factor = float(self.discount_factors([tenor])[0])
                result.append((1 / factor - 1) / tenor)
                continue
            count = round(tenor * frequency)
            times = tenor - step * np.arange(count)[::-1]
            factors = self.discount_factors(times)
            result.append(frequency * (1 - factors[-1]) / factors.sum())
        return np.array(result)

    @classmethod
    def from_gsw(
        cls, beta0: float, beta1: float, beta2: float, beta3: float, tau1: float, tau2: float
    ) -> NelsonSiegelSvensson:
        """From the Federal Reserve's published parameters, which are in percent."""
        return cls(beta0 / 100, beta1 / 100, beta2 / 100, beta3 / 100, tau1, tau2)


@dataclass(frozen=True, slots=True)
class CurveFit:
    """A fitted curve, with what it was fitted to and how well it fits."""

    model: NelsonSiegelSvensson
    tenors: tuple[float, ...]
    observed: tuple[float, ...]
    fitted: tuple[float, ...]
    kind: str

    @property
    def residuals_bp(self) -> np.ndarray:
        return (np.array(self.observed) - np.array(self.fitted)) * 10_000

    @property
    def rmse_bp(self) -> float:
        return float(np.sqrt(np.mean(self.residuals_bp**2)))

    @property
    def max_error_bp(self) -> float:
        return float(np.max(np.abs(self.residuals_bp)))


_TAU1_GRID = (0.3, 0.6, 1.0, 1.5, 2.0, 3.0, 5.0)
_TAU2_GRID = (4.0, 7.0, 10.0, 15.0, 25.0)


def _linear_betas(
    times: np.ndarray, zeros: np.ndarray, tau1: float, tau2: float, svensson: bool
) -> NelsonSiegelSvensson:
    model = NelsonSiegelSvensson(0, 0, 0, 0, tau1, tau2)
    design = model.loadings(times)
    if not svensson:
        design = design[:, :3]
    betas, *_ = np.linalg.lstsq(design, zeros, rcond=None)
    padded = [*betas, 0.0] if not svensson else list(betas)
    return replace(model, beta0=padded[0], beta1=padded[1], beta2=padded[2], beta3=padded[3])


def fit_par_curve(
    tenors: Sequence[float],
    par_yields: Sequence[float],
    *,
    svensson: bool = True,
    frequency: int = 2,
    starting_zeros: Sequence[float] | None = None,
) -> CurveFit:
    """Fit Nelson-Siegel (``svensson=False``) or Svensson to par yields in decimals.

    ``starting_zeros`` - zero rates at the same tenors, from a bootstrap - seed the
    grid search. Without them the par yields themselves are used, which is a fair
    first guess on an upward-sloping curve and a poorer one on an inverted curve.
    """
    t = np.asarray(tenors, dtype=float)
    observed = np.asarray(par_yields, dtype=float)
    needed = 6 if svensson else 4
    if len(t) < needed:
        raise ValidationError(f"A {'Svensson' if svensson else 'Nelson-Siegel'} fit needs at least {needed} tenors")
    zeros = np.asarray(starting_zeros if starting_zeros is not None else par_yields, dtype=float)

    # 1. a grid over the taus, with the betas by linear least squares on the zeros
    grid = [(a, b) for a in _TAU1_GRID for b in _TAU2_GRID if b > a] if svensson else [(a, 10.0) for a in _TAU1_GRID]
    starts = []
    for tau1, tau2 in grid:
        candidate = _linear_betas(t, zeros, tau1, tau2, svensson)
        error = float(np.sum((candidate.par_yields(t, frequency) - observed) ** 2))
        starts.append((error, candidate))
    starts.sort(key=lambda item: item[0])

    # 2. refine the best few starts against the par yields themselves
    def residuals(x: np.ndarray) -> np.ndarray:
        b0, b1, b2, b3, tau1, tau2 = x if svensson else (*x[:3], 0.0, x[3], 10.0)
        model = NelsonSiegelSvensson(b0, b1, b2, b3, tau1, tau2)
        return model.par_yields(t, frequency) - observed

    best: NelsonSiegelSvensson | None = None
    best_cost = math.inf
    for _, start in starts[:4]:
        if svensson:
            x0 = np.array(start.parameters)
            lower, upper = [-0.2, -0.3, -0.5, -0.5, 0.05, 0.05], [0.3, 0.3, 0.5, 0.5, 30.0, 50.0]
        else:
            x0 = np.array([start.beta0, start.beta1, start.beta2, start.tau1])
            lower, upper = [-0.2, -0.3, -0.5, 0.05], [0.3, 0.3, 0.5, 30.0]
        x0 = np.clip(x0, np.array(lower) + 1e-9, np.array(upper) - 1e-9)
        solution = least_squares(
            residuals,
            x0,
            bounds=(lower, upper),
            method="trf",
            x_scale="jac",
            xtol=1e-14,
            ftol=1e-14,
            gtol=1e-14,
            max_nfev=4000,
        )
        if solution.cost < best_cost:
            best_cost = float(solution.cost)
            values = solution.x
            best = (
                NelsonSiegelSvensson(*values)
                if svensson
                else NelsonSiegelSvensson(values[0], values[1], values[2], 0.0, values[3], 10.0)
            )
    assert best is not None
    return CurveFit(
        best,
        tuple(float(x) for x in t),
        tuple(float(y) for y in observed),
        tuple(float(y) for y in best.par_yields(t, frequency)),
        "Svensson" if svensson else "Nelson-Siegel",
    )
