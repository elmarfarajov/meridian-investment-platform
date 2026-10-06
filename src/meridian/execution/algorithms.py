"""Trading algorithms, and the engine that works a parent order through a simulated day.

An agency desk does not send a large order to the market at once. It gives it
to an algorithm, which cuts it into child orders over time according to a
schedule:

* **TWAP** - evenly in time. Simple, predictable, blind to volume.
* **VWAP** - in proportion to the volume the market is expected to trade in each
  minute, so the order's average price tracks the day's VWAP: the benchmark most
  institutions are judged against.
* **POV** (percentage of volume) - a fixed share of whatever actually trades,
  minute by minute; the order finishes when it finishes.
* **IS** (implementation shortfall, arrival price) - the Almgren-Chriss
  trajectory: front-loaded, to trade impact against the risk of the price moving
  away from where it was when the order arrived. ``urgency`` is ``κT``: zero is
  TWAP, larger is faster.
* **Close** - into the closing minutes, where the day's heaviest volume is: the
  benchmark for index funds, which are valued at the close.

A participation rate is the order's share of *all* the volume traded, its own
included - ``q / (q + V)`` for ``q`` shares against the market's ``V`` - the
definition the pre-trade model and the transaction cost analysis use. So a 10%
POV order trades ``V / 9`` shares against the market's ``V``, not ``V / 10``.

Every algorithm respects a **participation cap** (no more than a quarter of any
minute's volume, ours included, by default) and an optional **limit price**; what cannot be
done in time is left undone, and the parent order expires at the end of its
window with the rest unfilled - the opportunity cost that transaction cost
analysis charges it.

Each slice of the schedule is a **child order** with its own lifecycle; the
child is cancelled at the end of its slice if it is not done, and the remainder
rolls into the next one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..core.exceptions import ValidationError
from .almgren_chriss import ExecutionProblem, linear_eta
from .market import SESSION_MINUTES, ExecutionRecord, MarketDay, volume_profile
from .orders import Fill, Order

ALGORITHMS: tuple[str, ...] = ("twap", "vwap", "pov", "is", "close")
CLOSE_WINDOW = 10  # minutes before the close the close algorithm trades in


@dataclass(frozen=True)
class AlgoParams:
    name: str = "vwap"
    start: int = 0  # minute the order is released
    end: int = SESSION_MINUTES  # minute by which it must be done
    participation: float = 0.10  # POV's target rate; for the others, the cap is max_participation
    max_participation: float = 0.25
    urgency: float = 2.0  # IS: kappa times the horizon
    slice_minutes: int = 15
    limit_price: float | None = None

    def __post_init__(self) -> None:
        if self.name not in ALGORITHMS:
            raise ValidationError(f"unknown algorithm {self.name!r}; expected one of {', '.join(ALGORITHMS)}")
        if not 0 <= self.start < self.end <= SESSION_MINUTES:
            raise ValidationError("the window must lie within the session")
        if not 0 < self.participation <= self.max_participation <= 1:
            raise ValidationError("participation rates must satisfy 0 < participation <= cap <= 1")
        if self.slice_minutes < 1 or self.urgency < 0:
            raise ValidationError("slices must be at least a minute and urgency not negative")


def shares_at_rate(rate: float, market_volume: float) -> float:
    """Shares that make ``rate`` of a minute's total volume when the rest of the market trades ``market_volume``."""
    if rate >= 1.0:
        return math.inf
    return rate / (1.0 - rate) * market_volume


def schedule(params: AlgoParams, shares: float, market: MarketDay | None = None) -> np.ndarray:
    """Cumulative share of the order planned to be done by the end of each minute of the session.

    POV has no plan in advance - it follows realised volume - and returns the
    VWAP curve as its expectation.
    """
    minutes = SESSION_MINUTES
    weights = np.zeros(minutes)
    window = slice(params.start, params.end)
    if params.name == "twap":
        weights[window] = 1.0
    elif params.name in ("vwap", "pov"):
        weights[window] = volume_profile(minutes)[window]
    elif params.name == "close":
        weights[max(params.end - CLOSE_WINDOW, params.start) : params.end] = 1.0
    else:  # is: the Almgren-Chriss trajectory, one interval per minute
        horizon = params.end - params.start
        holdings = _is_holdings(params, shares, horizon, market)
        weights[window] = -np.diff(holdings)
    total = weights.sum()
    if total <= 0:
        raise ValidationError("the schedule trades nothing")
    return np.cumsum(weights / total)


def _is_holdings(params: AlgoParams, shares: float, horizon: int, market: MarketDay | None) -> np.ndarray:
    if params.urgency == 0:
        return shares * (1 - np.linspace(0, 1, horizon + 1))
    if market is None:  # the shape depends only on kappa T: build it from the urgency directly
        kappa = params.urgency / horizon
        times = np.arange(horizon + 1)
        return shares * np.sinh(kappa * (horizon - times)) / math.sinh(kappa * horizon)
    problem = is_problem(params, shares, market)
    return problem.holdings(risk_aversion_for(problem, params.urgency / horizon))


