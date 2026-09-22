"""The end-of-day pricing run, from sources to published golden prices."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import numpy as np
import pytest

from meridian.marketdata.golden import GoldenMethod, PricingPolicy, compare_to_reference
from meridian.marketdata.providers import FaultKind, InstrumentSpec, StaticProvider, SyntheticMarket
from meridian.persistence import UnitOfWork, seed_reference_data
from meridian.quality import evaluate
from meridian.seed import demo_book
from meridian.services import (
    SHOWCASE_FAULTS,
    EndOfDayPricing,
    build_demo_market,
    demo_reference_data,
    demo_vendor_dataset,
    run_demo_pricing,
)


@pytest.fixture(scope="module")
def market():
    return build_demo_market()


@pytest.fixture(scope="module")
def result(market):
    return run_demo_pricing(market)


def test_the_showcase_faults_are_all_planted(market):
    assert len(market.faults) == len(SHOWCASE_FAULTS)
    assert {fault.kind for fault in market.faults} == {spec.kind for spec in SHOWCASE_FAULTS}
    assert set(market.clean.pairs) >= {"EURGBP", "EURCHF", "GBPJPY"}


def test_every_fault_in_the_exchange_feed_is_caught(market, result):
    exchange = [item for item in result.report.findings if item.source in {"exchange", ""}]
    score = evaluate(exchange, market.faults)
    assert score.missed == []
    assert score.recall == 1.0


def test_the_golden_copy_is_closer_to_the_truth_than_any_vendor(market, result):
    errors = compare_to_reference(result.golden, market.clean, demo_vendor_dataset(market))
    mean = {name: float(np.mean(np.abs(values))) for name, values in errors.items()}
    assert mean["golden"] < 1.0
    assert all(mean["golden"] < mean[name] for name in ("exchange", "vendor-b", "evaluated"))


def test_no_faulty_exchange_print_reaches_the_golden_copy(market, result):
    truth = {(quote.instrument_id, quote.day): quote.close for items in market.clean.quotes.values() for quote in items}
    for fault in market.faults:
        if fault.kind in {FaultKind.FX_TRIANGLE_BREAK, FaultKind.HOLIDAY_PRINT, FaultKind.MISSING_RUN}:
            continue
        for price in result.golden.prices:
            if price.instrument_id == fault.key and fault.start <= price.day <= fault.end:
                actual = truth[(price.instrument_id, price.day)]
                assert abs(float(price.value / actual) - 1) < 0.01, (fault, price)


def test_the_run_summary(result):
    summary = dict(result.summary())
    assert summary["run"] == result.run_id
    assert set(result.sources) >= {"exchange", "vendor-b", "evaluated"}
    assert result.challenges > 0
    assert "0 observations" in summary["written to the database"]  # a dry run writes nothing


def test_a_persisted_run_writes_observations_prices_fx_and_findings(unit_of_work: UnitOfWork, market):
    book = demo_book()
    seed_reference_data(
        unit_of_work,
        instruments=book.instruments,
        benchmarks=book.benchmarks,
        clients=book.clients,
        households=book.households,
        accounts=book.accounts,
        portfolios=book.portfolios,
    )
    persisted = run_demo_pricing(market, unit_of_work=unit_of_work)
    assert persisted.observations_recorded == len(persisted.dataset) - sum(
        len(items) for items in persisted.dataset.fx.values()
    )
    assert persisted.prices_published == len(persisted.golden)
    assert persisted.fx_published > 4000
    assert unit_of_work.prices.latest("US-AAPL", date(2026, 9, 18)) is not None
    stored = unit_of_work.quality.findings(persisted.run_id)
    assert len(stored) == len({finding.identifier for finding in persisted.report.findings})
    run = unit_of_work.quality.latest_run()
    assert run is not None and run.overall_score == pytest.approx(persisted.report.overall)


def test_a_custom_pipeline_over_static_providers(unit_of_work: UnitOfWork, instruments):
    seed_reference_data(unit_of_work, instruments=instruments)
    history = SyntheticMarket([InstrumentSpec("AAPL"), InstrumentSpec("MSFT", initial_price=400.0)], seed=4).generate(
        date(2026, 1, 2), date(2026, 3, 31)
    )
    quotes = [quote for items in history.dataset.quotes.values() for quote in items]
    backup = [quote.with_close(quote.close * Decimal("1.0001"), source="backup") for quote in quotes]
    pricing = EndOfDayPricing(
        [StaticProvider("synthetic", quotes), StaticProvider("backup", backup)],
        PricingPolicy(ranking=("synthetic", "backup"), method=GoldenMethod.MEDIAN),
    )
    outcome = pricing.run(
        ["AAPL", "MSFT"],
        date(2026, 1, 2),
        date(2026, 3, 31),
        calendars={"AAPL": "XNYS", "MSFT": "XNYS"},
        unit_of_work=unit_of_work,
        received_at=datetime(2026, 3, 31, 22, tzinfo=timezone.utc),
        run_id="custom",
    )
    assert outcome.run_id == "custom"
    assert outcome.observations_recorded == 2 * len(quotes)
    assert {price.source for price in outcome.golden.prices} == {"median"}
    assert unit_of_work.observations.count("AAPL") == 2 * len(history.dataset.for_instrument("AAPL"))


def test_demo_reference_data_describes_every_instrument_in_the_book():
    reference = demo_reference_data()
    for instrument in demo_book().instruments:
        assert reference.entries(instrument.instrument_id), instrument.instrument_id
    assert reference.resolve("ticker", "FB", date(2021, 1, 4)) == "US-META"


def test_a_backfilled_load_is_known_on_each_evening(unit_of_work: UnitOfWork, instruments):
    seed_reference_data(unit_of_work, instruments=instruments)
    history = SyntheticMarket([InstrumentSpec("AAPL")], seed=2).generate(date(2026, 3, 2), date(2026, 3, 13))
    quotes = history.dataset.for_instrument("AAPL")
    assert unit_of_work.observations.record_backfill(quotes) == len(quotes)
    evening = datetime(2026, 3, 5, 23, tzinfo=timezone.utc)
    known = unit_of_work.observations.as_known_at("AAPL", evening)
    assert known.last.day == date(2026, 3, 5)
