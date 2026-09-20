"""Bond analytics, tested against the relationships that must hold.

Rather than pinning numbers from a spreadsheet, these tests assert the properties
fixed income mathematics guarantees: a bond priced at its own coupon is worth par,
a zero-coupon bond's duration is its maturity, the price-yield relationship is
convex, and a yield solved from a price reproduces that price exactly.
"""

from __future__ import annotations

from datetime import date

import pytest

from meridian.analytics.bonds import FixedRateBond, portfolio_duration, price_yield_curve
from meridian.analytics.curves import bootstrap_par_curve, flat_curve
from meridian.core.daycount import DayCountConvention
from meridian.core.enums import Frequency
from meridian.core.exceptions import ValidationError

VALUATION = date(2026, 9, 18)
SETTLEMENT = date(2026, 9, 21)


@pytest.fixture
def bond() -> FixedRateBond:
    return FixedRateBond.create(
        issue_date=date(2024, 5, 15),
        maturity=date(2034, 5, 15),
        coupon_rate=0.04,
        frequency=Frequency.SEMI_ANNUAL,
        name="UST 4% 2034",
    )


@pytest.fixture
def curve():
    return bootstrap_par_curve(
        VALUATION,
        [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0],
        [0.0425, 0.0432, 0.0418, 0.0395, 0.0388, 0.0390, 0.0402, 0.0415, 0.0448, 0.0455],
    )


def test_a_bond_priced_at_its_own_coupon_is_worth_par():
    """On a coupon date, with yield equal to coupon, the price is exactly 100."""
    for frequency in (Frequency.ANNUAL, Frequency.SEMI_ANNUAL, Frequency.QUARTERLY):
        instrument = FixedRateBond.create(
            issue_date=date(2026, 9, 18),
            maturity=date(2036, 9, 18),
            coupon_rate=0.05,
            frequency=frequency,
        )
        assert instrument.clean_price_from_yield(0.05, date(2026, 9, 18)) == pytest.approx(100.0, abs=1e-9)


def test_price_moves_inversely_with_yield(bond: FixedRateBond):
    high = bond.clean_price_from_yield(0.03, SETTLEMENT)
    middle = bond.clean_price_from_yield(0.04, SETTLEMENT)
    low = bond.clean_price_from_yield(0.06, SETTLEMENT)
    assert high > middle > low


def test_a_discount_bond_trades_below_par_and_a_premium_bond_above(bond: FixedRateBond):
    assert bond.clean_price_from_yield(bond.coupon_rate + 0.01, SETTLEMENT) < 100
    assert bond.clean_price_from_yield(bond.coupon_rate - 0.01, SETTLEMENT) > 100


def test_yield_to_maturity_reproduces_the_price_it_was_solved_from(bond: FixedRateBond):
    for quoted in (85.0, 96.79, 100.0, 113.4):
        rate = bond.yield_to_maturity(quoted, SETTLEMENT)
        assert bond.clean_price_from_yield(rate, SETTLEMENT) == pytest.approx(quoted, abs=1e-8)


def test_accrued_interest_grows_through_the_period_and_resets(bond: FixedRateBond):
    period = bond.schedule.period_containing(SETTLEMENT)
    assert period is not None
    assert bond.accrued_interest(period.start) == 0.0
    early = bond.accrued_interest(period.start.replace(day=period.start.day + 1))
    assert 0 < early < bond.accrued_interest(SETTLEMENT)
    days, period_days = bond.days_accrued(SETTLEMENT)
    assert 0 < days < period_days


def test_accrued_interest_on_a_thirty_360_bond_is_a_clean_fraction(bond: FixedRateBond):
    """Half a period into a 30/360 bond, exactly half the coupon has accrued."""
    period = bond.schedule.period_containing(SETTLEMENT)
    assert period is not None
    midpoint = date(period.start.year, period.start.month + 3, period.start.day)
    assert bond.accrued_interest(midpoint) == pytest.approx(bond.coupon_amount / 2, abs=1e-9)


def test_the_dirty_price_is_the_clean_price_plus_accrued(bond: FixedRateBond):
    clean = bond.clean_price_from_yield(0.045, SETTLEMENT)
    dirty = bond.dirty_price_from_yield(0.045, SETTLEMENT)
    assert dirty - clean == pytest.approx(bond.accrued_interest(SETTLEMENT), abs=1e-12)


def test_a_zero_coupon_bonds_duration_is_its_maturity():
    zero = FixedRateBond.create(
        issue_date=date(2026, 9, 18),
        maturity=date(2036, 9, 18),
        coupon_rate=0.0,
        frequency=Frequency.ANNUAL,
        name="zero 2036",
    )
    assert zero.macaulay_duration(0.04, date(2026, 9, 18)) == pytest.approx(10.0, abs=1e-6)


def test_modified_duration_is_macaulay_discounted(bond: FixedRateBond):
    macaulay = bond.macaulay_duration(0.045, SETTLEMENT)
    modified = bond.modified_duration(0.045, SETTLEMENT)
    assert modified == pytest.approx(macaulay / (1 + 0.045 / bond.frequency), abs=1e-12)
    assert modified < macaulay


def test_duration_predicts_the_dv01(bond: FixedRateBond):
    dirty = bond.dirty_price_from_yield(0.045, SETTLEMENT)
    predicted = bond.modified_duration(0.045, SETTLEMENT) * dirty * 0.0001
    assert bond.dv01(0.045, SETTLEMENT) == pytest.approx(predicted, rel=1e-3)


