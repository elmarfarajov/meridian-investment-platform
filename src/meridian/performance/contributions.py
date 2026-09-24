"""The portfolio's daily return, taken apart holding by holding.

Attribution needs, for every day, the value at risk in each holding at the start
of the day and what it earned - split into the part the local market paid, the
part the currency paid, and the income. Day 3 already computes all of this
exactly: the value bridge carries price, currency and accrued interest per
holding, and the ledger records every dividend and coupon against its instrument.
This module assembles them into one :class:`PortfolioDay` per valuation day:

* one :class:`Exposure` per holding - opening value, local result (price plus
  income), currency result;
* one exposure per currency for cash and everything cash-like, whose result is
  the currency move on the balance and the spread on any conversion;
* the day's costs - commissions, fees, taxes and unreclaimable withholding -
  which belong to the portfolio rather than to a holding.

The exposures' results and the costs add up to the day's investment result, and
the difference is carried as ``residual`` so the tests can require it to be zero.
Flows arrive in cash at the start of the day, the convention the daily returns use.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..accounting.book import Book
from ..accounting.bridge import ValueBridge
from ..accounting.chart_of_accounts import Accounts
from ..accounting.valuation import PortfolioValuation, Valuator
from ..core.exceptions import ValidationError

CASH_PREFIX = "CASH:"


@dataclass(frozen=True, slots=True)
class Exposure:
    """One holding (or one currency of cash) over one day, in base currency."""

    key: str
    currency: str
    value: float  # at risk at the start of the day
    local: float  # price move in local terms at the opening rate, plus income
    fx: float  # the currency move, on the closing local value
    income: float = 0.0  # the part of ``local`` that was dividends, coupons and accrual

    @property
    def result(self) -> float:
        return self.local + self.fx

    @property
    def is_cash(self) -> bool:
        return self.key.startswith(CASH_PREFIX)


@dataclass(frozen=True)
class PortfolioDay:
    day: date
    capital: float  # opening NAV plus the day's flows
    result: float  # the day's investment result from the value bridge
    costs: float  # negative: commissions, fees, taxes, unreclaimable withholding
    exposures: tuple[Exposure, ...] = field(default_factory=tuple)

    @property
    def rate(self) -> float:
        return self.result / self.capital if self.capital > 0 else 0.0

    @property
    def residual(self) -> float:
        return self.result - sum(item.result for item in self.exposures) - self.costs

    def weight(self, exposure: Exposure) -> float:
        return exposure.value / self.capital if self.capital > 0 else 0.0


def _income_by_instrument(book: Book, start: date, end: date) -> dict[str, dict[str, Decimal]]:
    """Dividends (gross, on the ex-date) and coupons (on the pay date) per instrument and currency, local."""
    found: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for entry in book.ledger.entries_between(start, end):
        for posting in entry.postings:
            if not posting.instrument_id:
                continue
            if posting.account_code == Accounts.DIVIDEND_INCOME.code:
                found[posting.instrument_id][posting.currency] -= posting.amount
            elif posting.account_code == Accounts.CASH.code and entry.entry_id.endswith(":I"):
                found[posting.instrument_id][posting.currency] += posting.amount
    return found


def decompose(
    valuator: Valuator,
    valuations: Sequence[PortfolioValuation],
    bridges: Sequence[ValueBridge],
) -> list[PortfolioDay]:
    """One :class:`PortfolioDay` per bridge step; ``valuations[i]`` must open ``bridges[i]``."""
    if len(valuations) != len(bridges) + 1:
        raise ValidationError("decompose needs one more valuation than bridge steps")
    book = valuator.book
    days: list[PortfolioDay] = []
    for before, after, step in zip(valuations, valuations[1:], bridges, strict=False):
        if before.day != step.start or after.day != step.end:
            raise ValidationError(f"valuations and bridges are misaligned at {step.start}")
        income = _income_by_instrument(book, step.start, step.end)
        activity_flows: dict[str, Decimal] = defaultdict(Decimal)
        converted: dict[str, Decimal] = defaultdict(Decimal)
        transferred: dict[str, float] = defaultdict(float)
        closing = {item.instrument_id: item for item in after.positions}
        for activity in book.activity_between(step.start, step.end):
            for currency, amount in activity.flows.items():
                activity_flows[currency] += amount
            for sold_currency, sold, bought_currency, bought in activity.conversions:
                converted[sold_currency] -= sold
                converted[bought_currency] += bought
            for trade in activity.trades:
                # securities transferred in kind arrive at the start of the day, at the day's value
                held = closing.get(trade.instrument_id)
                if trade.is_flow and held is not None:
                    transferred[trade.instrument_id] += float(trade.quantity * held.price * held.scale * held.fx_rate)
        opening = {item.instrument_id: item for item in before.positions}
        exposures: list[Exposure] = []
        instrument_fx: dict[str, float] = defaultdict(float)
        instrument_income: dict[str, float] = defaultdict(float)
        for instrument_id, effect in sorted(step.by_instrument.items()):
            currency = valuator.instruments[instrument_id].currency.code
            rate = valuator.rate(currency, step.end)
            paid = sum((amount * rate for amount in income.get(instrument_id, {}).values()), Decimal(0))
            held = opening.get(instrument_id)
            earned = float(effect.income + paid)
            exposures.append(
                Exposure(
                    instrument_id,
                    currency,
                    (float(held.total_base) if held else 0.0) + transferred.get(instrument_id, 0.0),
                    float(effect.price) + earned,
                    float(effect.fx),
                    earned,
                )
            )
            instrument_fx[currency] += float(effect.fx)
            instrument_income[currency] += float(paid)
        cash_lines = {line.currency: line for line in before.cash}
        activity_income: dict[str, float] = defaultdict(float)
        for activity in book.activity_between(step.start, step.end):
            for currency, amount in activity.income.items():
                activity_income[currency] += float(amount * valuator.rate(currency, step.end))
        currencies = sorted(
            set(cash_lines) | set(step.fx_detail) | set(activity_flows) | set(activity_income) | {valuator.base}
        )
        # a conversion moves money between currencies; only its spread against the market rate is a result
        legs = {currency: float(amount * valuator.rate(currency, step.end)) for currency, amount in converted.items()}
        spread = sum(legs.values())
        for currency in currencies:
            flow = float(activity_flows.get(currency, Decimal(0)) * valuator.rate(currency, step.end))
            value = (float(cash_lines[currency].total_base) if currency in cash_lines else 0.0) + flow
            cash_fx = float(step.fx_detail.get(currency, Decimal(0))) - instrument_fx.get(currency, 0.0)
            cash_fx -= legs.get(currency, 0.0)
            if currency == valuator.base:
                cash_fx += spread
            # income not attributed to an instrument (none in practice) stays with cash, so nothing is lost
            stray = activity_income.get(currency, 0.0) - instrument_income.get(currency, 0.0)
            if value or cash_fx or abs(stray) > 1e-9:
                exposures.append(Exposure(f"{CASH_PREFIX}{currency}", currency, value, stray, cash_fx, stray))
        days.append(
            PortfolioDay(
                step.end,
                float(step.opening + step.flows),
                float(step.investment_result),
                float(step.costs),
                tuple(exposures),
            )
        )
    return days


def holding_contributions(days: Sequence[PortfolioDay]) -> dict[str, float]:
    """Each holding's contribution to the period's return, linked so the contributions sum to it exactly.

    A day's contribution is the holding's result over the day's capital. Summed
    over days it would miss the compounding, so each day is scaled by
    ``ln(1 + R_t) / R_t`` against ``ln(1 + R) / R`` for the period - Cariño's
    factors with a benchmark of zero. Cash in every currency is one line, and the
    portfolio's costs are another.
    """
    import math

    total = math.prod(1.0 + day.rate for day in days) - 1.0

    def factor(rate: float) -> float:
        return math.log1p(rate) / rate if abs(rate) > 1e-15 else 1.0 / (1.0 + rate)

    scale = factor(total)
    found: dict[str, float] = defaultdict(float)
    for day in days:
        if day.capital <= 0:
            continue
        weight = factor(day.rate) / scale / day.capital
        for exposure in day.exposures:
            found["Cash" if exposure.is_cash else exposure.key] += exposure.result * weight
        found["Costs"] += day.costs * weight
    return dict(sorted(found.items(), key=lambda item: -item[1]))
