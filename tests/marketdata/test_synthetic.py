"""The synthetic market: reproducible, and realistic in the ways a quality rule has to survive."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from meridian.core.calendars import get_calendar
from meridian.core.exceptions import ValidationError
from meridian.domain.corporate_actions import CashDividend, StockSplit
from meridian.marketdata.providers import (
    FxSpec,
    InstrumentSpec,
    MarketDataProvider,
    SyntheticMarket,
    cross_rates,
    demo_market,
    garch_fourth_moment_finite,
    load,
    student_t_kurtosis,
    weekdays,
)

START, END = date(2024, 1, 2), date(2026, 6, 30)


@pytest.fixture(scope="module")
def market() -> SyntheticMarket:
    return SyntheticMarket(
        [
            InstrumentSpec("A", "USD", "XNYS", 100.0, 0.25, sector="Tech"),
            InstrumentSpec("B", "USD", "XNYS", 50.0, 0.30, sector="Tech", beta=1.2),
            InstrumentSpec("L", "GBP", "XLON", 12.5, 0.20, sector="Industrials", price_places=3),
            InstrumentSpec(
                "S",
                "USD",
                "XNYS",
                400.0,
                0.35,
                sector="Tech",
                splits=((date(2025, 3, 3), 4, 1),),
                dividends=((date(2024, 9, 12), 1.20), (date(2025, 9, 11), 0.35)),
            ),
        ],
        [FxSpec("EUR", "USD", 1.08), FxSpec("GBP", "USD", 1.27), FxSpec("USD", "JPY", 150.0, places=4)],
        seed=3,
    )


def test_the_same_seed_gives_the_same_market_to_the_last_decimal(market: SyntheticMarket):
    first = market.generate(START, END).raw_series("A")
    fresh = SyntheticMarket(list(market.instruments.values()), list(market.fx_specs.values()), seed=3)
    assert fresh.generate(START, END).raw_series("A") == first
    other = SyntheticMarket(list(market.instruments.values()), seed=4)
    assert other.generate(START, END).raw_series("A") != first


def test_each_instrument_trades_on_its_own_calendar(market: SyntheticMarket):
    history = market.generate(START, END)
    for key, calendar in (("A", "XNYS"), ("L", "XLON")):
        days = history.raw_series(key).days
        assert days == tuple(get_calendar(calendar).business_days(days[0], END))
    assert date(2024, 7, 4) not in history.raw_series("A")  # Independence Day
    assert date(2024, 7, 4) in history.raw_series("L")


def test_prices_carry_the_instrument_precision(market: SyntheticMarket):
    history = market.generate(START, END)
    assert all(value.as_tuple().exponent == -3 for value in history.raw_series("L").values)
    assert all(value.as_tuple().exponent == -2 for value in history.raw_series("A").values)


def test_returns_have_fat_tails(market: SyntheticMarket):
    returns = np.array(market.generate(START, END).log_returns["A"])
    standardised = (returns - returns.mean()) / returns.std()
    excess_kurtosis = float((standardised**4).mean() - 3)
    assert excess_kurtosis > 1.0  # a normal distribution has zero


def test_volatility_clusters(market: SyntheticMarket):
    returns = np.array(market.generate(START, END).log_returns["B"])
    squared = returns**2 - (returns**2).mean()
    autocorrelation = float((squared[1:] * squared[:-1]).mean() / (squared**2).mean())
    assert autocorrelation > 0.02  # large moves follow large moves


def test_names_in_one_sector_move_together(market: SyntheticMarket):
    history = market.generate(START, END)
    a, b = history.raw_series("A"), history.raw_series("B")
    left, right = a.align(b)
    ra = np.diff(np.log(left.floats()))
    rb = np.diff(np.log(right.floats()))
    assert float(np.corrcoef(ra, rb)[0, 1]) > 0.3


def test_the_default_parameters_have_a_finite_fourth_moment():
    assert garch_fourth_moment_finite(0.06, 0.92, 5.0)
    assert not garch_fourth_moment_finite(0.08, 0.90, 4.0)  # Student-t(4) has infinite kurtosis
    assert student_t_kurtosis(6.0) == pytest.approx(6.0)


def test_realised_volatility_is_calibrated_to_the_specification():
    """Judged across seeds: one 2.5-year GARCH sample is a single draw from a wide distribution."""
    spec = InstrumentSpec("A", annual_vol=0.25)
    realised = [
        float(np.std(SyntheticMarket([spec, InstrumentSpec("B")], seed=seed).generate(START, END).log_returns["A"]))
        * math.sqrt(252)
        for seed in range(1, 10)
    ]
    assert float(np.median(realised)) == pytest.approx(0.25, rel=0.12)


def test_corporate_actions_are_emitted_on_trading_days(market: SyntheticMarket):
    history = market.generate(START, END)
    splits = [action for action in history.corporate_actions if isinstance(action, StockSplit)]
    dividends = [action for action in history.corporate_actions if isinstance(action, CashDividend)]
    assert [(item.instrument_id, item.ex_date, item.numerator) for item in splits] == [("S", date(2025, 3, 3), 4)]
    assert len(dividends) == 2
    assert all(get_calendar("XNYS").is_business_day(item.ex_date) for item in dividends)
    assert dividends[0].pay_date is not None and dividends[0].pay_date > dividends[0].ex_date


def test_the_split_moves_the_quoted_price_by_the_ratio(market: SyntheticMarket):
    history = market.generate(START, END)
    raw = history.raw_series("S")
    before = raw.as_of(date(2025, 2, 28))
    after = raw[date(2025, 3, 3)]
    assert before is not None
    assert float(after / before.value) == pytest.approx(0.25, rel=0.2)


def test_economic_value_ignores_the_split_and_reinvests_dividends(market: SyntheticMarket):
    history = market.generate(START, END)
    economic = history.economic_value["S"]
    log_moves = np.diff(np.log(economic.floats()))
    assert float(np.abs(log_moves).max()) < 0.5  # no -75% day
    assert economic.first.value == Decimal("400.00000000")


def test_bid_and_ask_straddle_the_close(market: SyntheticMarket):
    for quote in market.generate(START, END).dataset.for_instrument("A")[:200]:
        assert quote.bid is not None and quote.ask is not None
        assert quote.bid < quote.ask
        assert quote.bid <= quote.close <= quote.ask
        assert quote.volume is not None and quote.volume > 0


def test_fx_trades_every_weekday_and_crosses_close_the_triangle(market: SyntheticMarket):
    history = market.generate(START, END)
    eurusd = history.dataset.fx_series("EURUSD")
    assert eurusd.days == tuple(weekdays(START, END))
    legs = [rate for items in history.dataset.fx.values() for rate in items]
    (first, *_) = cross_rates(legs, "EUR", "GBP")
    implied = history.dataset.fx_series("EURUSD")[first.day] / history.dataset.fx_series("GBPUSD")[first.day]
    assert float(first.rate) == pytest.approx(float(implied), rel=1e-6)
    jpy = cross_rates(legs, "GBP", "JPY")
    assert jpy and jpy[0].pair == "GBPJPY"


def test_the_market_satisfies_the_provider_contract(market: SyntheticMarket):
    assert isinstance(market, MarketDataProvider)
    dataset = load(market, ["A", "L"], START, END, pairs=["EURUSD"])
    assert dataset.instruments == ("A", "L")
    assert dataset.pairs == ("EURUSD",)
    with pytest.raises(ValidationError, match="no specification"):
        market.quotes(["NOPE"], START, END)


def test_specification_validation():
    with pytest.raises(ValidationError):
        InstrumentSpec("X", initial_price=0)
    with pytest.raises(ValidationError):
        InstrumentSpec("X", annual_vol=5.0)
    with pytest.raises(ValidationError):
        InstrumentSpec("X", tail_dof=2.0)
    with pytest.raises(ValidationError, match="stationary"):
        SyntheticMarket([InstrumentSpec("X")], garch_alpha=0.2, garch_beta=0.85)
    with pytest.raises(ValidationError, match="unique"):
        SyntheticMarket([InstrumentSpec("X"), InstrumentSpec("X")])
    with pytest.raises(ValidationError, match="against USD"):
        SyntheticMarket([InstrumentSpec("X")], [FxSpec("EUR", "GBP", 0.85)]).generate(START, END)


def test_the_demo_market_covers_the_book():
    history = demo_market().generate(date(2024, 4, 1), date(2024, 12, 31))
    assert {"US-AAPL", "GB-BAE", "DE-BAYN", "CH-ROG", "DEMO-SPLIT"} <= set(history.dataset.instruments)
    assert {"EURUSD", "GBPUSD", "USDCHF", "USDJPY"} == set(history.dataset.pairs)
