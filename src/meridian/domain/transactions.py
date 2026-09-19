"""Transactions: the only way anything enters or leaves a portfolio.

Every position and every cash balance in the platform is derived from this record,
which is why the sign conventions are fixed here rather than left to each caller:

* ``quantity`` is always positive; the transaction type carries the direction.
* ``cash_impact`` is positive when cash comes in and negative when it leaves.
* Fees and taxes are always positive and always reduce cash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.currency import Currency, get_currency
from ..core.decimals import Numeric, to_decimal
from ..core.enums import TransactionType
from ..core.exceptions import ValidationError
from ..core.money import Money

_REQUIRES_INSTRUMENT = {
    TransactionType.BUY,
    TransactionType.SELL,
    TransactionType.TRANSFER_IN,
    TransactionType.TRANSFER_OUT,
    TransactionType.SPLIT,
    TransactionType.SPIN_OFF,
    TransactionType.DIVIDEND,
}
_CASH_IN = {
    TransactionType.SELL,
    TransactionType.DIVIDEND,
    TransactionType.INTEREST,
    TransactionType.DEPOSIT,
    TransactionType.TRANSFER_IN,
}
_CASH_OUT = {
    TransactionType.BUY,
    TransactionType.FEE,
    TransactionType.TAX,
    TransactionType.WITHDRAWAL,
    TransactionType.TRANSFER_OUT,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Transaction:
    transaction_id: str
    portfolio_id: str
    transaction_type: TransactionType
    trade_date: date
    currency: Currency
    settlement_date: date | None = None
    instrument_id: str | None = None
    quantity: Decimal = Decimal(0)
    price: Decimal = Decimal(0)
    gross_amount: Decimal | None = None
    fees: Decimal = Decimal(0)
    taxes: Decimal = Decimal(0)
    fx_rate: Decimal = Decimal(1)
    lot_id: str | None = None
    external_id: str | None = None
    notes: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", get_currency(self.currency))
        for name in ("quantity", "price", "fees", "taxes", "fx_rate"):
            object.__setattr__(self, name, to_decimal(getattr(self, name), field=name))
        if self.gross_amount is not None:
            object.__setattr__(self, "gross_amount", to_decimal(self.gross_amount, field="gross_amount"))

        if not self.transaction_id.strip():
            raise ValidationError("transaction_id must not be empty")
        if self.quantity < 0:
            raise ValidationError(f"{self.transaction_id}: quantity is unsigned; the type carries the direction")
        if self.price < 0:
            raise ValidationError(f"{self.transaction_id}: price must not be negative")
        if self.fees < 0 or self.taxes < 0:
            raise ValidationError(f"{self.transaction_id}: fees and taxes are expressed as positive amounts")
        if self.fx_rate <= 0:
            raise ValidationError(f"{self.transaction_id}: fx_rate must be positive")
        if self.transaction_type in _REQUIRES_INSTRUMENT and not self.instrument_id:
            raise ValidationError(f"{self.transaction_id}: a {self.transaction_type.value} needs an instrument")
        if self.settlement_date and self.settlement_date < self.trade_date:
            raise ValidationError(f"{self.transaction_id}: settlement precedes the trade date")
        if self.transaction_type.affects_position and self.quantity == 0 and self.transaction_type not in {
            TransactionType.SPIN_OFF
        }:
            raise ValidationError(f"{self.transaction_id}: a {self.transaction_type.value} needs a quantity")

    # ------------------------------------------------------------------ amounts
    @property
    def settles_on(self) -> date:
        return self.settlement_date or self.trade_date

    @property
    def gross(self) -> Money:
        """Consideration before fees and taxes."""
        amount = self.gross_amount if self.gross_amount is not None else self.quantity * self.price
        return Money(amount, self.currency)

    @property
    def total_costs(self) -> Money:
        return Money(self.fees + self.taxes, self.currency)

    @property
    def net(self) -> Money:
        """Cash consideration after costs, always positive."""
        if self.transaction_type in _CASH_IN:
            return self.gross - self.total_costs
        return self.gross + self.total_costs

    @property
    def cash_impact(self) -> Money:
        """Signed effect on the cash balance: positive in, negative out."""
        if self.transaction_type in _CASH_IN:
            return self.net
        if self.transaction_type in _CASH_OUT:
            return -self.net
        return Money.zero(self.currency)

    @property
    def signed_quantity(self) -> Decimal:
        """Effect on the position: positive increases it, negative reduces it."""
        if self.transaction_type in {TransactionType.BUY, TransactionType.TRANSFER_IN, TransactionType.SPIN_OFF}:
            return self.quantity
        if self.transaction_type in {TransactionType.SELL, TransactionType.TRANSFER_OUT}:
            return -self.quantity
        return Decimal(0)

    def in_base_currency(self, base: str | Currency) -> Money:
        """Cash impact translated at the rate recorded on the transaction."""
        return Money(self.cash_impact.amount * self.fx_rate, get_currency(base))

    def __str__(self) -> str:
        instrument = self.instrument_id or self.currency.code
        return f"{self.trade_date} {self.transaction_type.value} {self.quantity} {instrument} @ {self.price}"


def build_trade(
    *,
    transaction_id: str,
    portfolio_id: str,
    instrument_id: str,
    trade_date: date,
    quantity: Numeric,
    price: Numeric,
    currency: str | Currency,
    buy: bool = True,
    fees: Numeric = 0,
    taxes: Numeric = 0,
    settlement_date: date | None = None,
) -> Transaction:
    """Convenience constructor for the most common case, an equity trade."""
    return Transaction(
        transaction_id=transaction_id,
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY if buy else TransactionType.SELL,
        trade_date=trade_date,
        settlement_date=settlement_date,
        quantity=to_decimal(quantity, field="quantity"),
        price=to_decimal(price, field="price"),
        currency=currency,
        fees=to_decimal(fees, field="fees"),
        taxes=to_decimal(taxes, field="taxes"),
    )
