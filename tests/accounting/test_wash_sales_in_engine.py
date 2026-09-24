"""The wash sale rule applied by the engine: IRS Publication 550's cases, end to end."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from meridian.accounting.builders import cash_transaction, purchase, sale
from meridian.accounting.lots import RealisationKind
from meridian.accounting.sources import FixedFx
from meridian.core.enums import TransactionType

D = date


def deposit(day: date, amount: str, currency: str = "USD"):
    return cash_transaction(
        transaction_id=f"DEP-{day}-{currency}",
        portfolio_id="P",
        kind=TransactionType.DEPOSIT,
        day=day,
        amount=amount,
        currency=currency,
    )


def buy(transaction_id, day, quantity, price, instrument="US-AAPL", currency="USD"):
    return purchase(
        transaction_id=transaction_id,
        portfolio_id="P",
        instrument_id=instrument,
        day=day,
        quantity=quantity,
        price=price,
        currency=currency,
    )


def sell(transaction_id, day, quantity, price, instrument="US-AAPL", currency="USD"):
    return sale(
        transaction_id=transaction_id,
        portfolio_id="P",
        instrument_id=instrument,
        day=day,
        quantity=quantity,
        price=price,
        currency=currency,
    )


def test_publication_550_example_the_loss_moves_into_the_replacement_basis(make_engine, fx):
    """Buy 100 for 1,000, sell for 750, buy 100 again within 30 days for 800: basis becomes 1,050."""
    engine = make_engine(fx)
    book = engine.run(
        [
            deposit(D(2025, 1, 2), "10000"),
            buy("B1", D(2025, 1, 6), 100, "10"),
            sell("S1", D(2025, 3, 10), 100, "7.5"),
            buy("B2", D(2025, 3, 25), 100, "8"),
        ]
    )
    (record,) = book.realised
    assert record.tax_gain_before_wash == Decimal(-250)
    assert record.disallowed_loss == Decimal(250)
    assert record.reportable_gain == 0
    (replacement,) = book.open_lots["US-AAPL"]
    assert replacement.tax_basis == Decimal(1050)
    assert replacement.cost_basis.amount == Decimal(800)  # the book cost is untouched
    assert replacement.holding_start == D(2025, 3, 25) - (D(2025, 3, 10) - D(2025, 1, 6))
    (match,) = book.wash_sales
    assert match.replacement_id == "B2" and not match.replacement_before_sale


def test_only_the_replaced_fraction_of_a_loss_is_disallowed(make_engine, fx):
    book = make_engine(fx).run(
        [
            deposit(D(2025, 1, 2), "10000"),
            buy("B1", D(2025, 1, 6), 100, "10"),
            sell("S1", D(2025, 3, 10), 100, "7"),
            buy("B2", D(2025, 3, 11), 25, "7"),
        ]
    )
    assert book.realised[0].disallowed_loss == Decimal(75)
    assert book.realised[0].reportable_gain == Decimal(-225)


def test_remaining_shares_of_a_recent_purchase_are_replacements(make_engine, fx):
    """Buy 200, sell 100 of them at a loss three weeks later: the other 100 replace them."""
    book = make_engine(fx).run(
        [
            deposit(D(2025, 1, 2), "10000"),
            buy("B1", D(2025, 2, 17), 200, "10"),
            sell("S1", D(2025, 3, 10), 100, "9"),
        ]
    )
    assert book.realised[0].disallowed_loss == Decimal(100)
    (remaining,) = book.open_lots["US-AAPL"]
    assert remaining.quantity == 100 and remaining.wash_sale_adjustment == Decimal(1)


def test_a_purchase_outside_the_window_or_in_a_non_taxable_account_is_not_a_wash(make_engine, fx):
    transactions = [
        deposit(D(2025, 1, 2), "10000"),
        buy("B1", D(2025, 1, 6), 100, "10"),
        sell("S1", D(2025, 3, 10), 100, "7"),
        buy("B2", D(2025, 4, 10), 100, "7"),
    ]
    assert make_engine(fx).run(transactions).realised[0].disallowed_loss == 0
    inside = [*transactions[:3], buy("B2", D(2025, 4, 9), 100, "7")]
    assert make_engine(fx).run(inside).realised[0].disallowed_loss == Decimal(300)
    assert make_engine(fx, wash_sales=False).run(inside).realised[0].disallowed_loss == 0


def test_a_replacement_bought_before_the_sale_is_adjusted_in_place(make_engine, fx):
    book = make_engine(fx).run(
        [
            deposit(D(2025, 1, 2), "10000"),
            buy("B1", D(2025, 1, 6), 100, "10"),
            buy("B2", D(2025, 3, 3), 100, "8"),
            sell("S1", D(2025, 3, 10), 100, "7"),
        ]
    )
    (open_lot,) = book.open_lots["US-AAPL"]
    assert open_lot.lot_id == "B2"
    assert open_lot.tax_basis == Decimal(800) + Decimal(300)
    assert book.realised[0].lot_id == "B1"


def test_a_loss_realised_in_euros_is_measured_in_the_tax_currency(make_engine):
    # the euro strengthens: a loss in euros is a gain in dollars, so there is nothing to disallow
    fx = FixedFx({"EUR": "1.00", ("EUR", D(2025, 3, 1)): "1.25"})
    book = make_engine(fx).run(
        [
            deposit(D(2025, 1, 2), "10000", "EUR"),
            buy("B1", D(2025, 1, 6), 100, "20", "DE-BAYN", "EUR"),
            sell("S1", D(2025, 3, 10), 100, "18", "DE-BAYN", "EUR"),
            buy("B2", D(2025, 3, 20), 100, "18", "DE-BAYN", "EUR"),
        ]
    )
    (record,) = book.realised
    assert record.gain == Decimal(-200)
    assert record.gain_base == Decimal(250)
    assert record.disallowed_loss == 0
    assert record.kind is RealisationKind.SALE


def test_a_replacement_matched_to_two_sold_lots_is_split_and_tacked_once_each(make_engine):
    """One sale closes two lots of different ages; each half of the replacement carries its own sold lot's period."""
    fx = FixedFx({})
    book = make_engine(fx).run(
        [
            deposit(D(2024, 1, 2), "100000"),
            buy("OLD", D(2024, 1, 3), 100, "10"),
            buy("NEW", D(2025, 1, 6), 100, "10"),
            sell("S1", D(2025, 3, 10), 200, "7"),
            buy("REP", D(2025, 3, 20), 200, "7"),
        ]
    )
    lots = sorted(book.open_lots["US-AAPL"], key=lambda lot: lot.holding_start)
    assert [lot.quantity for lot in lots] == [100, 100]
    old_held = (D(2025, 3, 10) - D(2024, 1, 3)).days
    new_held = (D(2025, 3, 10) - D(2025, 1, 6)).days
    assert lots[0].holding_start == D(2025, 3, 20) - timedelta(days=old_held)
    assert lots[1].holding_start == D(2025, 3, 20) - timedelta(days=new_held)
    assert all(lot.wash_sale_adjustment == Decimal(3) for lot in lots)
    assert all(lot.holding_start >= D(2024, 1, 3) for lot in lots)
