"""Compliance in the database: rules as written, results, the register and pre-trade decisions."""

from __future__ import annotations

from dataclasses import replace

import pytest

from meridian.compliance.language import to_text
from meridian.compliance.monitor import Breach
from meridian.compliance.parser import parse_rule
from meridian.core import ValidationError
from meridian.persistence import UnitOfWork
from meridian.persistence.compliance_repositories import text_hash
from meridian.services.compliance_run import check_controls, run_demo_compliance
from meridian.services.demo_compliance import build_demo_compliance

PORTFOLIO = "PF-GLOBAL-EQ"


@pytest.fixture(scope="module")
def compliance():
    return build_demo_compliance()


@pytest.fixture
def stored(unit_of_work: UnitOfWork, compliance):
    result = run_demo_compliance(compliance, unit_of_work)
    unit_of_work.commit()
    return result


def test_the_run_stores_rules_results_breaches_and_orders(stored, compliance):
    assert stored.stored["rule"] == len(compliance.mandate.rules)
    assert stored.stored["result"] == len(compliance.history.reports) * len(compliance.mandate.rules)
    assert stored.stored["breach"] == len(compliance.history.breaches)
    assert stored.stored["pre-trade check"] == len(compliance.demo_decisions)
    assert any("breaches" in label for label, _ in stored.summary_rows())


def test_a_stored_rule_is_the_rule_that_ran(stored, unit_of_work, compliance):
    rows = unit_of_work.compliance.rules("Global Equity Core")
    assert len(rows) == len(compliance.mandate.rules) and rows[0].version == 3
    for row in rows:
        rule = parse_rule(row.text)
        assert rule == compliance.mandate.rule(row.rule_id)
        assert row.text_hash == text_hash(to_text(rule))


def test_counts_in_sql_match_the_reports(stored, unit_of_work, compliance):
    today = compliance.history.reports[-1]
    counts = unit_of_work.compliance.status_counts(PORTFOLIO, today.day)
    assert counts == {status: today.count(status) for status in ("pass", "warning", "breach") if today.count(status)}
    history = unit_of_work.compliance.status_counts(PORTFOLIO)
    assert sum(history.values()) == stored.stored["result"]
    series = unit_of_work.compliance.results(PORTFOLIO, "issuer_limit")
    assert series[-1].top_contributor == "MICROSOFT"


def test_the_register_and_the_orders_read_back(stored, unit_of_work, compliance):
    register = unit_of_work.compliance.breaches(PORTFOLIO)
    assert [row.breach_id for row in register] == [breach.breach_id for breach in compliance.history.breaches]
    days = unit_of_work.compliance.breach_days(PORTFOLIO)
    assert sum(days.values()) == sum(breach.days for breach in compliance.history.breaches)
    assert unit_of_work.compliance.breaches(PORTFOLIO, open_only=True) == []
    blocked = unit_of_work.compliance.pretrade(PORTFOLIO, "blocked")
    assert {row.check_id for row in blocked} == {
        d.order.order_id for d in compliance.demo_decisions if d.decision == "blocked"
    }
    assert "issuer_limit" in blocked[0].reasons


def test_controls_refuse_to_store_an_overdue_hard_breach(compliance, monkeypatch):
    check_controls(compliance)
    last = compliance.history.reports[-1].day
    overdue = Breach("BR-X", "cash_band", "Cash", "hard", "active", last.replace(year=last.year - 1))
    breaches = [*compliance.history.breaches, overdue]
    monkeypatch.setattr(compliance.history, "breaches", breaches)
    with pytest.raises(ValidationError, match="opened on a day"):
        check_controls(compliance)
    good_day = next(breach for breach in compliance.history.breaches if breach.severity == "hard")
    monkeypatch.setattr(compliance.history, "breaches", [replace(good_day, closed=None)])
    with pytest.raises(ValidationError, match="overdue"):
        check_controls(compliance)
