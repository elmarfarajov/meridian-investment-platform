"""Exchange-rate quality on real ECB data: regimes, lifecycles, resolution, and the events behind the findings."""

from datetime import date, time, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest

from meridian.marketdata.fx_reference import SOURCES, ecb_cross, ecb_rates, fed_rates
from meridian.marketdata.golden import FixingTime, GoldenPrice, PricingPolicy, choose_price
from meridian.marketdata.quotes import Quote
from meridian.marketdata.series import TimeSeries
from meridian.quality.context import SeriesContext
from meridian.quality.fx_regimes import MARKET_EVENTS, PegBand, fx_context, managed_days, review
from meridian.quality.rules import RobustOutlier, StaleMark
from meridian.refdata.currency_regimes import ENDINGS, REGIMES, EndReason, ending_for, inactive_spans, regime_on
from meridian.services.fx_review import fx_quality_review, source_comparison


# ---------------------------------------------------------------------------- the packaged data
def test_the_ecb_file_covers_every_currency_since_1999():
    rates = ecb_rates()
    assert len(rates) == 41
    assert rates["EURUSD"].first.day == date(1999, 1, 4)
    assert rates["EURUSD"][date(2008, 7, 15)] == Decimal("1.5990")  # the euro's all-time high fixing
    assert "European Central Bank" in SOURCES["ecb"] and "FRED" in SOURCES["fed"]


def test_the_fed_noon_rates_are_keyed_by_market_convention():
    fed = fed_rates()
    assert set(fed) == {"EURUSD", "GBPUSD", "USDCHF", "USDJPY"}
    assert fed["GBPUSD"].first.day == date(1971, 1, 4)


def test_a_cross_is_derived_from_two_ecb_fixings():
    cross = ecb_cross("USD", "JPY")
    day = date(2026, 9, 30)
    rates = ecb_rates()
    assert cross[day] == rates["EURJPY"][day] / rates["EURUSD"][day]


# ---------------------------------------------------------------------------- regimes and lifecycles
@pytest.mark.parametrize("ending", ENDINGS, ids=lambda item: item.currency)
def test_each_ending_is_the_last_fixing_in_the_data(ending):
    series = ecb_rates()[f"EUR{ending.currency}"]
    if ending.resumed:
        assert ending.last_fixing in series and ending.resumed in series
        assert not [day for day in series.days if ending.last_fixing < day < ending.resumed]
    else:
        assert series.last.day == ending.last_fixing


@pytest.mark.parametrize(
    "ending", [item for item in ENDINGS if item.reason is EndReason.EURO and item.currency != "HRK"], ids=str
)
def test_a_currency_that_joined_the_euro_ended_on_its_conversion_rate(ending):
    last = ecb_rates()[f"EUR{ending.currency}"].last.value
    assert abs(float(last / ending.conversion_rate) - 1) < 0.0005


@pytest.mark.parametrize(
    "regime", [item for item in REGIMES if item.central is not None and item.band is not None], ids=str
)
def test_every_managed_rate_stayed_inside_its_band(regime):
    series = ecb_rates()[f"EUR{regime.currency}"]
    deviations = [regime.deviation(point.value) for point in series if regime.covers(point.day)]
    assert deviations, regime
    assert max(abs(value) for value in deviations if value is not None) <= regime.band + 0.0005


def test_the_regime_in_force_is_the_tightest_one():
    assert regime_on("BGN", date(2022, 1, 3)).kind.value == "currency board"
    assert regime_on("CHF", date(2013, 1, 2)).kind.value == "floor"
    assert regime_on("USD", date(2013, 1, 2)) is None


def test_an_ending_marks_the_days_with_nothing_to_expect():
    assert inactive_spans("CYP") == ((date(2007, 12, 31), None),)
    assert inactive_spans("ISK") == ((date(2008, 12, 9), date(2018, 2, 1)),)
    assert ending_for("USD") is None


def test_statistics_leave_a_managed_rate_alone_and_warm_up_after_a_floor():
    chf = ecb_rates()["EURCHF"]
    excluded = managed_days("CHF", chf.days)
    assert date(2013, 6, 3) in excluded  # under the 1.20 floor
    after = [day for day in chf.days if day > date(2015, 1, 14)]
    assert after[0] in excluded and after[59] in excluded and after[60] not in excluded


# ---------------------------------------------------------------------------- the rules, made aware
def test_a_pegged_rate_is_not_infinitely_surprising_once_resolution_is_known():
    lev = ecb_rates()["EURBGN"]
    context = SeriesContext.from_series("EURBGN", lev, "TARGET")
    blind = RobustOutlier(threshold=10.0, resolution_aware=False).check(context)
    aware = RobustOutlier(threshold=10.0).check(context)
    assert any(abs(finding.score or 0) >= 999 for finding in blind)  # one tick over a MAD of zero
    assert len(aware) < len(blind)


def test_a_coarsely_quoted_rate_is_not_stale_for_repeating_its_rounding():
    krona = ecb_rates()["EURISK"]
    context = SeriesContext.from_series("EURISK", krona, "TARGET")
    assert context.tick_returns[0] < 2e-4  # 1999: two decimals on ~80
    assert context.tick_returns[-1] > 5e-4  # now: one decimal on ~140
    blind = StaleMark(resolution_aware=False).check(context)
    aware = StaleMark().check(context)
    assert len(aware) < len(blind) / 3


