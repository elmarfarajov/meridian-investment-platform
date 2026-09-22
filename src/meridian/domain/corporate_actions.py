"""Corporate actions: the events that change what a share is.

A split, a dividend or a spin-off changes the unit being priced. The day before
a 4-for-1 split a share costs 400; the day after it costs 100, and nobody lost
75%. Every price history, every return series and every tax lot that crosses
the ex-date has to be told about the event, or the platform reports a crash
that did not happen and a cost basis that is four times too high.

Each action here knows two numbers about itself:

``price_factor``
    The multiplier that makes a price *before* the ex-date comparable with a
    price on or after it. Back-adjusting a history multiplies every earlier
    price by the product of the factors of every later event - the CRSP
    convention. The factor needs the last cum-event close for the events whose
    size depends on the share price (cash dividends, rights issues, spin-offs).
``quantity_factor``
    How the number of shares held changes on the ex-date.

The dates follow market practice. The *ex-date* is the first day the share
trades without the entitlement; it is the date that moves the price. The
*record date* decides who is entitled; under T+1 settlement (the US since May
2024) it coincides with the ex-date. The *pay date* is when cash or shares
actually arrive, which is what the cash ledger cares about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from ..core.decimals import Numeric, to_decimal
from ..core.exceptions import ValidationError


class CorporateActionType(str, Enum):
    CASH_DIVIDEND = "cash_dividend"
    STOCK_DIVIDEND = "stock_dividend"
    SPLIT = "split"
    SPIN_OFF = "spin_off"
    RIGHTS_ISSUE = "rights_issue"
    CASH_MERGER = "cash_merger"
    STOCK_MERGER = "stock_merger"
    SYMBOL_CHANGE = "symbol_change"

    @property
    def is_capital_change(self) -> bool:
        """Events that change the share count or the unit, as opposed to paying income."""
        return self is not CorporateActionType.CASH_DIVIDEND

    @property
    def is_terminal(self) -> bool:
        """After these, the instrument no longer exists as it was."""
        return self in {CorporateActionType.CASH_MERGER, CorporateActionType.STOCK_MERGER}


class AdjustmentMode(str, Enum):
    """Which events a back-adjusted history takes out."""

    CAPITAL = "capital"  # splits, stock dividends, spin-offs, rights: the unit changes
    TOTAL_RETURN = "total_return"  # capital events and cash dividends reinvested


@dataclass(frozen=True, slots=True, kw_only=True)
class CorporateAction:
    """Fields every corporate action shares."""

    action_id: str
    instrument_id: str
    ex_date: date
    record_date: date | None = None
    pay_date: date | None = None
    announced: date | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValidationError("a corporate action needs an action_id")
        if not self.instrument_id.strip():
            raise ValidationError(f"{self.action_id}: a corporate action needs an instrument")
        if self.announced and self.announced > self.ex_date:
            raise ValidationError(f"{self.action_id}: announced after its own ex-date")
        if self.pay_date and self.pay_date < self.ex_date:
            raise ValidationError(f"{self.action_id}: pay date precedes the ex-date")
        if self.record_date and self.announced and self.record_date < self.announced:
            raise ValidationError(f"{self.action_id}: record date precedes the announcement")

    @property
    def action_type(self) -> CorporateActionType:  # pragma: no cover - every subclass overrides
        raise NotImplementedError

    @property
    def entitlement_date(self) -> date:
        """The date whose holding decides entitlement: the record date if known, else the ex-date."""
        return self.record_date or self.ex_date

    def price_factor(self, cum_price: Decimal | None = None) -> Decimal:
        """Multiplier for prices before the ex-date. 1 means the event does not move the unit price."""
        return Decimal(1)

    @property
    def quantity_factor(self) -> Decimal:
        return Decimal(1)

    def applies_in(self, mode: AdjustmentMode) -> bool:
        return mode is AdjustmentMode.TOTAL_RETURN or self.action_type.is_capital_change

    def describe(self) -> str:
        return f"{self.action_type.value} on {self.instrument_id}, ex {self.ex_date.isoformat()}"


def _require_cum_price(action: CorporateAction, cum_price: Decimal | None) -> Decimal:
    if cum_price is None or cum_price <= 0:
        raise ValidationError(f"{action.action_id}: the adjustment needs a positive cum-event close")
    return cum_price


@dataclass(frozen=True, slots=True, kw_only=True)
class CashDividend(CorporateAction):
    """A cash distribution per share. ``withholding_rate`` is the tax deducted at source."""

    amount: Decimal
    currency: str
    withholding_rate: Decimal = Decimal(0)
    special: bool = False

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        object.__setattr__(self, "amount", to_decimal(self.amount, field="amount"))
        object.__setattr__(self, "withholding_rate", to_decimal(self.withholding_rate, field="withholding_rate"))
        object.__setattr__(self, "currency", self.currency.upper())
        if self.amount <= 0:
            raise ValidationError(f"{self.action_id}: a dividend must be positive")
        if not 0 <= self.withholding_rate < 1:
            raise ValidationError(f"{self.action_id}: withholding must be a fraction below 1")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.CASH_DIVIDEND

    def price_factor(self, cum_price: Decimal | None = None) -> Decimal:
        """(P - D) / P: the share trades lower by the dividend on the ex-date."""
        price = _require_cum_price(self, cum_price)
        if self.amount >= price:
            raise ValidationError(f"{self.action_id}: a dividend of {self.amount} exceeds the price {price}")
        return (price - self.amount) / price

    def net_amount(self) -> Decimal:
        return self.amount * (1 - self.withholding_rate)


@dataclass(frozen=True, slots=True, kw_only=True)
class StockSplit(CorporateAction):
    """``numerator`` new shares for every ``denominator`` old ones. 1-for-10 is a reverse split."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValidationError(f"{self.action_id}: split terms must be positive")
        if self.numerator == self.denominator:
            raise ValidationError(f"{self.action_id}: a {self.numerator}-for-{self.denominator} split changes nothing")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.SPLIT

    @property
    def ratio(self) -> Decimal:
        return Decimal(self.numerator) / Decimal(self.denominator)

    @property
    def is_reverse(self) -> bool:
        return self.numerator < self.denominator

    def price_factor(self, cum_price: Decimal | None = None) -> Decimal:
        return Decimal(self.denominator) / Decimal(self.numerator)

    @property
    def quantity_factor(self) -> Decimal:
        return self.ratio

    def describe(self) -> str:
        kind = "reverse split" if self.is_reverse else "split"
        return f"{self.numerator}-for-{self.denominator} {kind} on {self.instrument_id}, ex {self.ex_date.isoformat()}"


