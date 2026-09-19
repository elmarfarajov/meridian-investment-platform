"""Clients, households, accounts, portfolios and benchmarks.

Wealth platforms report at the level a client thinks in - "how are *we* doing?" -
which spans several legal accounts with different tax treatment. Institutional
platforms report per mandate. The same hierarchy serves both: a household owns
accounts, an account holds one portfolio, and a portfolio is measured against a
benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.currency import Currency, get_currency
from ..core.decimals import to_decimal
from ..core.enums import AccountType
from ..core.exceptions import ValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class Benchmark:
    benchmark_id: str
    name: str
    currency: Currency
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.benchmark_id.strip():
            raise ValidationError("benchmark_id must not be empty")
        object.__setattr__(self, "currency", get_currency(self.currency))


@dataclass(frozen=True, slots=True, kw_only=True)
class BlendedBenchmark(Benchmark):
    """A weighted blend, e.g. 60% equity and 40% aggregate bonds."""

    components: tuple[tuple[str, Decimal], ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.components:
            raise ValidationError(f"{self.benchmark_id}: a blend needs components")
        weights = tuple((code, to_decimal(weight, field="weight")) for code, weight in self.components)
        total = sum(weight for _, weight in weights)
        if abs(total - Decimal(1)) > Decimal("0.0001"):
            raise ValidationError(f"{self.benchmark_id}: component weights sum to {total}, not 1")
        object.__setattr__(self, "components", weights)


@dataclass(frozen=True, slots=True, kw_only=True)
class Client:
    client_id: str
    name: str
    domicile: str | None = None
    tax_residence: str | None = None
    onboarded: date | None = None

    def __post_init__(self) -> None:
        if not self.client_id.strip() or not self.name.strip():
            raise ValidationError("A client needs an identifier and a name")


@dataclass(frozen=True, slots=True, kw_only=True)
class Household:
    """A reporting group: the accounts a family or institution sees as one pot."""

    household_id: str
    name: str
    client_ids: tuple[str, ...] = ()
    base_currency: Currency = field(default_factory=lambda: get_currency("USD"))

    def __post_init__(self) -> None:
        if not self.household_id.strip():
            raise ValidationError("household_id must not be empty")
        object.__setattr__(self, "base_currency", get_currency(self.base_currency))


@dataclass(frozen=True, slots=True, kw_only=True)
class Account:
    """A legal account at a custodian, which is what tax rules actually apply to."""

    account_id: str
    name: str
    account_type: AccountType
    base_currency: Currency
    household_id: str | None = None
    client_id: str | None = None
    custodian: str | None = None
    opened: date | None = None
    closed: date | None = None
    calendar: str = "XNYS"

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValidationError("account_id must not be empty")
        object.__setattr__(self, "base_currency", get_currency(self.base_currency))
        if self.opened and self.closed and self.closed < self.opened:
            raise ValidationError(f"{self.account_id}: closed date precedes opened date")

    @property
    def is_taxable(self) -> bool:
        return not self.account_type.is_tax_deferred

    def is_open(self, as_of: date) -> bool:
        if self.opened and as_of < self.opened:
            return False
        return not (self.closed and as_of > self.closed)


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentPolicy:
    """The mandate: what the portfolio is allowed and expected to do."""

    target_equity_weight: Decimal | None = None
    max_single_issuer_weight: Decimal | None = None
    max_cash_weight: Decimal | None = None
    tracking_error_budget: Decimal | None = None
    excluded_sectors: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        for name in ("target_equity_weight", "max_single_issuer_weight", "max_cash_weight", "tracking_error_budget"):
            value = getattr(self, name)
            if value is None:
                continue
            decimal_value = to_decimal(value, field=name)
            if not 0 <= decimal_value <= 1:
                raise ValidationError(f"{name} must be a decimal fraction between 0 and 1")
            object.__setattr__(self, name, decimal_value)


@dataclass(frozen=True, slots=True, kw_only=True)
class Portfolio:
    """A managed book of holdings inside an account."""

    portfolio_id: str
    name: str
    base_currency: Currency
    account_id: str | None = None
    benchmark_id: str | None = None
    strategy: str | None = None
    inception: date | None = None
    policy: InvestmentPolicy = field(default_factory=InvestmentPolicy)

    def __post_init__(self) -> None:
        if not self.portfolio_id.strip():
            raise ValidationError("portfolio_id must not be empty")
        object.__setattr__(self, "base_currency", get_currency(self.base_currency))

    def __str__(self) -> str:
        return f"{self.portfolio_id} ({self.name}, {self.base_currency.code})"
