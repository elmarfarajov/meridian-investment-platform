"""US tax reporting from the realised lots: tax years, Form 8949, and the choice of lots.

Everything a US return needs about capital gains is already in the realised
lots - the dates, the proceeds and basis in dollars, the holding period and
any wash sale adjustment. This module arranges it:

* **A tax-year summary** in the order Schedule D nets it: short-term gains
  against short-term losses, long-term against long-term, then the two nets
  against each other. A net capital loss is deductible against ordinary income
  only up to $3,000 a year; the rest carries forward, keeping its character.
* **Form 8949 rows**, one per realised lot, with the adjustment code ``W`` and
  the disallowed amount where the wash sale rule applied.
* **Lot selection.** Which lots a sale relieves is a decision, and it is worth
  money. For a given sale the realised gain and the tax on it are computed
  under FIFO, LIFO, highest-cost-first, and a minimum-tax order that sells the
  lots with the lowest tax per share first. With a linear tax the greedy order
  is optimal - each share's tax does not depend on which others are sold - so
  the minimum-tax result is a true lower bound for that sale.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.decimals import decimal_sum
from ..core.enums import LotSelectionMethod
from ..core.exceptions import ValidationError
from ..domain.positions import Position, TaxLot
from .lots import RealisedLot, Term

CAPITAL_LOSS_LIMIT = Decimal(3000)


@dataclass(frozen=True, slots=True)
class TaxRates:
    """Federal rates for a top-bracket individual: ordinary income, long-term gains, and the 3.8% NIIT."""

    short_term: Decimal = Decimal("0.37")
    long_term: Decimal = Decimal("0.20")
    net_investment_income: Decimal = Decimal("0.038")

    def rate(self, term: Term) -> Decimal:
        base = self.short_term if term is Term.SHORT else self.long_term
        return base + self.net_investment_income


DEFAULT_RATES = TaxRates()


@dataclass(frozen=True)
class TaxYearSummary:
    year: int
    short_term_gains: Decimal
    short_term_losses: Decimal
    long_term_gains: Decimal
    long_term_losses: Decimal
    disallowed: Decimal
    carryforward_in_short: Decimal = Decimal(0)
    carryforward_in_long: Decimal = Decimal(0)

    @property
    def net_short(self) -> Decimal:
        return self.short_term_gains + self.short_term_losses - self.carryforward_in_short

    @property
    def net_long(self) -> Decimal:
        return self.long_term_gains + self.long_term_losses - self.carryforward_in_long

    @property
    def net(self) -> Decimal:
        return self.net_short + self.net_long

    @property
    def deductible_loss(self) -> Decimal:
        return min(-self.net, CAPITAL_LOSS_LIMIT) if self.net < 0 else Decimal(0)

    def carryforward(self) -> tuple[Decimal, Decimal]:
        """Short- and long-term losses carried into next year, after the $3,000 deduction.

        The deduction is taken from the short-term loss first, as the IRS
        capital loss carryover worksheet does.
        """
        if self.net >= 0:
            return Decimal(0), Decimal(0)
        short, long = self.net_short, self.net_long
        remaining = self.deductible_loss
        if short < 0 and long >= 0:
            short += long
            long = Decimal(0)
        elif long < 0 and short >= 0:
            long += short
            short = Decimal(0)
        use = min(-short, remaining) if short < 0 else Decimal(0)
        short += use
        remaining -= use
        if long < 0:
            long += min(-long, remaining)
        return max(-short, Decimal(0)), max(-long, Decimal(0))

    def estimated_tax(self, rates: TaxRates = DEFAULT_RATES) -> Decimal:
        """Federal tax on the year's net gain; a net loss earns the deduction at the ordinary rate."""
        if self.net < 0:
            return -self.deductible_loss * rates.short_term
        short, long = self.net_short, self.net_long
        if short < 0:
            long, short = long + short, Decimal(0)
        if long < 0:
            short, long = short + long, Decimal(0)
        return short * rates.rate(Term.SHORT) + long * rates.rate(Term.LONG)


def tax_years(realised: Iterable[RealisedLot]) -> list[TaxYearSummary]:
    """One summary per calendar year, with losses carried forward from year to year."""
    by_year: dict[int, list[RealisedLot]] = {}
    for item in realised:
        by_year.setdefault(item.tax_year, []).append(item)
    if not by_year:
        return []
    summaries: list[TaxYearSummary] = []
    carry_short = carry_long = Decimal(0)
    for year in range(min(by_year), max(by_year) + 1):
        items = by_year.get(year, [])

        def total(term: Term, gains: bool, records: list[RealisedLot] = items) -> Decimal:
            return decimal_sum(
                item.reportable_gain for item in records if item.term is term and (item.reportable_gain >= 0) == gains
            )

        summary = TaxYearSummary(
            year=year,
            short_term_gains=total(Term.SHORT, True),
            short_term_losses=total(Term.SHORT, False),
            long_term_gains=total(Term.LONG, True),
            long_term_losses=total(Term.LONG, False),
            disallowed=decimal_sum(item.disallowed_loss for item in items),
            carryforward_in_short=carry_short,
            carryforward_in_long=carry_long,
        )
        summaries.append(summary)
        carry_short, carry_long = summary.carryforward()
    return summaries


