"""The chart of accounts: every number in the book lives in exactly one of these.

A portfolio accounting system is a general ledger with an investment sub-ledger
attached. The accounts below are the ones a fund accountant would recognise:
investments carried at cost, the receivables and payables that exist between
trade date and settlement date, accrued income, contributed capital, and the
income and expense lines that explain why the capital grew or shrank.

The numbering follows the usual convention - 1xxx assets, 2xxx liabilities,
3xxx capital, 4xxx income, 5xxx expenses - so that a trial balance sorted by
code reads like a balance sheet followed by an income statement.

Unrealised appreciation is deliberately absent. The ledger is the book of
record at cost; market value is a *valuation* of that book, computed from it
each day (see :mod:`meridian.accounting.valuation`) rather than posted into it.
That keeps the ledger free of entries that are reversed and re-posted every
night, and keeps one source of truth for what was paid and received.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..core.exceptions import ValidationError


class AccountClass(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    CAPITAL = "capital"
    INCOME = "income"
    EXPENSE = "expense"

    @property
    def normal_balance(self) -> int:
        """+1 for accounts that normally carry a debit balance, -1 for credit balances."""
        return 1 if self in {AccountClass.ASSET, AccountClass.EXPENSE} else -1

    @property
    def is_balance_sheet(self) -> bool:
        return self in {AccountClass.ASSET, AccountClass.LIABILITY, AccountClass.CAPITAL}


@dataclass(frozen=True, slots=True)
class LedgerAccount:
    code: str
    name: str
    account_class: AccountClass
    description: str = ""

    def __post_init__(self) -> None:
        if not (self.code.isdigit() and len(self.code) == 4):
            raise ValidationError(f"account code {self.code!r} must be four digits")
        expected = {"1": AccountClass.ASSET, "2": AccountClass.LIABILITY, "3": AccountClass.CAPITAL}
        leading = self.code[0]
        if leading in expected and expected[leading] is not self.account_class:
            raise ValidationError(f"account {self.code} is numbered as {expected[leading].value}")
        if leading == "4" and self.account_class is not AccountClass.INCOME:
            raise ValidationError(f"account {self.code} is numbered as income")
        if leading == "5" and self.account_class is not AccountClass.EXPENSE:
            raise ValidationError(f"account {self.code} is numbered as an expense")

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class Accounts:
    """The accounts the posting rules use, as named constants."""

    CASH = LedgerAccount("1000", "Cash", AccountClass.ASSET, "Settled cash at the custodian, one balance per currency")
    INVESTMENTS = LedgerAccount(
        "1100", "Investments at cost", AccountClass.ASSET, "Open tax lots at their book cost, including commissions"
    )
    ACCRUED_INTEREST_PURCHASED = LedgerAccount(
        "1150",
        "Accrued interest purchased",
        AccountClass.ASSET,
        "Interest paid to the seller of a bond, recovered from the next coupon",
    )
    SALES_RECEIVABLE = LedgerAccount(
        "1200", "Receivable for investments sold", AccountClass.ASSET, "Sales traded but not yet settled"
    )
    DIVIDENDS_RECEIVABLE = LedgerAccount(
        "1210", "Dividends receivable", AccountClass.ASSET, "Dividends gone ex but not yet paid, net of withholding"
    )
    INTEREST_RECEIVABLE = LedgerAccount(
        "1220", "Interest receivable", AccountClass.ASSET, "Coupons due but not yet received"
    )
    TAX_RECLAIMABLE = LedgerAccount(
        "1230",
        "Withholding tax reclaimable",
        AccountClass.ASSET,
        "Withholding above the treaty rate, recoverable from the source country",
    )
    PURCHASES_PAYABLE = LedgerAccount(
        "2000", "Payable for investments purchased", AccountClass.LIABILITY, "Purchases traded but not yet settled"
    )
    CONTRIBUTED_CAPITAL = LedgerAccount(
        "3000", "Contributed capital", AccountClass.CAPITAL, "Cash deposited less cash withdrawn"
    )
    TRANSFERRED_IN_KIND = LedgerAccount(
        "3100",
        "Securities transferred in kind",
        AccountClass.CAPITAL,
        "Securities received from or delivered to another custodian, at carried-over cost",
    )
    REALISED_SHORT_TERM = LedgerAccount(
        "4000", "Realised gain - short term", AccountClass.INCOME, "Price gains on lots held one year or less"
    )
    REALISED_LONG_TERM = LedgerAccount(
        "4010", "Realised gain - long term", AccountClass.INCOME, "Price gains on lots held more than one year"
    )
    REALISED_FX_INVESTMENTS = LedgerAccount(
        "4020",
        "Realised currency gain on investments",
        AccountClass.INCOME,
        "The part of a sale's base-currency gain due to the exchange rate moving since purchase",
    )
    REALISED_FX_SETTLEMENT = LedgerAccount(
        "4030",
        "Realised currency gain on settlement",
        AccountClass.INCOME,
        "Rate moves between trade date and settlement date, and on currency conversions",
    )
    DIVIDEND_INCOME = LedgerAccount("4100", "Dividend income", AccountClass.INCOME, "Gross of withholding tax")
    INTEREST_INCOME = LedgerAccount(
        "4110", "Interest income", AccountClass.INCOME, "Coupons, net of accrued interest purchased"
    )
    FEES = LedgerAccount(
        "5000", "Custody and account fees", AccountClass.EXPENSE, "Fees not attributable to a single trade"
    )
    WITHHOLDING_TAX = LedgerAccount(
        "5100", "Withholding tax", AccountClass.EXPENSE, "Tax deducted at source that cannot be reclaimed"
    )
    TRANSACTION_TAXES = LedgerAccount(
        "5200", "Transaction taxes", AccountClass.EXPENSE, "Stamp duty and similar taxes on disposals"
    )


CHART_OF_ACCOUNTS: tuple[LedgerAccount, ...] = tuple(
    sorted(
        (value for name, value in vars(Accounts).items() if isinstance(value, LedgerAccount)),
        key=lambda account: account.code,
    )
)
_BY_CODE = {account.code: account for account in CHART_OF_ACCOUNTS}


def account(code: str) -> LedgerAccount:
    try:
        return _BY_CODE[code]
    except KeyError:
        raise ValidationError(f"no account {code!r} in the chart of accounts") from None


def accounts_of(account_class: AccountClass) -> tuple[LedgerAccount, ...]:
    return tuple(item for item in CHART_OF_ACCOUNTS if item.account_class is account_class)