@dataclass(frozen=True, slots=True, kw_only=True)
class StockDividend(CorporateAction):
    """New shares paid as a fraction of the holding: a 5% stock dividend is 0.05."""

    rate: Decimal

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        object.__setattr__(self, "rate", to_decimal(self.rate, field="rate"))
        if self.rate <= 0:
            raise ValidationError(f"{self.action_id}: a stock dividend rate must be positive")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.STOCK_DIVIDEND

    def price_factor(self, cum_price: Decimal | None = None) -> Decimal:
        return Decimal(1) / (1 + self.rate)

    @property
    def quantity_factor(self) -> Decimal:
        return 1 + self.rate


@dataclass(frozen=True, slots=True, kw_only=True)
class SpinOff(CorporateAction):
    """Shares in a new company distributed to the parent's holders.

    ``ratio`` is child shares per parent share. The cost basis is split between
    parent and child by relative market value; issuers publish that fraction
    (in the US on Form 8937), so ``cost_allocation`` takes precedence when it is
    known, and otherwise it is derived from ``child_price``.
    """

    child_instrument_id: str
    ratio: Decimal
    child_price: Decimal | None = None
    cost_allocation: Decimal | None = None

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        object.__setattr__(self, "ratio", to_decimal(self.ratio, field="ratio"))
        if self.ratio <= 0:
            raise ValidationError(f"{self.action_id}: a spin-off ratio must be positive")
        if self.child_price is not None:
            object.__setattr__(self, "child_price", to_decimal(self.child_price, field="child_price"))
        if self.cost_allocation is not None:
            allocation = to_decimal(self.cost_allocation, field="cost_allocation")
            if not 0 < allocation < 1:
                raise ValidationError(f"{self.action_id}: the child's cost allocation must be between 0 and 1")
            object.__setattr__(self, "cost_allocation", allocation)
        if self.child_price is None and self.cost_allocation is None:
            raise ValidationError(f"{self.action_id}: a spin-off needs a child price or a cost allocation")
        if self.child_instrument_id == self.instrument_id:
            raise ValidationError(f"{self.action_id}: a company cannot spin itself off")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.SPIN_OFF

    def child_fraction(self, cum_price: Decimal | None = None) -> Decimal:
        """Share of the pre-event value that moved into the child."""
        if self.cost_allocation is not None:
            return self.cost_allocation
        price = _require_cum_price(self, cum_price)
        assert self.child_price is not None  # guaranteed by __post_init__
        fraction = self.ratio * self.child_price / price
        if not 0 < fraction < 1:
            raise ValidationError(f"{self.action_id}: the child is worth {fraction:.2%} of the parent")
        return fraction

    def price_factor(self, cum_price: Decimal | None = None) -> Decimal:
        return 1 - self.child_fraction(cum_price)


