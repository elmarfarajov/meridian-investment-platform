from datetime import date
from decimal import Decimal

import pytest

from meridian.core import Money, TransactionType, ValidationError
from meridian.domain import Transaction, build_trade


def test_buy_costs_cash_and_increases_the_position():
    trade = build_trade(
        transaction_id="T1",
        portfolio_id="P1",
        instrument_id="AAPL",
        trade_date=date(2026, 9, 16),
        quantity=100,
        price="185.50",
        currency="USD",
        fees="4.95",
    )
    assert trade.gross == Money("18550.00", "USD")
    assert trade.net == Money("18554.95", "USD")
    assert trade.cash_impact == Money("-18554.95", "USD")
    assert trade.signed_quantity == Decimal(100)


def test_sell_raises_cash_net_of_costs():
    trade = build_trade(
        transaction_id="T2",
        portfolio_id="P1",
        instrument_id="AAPL",
        trade_date=date(2026, 9, 16),
        quantity=100,
        price="190.00",
        currency="USD",
        buy=False,
        fees="4.95",
        taxes="1.05",
    )
    assert trade.gross == Money("19000.00", "USD")
    assert trade.total_costs == Money("6.00", "USD")
    assert trade.cash_impact == Money("18994.00", "USD")
    assert trade.signed_quantity == Decimal(-100)


def test_income_and_cash_movements():
    dividend = Transaction(
        transaction_id="D1",
        portfolio_id="P1",
        instrument_id="AAPL",
        transaction_type=TransactionType.DIVIDEND,
        trade_date=date(2026, 9, 16),
        currency="USD",
        gross_amount="240.00",
        taxes="36.00",
    )
    assert dividend.cash_impact == Money("204.00", "USD")
    assert dividend.signed_quantity == Decimal(0)
    assert dividend.transaction_type.is_income

    deposit = Transaction(
        transaction_id="C1",
        portfolio_id="P1",
        transaction_type=TransactionType.DEPOSIT,
        trade_date=date(2026, 9, 16),
        currency="USD",
        gross_amount="50000",
    )
    assert deposit.cash_impact == Money(50000, "USD")

    fee = Transaction(
        transaction_id="F1",
        portfolio_id="P1",
        transaction_type=TransactionType.FEE,
        trade_date=date(2026, 9, 30),
        currency="USD",
        gross_amount="125.00",
    )
    assert fee.cash_impact == Money("-125.00", "USD")


def test_settlement_defaults_to_the_trade_date():
    trade = build_trade(
        transaction_id="T3",
        portfolio_id="P1",
        instrument_id="AAPL",
        trade_date=date(2026, 9, 16),
        quantity=10,
        price=100,
        currency="USD",
    )
    assert trade.settles_on == date(2026, 9, 16)
    settled = build_trade(
        transaction_id="T4",
        portfolio_id="P1",
        instrument_id="AAPL",
        trade_date=date(2026, 9, 16),
        quantity=10,
        price=100,
        currency="USD",
        settlement_date=date(2026, 9, 17),
    )
    assert settled.settles_on == date(2026, 9, 17)


def test_foreign_currency_translation_uses_the_recorded_rate():
    trade = build_trade(
        transaction_id="T5",
        portfolio_id="P1",
        instrument_id="SAP",
        trade_date=date(2026, 9, 16),
        quantity=100,
        price="150.00",
        currency="EUR",
    )
    in_eur = trade.cash_impact
    translated = Transaction(
        transaction_id="T5",
        portfolio_id="P1",
        instrument_id="SAP",
        transaction_type=TransactionType.BUY,
        trade_date=date(2026, 9, 16),
        quantity=100,
        price="150.00",
        currency="EUR",
        fx_rate="1.0850",
    ).in_base_currency("USD")
    assert in_eur == Money("-15000.00", "EUR")
    assert translated == Money(Decimal("-15000.00") * Decimal("1.0850"), "USD")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": -5},
        {"price": -1},
        {"fees": -1},
        {"fx_rate": 0},
    ],
)
def test_sign_conventions_are_enforced(kwargs):
    base = dict(
        transaction_id="T6",
        portfolio_id="P1",
        instrument_id="AAPL",
        transaction_type=TransactionType.BUY,
        trade_date=date(2026, 9, 16),
        quantity=10,
        price=100,
        currency="USD",
    )
    with pytest.raises(ValidationError):
        Transaction(**{**base, **kwargs})


def test_structural_validation():
    with pytest.raises(ValidationError):  # a trade needs an instrument
        Transaction(
            transaction_id="T7",
            portfolio_id="P1",
            transaction_type=TransactionType.BUY,
            trade_date=date(2026, 9, 16),
            quantity=10,
            price=100,
            currency="USD",
        )
    with pytest.raises(ValidationError):  # settlement cannot precede the trade
        Transaction(
            transaction_id="T8",
            portfolio_id="P1",
            instrument_id="AAPL",
            transaction_type=TransactionType.BUY,
            trade_date=date(2026, 9, 16),
            settlement_date=date(2026, 9, 15),
            quantity=10,
            price=100,
            currency="USD",
        )
    with pytest.raises(ValidationError):  # a trade needs a quantity
        Transaction(
            transaction_id="T9",
            portfolio_id="P1",
            instrument_id="AAPL",
            transaction_type=TransactionType.BUY,
            trade_date=date(2026, 9, 16),
            price=100,
            currency="USD",
        )
