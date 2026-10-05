"""The Day 6 revisit charts: compliance that cannot be talked past, and a century of a sector limit.

Two charts compare the revisited checks with Day 6's. Day 6's rules are reproduced
here, in a few lines each, for exactly that comparison: the pre-trade decision by
utilisation and the heaviest group, and the register of one breach per rule.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .compliance.engine import RuleResult
from .compliance.parser import parse_mandate
from .compliance.pretrade import Order, PreTradeChecker, RuleChange, _decide, apply_order
from .compliance.snapshot import Holding, Snapshot
from .marketdata.french import french_history
from .services import century_compliance as century
from .viz.compliance_revisited import (
    GuaranteeBar,
    RegisterBar,
    ReviewPanel,
    plot_capped,
    plot_century_limit,
    plot_effective_number,
    plot_guarantee,
    plot_register,
    plot_review,
)

if TYPE_CHECKING:
    from .compliance.monitor import Breach
    from .gallery import GalleryItem

ORDERS = 3000
MANDATE = parse_mandate(
    """
mandate "guarantee" version 1 effective 2026-01-01
rule issuer "Single issuer" hard
    max weight by issuer where asset_class = "equity" <= 10%
rule sector "Single sector" hard
    max weight by sector <= 40%
rule tobacco "No tobacco" hard
    no holdings where industry = "Tobacco"
rule cash "Cash" hard
    weight where asset_class = "cash" between 1% and 10%
"""
)
SECTORS = ("Technology", "Financials", "Energy", "Staples")
UNIVERSE = {
    f"S{index}": {
        "asset_class": "equity",
        "issuer": f"ISSUER{index % 6}",
        "sector": SECTORS[index % 4],
        "industry": "Tobacco" if index in (3, 9) else "Other",
    }
    for index in range(12)
}
LIMITS = {"issuer": 0.10, "sector": 0.40}


def _day6_effect(before: RuleResult, after: RuleResult) -> str:
    """Day 6's judgement of one rule: by utilisation, the heaviest group only."""
    if after.status == "breach":
        if before.status != "breach":
            return "new breach"
        assert before.utilisation is not None and after.utilisation is not None
        if after.utilisation > before.utilisation + 1e-12:
            return "worse breach"
        if after.utilisation < before.utilisation - 1e-12:
            return "reduces breach"
        return "unchanged"
    if before.status == "breach":
        return "reduces breach"
    if after.status == "warning" and before.status != "warning":
        return "new warning"
    return "unchanged"


def _excess(snapshot: Snapshot) -> dict[tuple[str, str], float]:
    """An independent measure of every group's excess past its hard limit."""
    issuers: dict[str, float] = defaultdict(float)
    sectors: dict[str, float] = defaultdict(float)
    tobacco = cash = 0.0
    for holding in snapshot.holdings:
        attributes = holding.attributes
        if attributes.get("asset_class") == "equity":
            issuers[str(attributes["issuer"])] += holding.weight
            sectors[str(attributes["sector"])] += holding.weight
        if attributes.get("industry") == "Tobacco":
            tobacco += holding.weight
        if attributes.get("asset_class") == "cash":
            cash += holding.weight
    found = {("issuer", name): max(weight - LIMITS["issuer"], 0.0) for name, weight in issuers.items()}
    found.update({("sector", name): max(weight - LIMITS["sector"], 0.0) for name, weight in sectors.items()})
    found[("tobacco", "")] = tobacco
    found[("cash", "")] = max(0.01 - cash, cash - 0.10, 0.0)
    return found


