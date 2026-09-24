"""Reconciliation against a custodian: classification, the break register, and planted breaks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.accounting.builders import cash_transaction, purchase, sale
from meridian.accounting.custodian import (
    PlantedBreak,
    SyntheticCustodian,
    run_reconciliation,
    score_reconciliation,
    transpose,
)
from meridian.accounting.reconciliation import (
    BreakCause,
    BreakKind,
    BreakRegister,
    CustodianCashLine,
    CustodianPosition,
    CustodianStatement,
    Reconciler,
    _is_transposition,
    reconcile_series,
    total_value,
)
from meridian.accounting.sources import FixedFx, FixedPrices
from meridian.core.calendars import get_calendar
from meridian.core.enums import TransactionType
from meridian.domain.corporate_actions import dividend

D = date
DAYS = list(get_calendar("XNYS").business_days(D(2026, 3, 2), D(2026, 3, 31)))


@pytest.fixture
def setup(make_engine, instruments):
    fx = FixedFx({"EUR": "1.10"})
    prices = FixedPrices(
        {
            "US-AAPL": {day: "200" for day in DAYS},
            "US-MSFT": {day: "400" for day in DAYS},
            "DE-BAYN": {day: "25" for day in DAYS},
        }
    )
    engine = make_engine(fx, prices=prices)
    transactions = [
        cash_transaction(
            transaction_id="DEP",
            portfolio_id="P",
            kind=TransactionType.DEPOSIT,
            day=D(2026, 3, 2),
            amount="500000",
            currency="USD",
        ),
        cash_transaction(
            transaction_id="DEP-EUR",
            portfolio_id="P",
            kind=TransactionType.DEPOSIT,
            day=D(2026, 3, 2),
            amount="100000",
            currency="EUR",
        ),
        purchase(
            transaction_id="B1",
            portfolio_id="P",
            instrument_id="US-AAPL",
            day=D(2026, 3, 2),
            quantity=1250,
            price="200",
            currency="USD",
        ),
        purchase(
            transaction_id="B2",
            portfolio_id="P",
            instrument_id="US-MSFT",
            day=D(2026, 3, 9),
            quantity=300,
            price="400",
            currency="USD",
        ),
        purchase(
            transaction_id="B3",
            portfolio_id="P",
            instrument_id="DE-BAYN",
            day=D(2026, 3, 2),
            quantity=2000,
            price="25",
            currency="EUR",
        ),
        sale(
            transaction_id="S1",
            portfolio_id="P",
            instrument_id="US-AAPL",
            day=D(2026, 3, 16),
            quantity=250,
            price="200",
            currency="USD",
        ),
    ]
    actions = [dividend("DV", "DE-BAYN", D(2026, 3, 11), "1.00", "EUR", pay_date=D(2026, 3, 25))]
    book = engine.run(transactions, actions, until=D(2026, 3, 31))
    reconciler = Reconciler(book, instruments, prices, fx)
    custodian = SyntheticCustodian(book, instruments, prices, price_noise_bps=2)
    return book, reconciler, custodian


def statement(day: date, positions, cash, activity=()) -> CustodianStatement:
    return CustodianStatement(
        "Custodian",
        "A1",
        day,
        tuple(
            CustodianPosition(key, Decimal(quantity), Decimal(price), currency)
            for key, quantity, price, currency in positions
        ),
        {key: Decimal(value) for key, value in cash.items()},
        tuple(activity),
    )


def test_a_clean_statement_on_the_settlement_basis_has_no_breaks(setup):
    book, reconciler, custodian = setup
    for day in DAYS:
        report = reconciler.reconcile(custodian.clean_statement(day))
        assert report.breaks == (), day
        assert report.match_rate == 1.0
    # on the trade date of B2 the custodian does not have the shares yet, and that is not a break
    assert book.settled_position("US-MSFT", D(2026, 3, 9)) == 0
    assert custodian.clean_statement(D(2026, 3, 9)).position("US-MSFT") is None


def test_a_sold_out_position_awaiting_settlement_is_still_at_the_custodian(make_engine, instruments):
    fx = FixedFx({})
    prices = FixedPrices({"US-AAPL": {day: "200" for day in DAYS}})
    book = make_engine(fx, prices=prices).run(
        [
            purchase(
                transaction_id="B",
                portfolio_id="P",
                instrument_id="US-AAPL",
                day=D(2026, 3, 2),
                quantity=10,
                price="200",
                currency="USD",
            ),
            sale(
                transaction_id="S",
                portfolio_id="P",
                instrument_id="US-AAPL",
                day=D(2026, 3, 5),
                quantity=10,
                price="200",
                currency="USD",
            ),
        ]
    )
    assert book.settled_positions(D(2026, 3, 5)) == {"US-AAPL": Decimal(10)}
    reconciler = Reconciler(book, instruments, prices, fx)
    custodian = SyntheticCustodian(book, instruments, prices)
    assert reconciler.reconcile(custodian.clean_statement(D(2026, 3, 5))).breaks == ()


def test_each_cause_is_recognised_from_the_size_of_the_difference(setup):
    book, reconciler, _ = setup
    day = D(2026, 3, 10)  # B2 settled today; the dividend on BAYN goes ex tomorrow
    report = reconciler.reconcile(
        statement(
            day,
            [
                ("US-AAPL", 2150, "200.01", "USD"),  # 1,250 keyed as 2,150
                ("US-MSFT", 0, "400", "USD"),  # B2 not settled at the custodian
                ("DE-BAYN", 6000, "25", "EUR"),  # a 3-for-1 split applied by the custodian only
            ],
            {
                "USD": book.settled_cash("USD", day) + Decimal(120000) - Decimal(125),
                "EUR": book.settled_cash("EUR", day),
            },
            [CustodianCashLine("USD", Decimal(-125), "custody fee")],
        )
    )
    causes = {(item.kind, item.key): item.causes for item in report.breaks}
    assert causes[(BreakKind.POSITION, "US-AAPL")] == (BreakCause.TRANSPOSITION,)
    assert causes[(BreakKind.MISSING_AT_CUSTODIAN, "US-MSFT")] == (BreakCause.FAILED_SETTLEMENT,)
    assert causes[(BreakKind.POSITION, "DE-BAYN")] == (BreakCause.CORPORATE_ACTION,)
    # the failed purchase and the fee in the same currency are found as a pair
    assert set(causes[(BreakKind.CASH, "USD")]) == {BreakCause.FAILED_SETTLEMENT, BreakCause.UNBOOKED_CASH}
    assert report.unexplained == []
    assert report.by_cause()[BreakCause.TRANSPOSITION] == 1
    assert report.matched_cash == 1  # EUR agrees
    assert total_value(report.breaks) > 0
    usd = next(item for item in report.breaks if item.key == "USD")
    assert usd.difference == Decimal(-120000) + Decimal(125)
    assert usd.is_explained and "not settled" in usd.explanation


def test_duplicates_price_differences_and_the_unexplained(setup):
    book, reconciler, _ = setup
    day = D(2026, 3, 17)  # S1 (250 AAPL) settled today
    report = reconciler.reconcile(
        statement(
            day,
            [
                ("US-AAPL", 750, "200", "USD"),  # the custodian booked the sale twice
                ("US-MSFT", 300, "412", "USD"),  # +300 bp from the golden copy
                ("DE-BAYN", 2000, "25", "EUR"),
                ("US-JNJ", 55, "150", "USD"),  # nothing in the book
            ],
            {"USD": book.settled_cash("USD", day) - Decimal("1234.56"), "EUR": book.settled_cash("EUR", day)},
        )
    )
    causes = {(item.kind, item.key): item.cause for item in report.breaks}
    assert causes[(BreakKind.POSITION, "US-AAPL")] is BreakCause.DUPLICATE
    assert causes[(BreakKind.PRICE, "US-MSFT")] is BreakCause.PRICE_DIFFERENCE
    assert causes[(BreakKind.MISSING_IN_BOOK, "US-JNJ")] is BreakCause.UNEXPLAINED
    assert causes[(BreakKind.CASH, "USD")] is BreakCause.UNEXPLAINED
    # unexplained breaks are listed first: they are what a person has to read
    assert not report.breaks[0].is_explained
    price_break = next(item for item in report.breaks if item.kind is BreakKind.PRICE)
    assert price_break.value_base == Decimal(12) * 300
    assert "+300 bp" in price_break.explanation


def test_a_dividend_paid_early_or_a_coupon_paid_late_is_income_timing(setup):
    book, reconciler, _ = setup
    day = D(2026, 3, 23)  # the BAYN dividend is receivable, payable on the 25th
    net = book.snapshot_on(day).balance("1210", "EUR")
    report = reconciler.reconcile(
        statement(
            day,
            [("US-AAPL", 1000, "200", "USD"), ("US-MSFT", 300, "400", "USD"), ("DE-BAYN", 2000, "25", "EUR")],
            {"USD": book.settled_cash("USD", day), "EUR": book.settled_cash("EUR", day) + net},
        )
    )
    (only,) = report.breaks
    assert only.cause is BreakCause.INCOME_TIMING and "paid early" in only.explanation
    assert BreakCause.INCOME_TIMING.is_timing and not BreakCause.TRANSPOSITION.is_timing


def test_the_transposition_test_and_generator():
    assert _is_transposition(Decimal(1250), Decimal(2150))
    assert _is_transposition(Decimal(1011), Decimal(1101))
    assert not _is_transposition(Decimal(1250), Decimal(1250))
    assert not _is_transposition(Decimal(1250), Decimal(1260))
    assert not _is_transposition(Decimal("12.5"), Decimal("21.5"))
    assert transpose(Decimal(1250)) == Decimal(2150)
    assert transpose(Decimal(1011)) == Decimal(1101)  # never a leading zero
    assert transpose(Decimal(1111)) == Decimal(1111)


def test_the_register_ages_breaks_and_clears_them(setup):
    _, reconciler, custodian = setup
    planted = [
        PlantedBreak(BreakCause.UNBOOKED_CASH, "USD", D(2026, 3, 18), 6, Decimal(-75), "custody fee"),
        PlantedBreak(BreakCause.PRICE_DIFFERENCE, "US-AAPL", D(2026, 3, 24), 2, Decimal(150)),
    ]
    register = reconcile_series(reconciler, [custodian.statement(day, planted) for day in DAYS])
    fee = next(record for record in register.records if record.identity == ("cash", "USD"))
    assert fee.first_seen == D(2026, 3, 18) and fee.resolved_on == D(2026, 3, 24)
    assert fee.observations == 4 and fee.age(D(2026, 3, 31)) == 6 and fee.age(D(2026, 3, 20)) == 2
    assert not fee.is_open and fee.cause is BreakCause.UNBOOKED_CASH
    assert len(register.open_on(D(2026, 3, 24))) == 1
    assert register.aging(D(2026, 3, 24)) == {"<= 1d": 1, "<= 3d": 0, "<= 5d": 0, "<= 10d": 0, "> 10d": 0}
    assert register.aging(D(2026, 3, 31))["<= 1d"] == 0
    empty = BreakRegister()
    assert empty.aging(D(2026, 3, 31)) == {"<= 1d": 0, "<= 3d": 0, "<= 5d": 0, "<= 10d": 0, "> 10d": 0}


def test_planted_breaks_are_found_with_the_right_cause(setup):
    _, reconciler, custodian = setup
    plan = custodian.random_plan(DAYS, per_cause=2, seed=5)
    assert {item.cause for item in plan} >= {
        BreakCause.FAILED_SETTLEMENT,
        BreakCause.UNBOOKED_CASH,
        BreakCause.PRICE_DIFFERENCE,
        BreakCause.CORPORATE_ACTION,
        BreakCause.TRANSPOSITION,
    }
    register, score = run_reconciliation(reconciler, custodian, DAYS, plan)
    assert score.recall == 1.0
    assert score.precision == 1.0
    assert score.missed == [] and score.false_alarms == []
    again = score_reconciliation(register.reports, custodian, plan)
    assert again.recall == score.recall
    assert all(item.recall == 1.0 for item in score.causes.values())
