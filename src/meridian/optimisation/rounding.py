"""From weights to orders: round lots, a minimum ticket, and the lots each sale relieves.

The optimiser trades fractions of NAV; a broker takes whole shares, in board
lots where the market has them (100 shares in Tokyo), and a desk will not send
a ticket too small to be worth its fixed cost. Rounding every trade to the
nearest lot and dropping the small ones one by one can break the cash band -
many buys rounded up together - so the rounding is itself an optimisation, a
small mixed-integer programme:

    minimise   sum |rounded trade value - continuous trade value|
    subject to each trade a whole number of lots, in the direction the
               continuous solution chose (never a sale turned into a purchase);
               each trade either zero or at least the minimum ticket;
               no sale larger than the position;
               cash after the trades within its band.

It is solved by HiGHS, branch and bound on a problem of one integer and one
binary per traded asset. Sales are then allocated to lots at the lowest tax
per unit first - which is what specific identification chooses, since the
lots of one asset differ in nothing but their tax.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np

from ..core.exceptions import ValidationError
from .rebalance import TRADE_EPSILON, LotSale, Rebalancer, RebalanceResult, Settings

DEFAULT_MIN_TICKET = 10_000.0  # base currency


@dataclass(frozen=True)
class Ticket:
    """One ticket for the desk."""

    asset_id: str
    side: str  # buy | sell
    units: float
    value: float  # base currency, at the unit value
    lots: tuple[tuple[str, float], ...] = ()  # (lot id, units) relieved by a sale

    @property
    def signed_value(self) -> float:
        return self.value if self.side == "buy" else -self.value


@dataclass
class RoundedRebalance:
    tickets: list[Ticket]
    continuous: dict[str, float]  # signed trade value per asset the optimiser proposed
    dropped: list[str]  # trades below the minimum ticket that were not worth raising
    raised: list[str]  # trades below the minimum ticket raised to it
    sales: list[LotSale]
    after: dict[str, float]
    cash_after: float
    tracking_error_after: float
    active_share_after: float
    cost: float  # fraction of NAV
    status: str
    min_ticket: float
    notes: list[str] = field(default_factory=list)

    @property
    def tax(self) -> float:
        return sum(sale.tax for sale in self.sales)

    @property
    def drift(self) -> float:
        """Total absolute difference between rounded and continuous trades, base currency."""
        rounded = {order.asset_id: order.signed_value for order in self.tickets}
        keys = rounded.keys() | self.continuous.keys()
        return sum(abs(rounded.get(key, 0.0) - self.continuous.get(key, 0.0)) for key in keys)


def round_trades(
    rebalancer: Rebalancer,
    result: RebalanceResult,
    settings: Settings | None = None,
    *,
    min_ticket: float = DEFAULT_MIN_TICKET,
) -> RoundedRebalance:
    settings = settings or Settings()
    nav = rebalancer.nav
    assets = rebalancer.assets
    sells = result.sells
    continuous: dict[str, float] = {}
    for asset in assets:
        value = (result.buys.get(asset.asset_id, 0.0) - sells.get(asset.asset_id, 0.0)) * nav
        if abs(value) > TRADE_EPSILON * nav:
            continuous[asset.asset_id] = value
    traded = [rebalancer.asset_index[key] for key in continuous]
    if not traded:
        return _finish(rebalancer, result, settings, continuous, {}, [], [], "optimal", min_ticket)

    count = len(traded)
    lots = cp.Variable(count, integer=True, name="lots")
    ticket = cp.Variable(count, boolean=True, name="ticket")
    deviation = cp.Variable(count, nonneg=True, name="deviation")
    lot_value = np.array([assets[i].lot_size * assets[i].unit_value for i in traded])
    target = np.array([abs(continuous[assets[i].asset_id]) for i in traded])
    direction = np.array([1.0 if continuous[assets[i].asset_id] > 0 else -1.0 for i in traded])
    # the most lots a trade may take: a sale no more than the position, a purchase at most a lot past its target
    ceiling = np.array(
        [
            math.floor(assets[i].quantity / assets[i].lot_size + 1e-9)
            if direction[k] < 0
            else math.ceil(target[k] / lot_value[k]) + 1
            for k, i in enumerate(traded)
        ],
        dtype=float,
    )
    order_value = cp.multiply(lot_value, lots)
    linear = np.array([rebalancer.costs.linear(assets[i]) for i in traded])
    cash = rebalancer.cash * nav - direction @ order_value
    cash_after_costs = cash - linear @ order_value
    constraints = [
        lots >= 0,
        lots <= cp.multiply(ceiling, ticket),
        order_value >= min_ticket * ticket,
        deviation >= order_value - target,
        deviation >= target - order_value,
        cash_after_costs >= settings.cash_band[0] * nav,
        cash <= settings.cash_band[1] * nav,
    ]
    problem = cp.Problem(cp.Minimize(cp.sum(deviation) / nav), constraints)
    # HiGHS directly when highspy is installed, otherwise through SciPy's milp (the same HiGHS inside)
    problem.solve(solver=cp.HIGHS if cp.HIGHS in cp.installed_solvers() else cp.SCIPY)
    if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        raise ValidationError(f"the rounding is {problem.status}")
    units: dict[str, float] = {}
    dropped: list[str] = []
    raised: list[str] = []
    for k, i in enumerate(traded):
        asset = assets[i]
        count_lots = round(float(np.asarray(lots.value)[k]))
        if count_lots == 0:
            dropped.append(asset.asset_id)
            continue
        units[asset.asset_id] = direction[k] * count_lots * asset.lot_size
        if target[k] < min_ticket <= count_lots * lot_value[k]:
            raised.append(asset.asset_id)
    return _finish(rebalancer, result, settings, continuous, units, dropped, raised, str(problem.status), min_ticket)


def _allocate(rebalancer: Rebalancer, asset_index: int, units: float, rates: np.ndarray) -> list[tuple[int, float]]:
    """Units sold from each lot of one asset, lowest tax per unit of value first."""
    positions = [
        position for position, lot in enumerate(rebalancer.lots) if rebalancer.lot_asset[position] == asset_index
    ]
    positions.sort(key=lambda position: (rates[position], rebalancer.lots[position].lot_id))
    output = []
    remaining = units
    for position in positions:
        if remaining <= 1e-9:
            break
        take = min(remaining, rebalancer.lots[position].quantity)
        output.append((position, take))
        remaining -= take
    return output


def _finish(
    rebalancer: Rebalancer,
    result: RebalanceResult,
    settings: Settings,
    continuous: dict[str, float],
    units: dict[str, float],
    dropped: list[str],
    raised: list[str],
    status: str,
    min_ticket: float,
) -> RoundedRebalance:
    nav = rebalancer.nav
    rates = rebalancer.lot_rates(settings)
    bought = np.zeros(len(rebalancer.assets))
    sold = np.zeros(len(rebalancer.lots))
    tickets: list[Ticket] = []
    for asset_id, amount in sorted(units.items()):
        index = rebalancer.asset_index[asset_id]
        asset = rebalancer.assets[index]
        if amount > 0:
            bought[index] = amount * asset.unit_value / nav
            tickets.append(Ticket(asset_id, "buy", amount, amount * asset.unit_value))
            continue
        relieved = _allocate(rebalancer, index, -amount, rates)
        if settings.lot_relief != "specific":
            weights = np.zeros(len(rebalancer.lots))
            for position, count in relieved:
                weights[position] = count * asset.unit_value / nav
            relieved = [
                (position, weight * nav / asset.unit_value)
                for position, weight in enumerate(rebalancer.relieve(weights, settings.lot_relief))
                if weight > 0
            ]
        for position, count in relieved:
            sold[position] += count * asset.unit_value / nav
        lots = tuple((rebalancer.lots[position].lot_id, float(count)) for position, count in relieved)
        tickets.append(Ticket(asset_id, "sell", -amount, -amount * asset.unit_value, lots))
    by_asset = rebalancer.selling @ sold
    after = rebalancer.w0 + bought - by_asset
    cost = float(
        sum(
            rebalancer.costs.cost(asset, nav, bought[i]) + rebalancer.costs.cost(asset, nav, by_asset[i])
            for i, asset in enumerate(rebalancer.assets)
        )
    )
    cash_after = rebalancer.cash - float(bought.sum()) + float(sold.sum()) - cost
    notes = []
    if cash_after < settings.cash_band[0] - 1e-9:
        notes.append(f"cash after market impact {cash_after:.2%} is below the band's {settings.cash_band[0]:.0%}")
    return RoundedRebalance(
        tickets=tickets,
        continuous=continuous,
        dropped=dropped,
        raised=raised,
        sales=rebalancer.sales(sold),
        after={asset.asset_id: float(after[i]) for i, asset in enumerate(rebalancer.assets)},
        cash_after=cash_after,
        tracking_error_after=rebalancer.evaluate(after),
        active_share_after=rebalancer.active_share(after, cash_after),
        cost=cost,
        status=status,
        min_ticket=min_ticket,
        notes=notes,
    )
