"""Settlement cycles by market and date, and the versioned trade blotter."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from meridian.accounting.blotter import (
    FAILING_FLAG,
    SettlementStatus,
    TradeBlotter,
    VersionKind,
    blotter_from,
)
from meridian.accounting.settlement import (
    DEFAULT_RULES,
    US_T1_EFFECTIVE,
    SettlementRule,
    SettlementRules,
    settlement_calendar,
)
from meridian.core import ValidationError
from meridian.core.enums import AssetClass
from meridian.domain import build_trade
from meridian.seed import demo_instruments

INSTRUMENTS = {item.instrument_id: item for item in demo_instruments()}
RULES = SettlementRules()


def at(day: int, hour: int = 18) -> datetime:
    return datetime(2026, 3, day, hour, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------- settlement cycles
def test_us_equities_moved_from_t_plus_two_to_t_plus_one_on_28_may_2024():
    apple = INSTRUMENTS["US-AAPL"]
    assert date(2024, 5, 28) == US_T1_EFFECTIVE
    assert RULES.cycle(apple, date(2024, 5, 24)) == 2
    assert RULES.cycle(apple, date(2024, 5, 28)) == 1
    # Friday 24 May 2024, T+2 across the Memorial Day weekend lands on Wednesday
    assert RULES.settlement_date(apple, date(2024, 5, 24)) == date(2024, 5, 29)
    # the first T+1 trade date
    assert RULES.settlement_date(apple, date(2024, 5, 28)) == date(2024, 5, 29)


def test_european_markets_stay_on_t_plus_two():
    assert RULES.cycle(INSTRUMENTS["DE-BAYN"], date(2026, 3, 2)) == 2
    assert RULES.cycle(INSTRUMENTS["GB-BAE"], date(2026, 3, 2)) == 2
    assert RULES.settlement_date(INSTRUMENTS["GB-BAE"], date(2026, 3, 2)) == date(2026, 3, 4)


def test_the_announced_european_move_needs_no_code():
    assert RULES.cycle(INSTRUMENTS["GB-BAE"], date(2027, 10, 11)) == 1
    assert RULES.cycle(INSTRUMENTS["DE-BAYN"], date(2027, 10, 8)) == 2


def test_treasuries_settle_next_day():
    treasury = INSTRUMENTS["US-T-2032"]
    assert RULES.rule_for(treasury, date(2024, 1, 3)).days == 1
    assert RULES.settlement_date(treasury, date(2026, 3, 6)) == date(2026, 3, 9)


def test_settlement_needs_both_the_market_and_the_currency_open():
    # a USD-denominated ETF listed in Amsterdam: TARGET and New York must both be open.
    # Good Friday closes both; Easter Monday closes TARGET only, so T+2 from Thursday skips both days.
    world = INSTRUMENTS["IE-IWDA"]
    assert RULES.settlement_date(world, date(2026, 4, 2)) == date(2026, 4, 8)
    joint = settlement_calendar("TARGET", "USD")
    assert not joint.is_business_day(date(2026, 4, 6))


def test_a_trade_on_a_holiday_rolls_to_the_next_business_day_first():
    assert RULES.settlement_date(INSTRUMENTS["US-AAPL"], date(2026, 1, 1)) == date(2026, 1, 5)


def test_fx_spot_settles_t_plus_two_on_the_joint_calendar():
    # Monday 25 May 2026 is a holiday in both London and New York
    assert RULES.fx_settlement_date("GBP", "USD", date(2026, 5, 21)) == date(2026, 5, 26)


def test_rules_are_validated_and_an_unknown_market_falls_back_to_the_default():
    with pytest.raises(ValidationError, match="precede"):
        SettlementRule("bad", frozenset({"X"}), -1)
    with pytest.raises(ValidationError, match="ends before"):
        SettlementRule("bad", frozenset({"X"}), 1, effective_from=date(2025, 1, 1), effective_to=date(2024, 1, 1))
    exotic = replace(INSTRUMENTS["US-AAPL"], exchange="XBOM", calendar="WEEKEND")
    assert RULES.rule_for(exotic, date(2026, 1, 5)) is None
    assert SettlementRules(DEFAULT_RULES, default_days=3).cycle(exotic, date(2026, 1, 5)) == 3
    assert DEFAULT_RULES[0].asset_classes == frozenset({AssetClass.EQUITY, AssetClass.MULTI_ASSET})


# ---------------------------------------------------------------------------- the blotter
def trade(transaction_id: str = "T1", quantity: int = 100, price: str = "50") -> object:
    return build_trade(
        transaction_id=transaction_id,
        portfolio_id="P",
        instrument_id="US-AAPL",
        trade_date=date(2026, 3, 2),
        quantity=quantity,
        price=price,
        currency="USD",
        settlement_date=date(2026, 3, 3),
    )


def test_amendments_are_new_versions_and_the_past_can_be_replayed():
    blotter = TradeBlotter()
    blotter.book(trade(), at(2))
    blotter.amend(trade(price="51"), at(4), reason="wrong price")
    history = blotter.history("T1")
    assert [(item.version, item.kind) for item in history] == [(1, VersionKind.BOOKED), (2, VersionKind.AMENDED)]
    assert blotter.current("T1", at(3)).price == Decimal(50)
    assert blotter.current("T1").price == Decimal(51)
    assert blotter.current("T1", at(1, 9)) is None  # not yet booked
    assert [item.price for item in blotter.as_known_at(at(3))] == [Decimal(50)]


def test_a_cancelled_trade_disappears_from_the_current_book_but_not_from_the_past():
    blotter = blotter_from([trade("T1"), trade("T2")], at(2))
    blotter.cancel("T2", at(5), reason="booked to the wrong account")
    assert [item.transaction_id for item in blotter.as_known_at()] == ["T1"]
    assert [item.transaction_id for item in blotter.as_known_at(at(4))] == ["T1", "T2"]
    corrections = blotter.corrections(at(3))
    assert [(item.transaction_id, item.kind) for item in corrections] == [("T2", VersionKind.CANCELLED)]
    assert blotter.corrections(at(6)) == []
    assert len(blotter.knowledge_times()) == 2
    with pytest.raises(ValidationError, match="already cancelled"):
        blotter.cancel("T2", at(6))
    with pytest.raises(ValidationError, match="was cancelled"):
        blotter.amend(trade("T2"), at(6))


def test_the_blotter_refuses_duplicates_unknown_trades_and_back_dated_amendments():
    blotter = blotter_from([trade()], at(4))
    with pytest.raises(ValidationError, match="already booked"):
        blotter.book(trade(), at(5))
    with pytest.raises(ValidationError, match="no trade"):
        blotter.history("NOPE")
    with pytest.raises(ValidationError, match="predate"):
        blotter.amend(trade(price="1"), at(3))
    assert len(blotter) == 1


def test_a_settlement_fail_moves_the_cash_date_and_is_tracked_while_open():
    blotter = blotter_from([trade("T1"), trade("T2")], at(2))
    record = blotter.fail("T1", actual=date(2026, 3, 6), reason="counterparty short of stock")
    assert record.days_failing(date(2026, 3, 5)) == 2
    assert record.days_failing(date(2026, 3, 20)) == 3
    assert blotter.current("T1").settles_on == date(2026, 3, 6)
    assert blotter.status("T1", date(2026, 3, 2)) is SettlementStatus.PENDING
    assert blotter.status("T1", date(2026, 3, 4)) is SettlementStatus.FAILING
    assert blotter.status("T1", date(2026, 3, 6)) is SettlementStatus.SETTLED
    assert blotter.status("T2", date(2026, 3, 3)) is SettlementStatus.SETTLED
    assert [item.transaction_id for item in blotter.fails(date(2026, 3, 4))] == ["T1"]
    assert blotter.fails(date(2026, 3, 7)) == []
    with pytest.raises(ValidationError, match="after its contractual"):
        blotter.fail("T2", actual=date(2026, 3, 3))


def test_an_open_fail_is_flagged_for_the_engine():
    blotter = blotter_from([trade()], at(2))
    blotter.fail("T1")
    assert blotter.current("T1").metadata[FAILING_FLAG] == "true"
    assert blotter.status("T1", date(2026, 3, 30)) is SettlementStatus.FAILING
    blotter.cancel("T1", at(9))
    with pytest.raises(ValidationError, match="not a live trade"):
        blotter.status("T1", date(2026, 3, 30))
    with pytest.raises(ValidationError, match="not a live trade"):
        blotter.fail("T1")
