"""Back-adjusting price histories for corporate actions.

The raw history is kept exactly as it was quoted - it is the record of what the
market printed, and a statement or a trade confirmation has to match it. Every
*analytical* use of the history, though, needs it adjusted: a return series
that runs through an unadjusted 4-for-1 split shows a 75% loss that never
happened.

Adjustment follows the CRSP convention. Each event has a factor ``f`` (see
:mod:`meridian.domain.corporate_actions`); every price *before* the ex-date is
multiplied by the product of the factors of all later events. Prices on and
after the last event are untouched, so the adjusted series ends at the price a
client can see on their screen today.

Two adjusted views are produced, because they answer different questions:

``CAPITAL``
    Splits, stock dividends, spin-offs and rights taken out. The price return a
    share actually delivered, with dividends excluded - what an index "price
    return" measures.
``TOTAL_RETURN``
    Cash dividends taken out as well, which is equivalent to reinvesting them on
    the ex-date. This is the series performance measurement and risk models use.

Adjustment is never stored over the raw data (ADR 0011). It is a view, derived
on demand from the raw history and the event list, so an event loaded late or
corrected changes every adjusted number consistently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext

from ..core.exceptions import ValidationError
from ..domain.corporate_actions import AdjustmentMode, CorporateAction
from .series import TimeSeries

ADJUSTED_PLACES = Decimal("0.00000001")


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    """One event's contribution to the adjustment."""

    action_id: str
    ex_date: date
    factor: Decimal
    cum_price: Decimal | None
    description: str

    @property
    def implied_move(self) -> float:
        """The price change the event alone should cause on its ex-date."""
        return float(self.factor) - 1.0


def adjustment_factors(
    series: TimeSeries,
    actions: Sequence[CorporateAction],
    mode: AdjustmentMode = AdjustmentMode.TOTAL_RETURN,
    *,
    instrument_id: str | None = None,
) -> list[AdjustmentFactor]:
    """The factor of every event that falls inside the series and applies in ``mode``.

    The cum-event price is the last close strictly before the ex-date. An event
    whose ex-date precedes the whole series has nothing to adjust and is
    skipped; an event with no cum price inside the series cannot be sized when
    its size depends on the price, and raises.
    """
    key = instrument_id or series.name
    factors: list[AdjustmentFactor] = []
    if not series:
        return factors
    for action in sorted(actions, key=lambda item: (item.ex_date, item.action_id)):
        if key and action.instrument_id != key:
            continue
        if not action.applies_in(mode) or action.ex_date <= series.first.day:
            continue
        if action.action_type.is_terminal:
            continue
        cum = series.as_of(action.ex_date - timedelta(days=1))
        cum_price = cum.value if cum is not None else None
        factors.append(
            AdjustmentFactor(
                action_id=action.action_id,
                ex_date=action.ex_date,
                factor=action.price_factor(cum_price),
                cum_price=cum_price,
                description=action.describe(),
            )
        )
    return factors


def cumulative_factor(factors: Sequence[AdjustmentFactor], day: date) -> Decimal:
    """Product of every factor whose ex-date is after ``day``: the multiplier for that day's price."""
    product = Decimal(1)
    with localcontext() as context:
        context.prec = 34
        for item in factors:
            if item.ex_date > day:
                product *= item.factor
    return product


def adjust_history(
    series: TimeSeries,
    actions: Sequence[CorporateAction],
    mode: AdjustmentMode = AdjustmentMode.TOTAL_RETURN,
    *,
    instrument_id: str | None = None,
) -> TimeSeries:
    """The history back-adjusted for every event in ``mode``, ending at the unadjusted latest price."""
    factors = adjustment_factors(series, actions, mode, instrument_id=instrument_id)
    if not factors:
        return series.with_name(f"{series.name} ({mode.value})")
    points: list[tuple[date, Decimal]] = []
    for point in series:
        multiplier = cumulative_factor(factors, point.day)
        points.append((point.day, (point.value * multiplier).quantize(ADJUSTED_PLACES)))
    return TimeSeries(points, name=f"{series.name} ({mode.value})")


def adjust_quantity(
    quantity: Decimal,
    actions: Sequence[CorporateAction],
    *,
    held_from: date,
    to: date,
    instrument_id: str | None = None,
) -> Decimal:
    """What a holding of ``quantity`` shares at ``held_from`` became by ``to``, through splits and stock dividends."""
    if to < held_from:
        raise ValidationError("cannot adjust a quantity backwards in time")
    result = quantity
    for action in sorted(actions, key=lambda item: item.ex_date):
        if instrument_id and action.instrument_id != instrument_id:
            continue
        if held_from < action.ex_date <= to:
            result *= action.quantity_factor
    return result


@dataclass(frozen=True)
class AdjustedHistory:
    """The three views of one history, side by side."""

    raw: TimeSeries
    capital: TimeSeries
    total_return: TimeSeries
    factors: tuple[AdjustmentFactor, ...]

    def total_return_index(self, base: float = 100.0) -> list[tuple[date, float]]:
        return self.total_return.cumulative_index(base)

    def price_return_index(self, base: float = 100.0) -> list[tuple[date, float]]:
        return self.capital.cumulative_index(base)

    def dividend_contribution(self) -> float:
        """Total return less price return over the whole history, as a fraction of the start value."""
        total = self.total_return_index(1.0)
        price = self.price_return_index(1.0)
        if not total or not price:
            return 0.0
        return total[-1][1] - price[-1][1]

    def raw_return(self) -> float:
        if len(self.raw) < 2:
            return 0.0
        return float(self.raw.last.value / self.raw.first.value) - 1.0


def adjusted_history(
    series: TimeSeries, actions: Sequence[CorporateAction], *, instrument_id: str | None = None
) -> AdjustedHistory:
    return AdjustedHistory(
        raw=series,
        capital=adjust_history(series, actions, AdjustmentMode.CAPITAL, instrument_id=instrument_id),
        total_return=adjust_history(series, actions, AdjustmentMode.TOTAL_RETURN, instrument_id=instrument_id),
        factors=tuple(adjustment_factors(series, actions, AdjustmentMode.TOTAL_RETURN, instrument_id=instrument_id)),
    )