@lru_cache(maxsize=1)
def guarantee_counts() -> dict[str, tuple[int, int]]:
    """Per rule: orders let through although they made it worse, by Day 6's rule and by the revisited one."""
    rng = np.random.default_rng(20261005)
    keys = sorted(UNIVERSE)
    counts = {rule.rule_id: [0, 0] for rule in MANDATE.rules}
    counts["any"] = [0, 0]
    for _ in range(ORDERS):
        chosen = list(rng.choice(keys, size=int(rng.integers(3, 11)), replace=False))
        raw = rng.uniform(0.2, 3.0, len(chosen))
        cash = float(rng.uniform(0.0, 0.15))
        weights = raw / raw.sum() * (1.0 - cash)
        holdings = [Holding(key, float(w), UNIVERSE[key]) for key, w in zip(chosen, weights, strict=True)]
        holdings.append(Holding("CASH.USD", cash, {"asset_class": "cash"}))
        snapshot = Snapshot(date(2026, 9, 18), 1_000_000.0, tuple(holdings))
        if rng.random() < 0.5:
            target = str(rng.choice(chosen))
            held = next(holding.weight for holding in holdings if holding.key == target)
            order = Order("O", target, "sell", float(rng.uniform(0, 1)) * held * snapshot.nav)
        else:
            order = Order("O", str(rng.choice(keys)), "buy", float(rng.uniform(1_000, 150_000)))
        checker = PreTradeChecker(MANDATE, snapshot, reference=UNIVERSE)
        decision = checker.check(order, find_maximum=False)
        old = _decide([RuleChange(c.before, c.after, _day6_effect(c.before, c.after)) for c in decision.changes])
        before, after = _excess(snapshot), _excess(apply_order(snapshot, order, UNIVERSE))
        worse = {key[0] for key, value in after.items() if value > before.get(key, 0.0) + 1e-9}
        for rule_id in worse:
            counts[rule_id][0] += old in ("allowed", "warning")
            counts[rule_id][1] += decision.decision in ("allowed", "warning")
        if worse:  # each order once, however many limits it made worse
            counts["any"][0] += old in ("allowed", "warning")
            counts["any"][1] += decision.decision in ("allowed", "warning")
    return {rule: (old, new) for rule, (old, new) in counts.items()}


def guarantee_chart() -> Figure:
    counts = guarantee_counts()
    names = {rule.rule_id: rule.name for rule in MANDATE.rules}
    bars = [GuaranteeBar(names[rule], old, new) for rule, (old, new) in counts.items() if rule != "any"]
    examples = [
        (
            "Adding to an excluded stock already held",
            "a limit of zero makes utilisation infinite before and after, so a bigger breach looked unchanged.",
            "the excess past the limit - the tobacco weight itself - grew, so the order is blocked.",
        ),
        (
            "A second issuer crossing the limit",
            "the rule's value is its heaviest issuer, still the first one, so the second's breach was invisible.",
            "every issuer is judged on its own; a breach in one that was within the limit is new.",
        ),
        (
            "Spending the last of the cash",
            "a cash floor against cash of zero is infinite utilisation too: going overdrawn looked unchanged.",
            "the shortfall below the floor grew, so the order is blocked.",
        ),
    ]
    return plot_guarantee(ORDERS, bars, examples, counts["any"])


def _register_per_rule(reports, traded, groups_of) -> list[tuple[str, date, str]]:  # type: ignore[no-untyped-def]
    """Day 6's register, reduced to what the comparison needs: (rule, opened, heaviest group at opening)."""
    opened: list[tuple[str, date, str]] = []
    open_rules: set[str] = set()
    for report in reports:
        for result in report.results:
            rule_id = result.rule.rule_id
            if result.is_breach and rule_id not in open_rules:
                open_rules.add(rule_id)
                opened.append((rule_id, report.day, str(result.group or "")))
            elif not result.is_breach and result.status != "not evaluable":
                open_rules.discard(rule_id)
    return opened


def _days_per_rule(reports) -> list[int]:  # type: ignore[no-untyped-def]
    """Day 6's register counted a rule's breach-days once, however many groups were over the limit."""
    return [sum(1 for report in reports for result in report.results if result.is_breach)]


def register_chart() -> Figure:
    from .services.demo_compliance import build_demo_compliance

    demo = build_demo_compliance()
    rule_id = "issuer_look_through"
    old = _register_per_rule(demo.history.reports, demo.traded, demo.groups_of)
    old_openings = {(rule, day, group) for rule, day, group in old}
    breaches: list[Breach] = [breach for breach in demo.breaches if breach.rule_id == rule_id]
    bars = [
        RegisterBar(
            breach.group,
            breach.opened,
            breach.closed,
            breach.kind,
            (rule_id, breach.opened, breach.group) not in old_openings,
        )
        for breach in breaches
    ]
    old_count = sum(1 for rule, _, _ in old if rule == rule_id)
    return plot_register(bars, demo.days[-1], old_count, len(breaches), demo.mandate.rule(rule_id).name)


