"""The risk run: estimate, forecast, check, store.

After the performance run, the risk run stores what a risk report and its
backtest need: the model's factor return history, every morning's forecast for
the account with the day's outcome, and the report date's exposures. Before
anything is written it checks the controls a risk team would sign off:

* every decomposition adds up to its total (Euler's theorem, to 1e-10);
* every forecast is finite and positive;
* the VaR backtest over the last 250 days is not in the Basel red zone.

A failed control writes nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..core.exceptions import ValidationError
from ..persistence.repositories import UnitOfWork, seed_reference_data
from ..risk.factors import group_of
from ..risk.validation import kupiec, summarise_bias, traffic_light
from ..seed import demo_book
from .demo_risk import DemoRisk

MODEL_ID = "MERIDIAN-GLOBAL-EQUITY-EWMA"
TOLERANCE = 1e-10


@dataclass
class RiskRunResult:
    portfolio_id: str
    model_id: str
    volatility: float
    tracking_error: float
    var_99: float
    total_bias: float
    active_bias: float
    exceptions: int
    scored_days: int
    zone: str
    stored: dict[str, int] = field(default_factory=dict)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("portfolio", self.portfolio_id),
            ("risk model", self.model_id),
            ("forecast volatility", f"{self.volatility:.2%}"),
            ("forecast tracking error", f"{self.tracking_error:.2%}"),
            ("1-day 99% VaR (parametric)", f"{self.var_99:.2%}"),
            ("bias statistic, total risk", f"{self.total_bias:.3f}"),
            ("bias statistic, active risk", f"{self.active_bias:.3f}"),
            ("VaR exceptions", f"{self.exceptions} in {self.scored_days} days"),
            ("Basel zone, last 250 days", self.zone),
        ]
        rows += [(f"{table} rows stored", f"{count:,}") for table, count in self.stored.items()]
        return rows


def check(risk: DemoRisk) -> None:
    for name, decomposition in (("portfolio", risk.portfolio), ("benchmark", risk.benchmark), ("active", risk.active)):
        total = decomposition.volatility
        if (
            abs(sum(decomposition.by_group().values()) - total) > TOLERANCE
            or abs(sum(decomposition.by_asset().values()) - total) > TOLERANCE
        ):
            raise ValidationError(f"the {name} risk decomposition does not add up; nothing written")
    for item in risk.book_forecasts:
        if not (math.isfinite(item.volatility) and item.volatility > 0 and math.isfinite(item.tracking_error)):
            raise ValidationError(f"the forecast for {item.day} is not a positive number; nothing written")
    hits = [item.exception for item in risk.book_forecasts[-250:]]
    if traffic_light(sum(hits)).zone == "red":
        raise ValidationError("the VaR backtest is in the Basel red zone; nothing written")


def run_demo_risk(risk: DemoRisk, unit_of_work: UnitOfWork | None = None) -> RiskRunResult:
    check(risk)
    forecasts = risk.book_forecasts
    hits = [item.exception for item in forecasts]
    portfolio_id = risk.performance.accounting.portfolio.portfolio_id
    outcome = RiskRunResult(
        portfolio_id=portfolio_id,
        model_id=MODEL_ID,
        volatility=risk.portfolio.volatility,
        tracking_error=risk.active.volatility,
        var_99=risk.var_estimates[0].var,
        total_bias=summarise_bias("total", np.array([item.realised / item.volatility for item in forecasts])).bias,
        active_bias=summarise_bias("active", np.array([item.active / item.tracking_error for item in forecasts])).bias,
        exceptions=sum(hits),
        scored_days=len(forecasts),
        zone=traffic_light(sum(hits[-250:])).zone,
    )
    _ = kupiec(outcome.exceptions, outcome.scored_days)  # computable, or the counts are inconsistent
    if unit_of_work is None:
        return outcome
    if unit_of_work.portfolios.find(portfolio_id) is None:
        reference = demo_book()
        seed_reference_data(
            unit_of_work,
            instruments=reference.instruments,
            benchmarks=reference.benchmarks,
            clients=reference.clients,
            households=reference.households,
            accounts=reference.accounts,
            portfolios=reference.portfolios,
        )
        unit_of_work.portfolios.add(risk.performance.accounting.portfolio)
        unit_of_work.flush()
    repository = unit_of_work.risk
    outcome.stored["factor return"] = repository.replace_factor_returns(
        MODEL_ID, risk.estimated.days, risk.factors.names, risk.estimated.returns
    )
    outcome.stored["forecast"] = repository.replace_forecasts(portfolio_id, MODEL_ID, forecasts)
    contributions = risk.active.by_factor()
    exposure_rows = [
        (
            name,
            group_of(name),
            float(risk.portfolio.exposures[index]),
            float(risk.benchmark.exposures[index]),
            contributions[name],
        )
        for index, name in enumerate(risk.factors.names)
    ]
    outcome.stored["exposure"] = repository.replace_exposures(portfolio_id, risk.model.as_of, exposure_rows)
    unit_of_work.flush()
    return outcome
