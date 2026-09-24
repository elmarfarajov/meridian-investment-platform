"""A synthetic custodian, and breaks planted where the answer is known.

A reconciliation that finds nothing wrong on clean data proves nothing, and a
real custodian file cannot be published. So, as with the market data quality
rules (ADR 0013), the reconciler is measured against breaks planted on
purpose: the custodian's statement is generated from the book's own
settlement-date view, then damaged in the ways custodian statements really
disagree with a book - and every damage is recorded, with the cause the
reconciler ought to report and the days it lasts.

The custodian also prices the holdings itself, a few basis points away from
the golden copy, because a custodian price that agrees to the last decimal is
not a realistic test of a price tolerance.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from ..domain.instruments import Instrument
from .book import Book
from .reconciliation import (
    Break,
    BreakCause,
    BreakKind,
    BreakRegister,
    CustodianCashLine,
    CustodianPosition,
    CustodianStatement,
    Reconciler,
    ReconciliationReport,
)
from .sources import PriceSource


@dataclass(frozen=True, slots=True)
class PlantedBreak:
    """One planted disagreement: what, where, from when and for how long."""

    cause: BreakCause
    key: str  # a transaction, an instrument or a currency, depending on the cause
    start: date
    days: int = 1
    amount: Decimal = Decimal(0)  # ratio, bps or cash, depending on the cause
    note: str = ""

    def active(self, day: date) -> bool:
        return self.start <= day < self.start + timedelta(days=self.days)


@dataclass(frozen=True, slots=True)
class ExpectedBreak:
    kind: BreakKind
    key: str
    cause: BreakCause
    planted: PlantedBreak


class SyntheticCustodian:
    """Custodian statements generated from a book, with planted breaks applied."""

    def __init__(
        self,
        book: Book,
        instruments: Mapping[str, Instrument],
        prices: PriceSource,
        *,
        name: str = "Northern Trust",
        price_noise_bps: float = 4.0,
        seed: int = 3,
    ) -> None:
        self.book = book
        self.instruments = instruments
        self.prices = prices
        self.name = name
        self.price_noise_bps = price_noise_bps
        self.seed = seed

    # ------------------------------------------------------------------ clean statements
    def clean_statement(self, day: date) -> CustodianStatement:
        rng = random.Random(f"{self.seed}-{day.isoformat()}")
        positions = []
        for instrument_id, quantity in self.book.settled_positions(day).items():
            price = self.prices.price(instrument_id, day) or Decimal(0)
            noise = Decimal(repr(round(rng.uniform(-self.price_noise_bps, self.price_noise_bps) / 10_000, 6)))
            instrument = self.instruments[instrument_id]
            quoted = (price * (1 + noise)).quantize(Decimal("0.0001"))
            positions.append(CustodianPosition(instrument_id, quantity, quoted, instrument.currency.code))
        state = self.book.snapshot_on(day)
        cash = {currency: self.book.settled_cash(currency, day) for currency in state.currencies}
        return CustodianStatement(self.name, self.book.portfolio.account_id or "", day, tuple(positions), cash)

    # ------------------------------------------------------------------ damaged statements
    def statement(self, day: date, planted: Sequence[PlantedBreak] = ()) -> CustodianStatement:
        clean = self.clean_statement(day)
        positions = {item.instrument_id: item for item in clean.positions}
        cash: dict[str, Decimal] = defaultdict(Decimal, clean.cash)
        activity: list[CustodianCashLine] = []
        movements = {movement.transaction_id: movement for movement in self.book.cash_movements}
        for item in planted:
            if not item.active(day):
                continue
            cause = item.cause
            if cause is BreakCause.FAILED_SETTLEMENT:
                movement = movements[item.key]
                for trade in self.book.trades_for(item.key):
                    self._shift(positions, trade.instrument_id, -trade.quantity)
                cash[movement.currency] -= movement.amount
            elif cause is BreakCause.DUPLICATE:
                for trade in self.book.trades_for(item.key):
                    self._shift(positions, trade.instrument_id, trade.quantity)
            elif cause is BreakCause.CORPORATE_ACTION:
                line = positions[item.key]
                positions[item.key] = CustodianPosition(
                    line.instrument_id, line.quantity * item.amount, line.price, line.currency
                )
            elif cause is BreakCause.TRANSPOSITION:
                line = positions[item.key]
                positions[item.key] = CustodianPosition(
                    line.instrument_id, transpose(line.quantity), line.price, line.currency
                )
            elif cause is BreakCause.INCOME_TIMING:
                # amount +1: the custodian paid before the book's pay date; -1: after it
                movement = movements[item.key]
                cash[movement.currency] += movement.amount * (item.amount or 1)
            elif cause is BreakCause.UNBOOKED_CASH:
                cash[item.key] += item.amount
                activity.append(CustodianCashLine(item.key, item.amount, item.note or "custody fee"))
            elif cause is BreakCause.PRICE_DIFFERENCE:
                line = positions[item.key]
                shifted = (line.price * (1 + item.amount / 10_000)).quantize(Decimal("0.0001"))
                positions[item.key] = CustodianPosition(line.instrument_id, line.quantity, shifted, line.currency)
            elif cause is BreakCause.UNEXPLAINED:
                instrument = self.instruments[item.key]
                price = self.prices.price(item.key, day) or Decimal(1)
                positions[item.key] = CustodianPosition(item.key, item.amount, price, instrument.currency.code)
        return CustodianStatement(
            clean.custodian,
            clean.account_id,
            day,
            tuple(line for line in positions.values() if line.quantity),
            dict(cash),
            tuple(activity),
        )

    @staticmethod
    def _shift(positions: dict[str, CustodianPosition], instrument_id: str, quantity: Decimal) -> None:
        line = positions.get(instrument_id)
        if line is None:
            return
        positions[instrument_id] = CustodianPosition(instrument_id, line.quantity + quantity, line.price, line.currency)

    # ------------------------------------------------------------------ what the reconciler should say
    def expected(self, day: date, planted: Sequence[PlantedBreak]) -> list[ExpectedBreak]:
        movements = {movement.transaction_id: movement for movement in self.book.cash_movements}
        found: list[ExpectedBreak] = []
        for item in planted:
            if not item.active(day):
                continue
            if item.cause in {BreakCause.FAILED_SETTLEMENT, BreakCause.DUPLICATE}:
                for trade in self.book.trades_for(item.key):
                    found.append(ExpectedBreak(BreakKind.POSITION, trade.instrument_id, item.cause, item))
                if item.cause is BreakCause.FAILED_SETTLEMENT:
                    found.append(ExpectedBreak(BreakKind.CASH, movements[item.key].currency, item.cause, item))
            elif item.cause in {BreakCause.CORPORATE_ACTION, BreakCause.TRANSPOSITION}:
                found.append(ExpectedBreak(BreakKind.POSITION, item.key, item.cause, item))
            elif item.cause is BreakCause.INCOME_TIMING:
                found.append(ExpectedBreak(BreakKind.CASH, movements[item.key].currency, item.cause, item))
            elif item.cause is BreakCause.UNBOOKED_CASH:
                found.append(ExpectedBreak(BreakKind.CASH, item.key, item.cause, item))
            elif item.cause is BreakCause.PRICE_DIFFERENCE:
                found.append(ExpectedBreak(BreakKind.PRICE, item.key, item.cause, item))
            elif item.cause is BreakCause.UNEXPLAINED:
                found.append(ExpectedBreak(BreakKind.MISSING_IN_BOOK, item.key, item.cause, item))
        return found

    # ------------------------------------------------------------------ plans
    def random_plan(self, days: Sequence[date], *, per_cause: int = 3, seed: int = 11) -> list[PlantedBreak]:
        """Planted breaks spread over ``days``, never two on the same key on the same day."""
        rng = random.Random(seed)
        plan: list[PlantedBreak] = []
        window = set(days)
        trades = [
            movement
            for movement in self.book.cash_movements
            if movement.kind in {"buy", "sell"} and movement.value_date in window and not movement.failing
        ]
        early = [
            movement
            for movement in self.book.cash_movements
            if movement.kind == "dividend" and movement.value_date - timedelta(days=3) in window
        ]
        late = [
            movement
            for movement in self.book.cash_movements
            if movement.kind == "interest" and movement.value_date in window
        ]
        held = sorted({key for day in days for key in self.book.snapshot_on(day).instruments})
        not_held = sorted(
            set(self.instruments) - set(held) - {key for key in self.instruments if key.startswith("CASH.")}
        )
        currencies = sorted({currency for day in days for currency in self.book.snapshot_on(day).currencies})

        def pick(pool: Sequence, count: int) -> list:
            return rng.sample(list(pool), min(count, len(pool)))

        for movement in pick(trades, per_cause):
            plan.append(
                PlantedBreak(
                    BreakCause.FAILED_SETTLEMENT, movement.transaction_id, movement.value_date, rng.randint(1, 4)
                )
            )
        for movement in pick(trades, per_cause):
            plan.append(
                PlantedBreak(BreakCause.DUPLICATE, movement.transaction_id, movement.value_date, rng.randint(1, 3))
            )
        for movement in pick(early, per_cause):
            plan.append(
                PlantedBreak(
                    BreakCause.INCOME_TIMING,
                    movement.transaction_id,
                    movement.value_date - timedelta(days=2),
                    2,
                    Decimal(1),
                    "dividend paid early",
                )
            )
        for movement in pick(late, per_cause):
            plan.append(
                PlantedBreak(
                    BreakCause.INCOME_TIMING,
                    movement.transaction_id,
                    movement.value_date,
                    2,
                    Decimal(-1),
                    "coupon paid late",
                )
            )
        for currency in pick(currencies, per_cause):
            fee = Decimal(rng.choice(["-125.00", "-48.50", "-310.00", "-75.25"]))
            plan.append(
                PlantedBreak(
                    BreakCause.UNBOOKED_CASH, currency, rng.choice(days), rng.randint(2, 8), fee, "custody fee"
                )
            )
        for kind in (BreakCause.CORPORATE_ACTION, BreakCause.TRANSPOSITION, BreakCause.PRICE_DIFFERENCE):
            for instrument_id in pick(held, per_cause):
                amount = {
                    BreakCause.CORPORATE_ACTION: Decimal(rng.choice([2, 3, 4])),
                    BreakCause.TRANSPOSITION: Decimal(0),
                    BreakCause.PRICE_DIFFERENCE: Decimal(rng.choice([-180, -95, 120, 240])),
                }[kind]
                length = rng.randint(1, 5)
                # only on days the custodian holds the security for the whole life of the break
                starts = [
                    day
                    for index, day in enumerate(days)
                    if all(
                        self.book.settled_position(instrument_id, later) > 0
                        for later in days[index : index + length + 3]
                        if later < day + timedelta(days=length)
                    )
                ]
                if starts:
                    plan.append(PlantedBreak(kind, instrument_id, rng.choice(starts), length, amount))
        for instrument_id in pick(not_held, 1):
            plan.append(
                PlantedBreak(BreakCause.UNEXPLAINED, instrument_id, rng.choice(days), rng.randint(3, 10), Decimal(250))
            )
        return self._without_collisions(plan, days)

    def _without_collisions(self, plan: list[PlantedBreak], days: Sequence[date]) -> list[PlantedBreak]:
        """Drop plans that would land on a key another plan already damages on an overlapping day."""
        kept: list[PlantedBreak] = []
        occupied: dict[tuple[str, date], BreakCause] = {}
        for item in plan:
            keys = {expected.key for day in days if item.active(day) for expected in self.expected(day, [item])}
            if item.cause is BreakCause.TRANSPOSITION:
                quantity = next(
                    (self.book.settled_position(item.key, day) for day in days if item.active(day)), Decimal(0)
                )
                if transpose(quantity) == quantity:
                    continue
            active_days = [day for day in days if item.active(day)]
            if any((key, day) in occupied for key in keys for day in active_days):
                continue
            if item.cause is BreakCause.TRANSPOSITION and any(
                self.book.settled_position(item.key, day) != self.book.settled_position(item.key, active_days[0])
                for day in active_days
            ):
                continue
            for key in keys:
                for day in active_days:
                    occupied[(key, day)] = item.cause
            kept.append(item)
        return kept


def transpose(quantity: Decimal) -> Decimal:
    """Swap the first pair of adjacent distinct digits of a whole quantity: 1,250 keyed as 2,150.

    A swap that would put a zero in front is skipped - nobody keys 1,011 as 0,111 -
    so the result always has as many digits as the original, or it is unchanged.
    """
    digits = list(str(int(quantity)))
    for index in range(len(digits) - 1):
        if digits[index] == digits[index + 1] or (index == 0 and digits[1] == "0"):
            continue
        digits[index], digits[index + 1] = digits[index + 1], digits[index]
        break
    return Decimal("".join(digits))


# ---------------------------------------------------------------------------- measurement
@dataclass
class CauseScore:
    cause: BreakCause
    planted: int = 0
    detected: int = 0

    @property
    def recall(self) -> float:
        return self.detected / self.planted if self.planted else 1.0


@dataclass
class ReconciliationScore:
    causes: dict[BreakCause, CauseScore] = field(default_factory=dict)
    raised: int = 0
    attributed: int = 0
    false_alarms: list[Break] = field(default_factory=list)
    missed: list[ExpectedBreak] = field(default_factory=list)

    @property
    def recall(self) -> float:
        planted = sum(item.planted for item in self.causes.values())
        detected = sum(item.detected for item in self.causes.values())
        return detected / planted if planted else 1.0

    @property
    def precision(self) -> float:
        return self.attributed / self.raised if self.raised else 1.0


def _family(kind: BreakKind) -> BreakKind:
    """A holding missing on one side is still a position break about that holding."""
    if kind in {BreakKind.MISSING_AT_CUSTODIAN, BreakKind.MISSING_IN_BOOK}:
        return BreakKind.POSITION
    return kind


def score_reconciliation(
    reports: Iterable[ReconciliationReport], custodian: SyntheticCustodian, planted: Sequence[PlantedBreak]
) -> ReconciliationScore:
    """Recall by cause and overall precision: a planted break counts only if found with the right cause."""
    score = ReconciliationScore()
    for report in reports:
        expected = custodian.expected(report.as_of, planted)
        raised = {(_family(item.kind), item.key): item for item in report.breaks}
        matched: set[tuple[BreakKind, str]] = set()
        for item in expected:
            entry = score.causes.setdefault(item.cause, CauseScore(item.cause))
            entry.planted += 1
            key = (_family(item.kind), item.key)
            found = raised.get(key)
            if found is not None and item.cause in found.causes:
                entry.detected += 1
                matched.add(key)
            else:
                score.missed.append(item)
        score.raised += len(report.breaks)
        score.attributed += len(matched)
        score.false_alarms.extend(item for key, item in raised.items() if key not in matched)
    return score


def run_reconciliation(
    reconciler: Reconciler, custodian: SyntheticCustodian, days: Sequence[date], planted: Sequence[PlantedBreak]
) -> tuple[BreakRegister, ReconciliationScore]:
    register = BreakRegister()
    reports = []
    for day in days:
        report = reconciler.reconcile(custodian.statement(day, planted))
        register.update(report)
        reports.append(report)
    return register, score_reconciliation(reports, custodian, planted)
