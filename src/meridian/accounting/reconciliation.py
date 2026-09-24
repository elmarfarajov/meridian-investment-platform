"""Reconciliation: the book against the custodian, every day, break by break.

The custodian holds the securities and the cash; the book says what they
should be. Every morning the two are compared, and every difference - a
*break* - has to be explained before anyone trades on the numbers. Most
breaks are not errors: they are the two parties looking at the same thing on
different dates. The skill is in telling those apart from the few that are
real, quickly, so an operations team spends its day on the real ones.

The comparison is on the custodian's terms. A custodian reports *settled*
positions and cash, so the book is read on a settlement-date basis too: its
trade-date position less trades agreed but not yet settled. A break that is
only the difference between trade date and settlement date should never be
raised in the first place.

What is left is classified by cause, by testing candidate explanations
against the size of the difference - singly and in pairs, because two things
can go wrong on the same day in the same currency:

* **Failed settlement** - a trade the book settled and the custodian has not.
* **Duplicate** - the custodian booked a trade twice.
* **Corporate action** - the custodian's quantity is the book's times a split
  ratio: one side has applied a split the other has not.
* **Transposition** - the two quantities are the same digits in a different
  order, and differ by a multiple of nine: a keying error.
* **Income timing** - a dividend paid on a different day than the book expects.
* **Unbooked cash** - a charge or credit on the custodian's statement with no
  entry in the book.
* **Price** - the custodian's price differs from the golden copy beyond a
  tolerance. It moves the reported value, not the holding.

Anything else is **unexplained**, which is the list a human reads first.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from itertools import combinations

from ..core.decimals import decimal_sum
from ..domain.instruments import Instrument, instrument_price_scale
from .book import Book, CashMovement
from .sources import FxSource, PriceSource

TIMING_WINDOW_DAYS = 7
PRICE_TOLERANCE_BPS = 50.0
SPLIT_RATIOS: tuple[Decimal, ...] = tuple(
    Decimal(numerator) / Decimal(denominator)
    for numerator, denominator in (
        (2, 1),
        (3, 1),
        (4, 1),
        (5, 1),
        (10, 1),
        (3, 2),
        (1, 2),
        (1, 3),
        (1, 4),
        (1, 10),
        (2, 3),
    )
)


class BreakKind(str, Enum):
    POSITION = "position"
    CASH = "cash"
    PRICE = "price"
    MISSING_AT_CUSTODIAN = "missing at custodian"
    MISSING_IN_BOOK = "missing in book"


class BreakCause(str, Enum):
    FAILED_SETTLEMENT = "failed settlement"
    DUPLICATE = "duplicate booking"
    CORPORATE_ACTION = "corporate action"
    TRANSPOSITION = "transposition"
    INCOME_TIMING = "income timing"
    UNBOOKED_CASH = "unbooked cash"
    PRICE_DIFFERENCE = "price difference"
    UNEXPLAINED = "unexplained"

    @property
    def is_timing(self) -> bool:
        """Breaks that clear by themselves once both sides catch up."""
        return self in {BreakCause.FAILED_SETTLEMENT, BreakCause.INCOME_TIMING}


# ---------------------------------------------------------------------------- the custodian's side
@dataclass(frozen=True, slots=True)
class CustodianPosition:
    instrument_id: str
    quantity: Decimal
    price: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class CustodianCashLine:
    """An entry on the custodian's cash statement that the book may or may not know about."""

    currency: str
    amount: Decimal
    description: str
    reference: str | None = None


@dataclass(frozen=True)
class CustodianStatement:
    custodian: str
    account_id: str
    as_of: date
    positions: tuple[CustodianPosition, ...]
    cash: dict[str, Decimal]
    activity: tuple[CustodianCashLine, ...] = ()

    def position(self, instrument_id: str) -> CustodianPosition | None:
        return next((item for item in self.positions if item.instrument_id == instrument_id), None)

    def to_rows(self) -> list[tuple[str, str, str, str, str]]:
        """The statement as a custodian file: record type, key, quantity or amount, price, currency."""
        rows = [
            ("POS", item.instrument_id, f"{item.quantity}", f"{item.price}", item.currency) for item in self.positions
        ]
        rows += [("CASH", currency, f"{amount}", "", currency) for currency, amount in sorted(self.cash.items())]
        rows += [
            ("ACT", line.description, f"{line.amount}", line.reference or "", line.currency) for line in self.activity
        ]
        return rows


