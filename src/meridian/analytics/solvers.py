"""Root finding.

Yield to maturity, internal rate of return and implied volatility are all the same
problem: find the rate at which a pricing function returns the observed price.
There is no closed form, so it is solved numerically, and the quality of the
solver is the difference between an answer and a plausible-looking wrong number.

The approach here is Newton-Raphson with a bisection safety net. Newton converges
quadratically when it works and diverges spectacularly when the derivative is
small or the function is not locally well behaved - a deeply discounted bond, a
cash flow stream that changes sign more than once. Bisection cannot diverge but is
slow. Taking Newton steps only while they stay inside a bracket that is known to
contain a root, and falling back to bisection when they do not, gives the speed of
one and the guarantees of the other.

Failure is an exception, never a returned last iterate: a yield that did not
converge is worse than no yield at all.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from ..core.exceptions import ConvergenceError, ValidationError

DEFAULT_TOLERANCE = 1e-10
DEFAULT_MAX_ITERATIONS = 100


def _numerical_derivative(function: Callable[[float], float], x: float, step: float = 1e-6) -> float:
    """Central difference, scaled to the magnitude of x so it works for rates and for prices."""
    h = step * max(abs(x), 1.0)
    return (function(x + h) - function(x - h)) / (2 * h)


def newton(
    function: Callable[[float], float],
    guess: float,
    *,
    derivative: Callable[[float], float] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    label: str = "Newton solve",
) -> float:
    """Plain Newton-Raphson. Raises rather than returning a non-converged estimate."""
    x = guess
    for _ in range(max_iterations):
        value = function(x)
        if abs(value) < tolerance:
            return x
        slope = derivative(x) if derivative else _numerical_derivative(function, x)
        if slope == 0 or not math.isfinite(slope):
            raise ConvergenceError(label, max_iterations, x)
        step = value / slope
        x -= step
        if not math.isfinite(x):
            raise ConvergenceError(label, max_iterations, None)
        if abs(step) < tolerance:
            return x
    raise ConvergenceError(label, max_iterations, x)


def bisect(
    function: Callable[[float], float],
    low: float,
    high: float,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = 200,
    label: str = "Bisection",
) -> float:
    """Bisection on a bracket that must contain a sign change."""
    f_low, f_high = function(low), function(high)
    if f_low * f_high > 0:
        raise ValidationError(f"{label}: the bracket [{low}, {high}] does not contain a sign change")
    for _ in range(max_iterations):
        middle = 0.5 * (low + high)
        f_middle = function(middle)
        if abs(f_middle) < tolerance or (high - low) / 2 < tolerance:
            return middle
        if f_low * f_middle < 0:
            high, f_high = middle, f_middle
        else:
            low, f_low = middle, f_middle
    raise ConvergenceError(label, max_iterations, 0.5 * (low + high))


def find_bracket(
    function: Callable[[float], float],
    guess: float,
    *,
    step: float = 0.05,
    lower_limit: float = -0.99,
    upper_limit: float = 10.0,
    max_expansions: int = 200,
) -> tuple[float, float]:
    """Expand outwards from a guess until the function changes sign."""
    low = high = guess
    f_low = f_high = function(guess)
    for _ in range(max_expansions):
        low = max(low - step, lower_limit)
        high = min(high + step, upper_limit)
        try:
            f_low = function(low)
        except (ValueError, ZeroDivisionError, OverflowError):  # a rate the pricer cannot evaluate
            f_low = math.nan
        try:
            f_high = function(high)
        except (ValueError, ZeroDivisionError, OverflowError):
            f_high = math.nan
        if math.isfinite(f_low) and f_low * f_high < 0:
            return low, high
        if math.isfinite(f_high) and f_high * function(guess) < 0:
            return guess, high
        if low <= lower_limit and high >= upper_limit:
            break
    raise ValidationError("Could not bracket a root; the target may be unreachable for any rate")


def solve(
    function: Callable[[float], float],
    guess: float = 0.05,
    *,
    derivative: Callable[[float], float] | None = None,
    bracket: tuple[float, float] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    label: str = "Solve",
) -> float:
    """Newton where it behaves, bisection where it does not.

    A Newton step is accepted only while the iterate stays inside a bracket known
    to contain a root; otherwise the step is replaced by a bisection step. This is
    the safeguarded Newton method, and it is what a pricing library should use.
    """
    if bracket is None:
        try:
            low, high = find_bracket(function, guess)
        except ValidationError:
            return newton(
                function,
                guess,
                derivative=derivative,
                tolerance=tolerance,
                max_iterations=max_iterations,
                label=label,
            )
    else:
        low, high = bracket

    f_low, f_high = function(low), function(high)
    if f_low * f_high > 0:
        raise ValidationError(f"{label}: the bracket [{low}, {high}] does not contain a sign change")

    x = min(max(guess, low), high)
    for _ in range(max_iterations):
        value = function(x)
        if abs(value) < tolerance:
            return x
        if f_low * value < 0:
            high = x
        else:
            low, f_low = x, value

        slope = derivative(x) if derivative else _numerical_derivative(function, x)
        if slope != 0 and math.isfinite(slope):
            candidate = x - value / slope
            if low < candidate < high:
                if abs(candidate - x) < tolerance:
                    return candidate
                x = candidate
                continue
        x = 0.5 * (low + high)  # the Newton step left the bracket: bisect instead
        if (high - low) / 2 < tolerance:
            return x
    raise ConvergenceError(label, max_iterations, x)
