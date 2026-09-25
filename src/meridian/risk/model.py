"""The risk model on one day, and what it says about a portfolio.

The model is three things: every asset's exposures ``X`` to the factors, the
factors' covariance ``F``, and every asset's specific variance ``D``. The
covariance of any set of assets is

    V = X F X' + D

and a portfolio with weights ``w`` has factor exposures ``x = X'w`` and variance

    w'Vw = x'Fx + w'Dw.

**Decomposition.** Risk is not additive, but its Euler decomposition is: the
contribution of each part is its weight times its marginal contribution,
``w_i (V w)_i / sigma``, and the contributions add up to the volatility exactly.
The same holds for factors - the contribution of factor k is
``x_k (F x)_k / sigma`` - so a report can say how much of the risk is the
market, how much the portfolio's industry bets, its style tilts, its currencies,
and how much is stock-specific, and the pieces sum to the total.

**Active risk** is the same calculation on the difference between portfolio and
benchmark weights: the forecast tracking error.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ..core.exceptions import ValidationError
from .factors import GROUPS, FactorSet, group_of

TRADING_DAYS = 252


@dataclass(frozen=True)
class FactorRiskModel:
    """Exposures, factor covariance and specific variances on one day. All variances are daily."""

    as_of: date
    factors: FactorSet
    factor_covariance: np.ndarray  # K x K
    exposures: dict[str, np.ndarray]  # asset -> K
    specific_variance: dict[str, float]  # asset -> daily variance
    description: str = ""

    def __post_init__(self) -> None:
        size = len(self.factors)
        if self.factor_covariance.shape != (size, size):
            raise ValidationError("the factor covariance must be K x K for the model's factors")
        missing = sorted(set(self.exposures) ^ set(self.specific_variance))
        if missing:
            raise ValidationError(f"every asset needs both exposures and a specific variance: {', '.join(missing[:5])}")

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(self.exposures)

    def exposure_matrix(self, assets: tuple[str, ...]) -> np.ndarray:
        unknown = [asset for asset in assets if asset not in self.exposures]
        if unknown:
            raise ValidationError(f"the risk model does not cover {', '.join(unknown[:5])}")
        return np.vstack([self.exposures[asset] for asset in assets]) if assets else np.zeros((0, len(self.factors)))

    def covariance(self, assets: tuple[str, ...]) -> np.ndarray:
        matrix = self.exposure_matrix(assets)
        return matrix @ self.factor_covariance @ matrix.T + np.diag([self.specific_variance[a] for a in assets])

    def factor_volatility(self, name: str) -> float:
        index = self.factors.index(name)
        return math.sqrt(float(self.factor_covariance[index, index]) * TRADING_DAYS)

    def decompose(self, weights: Mapping[str, float]) -> RiskDecomposition:
        """The Euler decomposition of a portfolio's (or an active position's) risk."""
        assets = tuple(asset for asset, weight in weights.items() if weight != 0.0)
        w = np.array([weights[asset] for asset in assets])
        matrix = self.exposure_matrix(assets)
        exposure = matrix.T @ w
        factor_part = self.factor_covariance @ exposure
        factor_variance = float(exposure @ factor_part)
        specific = np.array([self.specific_variance[asset] for asset in assets])
        specific_variance = float(np.sum(w**2 * specific))
        variance = factor_variance + specific_variance
        if variance <= 0:
            return RiskDecomposition.empty(self.as_of, self.factors)
        sigma = math.sqrt(variance)
        marginal = (matrix @ factor_part + specific * w) / sigma
        return RiskDecomposition(
            as_of=self.as_of,
            factors=self.factors,
            variance=variance,
            factor_variance=factor_variance,
            specific_variance=specific_variance,
            exposures=exposure,
            factor_contributions=exposure * factor_part / sigma,
            assets=assets,
            weights=w,
            marginal=marginal,
            asset_contributions=w * marginal,
            asset_specific=w**2 * specific / sigma,
        )


@dataclass(frozen=True)
class RiskDecomposition:
    """Where a portfolio's risk comes from; daily units, annualised by the properties."""

    as_of: date
    factors: FactorSet
    variance: float
    factor_variance: float
    specific_variance: float
    exposures: np.ndarray  # K
    factor_contributions: np.ndarray  # K, sum = factor variance / sigma
    assets: tuple[str, ...] = ()
    weights: np.ndarray = field(default_factory=lambda: np.zeros(0))
    marginal: np.ndarray = field(default_factory=lambda: np.zeros(0))  # d sigma / d w, daily
    asset_contributions: np.ndarray = field(default_factory=lambda: np.zeros(0))  # sum = sigma
    asset_specific: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @classmethod
    def empty(cls, as_of: date, factors: FactorSet) -> RiskDecomposition:
        zeros = np.zeros(len(factors))
        return cls(as_of, factors, 0.0, 0.0, 0.0, zeros, zeros)

    @property
    def volatility(self) -> float:
        """Annualised volatility (or tracking error, for an active position)."""
        return math.sqrt(self.variance * TRADING_DAYS)

    @property
    def daily(self) -> float:
        return math.sqrt(self.variance)

    @property
    def factor_share(self) -> float:
        return self.factor_variance / self.variance if self.variance else 0.0

    def annual(self, value: float) -> float:
        """A contribution in daily volatility units, annualised."""
        return value * math.sqrt(TRADING_DAYS)

    def by_group(self) -> dict[str, float]:
        """Annualised contribution to volatility of each factor group, and of specific risk."""
        sigma = math.sqrt(self.variance) if self.variance else 1.0
        groups = {group: 0.0 for group in GROUPS}
        for index, name in enumerate(self.factors.names):
            groups[group_of(name)] += self.annual(float(self.factor_contributions[index]))
        groups["Specific"] = self.annual(self.specific_variance / sigma)
        return groups

    def by_factor(self) -> dict[str, float]:
        return {
            name: self.annual(float(value))
            for name, value in zip(self.factors.names, self.factor_contributions, strict=True)
        }

    def by_asset(self) -> dict[str, float]:
        return {
            asset: self.annual(float(value)) for asset, value in zip(self.assets, self.asset_contributions, strict=True)
        }

    def exposure(self, name: str) -> float:
        return float(self.exposures[self.factors.index(name)])
