"""The Day 8 charts: the rebalance traded - shortfall, algorithms, impact, allocation - and the client report.

Data preparation lives here and the chart functions take plain inputs, as for
the earlier days. The optimiser and the execution simulator load when a chart
is drawn, not when the gallery is listed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .viz.execution import (
    plot_ac_frontier,
    plot_algorithm_comparison,
    plot_allocation,
    plot_blotter,
    plot_impact_calibration,
    plot_intraday,
    plot_order_lifecycle,
    plot_participation,
    plot_pre_post,
    plot_shortfall,
    plot_trajectories,
)

if TYPE_CHECKING:
    from .execution.algorithms import ExecutionResult
    from .execution.tca import OrderCost
    from .gallery import GalleryItem
    from .reporting.client_pack import ClientPack
    from .services.demo_execution import DemoExecution

SHOWCASE = "DE-BAYN"  # the block the single-order charts follow: the largest traded by VWAP
LIFECYCLE = "BM-JP-FIN-1"  # a block that does not finish: children partially filled, the parent expires
MARKET_COMPONENTS = ("delay", "timing", "opportunity")


def _demo() -> DemoExecution:
    from .services.demo_execution import build_demo_execution

    return build_demo_execution()


def _index(instrument_id: str) -> int:
    demo = _demo()
    return next(index for index, block in enumerate(demo.blocks) if block.order.instrument_id == instrument_id)


def _controllable(cost: OrderCost) -> float:
    return cost.spread + cost.temporary + cost.permanent + cost.fees


def _label() -> str:
    return f"{_demo().trade_date:%d %B %Y}"


# ---------------------------------------------------------------------------- the day
def shortfall_chart() -> Figure:
    demo = _demo()
    totals = demo.totals()
    names = ("delay", "spread", "temporary impact", "permanent impact", "timing", "opportunity", "fees")
    rows = [
        (
            cost.instrument_id,
            cost.algorithm,
            cost.bps(_controllable(cost)),
            cost.bps(cost.delay + cost.timing + cost.opportunity),
            cost.size_adv,
        )
        for cost in demo.costs
    ]
    return plot_shortfall({name: totals[name] for name in names}, totals["paper value"], rows, _label())


def _realised(result: ExecutionResult) -> np.ndarray:
    filled = np.zeros(result.market.minutes)
    for record in result.records:
        filled[record.minute] += record.quantity
    return np.cumsum(filled) / result.parent.quantity


def trajectories_chart() -> Figure:
    from .execution.algorithms import ALGORITHMS, AlgoParams, execute, schedule
    from .execution.market import volume_profile
    from .execution.orders import Order

    demo = _demo()
    index = _index(SHOWCASE)
    block = demo.blocks[index]
    plans, realised = {}, {}
    for name in ALGORITHMS:
        market = demo.market(index)
        order = Order(f"T-{name}", block.order.instrument_id, block.order.side, block.order.quantity, demo.trade_date)
        params = AlgoParams(name)
        plans[name] = schedule(params, block.order.quantity, market)
        realised[name] = _realised(execute(order, market, params))
    return plot_trajectories(volume_profile(), plans, realised, SHOWCASE)


def ac_frontier_chart() -> Figure:
    from .execution.algorithms import AlgoParams, is_problem, risk_aversion_for

    demo = _demo()
    index = _index(SHOWCASE)
    block = demo.blocks[index]
    market = demo.market(index)
    params = AlgoParams("is")
    problem = is_problem(params, block.order.quantity, market)
    horizon = params.end - params.start
    levels = np.concatenate([[0.0], np.logspace(-9, -3, 60)])
    frontier = problem.frontier(levels)
    markers = []
    for label, urgency in (("TWAP (risk-neutral)", 0.0), ("chosen: urgency 1.5", 1.5), ("urgency 6", 6.0)):
        level = risk_aversion_for(problem, urgency / horizon) if urgency > 0 else 0.0
        markers.append((label, float(np.sqrt(problem.variance(level))), problem.expected_cost(level)))
    trajectories = [
        (f"urgency {urgency:g}", problem.holdings(risk_aversion_for(problem, urgency / horizon) if urgency else 0.0))
        for urgency in (0.0, 1.5, 6.0, 20.0)
    ]
    value = block.order.quantity * market.open_price
    return plot_ac_frontier(frontier, trajectories, markers, SHOWCASE, value)


def intraday_chart() -> Figure:
    demo = _demo()
    index = _index(SHOWCASE)
    result = demo.executions[index]
    cost = demo.costs[index]
    market = result.market
    impacted = market.unimpacted * (1.0 + market.shift)
    fills = [(record.minute, record.quantity, record.price) for record in result.records]
    levels = {"decision": cost.decision, "arrival": cost.arrival}
    if cost.average is not None:
        levels["average"] = cost.average
    if cost.vwap is not None:
        levels["VWAP"] = cost.vwap
    return plot_intraday(
        market.unimpacted, impacted, fills, levels, SHOWCASE, result.params.name, result.parent.side.value
    )


def comparison_chart() -> Figure:
    demo = _demo()
    rows = []
    for name, costs in demo.comparison.items():
        paper = sum(cost.paper_value for cost in costs)
        controllable = sum(_controllable(cost) for cost in costs) / paper * 1e4
        spread = float(np.std([cost.shortfall_bps for cost in costs]))
        total = sum(cost.shortfall for cost in costs) / paper * 1e4
        fill = sum(cost.filled * cost.decision for cost in costs) / paper  # by value, not by share count
        vwap = float(np.mean([cost.vwap_slippage_bps for cost in costs if cost.filled > 0]))
        rows.append((name, controllable, spread, total, fill, vwap))
    return plot_algorithm_comparison(rows)


def calibration_chart() -> Figure:
    import math

    from .services.demo_execution import IMPACT

    demo = _demo()

    def x_of(cost: OrderCost) -> float:
        return cost.daily_volatility * 1e4 * math.sqrt(cost.participation / (1 - cost.participation))

    history = [cost for cost in demo.desk_history if cost.filled > 0]
    measured = [
        (x_of(cost), cost.temporary / (cost.filled * cost.arrival) * 1e4)
        for cost in history
        if cost.algorithm in ("vwap", "pov")
    ]
    observed = [(x_of(cost), (cost.execution - cost.spread) / (cost.filled * cost.arrival) * 1e4) for cost in history]
    fits = {name: (fit.coefficient, fit.standard_error, fit.r_squared) for name, fit in demo.calibration.items()}
    return plot_impact_calibration(measured, observed, fits, IMPACT.temporary)


def pre_post_chart() -> Figure:
    demo = _demo()
    rows = [
        (
            cost.size_adv,
            demo.pre_trade_bps(cost),
            _controllable(cost) / (cost.filled * cost.arrival) * 1e4,
            cost.algorithm,
        )
        for cost in demo.desk_history
        if cost.filled > 0
    ]
    return plot_pre_post(rows)


def allocation_chart() -> Figure:
    from .services.demo_execution import FOLLOWERS

    demo = _demo()
    rows = []
    for block, allocations in zip(demo.blocks, demo.allocations, strict=True):
        requested = {member.portfolio_id: member.quantity for member in block.members}
        allocated = {item.portfolio_id: item.quantity for item in allocations}
        rows.append((block.order.instrument_id, requested, allocated, block.order.average_price or 0.0))
    return plot_allocation(rows, list(FOLLOWERS))


def lifecycle_chart() -> Figure:
    demo = _demo()
    result = demo.executions[_index(LIFECYCLE)]

    def events(order):  # type: ignore[no-untyped-def]
        return [(event.minute, event.status.value) for event in order.events if event.status.value != "pending new"]

    children = [
        (child.order_id.split("-")[-1], events(child), child.quantity, child.cumulative) for child in result.children
    ]
    fills: dict[int, float] = {}
    for record in result.records:
        fills[record.minute] = fills.get(record.minute, 0.0) + record.quantity
    return plot_order_lifecycle(
        (f"{result.parent.order_id} (parent)", events(result.parent)),
        children,
        sorted(fills.items()),
        result.market.minutes,
    )


def participation_chart() -> Figure:
    demo = _demo()
    names, rows = [], []
    for result in demo.executions:
        share = np.zeros(result.market.minutes)
        for record in result.records:
            volume = float(result.market.volumes[record.minute])
            share[record.minute] = record.quantity / (volume + record.quantity)
        names.append(f"{result.parent.instrument_id} ({result.params.name.upper()})")
        rows.append(share)
    return plot_participation(names, np.vstack(rows), 0.25)


def blotter_chart() -> Figure:
    demo = _demo()
    rows = []
    for result, cost in zip(demo.executions, demo.costs, strict=True):
        parent = result.parent
        average = f"{cost.arrival_slippage_bps:+.1f} bp" if cost.average is not None else "-"
        rows.append(
            (
                parent.order_id.split("-")[-1],
                parent.instrument_id,
                parent.side.value,
                f"{parent.quantity:,.0f}",
                f"{cost.size_adv:.2%}",
                result.params.name.upper(),
                f"{parent.fill_rate:.0%} ({parent.status.value})",
                average,
                f"{cost.shortfall_bps:+.1f} bp",
            )
        )
    return plot_blotter(rows, _label())


# ---------------------------------------------------------------------------- the client report
def _pack() -> ClientPack:
    from .reporting.client_pack import ClientPack

    return ClientPack(_demo())


def report_summary_chart() -> Figure:
    return _pack().summary()


def report_trading_chart() -> Figure:
    return _pack().trading()


def report_pages_chart() -> Figure:
    """Every page of the client report, side by side."""
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    from .viz.style import new_figure, title_block

    pages = _pack().pages()
    images = []
    for page in pages:
        figure = page.build()
        figure.set_size_inches(11.7, 16.5)
        canvas = FigureCanvasAgg(figure)
        figure.set_dpi(28)
        canvas.draw()
        images.append((page.title, np.asarray(canvas.buffer_rgba())))
        plt.close(figure)
    montage = new_figure(16.0, 10.4)
    columns = 5
    rows = int(np.ceil(len(images) / columns))
    grid = montage.add_gridspec(rows, columns, hspace=0.18, wspace=0.08, top=0.86, bottom=0.03, left=0.02, right=0.98)
    for index, (title, image) in enumerate(images):
        axis = montage.add_subplot(grid[divmod(index, columns)])
        axis.imshow(image)
        axis.set_title(f"{index + 1}. {title}", fontsize=8, loc="left")
        axis.axis("off")
    title_block(
        montage,
        "The client report: nine pages, one set of numbers",
        "Assembled from the objects every module uses - the valuation, the returns, the risk model, the mandate, the "
        "tax lots, the rebalance and the trades - so no number on one page can disagree with another.",
    )
    return montage


def execution_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    def item(filename: str, title: str, description: str, builder, group: str = "execution") -> GalleryItem:  # type: ignore[no-untyped-def]
        return GalleryItem(filename, title, description, builder, group)

    return (
        item(
            "implementation-shortfall.png",
            "Implementation shortfall of the rebalance",
            "The day's cost against the decision prices, split into delay, spread, impact, timing, opportunity and "
            "fees.",
            shortfall_chart,
        ),
        item(
            "execution-trajectories.png",
            "Five ways to work the same order",
            "TWAP, VWAP, POV, IS and Close: planned and realised completion against the volume curve.",
            trajectories_chart,
        ),
        item(
            "almgren-chriss-frontier.png",
            "The Almgren-Chriss frontier",
            "Expected cost against its risk for one block, and the trajectories from risk-neutral to urgent.",
            ac_frontier_chart,
        ),
        item(
            "intraday-execution.png",
            "One block through the day",
            "The price with and without our trades, every fill, and the decision, arrival, average and VWAP.",
            intraday_chart,
        ),
        item(
            "algorithm-comparison.png",
            "The same blocks, five algorithms",
            "Every block re-run with each algorithm on the same simulated day: cost, risk, fill rate, VWAP slippage.",
            comparison_chart,
        ),
        item(
            "impact-calibration.png",
            "Calibrating the impact model",
            "The square-root coefficient recovered from the desk's history, measured and as observed, against the "
            "truth.",
            calibration_chart,
        ),
        item(
            "pre-post-trade.png",
            "Pre-trade estimate against outcome",
            "The cost model's forecast against each order's realised spread, impact and fees, by order size.",
            pre_post_chart,
        ),
        item(
            "block-allocation.png",
            "Block orders allocated to accounts",
            "Three accounts' orders traded as one block per stock and shared back at one price, pro rata.",
            allocation_chart,
        ),
        item(
            "order-lifecycle.png",
            "An order's life in FIX states",
            "A parent order and its child orders through new, partially filled, cancelled, filled and expired.",
            lifecycle_chart,
        ),
        item(
            "participation-heatmap.png",
            "Participation minute by minute",
            "Each block's share of the market's volume through the day, against the 25% cap.",
            participation_chart,
        ),
        item(
            "trading-blotter.png",
            "The trading blotter",
            "Every block of the day: algorithm, fill, slippage against arrival and shortfall.",
            blotter_chart,
        ),
        item(
            "client-report-pages.png",
            "The client report",
            "All nine pages of the quarterly client report, assembled from every module's numbers.",
            report_pages_chart,
            "reporting",
        ),
        item(
            "client-report-summary.png",
            "Client report: the summary page",
            "Value, returns, risk, the mandate and the tax position on one page, with the quarter in brief.",
            report_summary_chart,
            "reporting",
        ),
        item(
            "client-report-trading.png",
            "Client report: trading and costs",
            "The account's share of the block orders, the prices it received and what trading cost.",
            report_trading_chart,
            "reporting",
        ),
    )
