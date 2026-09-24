"""The value bridge: why net asset value moved, to the last decimal.

Between two valuation dates the change in NAV is split into six causes:

* **Flows** - money and securities the client put in or took out. Not return.
* **Price** - the market moved the securities held, measured in local
  currency and translated at the *opening* rate; plus the difference between
  the price a trade was done at and the day's close.
* **Currency** - the exchange rate moved, applied to everything held in a
  foreign currency: securities at the closing price, accrued interest and
  cash-like balances; plus any gain or loss on converting one currency into
  another.
* **Income** - dividends on the ex-date, coupons, and interest accruing day
  by day on bonds.
* **Costs** - commissions, transaction taxes, fees and withholding tax that
  cannot be reclaimed.

For one holding over one day, with quantity ``Q``, price ``P``, contract scale
``s`` and rate ``X``::

    Q1 P1 s X1 - Q0 P0 s X0 = (Qa P1 - Q0 P0) s X0          price
                            + Qa P1 s (X1 - X0)              currency
                            + sum over trades (dQ P1 s - consideration) X1   price (trading)
                            + consideration X1               moves into cash

where ``Qa`` is the quantity held before the day's trades but after any
corporate action - so a 4-for-1 split, which quadruples ``Q`` and quarters
``P``, is correctly *not* a price move. The same identity is written for
accrued interest and for every cash-like balance, and the pieces are chosen so
that **nothing is left over**: the bridge carries a residual, and the tests
require it to be zero on every day of the demonstration history.

The split is the "local return at the opening rate, currency on the closing
local value" convention; the alternative ordering moves the small cross term
between the two effects. The choice is written down in ADR 0017.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import pairwise

from ..core.decimals import decimal_sum
from ..core.exceptions import ValidationError
from ..domain.instruments import instrument_price_scale
from .book import Book, DayActivity
from .valuation import PortfolioValuation, Valuator

COMPONENTS = ("flows", "price", "fx", "income", "costs")


@dataclass(frozen=True)
class InstrumentEffect:
    instrument_id: str
    price: Decimal
    fx: Decimal
    income: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
        return self.price + self.fx + self.income


@dataclass(frozen=True)
class ValueBridge:
    start: date
    end: date
    opening: Decimal
    closing: Decimal
    flows: Decimal
    price: Decimal
    fx: Decimal
    income: Decimal
    costs: Decimal  # negative: value that left
    by_instrument: dict[str, InstrumentEffect] = field(default_factory=dict)
    fx_detail: dict[str, Decimal] = field(default_factory=dict)
    days: int = 1

    @property
    def explained(self) -> Decimal:
        return self.flows + self.price + self.fx + self.income + self.costs

    @property
    def residual(self) -> Decimal:
        return self.closing - self.opening - self.explained

    @property
    def investment_result(self) -> Decimal:
        """Everything except flows: what the portfolio earned."""
        return self.price + self.fx + self.income + self.costs

    def components(self) -> list[tuple[str, Decimal]]:
        return [
            ("Opening NAV", self.opening),
            ("Flows", self.flows),
            ("Price", self.price),
            ("Currency", self.fx),
            ("Income", self.income),
            ("Costs", self.costs),
            ("Closing NAV", self.closing),
        ]

    def __add__(self, other: ValueBridge) -> ValueBridge:
        if other.start != self.end:
            raise ValidationError(f"bridges do not join: {self.end} then {other.start}")
        merged: dict[str, InstrumentEffect] = dict(self.by_instrument)
        for key, effect in other.by_instrument.items():
            current = merged.get(key)
            merged[key] = (
                effect
                if current is None
                else InstrumentEffect(
                    key, current.price + effect.price, current.fx + effect.fx, current.income + effect.income
                )
            )
        detail: dict[str, Decimal] = defaultdict(Decimal, self.fx_detail)
        for key, amount in other.fx_detail.items():
            detail[key] += amount
        return ValueBridge(
            self.start,
            other.end,
            self.opening,
            other.closing,
            self.flows + other.flows,
            self.price + other.price,
            self.fx + other.fx,
            self.income + other.income,
            self.costs + other.costs,
            merged,
            dict(detail),
            self.days + other.days,
        )


def _merge_activity(activities: Sequence[DayActivity], end: date) -> DayActivity:
    merged = DayActivity(end)
    for activity in activities:
        merged.trades.extend(activity.trades)
        merged.conversions.extend(activity.conversions)
        for target, source in (
            (merged.flows, activity.flows),
            (merged.income, activity.income),
            (merged.costs, activity.costs),
        ):
            for currency, amount in source.items():
                target[currency] += amount
    return merged


def bridge_step(
    before: PortfolioValuation, after: PortfolioValuation, activity: DayActivity, valuator: Valuator
) -> ValueBridge:
    """The exact decomposition of the NAV change from one valuation to the next."""
    if before.missing or after.missing:
        raise ValidationError(
            f"cannot bridge {before.day} to {after.day}: unpriced holdings {before.missing + after.missing}"
        )
    book = valuator.book
    start_state, end_state = book.snapshot_on(before.day), book.snapshot_on(after.day)
    old = {item.instrument_id: item for item in before.positions}
    new = {item.instrument_id: item for item in after.positions}
    trades_by_instrument: dict[str, list] = defaultdict(list)
    for trade in activity.trades:
        trades_by_instrument[trade.instrument_id].append(trade)

    price = fx = income = flows = costs = Decimal(0)
    effects: dict[str, InstrumentEffect] = {}
    fx_detail: dict[str, Decimal] = defaultdict(Decimal)
    for instrument_id in sorted(set(old) | set(new) | set(trades_by_instrument)):
        was, now = old.get(instrument_id), new.get(instrument_id)
        instrument = valuator.instruments[instrument_id]
        currency = instrument.currency.code
        rate0 = was.fx_rate if was else valuator.rate(currency, before.day)
        rate1 = now.fx_rate if now else valuator.rate(currency, after.day)
        price0 = was.price if was else Decimal(0)
        price1 = now.price if now else (valuator.prices.price(instrument_id, after.day) or Decimal(0))
        scale = instrument_price_scale(instrument)
        q0 = start_state.quantity(instrument_id)
        q1 = end_state.quantity(instrument_id)
        trades = trades_by_instrument.get(instrument_id, [])
        traded = decimal_sum(trade.quantity for trade in trades)
        held = q1 - traded  # after corporate actions, before trades
        item_price = (held * price1 - q0 * price0) * scale * rate0
        item_fx = held * price1 * scale * (rate1 - rate0)
        item_flow = Decimal(0)
        for trade in trades:
            value = trade.quantity * price1 * scale * rate1
            if trade.is_flow:
                item_flow += value
            else:
                item_price += value - trade.consideration * rate1
        # accrued interest: currency on the opening balance, the rest is income
        accrued0 = q0 * (was.accrued_per_unit if was else Decimal(0))
        accrued1 = q1 * (now.accrued_per_unit if now else Decimal(0))
        accrued_paid = decimal_sum(trade.accrued for trade in trades)
        item_fx += accrued0 * (rate1 - rate0)
        item_income = (accrued1 - accrued0 - accrued_paid) * rate1
        price += item_price
        fx += item_fx
        income += item_income
        flows += item_flow
        fx_detail[currency] += item_fx
        effects[instrument_id] = InstrumentEffect(instrument_id, item_price, item_fx, item_income)

    lines0 = {line.currency: line for line in before.cash}
    lines1 = {line.currency: line for line in after.cash}
    converted: dict[str, Decimal] = defaultdict(Decimal)
    for sold_currency, sold, bought_currency, bought in activity.conversions:
        converted[sold_currency] -= sold
        converted[bought_currency] += bought
    for currency in sorted(set(lines0) | set(lines1) | set(activity.flows) | set(converted)):
        rate0 = lines0[currency].fx_rate if currency in lines0 else valuator.rate(currency, before.day)
        rate1 = lines1[currency].fx_rate if currency in lines1 else valuator.rate(currency, after.day)
        balance0 = lines0[currency].total if currency in lines0 else Decimal(0)
        currency_fx = balance0 * (rate1 - rate0) + converted[currency] * rate1
        fx += currency_fx
        fx_detail[currency] += currency_fx
        flows += activity.flows.get(currency, Decimal(0)) * rate1
        income += activity.income.get(currency, Decimal(0)) * rate1
        costs -= activity.costs.get(currency, Decimal(0)) * rate1
    return ValueBridge(
        before.day,
        after.day,
        before.nav,
        after.nav,
        flows,
        price,
        fx,
        income,
        costs,
        effects,
        dict(fx_detail),
    )


def value_bridge(valuator: Valuator, days: Sequence[date]) -> tuple[ValueBridge, list[ValueBridge]]:
    """The bridge over consecutive valuation dates: the total and each step."""
    if len(days) < 2:
        raise ValidationError("a bridge needs at least two valuation dates")
    book: Book = valuator.book
    valuations = [valuator.value(day) for day in days]
    steps: list[ValueBridge] = []
    for before, after in pairwise(valuations):
        activity = _merge_activity(book.activity_between(before.day, after.day), after.day)
        steps.append(bridge_step(before, after, activity, valuator))
    total = steps[0]
    for step in steps[1:]:
        total = total + step
    return total, steps