# ---------------------------------------------------------------------------- breaks
@dataclass(frozen=True, slots=True)
class Break:
    kind: BreakKind
    key: str  # instrument or currency
    as_of: date
    book: Decimal
    custodian: Decimal
    causes: tuple[BreakCause, ...]
    currency: str
    value_base: Decimal = Decimal(0)  # the break's size in base currency, for ranking
    explanation: str = ""

    @property
    def difference(self) -> Decimal:
        return self.book - self.custodian

    @property
    def cause(self) -> BreakCause:
        return self.causes[0]

    @property
    def identity(self) -> tuple[str, str]:
        return (self.kind.value, self.key)

    @property
    def is_explained(self) -> bool:
        return self.cause is not BreakCause.UNEXPLAINED


@dataclass(frozen=True)
class ReconciliationReport:
    as_of: date
    breaks: tuple[Break, ...]
    positions_compared: int
    cash_compared: int

    @property
    def matched_positions(self) -> int:
        position_kinds = {BreakKind.POSITION, BreakKind.MISSING_AT_CUSTODIAN, BreakKind.MISSING_IN_BOOK}
        return self.positions_compared - sum(1 for item in self.breaks if item.kind in position_kinds)

    @property
    def matched_cash(self) -> int:
        return self.cash_compared - sum(1 for item in self.breaks if item.kind is BreakKind.CASH)

    @property
    def match_rate(self) -> float:
        total = self.positions_compared + self.cash_compared
        return (self.matched_positions + self.matched_cash) / total if total else 1.0

    def by_cause(self) -> dict[BreakCause, int]:
        counts: dict[BreakCause, int] = {}
        for item in self.breaks:
            counts[item.cause] = counts.get(item.cause, 0) + 1
        return counts

    @property
    def unexplained(self) -> list[Break]:
        return [item for item in self.breaks if not item.is_explained]


# ---------------------------------------------------------------------------- the reconciler
@dataclass(frozen=True, slots=True)
class _Candidate:
    cause: BreakCause
    amount: Decimal
    note: str


