"""Performance in the database: daily returns and linked attribution effects.

Returns are stored daily so any period can be recomputed by linking in SQL or
in Python; attribution is stored as linked effects per period, because linking
is not additive across periods and a report must show exactly the numbers that
were computed for its period. Both are floats: they are analytics, not ledger
amounts (ADR 0008).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from ..performance.attribution import AttributionResult
from ..performance.contributions import PortfolioDay
from .base import utcnow
from .models import AttributionEffectRow, PerformanceReturnRow


class PerformanceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_returns(
        self,
        portfolio_id: str,
        days: Iterable[PortfolioDay],
        benchmark: dict[date, float] | None = None,
        benchmark_id: str | None = None,
    ) -> int:
        self.session.execute(delete(PerformanceReturnRow).where(PerformanceReturnRow.portfolio_id == portfolio_id))
        now = utcnow()
        rows = [
            {
                "portfolio_id": portfolio_id,
                "return_date": day.day,
                "capital": day.capital,
                "result": day.result,
                "portfolio_return": day.rate,
                "benchmark_return": (benchmark or {}).get(day.day),
                "benchmark_id": benchmark_id,
                "created_at": now,
                "updated_at": now,
            }
            for day in days
        ]
        if rows:
            self.session.execute(insert(PerformanceReturnRow), rows)
        return len(rows)

    def returns(
        self, portfolio_id: str, start: date | None = None, end: date | None = None
    ) -> list[tuple[date, float, float | None]]:
        statement = (
            select(
                PerformanceReturnRow.return_date,
                PerformanceReturnRow.portfolio_return,
                PerformanceReturnRow.benchmark_return,
            )
            .where(PerformanceReturnRow.portfolio_id == portfolio_id)
            .order_by(PerformanceReturnRow.return_date)
        )
        if start is not None:
            statement = statement.where(PerformanceReturnRow.return_date > start)
        if end is not None:
            statement = statement.where(PerformanceReturnRow.return_date <= end)
        return [
            (day, float(rate), None if bench is None else float(bench))
            for day, rate, bench in self.session.execute(statement)
        ]

    def linked(self, portfolio_id: str, start: date | None = None, end: date | None = None) -> tuple[float, float]:
        """The portfolio's and benchmark's returns over ``(start, end]``, linked from the stored days."""
        rows = self.returns(portfolio_id, start, end)
        return (
            math.prod(1.0 + rate for _, rate, _ in rows) - 1.0,
            math.prod(1.0 + (bench or 0.0) for _, _, bench in rows) - 1.0,
        )

    def save_attribution(self, portfolio_id: str, result: AttributionResult) -> int:
        """Store one period's linked attribution, replacing any earlier run for the same period and dimension."""
        self.session.execute(
            delete(AttributionEffectRow).where(
                AttributionEffectRow.portfolio_id == portfolio_id,
                AttributionEffectRow.period_start == result.start,
                AttributionEffectRow.period_end == result.end,
                AttributionEffectRow.dimension == result.dimension,
            )
        )
        now = utcnow()
        base = {
            "portfolio_id": portfolio_id,
            "period_start": result.start,
            "period_end": result.end,
            "dimension": result.dimension,
            "created_at": now,
            "updated_at": now,
        }
        rows = [
            {
                **base,
                "segment": item.segment,
                "kind": "segment",
                "average_portfolio_weight": item.average_wp,
                "average_benchmark_weight": item.average_wb,
                "allocation": item.allocation,
                "selection": item.selection,
                "interaction": item.interaction,
                "currency": 0.0,
                "costs": 0.0,
            }
            for item in result.segments
        ]
        rows += [
            {
                **base,
                "segment": f"currency {code}",
                "kind": "currency",
                "average_portfolio_weight": None,
                "average_benchmark_weight": None,
                "allocation": 0.0,
                "selection": 0.0,
                "interaction": 0.0,
                "currency": value,
                "costs": 0.0,
            }
            for code, value in sorted(result.currency.items())
        ]
        rows.append(
            {
                **base,
                "segment": "costs",
                "kind": "costs",
                "average_portfolio_weight": None,
                "average_benchmark_weight": None,
                "allocation": 0.0,
                "selection": 0.0,
                "interaction": 0.0,
                "currency": 0.0,
                "costs": result.costs,
            }
        )
        self.session.execute(insert(AttributionEffectRow), rows)
        return len(rows)

    def effects(self, portfolio_id: str, dimension: str) -> Sequence[AttributionEffectRow]:
        return list(
            self.session.scalars(
                select(AttributionEffectRow)
                .where(AttributionEffectRow.portfolio_id == portfolio_id, AttributionEffectRow.dimension == dimension)
                .order_by(AttributionEffectRow.period_end, AttributionEffectRow.kind, AttributionEffectRow.segment)
            )
        )

    def explained(self, portfolio_id: str, dimension: str) -> float:
        """The sum of every stored effect for a dimension: equal to the active return it explains."""
        return sum(
            row.allocation + row.selection + row.interaction + row.currency + row.costs
            for row in self.effects(portfolio_id, dimension)
        )
