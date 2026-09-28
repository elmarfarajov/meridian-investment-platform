"""The trading day after the rebalance: the Day 7 proposal as block orders, worked, allocated and analysed.

The Day 7 optimiser proposed a rebalance of the Global Equity Core account on
18 September 2026. The same model portfolio is followed by two other accounts,
so on the next business day the desk receives three accounts' orders in the
same stocks:

* **PF-GLOBAL-EQ** - the demonstration account, with the proposal's own orders;
* **PF-BALANCED** - the equity sleeve of the Balanced Pension (Day 3's second
  portfolio), which follows the model at 45% of the size;
* **PF-INSTITUTIONAL** - an institutional mandate on the same model, 2.4 times
  the size. It is not in the Day 3 book; it is here to make the blocks the size
  a desk actually works.

The bond sale goes to the fixed-income desk by request for quote and is not
worked here. For each equity block the desk chooses an algorithm by size - a
simple **algorithm wheel**:

========================  ==========================================
order size (share of ADV)  algorithm
========================  ==========================================
under 2%                   VWAP over the whole day
2% to 10%                  IS (arrival price), moderately urgent
over 10%                   POV at 15%: it will not finish today
========================  ==========================================

Every block is also run with all five algorithms on the very same simulated
day, which is the comparison a real desk can never make. Beside the day, a
**desk history** of 400 simulated orders across the same stocks supplies the
data to calibrate the impact model, whose true parameters are known.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import cached_property, lru_cache

import numpy as np

from ..core.calendars import get_calendar
from ..execution.algorithms import ALGORITHMS, AlgoParams, ExecutionResult, execute
from ..execution.allocation import AccountOrder, Allocation, Block, aggregate, allocate
from ..execution.market import ImpactModel, MarketDay, StockProfile
from ..execution.orders import Order, Side
from ..execution.tca import COMMISSION_BPS, ImpactFit, OrderCost, analyse, calibrate, pre_trade_estimate_bps
from ..optimisation.assets import TradableAsset
from .demo_optimisation import DemoOptimisation, build_demo_optimisation

#: accounts following the model, and their size relative to the demonstration account
FOLLOWERS: dict[str, float] = {"PF-GLOBAL-EQ": 1.0, "PF-BALANCED": 0.45, "PF-INSTITUTIONAL": 2.4}
IMPACT = ImpactModel()
DESK_ORDERS = 400
DESK_SEED = 8_000
DAY_SEED = 2_026


def choose_algorithm(size_adv: float) -> AlgoParams:
    """The desk's algorithm wheel: VWAP for small orders, IS for medium, POV for the large."""
    if size_adv < 0.02:
        return AlgoParams("vwap")
    if size_adv < 0.10:
        return AlgoParams("is", urgency=1.5)
    return AlgoParams("pov", participation=0.15)


@dataclass(frozen=True)
class AccountCost:
    """One account's share of a block: what it got, at what price, and what that cost against its decision."""

    allocation: Allocation
    decision: float
    close: float

    @property
    def shortfall(self) -> float:
        side = 1 if self.allocation.side is Side.BUY else -1
        filled = self.allocation.quantity
        unfilled = self.allocation.requested - filled
        traded = side * filled * (self.allocation.price - self.decision) if filled else 0.0
        fees = filled * self.allocation.price * COMMISSION_BPS / 1e4
        return traded + side * unfilled * (self.close - self.decision) + fees

    @property
    def shortfall_bps(self) -> float:
        return self.shortfall / (self.allocation.requested * self.decision) * 1e4


