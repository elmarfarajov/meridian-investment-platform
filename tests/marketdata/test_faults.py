"""The fault injector damages data in exactly the ways it reports, and nowhere else."""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from meridian.core.calendars import get_calendar
from meridian.core.exceptions import ValidationError
from meridian.marketdata.providers import (
    FaultInjector,
    FaultKind,
    FaultSpec,
    FxSpec,
    InjectedFault,
    InstrumentSpec,
    SyntheticMarket,
    cross_rates,
)
from meridian.marketdata.quotes import MarketDataset

START, END = date(2025, 1, 2), date(2025, 12, 31)


@pytest.fixture(scope="module")
def clean() -> MarketDataset:
    market = SyntheticMarket(
        [InstrumentSpec("A", calendar="XNYS"), InstrumentSpec("B", calendar="XNYS", initial_price=40.0)],
        [FxSpec("EUR", "USD", 1.1), FxSpec("GBP", "USD", 1.3)],
        seed=9,
    )
    dataset = market.generate(START, END).dataset
    legs = [rate for items in dataset.fx.values() for rate in items]
    return MarketDataset.from_records(
        (quote for items in dataset.quotes.values() for quote in items), legs + cross_rates(legs, "EUR", "GBP")
    )


def damage(clean: MarketDataset, *specs: FaultSpec):
    return FaultInjector(list(specs)).apply(clean, {"A": "XNYS", "B": "XNYS"})


def test_a_stale_run_repeats_the_previous_close(clean: MarketDataset):
    damaged, (fault,) = damage(clean, FaultSpec(FaultKind.STALE_RUN, "A", 50, length=4))
    closes = [quote.close for quote in damaged.for_instrument("A")[49:54]]
    assert len(set(closes)) == 1
    assert fault.kind is FaultKind.STALE_RUN
    assert (fault.end - fault.start).days >= 3


def test_a_spike_changes_one_close_and_leaves_its_neighbours(clean: MarketDataset):
    damaged, (fault,) = damage(clean, FaultSpec(FaultKind.SPIKE, "A", 80, magnitude=0.2))
    before, after = clean.for_instrument("A"), damaged.for_instrument("A")
    changed = [index for index, (x, y) in enumerate(zip(before, after, strict=True)) if x.close != y.close]
    assert changed == [80]
    ratio = after[80].close / before[80].close
    assert abs(float(ratio) - 1) == pytest.approx(0.2, abs=0.001)
    assert fault.start == fault.end == before[80].day


def test_a_missing_run_removes_trading_days(clean: MarketDataset):
    damaged, (fault,) = damage(clean, FaultSpec(FaultKind.MISSING_RUN, "B", 100, length=3))
    assert len(damaged.for_instrument("B")) == len(clean.for_instrument("B")) - 3
    missing = {quote.day for quote in clean.for_instrument("B")} - {quote.day for quote in damaged.for_instrument("B")}
    assert min(missing) == fault.start and max(missing) == fault.end


def test_an_unrecorded_split_divides_everything_after_it(clean: MarketDataset):
    damaged, _ = damage(clean, FaultSpec(FaultKind.UNRECORDED_SPLIT, "A", 120, magnitude=4.0))
    before, after = clean.for_instrument("A"), damaged.for_instrument("A")
    assert after[119].close == before[119].close
    assert float(after[200].close) == pytest.approx(float(before[200].close) / 4, abs=0.01)


def test_a_unit_error_is_a_hundredfold_run_that_ends(clean: MarketDataset):
    damaged, _ = damage(clean, FaultSpec(FaultKind.UNIT_ERROR, "A", 60, length=2))
    before, after = clean.for_instrument("A"), damaged.for_instrument("A")
    assert after[60].close == before[60].close * 100
    assert after[62].close == before[62].close


def test_crossed_holiday_and_zero(clean: MarketDataset):
    damaged, faults = damage(
        clean,
        FaultSpec(FaultKind.CROSSED_QUOTE, "A", 40),
        FaultSpec(FaultKind.HOLIDAY_PRINT, "B", 40),
        FaultSpec(FaultKind.NON_POSITIVE, "B", 90),
    )
    assert damaged.for_instrument("A")[40].is_crossed
    holiday = next(fault for fault in faults if fault.kind is FaultKind.HOLIDAY_PRINT)
    assert not get_calendar("XNYS").is_business_day(holiday.start)
    assert holiday.start in damaged.close_series("B")
    assert any(quote.close == 0 for quote in damaged.for_instrument("B"))


def test_a_triangle_break_moves_only_the_cross(clean: MarketDataset):
    damaged, (fault,) = damage(clean, FaultSpec(FaultKind.FX_TRIANGLE_BREAK, "EURGBP", 30, magnitude=0.005))
    before = clean.fx_series("EURGBP")[fault.start]
    after = damaged.fx_series("EURGBP")[fault.start]
    assert float(after / before) == pytest.approx(1.005, abs=1e-5)
    assert damaged.fx_series("EURUSD") == clean.fx_series("EURUSD")


def test_the_original_dataset_is_never_modified(clean: MarketDataset):
    snapshot = clean.close_series("A")
    damage(clean, FaultSpec(FaultKind.SPIKE, "A", 50), FaultSpec(FaultKind.MISSING_RUN, "A", 150))
    assert clean.close_series("A") == snapshot


def test_several_faults_in_one_series_keep_their_positions(clean: MarketDataset):
    _, faults = damage(clean, FaultSpec(FaultKind.MISSING_RUN, "A", 30, length=5), FaultSpec(FaultKind.SPIKE, "A", 100))
    spike = next(fault for fault in faults if fault.kind is FaultKind.SPIKE)
    assert spike.start == clean.for_instrument("A")[100].day  # applied before the earlier deletion


def test_random_plan_is_reproducible_and_spaced(clean: MarketDataset):
    first = FaultInjector.random_plan(clean, per_instrument=4, fx_pairs=["EURGBP"], seed=5)
    second = FaultInjector.random_plan(clean, per_instrument=4, fx_pairs=["EURGBP"], seed=5)
    assert first.specs == second.specs
    for key in ("A", "B"):
        positions = sorted(spec.index for spec in first.specs if spec.key == key)
        assert positions[0] >= 30
        assert all(later - earlier >= 6 for earlier, later in itertools.pairwise(positions))
    assert any(spec.kind is FaultKind.FX_TRIANGLE_BREAK for spec in first.specs)


def test_bad_specifications_are_refused(clean: MarketDataset):
    with pytest.raises(ValidationError, match="outside"):
        damage(clean, FaultSpec(FaultKind.SPIKE, "A", 10_000))
    with pytest.raises(ValidationError, match="no quotes"):
        damage(clean, FaultSpec(FaultKind.SPIKE, "Z", 10))
    with pytest.raises(ValidationError, match="no FX"):
        damage(clean, FaultSpec(FaultKind.FX_TRIANGLE_BREAK, "USDXYZ", 10))


def test_an_empty_plan_changes_nothing(clean: MarketDataset):
    damaged, faults = FaultInjector([]).apply(clean, {})
    assert faults == []
    assert damaged.close_series("A") == clean.close_series("A")


def test_injected_fault_overlap_with_slack():
    fault = InjectedFault(FaultKind.SPIKE, "A", date(2025, 3, 3), date(2025, 3, 3), "")
    assert fault.overlaps(date(2025, 3, 4), date(2025, 3, 4), slack_days=1)
    assert not fault.overlaps(date(2025, 3, 6), date(2025, 3, 6), slack_days=1)
