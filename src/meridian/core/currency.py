"""ISO 4217 currencies.

Only the currencies the platform actually handles are registered. Each carries its
number of minor units, because rounding a JPY amount to two decimals - or a KWD
amount to fewer than three - is a real reconciliation break rather than a
cosmetic issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .exceptions import UnknownCurrencyError


@dataclass(frozen=True, slots=True)
class Currency:
    code: str
    name: str
    minor_units: int
    numeric_code: str

    def __post_init__(self) -> None:
        if len(self.code) != 3 or not self.code.isalpha() or not self.code.isupper():
            raise UnknownCurrencyError(f"{self.code!r} is not a three-letter uppercase ISO 4217 code")
        if not 0 <= self.minor_units <= 4:
            raise UnknownCurrencyError(f"{self.code} has an implausible minor unit count: {self.minor_units}")

    @property
    def precision(self) -> Decimal:
        """Smallest representable amount, e.g. ``0.01`` for USD and ``1`` for JPY."""
        return Decimal(1).scaleb(-self.minor_units)

    def __str__(self) -> str:
        return self.code


_REGISTRY: dict[str, Currency] = {
    currency.code: currency
    for currency in (
        Currency("USD", "US Dollar", 2, "840"),
        Currency("EUR", "Euro", 2, "978"),
        Currency("GBP", "Pound Sterling", 2, "826"),
        Currency("CHF", "Swiss Franc", 2, "756"),
        Currency("JPY", "Yen", 0, "392"),
        Currency("CAD", "Canadian Dollar", 2, "124"),
        Currency("AUD", "Australian Dollar", 2, "036"),
        Currency("SEK", "Swedish Krona", 2, "752"),
        Currency("NOK", "Norwegian Krone", 2, "578"),
        Currency("DKK", "Danish Krone", 2, "208"),
        Currency("HKD", "Hong Kong Dollar", 2, "344"),
        Currency("SGD", "Singapore Dollar", 2, "702"),
        Currency("CNY", "Yuan Renminbi", 2, "156"),
        Currency("KRW", "Won", 0, "410"),
        Currency("INR", "Indian Rupee", 2, "356"),
        Currency("BRL", "Brazilian Real", 2, "986"),
        Currency("MXN", "Mexican Peso", 2, "484"),
        Currency("ZAR", "Rand", 2, "710"),
        Currency("TRY", "Turkish Lira", 2, "949"),
        Currency("AED", "UAE Dirham", 2, "784"),
        Currency("AZN", "Azerbaijan Manat", 2, "944"),
        Currency("KWD", "Kuwaiti Dinar", 3, "414"),
    )
}

USD = _REGISTRY["USD"]
EUR = _REGISTRY["EUR"]
GBP = _REGISTRY["GBP"]
JPY = _REGISTRY["JPY"]
CHF = _REGISTRY["CHF"]


def get_currency(code: str | Currency) -> Currency:
    """Look up a currency by ISO code, case-insensitively."""
    if isinstance(code, Currency):
        return code
    try:
        return _REGISTRY[code.strip().upper()]
    except (KeyError, AttributeError) as exc:
        raise UnknownCurrencyError(f"{code!r} is not a registered currency") from exc


def register_currency(currency: Currency) -> Currency:
    """Add a currency at runtime, for instruments denominated outside the default set."""
    _REGISTRY[currency.code] = currency
    return currency


def all_currencies() -> tuple[Currency, ...]:
    return tuple(sorted(_REGISTRY.values(), key=lambda currency: currency.code))
