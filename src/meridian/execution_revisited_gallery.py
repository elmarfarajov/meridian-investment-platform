"""The Day 8 revisit charts: execution against the paper, and liquidation on a century of real prices.

The POV chart compares the revisited algorithm with Day 8's, whose rate is
reproduced here in one line for exactly that comparison: it traded the target
share of the *rest* of the market's volume.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .execution.algorithms import AlgoParams, execute
from .execution.allocation import AccountOrder, aggregate, allocate
from .execution.market import MarketDay, StockProfile
from .execution.orders import Fill, Order, Side
from .services import century_execution as century
from .viz.execution_revisited import (
    DecadeCoverage,
    ReviewPanel,
    plot_allocation,
    plot_century_bound,
    plot_cost_tails,
    plot_paper_example,
    plot_pov,
    plot_review,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

PAPER = "the paper's"
PROFILE = StockProfile("XYZ", 100.0, 0.02, 2_000_000.0, 4.0)


# ---------------------------------------------------------------------------- the paper
def _direct(problem, risk_aversion: float) -> np.ndarray:  # type: ignore[no-untyped-def]
    """The trajectory a conic solver finds, knowing nothing of the closed form (as the tests do)."""
    import cvxpy as cp

    inner = cp.Variable(problem.intervals - 1)
    held = cp.hstack([1.0, inner, 0.0])
    impact = problem.eta_tilde / problem.tau
    risk = risk_aversion * problem.sigma**2 * problem.tau
    scale = impact / problem.intervals
    objective = (impact * cp.sum_squares(held[:-1] - held[1:]) + risk * cp.sum_squares(inner)) / scale
    cp.Problem(cp.Minimize(objective)).solve(solver="CLARABEL")
    return np.asarray(problem.shares * np.concatenate([[1.0], inner.value, [0.0]]))


def paper_chart() -> Figure:
    problem = century.problem(0.95 / 50)
    trajectories = {name: problem.holdings(level) for name, level in century.SCHEDULES.items()}
    direct = {name: _direct(problem, level) for name, level in century.SCHEDULES.items()}
    levels = np.concatenate([[0.0], np.logspace(-8, -4.5, 60)])
    frontier = [(problem.expected_cost(level), math.sqrt(problem.variance(level))) for level in levels]
    points = {
        name: (problem.expected_cost(level), math.sqrt(problem.variance(level)))
        for name, level in century.SCHEDULES.items()
    }
    return plot_paper_example(trajectories, direct, frontier, points, problem.kappa(1e-6))


# ---------------------------------------------------------------------------- the century
def century_bound_chart() -> Figure:
    series = century.century("ewma")
    market = series[0]
    raw = century.by_decade(market, PAPER)
    corrected = century.by_decade(market, PAPER, corrected=True)
    returns = century.french_daily().market
    years = np.array([day.year for day in century.french_daily().days])
    decades = []
    for decade in raw:
        selected = returns[(years // 10) * 10 == decade]
        rho = float(np.corrcoef(selected[:-1], selected[1:])[0, 1])
        decades.append(DecadeCoverage(decade, raw[decade].rate, corrected[decade].rate, rho, raw[decade].weeks))
    raw_all, fixed_all = century.pooled(series, PAPER), century.pooled_corrected(series, PAPER)
    pooled = {
        "sellers": (century.coverage(raw_all).rate, century.coverage(fixed_all).rate),
        "buyers": (century.coverage(raw_all, "buy").rate, century.coverage(fixed_all, "buy").rate),
    }
    return plot_century_bound(decades, pooled)


def control_weeks() -> century.Weeks:
    """A random walk with the market's average daily volatility, forecast the same way: the model made true."""
    rng = np.random.default_rng(2026)
    returns = float(np.std(century.french_daily().market)) * rng.standard_normal(26_000)
    return century.weeks("random walk", returns, np.full(len(returns), 2000))


def tails_chart() -> Figure:
    series = century.century("ewma")
    z = century.pooled(series, PAPER)
    control = control_weeks().z[PAPER]
    coverage = {
        "century, sellers": century.coverage(z).rate,
        "century, buyers": century.coverage(z, "buy").rate,
        "random walk, forecast": century.coverage(control).rate,
    }
    return plot_cost_tails(z, control, coverage)


# ---------------------------------------------------------------------------- POV and allocation
def pov_participation(day8: bool, target: float = 0.10) -> np.ndarray:
    """Minute-by-minute share of all the volume a too-large POV order took."""
    market = MarketDay.simulate(PROFILE, seed=5)
    order = Order("P-1", "XYZ", Side.BUY, 2_000_000.0, date(2026, 9, 21), decision_price=100.0)
    if day8:  # Day 8's rate: the target share of the rest of the market's volume
        shares = np.floor(target * market.volumes)
        return np.asarray(shares / (shares + market.volumes))
    result = execute(order, market, AlgoParams("pov", participation=target))
    traded = np.zeros(market.minutes)
    for record in result.records:
        traded[record.minute] += record.quantity
    return np.asarray(traded / (traded + market.volumes))


