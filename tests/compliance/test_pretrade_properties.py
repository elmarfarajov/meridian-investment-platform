"""What the pre-trade check must guarantee for any portfolio and any order.

Hypothesis writes the portfolios and the orders. An independent oracle in this
file measures, for every hard rule, how far past its limit each *group* is - each
issuer, each sector - so a breach moving to a second issuer, or a second excluded
stock, cannot hide behind the rule's single headline number.

* **Sound:** an order the checker lets through ("allowed" or "warning") makes no
  hard limit worse for any group.
* **Not over-cautious:** an order it blocks makes some hard limit worse for some
  group.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.compliance.parser import parse_mandate
from meridian.compliance.pretrade import Order, PreTradeChecker, apply_order
from meridian.compliance.snapshot import Holding, Snapshot

MANDATE = parse_mandate(
    """
mandate "property" version 1 effective 2026-01-01
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
ISSUER_LIMIT, SECTOR_LIMIT = 0.10, 0.40
SECTORS = ("Technology", "Financials", "Energy", "Staples")
UNIVERSE = {
    f"S{index}": {
        "asset_class": "equity",
        "issuer": f"ISSUER{index % 6}",  # some issuers have two lines of stock
        "sector": SECTORS[index % 4],
        "industry": "Tobacco" if index in (3, 9) else "Other",
    }
    for index in range(12)
}


def oracle(snapshot: Snapshot) -> dict[tuple[str, str], float]:
    """How far past its hard limit each group is: (rule, group) -> excess, zero when within."""
    issuers: dict[str, float] = defaultdict(float)
    sectors: dict[str, float] = defaultdict(float)
    tobacco = cash = 0.0
    for holding in snapshot.holdings:
        attributes = holding.attributes
        if attributes.get("asset_class") == "equity":
            issuers[str(attributes["issuer"])] += holding.weight
        if attributes.get("sector") is not None:
            sectors[str(attributes["sector"])] += holding.weight
        if attributes.get("industry") == "Tobacco":
            tobacco += holding.weight
        if attributes.get("asset_class") == "cash":
            cash += holding.weight
    excess = {("issuer", name): max(weight - ISSUER_LIMIT, 0.0) for name, weight in issuers.items()}
    excess.update({("sector", name): max(weight - SECTOR_LIMIT, 0.0) for name, weight in sectors.items()})
    excess[("tobacco", "")] = max(tobacco, 0.0)
    excess[("cash", "")] = max(0.01 - cash, cash - 0.10, 0.0)
    return excess


@st.composite
def scenario(draw):  # type: ignore[no-untyped-def]
    count = draw(st.integers(min_value=3, max_value=10))
    keys = draw(st.lists(st.sampled_from(sorted(UNIVERSE)), min_size=count, max_size=count, unique=True))
    raw = [draw(st.floats(min_value=0.2, max_value=3.0)) for _ in keys]
    cash = draw(st.floats(min_value=0.0, max_value=0.15))
    scale = (1.0 - cash) / sum(raw)
    holdings = [Holding(key, value * scale, UNIVERSE[key]) for key, value in zip(keys, raw, strict=True)]
    holdings.append(Holding("CASH.USD", cash, {"asset_class": "cash"}))
    snapshot = Snapshot(date(2026, 9, 18), 1_000_000.0, tuple(holdings))
    side = draw(st.sampled_from(("buy", "sell")))
    if side == "sell":
        target = draw(st.sampled_from(keys))
        held = next(holding.weight for holding in holdings if holding.key == target)
        amount = draw(st.floats(min_value=0.0, max_value=1.0)) * held * snapshot.nav
    else:
        target = draw(st.sampled_from(sorted(UNIVERSE)))
        amount = draw(st.floats(min_value=1_000.0, max_value=150_000.0))
    return snapshot, Order("O1", target, side, amount)