@dataclass(frozen=True, slots=True)
class Form8949Row:
    description: str
    acquired: date
    sold: date
    proceeds: Decimal
    cost: Decimal
    code: str
    adjustment: Decimal
    gain: Decimal
    term: Term

    def as_tuple(self) -> tuple[str, str, str, str, str, str, str, str]:
        return (
            self.description,
            self.acquired.strftime("%m/%d/%Y"),
            self.sold.strftime("%m/%d/%Y"),
            f"{self.proceeds:,.2f}",
            f"{self.cost:,.2f}",
            self.code,
            f"{self.adjustment:,.2f}" if self.adjustment else "",
            f"{self.gain:,.2f}",
        )


def form_8949(realised: Iterable[RealisedLot], year: int) -> list[Form8949Row]:
    """Form 8949 rows for one year: short-term (Part I) before long-term (Part II), each by date sold."""
    rows = [
        Form8949Row(
            description=f"{item.quantity.normalize():f} sh {item.instrument_id}",
            acquired=item.holding_start,
            sold=item.close_date,
            proceeds=item.proceeds_base.quantize(Decimal("0.01")),
            cost=item.tax_basis.quantize(Decimal("0.01")),
            code=item.adjustment_code,
            adjustment=item.disallowed_loss.quantize(Decimal("0.01")),
            gain=item.reportable_gain.quantize(Decimal("0.01")),
            term=item.term,
        )
        for item in realised
        if item.tax_year == year
    ]
    return sorted(rows, key=lambda row: (row.term is Term.LONG, row.sold, row.description))


# ---------------------------------------------------------------------------- lot selection
@dataclass(frozen=True)
class LotChoice:
    method: str
    lots: tuple[tuple[str, Decimal], ...]
    short_term: Decimal
    long_term: Decimal
    tax: Decimal

    @property
    def realised(self) -> Decimal:
        return self.short_term + self.long_term


def lot_tax_per_unit(lot: TaxLot, price_base: Decimal, as_of: date, rates: TaxRates) -> Decimal:
    gain = price_base - (lot.base_cost_per_unit + lot.wash_sale_adjustment)
    term = Term.LONG if lot.is_long_term(as_of) else Term.SHORT
    return gain * rates.rate(term)


def minimum_tax_lots(
    lots: Sequence[TaxLot], price_base: Decimal, as_of: date, rates: TaxRates = DEFAULT_RATES
) -> list[str]:
    """Lot identifiers in the order that minimises tax on a sale at ``price_base`` per unit."""
    ranked = sorted(lots, key=lambda lot: (lot_tax_per_unit(lot, price_base, as_of, rates), lot.open_date))
    return [lot.lot_id for lot in ranked]


def evaluate_sale(
    lots: Sequence[TaxLot],
    quantity: Decimal,
    price: Decimal,
    fx_rate: Decimal,
    as_of: date,
    method: LotSelectionMethod,
    *,
    rates: TaxRates = DEFAULT_RATES,
    specific: Sequence[str] | None = None,
    label: str | None = None,
) -> LotChoice:
    """What a sale of ``quantity`` at ``price`` would realise, and the federal tax on it, under one method."""
    if not lots:
        raise ValidationError("no lots to sell")
    first = lots[0]
    position = Position(portfolio_id="-", instrument_id=first.instrument_id, currency=first.currency, lots=tuple(lots))
    sold, _ = position.select_lots(quantity, method, as_of=as_of, specific_lot_ids=specific)
    price_base = price * fx_rate
    short = long = tax = Decimal(0)
    chosen: list[tuple[str, Decimal]] = []
    for lot in sold:
        gain = lot.quantity * (price_base - lot.base_cost_per_unit - lot.wash_sale_adjustment)
        term = Term.LONG if lot.is_long_term(as_of) else Term.SHORT
        if term is Term.LONG:
            long += gain
        else:
            short += gain
        tax += gain * rates.rate(term)
        chosen.append((lot.lot_id.removesuffix("-R"), lot.quantity))
    return LotChoice(label or method.value, tuple(chosen), short, long, tax)


def compare_lot_methods(
    lots: Sequence[TaxLot],
    quantity: Decimal,
    price: Decimal,
    fx_rate: Decimal,
    as_of: date,
    *,
    rates: TaxRates = DEFAULT_RATES,
) -> list[LotChoice]:
    """The same sale under FIFO, LIFO, highest cost first, and the minimum-tax order."""
    results = [
        evaluate_sale(lots, quantity, price, fx_rate, as_of, method, rates=rates, label=label)
        for method, label in (
            (LotSelectionMethod.FIFO, "FIFO"),
            (LotSelectionMethod.LIFO, "LIFO"),
            (LotSelectionMethod.HIFO, "Highest cost"),
        )
    ]
    order = minimum_tax_lots(lots, price * fx_rate, as_of, rates)
    results.append(
        evaluate_sale(
            lots,
            quantity,
            price,
            fx_rate,
            as_of,
            LotSelectionMethod.SPECIFIC_LOT,
            rates=rates,
            specific=order,
            label="Minimum tax",
        )
    )
    return results
