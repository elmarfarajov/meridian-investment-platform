"""The Day 6 charts: the mandate checked every day, the breach register, and pre-trade decisions.

Data preparation lives here and the chart functions take plain inputs, as for
the earlier days, so every figure is rebuilt deterministically by
``meridian charts gallery`` and shows the numbers the tests assert.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .compliance.engine import RuleResult
from .compliance.language import (
    And,
    Comparison,
    ConcentrationSum,
    Condition,
    CountOf,
    MaxGroupWeight,
    Membership,
    Metric,
    NoHoldings,
    Or,
    Rule,
    WeightOf,
    bound_text,
    to_text,
)
from .services.demo_compliance import DemoCompliance, build_demo_compliance
from .viz.compliance import (
    plot_allocation_bands,
    plot_breach_timeline,
    plot_compliance_report,
    plot_issuer_limits,
    plot_limit_utilisation,
    plot_look_through,
    plot_pretrade,
    plot_register,
    plot_replay,
    plot_rule_tree,
    plot_ucits,
    plot_utilisation_heatmap,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

CATEGORIES = {
    "issuer_limit": "Concentration",
    "issuer_look_through": "Concentration",
    "government_issuer": "Concentration",
    "single_fund": "Concentration",
    "sector_limit": "Concentration",
    "diversification": "Concentration",
    "equity_band": "Asset allocation",
    "fixed_income_band": "Asset allocation",
    "cash_band": "Asset allocation",
    "outside_us": "Geography and currency",
    "currency_limit": "Geography and currency",
    "credit_quality": "Credit and exclusions",
    "exclusions": "Credit and exclusions",
    "exclusions_indirect": "Credit and exclusions",
    "liquidity": "Liquidity and risk",
    "tracking_error": "Liquidity and risk",
    "volatility": "Liquidity and risk",
    "active_share": "Liquidity and risk",
}
EXCLUDED = ("Tobacco", "Controversial Weapons", "Thermal Coal")
ISSUER = "MICROSOFT"


def _demo() -> DemoCompliance:
    return build_demo_compliance()


def _format(rule: Rule, value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}" if isinstance(rule.measure, CountOf) else f"{value:.2%}"


def utilisation_rows(results: tuple[RuleResult, ...]) -> list[tuple[str, str, str, float | None, str, str, str]]:
    rows = [
        (
            result.rule.rule_id,
            result.rule.name,
            CATEGORIES.get(result.rule.rule_id, "Other"),
            result.utilisation,
            result.status,
            _format(result.rule, result.value),
            bound_text(result.rule) or "none may be held",
        )
        for result in results
    ]
    order = list(dict.fromkeys(CATEGORIES.values()))
    return sorted(rows, key=lambda row: order.index(row[2]) if row[2] in order else len(order))


def warn_levels(demo: DemoCompliance) -> dict[str, float]:
    """Each rule's warning level on the utilisation scale."""
    levels: dict[str, float] = {}
    for rule in demo.mandate.rules:
        if rule.warn_at is None:
            continue
        if rule.bound.upper is not None and rule.bound.upper > 0:
            levels[rule.rule_id] = float(rule.warn_at / rule.bound.upper)
        elif rule.bound.lower is not None and rule.warn_at > 0:
            levels[rule.rule_id] = float(rule.bound.lower / rule.warn_at)
    return levels


def utilisation_chart() -> Figure:
    demo = _demo()
    today = demo.today
    counts = {status: today.count(status) for status in ("pass", "warning", "breach")}
    return plot_limit_utilisation(utilisation_rows(today.results), warn_levels(demo), today.day, counts)


def rule_titles(demo: DemoCompliance) -> list[tuple[str, str]]:
    return [(rule.rule_id, rule.name) for rule in demo.mandate.rules]


def breach_rows(demo: DemoCompliance) -> list[tuple[str, date, date | None, str, str]]:
    return [(breach.rule_id, breach.opened, breach.closed, breach.kind, breach.severity) for breach in demo.breaches]


def timeline_chart() -> Figure:
    demo = _demo()
    days = demo.history.days
    return plot_breach_timeline(rule_titles(demo), breach_rows(demo), days[0], days[-1])


