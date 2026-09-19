"""Instruments: what the platform can hold.

Reference data is modelled as immutable objects with validated identifiers. The
type hierarchy stays deliberately shallow - an equity, a bond and a fund share
almost everything except the handful of fields that drive valuation - because deep
inheritance in reference data is how vendor systems become impossible to extend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.currency import Currency, get_currency
from ..core.daycount import DayCountConvention
from ..core.decimals import Numeric, to_decimal
from ..core.enums import AssetClass, Frequency, InstrumentType, SecurityStatus
from ..core.exceptions import ValidationError
from ..core.identifiers import CUSIP, FIGI, ISIN, SEDOL, Ticker


@dataclass(frozen=True, slots=True)
class SecurityIdentifiers:
    """The identifier set for one security; at least one must be present."""

    isin: ISIN | None = None
    cusip: CUSIP | None = None
    sedol: SEDOL | None = None
    figi: FIGI | None = None
    ticker: Ticker | None = None

    def __post_init__(self) -> None:
        if not any((self.isin, self.cusip, self.sedol, self.figi, self.ticker)):
            raise ValidationError("A security needs at least one identifier")

    @property
    def primary(self) -> str:
        """Preferred identifier, in the order a global book would use."""
        for identifier in (self.isin, self.figi, self.cusip, self.sedol, self.ticker):
            if identifier is not None:
                return str(identifier)
        raise ValidationError("No identifier available")  # pragma: no cover - guarded in __post_init__

    def as_dict(self) -> dict[str, str]:
        mapping = {
            "isin": self.isin,
            "cusip": self.cusip,
            "sedol": self.sedol,
            "figi": self.figi,
            "ticker": self.ticker,
        }
        return {key: str(value) for key, value in mapping.items() if value is not None}


@dataclass(frozen=True, slots=True, kw_only=True)
class Instrument:
    """Base reference data shared by every holdable security."""

    instrument_id: str
    name: str
    instrument_type: InstrumentType
    currency: Currency
    identifiers: SecurityIdentifiers
    country: str | None = None
    exchange: str | None = None
    calendar: str = "XNYS"
    status: SecurityStatus = SecurityStatus.ACTIVE
    multiplier: Decimal = Decimal(1)
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValidationError("instrument_id must not be empty")
        if not self.name.strip():
            raise ValidationError(f"{self.instrument_id}: name must not be empty")
        object.__setattr__(self, "currency", get_currency(self.currency))
        object.__setattr__(self, "multiplier", to_decimal(self.multiplier, field="multiplier"))
        if self.multiplier <= 0:
            raise ValidationError(f"{self.instrument_id}: multiplier must be positive")
        if self.country is not None and len(self.country) != 2:
            raise ValidationError(f"{self.instrument_id}: country must be a two-letter code")

    @property
    def asset_class(self) -> AssetClass:
        return self.instrument_type.asset_class

    @property
    def is_tradable(self) -> bool:
        return self.status is SecurityStatus.ACTIVE

    def __str__(self) -> str:
        return f"{self.instrument_id} ({self.name})"


@dataclass(frozen=True, slots=True, kw_only=True)
class Equity(Instrument):
    """Listed shares, with the classification a risk model and a compliance rule need."""

    instrument_type: InstrumentType = InstrumentType.COMMON_STOCK
    sector: str | None = None
    industry: str | None = None
    issuer_id: str | None = None
    shares_outstanding: Decimal | None = None

    def __post_init__(self) -> None:
        # dataclass(slots=True) rebuilds the class, which breaks the zero-argument
        # super() closure, so the base validation is invoked explicitly.
        Instrument.__post_init__(self)
        if self.instrument_type.asset_class is not AssetClass.EQUITY:
            raise ValidationError(f"{self.instrument_id}: {self.instrument_type} is not an equity type")
        if self.shares_outstanding is not None:
            shares = to_decimal(self.shares_outstanding, field="shares_outstanding")
            if shares <= 0:
                raise ValidationError(f"{self.instrument_id}: shares outstanding must be positive")
            object.__setattr__(self, "shares_outstanding", shares)


@dataclass(frozen=True, slots=True, kw_only=True)
class Fund(Instrument):
    """Pooled vehicles: ETFs, mutual funds and private funds."""

    instrument_type: InstrumentType = InstrumentType.ETF
    expense_ratio: Decimal | None = None
    benchmark_id: str | None = None
    inception: date | None = None

    def __post_init__(self) -> None:
        # dataclass(slots=True) rebuilds the class, which breaks the zero-argument
        # super() closure, so the base validation is invoked explicitly.
        Instrument.__post_init__(self)
        if self.expense_ratio is not None:
            ratio = to_decimal(self.expense_ratio, field="expense_ratio")
            if not 0 <= ratio < 1:
                raise ValidationError(f"{self.instrument_id}: expense ratio must be a decimal fraction below 1")
            object.__setattr__(self, "expense_ratio", ratio)


@dataclass(frozen=True, slots=True, kw_only=True)
class Bond(Instrument):
    """A fixed income security with the terms needed to accrue and value it."""

    instrument_type: InstrumentType = InstrumentType.CORPORATE_BOND
    coupon: Decimal = Decimal(0)
    maturity: date | None = None
    issue_date: date | None = None
    face_value: Decimal = Decimal(100)
    coupon_frequency: Frequency = Frequency.SEMI_ANNUAL
    day_count: DayCountConvention = DayCountConvention.THIRTY_360_US
    issuer_id: str | None = None
    rating: str | None = None
    seniority: str | None = None

    def __post_init__(self) -> None:
        # dataclass(slots=True) rebuilds the class, which breaks the zero-argument
        # super() closure, so the base validation is invoked explicitly.
        Instrument.__post_init__(self)
        object.__setattr__(self, "coupon", to_decimal(self.coupon, field="coupon"))
        object.__setattr__(self, "face_value", to_decimal(self.face_value, field="face_value"))
        if self.coupon < 0:
            raise ValidationError(f"{self.instrument_id}: coupon must not be negative")
        if self.face_value <= 0:
            raise ValidationError(f"{self.instrument_id}: face value must be positive")
        if self.maturity and self.issue_date and self.maturity <= self.issue_date:
            raise ValidationError(f"{self.instrument_id}: maturity must be after the issue date")

    def is_matured(self, as_of: date) -> bool:
        return self.maturity is not None and as_of >= self.maturity


@dataclass(frozen=True, slots=True, kw_only=True)
class CashInstrument(Instrument):
    """A currency balance, modelled as an instrument so cash sits in the same book."""

    instrument_type: InstrumentType = InstrumentType.CASH

    @classmethod
    def for_currency(cls, currency: str | Currency, calendar: str = "XNYS") -> CashInstrument:
        resolved = get_currency(currency)
        return cls(
            instrument_id=f"CASH.{resolved.code}",
            name=f"{resolved.name} cash",
            currency=resolved,
            identifiers=SecurityIdentifiers(ticker=Ticker(f"CASH{resolved.code}")),
            calendar=calendar,
        )


def instrument_price_scale(instrument: Instrument) -> Decimal:
    """Factor turning a quoted price into a value per unit held.

    Equities quote per share, bonds quote per 100 of face, and derivatives carry a
    contract multiplier. Getting this wrong is a classic source of valuation errors.
    """
    if isinstance(instrument, Bond):
        return instrument.face_value / Decimal(100) * instrument.multiplier
    return instrument.multiplier
