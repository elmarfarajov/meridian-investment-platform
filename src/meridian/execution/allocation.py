"""Block orders: many accounts' orders traded as one, and the fills shared back fairly.

When a model portfolio changes, every account that follows it needs the same
trade. Sending each account's order separately would make the accounts compete
with each other in the market - the first order's impact raising the price for
the second - and whichever account's order happened to go first would get the
best price. So the desk **aggregates** the orders into one block per stock and
side, works the block, and **allocates** the fills back.

The rules for allocating are the ones regulators write down (the SEC's
guidance for investment advisers, the FCA's COBS 11.3 on aggregation):

* **the same price for everyone** - every account receives the block's average
  price, not a particular fill's;
* **pro rata when the block is not completed** - each account gets the same
  share of what it asked for, in whole shares, the odd shares going by largest
  remainder so nothing is lost and nothing invented;
* **no account receives more than it asked for**, and an allocation below a
  minimum is not made (it would cost more to book than it is worth) and goes to
  the others instead;
* the allocation is decided **before** the block is worked and recorded with it,
  so it cannot be chosen afterwards to favour an account.

Accounts that want to buy and sell the same stock on the same day are not
crossed against each other here; they are sent as separate blocks.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ..core.exceptions import ValidationError
from .orders import Order, Side

MINIMUM_ALLOCATION = 1.0  # shares


@dataclass(frozen=True)
class AccountOrder:
    """What one account asked for."""

    portfolio_id: str
    instrument_id: str
    side: Side
    quantity: float
    decision_price: float

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValidationError(f"{self.portfolio_id} {self.instrument_id}: the quantity must be positive")


@dataclass(frozen=True)
class Allocation:
    portfolio_id: str
    instrument_id: str
    side: Side
    requested: float
    quantity: float
    price: float  # the block's average price

    @property
    def fill_rate(self) -> float:
        return self.quantity / self.requested


@dataclass
class Block:
    """A block order and the account orders it stands for."""

    order: Order
    members: list[AccountOrder]

    @property
    def requested(self) -> float:
        return sum(member.quantity for member in self.members)


def aggregate(orders: Sequence[AccountOrder], trade_date: date, prefix: str = "BLK") -> list[Block]:
    """One block per stock and side; its decision price is the members' quantity-weighted decision price."""
    grouped: dict[tuple[str, Side], list[AccountOrder]] = defaultdict(list)
    for order in orders:
        grouped[(order.instrument_id, order.side)].append(order)
    blocks = []
    for number, ((instrument_id, side), members) in enumerate(
        sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1].value)), start=1
    ):
        quantity = sum(member.quantity for member in members)
        decision = sum(member.quantity * member.decision_price for member in members) / quantity
        block = Order(
            f"{prefix}-{trade_date:%Y%m%d}-{number:03d}",
            instrument_id,
            side,
            quantity,
            trade_date,
            decision_price=decision,
        )
        blocks.append(Block(block, sorted(members, key=lambda member: member.portfolio_id)))
    return blocks


def allocate(block: Block, minimum: float = MINIMUM_ALLOCATION) -> list[Allocation]:
    """Share a block's fills among its accounts: one price, pro rata in whole shares, largest remainder."""
    filled = block.order.cumulative
    price = block.order.average_price
    requested = block.requested
    members = block.members
    if filled <= 0 or price is None:
        return [Allocation(m.portfolio_id, m.instrument_id, m.side, m.quantity, 0.0, 0.0) for m in members]
    if filled >= requested - 1e-9:
        shares = [member.quantity for member in members]
    else:
        shares = _pro_rata([member.quantity for member in members], filled, minimum)
    allocations = [
        Allocation(
            member.portfolio_id,
            member.instrument_id,
            member.side,
            member.quantity,
            quantity,
            price if quantity > 0 else 0.0,
        )
        for member, quantity in zip(members, shares, strict=True)
    ]
    check_allocations(block, allocations)
    return allocations


def _pro_rata(requested: list[float], filled: float, minimum: float) -> list[float]:
    total = math.floor(filled + 1e-9)
    eligible = list(range(len(requested)))
    while True:
        base = sum(requested[i] for i in eligible)
        exact = {i: total * requested[i] / base for i in eligible}
        floors = {i: math.floor(exact[i]) for i in eligible}
        small = [i for i in eligible if floors[i] < minimum and len(eligible) > 1]
        if not small:
            break
        # too small to book: this account's share goes to the others
        eligible = [i for i in eligible if i not in small[:1]]
    shares = {i: float(min(floors[i], requested[i])) for i in eligible}
    order = sorted(eligible, key=lambda i: (-(exact[i] - floors[i]), -requested[i], i))
    remainder = total - sum(shares.values())
    for i in order:  # the odd shares, by largest remainder, to those it does not take past their request
        if remainder < 1:
            break
        if shares[i] + 1 <= requested[i] + 1e-9:
            shares[i] += 1
            remainder -= 1
    for i in order:  # what no whole share can place: a request in fractions, or a share given up by the minimum
        if remainder <= 1e-9:
            break
        room = min(requested[i] - shares[i], remainder)
        if room > 1e-9:
            shares[i] += room
            remainder -= room
    return [shares.get(i, 0.0) for i in range(len(requested))]


def check_allocations(block: Block, allocations: Sequence[Allocation]) -> None:
    """The rules every allocation must satisfy."""
    filled = block.order.cumulative
    allocated = sum(item.quantity for item in allocations)
    if allocated > filled + 1e-6:
        raise ValidationError(f"{block.order.order_id}: allocated {allocated} of {filled} filled")
    if filled - allocated >= 1.0:
        raise ValidationError(f"{block.order.order_id}: {filled - allocated} filled shares left unallocated")
    prices = {round(item.price, 10) for item in allocations if item.quantity > 0}
    if len(prices) > 1:
        raise ValidationError(f"{block.order.order_id}: accounts allocated at different prices")
    for item in allocations:
        if item.quantity > item.requested + 1e-9:
            raise ValidationError(f"{item.portfolio_id}: allocated more than it asked for")
