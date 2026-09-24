"""Repositories for the book of record: the journal, realised lots, valuations and breaks.

The journal repository computes the trial balance in SQL - one ``GROUP BY``
over the postings - and the tests hold it equal, account by account, to the
trial balance the in-memory ledger computes. As with the bitemporal query on
Day 2, having the same answer computed two ways is what stops the database
and the reference model drifting apart.

A book is derived by replay, so persisting it replaces what was stored for
that portfolio rather than merging into it: stale rows from an earlier replay
would otherwise survive a correction that removed them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, selectinload

from ..accounting.chart_of_accounts import CHART_OF_ACCOUNTS
from ..accounting.journal import BALANCE_TOLERANCE, JournalEntry
from ..accounting.ledger import TrialBalance, TrialBalanceLine
from ..accounting.lots import RealisedLot
from ..accounting.reconciliation import Break
from ..accounting.valuation import PortfolioValuation
from . import accounting_mappers as mappers
from .bulk import bulk_upsert
from .models import (
    JournalEntryRow,
    JournalPostingRow,
    PortfolioValuationRow,
    PositionValuationRow,
    RealisedLotRow,
    ReconciliationBreakRow,
)


class LedgerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace(self, portfolio_id: str, entries: Iterable[JournalEntry]) -> int:
        """Store a portfolio's journal, replacing what was there."""
        existing = select(JournalEntryRow.entry_id).where(JournalEntryRow.portfolio_id == portfolio_id)
        self.session.execute(delete(JournalPostingRow).where(JournalPostingRow.entry_id.in_(existing)))
        self.session.execute(delete(JournalEntryRow).where(JournalEntryRow.portfolio_id == portfolio_id))
        materialised = list(entries)
        if not materialised:
            return 0
        self.session.execute(insert(JournalEntryRow), [mappers.entry_values(entry) for entry in materialised])
        postings = [row for entry in materialised for row in mappers.posting_values(entry)]
        self.session.execute(insert(JournalPostingRow), postings)
        return len(materialised)

    def entries(self, portfolio_id: str, *, source_id: str | None = None) -> Sequence[JournalEntry]:
        statement = (
            select(JournalEntryRow)
            .where(JournalEntryRow.portfolio_id == portfolio_id)
            .options(selectinload(JournalEntryRow.postings))
            .order_by(JournalEntryRow.effective_date, JournalEntryRow.entry_id)
        )
        if source_id is not None:
            statement = statement.where(JournalEntryRow.source_id == source_id)
        return [mappers.row_to_entry(row) for row in self.session.scalars(statement)]

    def count(self, portfolio_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(JournalEntryRow).where(JournalEntryRow.portfolio_id == portfolio_id)
            )
            or 0
        )

    def trial_balance(self, portfolio_id: str, as_of: date | None = None) -> TrialBalance:
        """The trial balance computed by the database."""
        statement = (
            select(JournalPostingRow.account_code, func.sum(JournalPostingRow.base_amount))
            .join(JournalEntryRow, JournalEntryRow.entry_id == JournalPostingRow.entry_id)
            .where(JournalEntryRow.portfolio_id == portfolio_id)
            .group_by(JournalPostingRow.account_code)
        )
        if as_of is not None:
            statement = statement.where(JournalEntryRow.effective_date <= as_of)
        totals = {code: Decimal(str(amount)) for code, amount in self.session.execute(statement)}
        lines = tuple(
            TrialBalanceLine(account, totals[account.code])
            for account in CHART_OF_ACCOUNTS
            if abs(totals.get(account.code, Decimal(0))) > BALANCE_TOLERANCE
        )
        return TrialBalance(as_of or date.max, lines)

    def balance_by_instrument(self, portfolio_id: str, account_code: str) -> dict[str, Decimal]:
        statement = (
            select(JournalPostingRow.instrument_id, func.sum(JournalPostingRow.base_amount))
            .join(JournalEntryRow, JournalEntryRow.entry_id == JournalPostingRow.entry_id)
            .where(JournalEntryRow.portfolio_id == portfolio_id, JournalPostingRow.account_code == account_code)
            .where(JournalPostingRow.instrument_id.is_not(None))
            .group_by(JournalPostingRow.instrument_id)
        )
        return {
            key: Decimal(str(amount))
            for key, amount in self.session.execute(statement)
            if abs(Decimal(str(amount))) > BALANCE_TOLERANCE
        }


class RealisedLotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace(self, portfolio_id: str, items: Iterable[RealisedLot]) -> int:
        self.session.execute(delete(RealisedLotRow).where(RealisedLotRow.portfolio_id == portfolio_id))
        rows = [mappers.realised_values(item) for item in items]
        if rows:
            self.session.execute(insert(RealisedLotRow), rows)
        return len(rows)

    def for_portfolio(
        self, portfolio_id: str, *, year: int | None = None, instrument_id: str | None = None
    ) -> Sequence[RealisedLot]:
        statement = (
            select(RealisedLotRow)
            .where(RealisedLotRow.portfolio_id == portfolio_id)
            .order_by(RealisedLotRow.close_date, RealisedLotRow.disposal_id, RealisedLotRow.lot_id)
        )
        if year is not None:
            statement = statement.where(
                RealisedLotRow.close_date >= date(year, 1, 1), RealisedLotRow.close_date <= date(year, 12, 31)
            )
        if instrument_id is not None:
            statement = statement.where(RealisedLotRow.instrument_id == instrument_id)
        return [mappers.row_to_realised(row) for row in self.session.scalars(statement)]


class ValuationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, valuations: Iterable[PortfolioValuation]) -> int:
        materialised = list(valuations)
        bulk_upsert(self.session, PortfolioValuationRow, [mappers.valuation_values(item) for item in materialised])
        positions = [
            mappers.position_values(item.portfolio_id, item.day, position)
            for item in materialised
            for position in item.positions
        ]
        bulk_upsert(self.session, PositionValuationRow, positions)
        return len(materialised)

    def nav_series(
        self, portfolio_id: str, start: date | None = None, end: date | None = None
    ) -> list[tuple[date, Decimal]]:
        statement = (
            select(PortfolioValuationRow.valuation_date, PortfolioValuationRow.nav)
            .where(PortfolioValuationRow.portfolio_id == portfolio_id)
            .order_by(PortfolioValuationRow.valuation_date)
        )
        if start is not None:
            statement = statement.where(PortfolioValuationRow.valuation_date >= start)
        if end is not None:
            statement = statement.where(PortfolioValuationRow.valuation_date <= end)
        return [(day, Decimal(str(nav))) for day, nav in self.session.execute(statement)]

    def positions_on(self, portfolio_id: str, day: date) -> Sequence[PositionValuationRow]:
        return list(
            self.session.scalars(
                select(PositionValuationRow)
                .where(PositionValuationRow.portfolio_id == portfolio_id, PositionValuationRow.valuation_date == day)
                .order_by(PositionValuationRow.instrument_id)
            )
        )

    def latest_date(self, portfolio_id: str) -> date | None:
        return self.session.scalar(
            select(func.max(PortfolioValuationRow.valuation_date)).where(
                PortfolioValuationRow.portfolio_id == portfolio_id
            )
        )


class ReconciliationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, portfolio_id: str, as_of: date, breaks: Iterable[Break]) -> int:
        """Store one statement date's breaks, replacing any earlier run for that date."""
        self.session.execute(
            delete(ReconciliationBreakRow).where(
                ReconciliationBreakRow.portfolio_id == portfolio_id, ReconciliationBreakRow.as_of == as_of
            )
        )
        rows = [mappers.break_values(portfolio_id, item) for item in breaks]
        if rows:
            self.session.execute(insert(ReconciliationBreakRow), rows)
        return len(rows)

    def breaks(self, portfolio_id: str, as_of: date | None = None) -> Sequence[ReconciliationBreakRow]:
        statement = (
            select(ReconciliationBreakRow)
            .where(ReconciliationBreakRow.portfolio_id == portfolio_id)
            .order_by(ReconciliationBreakRow.as_of, ReconciliationBreakRow.kind, ReconciliationBreakRow.break_key)
        )
        if as_of is not None:
            statement = statement.where(ReconciliationBreakRow.as_of == as_of)
        return list(self.session.scalars(statement))

    def counts_by_cause(self, portfolio_id: str) -> dict[str, int]:
        statement = (
            select(ReconciliationBreakRow.cause, func.count())
            .where(ReconciliationBreakRow.portfolio_id == portfolio_id)
            .group_by(ReconciliationBreakRow.cause)
        )
        return {cause: int(count) for cause, count in self.session.execute(statement)}