def monthly_utilisation(demo: DemoCompliance) -> tuple[list[str], np.ndarray]:
    months: dict[tuple[int, int], int] = {}
    for day in demo.history.days:
        months.setdefault((day.year, day.month), len(months))
    matrix = np.full((len(demo.mandate.rules), len(months)), np.nan)
    for report in demo.history.reports:
        column = months[(report.day.year, report.day.month)]
        for row, result in enumerate(report.results):
            if result.utilisation is not None and np.isfinite(result.utilisation):
                current = matrix[row, column]
                matrix[row, column] = result.utilisation if np.isnan(current) else max(current, result.utilisation)
    labels = [date(year, month, 1).strftime("%b %y") for year, month in months]
    return labels, matrix


def heatmap_chart() -> Figure:
    demo = _demo()
    labels, matrix = monthly_utilisation(demo)
    return plot_utilisation_heatmap([rule.name for rule in demo.mandate.rules], labels, matrix)


def issuer_series(demo: DemoCompliance, rule_id: str, issuer: str = ISSUER) -> list[float]:
    return [dict(result.contributors).get(issuer, 0.0) for result in demo.history.series(rule_id)]


def issuer_chart() -> Figure:
    demo = _demo()
    mandate = demo.mandate
    direct, looked = mandate.rule("issuer_limit"), mandate.rule("issuer_look_through")
    assert direct.bound.upper is not None and looked.bound.upper is not None
    limits = {
        "direct limit": float(direct.bound.upper),
        "look-through limit": float(looked.bound.upper),
        "direct warning": float(direct.warn_at or 0),
        "look-through warning": float(looked.warn_at or 0),
    }
    return plot_issuer_limits(
        demo.history.days,
        issuer_series(demo, "issuer_limit"),
        issuer_series(demo, "issuer_look_through"),
        limits,
        "Microsoft",
    )


def look_through_rows(
    demo: DemoCompliance, top: int = 12
) -> tuple[list[tuple[str, float, float]], list[tuple[str, str, float]]]:
    snapshot = demo.today_snapshot
    direct: dict[str, float] = defaultdict(float)
    looked: dict[str, float] = defaultdict(float)
    for holding in snapshot.holdings:
        if holding.attribute("asset_class") == "equity":
            direct[str(holding.attribute("issuer"))] += holding.weight
    exclusions: list[tuple[str, str, float]] = []
    for holding in snapshot.expanded():
        if holding.attribute("asset_class") == "equity":
            looked[str(holding.attribute("issuer"))] += holding.weight
        industry = holding.attribute("industry")
        if industry in EXCLUDED and holding.via:
            exclusions.append((holding.key, str(industry), holding.weight))
    merged: dict[tuple[str, str], float] = defaultdict(float)
    for key, industry, weight in exclusions:
        merged[(key, industry)] += weight
    rows = sorted(
        ((issuer, direct.get(issuer, 0.0), value) for issuer, value in looked.items()), key=lambda row: -row[2]
    )[:top]
    return rows, [(key, industry, weight) for (key, industry), weight in merged.items()]


def look_through_chart() -> Figure:
    rows, exclusions = look_through_rows(_demo())
    return plot_look_through(rows, exclusions)


def register_summary(
    demo: DemoCompliance,
) -> tuple[list[tuple[str, int, int, int, int]], dict[str, list[int]], dict[str, int]]:
    by_rule: dict[str, list[int]] = {}
    for breach in demo.breaches:
        row = by_rule.setdefault(breach.rule_name, [0, 0, 0, 0])
        index = 0 if breach.kind == "active" else 1
        row[index] += 1
        row[index + 2] += breach.days
    rows: list[tuple[str, int, int, int, int]] = sorted(
        ((name, values[0], values[1], values[2], values[3]) for name, values in by_rule.items()),
        key=lambda row: -(row[1] + row[2]),
    )
    durations = {
        kind: [breach.days for breach in demo.breaches if breach.kind == kind] for kind in ("active", "passive")
    }
    resolutions: dict[str, int] = {}
    last = demo.today.day
    for breach in demo.breaches:
        state = breach.state(last)
        resolutions[state] = resolutions.get(state, 0) + 1
    return rows, durations, resolutions


