"""What the platform serves, and where it comes from: one facade over every module.

The API does not compute anything of its own. Each endpoint asks this facade,
and the facade asks the module that owns the answer - the valuation from the
Day 3 book, returns and attribution from Day 4, risk from Day 5, the mandate
from Day 6, the rebalance from Day 7, trading costs from Day 8 - so a number
served over HTTP is the number the CLI prints and the client report shows.

The facade is a :class:`typing.Protocol`, so the web layer can be tested
against a small in-memory stand-in (fast, and exact about what each endpoint
returns) and run against :class:`DemoPlatformData`, which builds the
demonstration account lazily and keeps it for the life of the process.

Answers are plain dictionaries of JSON-ready values; the response models in
:mod:`.schemas` give them their public shape.
"""

from __future__ import annotations

import logging
import threading
import warnings
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

from ..core.exceptions import ValidationError

ANALYSED = "PF-GLOBAL-EQ"  # the portfolio every module analyses


class NotAvailable(LookupError):
    """The portfolio exists but this analysis has not been run for it."""


class PlatformData(Protocol):
    def portfolios(self) -> list[dict[str, Any]]: ...
    def valuation(self, portfolio_id: str) -> dict[str, Any]: ...
    def performance(self, portfolio_id: str) -> dict[str, Any]: ...
    def attribution(self, portfolio_id: str) -> dict[str, Any]: ...
    def risk(self, portfolio_id: str) -> dict[str, Any]: ...
    def compliance(self, portfolio_id: str) -> dict[str, Any]: ...
    def tax_lots(self, portfolio_id: str) -> dict[str, Any]: ...
    def pretrade(self, portfolio_id: str, instrument_id: str, side: str, amount: float) -> dict[str, Any]: ...
    def rebalance(self, portfolio_id: str) -> dict[str, Any]: ...
    def trading_costs(self) -> dict[str, Any]: ...
    def client_report(self, portfolio_id: str, directory: Path) -> Path: ...


