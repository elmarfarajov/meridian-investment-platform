"""Each quality rule catches what it is for and stays quiet about what it is not."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from meridian.core.calendars import get_calendar
from meridian.domain.corporate_actions import dividend, split
from meridian.marketdata.quotes import Quote
from meridian.quality.context import SeriesContext
from meridian.quality.findings import Dimension, Finding, Severity
from meridian.quality.rules import (
    CloseOutsideQuote,
    CrossedQuote,
    LateMark,
    MissingDays,
    NonPositivePrice,
    NonTradingDayPrint,
    RobustOutlier,
    SpikeReversal,
    StaleMark,
    UnexplainedJump,
    WideSpread,
    default_rules,
    rule_catalogue,
)

NYSE = get_calendar("XNYS")
START = date(2025, 1, 2)


def trading_days(count: int, start: date = START) -> list[date]:
    days = list(NYSE.business_days(start, start + timedelta(days=count * 2)))
    return days[:count]


def walk(count: int = 120, *, seed: int = 1, start_price: float = 100.0, vol: float = 0.012) -> list[Decimal]:
    rng = np.random.default_rng(seed)
    prices = start_price * np.exp(np.cumsum(rng.normal(0, vol, count)))
    return [Decimal(f"{price:.2f}") for price in prices]


def context(prices: list[Decimal], days: list[date] | None = None, **kwargs) -> SeriesContext:
    days = days or trading_days(len(prices))
    quotes = [
        Quote(
            instrument_id="X",
            day=day,
            close=price,
            currency="USD",
            bid=kwargs.get("bids", {}).get(day, price - Decimal("0.02") if price > 0 else None),
            ask=kwargs.get("asks", {}).get(day, price + Decimal("0.02") if price > 0 else None),
        )
        for day, price in zip(days, prices, strict=True)
    ]
    return SeriesContext.build(
        "X", quotes, NYSE, as_of=kwargs.get("as_of", days[-1]), actions=kwargs.get("actions", ())
    )


def rules_fired(findings: list[Finding]) -> set[str]:
    return {finding.rule for finding in findings}


def test_a_clean_random_walk_passes_every_rule():
    ctx = context(walk(250, seed=11))
    findings = [finding for rule in default_rules() for finding in rule.check(ctx)]
    assert findings == []


# ---------------------------------------------------------------------------- validity
def test_non_positive_price_is_critical():
    prices = walk(40)
    prices[20] = Decimal(0)
    (finding,) = NonPositivePrice().check(context(prices))
    assert finding.severity is Severity.CRITICAL
    assert finding.dimension is Dimension.VALIDITY
    assert finding.day == trading_days(40)[20]


def test_a_print_on_a_holiday_names_the_holiday():
    days = trading_days(30)
    days[10] = date(2025, 1, 20)  # Martin Luther King Jr. Day
    days.sort()
    (finding,) = NonTradingDayPrint().check(context(walk(30), days))
    assert finding.day == date(2025, 1, 20)
    assert "Martin Luther King" in finding.message


def test_a_print_on_a_weekend_says_so():
    days = trading_days(10)
    days[5] = date(2025, 1, 11)  # a Saturday
    days.sort()
    (finding,) = NonTradingDayPrint().check(context(walk(10), days))
    assert "Saturday" in finding.message


def test_crossed_quote():
    prices = walk(20)
    day = trading_days(20)[7]
    ctx = context(prices, bids={day: prices[7] + 1}, asks={day: prices[7] - 1})
    (finding,) = CrossedQuote().check(ctx)
    assert finding.day == day
    assert finding.observed == pytest.approx(2.0)


# ---------------------------------------------------------------------------- completeness
def test_missing_days_are_grouped_into_runs_on_the_instruments_own_calendar():
    days = trading_days(60)
    kept = days[:10] + days[11:30] + days[34:]
    findings = MissingDays().check(context(walk(len(kept)), kept))
    assert [(item.day, item.last_day, item.severity) for item in findings] == [
        (days[10], days[10], Severity.WARNING),
        (days[30], days[33], Severity.ERROR),
    ]
    assert findings[1].observed == 4


def test_a_holiday_is_not_a_missing_day():
    ctx = context(walk(20))  # the 20 NYSE days skip Martin Luther King Jr. Day
    assert date(2025, 1, 20) not in ctx.days
    assert MissingDays().check(ctx) == []


def test_missing_days_run_up_to_the_valuation_date():
    days = trading_days(20)
    ctx = context(walk(20), days, as_of=NYSE.add_business_days(days[-1], 3))
    (finding,) = MissingDays().check(ctx)
    assert finding.observed == 3


# ---------------------------------------------------------------------------- timeliness
def test_stale_run_is_flagged_once_with_its_span():
    prices = walk(60)
    for index in range(31, 37):
        prices[index] = prices[30]
    (finding,) = StaleMark().check(context(prices))
    days = trading_days(60)
    assert (finding.day, finding.last_day) == (days[31], days[36])
    assert finding.severity is Severity.ERROR
    assert finding.observed == 6


def test_one_unchanged_day_is_not_stale():
    prices = walk(40)
    prices[21] = prices[20]
    assert StaleMark().check(context(prices)) == []


def test_a_short_stale_run_is_a_warning():
    prices = walk(40)
    prices[21] = prices[22] = prices[20]
    (finding,) = StaleMark().check(context(prices))
    assert finding.severity is Severity.WARNING


def test_stale_run_at_the_end_of_the_series_is_still_reported():
    prices = walk(40)
    prices[-3:] = [prices[-4]] * 3
    assert len(StaleMark().check(context(prices))) == 1


def test_late_mark_counts_trading_days_to_the_valuation_date():
    days = trading_days(30)
    late = context(walk(30), days, as_of=NYSE.add_business_days(days[-1], 3))
    (finding,) = LateMark().check(late)
    assert finding.observed == 3
    on_time = context(walk(30), days, as_of=NYSE.add_business_days(days[-1], 1))
    assert LateMark().check(on_time) == []


# ---------------------------------------------------------------------------- accuracy
def test_a_spike_is_caught_by_both_the_outlier_and_the_reversal_rule():
    prices = walk(120)
    prices[80] = prices[80] * Decimal("1.2")
    ctx = context(prices)
    outliers = RobustOutlier().check(ctx)
    reversals = SpikeReversal().check(ctx)
    days = trading_days(120)
    assert days[80] in {item.day for item in outliers}
    assert [item.day for item in reversals] == [days[80]]
    assert "bad tick" in reversals[0].message


def test_a_genuine_move_that_persists_is_not_a_reversal():
    prices = walk(120)
    prices[80:] = [price * Decimal("0.8") for price in prices[80:]]
    assert SpikeReversal().check(context(prices)) == []


def test_outlier_needs_history_before_it_judges():
    prices = walk(30)
    prices[5] = prices[5] * 2
    assert RobustOutlier(min_periods=20).check(context(prices)) == []


def test_a_recorded_split_is_not_an_outlier():
    prices = walk(120)
    prices[70:] = [(price / 4).quantize(Decimal("0.01")) for price in prices[70:]]
    event = split("S", "X", trading_days(120)[70], 4)
    ctx = context(prices, actions=[event])
    assert RobustOutlier().check(ctx) == []
    assert UnexplainedJump().check(ctx) == []


def test_wide_spread():
    prices = walk(40)
    day = trading_days(40)[25]
    ctx = context(prices, bids={day: prices[25] - 2}, asks={day: prices[25] + 2})
    (finding,) = WideSpread().check(ctx)
    assert finding.day == day
    assert finding.observed is not None and finding.observed > 300


# ---------------------------------------------------------------------------- consistency
@pytest.mark.parametrize(
    ("factor", "label"),
    [
        (Decimal("0.5"), "2-for-1 split"),
        (Decimal(1) / 3, "3-for-1 split"),
        (Decimal(10), "1-for-10 reverse split"),
        (Decimal(100), "unit error"),
    ],
)
def test_unexplained_jumps_are_labelled_with_their_likely_cause(factor: Decimal, label: str):
    prices = walk(60)
    prices[40:] = [(price * factor).quantize(Decimal("0.01")) for price in prices[40:]]
    findings = UnexplainedJump().check(context(prices))
    assert findings, label
    assert label in findings[0].message
    assert findings[0].day == trading_days(60)[40]


def test_an_ordinary_large_move_is_not_a_split():
    prices = walk(60)
    prices[40:] = [price * Decimal("0.88") for price in prices[40:]]
    assert UnexplainedJump().check(context(prices)) == []


def test_an_event_on_file_whose_price_did_not_move_is_questioned():
    prices = walk(60)
    event = split("S", "X", trading_days(60)[30], 2)
    (finding,) = UnexplainedJump().check(context(prices, actions=[event]))
    assert finding.severity is Severity.WARNING
    assert "ex-date" in finding.message


def test_a_dividend_does_not_upset_the_jump_rule():
    prices = walk(60)
    event = dividend("D", "X", trading_days(60)[30], "0.50", "USD")
    assert UnexplainedJump().check(context(prices, actions=[event])) == []


def test_close_outside_its_own_quote():
    prices = walk(40)
    day = trading_days(40)[15]
    ctx = context(prices, bids={day: prices[15] * Decimal("0.9")}, asks={day: prices[15] * Decimal("0.91")})
    (finding,) = CloseOutsideQuote().check(ctx)
    assert finding.day == day
    assert finding.dimension is Dimension.CONSISTENCY


def test_the_catalogue_describes_every_default_rule():
    catalogue = rule_catalogue()
    assert len(catalogue) == len(default_rules()) == 11
    assert all(name and dimension and description for name, dimension, description in catalogue)
    assert len({name for name, _, _ in catalogue}) == 11


def test_findings_have_stable_identifiers():
    prices = walk(40)
    prices[20] = Decimal(0)
    first = NonPositivePrice().check(context(prices))
    second = NonPositivePrice().check(context(prices))
    assert first[0].identifier == second[0].identifier
    assert str(first[0]).startswith("[critical] X")
