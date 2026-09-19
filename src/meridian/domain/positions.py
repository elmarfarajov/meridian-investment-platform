"""Positions and tax lots.

A position is not a single number. For a taxable account it is a stack of lots,
each with its own acquisition date and cost, because which lot is sold determines
the tax bill: selling the highest-cost lot defers gains, selling a lot held for
more than a year converts a short-term gain into a long-term one. The rebalancing
engine later optimises exactly this choice, so the lot detail is part of the
domain model from the start rather than bolted on.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

from ..core.currency import Currency, get_currency
from ..core.decimals import Numeric, decimal_sum, safe_divide, to_decimal
from ..core.enums import LotSelectionMethod
from ..core.exceptions import ValidationError
from ..core.money import Money

LONG_TERM_HOLDING_DAYS = 365


@dataclass(frozen=True, slots=True, kw_only=True)
class TaxLot:
    """One acquisition of a security, tracked separately for tax purposes."""

    lot_id: str
    instrument_id: str
    open_date: date
    quantity: Decimal
    cost_per_unit: Decimal
    currency: Currency
    transaction_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", get_currency(self.currency))
        object.__setattr__(self, "quantity", to_decimal(self.quantity, field="quantity"))
        object.__setattr__(self, "cost_per_unit", to_decimal(self.cost_per_unit, field="cost_per_unit"))
        if self.quantity <= 0:
            raise ValidationError(f"{self.lot_id}: an open lot must have a positive quantity")
        if self.cost_per_unit < 0:
            raise ValidationError(f"{self.lot_id}: cost per unit must not be negative")

    @property
    def cost_basis(self) -> Money:
        return Money(self.quantity * self.cost_per_unit, self.currency)

    def holding_days(self, as_of: date) -> int:
        return (as_of - self.open_date).days

    def is_long_term(self, as_of: date) -> bool:
        """US convention: more than one year qualifies for long-term treatment."""
        return self.holding_days(as_of) > LONG_TERM_HOLDING_DAYS

    def long_term_from(self) -> date:
        return self.open_date + timedelta(days=LONG_TERM_HOLDING_DAYS + 1)

    def market_value(self, price: Numeric) -> Money:
        return Money(self.quantity * to_decimal(price, field="price"), self.currency)

    def unrealised_gain(self, price: Numeric) -> Money:
        return self.market_value(price) - self.cost_basis

    def split(self, quantity: Numeric) -> tuple[TaxLot, TaxLot | None]:
        """Divide a lot into the part being sold and the remainder."""
        sold = to_decimal(quantity, field="quantity")
        if sold <= 0:
            raise ValidationError(f"{self.lot_id}: split quantity must be positive")
        if sold > self.quantity:
            raise ValidationError(f"{self.lot_id}: cannot split {sold} out of {self.quantity}")
        if sold == self.quantity:
            return self, None
        return (
            replace(self, quantity=sold),
            replace(self, lot_id=f"{self.lot_id}-R", quantity=self.quantity - sold),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Position:
    """The holding in one instrument, with its open lots."""

    portfolio_id: str
    instrument_id: str
    currency: Currency
    lots: tuple[TaxLot, ...] = ()
    as_of: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", get_currency(self.currency))
        for lot in self.lots:
            if lot.instrument_id != self.instrument_id:
                raise ValidationError(
                    f"Lot {lot.lot_id} belongs to {lot.instrument_id}, not {self.instrument_id}"
                )
            if lot.currency != self.currency:
                raise ValidationError(f"Lot {lot.lot_id} is in {lot.currency.code}, not {self.currency.code}")

    @property
    def quantity(self) -> Decimal:
        return decimal_sum(lot.quantity for lot in self.lots)

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    @property
    def cost_basis(self) -> Money:
        return Money(decimal_sum(lot.cost_basis.amount for lot in self.lots), self.currency)

    @property
    def average_cost(self) -> Decimal:
        return safe_divide(self.cost_basis.amount, self.quantity, default=Decimal(0))

    def market_value(self, price: Numeric) -> Money:
        return Money(self.quantity * to_decimal(price, field="price"), self.currency)

    def unrealised_gain(self, price: Numeric) -> Money:
        return self.market_value(price) - self.cost_basis

    def unrealised_split_by_term(self, price: Numeric, as_of: date) -> tuple[Money, Money]:
        """Unrealised gain split into (long-term, short-term), which drives tax planning."""
        unit_price = to_decimal(price, field="price")
        long_term = Money.zero(self.currency)
        short_term = Money.zero(self.currency)
        for lot in self.lots:
            gain = lot.unrealised_gain(unit_price)
            if lot.is_long_term(as_of):
                long_term = long_term + gain
            else:
                short_term = short_term + gain
        return long_term, short_term

    def select_lots(
        self,
        quantity: Numeric,
        method: LotSelectionMethod = LotSelectionMethod.FIFO,
        *,
        as_of: date | None = None,
        specific_lot_ids: Sequence[str] | None = None,
    ) -> tuple[tuple[TaxLot, ...], tuple[TaxLot, ...]]:
        """Choose which lots a sale relieves.

        Returns the lots (or lot fragments) being sold and the lots that remain open.
        FIFO is the regulatory default; HIFO sells the most expensive lots first and
        therefore realises the smallest gain; specific identification lets the
        optimiser name the lots it wants.
        """
        requested = to_decimal(quantity, field="quantity")
        if requested <= 0:
            raise ValidationError("Sale quantity must be positive")
        if requested > self.quantity:
            raise ValidationError(f"Cannot sell {requested} of {self.instrument_id}; only {self.quantity} is held")

        ordered = self._order_lots(method, as_of=as_of, specific_lot_ids=specific_lot_ids)
        sold: list[TaxLot] = []
        remaining: list[TaxLot] = []
        outstanding = requested
        for lot in ordered:
            if outstanding <= 0:
                remaining.append(lot)
                continue
            if lot.quantity <= outstanding:
                sold.append(lot)
                outstanding -= lot.quantity
            else:
                taken, rest = lot.split(outstanding)
                sold.append(taken)
                if rest is not None:
                    remaining.append(rest)
                outstanding = Decimal(0)
        remaining.sort(key=lambda lot: (lot.open_date, lot.lot_id))
        return tuple(sold), tuple(remaining)

    def _order_lots(
        self,
        method: LotSelectionMethod,
        *,
        as_of: date | None,
        specific_lot_ids: Sequence[str] | None,
    ) -> list[TaxLot]:
        lots = list(self.lots)
        if method is LotSelectionMethod.FIFO:
            return sorted(lots, key=lambda lot: (lot.open_date, lot.lot_id))
        if method is LotSelectionMethod.LIFO:
            return sorted(lots, key=lambda lot: (lot.open_date, lot.lot_id), reverse=True)
        if method is LotSelectionMethod.HIFO:
            return sorted(lots, key=lambda lot: (-lot.cost_per_unit, lot.open_date))
        if method is LotSelectionMethod.AVERAGE_COST:
            # Average cost is a reporting convention; lots are still relieved in order.
            return sorted(lots, key=lambda lot: (lot.open_date, lot.lot_id))
        if method is LotSelectionMethod.SPECIFIC_LOT:
            if not specific_lot_ids:
                raise ValidationError("Specific lot selection needs lot identifiers")
            index = {lot.lot_id: lot for lot in lots}
            missing = [lot_id for lot_id in specific_lot_ids if lot_id not in index]
            if missing:
                raise ValidationError(f"Unknown lots for {self.instrument_id}: {missing}")
            chosen = [index[lot_id] for lot_id in specific_lot_ids]
            rest = [lot for lot in lots if lot.lot_id not in set(specific_lot_ids)]
            return chosen + sorted(rest, key=lambda lot: (lot.open_date, lot.lot_id))
        raise ValidationError(f"Unsupported lot selection method {method!r}")  # pragma: no cover

    def with_lots(self, lots: Iterable[TaxLot]) -> Position:
        return replace(self, lots=tuple(lots))

    def add_lot(self, lot: TaxLot) -> Position:
        return self.with_lots((*self.lots, lot))

    def __str__(self) -> str:
        return f"{self.instrument_id}: {self.quantity} @ {self.average_cost} {self.currency.code}"


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionSnapshot:
    """Positions for one portfolio on one date, the unit the reporting layer consumes."""

    portfolio_id: str
    as_of: date
    positions: tuple[Position, ...] = ()
    cash: Money | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def by_instrument(self) -> dict[str, Position]:
        return {position.instrument_id: position for position in self.positions}

    def cost_basis(self, currency: str | Currency) -> Money:
        target = get_currency(currency)
        total = Money.zero(target)
        for position in self.positions:
            if position.currency != target:
                raise ValidationError("Mixed currency snapshot needs FX translation before totals")
            total = total + position.cost_basis
        return total
