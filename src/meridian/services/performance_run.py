"""The performance run: returns and attribution, checked and stored.

After the accounting run has valued the book, the performance run computes the
daily time-weighted returns and the attribution against the benchmark, checks
that the attribution explains the active return, and stores both. The periods
stored are the ones a quarterly report needs: since inception and each calendar
year, by sector and by region.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..core.exceptions import ValidationError
from ..performance.attribution import AttributionResult
from ..persistence.repositories import UnitOfWork, seed_reference_data
from ..seed import demo_book
from .demo_performance import DemoPerformance

TOLERANCE = 1e-10


@dataclass
class PerformanceRunResult:
    portfolio_id: str
    days: int
    periods: list[tuple[date, date, str, float]] = field(default_factory=list)  # start, end, dimension, active
    effects: int = 0

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = [("portfolio", self.portfolio_id), ("daily returns stored", f"{self.days:,}")]
        rows += [
            (f"{dimension} attribution {start} to {end}", f"active {active:+.2%}")
            for start, end, dimension, active in self.periods
        ]
        rows.append(("attribution rows stored", f"{self.effects:,}"))
        return rows


def report_periods(performance: DemoPerformance) -> list[tuple[date, date]]:
    """Since inception, then each calendar year the history covers."""
    series = performance.portfolio_returns
    start, end = series.start, series.days[-1]
    periods = [(start, end)]
    for year in range(start.year, end.year + 1):
        first = max(start, date(year - 1, 12, 31))
        last = min(end, date(year, 12, 31))
        if last > first:
            periods.append((first, last))
    return periods


def check(result: AttributionResult) -> None:
    if abs(result.residual) > TOLERANCE:
        raise ValidationError(
            f"attribution {result.start} to {result.end} leaves {result.residual:.2e} unexplained; nothing written"
        )


def run_demo_performance(performance: DemoPerformance, unit_of_work: UnitOfWork | None = None) -> PerformanceRunResult:
    portfolio_id = performance.accounting.portfolio.portfolio_id
    computed: list[AttributionResult] = []
    for start, end in report_periods(performance):
        for dimension in ("sector", "region"):
            result = performance.attribution(dimension, start=start, end=end)
            check(result)
            computed.append(result)
    outcome = PerformanceRunResult(
        portfolio_id,
        len(performance.portfolio_days),
        [(item.start, item.end, item.dimension, item.active) for item in computed],
    )
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
        unit_of_work.portfolios.add(performance.accounting.portfolio)
        unit_of_work.flush()
    benchmark = dict(zip(performance.benchmark_returns.days, performance.benchmark_returns.rates, strict=True))
    unit_of_work.performance.replace_returns(portfolio_id, performance.portfolio_days, benchmark, "POLICY-80-15-5")
    outcome.effects = sum(unit_of_work.performance.save_attribution(portfolio_id, item) for item in computed)
    unit_of_work.flush()
    return outcome
