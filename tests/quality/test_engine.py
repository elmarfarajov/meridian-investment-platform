"""The engine, the FX rules and the measurement of the rules against planted faults."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from meridian.marketdata.providers import (
    FaultInjector,
    FaultKind,
    FaultSpec,
    FxSpec,
    InstrumentSpec,
    SyntheticMarket,
    cross_rates,
)
from meridian.marketdata.quotes import FxQuote, MarketDataset
from meridian.marketdata.series import TimeSeries
from meridian.quality import (
    EXPECTED_RULES,
    Dimension,
    FxInverseRule,
    FxTriangleRule,
    QualityEngine,
    Severity,
    evaluate,
    find_triangles,
    run_quality,
    series_report,
)

START, END = date(2024, 6, 3), date(2025, 12, 31)
CALENDARS = {"A": "XNYS", "B": "XNYS", "C": "XLON", "D": "TARGET", "E": "XNYS"}


@pytest.fixture(scope="module")
def market():
    specs = [
        InstrumentSpec("A", sector="Tech"),
        InstrumentSpec("B", sector="Tech", initial_price=40.0, splits=((date(2025, 3, 3), 3, 1),)),
        InstrumentSpec("C", "GBP", "XLON", 12.0, 0.2, sector="Industrials", price_places=3),
        InstrumentSpec("D", "EUR", "TARGET", 60.0, 0.22, sector="Industrials"),
        InstrumentSpec("E", sector="Health", initial_price=150.0, annual_vol=0.18),
    ]
    history = SyntheticMarket(specs, [FxSpec("EUR", "USD", 1.1), FxSpec("GBP", "USD", 1.3)], seed=5).generate(
        START, END
    )
    legs = [rate for items in history.dataset.fx.values() for rate in items]
    dataset = MarketDataset.from_records(
        (quote for items in history.dataset.quotes.values() for quote in items),
        legs + cross_rates(legs, "EUR", "GBP"),
    )
    return history, dataset


def test_clean_data_scores_near_perfect(market):
    history, dataset = market
    report = QualityEngine().run(dataset, calendars=CALENDARS, actions=history.corporate_actions)
    assert report.overall > 0.995
    assert len(report.blocking()) <= 3  # genuine fat-tail days, not faults
    assert {score.key for score in report.scores} == {"A", "B", "C", "D", "E", "EURUSD", "GBPUSD", "EURGBP"}
    assert report.fx_residuals["EURGBP"]
    assert max(abs(gap) for _, gap in report.fx_residuals["EURGBP"]) < 0.1


def test_every_planted_fault_is_found(market):
    history, dataset = market
    plan = FaultInjector.random_plan(dataset, per_instrument=5, fx_pairs=["EURGBP"], fx_breaks=2, seed=8)
    damaged, faults = plan.apply(dataset, CALENDARS)
    report = QualityEngine().run(damaged, calendars=CALENDARS, actions=history.corporate_actions)
    score = evaluate(report.findings, faults)
    assert score.planted == len(faults) >= 20
    assert score.missed == []
    assert score.recall == 1.0
    assert score.precision > 0.8
    assert score.f1 > 0.9
    assert all(item.recall == 1.0 for item in score.kinds)


def test_the_recorded_split_is_not_reported(market):
    history, dataset = market
    report = QualityEngine().run(dataset, calendars=CALENDARS, actions=history.corporate_actions)
    split_day = date(2025, 3, 3)
    assert not [item for item in report.for_key("B") if item.day == split_day]
    without_the_event = QualityEngine().run(dataset, calendars=CALENDARS, actions=())
    flagged = {item.rule for item in without_the_event.for_key("B") if item.day == split_day}
    assert "unexplained_jump" in flagged  # the same move, with nobody having loaded the event


def test_scores_fall_on_the_dimension_that_was_damaged(market):
    history, dataset = market
    damaged, _ = FaultInjector([FaultSpec(FaultKind.MISSING_RUN, "A", 100, length=12)]).apply(dataset, CALENDARS)
    report = QualityEngine().run(damaged, calendars=CALENDARS, actions=history.corporate_actions)
    score = report.score("A")
    assert score.dimensions[Dimension.COMPLETENESS] < 0.99
    assert score.dimensions[Dimension.VALIDITY] == 1.0
    assert score.coverage < 1.0
    assert score.status in {"amber", "red"}


def test_a_critical_finding_turns_the_light_red(market):
    history, dataset = market
    damaged, _ = FaultInjector([FaultSpec(FaultKind.NON_POSITIVE, "E", 60)]).apply(dataset, CALENDARS)
    report = QualityEngine().run(damaged, calendars=CALENDARS, actions=history.corporate_actions)
    assert report.score("E").status == "red"
    assert report.by_severity()[Severity.CRITICAL] == 1


def test_blocked_points_are_per_source_and_cover_runs(market):
    history, dataset = market
    damaged, (fault,) = FaultInjector([FaultSpec(FaultKind.STALE_RUN, "A", 90, length=5)]).apply(dataset, CALENDARS)
    report = QualityEngine().run(damaged, calendars=CALENDARS, actions=history.corporate_actions)
    blocked = {(key, day) for key, source, day in report.blocked_points() if source == "synthetic"}
    assert {("A", day) for day in report.expected_days["A"] if fault.start <= day <= fault.end} <= blocked


def test_summaries(market):
    history, dataset = market
    report = QualityEngine().run(dataset, calendars=CALENDARS, actions=history.corporate_actions, run_id="r1")
    assert report.run_id == "r1"
    assert set(report.by_dimension()) == set(Dimension)
    assert sum(report.by_rule().values()) == len(report.findings)
    assert len(report.summary_rows()) == len(report.scores)
    for rule, counts in report.by_rule_and_severity().items():
        assert sum(counts.values()) == report.by_rule()[rule]
    with pytest.raises(KeyError):
        report.score("NOPE")


def test_the_market_proxy_can_be_switched_off(market):
    history, dataset = market
    with_proxy = QualityEngine().run(dataset, calendars=CALENDARS, actions=history.corporate_actions)
    without = QualityEngine(use_market_proxy=False).run(dataset, calendars=CALENDARS, actions=history.corporate_actions)
    assert len(without.findings) >= len(with_proxy.findings) - 1


def test_convenience_wrappers(market):
    history, dataset = market
    assert run_quality(dataset, CALENDARS, actions=history.corporate_actions).overall > 0.99
    series = dataset.close_series("A")
    broken = series.replace({series.days[50]: series.values[50] * 3})
    assert {item.rule for item in series_report("A", broken)} >= {"robust_outlier"}


# ---------------------------------------------------------------------------- FX rules
def fx(pair: str, day: int, rate: str) -> FxQuote:
    return FxQuote(base=pair[:3], quote=pair[3:], day=date(2026, 3, day), rate=Decimal(rate))


def test_triangles_are_found_through_the_pivot_in_either_direction():
    names = ["EURUSD", "GBPUSD", "EURGBP", "USDJPY", "GBPJPY", "USDCHF"]
    triangles = {item.cross: item for item in find_triangles(names)}
    assert set(triangles) == {"EURGBP", "GBPJPY"}
    assert (triangles["GBPJPY"].base_leg, triangles["GBPJPY"].quote_leg) == ("GBPUSD", "USDJPY")


def test_triangle_rule_measures_the_gap_in_basis_points():
    dataset = MarketDataset.from_records(
        fx=[
            fx("EURUSD", 2, "1.10"),
            fx("GBPUSD", 2, "1.25"),
            fx("EURGBP", 2, "0.88"),  # exactly 1.10 / 1.25
            fx("EURUSD", 3, "1.10"),
            fx("GBPUSD", 3, "1.25"),
            fx("EURGBP", 3, "0.8844"),  # 50 bp rich
        ]
    )
    series = {pair: dataset.fx_series(pair) for pair in dataset.pairs}
    rule = FxTriangleRule(tolerance_bps=2)
    residuals = dict(rule.residuals(series)["EURGBP"])
    assert residuals[date(2026, 3, 2)] == pytest.approx(0.0, abs=1e-9)
    assert residuals[date(2026, 3, 3)] == pytest.approx(50.0, abs=0.01)
    (finding,) = rule.check(series)
    assert finding.day == date(2026, 3, 3)
    assert finding.severity is Severity.ERROR


def test_a_cross_with_a_missing_leg_is_not_judged():
    series = {"EURUSD": TimeSeries([(date(2026, 3, 2), "1.1")]), "EURGBP": TimeSeries([(date(2026, 3, 2), "0.9")])}
    assert FxTriangleRule().check(series) == []


def test_inverse_rule():
    series = {
        "EURUSD": TimeSeries([(date(2026, 3, 2), "1.25"), (date(2026, 3, 3), "1.25")]),
        "USDEUR": TimeSeries([(date(2026, 3, 2), "0.8"), (date(2026, 3, 3), "0.81")]),
    }
    (finding,) = FxInverseRule().check(series)
    assert finding.day == date(2026, 3, 3)
    assert finding.observed == pytest.approx(125.0)


# ---------------------------------------------------------------------------- evaluation
def test_every_fault_kind_has_rules_that_exist():
    from meridian.quality import default_rules

    names = {rule.name for rule in default_rules()} | {"fx_triangle"}
    assert set(EXPECTED_RULES) == set(FaultKind)
    assert all(rules <= names for rules in EXPECTED_RULES.values())


def test_evaluation_counts_false_alarms_and_misses():
    from meridian.marketdata.providers import InjectedFault
    from meridian.quality import Finding

    faults = [
        InjectedFault(FaultKind.SPIKE, "A", date(2026, 3, 2), date(2026, 3, 2), ""),
        InjectedFault(FaultKind.STALE_RUN, "A", date(2026, 4, 1), date(2026, 4, 7), ""),
    ]
    findings = [
        Finding(
            rule="spike_reversal",
            key="A",
            day=date(2026, 3, 2),
            severity=Severity.ERROR,
            dimension=Dimension.ACCURACY,
            message="",
        ),
        Finding(
            rule="robust_outlier",
            key="A",
            day=date(2026, 6, 1),
            severity=Severity.ERROR,
            dimension=Dimension.ACCURACY,
            message="",
        ),
    ]
    score = evaluate(findings, faults)
    assert score.recall == 0.5
    assert score.precision == 0.5
    assert [fault.kind for fault in score.missed] == [FaultKind.STALE_RUN]
    assert [item.day for item in score.false_alarms] == [date(2026, 6, 1)]
    assert score.kind(FaultKind.SPIKE).recall == 1.0
    with pytest.raises(KeyError):
        score.kind(FaultKind.UNIT_ERROR)