def test_the_frozen_krona_of_2008_is_still_caught():
    context = fx_context("EURISK", ecb_rates()["EURISK"])
    stale = [finding for finding in StaleMark().check(context) if finding.day.year == 2008]
    assert any(finding.observed and finding.observed >= 19 for finding in stale)  # 305 for 19 days


def test_the_peg_band_rule_flags_a_rate_outside_its_band():
    days = [date(2022, 1, 3) + timedelta(days=offset) for offset in range(5)]
    rates = [Decimal("1.9558")] * 4 + [Decimal("2.0100")]
    context = SeriesContext.from_series("EURBGN", TimeSeries(zip(days, rates, strict=True)), "WEEKEND")
    findings = PegBand().check(context)
    assert [finding.day for finding in findings] == [days[-1]]
    assert "currency board" in findings[0].message


def test_a_finding_on_the_day_of_the_brexit_vote_is_explained_not_dropped():
    findings = RobustOutlier(threshold=10.0).check(fx_context("EURGBP", ecb_rates()["EURGBP"]))
    on_the_day = [item for item in findings if item.day == date(2016, 6, 24)]
    assert on_the_day
    result = review(on_the_day)["EURGBP"]
    assert result.explained and result.explained[0][1].title == "The Brexit referendum"
    assert not result.open


def test_the_day_the_snb_removed_its_floor_is_not_judged_by_statistics_of_the_floor():
    context = fx_context("EURCHF", ecb_rates()["EURCHF"])
    assert date(2015, 1, 15) in context.managed  # the window still holds the floor's flat fixings
    assert any(event.explains("CHF", date(2015, 1, 15)) for event in MARKET_EVENTS)


def test_every_market_event_names_what_happened():
    assert all(event.title and event.detail for event in MARKET_EVENTS)


# ---------------------------------------------------------------------------- the whole review
@pytest.fixture(scope="module")
def reviewed():
    return fx_quality_review()


def test_each_stage_leaves_fewer_findings_than_the_last(reviewed):
    counts = [stage.open for stage in reviewed.stages]
    assert counts[0] == 1282
    assert all(later <= earlier for earlier, later in pairwise(counts))
    assert counts[-1] < 0.05 * counts[0]


def test_the_review_covers_every_currency_and_day(reviewed):
    assert len(reviewed.pairs) == 41
    assert reviewed.observations > 200_000
    assert reviewed.first == date(1999, 1, 4)


def test_no_open_finding_is_a_lifecycle_gap(reviewed):
    assert not [finding for finding in reviewed.open_findings if finding.rule == "missing_days"]


# ---------------------------------------------------------------------------- two central banks
def test_two_central_banks_fix_the_same_rates_about_18_bp_apart():
    gaps = {gap.pair: gap for gap in source_comparison()}
    assert set(gaps) == {"EURUSD", "GBPUSD", "USDCHF", "USDJPY"}
    for gap in gaps.values():
        assert 10 < gap.median_abs < 30
        assert gap.lead_correlation > 0.4  # the later fix already shows part of tomorrow's move
    assert gaps["EURUSD"].largest(1)[0][0] == date(2016, 3, 10)  # the ECB's easing, between the two fixes
    assert gaps["USDJPY"].largest(1)[0][0] == date(2022, 10, 21)  # the Bank of Japan intervenes


# ---------------------------------------------------------------------------- fixing times in the golden copy
ECB_FIX = FixingTime(time(14, 15), "Europe/Berlin")
FED_FIX = FixingTime(time(12, 0), "America/New_York")


def test_the_gap_between_fixes_follows_daylight_saving():
    assert FED_FIX.on(date(2026, 1, 15)) - ECB_FIX.on(date(2026, 1, 15)) == timedelta(hours=3, minutes=45)
    assert FED_FIX.on(date(2026, 3, 10)) - ECB_FIX.on(date(2026, 3, 10)) == timedelta(hours=2, minutes=45)


def test_a_source_fixed_hours_apart_is_set_aside_not_counted_as_disagreeing():
    day = date(2016, 3, 10)
    quotes = [
        Quote(instrument_id="EURUSD", day=day, close=Decimal("1.0970"), currency="USD", source="ecb"),
        Quote(instrument_id="EURUSD", day=day, close=Decimal("1.1278"), currency="USD", source="fed"),
    ]
    policy = PricingPolicy(("ecb", "fed"), fixing_times=(("ecb", ECB_FIX), ("fed", FED_FIX)))
    price = choose_price("EURUSD", day, quotes, policy)
    assert isinstance(price, GoldenPrice)
    assert price.source == "ecb" and not price.challenged
    assert any("fixed at 12:00 New York" in reason for _, reason in price.excluded)
    blind = choose_price("EURUSD", day, quotes, PricingPolicy(("ecb", "fed")))
    assert not isinstance(blind, GoldenPrice)  # 280 bp apart: no consensus, nothing published
