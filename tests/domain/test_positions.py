from datetime import date
from decimal import Decimal

import pytest

from meridian.core import LotSelectionMethod, Money, ValidationError
from meridian.domain import Position, PositionSnapshot, TaxLot


def lot(lot_id: str, quantity, cost, open_date: date) -> TaxLot:
    return TaxLot(
        lot_id=lot_id,
        instrument_id="AAPL",
        open_date=open_date,
        quantity=Decimal(str(quantity)),
        cost_per_unit=Decimal(str(cost)),
        currency="USD",
    )


@pytest.fixture
def position() -> Position:
    return Position(
        portfolio_id="P1",
        instrument_id="AAPL",
        currency="USD",
        lots=(
            lot("L1", 100, "120.00", date(2024, 3, 1)),  # long-term, cheap
            lot("L2", 50, "210.00", date(2026, 6, 1)),  # short-term, expensive
            lot("L3", 75, "165.00", date(2025, 1, 15)),  # long-term, middle
        ),
    )


def test_position_aggregates_its_lots(position: Position):
    assert position.quantity == Decimal(225)
    assert position.cost_basis == Money(Decimal("100") * 120 + Decimal("50") * 210 + Decimal("75") * 165, "USD")
    assert position.average_cost == pytest.approx(position.cost_basis.amount / Decimal(225))
    assert position.is_open


def test_market_value_and_unrealised_gain(position: Position):
    assert position.market_value("200.00") == Money(Decimal(225) * 200, "USD")
    assert position.unrealised_gain("200.00") == position.market_value("200.00") - position.cost_basis


def test_unrealised_gain_splits_by_holding_period(position: Position):
    as_of = date(2026, 9, 18)
    long_term, short_term = position.unrealised_split_by_term("200.00", as_of)
    # L1 and L3 are held over a year; L2 was bought in June 2026
    assert long_term == Money(Decimal(100) * (200 - 120) + Decimal(75) * (200 - 165), "USD")
    assert short_term == Money(Decimal(50) * (200 - 210), "USD")
    assert (long_term + short_term) == position.unrealised_gain("200.00")


def test_lot_holding_period_helpers():
    old = lot("L1", 10, 100, date(2025, 1, 1))
    assert old.is_long_term(date(2026, 1, 2))
    assert not old.is_long_term(date(2025, 12, 31))
    assert old.long_term_from() == date(2026, 1, 2)
    assert old.holding_days(date(2025, 1, 31)) == 30


def test_fifo_sells_the_oldest_lots(position: Position):
    sold, remaining = position.select_lots(120, LotSelectionMethod.FIFO)
    assert [item.lot_id for item in sold] == ["L1", "L3"]
    assert sold[1].quantity == Decimal(20)
    assert sum(item.quantity for item in sold) == Decimal(120)
    assert sum(item.quantity for item in remaining) == Decimal(105)


def test_lifo_sells_the_newest_lots(position: Position):
    sold, _ = position.select_lots(60, LotSelectionMethod.LIFO)
    assert [item.lot_id for item in sold] == ["L2", "L3"]


def test_hifo_realises_the_smallest_gain(position: Position):
    sold_hifo, _ = position.select_lots(50, LotSelectionMethod.HIFO)
    sold_fifo, _ = position.select_lots(50, LotSelectionMethod.FIFO)
    price = Decimal("200")
    gain_hifo = sum((item.unrealised_gain(price).amount for item in sold_hifo), Decimal(0))
    gain_fifo = sum((item.unrealised_gain(price).amount for item in sold_fifo), Decimal(0))
    assert [item.lot_id for item in sold_hifo] == ["L2"]
    assert gain_hifo < gain_fifo  # this is the entire point of HIFO


def test_specific_lot_identification(position: Position):
    sold, remaining = position.select_lots(75, LotSelectionMethod.SPECIFIC_LOT, specific_lot_ids=["L3"])
    assert [item.lot_id for item in sold] == ["L3"]
    assert {item.lot_id for item in remaining} == {"L1", "L2"}
    with pytest.raises(ValidationError):
        position.select_lots(10, LotSelectionMethod.SPECIFIC_LOT)
    with pytest.raises(ValidationError):
        position.select_lots(10, LotSelectionMethod.SPECIFIC_LOT, specific_lot_ids=["NOPE"])


def test_selling_more_than_held_is_rejected(position: Position):
    with pytest.raises(ValidationError):
        position.select_lots(1000)
    with pytest.raises(ValidationError):
        position.select_lots(0)


def test_selected_lots_preserve_total_quantity_and_cost(position: Position):
    sold, remaining = position.select_lots(140, LotSelectionMethod.HIFO)
    total_quantity = sum(item.quantity for item in sold) + sum(item.quantity for item in remaining)
    total_cost = sum(item.cost_basis.amount for item in sold) + sum(item.cost_basis.amount for item in remaining)
    assert total_quantity == position.quantity
    assert total_cost == position.cost_basis.amount


def test_lot_split_conserves_quantity():
    original = lot("L1", 100, "120.00", date(2024, 3, 1))
    taken, rest = original.split(40)
    assert taken.quantity == Decimal(40)
    assert rest is not None and rest.quantity == Decimal(60)
    assert taken.cost_per_unit == rest.cost_per_unit == Decimal("120.00")
    whole, nothing = original.split(100)
    assert whole is original and nothing is None
    with pytest.raises(ValidationError):
        original.split(101)
    with pytest.raises(ValidationError):
        original.split(0)


def test_lots_must_match_the_position():
    with pytest.raises(ValidationError):
        Position(
            portfolio_id="P1",
            instrument_id="MSFT",
            currency="USD",
            lots=(lot("L1", 10, 100, date(2025, 1, 1)),),
        )
    with pytest.raises(ValidationError):
        Position(
            portfolio_id="P1",
            instrument_id="AAPL",
            currency="EUR",
            lots=(lot("L1", 10, 100, date(2025, 1, 1)),),
        )


def test_lot_validation():
    with pytest.raises(ValidationError):
        lot("L1", 0, 100, date(2025, 1, 1))
    with pytest.raises(ValidationError):
        lot("L1", 10, -1, date(2025, 1, 1))


def test_snapshot_indexes_and_totals(position: Position):
    snapshot = PositionSnapshot(
        portfolio_id="P1",
        as_of=date(2026, 9, 18),
        positions=(position,),
        cash=Money("12500.00", "USD"),
    )
    assert snapshot.by_instrument()["AAPL"] is position
    assert snapshot.cost_basis("USD") == position.cost_basis
    with pytest.raises(ValidationError):
        snapshot.cost_basis("EUR")
