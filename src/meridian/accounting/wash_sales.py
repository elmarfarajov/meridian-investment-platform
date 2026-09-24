"""The US wash sale rule (IRC section 1091).

A loss on selling a security is disallowed if substantially identical shares
are acquired within 30 days before or after the sale - a 61-day window centred
on the sale date. The loss is not lost: it is added to the basis of the
replacement shares, and the holding period of the shares sold is added to
theirs. The rule exists to stop an investor harvesting a tax loss while never
really giving up the position.

What makes it awkward to implement is the look-ahead. A sale on 10 March cannot
be finalised until 9 April, because a purchase on 8 April turns its loss into a
wash sale. The engine therefore processes the transaction history knowing every
acquisition in advance, and a replacement purchase that has not yet happened
when the sale is processed is recorded as a *pending* adjustment, applied to
the lot when that purchase is booked.

Matching follows IRS Publication 550:

* Replacement shares are taken in the order they were acquired, earliest first.
* A share can serve as a replacement only once.
* The shares being sold cannot replace themselves - but other shares from the
  same purchase can, if that purchase falls inside the window and they are
  still held.
* Only as many shares as were sold at a loss can be replacements; if fewer
  replacement shares were bought, only that fraction of the loss is disallowed.

Which shares were bought is taken from purchases (and rights taken up); shares
received by transfer or in a corporate action are not an acquisition for this
purpose.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..core.decimals import decimal_sum
from .lots import RealisedLot

WASH_SALE_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class Acquisition:
    transaction_id: str
    instrument_id: str
    trade_date: date
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class WashSaleMatch:
    """Replacement shares matched to a loss sale."""

    instrument_id: str
    disposal_id: str
    sold_lot_id: str
    sale_date: date
    replacement_id: str
    replacement_date: date
    quantity: Decimal
    disallowed_per_unit: Decimal  # base currency
    tacked_days: int

    @property
    def disallowed(self) -> Decimal:
        return self.quantity * self.disallowed_per_unit

    @property
    def replacement_before_sale(self) -> bool:
        return self.replacement_date <= self.sale_date

    @property
    def days_from_sale(self) -> int:
        return (self.replacement_date - self.sale_date).days


@dataclass(frozen=True, slots=True)
class PendingAdjustment:
    quantity: Decimal
    per_unit: Decimal
    tacked_days: int
    match: WashSaleMatch


class WashSaleTracker:
    """Replacement capacity per acquisition, consumed as loss sales are matched."""

    def __init__(self, acquisitions: Iterable[Acquisition], *, window_days: int = WASH_SALE_WINDOW_DAYS) -> None:
        self.window = timedelta(days=window_days)
        self._acquisitions: dict[str, list[Acquisition]] = defaultdict(list)
        self._capacity: dict[str, Decimal] = {}
        for acquisition in acquisitions:
            self._acquisitions[acquisition.instrument_id].append(acquisition)
            self._capacity[acquisition.transaction_id] = acquisition.quantity
        for items in self._acquisitions.values():
            items.sort(key=lambda item: (item.trade_date, item.transaction_id))
        self._pending: dict[str, list[PendingAdjustment]] = defaultdict(list)
        self.matches: list[WashSaleMatch] = []

    def capacity(self, transaction_id: str) -> Decimal:
        return self._capacity.get(transaction_id, Decimal(0))

    def consume_sold(self, transaction_id: str | None, quantity: Decimal) -> None:
        """Shares of an acquisition that have been sold cannot later serve as replacements."""
        if transaction_id in self._capacity:
            self._capacity[transaction_id] = max(self._capacity[transaction_id] - quantity, Decimal(0))

    def candidates(self, instrument_id: str, sale_date: date) -> list[Acquisition]:
        start, end = sale_date - self.window, sale_date + self.window
        return [
            item
            for item in self._acquisitions.get(instrument_id, [])
            if start <= item.trade_date <= end and self._capacity[item.transaction_id] > 0
        ]

    def match(self, realised: RealisedLot) -> list[WashSaleMatch]:
        """Match a realised lot to replacement shares; returns the matches (empty for a gain)."""
        loss = -realised.tax_gain_before_wash
        if loss <= 0:
            return []
        per_unit = loss / realised.quantity
        tacked = realised.holding_days
        outstanding = realised.quantity
        found: list[WashSaleMatch] = []
        for acquisition in self.candidates(realised.instrument_id, realised.close_date):
            if outstanding <= 0:
                break
            take = min(self._capacity[acquisition.transaction_id], outstanding)
            self._capacity[acquisition.transaction_id] -= take
            outstanding -= take
            match = WashSaleMatch(
                instrument_id=realised.instrument_id,
                disposal_id=realised.disposal_id,
                sold_lot_id=realised.lot_id,
                sale_date=realised.close_date,
                replacement_id=acquisition.transaction_id,
                replacement_date=acquisition.trade_date,
                quantity=take,
                disallowed_per_unit=per_unit,
                tacked_days=tacked,
            )
            found.append(match)
        self.matches.extend(found)
        return found

    def defer(self, match: WashSaleMatch, quantity: Decimal | None = None) -> None:
        """Hold an adjustment until the replacement purchase is booked."""
        self._pending[match.replacement_id].append(
            PendingAdjustment(
                quantity if quantity is not None else match.quantity,
                match.disallowed_per_unit,
                match.tacked_days,
                match,
            )
        )

    def pending_for(self, transaction_id: str) -> list[PendingAdjustment]:
        """Adjustments waiting for a purchase that had not happened when the loss sale was processed."""
        return self._pending.pop(transaction_id, [])

    def disallowed_total(self) -> Decimal:
        return decimal_sum(match.disallowed for match in self.matches)
