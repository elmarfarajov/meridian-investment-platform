"""Daily valuation and the value bridge, including an exactness property over random books."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from meridian.accounting.bridge import value_bridge
from meridian.accounting.builders import cash_transaction, fx_conversion, purchase, sale, transfer_in
from meridian.accounting.sources import FixedFx, FixedPrices
from meridian.accounting.valuation import Valuator
from meridian.core import ValidationError
from meridian.core.calendars import get_calendar
from meridian.core.enums import TransactionType
from meridian.domain.corporate_actions import dividend, split

D = date
XNYS = get_calendar("XNYS")


def deposit(day, amount, currency="USD", tid=None):
    return cash_transaction(
        transaction_id=tid or f"DEP-{day}-{currency}",
        portfolio_id="P",
        kind=TransactionType.DEPOSIT,
        day=day,
        amount=amount,
        currency=currency,
    )


def buy(tid, day, quantity, price, instrument="US-AAPL", currency="USD", fees="0"):
    return purchase(
        transaction_id=tid,
        portfolio_id="P",
        instrument_id=instrument,
        day=day,
        quantity=quantity,
        price=price,
        currency=currency,
        fees=fees,
    )


def sell(tid, day, quantity, price, instrument="US-AAPL", currency="USD", fees="0"):
    return sale(
        transaction_id=tid,
        portfolio_id="P",
        instrument_id=instrument,
        day=day,
        quantity=quantity,
        price=price,
        currency=currency,
        fees=fees,
    )


def days_between(start: date, end: date) -> list[date]:
    return list(XNYS.business_days(start, end))


# ---------------------------------------------------------------------------- valuation
@pytest.fixture
def euro_book(make_engine):
    fx = FixedFx({"EUR": "1.10", ("EUR", D(2026, 4, 1)): "1.20"})
    prices = FixedPrices(
        {
            "DE-BAYN": {D(2026, 3, 2): "25", D(2026, 4, 15): "24"},
            "US-AAPL": {D(2026, 3, 2): "200", D(2026, 4, 15): "230"},
        },
        max_age_days=60,
    )
    engine = make_engine(fx, prices=prices)
    book = engine.run(
        [
            deposit(D(2026, 3, 2), "30000", "EUR"),
            deposit(D(2026, 3, 2), "30000"),
            buy("B1", D(2026, 3, 2), 1000, "25", "DE-BAYN", "EUR", fees="10"),
            buy("B2", D(2026, 3, 2), 100, "200"),
        ],
        until=D(2026, 4, 30),
    )
    return book, Valuator(book, engine.instruments, prices, fx, max_price_age_days=60)


def test_nav_is_securities_plus_accrued_plus_everything_cash_like(euro_book):
    _, valuator = euro_book
    valuation = valuator.value(D(2026, 4, 15))
    assert valuation.securities == Decimal(1000) * 24 * Decimal("1.20") + Decimal(100) * 230
    assert valuation.cash_like == Decimal(4990) * Decimal("1.20") + Decimal(10000)
    assert valuation.nav == valuation.securities + valuation.accrued_interest + valuation.cash_like
    assert valuation.settled_cash == valuation.cash_like
    assert valuation.receivables == 0 and valuation.payables == 0
    weights = valuation.weights()
    assert sum(weights.values()) == pytest.approx(Decimal(1))
    exposure = valuation.currency_exposure()
    assert exposure["EUR"] == Decimal(1000) * 24 * Decimal("1.20") + Decimal(4990) * Decimal("1.20")


def test_unrealised_gain_splits_into_price_at_todays_rate_and_currency_on_cost(euro_book):
    _, valuator = euro_book
    bayer = valuator.value(D(2026, 4, 15)).position("DE-BAYN")
    assert bayer.cost == Decimal("25010")
    assert bayer.unrealised_price_base == (Decimal(24000) - Decimal(25010)) * Decimal("1.20")
    assert bayer.unrealised_fx_base == Decimal(25010) * (Decimal("1.20") - Decimal("1.10"))
    assert bayer.unrealised_price_base + bayer.unrealised_fx_base == bayer.unrealised_base
    assert bayer.unrealised_short_term == bayer.unrealised_base  # held six weeks
    assert bayer.unrealised_local == Decimal(-1010)


def test_payables_of_unsettled_trades_are_part_of_nav(euro_book):
    _, valuator = euro_book
    on_trade_date = valuator.value(D(2026, 3, 2))
    assert on_trade_date.payables == -(Decimal(25010) * Decimal("1.10") + Decimal(20000))
    assert on_trade_date.nav == on_trade_date.securities + on_trade_date.cash_like


def test_a_stale_or_missing_price_is_listed_rather_than_valued(make_engine, fx):
    prices = FixedPrices({"US-AAPL": {D(2026, 3, 2): "200"}}, max_age_days=365)
    engine = make_engine(fx, prices=prices)
    book = engine.run([deposit(D(2026, 3, 2), "30000"), buy("B1", D(2026, 3, 2), 10, "200")])
    valuator = Valuator(book, engine.instruments, prices, fx, max_price_age_days=4)
    assert valuator.value(D(2026, 3, 5)).missing == ()
    assert valuator.value(D(2026, 3, 20)).missing == ("US-AAPL",)
    position = valuator.value(D(2026, 3, 5)).position("US-AAPL")
    assert position.is_stale(D(2026, 3, 9), max_days=4)
    with pytest.raises(ValidationError, match="unpriced"):
        value_bridge(valuator, [D(2026, 3, 5), D(2026, 3, 20)])


# ---------------------------------------------------------------------------- the bridge
def test_a_currency_move_alone_is_all_currency(euro_book):
    _, valuator = euro_book
    total, _ = value_bridge(valuator, [D(2026, 3, 31), D(2026, 4, 1)])
    assert total.price == 0 and total.income == 0 and total.flows == 0
    eur_held = Decimal(1000) * 25 + Decimal(4990)
    assert total.fx == eur_held * Decimal("0.10")
    assert total.residual == 0
    assert total.fx_detail["EUR"] == total.fx


def test_deposits_are_flows_and_trades_at_the_close_move_nothing(make_engine, fx):
    prices = FixedPrices({"US-AAPL": {D(2026, 3, 2): "200"}})
    engine = make_engine(fx, prices=prices)
    book = engine.run([deposit(D(2026, 3, 3), "50000"), buy("B1", D(2026, 3, 3), 100, "200", fees="9")])
    valuator = Valuator(book, engine.instruments, prices, fx)
    total, _ = value_bridge(valuator, [D(2026, 3, 2), D(2026, 3, 3), D(2026, 3, 4)])
    assert total.flows == Decimal(50000)
    assert total.price == 0
    assert total.costs == Decimal(-9)
    assert total.closing == Decimal(50000 - 9)
    assert total.residual == 0
    assert total.investment_result == Decimal(-9)


def test_a_split_is_not_a_price_move_and_a_dividend_is_income_not_loss(make_engine, fx):
    prices = FixedPrices(
        {
            "DEMO-SPLIT": {D(2025, 6, 6): "400", D(2025, 6, 9): "400", D(2025, 6, 10): "100", D(2025, 6, 11): "100"},
            "US-JNJ": {D(2025, 6, 6): "150", D(2025, 6, 9): "150", D(2025, 6, 10): "148.76", D(2025, 6, 11): "148.76"},
        }
    )
    engine = make_engine(fx, prices=prices)
    actions = [
        split("S", "DEMO-SPLIT", D(2025, 6, 10), 4),
        dividend("DV", "US-JNJ", D(2025, 6, 10), "1.24", "USD", pay_date=D(2025, 6, 24)),
    ]
    book = engine.run(
        [
            deposit(D(2025, 6, 6), "100000"),
            buy("B1", D(2025, 6, 6), 100, "400", "DEMO-SPLIT"),
            buy("B2", D(2025, 6, 6), 100, "150", "US-JNJ"),
        ],
        actions,
        until=D(2025, 6, 30),
    )
    valuator = Valuator(book, engine.instruments, prices, fx)
    total, steps = value_bridge(valuator, [D(2025, 6, 9), D(2025, 6, 10)])
    effects = total.by_instrument
    assert effects["DEMO-SPLIT"].price == 0
    assert effects["US-JNJ"].price == Decimal(-124)
    assert total.income == Decimal(124)
    assert total.closing == total.opening
    assert total.residual == 0
    assert steps[0].days == 1


def test_a_transfer_in_kind_is_a_flow_at_market_value(make_engine, fx):
    prices = FixedPrices({"US-AAPL": {D(2026, 3, 2): "180"}})
    engine = make_engine(fx, prices=prices)
    book = engine.run(
        [
            transfer_in(
                transaction_id="TI",
                portfolio_id="P",
                instrument_id="US-AAPL",
                day=D(2026, 3, 3),
                quantity=100,
                cost_per_unit="120",
                currency="USD",
                acquired=D(2020, 1, 2),
            )
        ]
    )
    total, _ = value_bridge(Valuator(book, engine.instruments, prices, fx), [D(2026, 3, 2), D(2026, 3, 3)])
    assert total.flows == Decimal(18000)
    assert total.price == 0 and total.residual == 0


def test_bridges_join_only_end_to_start(euro_book):
    _, valuator = euro_book
    first, _ = value_bridge(valuator, [D(2026, 3, 2), D(2026, 3, 3)])
    later, _ = value_bridge(valuator, [D(2026, 3, 4), D(2026, 3, 5)])
    with pytest.raises(ValidationError, match="do not join"):
        _ = first + later
    with pytest.raises(ValidationError, match="two valuation dates"):
        value_bridge(valuator, [D(2026, 3, 2)])
    labels = [label for label, _ in first.components()]
    assert labels[0] == "Opening NAV" and labels[-1] == "Closing NAV"


# ---------------------------------------------------------------------------- exactness, by property
INSTRUMENTS = (("US-AAPL", "USD", 200.0), ("DE-BAYN", "EUR", 25.0), ("GB-BAE", "GBP", 12.9), ("US-T-2032", "USD", 96.0))


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(seed=st.integers(min_value=0, max_value=10_000), trades=st.integers(min_value=3, max_value=25))
def test_the_bridge_explains_every_cent_on_every_day_of_a_random_book(make_engine, seed, trades):
    rng = random.Random(seed)
    days = days_between(D(2026, 1, 5), D(2026, 4, 30))
    prices: dict[str, dict[date, str]] = {}
    for instrument, _, start in INSTRUMENTS:
        level, path = start, {}
        for day in days:
            level *= 1 + rng.gauss(0, 0.015)
            path[day] = f"{level:.2f}"
        prices[instrument] = path
    fx_path: dict[object, str] = {"EUR": "1.08", "GBP": "1.26"}
    for day in days[::5]:
        fx_path[("EUR", day)] = f"{1.08 * (1 + rng.gauss(0, 0.01)):.5f}"
        fx_path[("GBP", day)] = f"{1.26 * (1 + rng.gauss(0, 0.01)):.5f}"
    fx = FixedFx(fx_path)
    price_source = FixedPrices(prices)
    transactions = [
        deposit(days[0], "2000000"),
        fx_conversion(
            transaction_id="FX-EUR",
            portfolio_id="P",
            trade_date=days[0],
            sell_currency="USD",
            sell_amount="300000",
            buy_currency="EUR",
            rate="0.92",
        ),
        fx_conversion(
            transaction_id="FX-GBP",
            portfolio_id="P",
            trade_date=days[0],
            sell_currency="USD",
            sell_amount="200000",
            buy_currency="GBP",
            rate="0.79",
        ),
    ]
    held: dict[str, int] = {}
    for index in range(trades):
        day = days[rng.randrange(3, len(days) - 5)]
        instrument, currency, _ = INSTRUMENTS[rng.randrange(len(INSTRUMENTS))]
        price = Decimal(prices[instrument][day]) * Decimal(str(round(1 + rng.gauss(0, 0.004), 4)))
        quantity = rng.randrange(1, 40)
        transactions.append(buy(f"B{index}", day, quantity, f"{price:.2f}", instrument, currency, fees="3.5"))
        held[instrument] = held.get(instrument, 0) + quantity
        if rng.random() < 0.4:
            later = days[min(days.index(day) + rng.randrange(1, 20), len(days) - 2)]
            transactions.append(
                sell(f"S{index}", later, quantity, prices[instrument][later], instrument, currency, fees="2")
            )
    actions = [dividend("DV", "US-AAPL", days[40], "0.26", "USD", pay_date=days[50])]
    engine = make_engine(fx, prices=price_source)
    try:
        book = engine.run(transactions, actions, until=days[-1])
    except ValidationError as error:  # a random sale can precede its own purchase
        assert "cannot dispose" in str(error)
        return
    valuator = Valuator(book, engine.instruments, price_source, fx)
    total, steps = value_bridge(valuator, days)
    assert all(abs(step.residual) < Decimal("1e-8") for step in steps)
    assert abs(total.residual) < Decimal("1e-8")
    assert book.ledger.trial_balance().is_balanced