def register_chart() -> Figure:
    return plot_register(*register_summary(_demo()))


def pretrade_rows(demo: DemoCompliance) -> list[tuple[str, str, str, float, float, str, str]]:
    rows = []
    for decision in demo.demo_decisions:
        rank = {
            ("hard", "new breach"): 0,
            ("hard", "worse breach"): 0,
            ("soft", "new breach"): 1,
            ("soft", "worse breach"): 1,
        }
        reasons = sorted(
            (change for change in decision.reasons if change.effect in ("new breach", "worse breach", "new warning")),
            key=lambda change: rank.get((change.after.rule.severity, change.effect), 2),
        )
        reason = reasons[0].after.rule.name.lower() if reasons else ""
        rows.append(
            (
                decision.order.order_id,
                decision.order.side,
                decision.order.instrument_id,
                decision.order.amount,
                decision.maximum or 0.0,
                decision.decision,
                reason,
            )
        )
    return rows


def pretrade_chart() -> Figure:
    return plot_pretrade(pretrade_rows(_demo()))


def replay_chart() -> Figure:
    demo = _demo()
    rows = [
        (item.day, item.order.side, item.order.instrument_id, item.order.amount, item.decision, item.basket_decision)
        for item in demo.replayed
    ]
    return plot_replay(rows)


def ucits_series(
    demo: DemoCompliance,
) -> tuple[list[date], dict[str, list[float]], list[float], list[tuple[str, float]]]:
    history = demo.ucits
    days = history.days
    results = history.series("five_ten_forty")
    issuers = sorted({label for result in results for label, _ in result.contributors})
    layers = {issuer: [dict(result.contributors).get(issuer, 0.0) for result in results] for issuer in issuers}
    totals = [result.value or 0.0 for result in results]
    today = history.reports[-1].result("issuer_10").contributors[:10]
    return days, layers, totals, [(label, float(value)) for label, value in today]


def ucits_chart() -> Figure:
    return plot_ucits(*ucits_series(_demo()))


def _condition_tree(condition: Condition) -> tuple[str, list]:
    if isinstance(condition, And | Or):
        return ("and" if isinstance(condition, And) else "or", [_condition_tree(part) for part in condition.parts])
    if isinstance(condition, Comparison):
        return (f"{condition.field}\n{condition.operator} {condition.value}", [])
    assert isinstance(condition, Membership)
    values = ", ".join(str(value) for value in condition.values)
    return (f"{condition.field}\n{'not in' if condition.negated else 'in'} ({values})", [])


def rule_tree(rule: Rule) -> tuple[str, list]:
    """A rule as a tree of labels: what the parser built, for drawing."""
    measure = rule.measure
    names = {
        WeightOf: "weight of",
        MaxGroupWeight: "heaviest group",
        ConcentrationSum: "sum of groups above",
        CountOf: "count of",
        NoHoldings: "none may be held",
        Metric: "metric",
    }
    detail = ""
    if isinstance(measure, MaxGroupWeight | ConcentrationSum):
        detail = f"\nby {measure.group_by}"
    if isinstance(measure, Metric):
        detail = f"\n{measure.name}"
    children: list[tuple[str, list]] = []
    look = getattr(measure, "look_through", False)
    if look:
        children.append(("look through\nindex funds", []))
    condition = getattr(measure, "filter", None)
    if condition is not None:
        children.append(("filter", [_condition_tree(condition)]))
    measure_node = (names[type(measure)] + detail, children)
    parts = [measure_node, (f"bound\n{bound_text(rule) or '= 0'}", [])]
    if rule.warn_at is not None:
        parts.append((f"warn at\n{rule.warn_at * 100:.1f}%", []))
    return (f"rule {rule.rule_id}\n{rule.severity}", parts)


TREE_RULE = (
    'rule defence_screen "Defence, including funds" soft\n'
    '    weight with look-through where industry = "Aerospace and Defence" '
    'or (sector = "Industrials" and country != "US") <= 10% warn at 8%'
)