@dataclass(frozen=True, slots=True, kw_only=True)
class RightsIssue(CorporateAction):
    """The right to buy ``ratio`` new shares per share held, at ``subscription_price``.

    The theoretical ex-rights price is the value of the enlarged holding spread
    over the enlarged share count: ``TERP = (P + ratio * S) / (1 + ratio)``.
    """

    ratio: Decimal
    subscription_price: Decimal

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        object.__setattr__(self, "ratio", to_decimal(self.ratio, field="ratio"))
        object.__setattr__(self, "subscription_price", to_decimal(self.subscription_price, field="subscription_price"))
        if self.ratio <= 0 or self.subscription_price <= 0:
            raise ValidationError(f"{self.action_id}: rights terms must be positive")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.RIGHTS_ISSUE

    def theoretical_ex_rights_price(self, cum_price: Decimal) -> Decimal:
        return (cum_price + self.ratio * self.subscription_price) / (1 + self.ratio)

    def rights_value(self, cum_price: Decimal) -> Decimal:
        """What one right is worth: the discount to TERP on ``ratio`` new shares."""
        return (self.theoretical_ex_rights_price(cum_price) - self.subscription_price) * self.ratio

    def price_factor(self, cum_price: Decimal | None = None) -> Decimal:
        price = _require_cum_price(self, cum_price)
        if self.subscription_price >= price:
            return Decimal(1)  # an out-of-the-money right carries no value and moves nothing
        return self.theoretical_ex_rights_price(price) / price


@dataclass(frozen=True, slots=True, kw_only=True)
class CashMerger(CorporateAction):
    """The instrument is bought out for cash; holders are paid and the position closes."""

    cash_per_share: Decimal
    currency: str

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        object.__setattr__(self, "cash_per_share", to_decimal(self.cash_per_share, field="cash_per_share"))
        object.__setattr__(self, "currency", self.currency.upper())
        if self.cash_per_share <= 0:
            raise ValidationError(f"{self.action_id}: merger consideration must be positive")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.CASH_MERGER


@dataclass(frozen=True, slots=True, kw_only=True)
class StockMerger(CorporateAction):
    """Each share becomes ``ratio`` shares of the acquirer, plus optional cash per share."""

    acquirer_instrument_id: str
    ratio: Decimal
    cash_per_share: Decimal = Decimal(0)
    currency: str = "USD"

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        object.__setattr__(self, "ratio", to_decimal(self.ratio, field="ratio"))
        object.__setattr__(self, "cash_per_share", to_decimal(self.cash_per_share, field="cash_per_share"))
        object.__setattr__(self, "currency", self.currency.upper())
        if self.ratio <= 0:
            raise ValidationError(f"{self.action_id}: the exchange ratio must be positive")
        if self.cash_per_share < 0:
            raise ValidationError(f"{self.action_id}: cash consideration cannot be negative")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.STOCK_MERGER


@dataclass(frozen=True, slots=True, kw_only=True)
class SymbolChange(CorporateAction):
    """A new ticker for the same security. Nothing economic happens, which is exactly why it gets lost."""

    old_symbol: str
    new_symbol: str

    def __post_init__(self) -> None:
        CorporateAction.__post_init__(self)
        if not self.new_symbol.strip() or self.new_symbol == self.old_symbol:
            raise ValidationError(f"{self.action_id}: a symbol change needs a different new symbol")

    @property
    def action_type(self) -> CorporateActionType:
        return CorporateActionType.SYMBOL_CHANGE


def split(action_id: str, instrument_id: str, ex_date: date, numerator: int, denominator: int = 1) -> StockSplit:
    """Shorthand for the most common capital event."""
    return StockSplit(
        action_id=action_id, instrument_id=instrument_id, ex_date=ex_date, numerator=numerator, denominator=denominator
    )


def dividend(
    action_id: str,
    instrument_id: str,
    ex_date: date,
    amount: Numeric,
    currency: str,
    *,
    pay_date: date | None = None,
    withholding_rate: Numeric = 0,
) -> CashDividend:
    return CashDividend(
        action_id=action_id,
        instrument_id=instrument_id,
        ex_date=ex_date,
        record_date=ex_date,
        pay_date=pay_date,
        amount=to_decimal(amount, field="amount"),
        currency=currency,
        withholding_rate=to_decimal(withholding_rate, field="withholding_rate"),
    )
