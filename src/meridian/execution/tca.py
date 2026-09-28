"""Transaction cost analysis: what an order cost, where the cost came from, and whether the model predicted it.

**Implementation shortfall** (Perold, 1988) is the difference between the paper
portfolio - every share traded at the price when the decision was made - and
the real one. For an order of X shares, of which q_i were filled at p_i, with
decision price P_d (the previous close), arrival price P_0 (the price when the
order reached the desk) and closing price P_c, and s = +1 to buy, -1 to sell:

    shortfall = s [Σ q_i (p_i − P_d) + (X − Σ q_i)(P_c − P_d)] + fees

It splits exactly into what happened before the desk had the order, while it
worked it, and what it left undone (Kissell and Glantz's decomposition):

    delay        s X (P_0 − P_d)                      the price moved before trading began
    execution    s Σ q_i (p_i − P_0)                  trading itself
    opportunity  s (X − Σ q_i)(P_c − P_0)             the shares not traded, marked at the close
    fees         commission

and because the simulator knows the price path without our trades, execution
splits further, exactly:

    spread       Σ q_i m_i h                          half the bid-ask spread
    temporary    Σ q_i m_i θ_i                        the square-root impact of each fill
    permanent    s Σ q_i (m_i − u_i)                  our earlier trades' lasting impact on the price
    timing       s Σ q_i (u_i − P_0)                  where the market went on its own

with m the mid we traded against, u the mid as it would have been without us, h
the half-spread and θ the temporary impact. In a real TCA the last three cannot
be separated - impact and timing are both in the price - which is why impact
models are estimated from thousands of orders. Here they can, and
:func:`calibrate` checks what such an estimate recovers against the truth.

Costs are reported in base currency and in basis points of the order's value at
the decision price, positive meaning a cost. Alongside the shortfall, the
**VWAP slippage** compares the average price with the market's VWAP over the
order's own trading window: the benchmark brokers are usually judged on, and
one an order can beat while costing its owner a great deal (by trading the
whole day into a price it pushed up itself).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..core.exceptions import ValidationError
from .algorithms import ExecutionResult

COMMISSION_BPS = 2.0  # an institutional agency rate


@dataclass(frozen=True)
class OrderCost:
    order_id: str
    instrument_id: str
    algorithm: str
    side: int
    quantity: float
    filled: float
    decision: float
    arrival: float
    average: float | None
    close: float
    vwap: float | None  # the market's VWAP while the order traded
    participation: float
    size_adv: float  # the order as a share of average daily volume
    daily_volatility: float
    # components, base currency, positive a cost
    delay: float
    spread: float
    temporary: float
    permanent: float
    timing: float
    opportunity: float
    fees: float

    @property
    def paper_value(self) -> float:
        return self.quantity * self.decision

    @property
    def execution(self) -> float:
        return self.spread + self.temporary + self.permanent + self.timing

    @property
    def impact(self) -> float:
        return self.temporary + self.permanent

    @property
    def shortfall(self) -> float:
        return self.delay + self.execution + self.opportunity + self.fees

    def bps(self, value: float) -> float:
        return value / self.paper_value * 1e4

    @property
    def shortfall_bps(self) -> float:
        return self.bps(self.shortfall)

    @property
    def arrival_slippage_bps(self) -> float:
        """Execution cost against the arrival price, per share filled, in basis points of the arrival price."""
        if self.average is None:
            return 0.0
        return self.side * (self.average - self.arrival) / self.arrival * 1e4

    @property
    def vwap_slippage_bps(self) -> float:
        if self.average is None or self.vwap is None:
            return 0.0
        return self.side * (self.average - self.vwap) / self.vwap * 1e4

    def components(self) -> dict[str, float]:
        return {
            "delay": self.delay,
            "spread": self.spread,
            "temporary impact": self.temporary,
            "permanent impact": self.permanent,
            "timing": self.timing,
            "opportunity": self.opportunity,
            "fees": self.fees,
        }


def analyse(
    result: ExecutionResult, decision_price: float | None = None, commission_bps: float = COMMISSION_BPS
) -> OrderCost:
    """The implementation shortfall of an executed order, decomposed exactly."""
    parent = result.parent
    market = result.market
    decision = decision_price if decision_price is not None else parent.decision_price
    if decision is None:
        decision = market.profile.previous_close
    sign = parent.side.sign
    arrival = market.mid(result.params.start) if result.params.start > 0 else market.open_price
    records = result.records
    filled = sum(record.quantity for record in records)
    quantity = parent.quantity
    spread = sum(record.quantity * record.mid * record.half_spread for record in records)
    temporary = sum(record.quantity * record.mid * record.temporary for record in records)
    permanent = sign * sum(record.quantity * (record.mid - record.unimpacted) for record in records)
    timing = sign * sum(record.quantity * (record.unimpacted - arrival) for record in records)
    notional = sum(record.quantity * record.price for record in records)
    vwap = None
    if records:
        vwap = market.vwap(records[0].minute, records[-1].minute + 1, records)
    cost = OrderCost(
        order_id=parent.order_id,
        instrument_id=parent.instrument_id,
        algorithm=result.params.name,
        side=sign,
        quantity=quantity,
        filled=filled,
        decision=decision,
        arrival=arrival,
        average=parent.average_price,
        close=market.close,
        vwap=vwap,
        participation=result.participation,
        size_adv=quantity / market.profile.average_volume,
        daily_volatility=market.profile.daily_volatility,
        delay=sign * quantity * (arrival - decision),
        spread=spread,
        temporary=temporary,
        permanent=permanent,
        timing=timing,
        opportunity=sign * (quantity - filled) * (market.close - arrival),
        fees=notional * commission_bps / 1e4,
    )
    check_decomposition(cost, records_value=notional)
    return cost


def check_decomposition(cost: OrderCost, records_value: float) -> None:
    """The components must add up to the shortfall computed directly from the fills."""
    direct = cost.side * (records_value - cost.filled * cost.decision)
    direct += cost.side * (cost.quantity - cost.filled) * (cost.close - cost.decision) + cost.fees
    if abs(direct - cost.shortfall) > 1e-6 * max(1.0, abs(cost.paper_value)):
        raise ValidationError(f"{cost.order_id}: the shortfall components do not add up ({cost.shortfall} vs {direct})")


def pre_trade_estimate_bps(
    size_adv: float,
    daily_volatility: float,
    spread_bps: float,
    temporary: float,
    permanent: float,
    commission_bps: float = COMMISSION_BPS,
) -> float:
    """The expected execution cost of an order traded evenly over the day, in basis points.

    Trading X shares at a constant share of volume π = X / (X + V) over the day
    pays the commission, half the spread, a temporary impact of η σ √(π / (1 − π))
    on every share, and on average half the permanent impact the order itself causes.
    """
    participation = size_adv / (1.0 + size_adv)
    temporary_cost = temporary * daily_volatility * math.sqrt(participation / (1 - participation))
    return commission_bps + (spread_bps / 2e4 + temporary_cost + 0.5 * permanent * daily_volatility * size_adv) * 1e4


@dataclass(frozen=True)
class ImpactFit:
    """Impact cost regressed on σ √(participation): the coefficient a desk would estimate from its own orders."""

    coefficient: float
    standard_error: float
    r_squared: float
    observations: int
    source: str  # "measured impact" or "arrival slippage"

    def interval(self, level: float = 1.96) -> tuple[float, float]:
        return self.coefficient - level * self.standard_error, self.coefficient + level * self.standard_error


def calibrate(costs: Sequence[OrderCost], *, observed: bool = True) -> ImpactFit:
    """Fit ``cost_bps = c · σ_bps · √π`` through the origin.

    ``observed=True`` uses what a desk sees - execution cost against arrival,
    less the half-spread, which still contains the market's own move (timing) -
    and ``observed=False`` the impact the simulator measured. The temporary
    coefficient that generated the data is the answer both should find, the
    second tightly and the first only with enough orders.
    """
    rows = [cost for cost in costs if cost.filled > 0 and cost.participation > 0]
    if len(rows) < 3:
        raise ValidationError("a calibration needs at least three executed orders")
    x = np.array(
        [cost.daily_volatility * 1e4 * math.sqrt(cost.participation / (1 - cost.participation)) for cost in rows]
    )
    if observed:
        y = np.array([(cost.execution - cost.spread) / (cost.filled * cost.arrival) * 1e4 for cost in rows])
    else:
        y = np.array([cost.temporary / (cost.filled * cost.arrival) * 1e4 for cost in rows])
    coefficient = float(x @ y / (x @ x))
    residuals = y - coefficient * x
    dof = max(len(rows) - 1, 1)
    sigma2 = float(residuals @ residuals) / dof
    standard_error = math.sqrt(sigma2 / float(x @ x))
    total = float(y @ y)
    r_squared = 1 - float(residuals @ residuals) / total if total > 0 else 0.0
    return ImpactFit(
        coefficient, standard_error, r_squared, len(rows), "arrival slippage" if observed else "measured impact"
    )
