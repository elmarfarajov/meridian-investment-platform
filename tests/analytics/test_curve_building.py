"""Curves from dated instruments: conventions, exact repricing, and risk in the quoted instruments."""

from datetime import date

import pytest

from meridian.analytics.curve_building import (
    SOFR_TENORS,
    Tenor,
    build_curve,
    deposit,
    forward_curve,
    overnight_index_swap,
    sofr_curve,
)
from meridian.analytics.curves import bootstrap_par_curve
from meridian.core.exceptions import CurveError, ValidationError
from meridian.marketdata.rates_history import illustrative_sofr_quotes

TODAY = date(2026, 9, 30)
QUOTES = illustrative_sofr_quotes(TODAY)


@pytest.fixture(scope="module")
def curve():
    return sofr_curve(TODAY, QUOTES)


def test_tenors_parse_and_roll():
    assert Tenor.parse("18m") == Tenor(18, "M")
    assert str(Tenor.parse(" 10Y ")) == "10Y"
    assert Tenor.parse("1W").add_to(date(2026, 1, 30)) == date(2026, 2, 6)
    assert Tenor.parse("1M").add_to(date(2026, 1, 31)) == date(2026, 2, 28)  # clamped to the month end
    assert Tenor.parse("2Y").years == 2.0
    with pytest.raises(ValidationError):
        Tenor.parse("ten years")


def test_a_swap_starts_two_business_days_after_the_trade_and_rolls_modified_following():
    swap = overnight_index_swap(date(2026, 12, 23), "1Y", 0.04)
    # 24 December is a business day for SIFMA, 25 is Christmas: spot is the 28th
    assert swap.start == date(2026, 12, 28)
    assert swap.maturity == date(2027, 12, 28)
    long = overnight_index_swap(TODAY, "5Y", 0.04)
    assert len(long.periods) == 5
    assert all(period.accrual == pytest.approx((period.end - period.start).days / 360) for period in long.periods)


def test_a_payment_lag_moves_payments_but_not_accrual():
    lagged = overnight_index_swap(TODAY, "2Y", 0.04, payment_lag=2)
    for period in lagged.periods:
        assert period.payment > period.end
    assert lagged.pillar == lagged.periods[-1].payment


def test_a_deposit_is_dated_like_the_market():
    item = deposit(TODAY, "3M", 0.041)
    assert item.start == date(2026, 10, 2)
    assert item.end == date(2027, 1, 4)  # 2 January 2027 is a Saturday
    assert item.pillar == item.end


@pytest.mark.parametrize("method", ["log_linear", "linear", "monotone_cubic", "monotone_convex"])
def test_every_instrument_prices_back_to_its_quote(method):
    built = sofr_curve(TODAY, QUOTES, interpolation=method)
    assert max(abs(error) for _, _, error in built.repricing()) < 1e-12
    assert built.iterations == 1 if method in {"log_linear", "linear"} else built.iterations > 1


def test_deposits_and_swaps_build_one_curve():
    instruments = [deposit(TODAY, "1M", 0.0399), deposit(TODAY, "3M", 0.0405)]
    instruments += [overnight_index_swap(TODAY, tenor, rate) for tenor, rate in (("1Y", 0.041), ("5Y", 0.043))]
    built = build_curve(TODAY, instruments)
    assert max(abs(error) for _, _, error in built.repricing()) < 1e-12
    assert built.labels[0] == "1M deposit"


def test_the_curve_refuses_what_it_cannot_build():
    with pytest.raises(CurveError):
        build_curve(TODAY, [])
    same = overnight_index_swap(TODAY, "12M", 0.04)
    with pytest.raises(CurveError, match="share a pillar"):
        build_curve(TODAY, [same, overnight_index_swap(TODAY, "1Y", 0.041)])
    with pytest.raises(CurveError):
        sofr_curve(TODAY, QUOTES[:-1])


def test_a_quote_moves_its_own_pillar_most(curve):
    jacobian = curve.jacobian()
    assert len(jacobian) == len(SOFR_TENORS)
    for index, row in enumerate(jacobian):
        assert abs(row[index]) == pytest.approx(max(abs(value) for value in row))
    # a quote cannot move a pillar before it under log-linear interpolation
    assert all(abs(jacobian[i][j]) < 1e-9 for i in range(len(jacobian)) for j in range(i))


def test_a_swap_s_risk_sits_in_its_own_bucket_and_sums_to_the_parallel_dv01(curve):
    ten_year = next(item for item in curve.instruments if item.label.startswith("10Y"))
    buckets = curve.bucketed_dv01(lambda moved: ten_year.value(moved.discount, 1_000_000))
    by_label = dict(buckets)
    largest = max(buckets, key=lambda item: abs(item[1]))
    assert largest[0] == ten_year.label
    assert by_label[ten_year.label] == pytest.approx(sum(by_label.values()), rel=1e-6)
    parallel = curve.rebuilt([q + 1e-4 for q in QUOTES])
    assert sum(by_label.values()) == pytest.approx(
        ten_year.value(parallel.discount, 1_000_000) - ten_year.value(curve.discount, 1_000_000), rel=1e-3
    )


def test_forwards_are_sampled_for_plotting(curve):
    times, forwards = forward_curve(curve, horizon_years=10)
    assert len(times) == len(forwards) > 500
    assert all(0 < value < 0.1 for value in forwards)


def test_the_par_bootstrap_reprices_its_inputs_with_a_non_local_interpolator():
    tenors = [0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30]
    pars = [0.0431, 0.0421, 0.0398, 0.0362, 0.0352, 0.0351, 0.0361, 0.0378, 0.0412, 0.0409]
    for method in ("monotone_cubic", "monotone_convex"):
        built = bootstrap_par_curve(TODAY, tenors, pars, interpolation=method)
        # a single sequential pass left monotone cubic up to 0.86 bp off its quotes
        assert max(abs(built.par_rate(t) - p) for t, p in zip(tenors, pars, strict=True)) < 1e-12
