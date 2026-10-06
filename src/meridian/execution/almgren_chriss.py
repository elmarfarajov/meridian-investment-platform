"""Optimal execution: the Almgren-Chriss trajectory and its efficient frontier.

Selling X shares over a horizon T trades two costs against each other. Trading
fast pays market impact; trading slowly leaves the position exposed to the
price moving. Almgren and Chriss (2000) make that precise with linear impact:

* temporary impact ``ε sign(n) + η n / τ`` per share on each slice of ``n``
  shares traded in an interval ``τ``, and
* permanent impact ``γ`` per share traded, and
* an unaffected price that is a random walk with variance ``σ²`` per unit time.

The expected cost and its variance of a trajectory ``x_0 = X, ..., x_N = 0``
(shares still held) are

    E = ½ γ X² + ε X + (η̃ / τ) Σ n_j²,    V = σ² τ Σ x_j²,    η̃ = η − ½ γ τ,

and minimising ``E + λ V`` gives the closed form

    x_j = X sinh(κ (T − t_j)) / sinh(κ T),    2 (cosh(κ τ) − 1) / τ² = λ σ² / η̃.

``λ = 0`` is the risk-neutral trader, who trades evenly (TWAP); a larger ``λ``
front-loads the order to cut its exposure. Sweeping ``λ`` traces the efficient
frontier of expected cost against its standard deviation, the execution
counterpart of Markowitz's.

The simulator in :mod:`.market` uses square-root temporary impact, which is
closer to the evidence; the linear ``η`` here is the one that matches it at the
order's own average participation, so the trajectory is optimal for the
simulator to first order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.exceptions import ValidationError


@dataclass(frozen=True)
class ExecutionProblem:
    shares: float  # X, positive
    horizon: float  # T, in minutes
    intervals: int  # N
    sigma: float  # price volatility per minute, in price units (so sigma^2 is variance per minute)
    eta: float  # temporary impact, price units per (share per minute)
    gamma: float = 0.0  # permanent impact, price units per share
    epsilon: float = 0.0  # fixed cost per share: half the spread

    def __post_init__(self) -> None:
        if self.shares <= 0 or self.horizon <= 0 or self.intervals < 1:
            raise ValidationError("an execution problem needs shares, a horizon and at least one interval")
        if self.eta_tilde <= 0:
            raise ValidationError("temporary impact must exceed half the permanent impact per interval")

    @property
    def tau(self) -> float:
        return self.horizon / self.intervals

    @property
    def eta_tilde(self) -> float:
        return self.eta - 0.5 * self.gamma * self.tau

    def kappa(self, risk_aversion: float) -> float:
        if risk_aversion <= 0:
            return 0.0
        kappa_tilde_sq = risk_aversion * self.sigma**2 / self.eta_tilde
        return math.acosh(1.0 + 0.5 * kappa_tilde_sq * self.tau**2) / self.tau

    def holdings(self, risk_aversion: float) -> np.ndarray:
        """x_0 .. x_N: shares still to trade at each interval boundary."""
        times = np.linspace(0.0, self.horizon, self.intervals + 1)
        kappa = self.kappa(risk_aversion)
        if kappa * self.horizon < 1e-9:
            return self.shares * (1.0 - times / self.horizon)
        if kappa * self.horizon > 700:  # sinh overflows; the trader is so urgent it trades at once
            output = np.zeros_like(times)
            output[0] = self.shares
            return output
        return self.shares * np.sinh(kappa * (self.horizon - times)) / math.sinh(kappa * self.horizon)

    def trades(self, risk_aversion: float) -> np.ndarray:
        """n_1 .. n_N: shares traded in each interval."""
        return -np.diff(self.holdings(risk_aversion))

    def expected_cost(self, risk_aversion: float) -> float:
        n = self.trades(risk_aversion)
        return 0.5 * self.gamma * self.shares**2 + self.epsilon * self.shares + self.eta_tilde / self.tau * float(n @ n)

    def variance(self, risk_aversion: float, autocorrelation: float = 0.0) -> float:
        """The variance of the cost: ``σ² τ Σ x_k²`` for a random walk.

        ``autocorrelation`` is the correlation of one interval's price move with
        the next. A position held through two intervals that move together is
        riskier than the random walk says, by ``2 ρ σ² τ Σ x_k x_{k+1}``. Daily
        index returns had a lag-one correlation near 0.3 in the 1970s, and the
        random-walk variance understated the cost's spread accordingly. The
        trajectory itself is still the random walk's optimum; only its risk is
        restated.
        """
        if not -1.0 < autocorrelation < 1.0:
            raise ValidationError("an autocorrelation must lie strictly between -1 and 1")
        x = self.holdings(risk_aversion)[1:]
        variance = float(x @ x) + 2.0 * autocorrelation * float(x[:-1] @ x[1:])
        return self.sigma**2 * self.tau * max(variance, 0.0)

    def frontier(self, risk_aversions: np.ndarray) -> list[tuple[float, float, float]]:
        """(risk aversion, expected cost, standard deviation of cost) along the efficient frontier."""
        return [
            (float(level), self.expected_cost(float(level)), math.sqrt(self.variance(float(level))))
            for level in risk_aversions
        ]

    def half_life(self, risk_aversion: float) -> float:
        """The time for the order to be half done, in minutes: how urgent the trajectory is."""
        kappa = self.kappa(risk_aversion)
        return self.horizon / 2 if kappa == 0 else math.log(2) / kappa


def linear_eta(temporary: float, sigma_daily: float, price: float, rate: float, bar_volume: float) -> float:
    """The linear eta matching square-root impact ``temporary · σ · √(v / V)`` at trading rate ``v`` per minute.

    Square-root cost per share at rate v is ``price · temporary · σ · √(v / V)``;
    a linear model charges ``η v``. Equal at the order's own rate, ``η = cost / v``.
    """
    if rate <= 0 or bar_volume <= 0:
        raise ValidationError("the matching rate and volume must be positive")
    return price * temporary * sigma_daily * math.sqrt(rate / bar_volume) / rate