def test_a_lower_coupon_lengthens_duration():
    durations = []
    for coupon in (0.02, 0.04, 0.08):
        instrument = FixedRateBond.create(issue_date=date(2026, 9, 18), maturity=date(2036, 9, 18), coupon_rate=coupon)
        durations.append(instrument.modified_duration(0.045, date(2026, 9, 18)))
    assert durations == sorted(durations, reverse=True)


def test_convexity_is_positive_and_improves_the_estimate(bond: FixedRateBond):
    assert bond.convexity(0.045, SETTLEMENT) > 0
    for shift in (-300, -100, 100, 300):
        actual, linear, quadratic = bond.price_change_estimate(0.045, SETTLEMENT, shift)
        assert abs(quadratic - actual) < abs(linear - actual)


def test_duration_alone_always_understates_the_price(bond: FixedRateBond):
    """Because the price-yield curve is convex, the tangent lies below it on both sides."""
    for shift in (-200, -50, 50, 200):
        actual, linear, _ = bond.price_change_estimate(0.045, SETTLEMENT, shift)
        assert linear < actual


def test_pricing_off_a_flat_curve_matches_pricing_at_that_yield():
    instrument = FixedRateBond.create(
        issue_date=date(2026, 9, 18), maturity=date(2031, 9, 18), coupon_rate=0.05, frequency=Frequency.ANNUAL
    )
    flat = flat_curve(date(2026, 9, 18), 0.05, compounding="annual")
    from_curve = instrument.price_from_curve(flat, date(2026, 9, 18))
    from_yield = instrument.dirty_price_from_yield(0.05, date(2026, 9, 18))
    assert from_curve == pytest.approx(from_yield, rel=2e-3)


def test_the_z_spread_reprices_the_bond(bond: FixedRateBond, curve):
    quoted = 96.79
    spread = bond.spread_to_curve(quoted, curve, SETTLEMENT)
    shifted_value = sum(
        flow.amount
        * curve.discount_factor(flow.payment_date)
        * pow(2.718281828459045, -spread * flow.years_from(curve.valuation_date, curve.day_count))
        for flow in bond.cash_flows(SETTLEMENT)
    )
    assert shifted_value == pytest.approx(quoted + bond.accrued_interest(SETTLEMENT), rel=1e-6)


def test_key_rate_durations_sum_to_roughly_the_modified_duration(bond: FixedRateBond, curve):
    durations = bond.key_rate_durations(curve, SETTLEMENT)
    total = sum(value for _, value in durations)
    assert total == pytest.approx(bond.modified_duration(0.0415, SETTLEMENT), rel=0.1)
    assert all(value >= -1e-9 for _, value in durations)


def test_key_rate_risk_concentrates_near_the_maturity(bond: FixedRateBond, curve):
    durations = dict(bond.key_rate_durations(curve, SETTLEMENT))
    assert durations["7y"] + durations["10y"] > sum(
        value for label, value in durations.items() if label not in {"7y", "10y"}
    )


def test_cash_flows_end_with_the_redemption(bond: FixedRateBond):
    flows = bond.cash_flows(SETTLEMENT)
    assert flows[-1].kind == "coupon+redemption"
    assert flows[-1].amount == pytest.approx(bond.face_value + bond.coupon_amount)
    assert all(flow.amount == pytest.approx(bond.coupon_amount) for flow in flows[:-1])
    assert flows[0].as_money() > 0


def test_a_matured_bond_cannot_be_priced(bond: FixedRateBond):
    with pytest.raises(ValidationError, match="no cash flows left"):
        bond.dirty_price_from_yield(0.04, date(2040, 1, 1))


def test_the_price_yield_series_is_monotone_and_convex(bond: FixedRateBond):
    _, prices = price_yield_curve(bond, SETTLEMENT, low=0.0, high=0.12, count=40)
    assert prices == sorted(prices, reverse=True)
    # second differences of a convex function are positive
    seconds = [prices[i + 2] - 2 * prices[i + 1] + prices[i] for i in range(len(prices) - 2)]
    assert all(value > 0 for value in seconds)


def test_portfolio_duration_is_market_value_weighted(bond: FixedRateBond):
    short = FixedRateBond.create(issue_date=date(2026, 9, 18), maturity=date(2029, 9, 18), coupon_rate=0.04, name="3y")
    duration, convexity = portfolio_duration([(bond, 0.045, 6_000_000.0), (short, 0.041, 4_000_000.0)], SETTLEMENT)
    long_only = bond.modified_duration(0.045, SETTLEMENT)
    short_only = short.modified_duration(0.041, SETTLEMENT)
    assert short_only < duration < long_only
    assert convexity > 0
    with pytest.raises(ValidationError):
        portfolio_duration([(bond, 0.045, 0.0)], SETTLEMENT)


def test_the_day_count_changes_the_accrued_but_not_the_maturity():
    actual = FixedRateBond.create(
        issue_date=date(2024, 5, 15),
        maturity=date(2034, 5, 15),
        coupon_rate=0.04,
        day_count=DayCountConvention.ACT_365F,
    )
    thirty = FixedRateBond.create(
        issue_date=date(2024, 5, 15),
        maturity=date(2034, 5, 15),
        coupon_rate=0.04,
        day_count=DayCountConvention.THIRTY_360_US,
    )
    assert actual.maturity == thirty.maturity
    assert actual.accrued_interest(SETTLEMENT) != pytest.approx(thirty.accrued_interest(SETTLEMENT))


def test_the_bond_prints_itself(bond: FixedRateBond):
    assert str(bond) == "UST 4% 2034 4.000% 2034-05-15"