def pov_chart() -> Figure:
    return plot_pov(np.arange(390), pov_participation(True), pov_participation(False), 0.10)


ALLOCATION_EXAMPLES = 2_000


def pro_rata_deviations(examples: int = ALLOCATION_EXAMPLES) -> np.ndarray:
    rng = np.random.default_rng(34)
    deviations: list[float] = []
    for number in range(examples):
        asked = [float(q) for q in rng.integers(1, 5_000, size=int(rng.integers(2, 10)))]
        filled = math.floor(sum(asked) * rng.uniform(0.05, 0.95))
        block = _block(asked, float(filled), number)
        booked = [item for item in allocate(block) if item.quantity > 0]
        base = sum(item.requested for item in booked)
        deviations += [item.quantity - filled * item.requested / base for item in booked]
    return np.array(deviations)


def _block(asked: list[float], filled: float, number: int = 0):  # type: ignore[no-untyped-def]
    orders = [AccountOrder(f"P{index:02d}", "XYZ", Side.BUY, quantity, 100.0) for index, quantity in enumerate(asked)]
    block = aggregate(orders, date(2026, 9, 21), prefix=f"B{number}")[0]
    if filled > 0:
        block.order.release(0, "vwap")
        block.order.fill(Fill("F1", block.order.order_id, 1, filled, 101.25))
    return block


FRACTIONAL_CASE = [1.0, 592.5, 211.0, 592.5, 592.0, 1.5]


def allocation_chart() -> Figure:
    allocations = allocate(_block(FRACTIONAL_CASE, 1990.0))
    case = [(item.portfolio_id, item.requested, item.quantity) for item in allocations]
    return plot_allocation(pro_rata_deviations(), case, ALLOCATION_EXAMPLES)


# ---------------------------------------------------------------------------- the review
#: The demo day's figures as Day 8 published them (docs/notes/execution-and-transaction-costs.md, v1.0.0)
DAY8 = {"shortfall": -7.9, "opportunity": -3.1, "pov": 21.9, "close": 21.3, "pov_rate": 0.0909}


def review_chart() -> Figure:
    from .execution_gallery import _controllable
    from .services.demo_execution import build_demo_execution

    demo = build_demo_execution()
    totals = demo.totals()
    paper = totals["paper value"]
    comparison = {
        name: sum(_controllable(cost) for cost in costs) / sum(cost.paper_value for cost in costs) * 1e4
        for name, costs in demo.comparison.items()
    }
    rate = float(np.nanmean(pov_participation(False)))
    panels = [
        ReviewPanel(
            "A 10% POV order's participation",
            ("10% POV",),
            (DAY8["pov_rate"] * 100,),
            (rate * 100,),
            ".1f",
            "Percent of all the minute's volume. Day 8 traded a tenth of the others' volume: 9.1% of the total.",
        ),
        ReviewPanel(
            "The demo day, bp of value",
            ("shortfall", "not traded"),
            (DAY8["shortfall"], DAY8["opportunity"]),
            (totals["shortfall"] / paper * 1e4, totals["opportunity"] / paper * 1e4),
            "+.1f",
            "With the cap at a quarter of all the volume, more of the large blocks is done, and less is left at the "
            "close.",
        ),
        ReviewPanel(
            "Controllable cost by algorithm, bp",
            ("POV", "close"),
            (DAY8["pov"], DAY8["close"]),
            (comparison["pov"], comparison["close"]),
            ".1f",
            "Both trade at the rate they were set, of all the volume: a little more impact, and more of the order done.",
        ),
    ]
    return plot_review(panels)


def execution_revisited_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "almgren-chriss-paper.png",
            "Almgren and Chriss's own example, reproduced",
            "The paper's Table 1: trajectories, the frontier, and a conic solver's minimum beside the closed form.",
            paper_chart,
            "validation",
        ),
        GalleryItem(
            "century-liquidation-bound.png",
            "Almgren-Chriss's 95% bound on a century of real prices",
            "How often a liquidation's cost broke the bound, decade by decade, and the autocorrelation behind it.",
            century_bound_chart,
            "execution",
        ),
        GalleryItem(
            "liquidation-cost-tails.png",
            "The cost of a liquidation is not normal",
            "The standardised cost of every week since 1927 against the normal and a random-walk control.",
            tails_chart,
            "execution",
        ),
        GalleryItem(
            "pov-participation.png",
            "A POV order at its own rate",
            "Participation minute by minute, as Day 8 traded it and as it is traded now.",
            pov_chart,
            "execution",
        ),
        GalleryItem(
            "allocation-properties.png",
            "Allocation, property-tested",
            "Random blocks against the pro-rata rule, and the block Day 8 could not allocate.",
            allocation_chart,
            "validation",
        ),
        GalleryItem(
            "execution-review.png",
            "A second reading of Day 8",
            "The figures the faults changed, before and after.",
            review_chart,
            "execution",
        ),
    )