class DemoPlatformData:
    """The demonstration account, served. Built on first use and kept; thread-safe to build."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the modules, built lazily
    @cached_property
    def _execution(self):  # type: ignore[no-untyped-def]
        from ..services.demo_execution import build_demo_execution

        logging.getLogger().setLevel(logging.WARNING)
        warnings.filterwarnings("ignore", module="cvxpy")
        with self._lock:
            return build_demo_execution()

    @property
    def _optimisation(self):  # type: ignore[no-untyped-def]
        return self._execution.optimisation

    @property
    def _compliance(self):  # type: ignore[no-untyped-def]
        return self._optimisation.compliance

    @property
    def _risk(self):  # type: ignore[no-untyped-def]
        return self._compliance.risk

    @property
    def _performance(self):  # type: ignore[no-untyped-def]
        return self._risk.performance

    @cached_property
    def _book(self):  # type: ignore[no-untyped-def]
        from ..seed import demo_book

        return demo_book()

    def _analysed(self, portfolio_id: str) -> None:
        if portfolio_id not in {portfolio.portfolio_id for portfolio in self._book.portfolios}:
            raise KeyError(portfolio_id)
        if portfolio_id != ANALYSED:
            raise NotAvailable(f"{portfolio_id} is on the books, but its analytics have not been run")

    # ------------------------------------------------------------------ answers
    def portfolios(self) -> list[dict[str, Any]]:
        return [
            {
                "portfolio_id": portfolio.portfolio_id,
                "name": portfolio.name,
                "base_currency": str(portfolio.base_currency),
                "benchmark_id": portfolio.benchmark_id,
                "account_id": portfolio.account_id,
                "strategy": portfolio.strategy,
                "inception": portfolio.inception.isoformat(),
                "analysed": portfolio.portfolio_id == ANALYSED,
            }
            for portfolio in self._book.portfolios
        ]

    def valuation(self, portfolio_id: str) -> dict[str, Any]:
        self._analysed(portfolio_id)
        valuation = self._optimisation.valuation
        nav = float(valuation.nav)
        positions = [
            {
                "instrument_id": position.instrument_id,
                "quantity": float(position.quantity),
                "price": float(position.price),
                "currency": str(position.currency),
                "market_value_base": float(position.total_base),
                "weight": float(position.total_base) / nav,
                "unrealised_long_term": float(position.unrealised_long_term),
                "unrealised_short_term": float(position.unrealised_short_term),
            }
            for position in sorted(valuation.positions, key=lambda item: -float(item.total_base))
        ]
        cash = sum(float(line.total_base) for line in valuation.cash)
        return {
            "portfolio_id": portfolio_id,
            "as_of": self._optimisation.as_of.isoformat(),
            "nav": nav,
            "cash": cash,
            "positions": positions,
        }

    def performance(self, portfolio_id: str) -> dict[str, Any]:
        from ..performance.returns import standard_periods
        from ..performance.statistics import summary_rows

        self._analysed(portfolio_id)
        perf = self._performance
        mine, theirs = standard_periods(perf.portfolio_returns), standard_periods(perf.benchmark_returns)
        return {
            "portfolio_id": portfolio_id,
            "periods": [
                {
                    "period": a.label,
                    "portfolio": a.annualised if a.is_annualised else a.total,
                    "benchmark": b.annualised if b.is_annualised else b.total,
                    "annualised": a.is_annualised,
                }
                for a, b in zip(mine, theirs, strict=True)
            ],
            "calendar_years": [
                {"year": year, "portfolio": value, "benchmark": dict(perf.benchmark_returns.yearly()).get(year)}
                for year, value in perf.portfolio_returns.yearly()
            ],
            "statistics": [
                {"measure": m, "portfolio": p, "benchmark": b}
                for m, p, b in summary_rows(perf.portfolio_returns, perf.benchmark_returns)
            ],
        }

    def attribution(self, portfolio_id: str) -> dict[str, Any]:
        self._analysed(portfolio_id)
        result = self._performance.by_sector
        return {
            "portfolio_id": portfolio_id,
            "start": result.start.isoformat(),
            "end": result.end.isoformat(),
            "portfolio": result.portfolio,
            "benchmark": result.benchmark,
            "active": result.active,
            "effects": {
                name: result.effect(name) for name in ("allocation", "selection", "interaction", "currency", "costs")
            },
            "segments": [
                {
                    "segment": item.segment,
                    "average_weight": item.average_wp,
                    "benchmark_weight": item.average_wb,
                    "allocation": item.allocation,
                    "selection": item.selection,
                    "interaction": item.interaction,
                }
                for item in result.segments
            ],
        }

    def risk(self, portfolio_id: str) -> dict[str, Any]:
        self._analysed(portfolio_id)
        risk = self._risk
        return {
            "portfolio_id": portfolio_id,
            "as_of": risk.model.as_of.isoformat(),
            "volatility": risk.portfolio.volatility,
            "tracking_error": risk.active.volatility,
            "by_group": risk.portfolio.by_group(),
            "active_by_group": risk.active.by_group(),
            "value_at_risk": [
                {"method": item.method, "confidence": item.confidence, "var": item.var, "expected_shortfall": item.es}
                for item in risk.var_estimates
            ],
            "stress": [
                {"scenario": item.scenario.name, "portfolio": item.portfolio, "benchmark": item.benchmark}
                for item in risk.stress
            ],
        }

    def compliance(self, portfolio_id: str) -> dict[str, Any]:
        from ..compliance.language import bound_text

        self._analysed(portfolio_id)
        report = self._compliance.today
        return {
            "portfolio_id": portfolio_id,
            "as_of": report.day.isoformat(),
            "mandate": f"{report.mandate.name}, version {report.mandate.version}",
            "rules": [
                {
                    "rule_id": result.rule.rule_id,
                    "title": result.rule.title,
                    "severity": result.rule.severity,
                    "status": result.status,
                    "value": result.value,
                    "limit": bound_text(result.rule),
                    "utilisation": None if result.utilisation in (None, float("inf")) else result.utilisation,
                }
                for result in report.results
            ],
            "open_breaches": len(self._compliance.history.open_breaches()),
        }

    def tax_lots(self, portfolio_id: str) -> dict[str, Any]:
        self._analysed(portfolio_id)
        as_of = self._optimisation.as_of
        lots = []
        for asset in self._optimisation.assets:
            for lot in asset.lots:
                lots.append(
                    {
                        "lot_id": lot.lot_id,
                        "instrument_id": lot.asset_id,
                        "quantity": lot.quantity,
                        "basis_per_unit": lot.basis_per_unit,
                        "price": asset.price,
                        "opened": lot.opened.isoformat(),
                        "long_term": lot.is_long_term(as_of),
                        "unrealised": lot.quantity * (asset.price - lot.basis_per_unit),
                    }
                )
        return {"portfolio_id": portfolio_id, "as_of": as_of.isoformat(), "lots": lots}

    def pretrade(self, portfolio_id: str, instrument_id: str, side: str, amount: float) -> dict[str, Any]:
        from ..compliance.pretrade import Order

        self._analysed(portfolio_id)
        if (
            instrument_id not in self._compliance.reference
            and instrument_id not in self._compliance.constituent_attributes
        ):
            raise ValidationError(f"{instrument_id} is not an instrument the platform knows")
        checker = self._optimisation.pretrade
        decision = checker.check(Order("API", instrument_id, side, amount))
        return {
            "decision": decision.decision,
            "maximum": decision.maximum,
            "reasons": [
                {
                    "rule_id": change.rule_id,
                    "effect": change.effect,
                    "before": change.before.value,
                    "after": change.after.value,
                }
                for change in decision.reasons
            ],
        }

    def rebalance(self, portfolio_id: str) -> dict[str, Any]:
        self._analysed(portfolio_id)
        result, rounded = self._optimisation.proposal, self._optimisation.tickets
        return {
            "portfolio_id": portfolio_id,
            "as_of": result.as_of.isoformat(),
            "tracking_error_before": result.tracking_error_before,
            "tracking_error_after": rounded.tracking_error_after,
            "active_share_after": rounded.active_share_after,
            "tax": rounded.tax,
            "cost": rounded.cost * result.nav,
            "turnover": result.turnover,
            "compliance": self._optimisation.compliance_check.decision,
            "orders": [
                {
                    "instrument_id": t.asset_id,
                    "side": t.side,
                    "units": t.units,
                    "value": t.value,
                    "lots": [{"lot_id": lot_id, "units": units} for lot_id, units in t.lots],
                }
                for t in rounded.tickets
            ],
        }

    def trading_costs(self) -> dict[str, Any]:
        execution = self._execution
        totals = execution.totals()
        paper = totals["paper value"]
        return {
            "trade_date": execution.trade_date.isoformat(),
            "paper_value": paper,
            "shortfall_bps": totals["shortfall"] / paper * 1e4,
            "components_bps": {
                name: totals[name] / paper * 1e4
                for name in ("delay", "spread", "temporary impact", "permanent impact", "timing", "opportunity", "fees")
            },
            "blocks": [
                {
                    "order_id": cost.order_id,
                    "instrument_id": cost.instrument_id,
                    "algorithm": cost.algorithm,
                    "quantity": cost.quantity,
                    "filled": cost.filled,
                    "average_price": cost.average,
                    "shortfall_bps": cost.shortfall_bps,
                    "vwap_slippage_bps": cost.vwap_slippage_bps,
                }
                for cost in execution.costs
            ],
        }

    def client_report(self, portfolio_id: str, directory: Path) -> Path:
        from ..reporting.client_pack import ClientPack

        self._analysed(portfolio_id)
        path = directory / f"client-report-{portfolio_id}.pdf"
        if not path.exists():
            with self._lock:
                if not path.exists():
                    ClientPack(self._execution, portfolio_id).write(path)
        return path
