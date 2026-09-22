"""Corporate action terms, and the price factors that make history comparable across them."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.core.exceptions import ValidationError
from meridian.domain.corporate_actions import (
    AdjustmentMode,
    CashDividend,
    CashMerger,
    CorporateActionType,
    RightsIssue,
    SpinOff,
    StockDividend,
    StockMerger,
    StockSplit,
    SymbolChange,
    dividend,
    split,
)

EX = date(2026, 6, 10)


def test_a_forward_split_quarters_the_price_and_quadruples_the_shares():
    event = split("S1", "X", EX, 4)
    assert event.price_factor() == Decimal("0.25")
    assert event.quantity_factor == Decimal(4)
    assert not event.is_reverse
    assert "4-for-1 split" in event.describe()


def test_a_reverse_split_works_the_other_way():
    event = split("S2", "X", EX, 1, 10)
    assert event.is_reverse
    assert event.price_factor() == Decimal(10)
    assert event.quantity_factor == Decimal("0.1")
    assert "reverse split" in event.describe()


def test_a_split_that_changes_nothing_is_refused():
    with pytest.raises(ValidationError):
        split("S3", "X", EX, 2, 2)
    with pytest.raises(ValidationError):
        split("S4", "X", EX, 0, 1)


def test_a_cash_dividend_factor_is_price_less_dividend_over_price():
    event = dividend("D1", "X", EX, "2.00", "usd")
    assert event.currency == "USD"
    assert event.price_factor(Decimal("100")) == Decimal("0.98")
    assert event.quantity_factor == Decimal(1)


def test_a_dividend_needs_a_cum_price_and_cannot_exceed_it():
    event = dividend("D2", "X", EX, "2.00", "USD")
    with pytest.raises(ValidationError, match="cum-event close"):
        event.price_factor(None)
    with pytest.raises(ValidationError, match="exceeds"):
        event.price_factor(Decimal("1.50"))


def test_withholding_reduces_the_net_amount():
    event = dividend("D3", "X", EX, "1.00", "USD", withholding_rate="0.15")
    assert event.net_amount() == Decimal("0.85")
    with pytest.raises(ValidationError):
        dividend("D4", "X", EX, "1.00", "USD", withholding_rate="1.5")


def test_dividends_apply_only_in_total_return_mode():
    event = dividend("D5", "X", EX, "1.00", "USD")
    assert not event.applies_in(AdjustmentMode.CAPITAL)
    assert event.applies_in(AdjustmentMode.TOTAL_RETURN)
    assert split("S5", "X", EX, 2).applies_in(AdjustmentMode.CAPITAL)


def test_a_stock_dividend_is_a_small_split():
    event = StockDividend(action_id="SD", instrument_id="X", ex_date=EX, rate=Decimal("0.05"))
    assert event.quantity_factor == Decimal("1.05")
    assert event.price_factor() * event.quantity_factor == pytest.approx(Decimal(1))


def test_spin_off_uses_the_published_allocation_when_there_is_one():
    event = SpinOff(
        action_id="SO",
        instrument_id="PARENT",
        ex_date=EX,
        child_instrument_id="CHILD",
        ratio=Decimal("0.5"),
        cost_allocation=Decimal("0.186"),
    )
    assert event.child_fraction() == Decimal("0.186")
    assert event.price_factor() == Decimal("0.814")


def test_spin_off_derives_the_allocation_from_market_value_otherwise():
    event = SpinOff(
        action_id="SO",
        instrument_id="PARENT",
        ex_date=EX,
        child_instrument_id="CHILD",
        ratio=Decimal("0.25"),
        child_price=Decimal("40"),
    )
    assert event.child_fraction(Decimal("100")) == Decimal("0.1")
    with pytest.raises(ValidationError):
        event.child_fraction(Decimal("5"))  # the child would be worth twice the parent


def test_spin_off_validation():
    with pytest.raises(ValidationError, match="child price or a cost allocation"):
        SpinOff(action_id="SO", instrument_id="P", ex_date=EX, child_instrument_id="C", ratio=Decimal(1))
    with pytest.raises(ValidationError, match="itself"):
        SpinOff(
            action_id="SO",
            instrument_id="P",
            ex_date=EX,
            child_instrument_id="P",
            ratio=Decimal(1),
            cost_allocation=Decimal("0.1"),
        )


def test_rights_issue_terp_and_factor():
    event = RightsIssue(
        action_id="R", instrument_id="X", ex_date=EX, ratio=Decimal("0.25"), subscription_price=Decimal("80")
    )
    terp = event.theoretical_ex_rights_price(Decimal("100"))
    assert terp == Decimal("96")
    assert event.rights_value(Decimal("100")) == Decimal("4")
    assert event.price_factor(Decimal("100")) == Decimal("0.96")
    assert event.price_factor(Decimal("70")) == Decimal(1)  # out of the money: nothing moves


def test_mergers_and_symbol_changes():
    cash = CashMerger(action_id="M1", instrument_id="X", ex_date=EX, cash_per_share=Decimal("55"), currency="usd")
    assert cash.action_type.is_terminal
    stock = StockMerger(action_id="M2", instrument_id="X", ex_date=EX, acquirer_instrument_id="Y", ratio=Decimal("0.8"))
    assert stock.action_type is CorporateActionType.STOCK_MERGER
    rename = SymbolChange(action_id="N", instrument_id="X", ex_date=EX, old_symbol="FB", new_symbol="META")
    assert rename.price_factor() == Decimal(1)
    with pytest.raises(ValidationError):
        SymbolChange(action_id="N", instrument_id="X", ex_date=EX, old_symbol="FB", new_symbol="FB")


def test_date_rules():
    with pytest.raises(ValidationError, match="announced after"):
        StockSplit(action_id="S", instrument_id="X", ex_date=EX, announced=date(2026, 7, 1), numerator=2)
    with pytest.raises(ValidationError, match="pay date"):
        CashDividend(
            action_id="D",
            instrument_id="X",
            ex_date=EX,
            pay_date=date(2026, 6, 1),
            amount=Decimal(1),
            currency="USD",
        )


def test_entitlement_date_prefers_the_record_date():
    event = dividend("D", "X", EX, 1, "USD")
    assert event.entitlement_date == EX
    later = CashDividend(
        action_id="D",
        instrument_id="X",
        ex_date=EX,
        record_date=date(2026, 6, 11),
        amount=Decimal(1),
        currency="USD",
    )
    assert later.entitlement_date == date(2026, 6, 11)


def test_capital_change_classification():
    assert not CorporateActionType.CASH_DIVIDEND.is_capital_change
    assert CorporateActionType.SPLIT.is_capital_change
    assert CorporateActionType.CASH_MERGER.is_terminal
    assert not CorporateActionType.SPIN_OFF.is_terminal
