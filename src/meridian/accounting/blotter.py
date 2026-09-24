"""The trade blotter: every version of every transaction, and when it was known.

Trades are booked, then amended - the price was wrong, the quantity was
allocated to the wrong account - and sometimes cancelled outright. A back
office that edits the record in place cannot answer the questions that
matter afterwards: what did the book say at yesterday's close, which reports
went out on a number that has since changed, and by how much.

So the blotter never edits. Each booking, amendment and cancellation is a new
version with the moment it was recorded, exactly as the market data store
keeps every observation (ADR 0009). The book is then a *pure function of the
blotter as known at a moment*: replaying ``as_known_at(t)`` through the
accounting engine reproduces the book exactly as it stood at ``t``, and the
difference between two replays is the restatement a correction caused.

The blotter also tracks settlement. A trade has a contractual settlement date
from the rule table; if the counterparty fails to deliver, the actual date is
later and the cash stays where it was. A failed trade is the commonest cause
of a cash break with the custodian, so it is recorded rather than assumed away.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum

from ..core.exceptions import ValidationError
from ..domain.transactions import Transaction
from ..marketdata.bitemporal import as_utc

#: Metadata key set on a transaction whose settlement is failing with no settled date yet.
FAILING_FLAG = "settlement_failing"


class VersionKind(str, Enum):
    BOOKED = "booked"
    AMENDED = "amended"
    CANCELLED = "cancelled"


class SettlementStatus(str, Enum):
    PENDING = "pending"
    SETTLED = "settled"
    FAILING = "failing"


@dataclass(frozen=True, slots=True)
class TradeVersion:
    transaction: Transaction
    version: int
    kind: VersionKind
    recorded_at: datetime
    reason: str = ""

    @property
    def transaction_id(self) -> str:
        return self.transaction.transaction_id


@dataclass(frozen=True, slots=True)
class SettlementFail:
    """A trade that did not settle on its contractual date."""

    transaction_id: str
    contractual: date
    actual: date | None  # None while still failing
    reason: str = ""

    def days_failing(self, as_of: date) -> int:
        end = self.actual or as_of
        return max((min(end, as_of) - self.contractual).days, 0)


class TradeBlotter:
    """Versioned transactions, append-only."""

    def __init__(self) -> None:
        self._versions: dict[str, list[TradeVersion]] = {}
        self._fails: dict[str, SettlementFail] = {}

    # ------------------------------------------------------------------ recording
    def book(self, transaction: Transaction, recorded_at: datetime, *, reason: str = "") -> TradeVersion:
        if transaction.transaction_id in self._versions:
            raise ValidationError(f"{transaction.transaction_id} is already booked; amend it instead")
        version = TradeVersion(transaction, 1, VersionKind.BOOKED, as_utc(recorded_at), reason)
        self._versions[transaction.transaction_id] = [version]
        return version

    def book_all(self, transactions: Iterable[Transaction], recorded_at: datetime) -> int:
        count = 0
        for transaction in transactions:
            self.book(transaction, recorded_at)
            count += 1
        return count

    def amend(self, transaction: Transaction, recorded_at: datetime, *, reason: str = "") -> TradeVersion:
        """A corrected version of a booked trade, keeping its identifier."""
        history = self._history(transaction.transaction_id)
        latest = history[-1]
        if latest.kind is VersionKind.CANCELLED:
            raise ValidationError(f"{transaction.transaction_id} was cancelled; book a new trade instead")
        moment = as_utc(recorded_at)
        if moment < latest.recorded_at:
            raise ValidationError(f"{transaction.transaction_id}: an amendment cannot predate the version it corrects")
        version = TradeVersion(transaction, latest.version + 1, VersionKind.AMENDED, moment, reason)
        history.append(version)
        return version

    def cancel(self, transaction_id: str, recorded_at: datetime, *, reason: str = "") -> TradeVersion:
        history = self._history(transaction_id)
        latest = history[-1]
        if latest.kind is VersionKind.CANCELLED:
            raise ValidationError(f"{transaction_id} is already cancelled")
        version = TradeVersion(
            latest.transaction, latest.version + 1, VersionKind.CANCELLED, as_utc(recorded_at), reason
        )
        history.append(version)
        return version

    def fail(self, transaction_id: str, *, actual: date | None = None, reason: str = "") -> SettlementFail:
        """Record that a trade missed its contractual settlement; ``actual`` is when it finally settled."""
        transaction = self.current(transaction_id)
        if transaction is None:
            raise ValidationError(f"{transaction_id} is not a live trade")
        contractual = transaction.settles_on
        if actual is not None and actual <= contractual:
            raise ValidationError(f"{transaction_id}: a fail settles after its contractual date")
        record = SettlementFail(transaction_id, contractual, actual, reason)
        self._fails[transaction_id] = record
        return record

    # ------------------------------------------------------------------ reading
    def _history(self, transaction_id: str) -> list[TradeVersion]:
        try:
            return self._versions[transaction_id]
        except KeyError:
            raise ValidationError(f"no trade {transaction_id!r} on the blotter") from None

    def history(self, transaction_id: str) -> tuple[TradeVersion, ...]:
        return tuple(self._history(transaction_id))

    def __len__(self) -> int:
        return len(self._versions)

    def current(self, transaction_id: str, known_at: datetime | None = None) -> Transaction | None:
        """The live version of one trade as known at a moment, or None if cancelled or not yet booked."""
        moment = as_utc(known_at) if known_at else None
        live: TradeVersion | None = None
        for version in self._history(transaction_id):
            if moment is not None and version.recorded_at > moment:
                break
            live = version
        if live is None or live.kind is VersionKind.CANCELLED:
            return None
        return self._with_settlement(live.transaction)

    def as_known_at(self, known_at: datetime | None = None) -> list[Transaction]:
        """Every live transaction as the blotter stood at ``known_at`` (now, if omitted)."""
        found: list[Transaction] = []
        for transaction_id in self._versions:
            transaction = self.current(transaction_id, known_at)
            if transaction is not None:
                found.append(transaction)
        return sorted(found, key=lambda item: (item.trade_date, item.transaction_id))

    def _with_settlement(self, transaction: Transaction) -> Transaction:
        record = self._fails.get(transaction.transaction_id)
        if record is None:
            return transaction
        if record.actual is None:
            # still failing: the engine keeps the cash and the securities where they were
            return replace(transaction, metadata={**transaction.metadata, FAILING_FLAG: "true"})
        return replace(transaction, settlement_date=record.actual)

    def status(self, transaction_id: str, as_of: date) -> SettlementStatus:
        transaction = self.current(transaction_id)
        if transaction is None:
            raise ValidationError(f"{transaction_id} is not a live trade")
        record = self._fails.get(transaction_id)
        if record is not None and as_of >= record.contractual and (record.actual is None or as_of < record.actual):
            return SettlementStatus.FAILING
        settles = record.actual if record and record.actual else transaction.settles_on
        return SettlementStatus.SETTLED if as_of >= settles else SettlementStatus.PENDING

    def fails(self, as_of: date | None = None) -> list[SettlementFail]:
        records = list(self._fails.values())
        if as_of is not None:
            records = [
                record
                for record in records
                if record.contractual <= as_of and (record.actual is None or record.actual > as_of)
            ]
        return sorted(records, key=lambda record: (record.contractual, record.transaction_id))

    def corrections(self, since: datetime, until: datetime | None = None) -> list[TradeVersion]:
        """Amendments and cancellations recorded in ``(since, until]``: what a restatement report lists."""
        start = as_utc(since)
        end = as_utc(until) if until else None
        return sorted(
            (
                version
                for history in self._versions.values()
                for version in history
                if version.kind is not VersionKind.BOOKED
                and version.recorded_at > start
                and (end is None or version.recorded_at <= end)
            ),
            key=lambda version: (version.recorded_at, version.transaction_id),
        )

    def knowledge_times(self) -> tuple[datetime, ...]:
        return tuple(sorted({version.recorded_at for history in self._versions.values() for version in history}))


def blotter_from(transactions: Sequence[Transaction], recorded_at: datetime) -> TradeBlotter:
    blotter = TradeBlotter()
    blotter.book_all(transactions, recorded_at)
    return blotter
