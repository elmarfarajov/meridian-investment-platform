"""The lot book: open tax lots per holding, and a record of every lot closed.

A sale does not reduce "the position"; it closes specific lots, chosen by the
account's lot relief method, and each closed lot is a realised gain with its
own holding period, its own cost in base currency and - if the wash sale rule
bit - its own disallowed loss. :class:`RealisedLot` keeps all of that, because
every tax report, every performance report and every reconciliation question
about a sale is eventually a question about one of these records.

A realised gain in base currency is split into the part due to the security's
price and the part due to the exchange rate:

    proceeds x rate_sale - cost x rate_open
        = (proceeds - cost) x rate_sale            price gain, at today's rate
        + cost x (rate_sale - rate_open)            currency gain on the cost

The split is exact - the two parts sum to the whole to the last decimal - and
it is the same split the valuation uses for unrealised gains, so a gain does
not change character when it is realised.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

from ..core.decimals import decimal_sum
from ..core.enums import LotSelectionMethod
from ..core.exceptions import ValidationError
from ..domain.positions import LONG_TERM_HOLDING_DAYS, Position, TaxLot


class RealisationKind(str, Enum):
    SALE = "sale"
    CASH_IN_LIEU = "cash_in_lieu"
    CASH_MERGER = "cash_merger"
    MERGER_BOOT = "merger_boot"


class Term(str, Enum):
    SHORT = "short"
    LONG = "long"


@dataclass(frozen=True, slots=True)
class RealisedLot:
    """One lot, or part of one, closed by a disposal."""

    portfolio_id: str
    instrument_id: str
    lot_id: str
    disposal_id: str
    open_date: date
    holding_start: date
    close_date: date
    quantity: Decimal
    currency: str
    proceeds: Decimal  # local currency, net of this lot's share of the disposal costs
    cost: Decimal  # local currency, book cost
    open_fx_rate: Decimal
    close_fx_rate: Decimal
    wash_sale_basis: Decimal = Decimal(0)  # base: disallowed losses carried into this lot earlier
    disallowed_loss: Decimal = Decimal(0)  # base: the part of this loss the wash sale rule disallows now
    kind: RealisationKind = RealisationKind.SALE

    # ------------------------------------------------------------------ holding period
    @property
    def holding_days(self) -> int:
        return (self.close_date - self.holding_start).days

    @property
    def term(self) -> Term:
        return Term.LONG if self.holding_days > LONG_TERM_HOLDING_DAYS else Term.SHORT

    @property
    def is_long_term(self) -> bool:
        return self.term is Term.LONG

    # ------------------------------------------------------------------ book (economic) gain
    @property
    def gain(self) -> Decimal:
        """Local-currency gain."""
        return self.proceeds - self.cost

    @property
    def proceeds_base(self) -> Decimal:
        return self.proceeds * self.close_fx_rate

    @property
    def cost_base(self) -> Decimal:
        return self.cost * self.open_fx_rate

    @property
    def gain_base(self) -> Decimal:
        return self.proceeds_base - self.cost_base

    @property
    def price_gain_base(self) -> Decimal:
        return self.gain * self.close_fx_rate

    @property
    def fx_gain_base(self) -> Decimal:
        return self.cost * (self.close_fx_rate - self.open_fx_rate)

    # ------------------------------------------------------------------ tax gain
    @property
    def tax_basis(self) -> Decimal:
        return self.cost_base + self.wash_sale_basis

    @property
    def tax_gain_before_wash(self) -> Decimal:
        return self.proceeds_base - self.tax_basis

    @property
    def reportable_gain(self) -> Decimal:
        """The gain or loss that goes on the return: a disallowed loss is added back."""
        return self.tax_gain_before_wash + self.disallowed_loss

    @property
    def is_loss(self) -> bool:
        return self.tax_gain_before_wash < 0

    @property
    def adjustment_code(self) -> str:
        """Form 8949 column (f): W for a wash sale."""
        return "W" if self.disallowed_loss else ""

    @property
    def tax_year(self) -> int:
        return self.close_date.year


def allocate_pro_rata(total: Decimal, quantities: Sequence[Decimal]) -> list[Decimal]:
    """Split ``total`` over ``quantities`` exactly: the parts are proportional and sum to the total."""
    whole = decimal_sum(quantities)
    if whole <= 0:
        raise ValidationError("cannot allocate over a zero quantity")
    parts = [total * quantity / whole for quantity in quantities[:-1]]
    parts.append(total - decimal_sum(parts))
    return parts


class LotBook:
    """Open lots by instrument, with lot relief that keeps lot identifiers stable."""

    def __init__(self, portfolio_id: str, *, method: LotSelectionMethod = LotSelectionMethod.FIFO) -> None:
        self.portfolio_id = portfolio_id
        self.method = method
        self._lots: dict[str, list[TaxLot]] = {}
        self._sequence = 0

    # ------------------------------------------------------------------ reading
    def instruments(self) -> tuple[str, ...]:
        return tuple(sorted(key for key, lots in self._lots.items() if lots))

    def lots(self, instrument_id: str | None = None) -> tuple[TaxLot, ...]:
        if instrument_id is not None:
            return tuple(self._lots.get(instrument_id, ()))
        return tuple(lot for key in sorted(self._lots) for lot in self._lots[key])

    def quantity(self, instrument_id: str) -> Decimal:
        return decimal_sum(lot.quantity for lot in self._lots.get(instrument_id, ()))

    def quantities(self) -> dict[str, Decimal]:
        return {key: self.quantity(key) for key in self.instruments()}

    def position(self, instrument_id: str) -> Position:
        lots = self._lots.get(instrument_id, [])
        if not lots:
            raise ValidationError(f"no open lots in {instrument_id}")
        return Position(
            portfolio_id=self.portfolio_id, instrument_id=instrument_id, currency=lots[0].currency, lots=tuple(lots)
        )

    def snapshot(self) -> dict[str, tuple[TaxLot, ...]]:
        return {key: tuple(lots) for key, lots in self._lots.items() if lots}

    # ------------------------------------------------------------------ changing
    def open(self, lot: TaxLot) -> TaxLot:
        existing = self._lots.setdefault(lot.instrument_id, [])
        if existing and existing[0].currency != lot.currency:
            raise ValidationError(f"{lot.lot_id}: {lot.instrument_id} is held in {existing[0].currency.code}")
        if any(item.lot_id == lot.lot_id for item in existing):
            raise ValidationError(f"lot {lot.lot_id} is already open")
        existing.append(lot)
        existing.sort(key=lambda item: (item.open_date, item.lot_id))
        return lot

    def replace_instrument(self, instrument_id: str, lots: Iterable[TaxLot]) -> None:
        self._lots[instrument_id] = sorted(lots, key=lambda item: (item.open_date, item.lot_id))

    def relieve(
        self,
        instrument_id: str,
        quantity: Decimal,
        as_of: date,
        *,
        method: LotSelectionMethod | None = None,
        specific_lot_ids: Sequence[str] | None = None,
    ) -> tuple[TaxLot, ...]:
        """Close ``quantity`` units and return the lots (or fragments) closed.

        A partly sold lot keeps its identifier; only the part being closed is a
        fragment. That keeps the identifier the custodian and the client see
        stable for the life of the lot.
        """
        position = self.position(instrument_id)
        chosen = method or self.method
        if specific_lot_ids:
            chosen = LotSelectionMethod.SPECIFIC_LOT
        sold, remaining = position.select_lots(quantity, chosen, as_of=as_of, specific_lot_ids=specific_lot_ids)
        original_ids = {lot.lot_id for lot in position.lots}
        restored = [
            replace(lot, lot_id=lot.lot_id[:-2])
            if lot.lot_id not in original_ids and lot.lot_id.endswith("-R")
            else lot
            for lot in remaining
        ]
        self.replace_instrument(instrument_id, restored)
        return sold

    def adjust_for_wash_sale(
        self, instrument_id: str, transaction_id: str, quantity: Decimal, per_unit: Decimal, tacked_days: int
    ) -> Decimal:
        """Add a disallowed loss to open replacement shares bought in ``transaction_id``.

        Returns the quantity actually adjusted, which is less than asked for if
        some of those shares have already been sold. A lot only partly used as
        a replacement is split, so each piece carries the right basis.
        """
        outstanding = quantity
        updated: list[TaxLot] = []
        for lot in self._lots.get(instrument_id, []):
            if outstanding <= 0 or lot.transaction_id != transaction_id:
                updated.append(lot)
                continue
            take = min(lot.quantity, outstanding)
            target, rest = lot.split(take) if take < lot.quantity else (lot, None)
            updated.append(wash_adjusted(target, per_unit, tacked_days))
            if rest is not None:
                self._sequence += 1
                updated.append(replace(rest, lot_id=f"{lot.lot_id}/{self._sequence}"))
            outstanding -= take
        self.replace_instrument(instrument_id, updated)
        return quantity - outstanding


def wash_adjusted(lot: TaxLot, per_unit: Decimal, tacked_days: int) -> TaxLot:
    """A replacement lot: basis raised by the disallowed loss, holding period extended by the shares sold."""
    start = lot.holding_start.toordinal() - tacked_days
    return replace(
        lot,
        wash_sale_adjustment=lot.wash_sale_adjustment + per_unit,
        holding_period_start=date.fromordinal(min(start, lot.open_date.toordinal())),
    )
