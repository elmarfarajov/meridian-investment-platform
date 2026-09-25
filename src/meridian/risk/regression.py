"""The cross-sectional regression: each day, what the market paid each factor.

On every day the stocks' returns are regressed on their exposures at the start
of the day. The coefficients are that day's factor returns; what is left over
is each stock's specific return. Three details make the regression work:

* **Weights.** Small stocks have larger, noisier specific returns. Weighted
  least squares with weights proportional to the square root of market
  capitalisation - roughly the inverse of specific variance - keeps them from
  dominating, without letting the largest companies decide everything.
* **The industry constraint.** Every stock has exposure one to the world factor
  and one to its industry, so the world column is the sum of the industry
  columns and the regression is singular. The constraint that the
  capitalisation-weighted industry returns sum to zero removes the redundancy
  and gives the factors their meaning: the world factor is the cap-weighted
  market, and an industry factor is how that industry did *relative* to it.
* **Timing.** Exposures are those known at the start of the day; a regression on
  end-of-day exposures would let the day's return leak into its own
  explanation.

The constraint is imposed by substitution: the largest industry's return is
written in terms of the others, the regression is solved in the reduced
parameters, and the full set is recovered - an exact solution of the
constrained problem, not a penalty.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.exceptions import ValidationError


@dataclass(frozen=True)
class CrossSection:
    """One day's regression."""

    factor_returns: np.ndarray  # K: world, industries, styles
    residuals: np.ndarray  # N
    r_squared: float
    t_stats: np.ndarray  # K
    standard_errors: np.ndarray  # K


def constraint_matrix(industry_caps: np.ndarray) -> tuple[np.ndarray, int]:
    """The map from free industry returns to all of them, with the largest industry dependent.

    Returns ``(C, dependent)`` where ``C`` is K x (K - 1) and ``caps @ C @ g == 0``
    for every ``g``. Industries with no capitalisation get a zero return.
    """
    count = len(industry_caps)
    dependent = int(np.argmax(industry_caps))
    if industry_caps[dependent] <= 0:
        raise ValidationError("the industry constraint needs at least one industry with capitalisation")
    matrix = np.zeros((count, count - 1))
    free = [index for index in range(count) if index != dependent]
    for column, index in enumerate(free):
        matrix[index, column] = 1.0
        matrix[dependent, column] = -industry_caps[index] / industry_caps[dependent]
    return matrix, dependent


def regress(
    returns: np.ndarray,
    world: np.ndarray,
    industries: np.ndarray,
    styles: np.ndarray,
    caps: np.ndarray,
) -> CrossSection:
    """Constrained weighted least squares of one day's returns on the start-of-day exposures."""
    count = len(returns)
    if count <= industries.shape[1] + styles.shape[1] + 1:
        raise ValidationError("more factors than stocks: the regression is not identified")
    industry_caps = industries.T @ caps
    constraint, _ = constraint_matrix(industry_caps)
    reduced = np.column_stack([world, industries @ constraint, styles])
    weights = np.sqrt(caps)
    weights = weights / weights.sum()
    root = np.sqrt(weights)
    solution, *_ = np.linalg.lstsq(reduced * root[:, None], returns * root, rcond=None)

    ind_count, style_count = industries.shape[1], styles.shape[1]
    transform = np.zeros((1 + ind_count + style_count, 1 + (ind_count - 1) + style_count))
    transform[0, 0] = 1.0
    transform[1 : 1 + ind_count, 1:ind_count] = constraint
    transform[1 + ind_count :, ind_count:] = np.eye(style_count)
    factor_returns = transform @ solution

    full = np.column_stack([world, industries, styles])
    residuals = returns - full @ factor_returns
    mean = float(weights @ returns)
    total = float(weights @ (returns - mean) ** 2)
    explained = 1.0 - float(weights @ residuals**2) / total if total > 0 else 0.0

    dof = max(count - reduced.shape[1], 1)
    sigma2 = float(weights @ residuals**2) * count / dof
    gram = (reduced * weights[:, None]).T @ reduced * count
    try:
        covariance = transform @ np.linalg.pinv(gram) @ transform.T * sigma2
    except np.linalg.LinAlgError:  # pragma: no cover - pinv does not fail on finite input
        covariance = np.full((len(factor_returns), len(factor_returns)), np.nan)
    errors = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        t_stats = np.where(errors > 0, factor_returns / errors, 0.0)
    return CrossSection(factor_returns, residuals, explained, t_stats, errors)
