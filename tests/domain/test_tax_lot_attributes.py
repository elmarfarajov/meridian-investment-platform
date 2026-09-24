"""Tax attributes of a lot: tacked holding periods, historical FX cost and wash sale basis."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.core import ValidationError
from meridian.domain.corporate_actions import SpinOff, StockMerger, split
from meridian.domain.entitlements import apply_action
from meridian.domain.positions import TaxLot

EX = date(2026, 6, 10)


def make_lot(**changes) -> TaxLot:
    fields = {
        "lot_id": "L1",
        "instrument_id": "X",
        "open_date": date(2026, 1, 15),
        "quantity": Decimal(100),
        "cost_per_unit": Decimal("50"),
        "currency": "EUR",
        "open_fx_rate": Decimal("1.10"),
    }
    fields.update(changes)
    return TaxLot(**fields)


def test_holding_period_defaults_to_the_open_date():
    lot = make_lot()
    assert lot.holding_start == date(2026, 1, 15)
    assert lot.holding_days(date(2026, 2, 14)) == 30


def test_a_tacked_holding_period_can_make_a_new_lot_long_term():
    lot = make_lot(holding_period_start=date(2024, 11, 1))
    assert lot.is_long_term(date(2026, 1, 20))
    assert lot.long_term_from() == date(2025, 11, 2)
    assert not make_lot().is_long_term(date(2026, 1, 20))


def test_base_cost_uses_the_historical_rate_and_tax_basis_adds_the_wash_sale():
    lot = make_lot(wash_sale_adjustment=Decimal("2.5"))
    assert lot.base_cost_per_unit == Decimal("55.00")
    assert lot.base_cost == Decimal("5500.00")
    assert lot.tax_basis == Decimal("5750.00")
    # the economic cost in the lot's own currency is untouched
    assert lot.cost_basis.amount == Decimal(5000)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"open_fx_rate": Decimal(0)}, "FX rate"),
        ({"wash_sale_adjustment": Decimal(-1)}, "only add"),
        ({"holding_period_start": date(2026, 2, 1)}, "cannot start after"),
    ],
)
def test_invalid_tax_attributes_are_refused(changes, message):
    with pytest.raises(ValidationError, match=message):
        make_lot(**changes)


def test_splitting_a_lot_keeps_every_per_unit_attribute():
    lot = make_lot(holding_period_start=date(2025, 3, 1), wash_sale_adjustment=Decimal("1.2"))
    sold, rest = lot.split(40)
    assert rest is not None
    for part in (sold, rest):
        assert part.holding_start == date(2025, 3, 1)
        assert part.open_fx_rate == Decimal("1.10")
        assert part.wash_sale_adjustment == Decimal("1.2")
    assert sold.tax_basis + rest.tax_basis == lot.tax_basis


def test_rescaling_divides_the_per_unit_adjustment_so_the_total_is_kept():
    lot = make_lot(wash_sale_adjustment=Decimal("3"))
    scaled = lot.rescaled(4, Decimal("12.5"))
    assert scaled.quantity == Decimal(400)
    assert scaled.wash_sale_adjustment == Decimal("0.75")
    assert scaled.tax_basis == lot.tax_basis


def test_a_split_carries_the_wash_sale_adjustment_and_the_tacked_period():
    lot = make_lot(holding_period_start=date(2025, 3, 1), wash_sale_adjustment=Decimal("2"))
    result = apply_action(split("S", "X", EX, 2), [lot], portfolio_id="P")
    (after,) = result.lots_after
    assert after.quantity == Decimal(200)
    assert after.wash_sale_adjustment == Decimal(1)
    assert after.holding_start == date(2025, 3, 1)
    assert after.open_fx_rate == Decimal("1.10")
    assert after.tax_basis == lot.tax_basis


def test_a_spin_off_divides_the_wash_sale_adjustment_with_the_basis():
    lot = make_lot(wash_sale_adjustment=Decimal("2"), currency="USD", open_fx_rate=Decimal(1))
    action = SpinOff(
        action_id="SO",
        instrument_id="X",
        ex_date=EX,
        child_instrument_id="Y",
        ratio=Decimal("0.5"),
        cost_allocation=Decimal("0.2"),
    )
    result = apply_action(action, [lot], portfolio_id="P")
    by_instrument = {item.instrument_id: item for item in result.lots_after}
    parent, child = by_instrument["X"], by_instrument["Y"]
    assert parent.wash_sale_adjustment * parent.quantity == Decimal("160")
    assert child.wash_sale_adjustment * child.quantity == Decimal("40")
    assert child.holding_start == lot.holding_start
    assert parent.tax_basis + child.tax_basis == pytest.approx(lot.tax_basis, abs=Decimal("1e-8"))


def test_a_stock_merger_moves_the_adjustment_into_the_acquirer_lots():
    lot = make_lot(wash_sale_adjustment=Decimal("1.5"), currency="USD", open_fx_rate=Decimal(1))
    action = StockMerger(
        action_id="M", instrument_id="X", ex_date=EX, acquirer_instrument_id="Z", ratio=Decimal("0.5"), currency="USD"
    )
    (after,) = apply_action(action, [lot], portfolio_id="P").lots_after
    assert after.instrument_id == "Z"
    assert after.wash_sale_adjustment * after.quantity == Decimal("150")
