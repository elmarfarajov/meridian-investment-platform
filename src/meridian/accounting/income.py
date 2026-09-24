"""Income: dividends with withholding tax, and interest that accrues day by day.

**Dividends.** A dividend is earned on the ex-date and paid on the pay date,
often two or three weeks later. Between the two it is a receivable - an asset
the book owns but the custodian has not yet paid - and a reconciliation that
ignores that window reports a cash break every quarter.

Cross-border dividends are paid net of tax withheld by the issuer's country.
The statutory rate is often higher than the double-taxation treaty rate, and
the difference can be reclaimed, slowly and with paperwork. Germany withholds
26.375% and the US-Germany treaty allows 15%; Switzerland withholds 35% against
a 15% treaty rate. The reclaimable part is an asset, not an expense, and
booking it as an expense understates the fund's income by several basis points
a year - a classic and expensive back-office error.

**Interest.** A bond earns its coupon a day at a time on its own day-count
convention. The buyer of a bond pays the seller the interest accrued since the
last coupon and recovers it from the next one, so interest *income* is the
coupon received less the accrued interest bought. The valuation carries the
full accrual as an asset every day; the ledger records the accrued interest
purchased as a receivable and the coupon when it is paid.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache

from ..analytics.bonds import FixedRateBond
from ..core.decimals import to_decimal
from ..core.exceptions import ValidationError
from ..domain.instruments import Bond, Instrument, instrument_price_scale


@dataclass(frozen=True, slots=True)
class WithholdingRate:
    statutory: Decimal
    treaty: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "statutory", to_decimal(self.statutory, field="statutory"))
        object.__setattr__(self, "treaty", to_decimal(self.treaty, field="treaty"))
        if not 0 <= self.treaty <= self.statutory < 1:
            raise ValidationError("withholding needs 0 <= treaty <= statutory < 1")

    @property
    def reclaimable(self) -> Decimal:
        return self.statutory - self.treaty


#: Rates for a UK-resident investor's account, by the issuer's country.
DEFAULT_WITHHOLDING: dict[str, WithholdingRate] = {
    "US": WithholdingRate(Decimal("0"), Decimal("0")),  # a US person: no withholding at source
    "GB": WithholdingRate(Decimal("0"), Decimal("0")),
    "IE": WithholdingRate(Decimal("0"), Decimal("0")),  # UCITS ETFs pay gross to non-residents
    "DE": WithholdingRate(Decimal("0.26375"), Decimal("0.15")),
    "CH": WithholdingRate(Decimal("0.35"), Decimal("0.15")),
    "FR": WithholdingRate(Decimal("0.128"), Decimal("0.128")),
    "JP": WithholdingRate(Decimal("0.15315"), Decimal("0.10")),
}


@dataclass(frozen=True, slots=True)
class WithholdingPolicy:
    rates: Mapping[str, WithholdingRate] = field(default_factory=lambda: dict(DEFAULT_WITHHOLDING))
    reclaim: bool = True

    def rate_for(self, country: str | None) -> WithholdingRate:
        return self.rates.get((country or "").upper(), WithholdingRate(Decimal(0), Decimal(0)))


@dataclass(frozen=True, slots=True)
class DividendSplit:
    """A gross dividend divided into what is paid, what is reclaimable and what is lost."""

    gross: Decimal
    withheld: Decimal
    reclaimable: Decimal

    @property
    def net_paid(self) -> Decimal:
        return self.gross - self.withheld

    @property
    def tax_expense(self) -> Decimal:
        return self.withheld - self.reclaimable


def split_dividend(gross: Decimal, rate: WithholdingRate, *, reclaim: bool = True, precision: Decimal) -> DividendSplit:
    withheld = (gross * rate.statutory).quantize(precision)
    reclaimable = (gross * rate.reclaimable).quantize(precision) if reclaim else Decimal(0)
    return DividendSplit(gross, withheld, min(reclaimable, withheld))


# ---------------------------------------------------------------------------- bonds
@lru_cache(maxsize=128)
def _analytic_bond(
    issue: date, maturity: date, coupon: Decimal, frequency: str, day_count: str, name: str
) -> FixedRateBond:
    from ..core.daycount import DayCountConvention
    from ..core.enums import Frequency

    return FixedRateBond.create(
        issue_date=issue,
        maturity=maturity,
        coupon_rate=float(coupon),
        face_value=100.0,
        frequency=Frequency(frequency),
        day_count=DayCountConvention(day_count),
        name=name,
    )


def analytic_bond(bond: Bond) -> FixedRateBond:
    """The analytics-layer bond for a security-master bond, priced per 100 of face."""
    if bond.issue_date is None or bond.maturity is None:
        raise ValidationError(f"{bond.instrument_id}: accrual needs an issue date and a maturity")
    return _analytic_bond(
        bond.issue_date,
        bond.maturity,
        bond.coupon,
        bond.coupon_frequency.value,
        bond.day_count.value,
        bond.instrument_id,
    )


def accrued_per_unit(instrument: Instrument, day: date) -> Decimal:
    """Accrued interest per unit held, in the instrument's currency; zero for anything but a bond."""
    if not isinstance(instrument, Bond) or instrument.coupon == 0:
        return Decimal(0)
    if instrument.issue_date and day < instrument.issue_date:
        return Decimal(0)
    if instrument.maturity and day >= instrument.maturity:
        return Decimal(0)
    per_hundred = Decimal(repr(round(analytic_bond(instrument).accrued_interest(day), 10)))
    return per_hundred * instrument_price_scale(instrument)


@dataclass(frozen=True, slots=True)
class CouponPayment:
    instrument_id: str
    payment_date: date
    per_unit: Decimal
    accrual_start: date | None
    accrual_end: date | None


def coupon_schedule(bond: Bond, start: date, end: date) -> list[CouponPayment]:
    """Coupons paid in ``(start, end]``, per unit held, in the bond's currency."""
    scale = instrument_price_scale(bond)
    payments: list[CouponPayment] = []
    for flow in analytic_bond(bond).cash_flows():
        if start < flow.payment_date <= end:
            coupon_only = Decimal(repr(round(flow.amount - (100.0 if "redemption" in flow.kind else 0.0), 10)))
            payments.append(
                CouponPayment(
                    bond.instrument_id,
                    flow.payment_date,
                    coupon_only * scale,
                    flow.accrual_start,
                    flow.accrual_end,
                )
            )
    return payments