class Reconciler:
    """Compares a book with a custodian statement and classifies what does not agree."""

    def __init__(
        self,
        book: Book,
        instruments: Mapping[str, Instrument],
        prices: PriceSource,
        fx: FxSource,
        *,
        timing_window_days: int = TIMING_WINDOW_DAYS,
        price_tolerance_bps: float = PRICE_TOLERANCE_BPS,
    ) -> None:
        self.book = book
        self.instruments = instruments
        self.prices = prices
        self.fx = fx
        self.window = timedelta(days=timing_window_days)
        self.price_tolerance_bps = price_tolerance_bps

    def _rate(self, currency: str, day: date) -> Decimal:
        return self.fx.rate(currency, self.book.base_currency, day)

    def reconcile(self, statement: CustodianStatement) -> ReconciliationReport:
        day = statement.as_of
        breaks: list[Break] = []
        state = self.book.snapshot_on(day)
        book_instruments = set(self.book.settled_positions(day)) | set(state.instruments)
        custodian_instruments = {item.instrument_id for item in statement.positions}
        compared = sorted(book_instruments | custodian_instruments)
        for instrument_id in compared:
            breaks.extend(self._position(instrument_id, statement))
        currencies = sorted(set(state.currencies) | set(statement.cash))
        for currency in currencies:
            found = self._cash(currency, statement)
            if found is not None:
                breaks.append(found)
        breaks.sort(key=lambda item: (item.cause is not BreakCause.UNEXPLAINED, -abs(item.value_base), item.key))
        return ReconciliationReport(day, tuple(breaks), len(compared), len(currencies))

    # ------------------------------------------------------------------ positions
    def _recent_trades(self, instrument_id: str, day: date) -> list[tuple[CashMovement, Decimal]]:
        """Trades in one instrument settled in the timing window, with their signed quantity."""
        found = []
        for movement in self.book.cash_movements:
            if movement.kind not in {"buy", "sell"} or movement.failing:
                continue
            if not (day - self.window < movement.value_date <= day):
                continue
            for trade in self.book.trades_for(movement.transaction_id):
                if trade.instrument_id == instrument_id and trade.quantity:
                    found.append((movement, trade.quantity))
        return found

    def _position(self, instrument_id: str, statement: CustodianStatement) -> list[Break]:
        day = statement.as_of
        ours = self.book.settled_position(instrument_id, day)
        theirs_line = statement.position(instrument_id)
        if theirs_line is not None and theirs_line.quantity == 0:
            theirs_line = None  # a zero line is the custodian saying it holds nothing
        theirs = theirs_line.quantity if theirs_line else Decimal(0)
        price = self._price(instrument_id, day) or (theirs_line.price if theirs_line else Decimal(0))
        currency = theirs_line.currency if theirs_line else self._currency_of(instrument_id)
        scale = self._scale(instrument_id)
        rate = self._rate(currency, day)
        found: list[Break] = []
        if ours != theirs:
            difference = ours - theirs
            kind = BreakKind.POSITION
            if theirs_line is None and ours:
                kind = BreakKind.MISSING_AT_CUSTODIAN
            elif not ours and theirs_line is not None:
                kind = BreakKind.MISSING_IN_BOOK
            causes, note = self._explain_position(instrument_id, ours, theirs, difference, day)
            found.append(
                Break(
                    kind,
                    instrument_id,
                    day,
                    ours,
                    theirs,
                    causes,
                    currency,
                    abs(difference) * price * scale * rate,
                    note,
                )
            )
        if theirs_line is not None and ours and theirs_line.price > 0 and price:
            deviation = float((theirs_line.price - price) / price) * 10_000
            if abs(deviation) > self.price_tolerance_bps:
                found.append(
                    Break(
                        BreakKind.PRICE,
                        instrument_id,
                        day,
                        price,
                        theirs_line.price,
                        (BreakCause.PRICE_DIFFERENCE,),
                        currency,
                        abs(theirs_line.price - price) * ours * scale * rate,
                        f"custodian price {deviation:+.0f} bp from the golden copy",
                    )
                )
        return found

    def _explain_position(
        self, instrument_id: str, ours: Decimal, theirs: Decimal, difference: Decimal, day: date
    ) -> tuple[tuple[BreakCause, ...], str]:
        candidates: list[_Candidate] = []
        for movement, quantity in self._recent_trades(instrument_id, day):
            candidates.append(
                _Candidate(
                    BreakCause.FAILED_SETTLEMENT, quantity, f"{movement.transaction_id} not settled at custodian"
                )
            )
            candidates.append(_Candidate(BreakCause.DUPLICATE, -quantity, f"{movement.transaction_id} booked twice"))
        explained = _search(difference, candidates)
        if explained:
            return explained
        if ours and theirs:
            ratio = theirs / ours
            if ratio in SPLIT_RATIOS:
                return (
                    BreakCause.CORPORATE_ACTION,
                ), f"custodian holds {ratio.normalize()}x the book: a split one side has not applied"
            if _is_transposition(ours, theirs):
                return (BreakCause.TRANSPOSITION,), f"{ours.normalize()} keyed as {theirs.normalize()}"
        return (BreakCause.UNEXPLAINED,), f"difference of {difference.normalize()}"

    # ------------------------------------------------------------------ cash
    def _cash(self, currency: str, statement: CustodianStatement) -> Break | None:
        day = statement.as_of
        ours = self.book.settled_cash(currency, day)
        theirs = statement.cash.get(currency, Decimal(0))
        if ours == theirs:
            return None
        difference = ours - theirs
        candidates: list[_Candidate] = []
        for movement in self.book.cash_movements:
            if movement.currency != currency or movement.failing:
                continue
            recent = day - self.window < movement.value_date <= day
            upcoming = day < movement.value_date <= day + self.window and movement.trade_date <= day
            if movement.kind in {"buy", "sell", "fx"} and recent:
                candidates.append(
                    _Candidate(BreakCause.FAILED_SETTLEMENT, movement.amount, f"{movement.transaction_id} not settled")
                )
            if movement.kind in {"dividend", "interest"}:
                if recent:
                    candidates.append(
                        _Candidate(BreakCause.INCOME_TIMING, movement.amount, f"{movement.transaction_id} not yet paid")
                    )
                if upcoming:
                    candidates.append(
                        _Candidate(BreakCause.INCOME_TIMING, -movement.amount, f"{movement.transaction_id} paid early")
                    )
        booked = {movement.transaction_id for movement in self.book.cash_movements}
        for line in statement.activity:
            if line.currency == currency and (line.reference is None or line.reference not in booked):
                candidates.append(
                    _Candidate(BreakCause.UNBOOKED_CASH, -line.amount, f"'{line.description}' not in the book")
                )
        causes, note = _search(difference, candidates) or ((BreakCause.UNEXPLAINED,), f"difference of {difference}")
        return Break(
            BreakKind.CASH,
            currency,
            day,
            ours,
            theirs,
            causes,
            currency,
            abs(difference) * self._rate(currency, day),
            note,
        )

    # ------------------------------------------------------------------ helpers
    def _price(self, instrument_id: str, day: date) -> Decimal | None:
        return self.prices.price(instrument_id, day)

    def _currency_of(self, instrument_id: str) -> str:
        instrument = self.instruments.get(instrument_id)
        return instrument.currency.code if instrument else self.book.base_currency

    def _scale(self, instrument_id: str) -> Decimal:
        instrument = self.instruments.get(instrument_id)
        return instrument_price_scale(instrument) if instrument else Decimal(1)


