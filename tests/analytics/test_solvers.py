"""Root finding, including the cases where plain Newton fails."""

from __future__ import annotations

import math

import pytest

from meridian.analytics.solvers import bisect, find_bracket, newton, solve
from meridian.core.exceptions import ConvergenceError, ValidationError


def quadratic(x: float) -> float:
    return x * x - 2.0


def test_newton_finds_a_root_with_an_analytic_derivative():
    root = newton(quadratic, 1.0, derivative=lambda x: 2 * x)
    # The solver's tolerance is on the function value, so the root is accurate to its square root
    assert root == pytest.approx(math.sqrt(2), abs=1e-9)
    assert abs(quadratic(root)) < 1e-10


def test_newton_works_from_a_numerical_derivative():
    assert newton(quadratic, 1.0) == pytest.approx(math.sqrt(2), abs=1e-8)


def test_newton_raises_rather_than_returning_a_non_converged_estimate():
    with pytest.raises(ConvergenceError) as error:
        newton(lambda x: math.exp(x) + 1.0, 0.0, max_iterations=12)  # no real root
    assert error.value.iterations == 12
    assert "did not converge" in str(error.value)


def test_newton_stops_on_a_flat_derivative():
    with pytest.raises(ConvergenceError):
        newton(lambda x: 1.0, 0.0, derivative=lambda x: 0.0)


def test_bisection_finds_the_root_inside_a_bracket():
    assert bisect(quadratic, 0.0, 2.0) == pytest.approx(math.sqrt(2), abs=1e-9)


def test_bisection_requires_a_sign_change():
    with pytest.raises(ValidationError, match="sign change"):
        bisect(quadratic, 2.0, 3.0)


def test_find_bracket_expands_until_it_straddles_a_root():
    low, high = find_bracket(quadratic, 0.5)
    assert quadratic(low) * quadratic(high) < 0


def test_find_bracket_gives_up_on_a_function_with_no_root():
    with pytest.raises(ValidationError, match="bracket"):
        find_bracket(lambda x: x * x + 1.0, 0.0)


def test_safeguarded_solve_matches_newton_on_a_well_behaved_function():
    assert solve(quadratic, 1.0, bracket=(0.0, 2.0)) == pytest.approx(math.sqrt(2), abs=1e-9)


def test_safeguarded_solve_survives_a_function_that_defeats_newton():
    """A function whose derivative sends Newton far outside the bracket."""

    def awkward(x: float) -> float:
        return math.atan(1_000 * (x - 0.3))

    assert solve(awkward, 5.0, bracket=(-1.0, 6.0)) == pytest.approx(0.3, abs=1e-6)


def test_safeguarded_solve_validates_the_bracket():
    with pytest.raises(ValidationError, match="sign change"):
        solve(quadratic, 2.5, bracket=(2.0, 3.0))


def test_solve_without_a_bracket_finds_one_itself():
    assert solve(lambda x: (1 + x) ** 5 - 1.5, 0.05) == pytest.approx(1.5 ** (1 / 5) - 1, abs=1e-9)


def test_solve_falls_back_to_newton_when_no_bracket_exists():
    with pytest.raises(ConvergenceError):
        solve(lambda x: x * x + 1.0, 0.5, max_iterations=20)
