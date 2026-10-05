"""The tax side of a rebalance: what each lot costs to sell, and what a year's realisations cost in tax.

**Selling a lot.** A sale of one unit of a lot realises the price less the lot's
tax basis. Taxed at the short-term rate (ordinary income, 37% plus the 3.8% net
investment income tax) if the holding period is a year or less, at the long-term
rate (20% plus 3.8%) if longer. Per unit of value sold, the tax is

    t = rate(term) x (price - basis) / price

which is negative for a lot standing at a loss: selling it *saves* tax, because
the loss offsets gains realised elsewhere. That negative number is what
tax-loss harvesting harvests.

**The wash-sale rule.** A loss is disallowed if the same security is bought
within 30 days before or after the sale. Two consequences for an optimiser:

* a lot cannot harvest a loss today if *another* lot of the security was
  **bought in the last 30 days** - the shares being sold are never their own
  replacement, so a lot bought last week and sold today at a loss is a loss;
* a security whose loss lots are being sold **cannot be bought** in the same
  rebalance, nor for 30 days after. The optimiser handles the second as a
  constraint it discovers and imposes (:mod:`.rebalance`).

**A year's tax.** Realised gains and losses are netted within the year, short
against short and long against long, then across; a net loss offsets up to
$3,000 of ordinary income and the rest carries forward (Schedule D, as in Day
3). :class:`TaxAccount` keeps that ledger for a simulated account.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from ..accounting.tax import DEFAULT_RATES, TaxRates
from .assets import LotState, TradableAsset

WASH_SALE_DAYS = 30
ORDINARY_OFFSET = 3_000.0


def short_rate(rates: TaxRates = DEFAULT_RATES) -> float:
    return float(rates.short_term + rates.net_investment_income)


def long_rate(rates: TaxRates = DEFAULT_RATES) -> float:
    return float(rates.long_term + rates.net_investment_income)


def lot_tax_rate(
    lot: LotState,
    price: float,
    as_of: date,
    *,
    rates: TaxRates = DEFAULT_RATES,
    harvest: bool = True,
    wash_blocked: bool = False,
    loss_value: float = 1.0,
    unit_value: float | None = None,
    loss_rate: float | None = None,
) -> float:
    """Tax per unit of value sold from this lot (negative: a saving).

    ``harvest=False`` values a loss at nothing (the tax-aware but harvest-blind
    manager); ``wash_blocked`` marks a loss the wash-sale rule would disallow;
    ``loss_value`` discounts a loss that may only be used in a later year.
    ``loss_rate`` is the rate a loss will actually save: a short-term loss
    offsets short-term gains first, but where there are none it offsets
    long-term gains, and is worth only the long-term rate. ``unit_value`` is
    what a unit sells for when it differs from the clean price the gain is
    measured on (a bond's accrued interest).
    """
    gain_share = (price - lot.basis_per_unit) / (unit_value or price)
    rate = long_rate(rates) if lot.is_long_term(as_of) else short_rate(rates)
    if gain_share >= 0:
        return rate * gain_share
    if not harvest or wash_blocked:
        return 0.0
    return (rate if loss_rate is None else loss_rate) * gain_share * loss_value


def recently_bought(
    assets: Iterable[TradableAsset], as_of: date, days: int = WASH_SALE_DAYS
) -> dict[str, frozenset[str]]:
    """The lots opened within the wash-sale window before ``as_of``, by asset."""
    recent: dict[str, frozenset[str]] = {}
    for asset in assets:
        lots = frozenset(lot.lot_id for lot in asset.lots if 0 <= (as_of - lot.opened).days <= days)
        if lots:
            recent[asset.asset_id] = lots
    return recent


def has_replacement(lot: LotState, recent: dict[str, frozenset[str]]) -> bool:
    """Whether a loss on this lot is a wash sale: another lot of the asset was bought within the window."""
    return bool(recent.get(lot.asset_id, frozenset()) - {lot.lot_id})


@dataclass
class TaxYear:
    short_gains: float = 0.0
    short_losses: float = 0.0
    long_gains: float = 0.0
    long_losses: float = 0.0


@dataclass
class TaxAccount:
    """Realised gains and losses year by year, netted as Schedule D nets them, with carryforward."""

    rates: TaxRates = DEFAULT_RATES
    years: dict[int, TaxYear] = field(default_factory=dict)
    carried: tuple[float, float] = (0.0, 0.0)  # (short, long) losses carried into the next year
    paid: dict[int, float] = field(default_factory=dict)

    def realise(self, day: date, gain: float, long_term: bool) -> None:
        year = self.years.setdefault(day.year, TaxYear())
        if long_term:
            if gain >= 0:
                year.long_gains += gain
            else:
                year.long_losses -= gain
        elif gain >= 0:
            year.short_gains += gain
        else:
            year.short_losses -= gain

    def close_year(self, year_number: int) -> float:
        """Net the year, pay its tax, and carry any unused loss forward."""
        year = self.years.get(year_number, TaxYear())
        carried_short, carried_long = self.carried
        short = year.short_gains - year.short_losses - carried_short
        long = year.long_gains - year.long_losses - carried_long
        if short * long < 0:  # net across: what is left keeps the character of the larger side
            total = short + long
            short, long = (total, 0.0) if (total >= 0) == (short > 0) else (0.0, total)
        tax = max(short, 0.0) * short_rate(self.rates) + max(long, 0.0) * long_rate(self.rates)
        short_loss, long_loss = -min(short, 0.0), -min(long, 0.0)
        # A net loss offsets up to $3,000 of ordinary income, short-term losses used
        # first (Publication 550). The deduction saves the ordinary rate; the net
        # investment income tax applies only to a positive net, so it saves nothing.
        from_short = min(short_loss, ORDINARY_OFFSET)
        from_long = min(long_loss, ORDINARY_OFFSET - from_short)
        tax -= (from_short + from_long) * float(self.rates.short_term)
        self.carried = (short_loss - from_short, long_loss - from_long)
        self.paid[year_number] = tax
        return tax

    @property
    def carryforward(self) -> float:
        return sum(self.carried)

    @property
    def total_paid(self) -> float:
        return sum(self.paid.values())
