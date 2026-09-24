"""Journal entries: the only way a number gets into the ledger.

Every economic event becomes one balanced entry of two or more postings. The
sign convention is fixed here and nowhere else: **a debit is positive and a
credit is negative**, so an entry balances when its postings sum to zero and a
trial balance is a sum.

Each posting carries two amounts: the amount in the currency it happened in,
and the same amount in the portfolio's base currency at the rate of the day.
An entry must balance in base currency, always. It must also balance in each
local currency, unless it is a genuine currency exchange - buying euros with
dollars is the one event whose two sides are, by definition, in different
currencies.

Entries are immutable. A mistake is corrected by a reversing entry and a new
one, never by editing: the ledger is an audit trail first and a set of
balances second.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import Enum

from ..core.currency import get_currency
from ..core.decimals import decimal_sum, to_decimal
from ..core.exceptions import ValidationError
from .chart_of_accounts import LedgerAccount, account

#: Base amounts are products of decimals and are exact; this only absorbs the
#: last digit of a 28-digit context when three or more factors are multiplied.
BALANCE_TOLERANCE = Decimal("1e-9")


class EntryKind(str, Enum):
    TRADE = "trade"
    SETTLEMENT = "settlement"
    INCOME = "income"
    CORPORATE_ACTION = "corporate_action"
    CASH_MOVEMENT = "cash_movement"
    CURRENCY_EXCHANGE = "currency_exchange"
    FEE = "fee"
    TRANSFER = "transfer"
    REVERSAL = "reversal"


@dataclass(frozen=True, slots=True)
class Posting:
    """One line of a journal entry. Positive is a debit, negative a credit."""

    account_code: str
    amount: Decimal
    currency: str
    base_amount: Decimal
    instrument_id: str | None = None
    memo: str = ""

    def __post_init__(self) -> None:
        account(self.account_code)  # refuses codes outside the chart
        object.__setattr__(self, "amount", to_decimal(self.amount, field="amount"))
        object.__setattr__(self, "base_amount", to_decimal(self.base_amount, field="base_amount"))
        object.__setattr__(self, "currency", get_currency(self.currency).code)
        if (self.amount > 0 and self.base_amount < 0) or (self.amount < 0 and self.base_amount > 0):
            raise ValidationError(f"posting to {self.account_code}: local and base amounts have opposite signs")

    @property
    def account(self) -> LedgerAccount:
        return account(self.account_code)

    @property
    def is_debit(self) -> bool:
        return self.base_amount > 0 or (self.base_amount == 0 and self.amount > 0)

    def negated(self) -> Posting:
        return replace(self, amount=-self.amount, base_amount=-self.base_amount)


def debit(
    ledger_account: LedgerAccount,
    amount: Decimal,
    currency: str,
    rate: Decimal,
    *,
    instrument_id: str | None = None,
    memo: str = "",
) -> Posting:
    """A debit of ``amount`` translated to base at ``rate``."""
    return Posting(ledger_account.code, amount, currency, amount * rate, instrument_id, memo)


def credit(
    ledger_account: LedgerAccount,
    amount: Decimal,
    currency: str,
    rate: Decimal,
    *,
    instrument_id: str | None = None,
    memo: str = "",
) -> Posting:
    """A credit of ``amount`` translated to base at ``rate``."""
    return Posting(ledger_account.code, -amount, currency, -(amount * rate), instrument_id, memo)


def base_only(
    ledger_account: LedgerAccount,
    base_amount: Decimal,
    currency: str,
    *,
    instrument_id: str | None = None,
    memo: str = "",
) -> Posting:
    """A posting with no local amount: a currency gain exists only in base currency."""
    return Posting(ledger_account.code, Decimal(0), currency, base_amount, instrument_id, memo)


@dataclass(frozen=True, slots=True)
class JournalEntry:
    entry_id: str
    portfolio_id: str
    effective_date: date
    kind: EntryKind
    postings: tuple[Posting, ...]
    description: str = ""
    source_id: str | None = None
    reverses: str | None = None
    cross_currency: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entry_id.strip():
            raise ValidationError("a journal entry needs an identifier")
        postings = tuple(posting for posting in self.postings if posting.amount != 0 or posting.base_amount != 0)
        if len(postings) < 2:
            raise ValidationError(f"{self.entry_id}: an entry needs at least two non-zero postings")
        object.__setattr__(self, "postings", postings)
        imbalance = self.base_imbalance
        if abs(imbalance) > BALANCE_TOLERANCE:
            raise ValidationError(f"{self.entry_id}: debits and credits differ by {imbalance} in base currency")
        if not self.cross_currency:
            for currency, residual in self.local_imbalances().items():
                if abs(residual) > BALANCE_TOLERANCE:
                    raise ValidationError(f"{self.entry_id}: unbalanced by {residual} {currency}")

    @property
    def base_imbalance(self) -> Decimal:
        return decimal_sum(posting.base_amount for posting in self.postings)

    def local_imbalances(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for posting in self.postings:
            totals[posting.currency] += posting.amount
        return dict(totals)

    @property
    def total_debits(self) -> Decimal:
        return decimal_sum(posting.base_amount for posting in self.postings if posting.base_amount > 0)

    @property
    def currencies(self) -> tuple[str, ...]:
        return tuple(sorted({posting.currency for posting in self.postings}))

    def touches(self, ledger_account: LedgerAccount) -> bool:
        return any(posting.account_code == ledger_account.code for posting in self.postings)

    def reversal(self, entry_id: str, effective_date: date, *, description: str | None = None) -> JournalEntry:
        """The entry that cancels this one exactly, dated when the correction is made."""
        return JournalEntry(
            entry_id=entry_id,
            portfolio_id=self.portfolio_id,
            effective_date=effective_date,
            kind=EntryKind.REVERSAL,
            postings=tuple(posting.negated() for posting in self.postings),
            description=description or f"reversal of {self.entry_id}",
            source_id=self.source_id,
            reverses=self.entry_id,
            cross_currency=self.cross_currency,
        )

    def lines(self) -> list[tuple[str, str, str, str, str]]:
        """Printable rows: account, currency, debit, credit, base amount."""
        rows = []
        for posting in self.postings:
            local = posting.amount
            rows.append(
                (
                    str(posting.account),
                    posting.currency,
                    f"{local:,.2f}" if local > 0 else "",
                    f"{-local:,.2f}" if local < 0 else "",
                    f"{posting.base_amount:,.2f}",
                )
            )
        return rows


def entries_for(entries: Iterable[JournalEntry], source_id: str) -> list[JournalEntry]:
    return [entry for entry in entries if entry.source_id == source_id]


def check_balanced(entries: Sequence[JournalEntry]) -> Decimal:
    """The base-currency imbalance of a set of entries: zero for any set of valid entries."""
    return decimal_sum(entry.base_imbalance for entry in entries)
