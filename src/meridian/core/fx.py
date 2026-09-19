"""Foreign exchange rates and conversion.

A rate is always quoted as "one unit of base buys this many units of quote", and a
table can answer a pair three ways: directly, by inverting the opposite quote, or
by crossing through a pivot currency (USD by default). Multi-currency portfolios
need all three, because market data rarely arrives for every pair a client holds.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .currency import Currency, get_currency
from .decimals import Numeric, to_decimal
from .exceptions import RateNotFoundError, ValidationError
from .money import Money


@dataclass(frozen=True, slots=True)
class FxRate:
    base: Currency
    quote: Currency
    rate: Decimal
    as_of: date | None = None

    def __init__(self, base: str | Currency, quote: str | Currency, rate: Numeric, as_of: date | None = None) -> None:
        object.__setattr__(self, "base", get_currency(base))
        object.__setattr__(self, "quote", get_currency(quote))
        value = to_decimal(rate, field="rate")
        if value <= 0:
            raise ValidationError(f"FX rate must be positive, got {value}")
        object.__setattr__(self, "rate", value)
        object.__setattr__(self, "as_of", as_of)

    @property
    def pair(self) -> str:
        return f"{self.base.code}{self.quote.code}"

    def inverse(self) -> FxRate:
        return FxRate(self.quote, self.base, Decimal(1) / self.rate, self.as_of)

    def convert(self, amount: Money) -> Money:
        if amount.currency != self.base:
            raise ValidationError(f"{self.pair} converts from {self.base.code}, not {amount.currency.code}")
        return Money(amount.amount * self.rate, self.quote)

    def __str__(self) -> str:
        return f"{self.pair} {self.rate}"


class FxTable:
    """A set of rates for one valuation date, with inversion and cross rates."""

    def __init__(self, rates: Iterable[FxRate] = (), *, pivot: str | Currency = "USD", as_of: date | None = None) -> None:
        self._rates: dict[tuple[str, str], FxRate] = {}
        self.pivot = get_currency(pivot)
        self.as_of = as_of
        for rate in rates:
            self.add(rate)

    def add(self, rate: FxRate) -> FxTable:
        self._rates[(rate.base.code, rate.quote.code)] = rate
        return self

    def __len__(self) -> int:
        return len(self._rates)

    def __contains__(self, pair: tuple[str, str]) -> bool:
        return pair in self._rates

    def rate(self, base: str | Currency, quote: str | Currency) -> FxRate:
        """Find a rate directly, by inversion, or by crossing through the pivot."""
        base_currency, quote_currency = get_currency(base), get_currency(quote)
        if base_currency == quote_currency:
            return FxRate(base_currency, quote_currency, Decimal(1), self.as_of)

        direct = self._rates.get((base_currency.code, quote_currency.code))
        if direct is not None:
            return direct

        opposite = self._rates.get((quote_currency.code, base_currency.code))
        if opposite is not None:
            return opposite.inverse()

        # Both legs are quoted as "one unit of the currency buys this much pivot", so
        # crossing divides one by the other: EURGBP = EURUSD / GBPUSD.
        base_leg = self._leg_to_pivot(base_currency)
        quote_leg = self._leg_to_pivot(quote_currency)
        if base_leg is None or quote_leg is None:
            raise RateNotFoundError(
                f"No direct, inverse or {self.pivot.code} cross rate connects "
                f"{base_currency.code} and {quote_currency.code}"
            )
        return FxRate(base_currency, quote_currency, base_leg / quote_leg, self.as_of)

    def _leg_to_pivot(self, currency: Currency) -> Decimal | None:
        """Rate that converts one unit of ``currency`` into the pivot, or back out of it."""
        if currency == self.pivot:
            return Decimal(1)
        direct = self._rates.get((currency.code, self.pivot.code))
        if direct is not None:
            return direct.rate
        opposite = self._rates.get((self.pivot.code, currency.code))
        if opposite is not None:
            return Decimal(1) / opposite.rate
        return None

    def convert(self, amount: Money, to: str | Currency) -> Money:
        target = get_currency(to)
        if amount.currency == target:
            return amount
        return self.rate(amount.currency, target).convert(amount)

    def pairs(self) -> tuple[str, ...]:
        return tuple(sorted(f"{base}{quote}" for base, quote in self._rates))
