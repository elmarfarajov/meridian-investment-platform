"""Risk in the database: factor returns, daily forecasts and the exposures behind a risk report.

Factor returns are stored because every covariance forecast is a function of
them: with the history in SQL, a forecast made on any past day can be rebuilt
and audited. Forecasts are stored with the outcome they were scored against,
so the backtest - how many times the VaR was exceeded, whether the tracking
error forecast was the right size - can be read back and recomputed from the
database without rerunning the model. Floats throughout: analytics, not the
ledger (ADR 0008).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol

import numpy as np
from sqlalchemy import case, delete, func, insert, select
from sqlalchemy.orm import Session

from .base import utcnow
from .models import RiskExposureRow, RiskFactorReturnRow, RiskForecastRow


class ScoredForecast(Protocol):
    """What a stored forecast needs: the morning's numbers and the day's outcome (read-only)."""

    @property
    def day(self) -> date: ...

    @property
    def weekdays(self) -> int: ...

    @property
    def volatility(self) -> float: ...

    @property
    def tracking_error(self) -> float: ...

    @property
    def factor_share(self) -> float: ...

    @property
    def realised(self) -> float: ...

    @property
    def active(self) -> float: ...

    @property
    def var(self) -> float: ...

    @property
    def exception(self) -> bool: ...


class RiskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ factor returns
    def replace_factor_returns(
        self, model_id: str, days: Sequence[date], factors: Sequence[str], returns: np.ndarray
    ) -> int:
        """Store a model's factor return history (days x factors), replacing any earlier run of the model."""
        self.session.execute(delete(RiskFactorReturnRow).where(RiskFactorReturnRow.model_id == model_id))
        now = utcnow()
        rows = [
            {
                "model_id": model_id,
                "return_date": day,
                "factor": factor,
                "value": float(returns[row, column]),
                "created_at": now,
                "updated_at": now,
            }
            for row, day in enumerate(days)
            for column, factor in enumerate(factors)
        ]
        for start in range(0, len(rows), 10_000):
            self.session.execute(insert(RiskFactorReturnRow), rows[start : start + 10_000])
        return len(rows)

    def factor_returns(self, model_id: str, factor: str) -> list[tuple[date, float]]:
        statement = (
            select(RiskFactorReturnRow.return_date, RiskFactorReturnRow.value)
            .where(RiskFactorReturnRow.model_id == model_id, RiskFactorReturnRow.factor == factor)
            .order_by(RiskFactorReturnRow.return_date)
        )
        return [(day, float(value)) for day, value in self.session.execute(statement)]

    def realised_volatility(self, model_id: str, factor: str) -> float:
        """Annualised volatility of a factor, computed in SQL from the stored returns."""
        statement = select(
            func.count(RiskFactorReturnRow.value),
            func.sum(RiskFactorReturnRow.value),
            func.sum(RiskFactorReturnRow.value * RiskFactorReturnRow.value),
        ).where(RiskFactorReturnRow.model_id == model_id, RiskFactorReturnRow.factor == factor)
        count, total, squares = self.session.execute(statement).one()
        if not count or count < 2:
            return 0.0
        mean = float(total) / count
        variance = (float(squares) - count * mean**2) / (count - 1)
        return float(np.sqrt(max(variance, 0.0) * 252))

    # ------------------------------------------------------------------ forecasts
    def replace_forecasts(self, portfolio_id: str, model_id: str, forecasts: Iterable[ScoredForecast]) -> int:
        """Store the daily forecasts of a portfolio with their outcomes."""
        self.session.execute(delete(RiskForecastRow).where(RiskForecastRow.portfolio_id == portfolio_id))
        now = utcnow()
        rows = [
            {
                "portfolio_id": portfolio_id,
                "forecast_date": item.day,
                "model_id": model_id,
                "weekdays": item.weekdays,
                "volatility": item.volatility,
                "tracking_error": item.tracking_error,
                "factor_share": item.factor_share,
                "var_99": item.var,
                "realised": item.realised,
                "active": item.active,
                "exception": bool(item.exception),
                "created_at": now,
                "updated_at": now,
            }
            for item in forecasts
        ]
        if rows:
            self.session.execute(insert(RiskForecastRow), rows)
        return len(rows)

    def forecasts(self, portfolio_id: str) -> list[RiskForecastRow]:
        return list(
            self.session.scalars(
                select(RiskForecastRow)
                .where(RiskForecastRow.portfolio_id == portfolio_id)
                .order_by(RiskForecastRow.forecast_date)
            )
        )

    def exception_count(self, portfolio_id: str, since: date | None = None) -> tuple[int, int]:
        """VaR exceptions and scored days, counted in SQL."""
        statement = select(
            func.count(RiskForecastRow.forecast_date),
            func.sum(case((RiskForecastRow.exception, 1), else_=0)),
        ).where(RiskForecastRow.portfolio_id == portfolio_id)
        if since is not None:
            statement = statement.where(RiskForecastRow.forecast_date > since)
        days, hits = self.session.execute(statement).one()
        return int(hits or 0), int(days or 0)

    # ------------------------------------------------------------------ exposures
    def replace_exposures(
        self, portfolio_id: str, as_of: date, rows: Iterable[tuple[str, str, float, float, float]]
    ) -> int:
        """Store (factor, group, portfolio exposure, benchmark exposure, active contribution) for a report date."""
        self.session.execute(
            delete(RiskExposureRow).where(RiskExposureRow.portfolio_id == portfolio_id, RiskExposureRow.as_of == as_of)
        )
        now = utcnow()
        payload = [
            {
                "portfolio_id": portfolio_id,
                "as_of": as_of,
                "factor": factor,
                "factor_group": group,
                "portfolio": portfolio,
                "benchmark": benchmark,
                "active_contribution": contribution,
                "created_at": now,
                "updated_at": now,
            }
            for factor, group, portfolio, benchmark, contribution in rows
        ]
        if payload:
            self.session.execute(insert(RiskExposureRow), payload)
        return len(payload)

    def exposures(self, portfolio_id: str, as_of: date) -> list[RiskExposureRow]:
        return list(
            self.session.scalars(
                select(RiskExposureRow)
                .where(RiskExposureRow.portfolio_id == portfolio_id, RiskExposureRow.as_of == as_of)
                .order_by(RiskExposureRow.factor)
            )
        )
