"""The lot book, realised gains split into price and currency, and the wash sale rule."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.accounting.lots import LotBook, RealisedLot, Term, allocate_pro_rata, wash_adjusted
from meridian.accounting.wash_sales import Acquisition, WashSaleTracker
from meridian.core import ValidationError
from meridian.core.enums import LotSelectionMethod
from meridian.domain.positions import TaxLot


def lot(lot_id: str, opened: date, quantity: str, cost: str, *, tx: str | None = None, rate: str = "1") -> TaxLot:
    return TaxLot(
        lot_id=lot_id,
        instrument_id="X",
        open_date=opened,
        quantity=Decimal(quantity),
        cost_per_unit=Decimal(cost),
        currency="USD",
        transaction_id=tx or lot_id,
        open_fx_rate=Decimal(rate),
    )


def realised(**changes) -> RealisedLot:
    fields = {
        "portfolio_id": "P",
        "instrument_id": "X",
        "lot_id": "L1",
        "disposal_id": "S1",
        "open_date": date(2025, 1, 10),
        "holding_start": date(2025, 1, 10),
        "close_date": date(2025, 3, 10),
        "quantity": Decimal(100),
        "currency": "EUR",
        "proceeds": Decimal(1800),
        "cost": Decimal(2000),
        "open_fx_rate": Decimal("1.10"),
        "close_fx_rate": Decimal("1.20"),
    }
    fields.update(changes)
    return RealisedLot(**fields)


# ---------------------------------------------------------------------------- realised lots
def test_a_realised_gain_splits_exactly_into_price_and_currency():
    record = realised()
    assert record.gain == Decimal(-200)
    assert record.proceeds_base == Decimal("2160.00")
    assert record.cost_base == Decimal("2200.00")
    assert record.gain_base == Decimal("-40.00")
    assert record.price_gain_base == Decimal("-240.00")
    assert record.fx_gain_base == Decimal("200.00")
    assert record.price_gain_base + record.fx_gain_base == record.gain_base


def test_holding_period_and_term_follow_the_tax_start_date():
    assert realised().term is Term.SHORT
    assert realised(holding_start=date(2024, 3, 10)).term is Term.SHORT  # exactly one year is not more than one year
    assert realised(holding_start=date(2024, 3, 9)).is_long_term
    assert realised().holding_days == 59
    assert realised().tax_year == 2025


def test_reportable_gain_adds_back_a_disallowed_loss_and_carries_the_code():
    record = realised(close_fx_rate=Decimal("1.10"), disallowed_loss=Decimal(110))
    assert record.tax_gain_before_wash == Decimal("-220.00")
    assert record.reportable_gain == Decimal("-110.00")
    assert record.adjustment_code == "W"
    assert realised().adjustment_code == ""
    carried = realised(close_fx_rate=Decimal("1.10"), wash_sale_basis=Decimal(50))
    assert carried.tax_basis == Decimal("2250.00")


def test_pro_rata_allocation_is_exact():
    parts = allocate_pro_rata(Decimal("100.00"), [Decimal(1), Decimal(1), Decimal(1)])
    assert sum(parts) == Decimal("100.00")
    assert parts[0] == parts[1]
    with pytest.raises(ValidationError, match="zero quantity"):
        allocate_pro_rata(Decimal(1), [Decimal(0)])


# ---------------------------------------------------------------------------- the lot book
def test_relief_keeps_the_identifier_of_a_partly_sold_lot():
    book = LotBook("P")
    book.open(lot("A", date(2025, 1, 2), "100", "10"))
    book.open(lot("B", date(2025, 2, 3), "50", "12"))
    sold = book.relieve("X", Decimal(130), date(2025, 6, 1))
    assert [(item.lot_id, item.quantity) for item in sold] == [("A", Decimal(100)), ("B", Decimal(30))]
    assert [(item.lot_id, item.quantity) for item in book.lots("X")] == [("B", Decimal(20))]
    assert book.quantity("X") == Decimal(20)
    assert book.instruments() == ("X",)


def test_relief_methods_and_specific_identification():
    for method, expected in (
        (LotSelectionMethod.FIFO, "A"),
        (LotSelectionMethod.LIFO, "C"),
        (LotSelectionMethod.HIFO, "B"),
    ):
        book = LotBook("P", method=method)
        book.open(lot("A", date(2025, 1, 2), "10", "10"))
        book.open(lot("B", date(2025, 2, 3), "10", "30"))
        book.open(lot("C", date(2025, 3, 4), "10", "20"))
        assert book.relieve("X", Decimal(10), date(2025, 6, 1))[0].lot_id == expected
    book = LotBook("P")
    book.open(lot("A", date(2025, 1, 2), "10", "10"))
    book.open(lot("B", date(2025, 2, 3), "10", "30"))
    assert book.relieve("X", Decimal(5), date(2025, 6, 1), specific_lot_ids=["B"])[0].lot_id == "B"


def test_the_lot_book_refuses_duplicates_mixed_currencies_and_empty_positions():
    book = LotBook("P")
    book.open(lot("A", date(2025, 1, 2), "10", "10"))
    with pytest.raises(ValidationError, match="already open"):
        book.open(lot("A", date(2025, 1, 3), "1", "1"))
    euro = TaxLot(
        lot_id="E", instrument_id="X", open_date=date(2025, 1, 2), quantity=1, cost_per_unit=1, currency="EUR"
    )
    with pytest.raises(ValidationError, match="held in USD"):
        book.open(euro)
    with pytest.raises(ValidationError, match="no open lots"):
        book.position("Y")


def test_a_wash_sale_adjustment_splits_a_lot_only_partly_used_as_replacement():
    book = LotBook("P")
    book.open(lot("R", date(2025, 3, 20), "300", "17", tx="B3"))
    adjusted = book.adjust_for_wash_sale("X", "B3", Decimal(100), Decimal("0.5"), 63)
    assert adjusted == Decimal(100)
    lots = {item.lot_id: item for item in book.lots("X")}
    assert lots["R"].quantity == 100 and lots["R"].wash_sale_adjustment == Decimal("0.5")
    assert lots["R"].holding_start == date(2025, 1, 16)
    (rest,) = [item for key, item in lots.items() if key != "R"]
    assert rest.quantity == 200 and rest.wash_sale_adjustment == 0
    assert rest.holding_start == date(2025, 3, 20)
    # shares already sold cannot be adjusted: only what is still held is
    assert book.adjust_for_wash_sale("X", "NOPE", Decimal(10), Decimal(1), 5) == 0


def test_tacking_never_moves_the_holding_start_after_the_open_date():
    replacement = wash_adjusted(lot("R", date(2025, 3, 20), "1", "1"), Decimal(1), 0)
    assert replacement.holding_start == date(2025, 3, 20)


# ---------------------------------------------------------------------------- the tracker
def test_the_tracker_matches_replacements_earliest_first_and_only_once():
    tracker = WashSaleTracker(
        [
            Acquisition("B1", "X", date(2025, 2, 20), Decimal(40)),
            Acquisition("B2", "X", date(2025, 3, 15), Decimal(100)),
            Acquisition("OLD", "X", date(2025, 1, 2), Decimal(100)),  # outside the window
        ]
    )
    first = tracker.match(realised(close_fx_rate=Decimal("1.10")))
    assert [(item.replacement_id, item.quantity) for item in first] == [("B1", Decimal(40)), ("B2", Decimal(60))]
    assert first[0].replacement_before_sale and first[1].days_from_sale == 5
    assert sum(item.disallowed for item in first) == Decimal("220.00")
    # a second loss sale finds only the 40 shares of B2 not yet used
    second = tracker.match(realised(lot_id="L2", close_fx_rate=Decimal("1.10")))
    assert [(item.replacement_id, item.quantity) for item in second] == [("B2", Decimal(40))]
    assert tracker.capacity("B2") == 0
    assert tracker.disallowed_total() == Decimal("308.00")


def test_a_gain_is_never_a_wash_sale_and_sold_shares_are_not_replacements():
    tracker = WashSaleTracker([Acquisition("B1", "X", date(2025, 3, 1), Decimal(100))])
    assert tracker.match(realised(proceeds=Decimal(2500))) == []
    tracker.consume_sold("B1", Decimal(100))
    assert tracker.match(realised(close_fx_rate=Decimal("1.10"))) == []
    tracker.consume_sold("UNKNOWN", Decimal(1))  # harmless


def test_the_window_is_thirty_days_either_side_inclusive():
    sale = date(2025, 3, 10)
    tracker = WashSaleTracker(
        [
            Acquisition("EDGE-BEFORE", "X", date(2025, 2, 8), Decimal(1)),
            Acquisition("EDGE-AFTER", "X", date(2025, 4, 9), Decimal(1)),
            Acquisition("TOO-EARLY", "X", date(2025, 2, 7), Decimal(1)),
            Acquisition("TOO-LATE", "X", date(2025, 4, 10), Decimal(1)),
            Acquisition("OTHER", "Y", date(2025, 3, 10), Decimal(1)),
        ]
    )
    assert [item.transaction_id for item in tracker.candidates("X", sale)] == ["EDGE-BEFORE", "EDGE-AFTER"]
