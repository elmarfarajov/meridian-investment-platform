"""Pre-trade compliance: check an order before it reaches the market.

An order is checked by applying it to today's snapshot - the security's
weight goes up, cash goes down by the same amount - and running every rule on
the portfolio *as it would be*. Each rule then says one of four things:

* the order **breaches** a limit that was not breached, or makes a breach
  worse: a hard rule **blocks** the order; a soft rule lets it through only
  with a recorded **override**;
* the order crosses a **warning** level: it proceeds, flagged;
* the order **reduces** an existing breach: it is allowed - a trade that
  moves the portfolio back towards compliance must never be blocked by the
  breach it is curing;
* nothing changes that matters: **allowed**.

**Baskets.** A rebalance is several orders at once: sell the fund, buy the
stocks with the proceeds. Checked one at a time, the sale looks like a cash
breach and the purchases like an overdraft; checked together they are neither.
:meth:`PreTradeChecker.check_basket` applies all the orders and judges the
result, which is how program trades are checked in practice.

The largest order that stays within every hard limit is found by bisection on
the order's size: compliance checks are monotone in size for the limits a
single order can move, so forty halvings find it to a fraction of a dollar.
Metric rules (tracking error, volatility) are re-evaluated with the risk model
when one is supplied; without one they keep today's value.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from ..core.exceptions import ValidationError
from .engine import EPSILON, ComplianceReport, RuleResult, check
from .language import Mandate
from .snapshot import Attribute, Snapshot

MetricModel = Callable[[Snapshot], Mapping[str, float]]
DECISIONS: tuple[str, ...] = ("allowed", "warning", "override required", "blocked")


@dataclass(frozen=True)
class Order:
    order_id: str
    instrument_id: str
    side: str  # buy | sell
    amount: float  # in base currency
    funding: str = "CASH.USD"

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValidationError(f"{self.order_id}: side must be buy or sell")
        if self.amount < 0:
            raise ValidationError(f"{self.order_id}: the amount must not be negative")

    def with_amount(self, amount: float) -> Order:
        return replace(self, amount=amount)


@dataclass(frozen=True)
class Basket:
    """Orders sent together, and checked together."""

    basket_id: str
    orders: tuple[Order, ...]


@dataclass(frozen=True)
class RuleChange:
    before: RuleResult
    after: RuleResult
    effect: str  # new breach | worse breach | reduces breach | new warning | unchanged

    @property
    def rule_id(self) -> str:
        return self.after.rule.rule_id


@dataclass(frozen=True)
class PreTradeDecision:
    order: Order
    decision: str
    changes: tuple[RuleChange, ...]
    before: ComplianceReport
    after: ComplianceReport
    maximum: float | None = None  # the largest amount within every hard limit

    @property
    def reasons(self) -> tuple[RuleChange, ...]:
        return tuple(change for change in self.changes if change.effect != "unchanged")


def apply_order(
    snapshot: Snapshot, order: Order, reference: Mapping[str, Mapping[str, Attribute]] | None = None
) -> Snapshot:
    """The snapshot as it would be after the order, with the funding cash moved the other way."""
    share = order.amount / snapshot.nav
    sign = 1.0 if order.side == "buy" else -1.0
    current = snapshot.holding(order.instrument_id)
    if order.side == "sell" and (current is None or current.weight < share - EPSILON):
        raise ValidationError(f"{order.order_id}: cannot sell more of {order.instrument_id} than is held")
    return snapshot.with_weights({order.instrument_id: sign * share, order.funding: -sign * share}, reference)


def apply_basket(
    snapshot: Snapshot, orders: tuple[Order, ...], reference: Mapping[str, Mapping[str, Attribute]] | None = None
) -> Snapshot:
    """All the orders applied at once: sales fund purchases, so only the net cash moves."""
    changes: dict[str, float] = {}
    for order in orders:
        share = order.amount / snapshot.nav * (1.0 if order.side == "buy" else -1.0)
        changes[order.instrument_id] = changes.get(order.instrument_id, 0.0) + share
        changes[order.funding] = changes.get(order.funding, 0.0) - share
    for key, change in changes.items():
        held = snapshot.holding(key)
        if change < 0 and not key.startswith("CASH") and (held is None or held.weight < -change - EPSILON):
            raise ValidationError(f"the basket sells more of {key} than is held")
    return snapshot.with_weights(changes, reference)


@dataclass(frozen=True)
class BasketDecision:
    basket: Basket
    decision: str
    changes: tuple[RuleChange, ...]
    after: ComplianceReport

    @property
    def reasons(self) -> tuple[RuleChange, ...]:
        return tuple(change for change in self.changes if change.effect != "unchanged")


def _effect(before: RuleResult, after: RuleResult) -> str:
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


def _decide(changes: list[RuleChange]) -> str:
    harmful = [change for change in changes if change.effect in ("new breach", "worse breach")]
    if any(change.after.rule.severity == "hard" for change in harmful):
        return "blocked"
    if harmful:
        return "override required"
    if any(change.effect == "new warning" for change in changes):
        return "warning"
    return "allowed"


class PreTradeChecker:
    def __init__(
        self,
        mandate: Mandate,
        snapshot: Snapshot,
        *,
        reference: Mapping[str, Mapping[str, Attribute]] | None = None,
        metric_model: MetricModel | None = None,
    ) -> None:
        self.mandate = mandate
        self.snapshot = snapshot
        self.reference = reference or {}
        self.metric_model = metric_model
        self.before = check(mandate, snapshot)

    def _after(self, order: Order) -> ComplianceReport:
        proposed = apply_order(self.snapshot, order, self.reference)
        if self.metric_model is not None:
            proposed = replace(proposed, metrics=dict(self.metric_model(proposed)))
        return check(self.mandate, proposed)

    def _assess(self, order: Order) -> tuple[str, list[RuleChange], ComplianceReport]:
        after = self._after(order)
        changes = [RuleChange(b, a, _effect(b, a)) for b, a in zip(self.before.results, after.results, strict=True)]
        return _decide(changes), changes, after

    def check_basket(self, basket: Basket) -> BasketDecision:
        proposed = apply_basket(self.snapshot, basket.orders, self.reference)
        if self.metric_model is not None:
            proposed = replace(proposed, metrics=dict(self.metric_model(proposed)))
        after = check(self.mandate, proposed)
        changes = [RuleChange(b, a, _effect(b, a)) for b, a in zip(self.before.results, after.results, strict=True)]
        return BasketDecision(basket, _decide(changes), tuple(changes), after)

    def check(self, order: Order, *, find_maximum: bool = True) -> PreTradeDecision:
        decision, changes, after = self._assess(order)
        maximum = self.maximum(order) if find_maximum else None
        return PreTradeDecision(order, decision, tuple(changes), self.before, after, maximum)

    def maximum(self, order: Order, *, iterations: int = 40) -> float:
        """The largest amount of this order that no hard rule blocks (zero if even a sliver is blocked)."""
        if order.side == "sell":
            held = self.snapshot.holding(order.instrument_id)
            ceiling = (held.weight if held else 0.0) * self.snapshot.nav
        else:
            funding = self.snapshot.holding(order.funding)
            ceiling = max(order.amount, (funding.weight if funding else 0.0) * self.snapshot.nav) * 4
        if self._assess(order.with_amount(ceiling))[0] != "blocked":
            return ceiling
        low, high = 0.0, ceiling
        if self._assess(order.with_amount(1e-6))[0] == "blocked":
            return 0.0
        for _ in range(iterations):
            middle = (low + high) / 2
            if self._assess(order.with_amount(middle))[0] == "blocked":
                high = middle
            else:
                low = middle
        return low
