"""The Day 7 charts: the tax-aware rebalance, its lots, its costs, its frontier, and its worth over years.

Data preparation lives here and the chart functions take plain inputs, as for
the earlier days, so every figure is rebuilt deterministically by
``meridian charts gallery`` and shows the numbers the tests assert.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .viz.optimisation import (
    FrontierMarker,
    plot_after_tax_wealth,
    plot_efficient_frontier,
    plot_harvest_calendar,
    plot_lot_map,
    plot_lot_selection,
    plot_post_trade,
    plot_rebalance_report,
    plot_rebalance_trades,
    plot_rounding,
    plot_solve_rounds,
    plot_strategy_comparison,
    plot_tax_alpha,
    plot_tracking_budget,
    plot_trading_costs,
)

if TYPE_CHECKING:  # the optimiser (and cvxpy) loads when a chart is drawn, not when the gallery is listed
    from .gallery import GalleryItem
    from .optimisation.rebalance import LotSale, RebalanceResult
    from .services.demo_optimisation import DemoOptimisation

TE_BUDGET = 0.015  # the backtest's tax-aware budget, checked against optimisation.backtest.TE_LIMIT in the tests
WASH_SALE_WINDOW = 30

ACCOUNT = "Global Equity Core"


def _demo() -> DemoOptimisation:
    from .services.demo_optimisation import build_demo_optimisation

    return build_demo_optimisation()


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    size = abs(value)
    return f"{sign}${size / 1e6:,.2f}m" if size >= 1e6 else f"{sign}${size / 1e3:,.1f}k"


def _net_gains(sales: list[LotSale]) -> tuple[float, float]:
    short = sum(sale.gain for sale in sales if not sale.long_term and not sale.wash_sale)
    long = sum(sale.gain for sale in sales if sale.long_term and not sale.wash_sale)
    return short, long


def _harvested(result: RebalanceResult) -> float:
    return -sum(sale.gain for sale in result.sales if sale.gain < 0 and not sale.wash_sale)


# ---------------------------------------------------------------------------- charts on today's proposal
def frontier_chart() -> Figure:
    demo = _demo()
    frontier = demo.frontier
    points = [(point.tax, point.tracking_error, point.cost, point.turnover) for point in frontier.points]
    alternatives = demo.alternatives
    markers = [
        FrontierMarker("current portfolio", 0.0, frontier.tracking_error_before, "current"),
        FrontierMarker(
            "tax-blind", alternatives["tax-blind"].tax, alternatives["tax-blind"].tracking_error_after, "other"
        ),
        FrontierMarker(
            "tax-aware, no harvesting",
            alternatives["tax-aware, no harvesting"].tax,
            alternatives["tax-aware, no harvesting"].tracking_error_after,
            "other",
        ),
        FrontierMarker("proposal", demo.proposal.tax, demo.proposal.tracking_error_after, "proposal"),
    ]
    dominated = [(point.tax, point.tracking_error) for point in frontier.dominated]
    return plot_efficient_frontier(points, markers, demo.as_of, demo.nav, dominated)


def trades_chart() -> Figure:
    demo = _demo()
    result = demo.proposal
    target = dict(zip(demo.risk_view.keys, demo.risk_view.benchmark, strict=True))
    taxes: dict[str, float] = {}
    for sale in result.sales:
        taxes[sale.lot.asset_id] = taxes.get(sale.lot.asset_id, 0.0) + sale.tax
    rows = [
        (
            asset_id,
            result.before[asset_id],
            result.after[asset_id],
            target.get(asset_id, float("nan")),
            taxes.get(asset_id, 0.0),
        )
        for asset_id in result.before
        if abs(result.after[asset_id] - result.before[asset_id]) > 1e-6 or result.before[asset_id] > 0
    ]
    rows.sort(key=lambda row: -max(row[1], row[2]))
    summary = [
        ("Tracking error", f"{result.tracking_error_before:.2%} to {result.tracking_error_after:.2%}"),
        ("Tax realised", _money(result.tax)),
        ("Losses harvested", _money(_harvested(result))),
        ("Gains realised", _money(result.realised_gains)),
        ("Trading cost", f"{result.cost * 1e4:.1f} bp"),
        ("Turnover, two-way", f"{result.turnover:.0%}"),
        ("Active share", f"{result.active_share_before:.1%} to {result.active_share_after:.1%}"),
    ]
    return plot_rebalance_trades(rows, (result.cash_before, result.cash_after), demo.as_of, summary)


def lot_selection_chart() -> Figure:
    demo = _demo()
    from .services.demo_optimisation import HOUSE

    rebalancer, result = demo.house, demo.proposal
    rates = rebalancer.lot_rates(HOUSE)
    sold = rebalancer.sold_vector(result.sales)
    sold_assets = {sale.lot.asset_id for sale in result.sales}
    rows = []
    for position, lot in enumerate(rebalancer.lots):
        if lot.asset_id in sold_assets:
            rows.append(
                (
                    lot.asset_id,
                    lot.lot_id,
                    float(rates[position]),
                    lot.is_long_term(rebalancer.as_of),
                    float(rebalancer.lot_weights[position]),
                    float(sold[position]),
                )
            )
    relief = {method: sum(sale.tax for sale in sales) for method, sales in demo.relief.items()}
    gains = {method: _net_gains(sales) for method, sales in demo.relief.items()}
    return plot_lot_selection(rows, relief, gains)


def lot_map_chart() -> Figure:
    from .optimisation.taxes import has_replacement

    demo = _demo()
    rebalancer, result = demo.house, demo.proposal
    sold = rebalancer.sold_vector(result.sales)
    rows = []
    for position, lot in enumerate(rebalancer.lots):
        asset = rebalancer.assets[rebalancer.asset_index[lot.asset_id]]
        rows.append(
            (
                lot.asset_id,
                (rebalancer.as_of - lot.holding_start).days,
                asset.price / lot.basis_per_unit - 1,
                float(rebalancer.lot_weights[position]) * rebalancer.nav,
                lot.is_long_term(rebalancer.as_of),
                float(sold[position] / rebalancer.lot_weights[position])
                if rebalancer.lot_weights[position] > 0
                else 0.0,
                has_replacement(lot, rebalancer.recent),
            )
        )
    return plot_lot_map(rows, demo.as_of, wash_days=WASH_SALE_WINDOW)


def solve_rounds_chart() -> Figure:
    demo = _demo()
    result = demo.proposal
    rounds = [
        (item.number, item.tracking_error, item.active_share, item.tax, item.forbidden, item.restricted)
        for item in result.history
    ]
    from .optimisation.constraints import active_share_rule

    rule = active_share_rule(demo.compliance.mandate)
    return plot_solve_rounds(rounds, result.repairs, None if rule is None else rule[1])


def trading_costs_chart() -> Figure:
    demo = _demo()
    rebalancer, result = demo.house, demo.proposal
    costs = rebalancer.costs
    rows = []
    for asset in rebalancer.assets:
        traded = result.buys.get(asset.asset_id, 0.0) + result.sells.get(asset.asset_id, 0.0)
        if traded <= 0:
            continue
        linear = costs.linear(asset) * traded * rebalancer.nav
        impact = costs.impact(asset, rebalancer.nav) * traded**1.5 * rebalancer.nav
        rows.append((asset.asset_id, traded * rebalancer.nav, linear, impact))
    examples = []
    for asset_id in ("US-MSFT", "US-IVV", "DE-BAYN", "BM-JP-CD-1"):
        asset = rebalancer.assets[rebalancer.asset_index[asset_id]]
        examples.append((asset_id, costs.linear(asset), costs.impact(asset, rebalancer.nav)))
    return plot_trading_costs(rows, examples, rebalancer.nav)


def rounding_chart() -> Figure:
    demo = _demo()
    rounded = demo.tickets
    orders = {ticket.asset_id: ticket.signed_value for ticket in rounded.tickets}
    rows = []
    for asset_id, value in rounded.continuous.items():
        asset = demo.house.assets[demo.house.asset_index[asset_id]]
        flag = "dropped" if asset_id in rounded.dropped else "raised" if asset_id in rounded.raised else ""
        rows.append((asset_id, value, orders.get(asset_id, 0.0), asset.lot_size, flag))
    return plot_rounding(rows, rounded.min_ticket, rounded.drift)


def strategies_chart() -> Figure:
    demo = _demo()
    rows = [
        (
            name,
            result.tracking_error_after,
            result.tax,
            result.cost * result.nav,
            result.turnover,
            result.active_share_after,
            _harvested(result),
        )
        for name, result in demo.alternatives.items()
    ]
    return plot_strategy_comparison(rows, demo.nav)


def post_trade_chart() -> Figure:
    demo = _demo()
    decision = demo.compliance_check
    rows = []
    for change in decision.changes:
        before, after = change.before, change.after
        if before.utilisation is None or after.utilisation is None:
            continue
        title = after.rule.title or after.rule.rule_id
        rows.append((title, float(before.utilisation), float(after.utilisation), after.status, change.effect))
    return plot_post_trade(rows, decision.decision)


# ---------------------------------------------------------------------------- charts on the backtest
def _months() -> list[int]:
    return list(range(1, _demo().backtest.config.months + 1))


def tax_alpha_chart() -> Figure:
    summary = _demo().backtest
    alphas = {name: summary.tax_alpha(name) for name in summary.strategies}
    held = {name: summary.tax_alpha(name, liquidate=False) for name in summary.strategies}
    return plot_tax_alpha(alphas, held, summary.table(), len(summary.paths), summary.config.months)


def wealth_chart() -> Figure:
    summary = _demo().backtest
    wealth = {}
    taxes = {}

    def navs(name: str) -> np.ndarray:
        return np.array([[record.nav for record in path[name].records] for path in summary.paths])

    blind = navs("tax-blind")
    for name in summary.strategies:
        relative = navs(name) / blind - 1  # the same market on each path: only the management differs
        wealth[name] = (
            np.percentile(relative, 25, axis=0),
            np.median(relative, axis=0),
            np.percentile(relative, 75, axis=0),
        )
        taxes[name] = summary.cumulative_tax(name)
    return plot_after_tax_wealth(_months(), wealth, taxes)


def harvest_calendar_chart() -> Figure:
    summary = _demo().backtest
    name = "tax-aware, harvesting"
    nav = summary.config.nav
    harvested = np.mean([[record.harvested for record in path[name].records] for path in summary.paths], axis=0) / nav
    gains = np.mean([[record.realised_gains for record in path[name].records] for path in summary.paths], axis=0) / nav
    carry = np.mean([[record.carryforward for record in path[name].records] for path in summary.paths], axis=0) / nav
    dispersion = np.mean([path.dispersion for path in summary.paths], axis=0)
    return plot_harvest_calendar(_months(), harvested, gains, carry, dispersion)


def tracking_budget_chart() -> Figure:
    summary = _demo().backtest
    errors = {
        name: np.mean([[record.tracking_error for record in path[name].records] for path in summary.paths], axis=0)
        for name in summary.strategies
    }
    realised = {name: summary.realised_tracking_error(name) for name in summary.strategies}
    return plot_tracking_budget(_months(), errors, realised, TE_BUDGET)


def report_chart() -> Figure:
    demo = _demo()
    result, rounded, check = demo.proposal, demo.tickets, demo.compliance_check
    tiles = [
        ("Tracking error", f"{result.tracking_error_before:.2%} > {result.tracking_error_after:.2%}"),
        ("Tax realised", _money(rounded.tax)),
        ("Losses harvested", _money(_harvested(result))),
        ("Trading cost", f"{rounded.cost * 1e4:.1f} bp"),
        ("Turnover, two-way", f"{result.turnover:.0%}"),
        ("Orders", f"{len(rounded.tickets)}"),
    ]
    tickets = []
    for ticket in sorted(rounded.tickets, key=lambda item: (item.side != "sell", -item.value)):
        lots = ", ".join(f"{lot_id} {units:,.0f}" for lot_id, units in ticket.lots[:2])
        if len(ticket.lots) > 2:
            lots += ", ..."
        tickets.append((ticket.asset_id, ticket.side, f"{ticket.units:,.0f}", _money(ticket.value), lots))
    frontier = [(point.tax, point.tracking_error) for point in demo.frontier.points]
    reasons = ", ".join(f"{change.rule_id} ({change.effect})" for change in check.reasons) or "no rule changes status"
    checks = [
        ("Compliance engine, as one basket", f"{check.decision}: {reasons}"),
        ("Wash sales", f"{sum('wash sale' in note for note in result.repairs)} names barred from purchase"),
        ("Active share", f"{result.active_share_after:.1%} (floor 30%)"),
        ("Solver", f"{result.solver}, {result.rounds} rounds, {result.status}"),
    ]
    return plot_rebalance_report(
        ACCOUNT, demo.as_of, tiles, tickets, frontier, (rounded.tax, rounded.tracking_error_after), checks
    )


def optimisation_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    def item(filename: str, title: str, description: str, builder) -> GalleryItem:  # type: ignore[no-untyped-def]
        return GalleryItem(filename, title, description, builder, "optimisation")

    return (
        item(
            "tax-frontier.png",
            "The efficient frontier of tracking error against tax",
            "Every point a full compliant rebalance; the proposal, the tax-blind trade and today's portfolio placed "
            "on it.",
            frontier_chart,
        ),
        item(
            "rebalance-trades.png",
            "The proposed rebalance",
            "Weights before and after against the target, and the tax each sale realises or saves.",
            trades_chart,
        ),
        item(
            "lot-relief.png",
            "Which lots to sell",
            "Tax per dollar sold, lot by lot, and the same trades relieved first in, last in and highest cost first.",
            lot_selection_chart,
        ),
        item(
            "harvesting-map.png",
            "The harvesting map",
            "Every open lot by days held and gain, the one-year line, the wash-sale window, and the lots sold.",
            lot_map_chart,
        ),
        item(
            "solve-rounds.png",
            "Non-convex rules met in rounds",
            "Wash-sale repairs and the convex-concave rounds that hold active share above its floor.",
            solve_rounds_chart,
        ),
        item(
            "trading-costs.png",
            "Trading costs",
            "Commission, half-spread and square-root market impact for every trade, and the impact law.",
            trading_costs_chart,
        ),
        item(
            "order-rounding.png",
            "From weights to orders",
            "The optimiser's trades rounded to board lots and minimum tickets by a mixed-integer programme.",
            rounding_chart,
        ),
        item(
            "three-managers.png",
            "Three managers, one account",
            "Tax-blind, tax-aware and harvesting rebalances of the same account on the same day.",
            strategies_chart,
        ),
        item(
            "post-trade-compliance.png",
            "The mandate after the trades",
            "The Day 6 engine on the proposal as one basket: every limit's utilisation before and after.",
            post_trade_chart,
        ),
        item(
            "tax-alpha.png",
            "Tax alpha across simulated paths",
            "Annual after-tax return over the tax-blind manager, on liquidation and as held, for three managers.",
            tax_alpha_chart,
        ),
        item(
            "after-tax-wealth.png",
            "After-tax wealth",
            "Wealth against the tax-blind manager over three years, and the tax each manager paid.",
            wealth_chart,
        ),
        item(
            "harvest-calendar.png",
            "The harvest calendar",
            "Losses harvested and gains realised month by month, the carryforward, and the dispersion behind them.",
            harvest_calendar_chart,
        ),
        item(
            "tracking-error-budget.png",
            "Risk spent to save tax",
            "Ex-ante tracking error month by month for each manager against the tax-aware budget.",
            tracking_budget_chart,
        ),
        item(
            "rebalance-proposal.png",
            "The rebalance proposal",
            "One page for the investment committee: numbers, orders, frontier and checks.",
            report_chart,
        ),
    )
