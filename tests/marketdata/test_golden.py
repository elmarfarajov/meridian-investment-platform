"""The golden copy and FX history."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from meridian.core.exceptions import RateNotFoundError, ValidationError
from meridian.marketdata.fx_history import FxHistory
from meridian.marketdata.golden import (
    GoldenMethod,
    GoldenPrice,
    PricingPolicy,
    build_golden_copy,
    choose_price,
    compare_to_reference,
)
from meridian.marketdata.providers import DEFAULT_VENDORS, InstrumentSpec, SyntheticMarket, vendor_panel
from meridian.marketdata.quotes import FxQuote, MarketDataset, Quote
from meridian.marketdata.series import TimeSeries

DAY = date(2026, 5, 4)
POLICY = PricingPolicy(ranking=("exchange", "vendor", "evaluated"), tolerance_bps=25)


def q(source: str, close: str, day: date = DAY) -> Quote:
    return Quote(instrument_id="X", day=day, close=Decimal(close), currency="USD", source=source)


def test_priority_takes_the_top_ranked_source_within_tolerance():
    price = choose_price("X", DAY, [q("evaluated", "100.10"), q("vendor", "100.05"), q("exchange", "100.00")], POLICY)
    assert isinstance(price, GoldenPrice)
    assert price.source == "exchange"
    assert price.value == Decimal("100.00")
    assert not price.challenged
    assert price.dispersion_bps == pytest.approx(10.0, abs=0.01)


def test_a_top_ranked_source_far_from_consensus_does_not_win():
    price = choose_price("X", DAY, [q("exchange", "110.00"), q("vendor", "100.00"), q("evaluated", "100.02")], POLICY)
    assert isinstance(price, GoldenPrice)
    assert price.source == "vendor"
    assert price.challenged
    # the consensus is the median, 100.02, so the exchange is 998 bp away from it
    assert "exchange +998 bp" in price.reason
    assert ("exchange", "+998 bp from consensus") in price.excluded


def test_median_method_blends_the_in_tolerance_values():
    policy = PricingPolicy(ranking=POLICY.ranking, method=GoldenMethod.MEDIAN)
    price = choose_price("X", DAY, [q("exchange", "100.00"), q("vendor", "100.04"), q("evaluated", "100.10")], policy)
    assert isinstance(price, GoldenPrice)
    assert price.source == "median"
    assert price.value == Decimal("100.04")


def test_blocked_and_zero_values_are_excluded_with_a_reason():
    quotes = [q("exchange", "0"), q("vendor", "100.00"), q("evaluated", "100.01")]
    price = choose_price("X", DAY, quotes, POLICY, blocked_sources={"vendor"})
    assert isinstance(price, GoldenPrice)
    assert price.source == "evaluated"
    assert price.challenged  # one usable source out of three
    assert dict(price.excluded) == {"vendor": "withheld by a quality check", "exchange": "non-positive"}


def test_nothing_is_published_when_the_policy_cannot_be_met():
    strict = PricingPolicy(ranking=POLICY.ranking, min_sources=2)
    outcome = choose_price("X", DAY, [q("exchange", "100")], strict)
    assert outcome == ("X", DAY, "1 usable source(s), policy needs 2")


def test_policy_validation():
    with pytest.raises(ValidationError):
        PricingPolicy(ranking=())
    with pytest.raises(ValidationError):
        PricingPolicy(ranking=("a",), tolerance_bps=0)
    with pytest.raises(ValidationError):
        PricingPolicy(ranking=("a",), min_sources=0)
    assert POLICY.rank("unknown") == 3


def test_consensus_beats_every_single_vendor_against_the_truth():
    reference = (
        SyntheticMarket([InstrumentSpec("A"), InstrumentSpec("B", initial_price=25.0)], seed=6)
        .generate(date(2025, 1, 2), date(2025, 12, 31))
        .dataset
    )
    vendors = vendor_panel(reference, DEFAULT_VENDORS, seed=3)
    copy = build_golden_copy(vendors, PricingPolicy(ranking=tuple(v.name for v in DEFAULT_VENDORS)))
    errors = compare_to_reference(copy, reference, vendors)
    worst = {name: float(np.max(np.abs(values))) for name, values in errors.items()}
    assert set(errors) == {"golden", "exchange", "vendor-b", "evaluated"}
    assert worst["golden"] < min(worst[name] for name in ("exchange", "vendor-b", "evaluated"))
    assert float(np.mean(np.abs(errors["golden"]))) < 2.0
    assert len(copy.series("A")) > 240
    assert sum(copy.source_share().values()) == len(copy)
    assert copy.challenges()
    assert copy.dispersion("A")


def test_golden_copy_reports_what_it_could_not_price():
    dataset = MarketDataset.from_records([q("exchange", "100", date(2026, 5, 4)), q("vendor", "100", date(2026, 5, 5))])
    copy = build_golden_copy(dataset, POLICY, blocked=[("X", "vendor", date(2026, 5, 5))])
    assert [price.day for price in copy.prices] == [date(2026, 5, 4)]
    assert copy.unpriced[0][:2] == ("X", date(2026, 5, 5))


# ---------------------------------------------------------------------------- FX history
@pytest.fixture
def history() -> FxHistory:
    rates = [
        FxQuote(base="EUR", quote="USD", day=date(2026, 5, 1), rate=Decimal("1.10")),
        FxQuote(base="EUR", quote="USD", day=date(2026, 5, 4), rate=Decimal("1.12")),
        FxQuote(base="GBP", quote="USD", day=date(2026, 5, 1), rate=Decimal("1.25")),
        FxQuote(base="USD", quote="JPY", day=date(2026, 5, 1), rate=Decimal("150")),
    ]
    return FxHistory.from_quotes(rates, max_age_days=4)


def test_rates_are_looked_up_as_of_a_date_through_the_pivot(history: FxHistory):
    assert history.rate("EUR", "USD", date(2026, 5, 4)) == Decimal("1.12")
    assert history.rate("EUR", "USD", date(2026, 5, 3)) == Decimal("1.10")  # carried over the weekend
    assert history.rate("EUR", "GBP", date(2026, 5, 1)) == Decimal("0.88")
    assert history.rate("GBP", "JPY", date(2026, 5, 1)) == Decimal("187.50")
    assert history.currencies == ("EUR", "GBP", "JPY", "USD")


def test_a_rate_older_than_the_limit_is_not_used(history: FxHistory):
    with pytest.raises(RateNotFoundError):
        history.rate("GBP", "USD", date(2026, 5, 8))


def test_a_series_is_converted_day_by_day_and_gaps_stay_gaps(history: FxHistory):
    prices = TimeSeries([(date(2026, 5, 1), "10"), (date(2026, 5, 4), "10"), (date(2026, 5, 20), "10")], name="P")
    converted = history.convert_series(prices, "EUR", "USD")
    assert converted[date(2026, 5, 1)] == Decimal("11.00")
    assert converted[date(2026, 5, 4)] == Decimal("11.20")
    assert date(2026, 5, 20) not in converted
    assert history.convert_series(prices, "USD", "USD") is prices


def test_cross_matrix_is_consistent(history: FxHistory):
    names = ["EUR", "GBP", "USD"]
    matrix = history.cross_matrix(date(2026, 5, 1), names)
    for i in range(3):
        assert matrix[i][i] == pytest.approx(1.0)
        for j in range(3):
            assert matrix[i][j] * matrix[j][i] == pytest.approx(1.0)
    assert len(history.returns("EURUSD")) == 1
