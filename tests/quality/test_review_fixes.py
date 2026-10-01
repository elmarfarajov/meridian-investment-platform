"""Faults found by reading the Day 2 code again, each pinned by the case that exposed it."""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
from scipy.stats import median_abs_deviation

from meridian.core.currency import quote_unit
from meridian.core.exceptions import ValidationError
from meridian.domain.corporate_actions import CashDividend, StockSplit
from meridian.marketdata.adjustments import adjust_history, in_price_units
from meridian.marketdata.quotes import Quote
from meridian.marketdata.series import TimeSeries
from meridian.quality.context import SeriesContext
from meridian.quality.engine import attach_market_proxy
from meridian.quality.robust import MAD_SCALE, mad
from meridian.quality.rules import RobustOutlier, UnexplainedJump

D = Decimal


def _weekdays(start: date, count: int) -> list[date]:
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------- the pence trap
def test_quote_units_know_their_currency_and_divisor():
    assert quote_unit("GBp").currency == "GBP" and quote_unit("GBX").divisor == 100
    assert quote_unit("ZAc").to_currency(D(1250)) == D("12.5")
    assert quote_unit("usd").divisor == 1


def test_a_sterling_dividend_on_a_pence_price_is_sized_in_pence():
    dividend = CashDividend(action_id="BA-1", instrument_id="GB-BAE", ex_date=date(2026, 4, 23), amount=D("0.198"),
                            currency="GBP")  # fmt: skip
    restated = in_price_units(dividend, "GBX")
    assert restated.amount == D("19.800") and restated.currency == "GBX"
    # a 1.02% payout; read naively against pence it would be 0.01%
    assert float(restated.price_factor(D(1950))) == pytest.approx(1 - 19.8 / 1950)
    assert float(dividend.price_factor(D(1950))) > 0.9998


def test_a_dollar_dividend_on_a_pence_price_needs_an_exchange_rate():
    dividend = CashDividend(action_id="SHEL-1", instrument_id="GB-SHEL", ex_date=date(2026, 5, 14), amount=D("0.358"),
                            currency="USD")  # fmt: skip
    with pytest.raises(ValidationError, match="needs an exchange rate"):
        in_price_units(dividend, "GBX")
    restated = in_price_units(dividend, "GBX", lambda base, quote, day: D("0.80"))
    assert restated.amount == D("28.64000")  # 0.358 USD x 0.80 GBP/USD x 100 pence


def test_the_adjusted_history_of_a_pence_share_is_not_moved_a_hundred_times_too_little():
    days = _weekdays(date(2026, 4, 1), 30)
    series = TimeSeries([(day, D(1950)) for day in days], name="GB-BAE")
    dividend = CashDividend(action_id="BA-1", instrument_id="GB-BAE", ex_date=days[15], amount=D("0.198"),
                            currency="GBP")  # fmt: skip
    adjusted = adjust_history(series, [dividend], price_unit="GBX")
    assert float(adjusted[days[0]]) == pytest.approx(1950 - 19.8)


# ---------------------------------------------------------------------------- events on days without a print
def _context_with_a_split_on_a_missing_day() -> tuple[SeriesContext, date]:
    rng = np.random.default_rng(4)
    days = _weekdays(date(2026, 1, 5), 120)
    split_day = days[80]
    quotes, price = [], 400.0
    for day in days:
        price *= float(np.exp(rng.normal(0, 0.01)))
        if day == split_day:
            continue  # the feed has no print on the ex-date
        shown = price / 4 if day > split_day else price
        quotes.append(Quote(instrument_id="X", day=day, close=D(f"{shown:.2f}"), currency="USD"))
    split = StockSplit(action_id="X-SPLIT", instrument_id="X", ex_date=split_day, numerator=4)
    return SeriesContext.build("X", quotes, "WEEKEND", actions=[split]), split_day


def test_a_split_whose_ex_date_has_no_print_is_still_divided_out():
    context, split_day = _context_with_a_split_on_a_missing_day()
    after = next(day for day, _ in context.adjusted_returns if day > split_day)
    value = dict(context.adjusted_returns)[after]
    assert abs(value) < 0.1  # two days of ordinary noise, not log(1/4)
    assert RobustOutlier().check(context) == []
    assert UnexplainedJump().check(context) == []


# ---------------------------------------------------------------------------- gaps against the market
def test_a_return_over_a_gap_is_set_against_the_market_over_the_whole_gap():
    days = _weekdays(date(2026, 3, 2), 10)
    market_move = 0.02
    contexts = []
    for name in ("A", "B", "C", "D", "E"):
        price, quotes = 100.0, []
        for day in days:
            price *= float(np.exp(market_move))
            if name == "A" and day in (days[4], days[5]):
                continue  # A misses two prints; its next return spans three sessions
            quotes.append(Quote(instrument_id=name, day=day, close=D(f"{price:.6f}"), currency="USD"))
        contexts.append(SeriesContext.build(name, quotes, "WEEKEND"))
    attach_market_proxy(contexts)
    gap = dict(contexts[0].residual_returns)[days[6]]
    assert gap == pytest.approx(0.0, abs=1e-6)  # three days of market, not one


# ---------------------------------------------------------------------------- the MAD constant
def test_the_mad_scale_is_exact_and_agrees_with_scipy():
    sample = np.random.default_rng(1).standard_t(4, 2_000)
    assert pytest.approx(1.482602218505602, abs=1e-15) == MAD_SCALE
    assert mad(sample) == pytest.approx(median_abs_deviation(sample, scale="normal"), abs=1e-15)