def tree_chart() -> Figure:
    from .compliance.parser import parse_rule

    rule = parse_rule(TREE_RULE)
    return plot_rule_tree(to_text(rule), rule_tree(rule))


def allocation_chart() -> Figure:
    demo = _demo()
    series = {
        "Equities": [result.value or 0.0 for result in demo.history.series("equity_band")],
        "Fixed income": [result.value or 0.0 for result in demo.history.series("fixed_income_band")],
        "Cash": [result.value or 0.0 for result in demo.history.series("cash_band")],
    }
    bands = {}
    for name, rule_id in (("Equities", "equity_band"), ("Fixed income", "fixed_income_band"), ("Cash", "cash_band")):
        bound = demo.mandate.rule(rule_id).bound
        assert bound.lower is not None and bound.upper is not None
        bands[name] = (float(bound.lower), float(bound.upper))
    return plot_allocation_bands(demo.history.days, series, bands)


def report_tiles(demo: DemoCompliance) -> list[tuple[str, str]]:
    today = demo.today
    return [
        ("Rules within limits", f"{today.count('pass')} of {len(today.results)}"),
        ("Warnings", f"{today.count('warning')}"),
        ("Breaches today", f"{today.count('breach')}"),
        ("Breaches since inception", f"{len(demo.breaches)}"),
    ]


def report_chart() -> Figure:
    demo = _demo()
    decisions = [
        (f"{row[1]} {row[3] / 1e3:,.0f}k {row[2]}", row[5], f"largest within hard limits {row[4] / 1e3:,.0f}k")
        for row in pretrade_rows(demo)
    ]
    return plot_compliance_report(
        demo.accounting.portfolio.name,
        demo.today.day,
        report_tiles(demo),
        utilisation_rows(demo.today.results),
        breach_rows(demo),
        rule_titles(demo),
        decisions,
        demo.history.days[0],
    )


def compliance_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    def item(filename: str, title: str, description: str, builder) -> GalleryItem:  # type: ignore[no-untyped-def]
        return GalleryItem(filename, title, description, builder, "compliance")

    return (
        item(
            "limit-utilisation.png",
            "Headroom against every rule",
            "Each rule of the mandate as the share of its limit in use, with its warning level.",
            utilisation_chart,
        ),
        item(
            "breach-timeline.png",
            "The breach register over time",
            "Every breach from opening to close, active or passive, hard limits outlined.",
            timeline_chart,
        ),
        item(
            "utilisation-heatmap.png",
            "Utilisation month by month",
            "The highest utilisation of every rule in every month, breaches marked.",
            heatmap_chart,
        ),
        item(
            "issuer-limits.png",
            "One issuer, two limits",
            "Microsoft held directly and including the index funds, against its hard and soft limits.",
            issuer_chart,
        ),
        item(
            "look-through.png",
            "What the index funds hide",
            "Issuer exposure direct and looked through, and excluded industries reached through funds.",
            look_through_chart,
        ),
        item(
            "breach-register.png",
            "The breach register",
            "Breaches by rule and cause, how long they lasted, and how they ended.",
            register_chart,
        ),
        item(
            "pretrade-decisions.png",
            "Pre-trade decisions",
            "Test orders against the mandate, and the largest size each limit allows.",
            pretrade_chart,
        ),
        item(
            "pretrade-replay.png",
            "The history, replayed",
            "The book's own trades through the pre-trade check, one at a time and as baskets.",
            replay_chart,
        ),
        item(
            "ucits-screen.png",
            "The UCITS screen",
            "Issuers above 5% against the 40% ceiling, and each issuer against the 10% limit.",
            ucits_chart,
        ),
        item(
            "rule-parse-tree.png",
            "How a rule is read",
            "A rule of the mandate language and the tree the Lark parser builds from it.",
            tree_chart,
        ),
        item(
            "allocation-bands.png",
            "Asset allocation bands",
            "Equities, fixed income and cash against the mandate's bands, breaches shaded.",
            allocation_chart,
        ),
        item(
            "compliance-report.png",
            "The compliance report",
            "The page the compliance committee reads: utilisation, breaches and today's orders.",
            report_chart,
        ),
    )
