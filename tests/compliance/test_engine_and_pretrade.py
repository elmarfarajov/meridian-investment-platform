"""Checking rules on snapshots, pre-trade decisions, and the breach register."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from meridian.compliance.engine import check, evaluate, matches
from meridian.compliance.language import Comparison, Membership
from meridian.compliance.monitor import PASSIVE_GRACE_DAYS, build_register
from meridian.compliance.parser import parse_mandate, parse_rule
from meridian.compliance.pretrade import Basket, Order, PreTradeChecker, apply_order
from meridian.compliance.snapshot import Holding, Snapshot, rating_score
from meridian.core import ValidationError

DAY = date(2026, 9, 18)


def equity(key: str, weight: float, issuer: str, sector: str = "Technology", **extra: object) -> Holding:
    return Holding(key, weight, {"asset_class": "equity", "issuer": issuer, "sector": sector, "country": "US", **extra})


def book(metrics: dict | None = None) -> Snapshot:
    fund = Holding("FUND", 0.30, {"asset_class": "fund", "issuer": "FUND", "sector": None, "country": "IE"})
    constituents = (
        equity("MSFT", 0.5, "MICROSOFT"),
        equity("BANK", 0.3, "BANK", "Financials"),
        equity("SMOKE", 0.2, "SMOKE", "Staples", industry="Tobacco"),
    )
    return Snapshot(
        DAY,
        1_000_000.0,
        (
            equity("MSFT", 0.09, "MICROSOFT"),
            equity("AAPL", 0.08, "APPLE"),
            equity("NVDA", 0.07, "NVIDIA", "Semis"),
            fund,
            Holding("BOND", 0.40, {"asset_class": "fixed income", "issuer": "UST", "rating": "AA+"}),
            Holding("CASH.USD", 0.06, {"asset_class": "cash", "issuer": "cash USD"}),
        ),
        metrics or {"tracking_error": 0.04},
        {"FUND": constituents},
    )


def test_conditions_match_on_attributes_ratings_and_missing_values():
    bond = Holding("B", 0.1, {"rating": "BB+"})
    assert matches(Comparison("rating", "<", "BBB-"), bond)
    assert not matches(Comparison("rating", "<", "BBB-"), Holding("E", 0.1, {}))  # no rating is not junk
    assert matches(Membership("country", ("US",), negated=True), Holding("X", 0.1, {"country": "DE"}))
    assert not matches(Membership("country", ("US",), negated=True), Holding("Y", 0.1, {}))
    assert rating_score("AAA") > rating_score("BBB-") > rating_score("D")
    with pytest.raises(ValidationError, match="unknown credit rating"):
        rating_score("AAAA")


def test_look_through_finds_the_issuer_inside_the_fund():
    direct = evaluate(parse_rule('rule d hard max weight by issuer where asset_class = "equity" <= 10%'), book())
    looked = evaluate(
        parse_rule('rule l hard max weight by issuer with look-through where asset_class = "equity" <= 10%'), book()
    )
    assert direct.value == pytest.approx(0.09) and direct.status == "pass" and direct.group == "MICROSOFT"
    assert looked.value == pytest.approx(0.09 + 0.30 * 0.5) and looked.status == "breach"
    hidden = evaluate(parse_rule('rule t soft no holdings with look-through where industry = "Tobacco"'), book())
    assert hidden.value == pytest.approx(0.06) and hidden.contributors[0][0] == "SMOKE" and hidden.status == "breach"


def test_statuses_utilisation_and_headroom():
    rule = parse_rule('rule c hard weight where asset_class = "cash" between 1% and 10%')
    result = evaluate(rule, book())
    assert (
        result.status == "pass" and result.headroom == pytest.approx(0.04) and result.utilisation == pytest.approx(0.6)
    )
    warn = evaluate(parse_rule('rule w soft weight where asset_class = "cash" <= 7% warn at 5%'), book())
    assert warn.status == "warning"
    ucits = evaluate(
        parse_rule('rule u hard sum weight by issuer above 5% where asset_class = "equity" <= 20%'), book()
    )
    assert ucits.value == pytest.approx(0.24) and ucits.status == "breach" and len(ucits.contributors) == 3
    exactly = evaluate(parse_rule('rule e hard weight where asset_class = "cash" <= 6%'), book())
    assert exactly.status == "pass"  # at the limit is within it, whatever binary rounding does
    missing = evaluate(parse_rule("rule m soft volatility <= 15%"), book())
    assert missing.status == "not evaluable" and missing.value is None


def test_a_report_counts_statuses():
    mandate = parse_mandate(
        'mandate "m" version 1 effective 2026-01-01\n'
        'rule a hard weight where asset_class = "cash" <= 10%\n'
        'rule b soft weight where asset_class = "cash" <= 5%\n'
        "rule c soft tracking_error <= 6%\n"
    )
    report = check(mandate, book())
    assert report.count("pass") == 2 and report.count("breach") == 1 and report.compliant
    assert report.result("b").rule.severity == "soft"


MANDATE = parse_mandate(
    'mandate "m" version 1 effective 2026-01-01\n'
    'rule issuer hard max weight by issuer where asset_class = "equity" <= 10% warn at 9.5%\n'
    'rule cash hard weight where asset_class = "cash" between 1% and 10%\n'
    'rule looked soft max weight by issuer with look-through where asset_class = "equity" <= 24.2%\n'
)


def test_pre_trade_decisions_and_the_largest_order():
    checker = PreTradeChecker(MANDATE, book())
    blocked = checker.check(Order("o1", "MSFT", "buy", 20_000.0))
    assert blocked.decision == "blocked" and blocked.reasons[0].effect == "new breach"
    assert blocked.maximum == pytest.approx(10_000.0, rel=1e-6)  # MSFT from 9% to 10%
    allowed = checker.check(Order("o2", "NVDA", "buy", 10_000.0))
    assert allowed.decision == "allowed"
    override = checker.check(Order("o3", "FUND", "buy", 10_000.0), find_maximum=False)
    assert override.decision == "override required"  # the looked-through Microsoft passes 24.2%, a soft limit
    warning = checker.check(Order("o4", "AAPL", "buy", 16_000.0), find_maximum=False)
    assert warning.decision == "warning"
    with pytest.raises(ValidationError, match="more of"):
        apply_order(book(), Order("o5", "MSFT", "sell", 200_000.0))
    with pytest.raises(ValidationError, match="side"):
        Order("o6", "MSFT", "hold", 1.0)


def test_a_trade_that_reduces_a_breach_is_allowed_and_baskets_net_their_cash():
    breached = PreTradeChecker(MANDATE, book().with_weights({"MSFT": 0.03, "CASH.USD": -0.03}))
    assert breached.before.result("issuer").status == "breach"
    assert breached.check(Order("s", "MSFT", "sell", 10_000.0), find_maximum=False).decision == "allowed"
    checker = PreTradeChecker(MANDATE, book())
    sale = Order("sell", "BOND", "sell", 50_000.0)
    purchases = (Order("b1", "AAPL", "buy", 10_000.0), Order("b2", "NVDA", "buy", 20_000.0))
    assert checker.check(sale, find_maximum=False).decision == "blocked"  # alone, cash would be 11%
    basket = checker.check_basket(Basket("rebalance", (sale, *purchases)))
    assert basket.decision == "allowed"  # together, cash ends at 8%
    too_much = checker.check_basket(Basket("greedy", (sale, Order("b3", "NVDA", "buy", 45_000.0))))
    assert too_much.decision == "blocked" and too_much.reasons[0].rule_id == "issuer"


def test_the_breach_register_opens_classifies_and_closes():
    rule = 'rule cash hard weight where asset_class = "cash" <= 10%'
    mandate = parse_mandate('mandate "m" version 1 effective 2026-01-01\n' + rule)

    def cash_book(day: date, weight: float) -> Snapshot:
        return Snapshot(
            day,
            1.0,
            (Holding("CASH.USD", weight, {"asset_class": "cash"}), Holding("X", 1 - weight, {"asset_class": "equity"})),
        )

    days = [DAY + timedelta(days=offset) for offset in range(6)]
    weights = [0.05, 0.12, 0.13, 0.08, 0.15, 0.15]
    reports = [check(mandate, cash_book(day, weight)) for day, weight in zip(days, weights, strict=True)]
    register = build_register(reports, {days[3]: {"CASH.USD"}, days[4]: {"CASH.USD"}})
    first, second = register
    assert (first.opened, first.closed, first.kind, first.days) == (days[1], days[3], "passive", 2)
    assert first.resolution == "resolved by trading" and first.peak_utilisation == pytest.approx(1.3)
    assert second.kind == "active" and second.closed is None and second.deadline == days[4]
    assert second.state(days[5]) == "overdue" and first.state(days[5]) == "resolved by trading"
    assert first.deadline == days[1] + timedelta(days=PASSIVE_GRACE_DAYS) and first.grade == "critical"
