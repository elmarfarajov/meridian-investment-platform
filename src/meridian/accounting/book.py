"""The book: what the accounting engine produces, and the questions it answers.

A :class:`Book` is the complete, derived state of one portfolio: the general
ledger, the open lots, every realised lot, every cash movement with the day it
was agreed and the day it settled, and an end-of-day snapshot for every date on
which anything happened. It is rebuilt from the transactions, never edited, so
two books built from the same transactions are identical and a book can be
rebuilt as it stood at any past moment from the blotter.

The snapshots are what the valuation reads. Each carries the open lots and the
balance of every cash-like account in each currency - settled cash, the
receivables and payables of unsettled trades, dividends gone ex but not yet
paid, withholding tax awaiting reclaim - because those are what net asset
value is made of besides the securities themselves.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from ..core.decimals import decimal_sum
from ..domain.portfolios import Portfolio
from ..domain.positions import TaxLot
from ..domain.transactions import Transaction
from .chart_of_accounts import Accounts
from .ledger import GeneralLedger
from .lots import RealisedLot, Term
from .wash_sales import WashSaleMatch

#: Accounts whose balances are money owed to or by the portfolio, and so part of NAV at face value.
CASH_LIKE_ACCOUNTS: tuple[str, ...] = (
    Accounts.CASH.code,
    Accounts.SALES_RECEIVABLE.code,
    Accounts.DIVIDENDS_RECEIVABLE.code,
    Accounts.INTEREST_RECEIVABLE.code,
    Accounts.TAX_RECLAIMABLE.code,
    Accounts.PURCHASES_PAYABLE.code,
)


@dataclass(frozen=True, slots=True)
class CashMovement:
    """Money that moves on one day and is agreed on another."""

    transaction_id: str
    currency: str
    amount: Decimal  # signed: positive into the account
    trade_date: date
    value_date: date
    kind: str
    description: str = ""
    failing: bool = False

    def is_pending(self, day: date) -> bool:
        """Agreed but not yet settled on ``day``."""
        return self.trade_date <= day and (self.failing or day < self.value_date)

    def is_settled(self, day: date) -> bool:
        return not self.failing and self.value_date <= day


@dataclass(frozen=True, slots=True)
class TradeActivity:
    """A change in a holding that happened at a price: a trade, a transfer, cash in lieu or merger cash.

    ``consideration`` is signed like the quantity: positive when the portfolio
    pays, negative when it receives. Transfers carry no consideration.
    """

    transaction_id: str
    instrument_id: str
    quantity: Decimal
    consideration: Decimal
    currency: str
    kind: str
    accrued: Decimal = Decimal(0)

    @property
    def is_flow(self) -> bool:
        """A transfer in kind is money entering or leaving, not a trade."""
        return self.kind == "transfer"


@dataclass
class DayActivity:
    """Everything that happened on one day, in the terms the value bridge needs."""

    day: date
    trades: list[TradeActivity] = field(default_factory=list)
    flows: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    income: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    costs: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    conversions: list[tuple[str, Decimal, str, Decimal]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.trades or self.flows or self.income or self.costs or self.conversions)


@dataclass(frozen=True)
class BookSnapshot:
    """End-of-day state: open lots and cash-like balances by account and currency."""

    day: date
    lots: dict[str, tuple[TaxLot, ...]]
    balances: dict[str, dict[str, Decimal]]

    def quantity(self, instrument_id: str) -> Decimal:
        return decimal_sum(lot.quantity for lot in self.lots.get(instrument_id, ()))

    def quantities(self) -> dict[str, Decimal]:
        return {key: self.quantity(key) for key in sorted(self.lots) if self.lots[key]}

    @property
    def instruments(self) -> tuple[str, ...]:
        return tuple(key for key in sorted(self.lots) if self.lots[key])

    def balance(self, account_code: str, currency: str) -> Decimal:
        return self.balances.get(account_code, {}).get(currency, Decimal(0))

    def cash(self, currency: str) -> Decimal:
        return self.balance(Accounts.CASH.code, currency)

    def cash_like(self, currency: str) -> Decimal:
        """Everything owed to the portfolio in one currency, less everything it owes."""
        return decimal_sum(self.balance(code, currency) for code in CASH_LIKE_ACCOUNTS)

    @property
    def currencies(self) -> tuple[str, ...]:
        found = {currency for values in self.balances.values() for currency, amount in values.items() if amount}
        found |= {lot.currency.code for lots in self.lots.values() for lot in lots}
        return tuple(sorted(found))


EMPTY_SNAPSHOT_DAY = date(1900, 1, 1)


@dataclass(frozen=True)
class CorporateActionRecord:
    action_id: str
    instrument_id: str
    ex_date: date
    kind: str
    notes: tuple[str, ...]
    quantity_before: Decimal
    quantity_after: Decimal


@dataclass
class Book:
    portfolio: Portfolio
    ledger: GeneralLedger
    open_lots: dict[str, tuple[TaxLot, ...]]
    realised: list[RealisedLot]
    wash_sales: list[WashSaleMatch]
    cash_movements: list[CashMovement]
    snapshots: list[BookSnapshot]
    activity: dict[date, DayActivity]
    transactions: list[Transaction]
    corporate_actions: list[CorporateActionRecord] = field(default_factory=list)
    as_of: date | None = None

    def __post_init__(self) -> None:
        self.snapshots.sort(key=lambda snapshot: snapshot.day)
        self._days = [snapshot.day for snapshot in self.snapshots]
        self._trade_index: dict[str, list[TradeActivity]] | None = None

    # ------------------------------------------------------------------ state by date
    @property
    def base_currency(self) -> str:
        return self.portfolio.base_currency.code

    @property
    def first_day(self) -> date | None:
        return self._days[0] if self._days else None

    @property
    def last_day(self) -> date | None:
        return self._days[-1] if self._days else None

    def snapshot_on(self, day: date) -> BookSnapshot:
        """The state at the close of ``day``: the last snapshot on or before it."""
        index = bisect.bisect_right(self._days, day)
        if index == 0:
            return BookSnapshot(EMPTY_SNAPSHOT_DAY, {}, {})
        return self.snapshots[index - 1]

    def positions_on(self, day: date) -> dict[str, Decimal]:
        return self.snapshot_on(day).quantities()

    def lots_on(self, day: date, instrument_id: str | None = None) -> tuple[TaxLot, ...]:
        lots = self.snapshot_on(day).lots
        if instrument_id is not None:
            return lots.get(instrument_id, ())
        return tuple(lot for key in sorted(lots) for lot in lots[key])

    def activity_between(self, start: date, end: date) -> list[DayActivity]:
        return [self.activity[day] for day in sorted(self.activity) if start < day <= end]

    # ------------------------------------------------------------------ settlement-date view
    def settled_position(self, instrument_id: str, day: date) -> Decimal:
        """Quantity as the custodian sees it: trade-date position less trades not yet settled."""
        pending = decimal_sum(
            trade.quantity
            for movement in self.cash_movements
            if movement.is_pending(day) and movement.kind in {"buy", "sell"}
            for trade in self.trades_for(movement.transaction_id)
            if trade.instrument_id == instrument_id
        )
        return self.snapshot_on(day).quantity(instrument_id) - pending

    def settled_positions(self, day: date) -> dict[str, Decimal]:
        """Every settled holding, including one sold in full whose sale has not yet settled."""
        instruments = set(self.snapshot_on(day).instruments)
        for movement in self.pending_movements(day):
            if movement.kind in {"buy", "sell"}:
                instruments |= {trade.instrument_id for trade in self.trades_for(movement.transaction_id)}
        positions = {key: self.settled_position(key, day) for key in sorted(instruments)}
        return {key: value for key, value in positions.items() if value}

    def trades_for(self, transaction_id: str) -> list[TradeActivity]:
        """The holding changes a transaction caused, by instrument and quantity."""
        if self._trade_index is None:
            index: dict[str, list[TradeActivity]] = defaultdict(list)
            for activity in self.activity.values():
                for trade in activity.trades:
                    index[trade.transaction_id].append(trade)
            self._trade_index = dict(index)
        return self._trade_index.get(transaction_id, [])

    def pending_movements(self, day: date) -> list[CashMovement]:
        return [movement for movement in self.cash_movements if movement.is_pending(day)]

    def settled_cash(self, currency: str, day: date) -> Decimal:
        return self.snapshot_on(day).cash(currency)

    def projected_cash(self, currency: str, day: date) -> Decimal:
        """Cash once everything already agreed has settled: the trade-date view of cash."""
        return self.settled_cash(currency, day) + decimal_sum(
            movement.amount
            for movement in self.pending_movements(day)
            if movement.currency == currency and not movement.failing
        )

    def cash_ladder(self, day: date, horizon_days: int = 10) -> dict[str, list[tuple[date, Decimal, Decimal]]]:
        """For each currency: (date, settling that day, settled balance after) over the coming days."""
        ladder: dict[str, list[tuple[date, Decimal, Decimal]]] = {}
        pending = self.pending_movements(day)
        currencies = sorted({movement.currency for movement in pending} | set(self.snapshot_on(day).currencies))
        for currency in currencies:
            balance = self.settled_cash(currency, day)
            rows: list[tuple[date, Decimal, Decimal]] = []
            for offset in range(1, horizon_days + 1):
                target = day + timedelta(days=offset)
                settling = decimal_sum(
                    movement.amount
                    for movement in pending
                    if movement.currency == currency and not movement.failing and movement.value_date == target
                )
                balance += settling
                if target.weekday() < 5:
                    rows.append((target, settling, balance))
            ladder[currency] = rows
        return ladder

    # ------------------------------------------------------------------ gains
    def realised_between(self, start: date, end: date) -> list[RealisedLot]:
        return [item for item in self.realised if start <= item.close_date <= end]

    def realised_in_year(self, year: int) -> list[RealisedLot]:
        return [item for item in self.realised if item.tax_year == year]

    def realised_summary(self, items: Iterable[RealisedLot] | None = None) -> dict[str, Decimal]:
        records = list(self.realised if items is None else items)
        summary: dict[str, Decimal] = defaultdict(Decimal)
        for item in records:
            prefix = "long" if item.term is Term.LONG else "short"
            gain = item.reportable_gain
            summary[f"{prefix}_gains" if gain >= 0 else f"{prefix}_losses"] += gain
            summary["disallowed"] += item.disallowed_loss
            summary["price"] += item.price_gain_base
            summary["fx"] += item.fx_gain_base
            summary["proceeds"] += item.proceeds_base
        summary["net"] = decimal_sum(item.reportable_gain for item in records)
        return dict(summary)

    def transactions_for(self, instrument_id: str) -> list[Transaction]:
        return [item for item in self.transactions if item.instrument_id == instrument_id]


def merge_balances(balances: Sequence[dict[str, dict[str, Decimal]]]) -> dict[str, dict[str, Decimal]]:
    merged: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for item in balances:
        for code, values in item.items():
            for currency, amount in values.items():
                merged[code][currency] += amount
    return {code: dict(values) for code, values in merged.items()}