def century_limit_chart() -> Figure:
    reports = century.index_reports()
    largest = [report.result("sector_40").value or 0.0 for report in reports]
    leaders = [str(report.result("sector_40").group) for report in reports]
    peak = max(
        ((report.day, report.result("sector_40").value or 0.0) for report in reports if report.day.year == 2000),
        key=lambda item: item[1],
    )
    breaches = [(breach.opened, breach.closed) for breach in century.index_register() if breach.rule_id == "sector_40"]
    return plot_century_limit([report.day for report in reports], largest, leaders, 0.40, 0.35, breaches, peak)


def effective_number_chart() -> Figure:
    history = french_history()
    effective, top_two = [], []
    for month in history.months:
        weights = np.array(sorted(history.weights(month).values(), reverse=True))
        effective.append(float(1.0 / np.sum(weights**2)))
        top_two.append(float(weights[:2].sum()))
    return plot_effective_number(history.months, effective, top_two)


def capped_chart() -> Figure:
    comparison = century.capped_comparison()
    gap = np.cumprod(1.0 + comparison.capped) / np.cumprod(1.0 + comparison.market) - 1.0
    market, capped = comparison.annual(comparison.market), comparison.annual(comparison.capped)
    growth_market, growth_capped = comparison.growth()
    summary = {
        "months the cap bound": f"{comparison.months_binding} of {len(comparison.months):,}",
        "first binding month": f"{comparison.months[int(np.argmax(comparison.binding))]:%B %Y}",
        "return a year, market": f"{market:.3%}",
        "return a year, capped": f"{capped:.3%}",
        "tracking error": f"{comparison.tracking_error:.2%} a year",
        "$1 in 1926 became": f"${growth_market:,.0f} against ${growth_capped:,.0f}".replace("$", r"\$"),
    }
    since = date(2018, 1, 1)
    monthly = comparison.capped - comparison.market
    return plot_capped(comparison.months, monthly, gap, comparison.binding.tolist(), summary, century.CAP, since)


def review_chart() -> Figure:
    from .services.demo_compliance import build_demo_compliance

    counts = guarantee_counts()
    demo = build_demo_compliance()
    old = _register_per_rule(demo.history.reports, demo.traded, demo.groups_of)
    old_days = _days_per_rule(demo.history.reports)
    panels = [
        ReviewPanel(
            f"Unsafe orders let through (of {ORDERS:,})",
            ("orders",),
            (float(counts["any"][0]),),
            (float(counts["any"][1]),),
            ".0f",
            "Day 6 judged a breach by utilisation and the heaviest group; it now judges the excess past "
            "the limit, group by group.",
        ),
        ReviewPanel(
            "The account's breach register",
            ("breaches",),
            (float(len(old)),),
            (float(len(demo.breaches)),),
            ".0f",
            "One record per rule, judged by its heaviest group, became one per rule and group: seven "
            "second-issuer breaches appear.",
        ),
        ReviewPanel(
            "Days in breach, the account",
            ("breach-days",),
            (float(sum(days for days in old_days)),),
            (float(sum(breach.days for breach in demo.breaches)),),
            ".0f",
            "The second-issuer breaches lasted 36 days that Day 6's register never counted.",
        ),
    ]
    return plot_review(panels)


def compliance_revisited_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "pretrade-guarantee.png",
            "Orders the pre-trade check let through",
            "Random portfolios and orders under Day 6's rule and the revisited one.",
            guarantee_chart,
            "validation",
        ),
        GalleryItem(
            "register-per-issuer.png",
            "One breach per issuer",
            "The account's look-through issuer breaches, with those Day 6's register missed.",
            register_chart,
            "compliance",
        ),
        GalleryItem(
            "century-sector-limit.png",
            "A 40% industry limit since 1926",
            "The US market's largest industry every month, against the limit and its warning.",
            century_limit_chart,
            "compliance",
        ),
        GalleryItem(
            "market-concentration.png",
            "The most concentrated market in a century",
            "The effective number of industries and the two largest together since 1926.",
            effective_number_chart,
            "compliance",
        ),
        GalleryItem(
            "capped-index.png",
            "What a 35% industry cap would have cost",
            "A monthly capped index against the market since 1926.",
            capped_chart,
            "compliance",
        ),
        GalleryItem(
            "compliance-review.png",
            "A second reading of Day 6",
            "The figures the faults changed, before and after.",
            review_chart,
            "compliance",
        ),
    )
