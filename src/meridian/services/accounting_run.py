"""The end-of-day accounting run: replay, value, reconcile, persist.

This is the process a middle office runs every evening after the pricing run
of Day 2 has published the golden copy:

1. **Replay** the blotter as known now into the book of record.
2. **Check** that the trial balance balances and that the investment
   sub-ledger ties to the open lots - a run that fails either stops here and
   writes nothing, because a wrong book is worse than yesterday's book.
3. **Value** the book on every business day that has not been valued yet.
4. **Reconcile** against the custodian's statement for the day.
5. **Persist** the journal, the open lots, the realised lots, the valuations
   and the breaks in one unit of work.

The book is derived, so persisting it replaces what was stored for the
portfolio; the transactions themselves are the only input that is appended.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..accounting.book import Book
from ..accounting.chart_of_accounts import Accounts
from ..accounting.reconciliation import ReconciliationReport
from ..accounting.valuation import PortfolioValuation
from ..core.exceptions import ValidationError
from ..persistence.repositories import UnitOfWork, seed_reference_data
from ..seed import demo_book
from .demo_accounting import DemoAccounting

logger = logging.getLogger(__name__)
TIE_OUT_TOLERANCE = Decimal("1e-8")


@dataclass
class AccountingRunResult:
    portfolio_id: str
    as_of: date
    entries: int
    open_lots: int
    realised_lots: int
    valuations: int
    breaks: int
    nav: Decimal
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    def summary_rows(self) -> list[tuple[str, str]]:
        return [
            ("portfolio", self.portfolio_id),
            ("as of", self.as_of.isoformat()),
            ("journal entries", f"{self.entries:,}"),
            ("open lots", f"{self.open_lots:,}"),
            ("realised lots", f"{self.realised_lots:,}"),
            ("valuation days", f"{self.valuations:,}"),
            ("reconciliation breaks", f"{self.breaks:,}"),
            ("net asset value", f"{self.nav:,.2f}"),
            *((f"check: {name}", "passed" if ok else "FAILED") for name, ok in self.checks.items()),
        ]


def tie_out(book: Book) -> dict[str, bool]:
    """The controls a run must pass before anything is written."""
    trial = book.ledger.trial_balance()
    ledger_cost = book.ledger.instrument_balances(Accounts.INVESTMENTS)
    lot_cost = {key: sum((lot.base_cost for lot in lots), Decimal(0)) for key, lots in book.open_lots.items()}
    keys = set(ledger_cost) | set(lot_cost)
    sub_ledger = all(
        abs(ledger_cost.get(key, Decimal(0)) - lot_cost.get(key, Decimal(0))) <= TIE_OUT_TOLERANCE for key in keys
    )
    last = book.snapshot_on(book.last_day) if book.last_day else None
    cash = last is None or all(
        last.cash(currency) == amount for currency, amount in book.ledger.local_balances(Accounts.CASH).items()
    )
    return {"trial balance balances": trial.is_balanced, "sub-ledger ties to lots": sub_ledger, "cash ties": cash}


def persist_book(
    unit_of_work: UnitOfWork,
    book: Book,
    valuations: Sequence[PortfolioValuation],
    reports: Sequence[ReconciliationReport] = (),
) -> AccountingRunResult:
    checks = tie_out(book)
    if not all(checks.values()):
        failed = ", ".join(name for name, ok in checks.items() if not ok)
        raise ValidationError(
            f"{book.portfolio.portfolio_id}: the book failed its controls ({failed}); nothing written"
        )
    portfolio_id = book.portfolio.portfolio_id
    entries = unit_of_work.ledger.replace(portfolio_id, book.ledger.entries)
    lots = unit_of_work.tax_lots.replace_open(portfolio_id, [lot for items in book.open_lots.values() for lot in items])
    realised = unit_of_work.realised.replace(portfolio_id, book.realised)
    valued = unit_of_work.valuations.upsert_many(valuations)
    breaks = sum(unit_of_work.reconciliation.save(portfolio_id, report.as_of, report.breaks) for report in reports)
    unit_of_work.flush()
    as_of = valuations[-1].day if valuations else book.as_of or date.min
    logger.info(
        "accounting.persisted",
        extra={"portfolio": portfolio_id, "entries": entries, "lots": lots, "valuations": valued, "breaks": breaks},
    )
    return AccountingRunResult(
        portfolio_id,
        as_of,
        entries,
        lots,
        realised,
        valued,
        breaks,
        valuations[-1].nav if valuations else Decimal(0),
        checks,
    )


def run_demo_accounting(demo: DemoAccounting, unit_of_work: UnitOfWork | None = None) -> AccountingRunResult:
    """Replay, check, value and reconcile the demonstration book; persist it if a unit of work is given."""
    register, _ = demo.reconciliation
    if unit_of_work is None:
        checks = tie_out(demo.book)
        return AccountingRunResult(
            demo.portfolio.portfolio_id,
            demo.valuations[-1].day,
            len(demo.book.ledger),
            sum(len(lots) for lots in demo.book.open_lots.values()),
            len(demo.book.realised),
            len(demo.valuations),
            sum(len(report.breaks) for report in register.reports),
            demo.valuations[-1].nav,
            checks,
        )
    reference = demo_book()
    if unit_of_work.portfolios.find(demo.portfolio.portfolio_id) is None:
        seed_reference_data(
            unit_of_work,
            instruments=reference.instruments,
            benchmarks=reference.benchmarks,
            clients=reference.clients,
            households=reference.households,
            accounts=reference.accounts,
            portfolios=reference.portfolios,
        )
    unit_of_work.portfolios.add(demo.portfolio)
    unit_of_work.flush()
    return persist_book(unit_of_work, demo.book, demo.valuations, register.reports)
