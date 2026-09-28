"""Orders and their lifecycle: the order management system's state machine, in the vocabulary of FIX.

An order is not a number, it is a history. It is created by the portfolio
manager, released to the desk, worked by an algorithm in child orders, filled
in pieces, and ends filled, cancelled or expired - and every step is an event
that an auditor may ask about. The states and transitions follow the FIX
protocol's ``OrdStatus`` (tag 39), so a message from a real broker would map
onto them one for one:

    NEW --> PARTIALLY_FILLED --> FILLED
     |            |
     +--> CANCELLED / EXPIRED (what is left is not traded)
     +--> REJECTED (before any fill)

Quantities obey two invariants that are checked on every event:

* ``cumulative + leaves == quantity`` while the order is open, and ``leaves``
  is zero once it is done;
* the **average price** is the fill-weighted mean of the fills, recomputed from
  the fills themselves rather than updated incrementally, so rounding cannot
  accumulate.

A **parent** order (the block the desk works) owns **child** orders (the slices
an algorithm sends to the market). A fill belongs to a child and rolls up to its
parent; allocation (``allocation.py``) splits a parent's fills back to the
accounts that asked for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from ..core.exceptions import ValidationError

QUANTITY_TOLERANCE = 1e-9


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderStatus(str, Enum):
    """FIX OrdStatus, the subset an agency desk uses."""

    PENDING_NEW = "pending new"  # created by the portfolio manager, not yet released to the desk
    NEW = "new"  # released, working, nothing filled
    PARTIALLY_FILLED = "partially filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # the day ended with shares left
    REJECTED = "rejected"

    @property
    def is_done(self) -> bool:
        return self in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED)


#: which events may move an order from each state
TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING_NEW: frozenset({OrderStatus.NEW, OrderStatus.REJECTED, OrderStatus.CANCELLED}),
    OrderStatus.NEW: frozenset(
        {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}


@dataclass(frozen=True)
class Fill:
    """An execution report: shares done at a price, at a minute of the session."""

    fill_id: str
    order_id: str  # the child order it filled
    minute: int  # minutes after the open
    quantity: float
    price: float
    venue: str = "lit"

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.price <= 0:
            raise ValidationError(f"{self.fill_id}: a fill needs a positive quantity and price")


@dataclass(frozen=True)
class OrderEvent:
    """One line of the order's audit trail."""

    minute: int
    status: OrderStatus
    note: str


@dataclass
class Order:
    order_id: str
    instrument_id: str
    side: Side
    quantity: float
    trade_date: date
    portfolio_id: str | None = None  # an account order; None for a block
    parent_id: str | None = None  # a child order's parent
    algorithm: str | None = None
    limit_price: float | None = None
    decision_price: float | None = None  # the price when the portfolio manager decided (the previous close)
    status: OrderStatus = OrderStatus.PENDING_NEW
    fills: list[Fill] = field(default_factory=list)
    events: list[OrderEvent] = field(default_factory=list)
    created: datetime | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValidationError(f"{self.order_id}: the quantity must be positive")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValidationError(f"{self.order_id}: a limit price must be positive")
        if not self.events:
            self.events.append(OrderEvent(0, self.status, "created"))

    # ------------------------------------------------------------------ quantities
    @property
    def cumulative(self) -> float:
        return sum(fill.quantity for fill in self.fills)

    @property
    def leaves(self) -> float:
        return 0.0 if self.status.is_done else max(self.quantity - self.cumulative, 0.0)

    @property
    def average_price(self) -> float | None:
        done = self.cumulative
        if done <= 0:
            return None
        return sum(fill.quantity * fill.price for fill in self.fills) / done

    @property
    def fill_rate(self) -> float:
        return self.cumulative / self.quantity

    @property
    def notional(self) -> float:
        """Filled value, in the instrument's price currency."""
        return sum(fill.quantity * fill.price for fill in self.fills)

    # ------------------------------------------------------------------ transitions
    def _move(self, status: OrderStatus, minute: int, note: str) -> None:
        if status not in TRANSITIONS[self.status]:
            raise ValidationError(f"{self.order_id}: cannot go from {self.status.value} to {status.value}")
        self.status = status
        self.events.append(OrderEvent(minute, status, note))

    def release(self, minute: int = 0, algorithm: str | None = None) -> None:
        """The desk accepts the order and starts working it."""
        if algorithm is not None:
            self.algorithm = algorithm
        self._move(OrderStatus.NEW, minute, f"released{' to ' + algorithm if algorithm else ''}")

    def reject(self, reason: str, minute: int = 0) -> None:
        self._move(OrderStatus.REJECTED, minute, reason)

    def fill(self, fill: Fill) -> None:
        if self.status.is_done:
            raise ValidationError(f"{self.order_id}: a fill arrived for an order that is {self.status.value}")
        if self.status is OrderStatus.PENDING_NEW:
            raise ValidationError(f"{self.order_id}: a fill arrived before the order was released")
        if fill.quantity > self.quantity - self.cumulative + QUANTITY_TOLERANCE * max(1.0, self.quantity):
            raise ValidationError(f"{self.order_id}: the fill of {fill.quantity} overfills the order")
        if self.limit_price is not None and self.side.sign * (fill.price - self.limit_price) > 1e-9:
            raise ValidationError(
                f"{self.order_id}: filled through its limit ({fill.price} against {self.limit_price})"
            )
        self.fills.append(fill)
        complete = self.quantity - self.cumulative <= QUANTITY_TOLERANCE * max(1.0, self.quantity)
        status = OrderStatus.FILLED if complete else OrderStatus.PARTIALLY_FILLED
        self._move(status, fill.minute, f"{fill.quantity:,.0f} at {fill.price:,.4f}")

    def cancel(self, minute: int, reason: str = "cancelled") -> None:
        self._move(OrderStatus.CANCELLED, minute, reason)

    def expire(self, minute: int) -> None:
        """The session ended; what is left is not traded."""
        if self.status.is_done:
            return
        self._move(OrderStatus.EXPIRED, minute, f"{self.quantity - self.cumulative:,.0f} left at the close")

    def check(self) -> None:
        """The invariants every order must satisfy after every event."""
        if self.cumulative > self.quantity + QUANTITY_TOLERANCE * max(1.0, self.quantity):
            raise ValidationError(f"{self.order_id}: filled {self.cumulative} of {self.quantity}")
        if not self.status.is_done and abs(self.cumulative + self.leaves - self.quantity) > 1e-6:
            raise ValidationError(f"{self.order_id}: cumulative and leaves do not add up")
        if self.status is OrderStatus.FILLED and abs(self.cumulative - self.quantity) > 1e-6:
            raise ValidationError(f"{self.order_id}: marked filled with {self.cumulative} of {self.quantity}")
        minutes = [event.minute for event in self.events]
        if minutes != sorted(minutes):
            raise ValidationError(f"{self.order_id}: the audit trail is out of order")
