"""UK gilt conventions: the ex-dividend period and negative accrued interest."""

from datetime import date

import pytest

from meridian.analytics.bonds import FixedRateBond

GILT = FixedRateBond.gilt(issue_date=date(2023, 1, 31), maturity=date(2034, 7, 31), coupon_rate=0.04625)


def test_a_gilt_goes_ex_seven_business_days_before_its_nominal_coupon_date():
    january = next(period for period in GILT.schedule.periods if period.end == date(2026, 1, 31))
    assert GILT.ex_dividend_date(january) == date(2026, 1, 22)
    assert january.payment_date == date(2026, 2, 2)  # 31 January 2026 is a Saturday: paid on the Monday
    assert not GILT.is_ex_dividend(date(2026, 1, 21))
    assert GILT.is_ex_dividend(date(2026, 1, 22))


def test_accrued_interest_is_negative_in_the_ex_period_and_resets_at_the_coupon():
    assert GILT.accrued_interest(date(2026, 1, 21)) > 2.0
    ex = GILT.accrued_interest(date(2026, 1, 22))
    # nine days to the coupon, of 184 in the period, at half the annual coupon
    assert ex == pytest.approx(-100 * 0.04625 / 2 * 9 / 184)
    assert GILT.accrued_interest(date(2026, 2, 2)) > 0


def test_the_buyer_in_the_ex_period_does_not_receive_the_next_coupon():
    before = GILT.cash_flows(date(2026, 1, 21))
    after = GILT.cash_flows(date(2026, 1, 22))
    assert len(after) == len(before) - 1
    assert after[0].payment_date == date(2026, 7, 31)


def test_the_dirty_price_drops_by_about_a_coupon_when_the_bond_goes_ex():
    cum = GILT.dirty_price_from_yield(0.045, date(2026, 1, 21))
    ex = GILT.dirty_price_from_yield(0.045, date(2026, 1, 22))
    assert cum - ex == pytest.approx(100 * 0.04625 / 2, rel=0.01)
    # the clean price barely moves: negative accrued compensates
    assert GILT.clean_price_from_yield(0.045, date(2026, 1, 22)) == pytest.approx(
        GILT.clean_price_from_yield(0.045, date(2026, 1, 21)), abs=0.01
    )


def test_a_bond_without_an_ex_period_is_never_ex():
    plain = FixedRateBond.create(issue_date=date(2023, 1, 31), maturity=date(2034, 7, 31), coupon_rate=0.04)
    assert plain.ex_dividend_days == 0
    assert not plain.is_ex_dividend(date(2026, 1, 30))
