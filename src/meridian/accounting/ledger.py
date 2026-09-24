"""The general ledger: journal entries accumulated into balances.

The ledger answers three questions, each as of any date:

* **What is the balance of an account?** In base currency, and broken down by
  currency and by instrument where the account has sub-ledgers (cash by
  currency, investments by security).
* **Does the book balance?** The trial balance lists every account's debit or
  credit balance; the two columns must be equal. That equality is checked on
  every date the valuation runs, not taken on trust.
* **What happened?** The activity in an account between two dates, entry by
  entry, which is what an auditor or an operations analyst actually reads.

The ledger is append-only. Entries are kept in posting order and indexed by
effective date, so a balance "as of" a date is a prefix sum.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.decimals import decimal_sum
from ..core.exceptions import ValidationError
from .chart_of_accounts import CHART_OF_ACCOUNTS, AccountClass, LedgerAccount, account
from .journal import BALANCE_TOLERANCE, JournalEntry, Posting


@dataclass(frozen=True, slots=True)
class TrialBalanceLine:
    account: LedgerAccount
    balance: Decimal  # base currency, debit positive

    @property
    def debit(self) -> Decimal:
        return self.balance if self.balance > 0 else Decimal(0)

    @property
    def credit(self) -> Decimal:
        return -self.balance if self.balance < 0 else Decimal(0)

    @property
    def natural(self) -> Decimal:
        """The balance with the sign of the account's normal side, so a healthy asset or income is positive."""
        return self.balance * self.account.account_class.normal_balance


@dataclass(frozen=True)
class TrialBalance:
    as_of: date
    lines: tuple[TrialBalanceLine, ...]

    @property
    def total_debits(self) -> Decimal:
        return decimal_sum(line.debit for line in self.lines)

    @property
    def total_credits(self) -> Decimal:
        return decimal_sum(line.credit for line in self.lines)

    @property
    def difference(self) -> Decimal:
        return self.total_debits - self.total_credits

    @property
    def is_balanced(self) -> bool:
        return abs(self.difference) <= BALANCE_TOLERANCE * max(len(self.lines), 1)

    def total(self, account_class: AccountClass) -> Decimal:
        """The natural balance of every account in a class."""
        return decimal_sum(line.natural for line in self.lines if line.account.account_class is account_class)

    @property
    def net_income(self) -> Decimal:
        return self.total(AccountClass.INCOME) - self.total(AccountClass.EXPENSE)

    @property
    def net_assets(self) -> Decimal:
        """Assets less liabilities at cost: capital plus retained earnings, by the accounting identity."""
        return self.total(AccountClass.ASSET) - self.total(AccountClass.LIABILITY)

    def line(self, ledger_account: LedgerAccount) -> TrialBalanceLine | None:
        return next((line for line in self.lines if line.account == ledger_account), None)

    def rows(self) -> list[tuple[str, str, str, str]]:
        return [
            (
                line.account.code,
                line.account.name,
                f"{line.debit:,.2f}" if line.debit else "",
                f"{line.credit:,.2f}" if line.credit else "",
            )
            for line in self.lines
        ]


