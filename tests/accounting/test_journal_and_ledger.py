"""The chart of accounts, journal entries and the general ledger."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.accounting.chart_of_accounts import (
    CHART_OF_ACCOUNTS,
    AccountClass,
    Accounts,
    LedgerAccount,
    account,
    accounts_of,
)
from meridian.accounting.journal import (
    EntryKind,
    JournalEntry,
    Posting,
    base_only,
    check_balanced,
    credit,
    debit,
    entries_for,
)
from meridian.accounting.ledger import GeneralLedger
from meridian.core import ValidationError

D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)


def entry(entry_id: str, day: date, *postings: Posting, cross: bool = False, source: str | None = None) -> JournalEntry:
    return JournalEntry(
        entry_id=entry_id,
        portfolio_id="P",
        effective_date=day,
        kind=EntryKind.TRADE,
        postings=postings,
        source_id=source,
        cross_currency=cross,
    )


def deposit(entry_id: str, day: date, amount: str, currency: str = "USD", rate: str = "1") -> JournalEntry:
    value, fx = Decimal(amount), Decimal(rate)
    return entry(
        entry_id,
        day,
        debit(Accounts.CASH, value, currency, fx),
        credit(Accounts.CONTRIBUTED_CAPITAL, value, currency, fx),
    )


# ---------------------------------------------------------------------------- chart of accounts
def test_the_chart_is_numbered_by_class_and_sorted():
    codes = [item.code for item in CHART_OF_ACCOUNTS]
    assert codes == sorted(codes)
    assert len(set(codes)) == len(codes)
    for item in CHART_OF_ACCOUNTS:
        expected = {
            "1": AccountClass.ASSET,
            "2": AccountClass.LIABILITY,
            "3": AccountClass.CAPITAL,
            "4": AccountClass.INCOME,
            "5": AccountClass.EXPENSE,
        }[item.code[0]]
        assert item.account_class is expected


def test_normal_balances_follow_the_accounting_equation():
    assert AccountClass.ASSET.normal_balance == 1
    assert AccountClass.EXPENSE.normal_balance == 1
    for kind in (AccountClass.LIABILITY, AccountClass.CAPITAL, AccountClass.INCOME):
        assert kind.normal_balance == -1
    assert AccountClass.CAPITAL.is_balance_sheet
    assert not AccountClass.INCOME.is_balance_sheet


def test_account_lookup_and_refusals():
    assert account("1000") is Accounts.CASH
    assert Accounts.CASH in accounts_of(AccountClass.ASSET)
    with pytest.raises(ValidationError, match="no account"):
        account("9999")
    with pytest.raises(ValidationError, match="four digits"):
        LedgerAccount("10", "Short", AccountClass.ASSET)
    with pytest.raises(ValidationError, match="numbered as asset"):
        LedgerAccount("1999", "Wrong", AccountClass.LIABILITY)
    with pytest.raises(ValidationError, match="income"):
        LedgerAccount("4999", "Wrong", AccountClass.EXPENSE)
    with pytest.raises(ValidationError, match="expense"):
        LedgerAccount("5999", "Wrong", AccountClass.INCOME)


# ---------------------------------------------------------------------------- journal entries
def test_postings_use_debit_positive_and_refuse_mismatched_signs():
    dr = debit(Accounts.CASH, Decimal(100), "EUR", Decimal("1.1"))
    cr = credit(Accounts.CONTRIBUTED_CAPITAL, Decimal(100), "EUR", Decimal("1.1"))
    assert dr.amount == 100 and dr.base_amount == Decimal("110.0") and dr.is_debit
    assert cr.amount == -100 and not cr.is_debit
    assert dr.negated().amount == -100
    with pytest.raises(ValidationError, match="opposite signs"):
        Posting("1000", Decimal(1), "USD", Decimal(-1))
    with pytest.raises(ValidationError, match="no account"):
        Posting("0000", Decimal(1), "USD", Decimal(1))


def test_an_entry_must_balance_in_base_and_in_each_currency():
    ok = deposit("E1", D1, "250.00", "EUR", "1.2")
    assert ok.base_imbalance == 0
    assert ok.total_debits == Decimal("300.000")
    assert ok.currencies == ("EUR",)
    with pytest.raises(ValidationError, match="base currency"):
        entry(
            "E2",
            D1,
            debit(Accounts.CASH, Decimal(100), "USD", Decimal(1)),
            credit(Accounts.CONTRIBUTED_CAPITAL, Decimal(90), "USD", Decimal(1)),
        )
    # balances in base but not in euros: only a currency exchange may do that
    lopsided = (
        Posting("1000", Decimal(100), "EUR", Decimal(110)),
        Posting("1000", Decimal(-110), "USD", Decimal(-110)),
    )
    with pytest.raises(ValidationError, match="unbalanced by"):
        entry("E3", D1, *lopsided)
    exchange = entry("E4", D1, *lopsided, cross=True)
    assert exchange.local_imbalances() == {"EUR": Decimal(100), "USD": Decimal(-110)}


def test_entries_need_two_non_zero_lines_and_an_identifier():
    with pytest.raises(ValidationError, match="two non-zero"):
        entry("E1", D1, debit(Accounts.CASH, Decimal(0), "USD", Decimal(1)), debit(Accounts.CASH, Decimal(5), "USD", 1))
    with pytest.raises(ValidationError, match="identifier"):
        deposit(" ", D1, "1")


def test_a_currency_gain_exists_only_in_base():
    # receivable booked at 1.10, cash received at 1.12: a gain of 2.00 on 100 euros
    settled = entry(
        "S1",
        D2,
        Posting("1000", Decimal(100), "EUR", Decimal(112)),
        Posting("1200", Decimal(-100), "EUR", Decimal(-110)),
        base_only(Accounts.REALISED_FX_SETTLEMENT, Decimal(-2), "EUR"),
    )
    assert settled.local_imbalances() == {"EUR": Decimal(0)}
    assert settled.base_imbalance == 0


def test_a_reversal_cancels_the_original_exactly():
    original = deposit("E1", D1, "1000")
    reversal = original.reversal("E1R", D3)
    assert reversal.kind is EntryKind.REVERSAL
    assert reversal.reverses == "E1"
    assert reversal.effective_date == D3
    assert check_balanced([original, reversal]) == 0
    ledger = GeneralLedger("P", "USD", [original, reversal])
    assert ledger.balance(Accounts.CASH) == 0
    assert ledger.balance(Accounts.CASH, D2) == 1000


def test_printable_lines_show_debits_and_credits_in_their_columns():
    rows = deposit("E1", D1, "1234.5").lines()
    assert rows[0][2] == "1,234.50" and rows[0][3] == ""
    assert rows[1][2] == "" and rows[1][3] == "1,234.50"


# ---------------------------------------------------------------------------- the ledger
@pytest.fixture
def ledger() -> GeneralLedger:
    book = GeneralLedger("P", "USD")
    book.post(deposit("E1", D1, "10000"))
    book.post(deposit("E2", D1, "500", "EUR", "1.10"))
    book.post(
        entry(
            "E3",
            D2,
            Posting("1100", Decimal(4000), "USD", Decimal(4000), "AAPL"),
            Posting("2000", Decimal(-4000), "USD", Decimal(-4000), "AAPL"),
            source="T1",
        )
    )
    book.post(
        entry(
            "E4",
            D3,
            Posting("2000", Decimal(4000), "USD", Decimal(4000), "AAPL"),
            Posting("1000", Decimal(-4000), "USD", Decimal(-4000)),
            source="T1",
        )
    )
    return book


def test_balances_by_date_currency_and_instrument(ledger: GeneralLedger):
    assert ledger.balance(Accounts.CASH) == Decimal(6550)
    assert ledger.balance(Accounts.CASH, D2) == Decimal(10550)
    assert ledger.local_balances(Accounts.CASH) == {"EUR": Decimal(500), "USD": Decimal(6000)}
    assert ledger.base_balances_by_currency(Accounts.CASH)["EUR"] == Decimal("550.00")
    assert ledger.instrument_balances(Accounts.INVESTMENTS) == {"AAPL": Decimal(4000)}
    assert ledger.balance(Accounts.PURCHASES_PAYABLE, D2) == Decimal(-4000)
    assert ledger.balance(Accounts.PURCHASES_PAYABLE) == 0


def test_the_trial_balance_balances_and_satisfies_the_identity(ledger: GeneralLedger):
    trial = ledger.trial_balance()
    assert trial.is_balanced
    assert trial.total_debits == trial.total_credits == Decimal(10550)
    assert trial.net_assets == trial.total(AccountClass.CAPITAL) + trial.net_income
    assert trial.line(Accounts.CASH).debit == Decimal(6550)
    assert trial.line(Accounts.CONTRIBUTED_CAPITAL).credit == Decimal(10550)
    assert trial.line(Accounts.DIVIDEND_INCOME) is None
    assert len(ledger.trial_balance(include_zero=True).lines) == len(CHART_OF_ACCOUNTS)
    assert [row[0] for row in trial.rows()] == ["1000", "1100", "3000"]


def test_activity_carries_a_running_balance(ledger: GeneralLedger):
    rows = ledger.activity(Accounts.CASH, D1, D3)
    assert [entry.entry_id for entry, _, _ in rows] == ["E4"]
    assert rows[-1][2] == Decimal(6550)
    assert ledger.movement(Accounts.CASH, D1, D3) == Decimal(-4000)
    assert [item.entry_id for item in ledger.entries_between(D1, D2)] == ["E3"]


def test_the_ledger_refuses_duplicates_and_foreign_entries(ledger: GeneralLedger):
    with pytest.raises(ValidationError, match="already been posted"):
        ledger.post(deposit("E1", D1, "1"))
    foreign = JournalEntry(
        entry_id="X",
        portfolio_id="OTHER",
        effective_date=D1,
        kind=EntryKind.CASH_MOVEMENT,
        postings=deposit("tmp", D1, "1").postings,
    )
    with pytest.raises(ValidationError, match="belongs to"):
        ledger.post(foreign)
    with pytest.raises(ValidationError, match="no entry"):
        ledger.entry("NOPE")


def test_entries_are_kept_in_effective_date_order_whatever_the_posting_order():
    book = GeneralLedger("P", "USD")
    book.post(deposit("late", D3, "1"))
    book.post(deposit("early", D1, "1"))
    book.post(deposit("middle", D2, "1"))
    assert [item.entry_id for item in book] == ["early", "middle", "late"]
    assert "middle" in book and len(book) == 3
    assert [item.entry_id for item in entries_for(book.entries, "none")] == []
    assert book.account_codes() == ("1000", "3000")
    assert book.accounts_used() == (Accounts.CASH, Accounts.CONTRIBUTED_CAPITAL)


amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1000000"), places=2)
rates = st.decimals(min_value=Decimal("0.5"), max_value=Decimal("2.0"), places=4)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(amounts, rates, st.sampled_from(["USD", "EUR", "GBP"])), min_size=1, max_size=25))
def test_any_sequence_of_balanced_entries_keeps_the_trial_balance_balanced(movements):
    book = GeneralLedger("P", "USD")
    for index, (amount, rate, currency) in enumerate(movements):
        book.post(deposit(f"D{index}", D1, str(amount), currency, str(rate)))
        # spend a third of it on a security, at the same rate
        spent = (amount / 3).quantize(Decimal("0.01"))
        if spent:
            book.post(
                entry(
                    f"B{index}",
                    D2,
                    debit(Accounts.INVESTMENTS, spent, currency, rate, instrument_id="X"),
                    credit(Accounts.CASH, spent, currency, rate),
                )
            )
    trial = book.trial_balance()
    assert trial.is_balanced
    assert trial.net_assets == trial.total(AccountClass.CAPITAL)
