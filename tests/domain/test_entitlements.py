"""Corporate actions applied to tax lots: basis conserved, holding periods tacked, cash booked."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.core.enums import TransactionType
from meridian.core.exceptions import ValidationError
from meridian.domain.corporate_actions import (
    CashMerger,
    RightsIssue,
    SpinOff,
    StockDividend,
    StockMerger,
    SymbolChange,
    dividend,
    split,
)
from meridian.domain.entitlements import apply_action, apply_actions, entitled_lots
from meridian.domain.positions import TaxLot

EX = date(2026, 6, 10)


def lot(lot_id: str, opened: date, quantity: str, cost: str, instrument: str = "X") -> TaxLot:
    return TaxLot(
        lot_id=lot_id,
        instrument_id=instrument,
        open_date=opened,
        quantity=Decimal(quantity),
        cost_per_unit=Decimal(cost),
        currency="USD",
    )


@pytest.fixture
def lots() -> list[TaxLot]:
    return [
        lot("L1", date(2024, 3, 1), "100", "150.00"),  # long term on the ex-date
        lot("L2", date(2026, 1, 15), "33", "210.00"),  # short term
        lot("L3", EX, "10", "60.00"),  # bought on the ex-date: not entitled
        lot("Y1", date(2025, 1, 2), "5", "20.00", instrument="Y"),  # another instrument
    ]


def test_only_lots_opened_before_the_ex_date_take_part(lots: list[TaxLot]):
    entitled, others = entitled_lots(lots, split("S", "X", EX, 2))
    assert [item.lot_id for item in entitled] == ["L1", "L2"]
    assert {item.lot_id for item in others} == {"L3", "Y1"}


def test_a_split_conserves_basis_and_keeps_acquisition_dates(lots: list[TaxLot]):
    result = apply_action(split("S", "X", EX, 4), lots, portfolio_id="P")
    adjusted = {item.lot_id: item for item in result.lots_after}
    assert adjusted["L1"].quantity == Decimal(400)
    assert adjusted["L1"].cost_per_unit == Decimal("37.5")
    assert adjusted["L1"].open_date == date(2024, 3, 1)
    assert adjusted["L3"].quantity == Decimal(10)  # untouched: bought post-split
    assert result.basis_after - adjusted["L3"].cost_basis.amount - adjusted["Y1"].cost_basis.amount == pytest.approx(
        result.basis_before
    )
    (transaction,) = result.transactions
    assert transaction.transaction_type is TransactionType.SPLIT
    assert transaction.quantity == Decimal(399)  # 133 shares became 532


def test_fractional_shares_are_paid_as_cash_in_lieu():
    lots = [lot("A", date(2025, 1, 2), "7", "30.00"), lot("B", date(2026, 2, 2), "4", "36.00")]
    event = StockDividend(action_id="SD", instrument_id="X", ex_date=EX, rate=Decimal("0.10"))
    with pytest.raises(ValidationError, match="fractional"):
        apply_action(event, lots, portfolio_id="P")
    result = apply_action(event, lots, portfolio_id="P", ex_price=Decimal("33.00"))
    assert result.quantity_after() == Decimal(12)  # 12.1 shares, 0.1 paid in cash
    (cash,) = result.cash
    assert cash.kind == "cash_in_lieu"
    assert cash.gross.amount == Decimal("3.30")
    assert result.realised_short_term != 0  # taken from the newest lot, which is short term
    assert any(item.transaction_type is TransactionType.SELL for item in result.transactions)


def test_reverse_split_surrenders_shares():
    result = apply_action(split("R", "X", EX, 1, 10), [lot("A", date(2025, 1, 2), "1000", "2.00")], portfolio_id="P")
    (after,) = result.lots_after
    assert after.quantity == Decimal(100)
    assert after.cost_per_unit == Decimal("20")
    assert "surrendered" in (result.transactions[0].notes or "")


def test_cash_dividend_pays_entitled_shares_net_of_withholding(lots: list[TaxLot]):
    event = dividend("D", "X", EX, "0.50", "USD", pay_date=date(2026, 6, 25), withholding_rate="0.30")
    result = apply_action(event, lots, portfolio_id="P")
    (cash,) = result.cash
    assert cash.gross.amount == Decimal("66.50")  # 133 entitled shares
    assert cash.tax_withheld.amount == Decimal("19.95")
    assert cash.net.amount == Decimal("46.55")
    assert cash.pay_date == date(2026, 6, 25)
    (transaction,) = result.transactions
    assert transaction.transaction_type is TransactionType.DIVIDEND
    assert transaction.cash_impact.amount == Decimal("46.55")
    assert transaction.settles_on == date(2026, 6, 25)
    assert set(result.lots_after) == set(lots)  # income leaves the lots alone


def test_spin_off_splits_basis_to_the_cent_and_the_child_inherits_dates(lots: list[TaxLot]):
    event = SpinOff(
        action_id="SO",
        instrument_id="X",
        ex_date=EX,
        child_instrument_id="KID",
        ratio=Decimal("0.5"),
        cost_allocation=Decimal("0.186"),
    )
    result = apply_action(event, lots[:2], portfolio_id="P")
    parents = [item for item in result.lots_after if item.instrument_id == "X"]
    children = [item for item in result.lots_after if item.instrument_id == "KID"]
    assert [child.open_date for child in children] == [date(2024, 3, 1), date(2026, 1, 15)]
    assert [child.quantity for child in children] == [Decimal(50), Decimal(16)]  # 16.5 rounded down
    assert sum(item.cost_basis.amount for item in parents + children) == pytest.approx(result.basis_before, abs=1e-6)
    child_share = sum(item.cost_basis.amount for item in children) / result.basis_before
    assert child_share == pytest.approx(Decimal("0.186"), abs=Decimal("1e-9"))
    assert result.transactions[0].transaction_type is TransactionType.SPIN_OFF


def test_rights_can_be_left_or_taken_up():
    held = [lot("A", date(2025, 1, 2), "100", "50.00")]
    event = RightsIssue(
        action_id="RI",
        instrument_id="X",
        ex_date=EX,
        pay_date=date(2026, 6, 24),
        ratio=Decimal("0.2"),
        subscription_price=Decimal("40"),
    )
    lapsed = apply_action(event, held, portfolio_id="P")
    assert lapsed.lots_after == tuple(held)
    taken = apply_action(event, held, portfolio_id="P", take_up_rights=True)
    new = [item for item in taken.lots_after if item.lot_id.startswith("RI")]
    assert new[0].quantity == Decimal(20)
    assert new[0].open_date == date(2026, 6, 24)  # new money starts a new holding period
    assert taken.transactions[0].transaction_type is TransactionType.BUY


def test_cash_merger_closes_every_lot_and_splits_gains_by_term(lots: list[TaxLot]):
    event = CashMerger(action_id="CM", instrument_id="X", ex_date=EX, cash_per_share=Decimal("200"), currency="USD")
    result = apply_action(event, lots[:2], portfolio_id="P")
    assert result.lots_after == ()
    assert result.realised_long_term == Decimal("5000.00")  # 100 x (200 - 150)
    assert result.realised_short_term == Decimal("-330.00")  # 33 x (200 - 210)
    assert result.cash_total == Decimal("26600.00")


def test_stock_merger_taxes_boot_only_up_to_the_gain():
    held = [lot("A", date(2024, 1, 2), "100", "30.00")]
    event = StockMerger(
        action_id="SM",
        instrument_id="X",
        ex_date=EX,
        acquirer_instrument_id="ACQ",
        ratio=Decimal("0.5"),
        cash_per_share=Decimal("10"),
    )
    with pytest.raises(ValidationError, match="acquirer"):
        apply_action(event, held, portfolio_id="P")
    result = apply_action(event, held, portfolio_id="P", acquirer_price=Decimal("80"))
    # realised = 1000 cash + 50 x 80 - 3000 basis = 2000; recognised = min(1000, 2000) = 1000
    assert result.realised_long_term == Decimal(1000)
    (new,) = result.lots_after
    assert new.instrument_id == "ACQ"
    assert new.quantity == Decimal(50)
    assert new.cost_basis.amount == pytest.approx(Decimal(3000))  # 3000 - 1000 cash + 1000 recognised
    assert new.open_date == date(2024, 1, 2)


def test_stock_merger_at_a_loss_recognises_nothing():
    held = [lot("A", date(2024, 1, 2), "100", "90.00")]
    event = StockMerger(
        action_id="SM",
        instrument_id="X",
        ex_date=EX,
        acquirer_instrument_id="ACQ",
        ratio=Decimal("0.5"),
        cash_per_share=Decimal("10"),
    )
    result = apply_action(event, held, portfolio_id="P", acquirer_price=Decimal("80"))
    assert result.realised == 0
    assert result.lots_after[0].cost_basis.amount == pytest.approx(Decimal(8000))  # 9000 - 1000 cash


def test_symbol_change_moves_nothing(lots: list[TaxLot]):
    event = SymbolChange(action_id="N", instrument_id="X", ex_date=EX, old_symbol="OLD", new_symbol="NEW")
    result = apply_action(event, lots, portfolio_id="P")
    assert set(result.lots_after) == set(lots)
    assert "NEW" in result.notes[0]


def test_no_entitled_lots_is_not_an_error():
    result = apply_action(split("S", "X", EX, 2), [lot("A", date(2026, 7, 1), "5", "1")], portfolio_id="P")
    assert result.notes == ("no lots held before the ex-date",)


def test_actions_thread_through_in_ex_date_order():
    held = [lot("A", date(2024, 1, 2), "10", "400.00")]
    events = [
        dividend("D", "X", date(2026, 9, 1), "0.25", "USD"),
        split("S", "X", date(2026, 6, 1), 4),
    ]
    final, results = apply_actions(events, held, portfolio_id="P")
    assert [item.action.action_id for item in results] == ["S", "D"]
    assert final[0].quantity == Decimal(40)
    assert results[1].cash[0].gross.amount == Decimal("10.00")  # paid on the post-split share count