@settings(max_examples=400, deadline=None)
@given(scenario())
def test_an_order_let_through_makes_no_hard_limit_worse_for_any_group(case):
    snapshot, order = case
    decision = PreTradeChecker(MANDATE, snapshot, reference=UNIVERSE).check(order, find_maximum=False)
    before, after = oracle(snapshot), oracle(apply_order(snapshot, order, UNIVERSE))
    worse = {key: (before.get(key, 0.0), value) for key, value in after.items() if value > before.get(key, 0.0) + 1e-9}
    if decision.decision in ("allowed", "warning"):
        assert not worse, (decision.decision, worse)
    else:
        assert worse, decision.decision


def _book(**weights: float) -> Snapshot:
    holdings = [Holding(key, weight, UNIVERSE[key]) for key, weight in weights.items() if key != "cash"]
    holdings.append(Holding("CASH.USD", weights.get("cash", 0.05), {"asset_class": "cash"}))
    return Snapshot(date(2026, 9, 18), 1_000_000.0, tuple(holdings))


def test_adding_to_an_excluded_stock_already_held_is_blocked():
    # S3 is tobacco and already held: utilisation was infinite before and after, so this looked unchanged
    snapshot = _book(S3=0.02, S1=0.09, S2=0.09, S4=0.09, S5=0.09, S7=0.09, S8=0.09, S10=0.09, S11=0.09, cash=0.26)
    decision = PreTradeChecker(MANDATE, snapshot, reference=UNIVERSE).check(
        Order("O", "S3", "buy", 5_000.0), find_maximum=False
    )
    assert decision.decision == "blocked"
    assert {change.rule_id: change.effect for change in decision.reasons}["tobacco"] == "worse breach"


def test_a_second_issuer_crossing_the_limit_is_a_new_breach():
    # ISSUER0 is over its limit; buying ISSUER1 to 10.5% left the rule's headline (the heaviest issuer) unchanged
    snapshot = _book(S0=0.13, S1=0.09, S2=0.09, S4=0.09, S5=0.09, S8=0.09, S10=0.09, S11=0.09, cash=0.24)
    decision = PreTradeChecker(MANDATE, snapshot, reference=UNIVERSE).check(
        Order("O", "S1", "buy", 15_000.0), find_maximum=False
    )
    assert decision.decision == "blocked"
    assert {change.rule_id: change.effect for change in decision.reasons}["issuer"] == "new breach"


def test_the_register_keeps_one_breach_per_issuer_and_judges_each_on_its_own():
    from datetime import timedelta

    from meridian.compliance.engine import check
    from meridian.compliance.monitor import build_register

    day0 = date(2026, 9, 14)
    days = [day0 + timedelta(days=offset) for offset in range(3)]
    # day 1: ISSUER0 rises over 10% with no trade (passive); day 2: S1 is bought over 10% (active)
    # five stocks of five different issuers (the universe's issuer is the index modulo six)
    books = [
        _book(S0=0.09, S1=0.08, S2=0.09, S4=0.09, S5=0.09, cash=0.56),
        _book(S0=0.11, S1=0.08, S2=0.09, S4=0.09, S5=0.09, cash=0.54),
        _book(S0=0.11, S1=0.105, S2=0.09, S4=0.09, S5=0.09, cash=0.515),
    ]
    reports = [check(MANDATE, Snapshot(day, 1e6, snapshot.holdings)) for day, snapshot in zip(days, books, strict=True)]
    groups = {key: {str(attributes["issuer"])} for key, attributes in UNIVERSE.items()}
    register = [b for b in build_register(reports, {days[2]: {"S1"}}, groups) if b.rule_id == "issuer"]
    by_group = {breach.group: breach for breach in register}
    assert set(by_group) == {"ISSUER0", "ISSUER1"}  # two issuers, two breaches
    assert by_group["ISSUER0"].kind == "passive" and by_group["ISSUER0"].opened == days[1]
    assert by_group["ISSUER1"].kind == "active" and by_group["ISSUER1"].opened == days[2]
    assert by_group["ISSUER1"].label == "Single issuer: ISSUER1"