def is_problem(params: AlgoParams, shares: float, market: MarketDay) -> ExecutionProblem:
    """The Almgren-Chriss problem an order poses in a market: linear impact matched to the square-root law."""
    profile = market.profile
    horizon = params.end - params.start
    price = market.arrival(params.start)
    sigma_minute = price * profile.daily_volatility / math.sqrt(SESSION_MINUTES)
    rate = shares / horizon
    bar_volume = profile.average_volume / SESSION_MINUTES
    eta = linear_eta(market.impact.temporary, profile.daily_volatility, price, rate, bar_volume)
    gamma = price * market.impact.permanent * profile.daily_volatility / profile.average_volume
    epsilon = price * profile.spread_bps / 2e4
    return ExecutionProblem(shares, float(horizon), horizon, sigma_minute, eta, gamma, epsilon)


def risk_aversion_for(problem: ExecutionProblem, kappa: float) -> float:
    """The risk aversion whose trajectory decays at rate ``kappa`` per minute."""
    tau = problem.tau
    kappa_tilde_sq = 2.0 * (math.cosh(kappa * tau) - 1.0) / tau**2
    return kappa_tilde_sq * problem.eta_tilde / problem.sigma**2


@dataclass
class ExecutionResult:
    parent: Order
    children: list[Order]
    records: list[ExecutionRecord]
    market: MarketDay
    params: AlgoParams
    planned: np.ndarray = field(default_factory=lambda: np.zeros(0))  # cumulative plan, shares

    @property
    def filled(self) -> float:
        return self.parent.cumulative

    @property
    def participation(self) -> float:
        """Our share of all volume traded while the order was working."""
        if not self.records:
            return 0.0
        first, last = self.records[0].minute, self.records[-1].minute + 1
        market = float(self.market.volumes[first:last].sum())
        return self.filled / (market + self.filled)

    @property
    def duration(self) -> int:
        return 0 if not self.records else self.records[-1].minute - self.records[0].minute + 1


def execute(parent: Order, market: MarketDay, params: AlgoParams) -> ExecutionResult:
    """Work a parent order through the day with an algorithm; returns its fills and child orders."""
    if parent.instrument_id != market.profile.instrument_id:
        raise ValidationError(f"{parent.order_id} is for {parent.instrument_id}, the market for another stock")
    sign = parent.side.sign
    shares = parent.quantity
    plan = schedule(params, shares, market) * shares
    parent.release(params.start, params.name)
    children: list[Order] = []
    records: list[ExecutionRecord] = []
    limit = params.limit_price if params.limit_price is not None else parent.limit_price
    done = 0.0
    for slice_start in range(params.start, params.end, params.slice_minutes):
        slice_end = min(slice_start + params.slice_minutes, params.end)
        leaves = shares - done
        if leaves < 1:
            break
        target = leaves if params.name == "pov" else min(max(math.floor(plan[slice_end - 1] - done + 1e-09), 0), leaves)
        if target < 1:
            continue
        child = Order(
            f"{parent.order_id}-C{len(children) + 1:02d}",
            parent.instrument_id,
            parent.side,
            float(target),
            parent.trade_date,
            parent_id=parent.order_id,
            algorithm=params.name,
            limit_price=limit,
        )
        child.release(slice_start)
        children.append(child)
        child_done = 0.0
        for minute in range(slice_start, slice_end):
            volume = float(market.volumes[minute])
            cap = shares_at_rate(params.max_participation, volume)
            # POV follows the volume that comes; the others catch up with their plan minute by minute
            want = shares_at_rate(params.participation, volume) if params.name == "pov" else plan[minute] - done
            quantity = math.floor(min(want, cap, target - child_done, shares - done) + 1e-9)
            if quantity < 1:
                continue
            record = market.trade(minute, float(quantity), sign, limit)
            if record is None:
                continue
            records.append(record)
            fill_number = len(records)
            child.fill(
                Fill(f"{child.order_id}-F{fill_number:03d}", child.order_id, minute, record.quantity, record.price)
            )
            parent.fill(
                Fill(f"{parent.order_id}-F{fill_number:03d}", parent.order_id, minute, record.quantity, record.price)
            )
            child_done += record.quantity
            done += record.quantity
            if child.status.is_done:
                break
        if not child.status.is_done:
            child.cancel(slice_end - 1, "slice ended; the rest rolls into the next child")
    if not parent.status.is_done:
        parent.expire(params.end - 1)
    parent.check()
    for child in children:
        child.check()
    return ExecutionResult(parent, children, records, market, params, plan)