def _search(difference: Decimal, candidates: Sequence[_Candidate]) -> tuple[tuple[BreakCause, ...], str] | None:
    """The smallest set of candidate explanations (one or two) that adds up to the difference exactly."""
    for candidate in candidates:
        if candidate.amount == difference:
            return (candidate.cause,), candidate.note
    for first, second in combinations(candidates, 2):
        if first.amount + second.amount == difference:
            ordered = sorted((first, second), key=lambda item: -abs(item.amount))
            return tuple(item.cause for item in ordered), f"{ordered[0].note}; {ordered[1].note}"
    return None


def _is_transposition(first: Decimal, second: Decimal) -> bool:
    if first != first.to_integral_value() or second != second.to_integral_value() or first == second:
        return False
    a, b = str(int(first)), str(int(second))
    return sorted(a) == sorted(b) and (int(first) - int(second)) % 9 == 0


# ---------------------------------------------------------------------------- break register
@dataclass
class BreakRecord:
    identity: tuple[str, str]
    first_seen: date
    last_seen: date
    cause: BreakCause
    resolved_on: date | None = None
    observations: int = 1
    largest_value: Decimal = Decimal(0)

    def age(self, as_of: date) -> int:
        """Days open as of a date: up to ``as_of``, or up to the day it cleared if that came first."""
        end = min(self.resolved_on, as_of) if self.resolved_on else as_of
        return max((end - self.first_seen).days, 0)

    @property
    def is_open(self) -> bool:
        return self.resolved_on is None


@dataclass
class BreakRegister:
    """Breaks tracked from one statement to the next: when each appeared, how long it lasted, when it cleared."""

    records: list[BreakRecord] = field(default_factory=list)
    reports: list[ReconciliationReport] = field(default_factory=list)

    def update(self, report: ReconciliationReport) -> None:
        open_by_identity = {record.identity: record for record in self.records if record.is_open}
        seen = set()
        for item in report.breaks:
            seen.add(item.identity)
            record = open_by_identity.get(item.identity)
            if record is None:
                self.records.append(
                    BreakRecord(item.identity, report.as_of, report.as_of, item.cause, None, 1, item.value_base)
                )
            else:
                record.last_seen = report.as_of
                record.observations += 1
                record.largest_value = max(record.largest_value, item.value_base)
        for identity, record in open_by_identity.items():
            if identity not in seen:
                record.resolved_on = report.as_of
        self.reports.append(report)

    def open_on(self, day: date) -> list[BreakRecord]:
        return [
            record
            for record in self.records
            if record.first_seen <= day and (record.resolved_on is None or record.resolved_on > day)
        ]

    def aging(self, as_of: date, buckets: Sequence[int] = (1, 3, 5, 10)) -> dict[str, int]:
        """Open breaks by age in days: the report a head of operations asks for first."""
        labels = [f"<= {bucket}d" for bucket in buckets] + [f"> {buckets[-1]}d"]
        counts = dict.fromkeys(labels, 0)
        for record in self.open_on(as_of):
            age = record.age(as_of)
            for bucket, label in zip(buckets, labels, strict=False):
                if age <= bucket:
                    counts[label] += 1
                    break
            else:
                counts[labels[-1]] += 1
        return counts


def reconcile_series(reconciler: Reconciler, statements: Iterable[CustodianStatement]) -> BreakRegister:
    register = BreakRegister()
    for statement in sorted(statements, key=lambda item: item.as_of):
        register.update(reconciler.reconcile(statement))
    return register


def total_value(breaks: Iterable[Break]) -> Decimal:
    return decimal_sum(item.value_base for item in breaks)
