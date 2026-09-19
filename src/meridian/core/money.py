"""Money: an amount that knows its currency and refuses to lose a cent.

Three rules are enforced, and each one exists because breaking it causes a real
reconciliation break:

1. **Amounts are decimal.** Cash balances are exact, not "approximately right".
2. **Currencies never mix silently.** Adding USD to EUR raises rather than
   producing a meaningless number; conversion must go through an explicit FX rate.
3. **Splitting money conserves the total.** :meth:`Money.allocate` distributes an
   amount across weights so the parts add back exactly to the whole, which is what
   an allocation of a block trade across client accounts requires.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Union

from .currency import Currency, get_currency
from .decimals import Numeric, to_decimal
from .exceptions import CurrencyMismatchError, ValidationError


@dataclass(frozen=True, slots=True, order=False)
class Money:
    amount: Decimal
    currency: Currency

    def __init__(self, amount: Numeric, currency: str | Currency) -> None:
        object.__setattr__(self, "amount", to_decimal(amount, field="amount"))
        object.__setattr__(self, "currency", get_currency(currency))

    # ------------------------------------------------------------------ helpers
    @classmethod
    def zero(cls, currency: str | Currency) -> Money:
        return cls(Decimal(0), currency)

    def _check(self, other: Money, operation: str) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency.code, other.currency.code, operation)

    def rounded(self) -> Money:
        """Round to the currency's minor units using banker's rounding."""
        return Money(self.amount.quantize(self.currency.precision, rounding=ROUND_HALF_EVEN), self.currency)

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    # --------------------------------------------------------------- arithmetic
    def __add__(self, other: Money) -> Money:
        self._check(other, "add")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other, "subtract")
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Numeric) -> Money:
        if isinstance(factor, Money):
            raise ValidationError("Multiplying money by money is not meaningful")
        return Money(self.amount * to_decimal(factor, field="factor"), self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor: Union[Numeric, "Money"]) -> Union["Money", Decimal]:
        """Dividing by a number scales the amount; dividing by money gives a ratio."""
        if isinstance(divisor, Money):
            self._check(divisor, "divide")
            if divisor.amount == 0:
                raise ValidationError("Division by a zero money amount")
            return self.amount / divisor.amount
        value = to_decimal(divisor, field="divisor")
        if value == 0:
            raise ValidationError("Division by zero")
        return Money(self.amount / value, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    # --------------------------------------------------------------- comparison
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __hash__(self) -> int:
        return hash((self.currency.code, self.amount))

    def __lt__(self, other: Money) -> bool:
        self._check(other, "compare")
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check(other, "compare")
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._check(other, "compare")
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._check(other, "compare")
        return self.amount >= other.amount

    # ----------------------------------------------------------------- division
    def allocate(self, weights: Sequence[Numeric]) -> list[Money]:
        """Split the amount across weights so the parts sum back to the whole.

        Rounding each share independently loses or invents cents; instead each share
        is floored to the currency's precision and the remaining smallest units are
        handed out one at a time, largest fractional remainder first. This is how a
        block trade is allocated across client accounts without breaking cash.
        """
        decimal_weights = [to_decimal(weight, field="weight") for weight in weights]
        if not decimal_weights:
            raise ValidationError("At least one weight is required")
        if any(weight < 0 for weight in decimal_weights):
            raise ValidationError("Allocation weights must be non-negative")
        total_weight = sum(decimal_weights)
        if total_weight == 0:
            raise ValidationError("Allocation weights must not sum to zero")

        precision = self.currency.precision
        unit = precision
        total_units = (self.amount / precision).to_integral_value(rounding=ROUND_HALF_EVEN)
        raw_shares = [total_units * weight / total_weight for weight in decimal_weights]
        floors = [share.to_integral_value(rounding=ROUND_FLOOR) for share in raw_shares]
        remainder = int(total_units - sum(floors))

        order = sorted(range(len(raw_shares)), key=lambda i: raw_shares[i] - floors[i], reverse=True)
        allocation = list(floors)
        step = 1 if remainder >= 0 else -1
        for index in range(abs(remainder)):
            allocation[order[index % len(order)]] += step

        return [Money(units * unit, self.currency) for units in allocation]

    # ------------------------------------------------------------------ display
    def __str__(self) -> str:
        quantised = self.amount.quantize(self.currency.precision, rounding=ROUND_HALF_EVEN)
        return f"{quantised:,} {self.currency.code}"

    def __repr__(self) -> str:
        return f"Money({self.amount}, '{self.currency.code}')"


def money_sum(amounts: Iterable[Money], currency: str | Currency | None = None) -> Money:
    """Sum money safely; an empty iterable needs an explicit currency."""
    total: Money | None = None
    for amount in amounts:
        total = amount if total is None else total + amount
    if total is not None:
        return total
    if currency is None:
        raise ValidationError("Summing an empty sequence needs an explicit currency")
    return Money.zero(currency)
