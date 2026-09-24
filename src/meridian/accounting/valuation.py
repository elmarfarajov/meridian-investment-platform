"""Daily valuation: the book at market, in local and base currency.

The ledger says what was paid. The valuation says what it is worth: every open
lot at the day's price, translated at the day's rate, plus accrued interest,
plus everything cash-like - settled cash, the receivables and payables of
trades not yet settled, dividends gone ex but not yet paid and withholding tax
awaiting reclaim. Net asset value is the sum.

Unrealised gain is split the same way a realised one is, so the two are
comparable:

    value - cost = (local value - local cost) x rate_today     price
                 + local cost x (rate_today - rate_at_purchase)  currency

per lot, because every lot was bought at its own rate. For a holding in the
base currency the currency term is zero; for a euro holding in a dollar book it
is often the larger of the two.

A price older than the staleness limit is not used. The holding is listed as
missing rather than valued at a number nobody would defend.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.calendars import TradingCalendar, get_calendar
from ..core.decimals import decimal_sum, safe_divide
from ..core.exceptions import ValidationError
from ..domain.instruments import Instrument, instrument_price_scale
from ..domain.positions import TaxLot
from .book import Book, BookSnapshot
from .chart_of_accounts import Accounts
from .income import accrued_per_unit
from .sources import FxSource, PriceSource


@dataclass(frozen=True, slots=True)
class PositionValuation:
    instrument_id: str
    currency: str
    quantity: Decimal
    price: Decimal
    price_date: date
    scale: Decimal
    fx_rate: Decimal
    cost: Decimal  # local book cost
    cost_base: Decimal  # at historical rates
    tax_basis: Decimal  # base, including wash sale adjustments
    accrued_per_unit: Decimal
    unrealised_fx_base: Decimal
    unrealised_long_term: Decimal  # base, tax view
    unrealised_short_term: Decimal

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.price * self.scale

    @property
    def market_value_base(self) -> Decimal:
        return self.market_value * self.fx_rate

    @property
    def accrued(self) -> Decimal:
        return self.quantity * self.accrued_per_unit

    @property
    def accrued_base(self) -> Decimal:
        return self.accrued * self.fx_rate

    @property
    def total_base(self) -> Decimal:
        return self.market_value_base + self.accrued_base

    @property
    def unrealised_base(self) -> Decimal:
        return self.market_value_base - self.cost_base

    @property
    def unrealised_price_base(self) -> Decimal:
        return (self.market_value - self.cost) * self.fx_rate

    @property
    def unrealised_local(self) -> Decimal:
        return self.market_value - self.cost

    def is_stale(self, day: date, max_days: int = 4) -> bool:
        return (day - self.price_date).days > max_days


@dataclass(frozen=True, slots=True)
class CashLine:
    """Cash-like balances in one currency, local and translated."""

    currency: str
    fx_rate: Decimal
    cash: Decimal
    receivables: Decimal
    payables: Decimal  # negative: money owed
    income_receivable: Decimal
    reclaimable: Decimal

    @property
    def total(self) -> Decimal:
        return self.cash + self.receivables + self.payables + self.income_receivable + self.reclaimable

    @property
    def total_base(self) -> Decimal:
        return self.total * self.fx_rate

    @property
    def cash_base(self) -> Decimal:
        return self.cash * self.fx_rate


@dataclass(frozen=True)
class PortfolioValuation:
    portfolio_id: str
    day: date
    base_currency: str
    positions: tuple[PositionValuation, ...]
    cash: tuple[CashLine, ...]
    missing: tuple[str, ...] = ()

    @property
    def securities(self) -> Decimal:
        return decimal_sum(position.market_value_base for position in self.positions)

    @property
    def accrued_interest(self) -> Decimal:
        return decimal_sum(position.accrued_base for position in self.positions)

    @property
    def cash_like(self) -> Decimal:
        return decimal_sum(line.total_base for line in self.cash)

    @property
    def settled_cash(self) -> Decimal:
        return decimal_sum(line.cash_base for line in self.cash)

    @property
    def receivables(self) -> Decimal:
        return decimal_sum(
            (line.receivables + line.income_receivable + line.reclaimable) * line.fx_rate for line in self.cash
        )

    @property
    def payables(self) -> Decimal:
        return decimal_sum(line.payables * line.fx_rate for line in self.cash)

    @property
    def nav(self) -> Decimal:
        return self.securities + self.accrued_interest + self.cash_like

    @property
    def cost_base(self) -> Decimal:
        return decimal_sum(position.cost_base for position in self.positions)

    @property
    def unrealised(self) -> Decimal:
        return decimal_sum(position.unrealised_base for position in self.positions)

    @property
    def unrealised_price(self) -> Decimal:
        return decimal_sum(position.unrealised_price_base for position in self.positions)

    @property
    def unrealised_fx(self) -> Decimal:
        return decimal_sum(position.unrealised_fx_base for position in self.positions)

    def position(self, instrument_id: str) -> PositionValuation | None:
        return next((item for item in self.positions if item.instrument_id == instrument_id), None)

    def weights(self) -> dict[str, Decimal]:
        nav = self.nav
        weights = {item.instrument_id: safe_divide(item.total_base, nav, default=Decimal(0)) for item in self.positions}
        weights["cash"] = safe_divide(self.cash_like, nav, default=Decimal(0))
        return weights

    def currency_exposure(self) -> dict[str, Decimal]:
        """Base-currency value held in each currency: securities, accrued interest and cash together."""
        exposure: dict[str, Decimal] = {}
        for item in self.positions:
            exposure[item.currency] = exposure.get(item.currency, Decimal(0)) + item.total_base
        for line in self.cash:
            exposure[line.currency] = exposure.get(line.currency, Decimal(0)) + line.total_base
        return dict(sorted(exposure.items()))


class Valuator:
    """Values a :class:`Book` on any day from a price source and an FX source."""

    def __init__(
        self,
        book: Book,
        instruments: Mapping[str, Instrument] | Iterable[Instrument],
        prices: PriceSource,
        fx: FxSource,
        *,
        max_price_age_days: int = 4,
    ) -> None:
        self.book = book
        self.instruments: dict[str, Instrument] = (
            dict(instruments)
            if isinstance(instruments, Mapping)
            else {item.instrument_id: item for item in instruments}
        )
        self.prices = prices
        self.fx = fx
        self.max_price_age_days = max_price_age_days
        self.base = book.base_currency

    def rate(self, currency: str, day: date) -> Decimal:
        return self.fx.rate(currency, self.base, day)

    def value(self, day: date, *, snapshot: BookSnapshot | None = None) -> PortfolioValuation:
        state = snapshot or self.book.snapshot_on(day)
        positions: list[PositionValuation] = []
        missing: list[str] = []
        for instrument_id, lots in sorted(state.lots.items()):
            if not lots:
                continue
            valued = self.value_position(instrument_id, lots, day)
            if valued is None:
                missing.append(instrument_id)
            else:
                positions.append(valued)
        lines = []
        for currency in state.currencies:
            line = CashLine(
                currency=currency,
                fx_rate=self.rate(currency, day),
                cash=state.balance(Accounts.CASH.code, currency),
                receivables=state.balance(Accounts.SALES_RECEIVABLE.code, currency),
                payables=state.balance(Accounts.PURCHASES_PAYABLE.code, currency),
                income_receivable=state.balance(Accounts.DIVIDENDS_RECEIVABLE.code, currency)
                + state.balance(Accounts.INTEREST_RECEIVABLE.code, currency),
                reclaimable=state.balance(Accounts.TAX_RECLAIMABLE.code, currency),
            )
            if line.total or line.cash:
                lines.append(line)
        return PortfolioValuation(
            self.book.portfolio.portfolio_id, day, self.base, tuple(positions), tuple(lines), tuple(missing)
        )

    def value_position(self, instrument_id: str, lots: tuple[TaxLot, ...], day: date) -> PositionValuation | None:
        instrument = self.instruments.get(instrument_id)
        if instrument is None:
            raise ValidationError(f"{instrument_id} is held but not in the security master")
        price = self.prices.price(instrument_id, day)
        price_date = self.prices.price_date(instrument_id, day)
        if price is None or price_date is None or (day - price_date).days > self.max_price_age_days:
            return None
        currency = instrument.currency.code
        rate = self.rate(currency, day)
        scale = instrument_price_scale(instrument)
        quantity = decimal_sum(lot.quantity for lot in lots)
        cost = decimal_sum(lot.quantity * lot.cost_per_unit for lot in lots)
        cost_base = decimal_sum(lot.base_cost for lot in lots)
        unrealised_fx = decimal_sum(lot.quantity * lot.cost_per_unit * (rate - lot.open_fx_rate) for lot in lots)
        long_term = short_term = Decimal(0)
        for lot in lots:
            gain = lot.quantity * price * scale * rate - lot.tax_basis
            if lot.is_long_term(day):
                long_term += gain
            else:
                short_term += gain
        return PositionValuation(
            instrument_id=instrument_id,
            currency=currency,
            quantity=quantity,
            price=price,
            price_date=price_date,
            scale=scale,
            fx_rate=rate,
            cost=cost,
            cost_base=cost_base,
            tax_basis=decimal_sum(lot.tax_basis for lot in lots),
            accrued_per_unit=accrued_per_unit(instrument, day),
            unrealised_fx_base=unrealised_fx,
            unrealised_long_term=long_term,
            unrealised_short_term=short_term,
        )

    def valuation_days(self, start: date, end: date, calendar: str | TradingCalendar | None = None) -> list[date]:
        """Business days of the portfolio's calendar in ``[start, end]``."""
        chosen = get_calendar(calendar or "XNYS")
        return list(chosen.business_days(start, end))

    def series(self, start: date, end: date, calendar: str | TradingCalendar | None = None) -> list[PortfolioValuation]:
        return [self.value(day) for day in self.valuation_days(start, end, calendar)]
