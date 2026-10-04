"""Meridian's risk building blocks reconciled against independent references.

Each check runs Meridian's own function and the reference on the same input:

- **the Basel Committee's traffic-light table** (1996): zone, plus factor and the
  printed cumulative probability, for every count from 0 to 10 exceptions;
- **arch**, the GARCH package: Meridian's ``garch_filter`` against ``arch``'s own
  conditional volatilities and one-day forecast, with ``arch``'s fitted
  parameters and backcast, on the last six years of US daily returns;
- **pandas**: the exponentially weighted variance of ``EwmaState`` against
  ``ewm(adjust=True)``, on the same returns;
- **scikit-learn**: Ledoit-Wolf shrinkage towards the identity;
- **PyPortfolioOpt**: Ledoit-Wolf towards constant correlation. PyPortfolioOpt
  ports Ledoit and Wolf's own ``covCor.m`` but feeds it the unbiased sample
  covariance, where the original divides by T. Given the maximum-likelihood
  sample the original uses, it agrees with Meridian exactly; with its own, it
  differs, and the difference is recorded as a convention, not a break.

arch, pandas and scikit-learn are dependencies already; PyPortfolioOpt is a
development dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..marketdata.french import french_daily
from ..risk.covariance import EwmaState, ledoit_wolf, ledoit_wolf_constant_correlation
from ..risk.garch import GarchFit, garch_filter
from ..risk.validation import cumulative_probability, traffic_light

TOLERANCE = 1e-12

#: Basel Committee on Banking Supervision (1996), Table 2: exceptions -> (zone, plus factor, cumulative %).
BASEL_TABLE: dict[int, tuple[str, float, float]] = {
    0: ("green", 0.00, 8.11), 1: ("green", 0.00, 28.58), 2: ("green", 0.00, 54.32), 3: ("green", 0.00, 75.81),
    4: ("green", 0.00, 89.22), 5: ("yellow", 0.40, 95.88), 6: ("yellow", 0.50, 98.63), 7: ("yellow", 0.65, 99.60),
    8: ("yellow", 0.75, 99.89), 9: ("yellow", 0.85, 99.97), 10: ("red", 1.00, 99.99),
}  # fmt: skip


@dataclass(frozen=True)
class Check:
    reference: str
    subject: str
    meridian: float
    theirs: float
    tolerance: float = TOLERANCE
    convention: str = ""  # set when the two differ by a documented choice rather than an error

    @property
    def difference(self) -> float:
        return abs(self.meridian - self.theirs)

    @property
    def agrees(self) -> bool:
        return self.difference <= self.tolerance


def basel_checks() -> list[Check]:
    checks = []
    for count, (zone, plus, cumulative) in BASEL_TABLE.items():
        light = traffic_light(count)
        checks.append(Check("Basel Committee (1996)", f"{count} exceptions: multiplier", light.multiplier, 3.0 + plus))
        checks.append(
            Check(
                "Basel Committee (1996)",
                f"{count} exceptions: cumulative probability (%)",
                round(cumulative_probability(count) * 100, 2),
                cumulative,
                1e-9,
            )
        )
        checks.append(
            Check("Basel Committee (1996)", f"{count} exceptions: zone is {zone}", float(light.zone == zone), 1.0)
        )
    return checks


def _returns() -> np.ndarray:
    return french_daily().market[-1500:]


def arch_checks() -> list[Check]:
    from arch import arch_model

    returns = _returns()
    scaled = returns * 100.0
    model = arch_model(scaled, mean="Zero", vol="GARCH", p=1, q=1, dist="t", rescale=False)
    result = model.fit(disp="off", show_warning=False)
    params = result.params
    fit = GarchFit(float(params["omega"]), float(params["alpha[1]"]), float(params["beta[1]"]), float(params["nu"]))
    backcast = float(model.volatility.backcast(np.asarray(result.resid)))
    ours = garch_filter(scaled, fit, backcast)
    theirs = np.asarray(result.conditional_volatility)
    forecast_ours = fit.omega + fit.alpha * scaled[-1] ** 2 + fit.beta * ours[-1] ** 2
    forecast_theirs = float(result.forecast(horizon=1, reindex=False).variance.values[-1, 0])
    return [
        Check(
            "arch",
            "GARCH(1,1) conditional volatility, largest gap over 1,500 days",
            float(np.abs(ours - theirs).max()),
            0.0,
            1e-12,
        ),
        Check("arch", "GARCH(1,1) one-day variance forecast", forecast_ours, forecast_theirs, 1e-12),
    ]


def pandas_checks() -> list[Check]:
    import pandas as pd

    returns = _returns()
    state = EwmaState.start(1)
    ours = []
    for value in returns:
        state.update(np.array([value]))
        ours.append(float(state.variances()[0]))
    theirs = pd.Series(returns**2).ewm(alpha=1.0 - state.vol_decay, adjust=True).mean().to_numpy()
    relative = float(np.max(np.abs(np.array(ours) - theirs) / theirs))
    return [Check("pandas", "EWMA variance, half-life 42 days, largest relative gap", relative, 0.0, 1e-12)]


def _industry_window() -> np.ndarray:
    return french_daily().returns[-252:]


def sklearn_checks() -> list[Check]:
    from sklearn.covariance import LedoitWolf

    window = _industry_window()
    reference = LedoitWolf().fit(window)
    ours = ledoit_wolf(window)
    return [
        Check("scikit-learn", "Ledoit-Wolf intensity (identity target)", ours.intensity, float(reference.shrinkage_)),
        Check(
            "scikit-learn",
            "Ledoit-Wolf covariance, largest gap",
            float(np.abs(ours.covariance - reference.covariance_).max()),
            0.0,
            1e-15,
        ),
    ]


def pypfopt_checks() -> list[Check]:
    import pandas as pd
    from pypfopt.risk_models import CovarianceShrinkage

    window = _industry_window()
    ours = ledoit_wolf_constant_correlation(window)
    shrinkage: Any = CovarianceShrinkage(pd.DataFrame(window), returns_data=True, frequency=1)
    shrinkage.ledoit_wolf("constant_correlation")
    as_shipped = float(shrinkage.delta)
    centred = window - window.mean(axis=0)
    shrinkage.S = centred.T @ centred / len(window)  # the maximum-likelihood sample covCor.m divides by T for
    recombined = shrinkage.ledoit_wolf("constant_correlation").to_numpy()
    return [
        Check(
            "PyPortfolioOpt",
            "Ledoit-Wolf intensity (constant correlation), as shipped",
            ours.intensity,
            as_shipped,
            1e-12,
            convention="PyPortfolioOpt feeds covCor.m the unbiased sample covariance (T - 1)",
        ),
        Check(
            "PyPortfolioOpt",
            "the same, given the maximum-likelihood sample covCor.m uses",
            ours.intensity,
            float(shrinkage.delta),
        ),
        Check(
            "PyPortfolioOpt",
            "constant-correlation covariance, largest gap",
            float(np.abs(ours.covariance - recombined).max()),
            0.0,
            1e-15,
        ),
    ]


def reconciliation() -> list[Check]:
    return [*basel_checks(), *arch_checks(), *pandas_checks(), *sklearn_checks(), *pypfopt_checks()]