class GeneralLedger:
    """An append-only set of journal entries with balance queries by date."""

    def __init__(self, portfolio_id: str, base_currency: str, entries: Iterable[JournalEntry] = ()) -> None:
        self.portfolio_id = portfolio_id
        self.base_currency = base_currency
        self._entries: list[JournalEntry] = []
        self._ids: set[str] = set()
        self._dates: list[date] = []
        for entry in entries:
            self.post(entry)

    # ------------------------------------------------------------------ posting
    def post(self, entry: JournalEntry) -> JournalEntry:
        if entry.portfolio_id != self.portfolio_id:
            raise ValidationError(f"{entry.entry_id} belongs to {entry.portfolio_id}, not {self.portfolio_id}")
        if entry.entry_id in self._ids:
            raise ValidationError(f"entry {entry.entry_id} has already been posted")
        # keep effective-date order; entries on the same date stay in posting order
        index = bisect.bisect_right(self._dates, entry.effective_date)
        self._entries.insert(index, entry)
        self._dates.insert(index, entry.effective_date)
        self._ids.add(entry.entry_id)
        return entry

    def post_all(self, entries: Iterable[JournalEntry]) -> int:
        count = 0
        for entry in entries:
            self.post(entry)
            count += 1
        return count

    # ------------------------------------------------------------------ reading
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[JournalEntry]:
        return iter(self._entries)

    def __contains__(self, entry_id: object) -> bool:
        return entry_id in self._ids

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    def entry(self, entry_id: str) -> JournalEntry:
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        raise ValidationError(f"no entry {entry_id!r} in the ledger")

    def entries_until(self, as_of: date | None) -> Sequence[JournalEntry]:
        if as_of is None:
            return self._entries
        return self._entries[: bisect.bisect_right(self._dates, as_of)]

    def entries_between(self, start: date, end: date) -> Sequence[JournalEntry]:
        """Entries with ``start < effective_date <= end``: the activity that moves a balance from start to end."""
        return self._entries[bisect.bisect_right(self._dates, start) : bisect.bisect_right(self._dates, end)]

    def postings(self, as_of: date | None = None) -> Iterator[tuple[JournalEntry, Posting]]:
        for entry in self.entries_until(as_of):
            for posting in entry.postings:
                yield entry, posting

    # ------------------------------------------------------------------ balances
    def balance(self, ledger_account: LedgerAccount, as_of: date | None = None) -> Decimal:
        """Base-currency balance of one account, debit positive."""
        return decimal_sum(
            posting.base_amount for _, posting in self.postings(as_of) if posting.account_code == ledger_account.code
        )

    def local_balances(self, ledger_account: LedgerAccount, as_of: date | None = None) -> dict[str, Decimal]:
        """Balance of one account in each currency it holds."""
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for _, posting in self.postings(as_of):
            if posting.account_code == ledger_account.code:
                totals[posting.currency] += posting.amount
        return {currency: amount for currency, amount in sorted(totals.items()) if amount != 0}

    def base_balances_by_currency(self, ledger_account: LedgerAccount, as_of: date | None = None) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for _, posting in self.postings(as_of):
            if posting.account_code == ledger_account.code:
                totals[posting.currency] += posting.base_amount
        return dict(sorted(totals.items()))

    def instrument_balances(self, ledger_account: LedgerAccount, as_of: date | None = None) -> dict[str, Decimal]:
        """Base-currency balance per instrument: the investment sub-ledger."""
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for _, posting in self.postings(as_of):
            if posting.account_code == ledger_account.code and posting.instrument_id:
                totals[posting.instrument_id] += posting.base_amount
        return {key: value for key, value in sorted(totals.items()) if value != 0}

    def trial_balance(self, as_of: date | None = None, *, include_zero: bool = False) -> TrialBalance:
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for _, posting in self.postings(as_of):
            totals[posting.account_code] += posting.base_amount
        lines = tuple(
            TrialBalanceLine(ledger_account, totals.get(ledger_account.code, Decimal(0)))
            for ledger_account in CHART_OF_ACCOUNTS
            if include_zero or totals.get(ledger_account.code, Decimal(0)) != 0
        )
        last = self._dates[-1] if self._dates else date.min
        return TrialBalance(as_of or last, lines)

    def activity(
        self, ledger_account: LedgerAccount, start: date, end: date
    ) -> list[tuple[JournalEntry, Posting, Decimal]]:
        """Each posting to an account in ``(start, end]`` with the running base balance after it."""
        running = self.balance(ledger_account, start)
        rows: list[tuple[JournalEntry, Posting, Decimal]] = []
        for entry in self.entries_between(start, end):
            for posting in entry.postings:
                if posting.account_code == ledger_account.code:
                    running += posting.base_amount
                    rows.append((entry, posting, running))
        return rows

    def movement(self, ledger_account: LedgerAccount, start: date, end: date) -> Decimal:
        return decimal_sum(
            posting.base_amount
            for entry in self.entries_between(start, end)
            for posting in entry.postings
            if posting.account_code == ledger_account.code
        )

    def account_codes(self) -> tuple[str, ...]:
        return tuple(sorted({posting.account_code for _, posting in self.postings()}))

    def accounts_used(self) -> tuple[LedgerAccount, ...]:
        return tuple(account(code) for code in self.account_codes())