@dataclass
class DemoExecution:
    optimisation: DemoOptimisation

    @cached_property
    def decision_day(self) -> date:
        return self.optimisation.as_of

    @cached_property
    def trade_date(self) -> date:
        return get_calendar("XNYS").add_business_days(self.decision_day, 1)

    @cached_property
    def assets(self) -> dict[str, TradableAsset]:
        return {asset.asset_id: asset for asset in self.optimisation.assets}

    def profile(self, instrument_id: str) -> StockProfile:
        asset = self.assets[instrument_id]
        return StockProfile(
            instrument_id,
            asset.price,
            asset.daily_volatility,
            asset.daily_volume / asset.price,
            asset.spread_bps,
        )

    # ------------------------------------------------------------------ orders
    @cached_property
    def account_orders(self) -> list[AccountOrder]:
        """Each following account's orders: the proposal's tickets scaled to the account, in whole lots."""
        output = []
        for ticket in self.optimisation.tickets.tickets:
            asset = self.assets[ticket.asset_id]
            if asset.daily_volume <= 0:  # the bond: to the fixed-income desk
                continue
            side = Side.BUY if ticket.side == "buy" else Side.SELL
            for portfolio_id, scale in FOLLOWERS.items():
                lots = math.floor(ticket.units * scale / asset.lot_size + 1e-9)
                if lots >= 1:
                    output.append(AccountOrder(portfolio_id, ticket.asset_id, side, lots * asset.lot_size, asset.price))
        return output

    @cached_property
    def rfq_orders(self) -> list[str]:
        return [
            ticket.asset_id
            for ticket in self.optimisation.tickets.tickets
            if self.assets[ticket.asset_id].daily_volume <= 0
        ]

    @cached_property
    def blocks(self) -> list[Block]:
        return aggregate(self.account_orders, self.trade_date)

    def _seed(self, index: int) -> int:
        return DAY_SEED + index

    def market(self, index: int) -> MarketDay:
        block = self.blocks[index]
        return MarketDay.simulate(self.profile(block.order.instrument_id), seed=self._seed(index), impact=IMPACT)

    # ------------------------------------------------------------------ the day
    @cached_property
    def executions(self) -> list[ExecutionResult]:
        """Every block worked by the algorithm the wheel chose."""
        output = []
        for index, block in enumerate(self.blocks):
            profile = self.profile(block.order.instrument_id)
            params = choose_algorithm(block.order.quantity / profile.average_volume)
            output.append(execute(block.order, self.market(index), params))
        return output

    @cached_property
    def costs(self) -> list[OrderCost]:
        return [analyse(result) for result in self.executions]

    @cached_property
    def allocations(self) -> list[list[Allocation]]:
        self.executions  # noqa: B018 - a block is allocated only after it has been worked
        return [allocate(block) for block in self.blocks]

    @cached_property
    def account_costs(self) -> dict[str, list[AccountCost]]:
        output: dict[str, list[AccountCost]] = defaultdict(list)
        for block, allocations, result in zip(self.blocks, self.allocations, self.executions, strict=True):
            decisions = {member.portfolio_id: member.decision_price for member in block.members}
            for allocation in allocations:
                output[allocation.portfolio_id].append(
                    AccountCost(allocation, decisions[allocation.portfolio_id], result.market.close)
                )
        return dict(output)

    @cached_property
    def comparison(self) -> dict[str, list[OrderCost]]:
        """Every block run again with each algorithm, on the same simulated day."""
        output: dict[str, list[OrderCost]] = {}
        for name in ALGORITHMS:
            costs = []
            for index, block in enumerate(self.blocks):
                order = Order(
                    f"{block.order.order_id}-{name.upper()}",
                    block.order.instrument_id,
                    block.order.side,
                    block.order.quantity,
                    self.trade_date,
                    decision_price=block.order.decision_price,
                )
                costs.append(analyse(execute(order, self.market(index), AlgoParams(name))))
            output[name] = costs
        return output

    # ------------------------------------------------------------------ the desk's history
    @cached_property
    def desk_history(self) -> list[OrderCost]:
        """Orders across the account's stocks, sizes from 0.2% to 25% of volume, every algorithm."""
        rng = np.random.default_rng(DESK_SEED)
        stocks = [key for key, asset in self.assets.items() if asset.daily_volume > 0]
        costs = []
        for number in range(DESK_ORDERS):
            instrument_id = stocks[number % len(stocks)]
            profile = self.profile(instrument_id)
            size = float(np.exp(rng.uniform(math.log(0.002), math.log(0.25))))
            quantity = max(round(size * profile.average_volume), 1)
            algorithm = ALGORITHMS[number % 4]  # twap, vwap, pov, is
            side = Side.BUY if rng.random() < 0.5 else Side.SELL
            market = MarketDay.simulate(profile, seed=DESK_SEED + number, impact=IMPACT)
            order = Order(
                f"H{number:04d}",
                instrument_id,
                side,
                float(quantity),
                self.trade_date,
                decision_price=profile.previous_close,
            )
            costs.append(analyse(execute(order, market, AlgoParams(algorithm))))
        return costs

    @cached_property
    def calibration(self) -> dict[str, ImpactFit]:
        steady = [cost for cost in self.desk_history if cost.algorithm in ("vwap", "pov")]
        return {
            "measured": calibrate(steady, observed=False),
            "observed": calibrate(self.desk_history, observed=True),
        }

    def pre_trade_bps(self, cost: OrderCost) -> float:
        asset = self.assets[cost.instrument_id]
        return pre_trade_estimate_bps(
            cost.size_adv, cost.daily_volatility, asset.spread_bps, IMPACT.temporary, IMPACT.permanent
        )

    # ------------------------------------------------------------------ summaries
    def totals(self, costs: list[OrderCost] | None = None) -> dict[str, float]:
        costs = self.costs if costs is None else costs
        totals: dict[str, float] = defaultdict(float)
        for cost in costs:
            for name, value in cost.components().items():
                totals[name] += value
        totals["shortfall"] = sum(cost.shortfall for cost in costs)
        totals["paper value"] = sum(cost.paper_value for cost in costs)
        return dict(totals)


@lru_cache(maxsize=2)
def build_demo_execution() -> DemoExecution:
    logging.getLogger().setLevel(logging.WARNING)
    return DemoExecution(build_demo_optimisation())
