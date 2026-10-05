"""The Day 7 revisit charts: the tax code as the IRS writes it, and harvesting on a century of real returns.

The carryover chart compares the revisited ledger with Day 7's, whose netting is
reproduced here in a few lines for exactly that comparison.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .accounting.tax import DEFAULT_RATES
from .domain.positions import long_term_from, one_year_after
from .optimisation.taxes import ORDINARY_OFFSET, TaxAccount, short_rate
from .services import century_tax_alpha as century
from .viz.optimisation_revisited import (
    CarryoverCase,
    DecadeBars,
    plot_carryover,
    plot_century_drag,
    plot_century_saved,
    plot_decade_account,
    plot_holding_period,
    plot_solver_agreement,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

HARVESTING = "tax-aware, harvesting"


# ---------------------------------------------------------------------------- the century
def _bars() -> list[DecadeBars]:
    return [
        DecadeBars(
            result.label,
            result.index_return(),
            {name: result.tax_drag(name) for name in result.outcome.strategies},
            result.tax_saved(HARVESTING),
            result.tracking_difference(HARVESTING),
            result.harvested(HARVESTING),
        )
        for result in century.decades()
    ]


def century_drag_chart() -> Figure:
    return plot_century_drag(_bars())


def century_saved_chart() -> Figure:
    return plot_century_saved(_bars())


def depression_chart() -> Figure:
    result = century.decades()[0]
    outcome = result.outcome
    records = outcome[HARVESTING].records
    nav = century.CONFIG.nav
    level = np.concatenate([[1.0], np.cumprod(1 + outcome.index_returns)])
    harvested = np.concatenate([[0.0], np.cumsum([record.harvested for record in records])]) / nav
    carried = np.concatenate([[0.0], [record.carryforward for record in records]]) / nav
    wealth = {name: [path.liquidation_value / nav] for name, path in outcome.strategies.items()}
    note = (
        f"Tax saved: {result.tax_saved(HARVESTING) * 1e4:.0f} bp a year - and the trades that harvested cost "
        f"{-result.tracking_difference(HARVESTING) * 1e4:.0f} bp a year before tax, in a decade whose tracking error "
        f"({result.tracking_error(HARVESTING):.1%}) ran past the 1.5% budget the 1926-30 risk model allowed."
    )
    return plot_decade_account(result.label, note, outcome.days, level, harvested, carried, wealth)


# ---------------------------------------------------------------------------- the tax code
def holding_period_chart() -> Figure:
    purchases = [
        date(2020, 1, 1) + timedelta(days=offset) for offset in range((date(2029, 12, 31) - date(2020, 1, 1)).days + 1)
    ]
    days = [(long_term_from(day) - day).days for day in purchases]
    bought = date(2024, 2, 5)
    return plot_holding_period(purchases, days, (bought, one_year_after(bought), long_term_from(bought)))


def day7_carryover(short: float, long: float) -> tuple[float, float, float]:
    """Day 7's year end, as it was: (short carried, long carried, what the deduction saved)."""
    if short < 0 < long:
        long, short = long + short, 0.0
    elif long < 0 < short:
        short, long = short + long, 0.0
    net = min(short, 0.0) + min(long, 0.0)
    used = min(-net, ORDINARY_OFFSET)
    remaining = -net - used
    short_part = min(-min(short, 0.0), remaining)
    return short_part, remaining - short_part, used * short_rate(DEFAULT_RATES)


def revisited_carryover(short: float, long: float) -> tuple[float, float, float]:
    account = TaxAccount()
    account.realise(date(2025, 6, 30), short, long_term=False)
    account.realise(date(2025, 6, 30), long, long_term=True)
    saved = -account.close_year(2025)
    return account.carried[0], account.carried[1], saved


def carryover_chart() -> Figure:
    cases = [
        CarryoverCase(
            "Publication 550: short-term losses first",
            "Realised: a \\$2,000 short-term loss and a \\$5,000 long-term loss.",
            day7_carryover(-2_000.0, -5_000.0),
            revisited_carryover(-2_000.0, -5_000.0),
        ),
        CarryoverCase(
            "A long-term loss larger than a short-term gain",
            "Realised: a \\$1,000 short-term gain and a \\$9,000 long-term loss.",
            day7_carryover(1_000.0, -9_000.0),
            revisited_carryover(1_000.0, -9_000.0),
        ),
    ]
    return plot_carryover(cases)


# ---------------------------------------------------------------------------- two solvers
def solver_chart() -> Figure:
    from dataclasses import replace

    from .optimisation import rebalance
    from .services.demo_optimisation import HOUSE, NO_HARVEST, build_demo_optimisation

    demo = build_demo_optimisation()
    cases = {
        "the house rebalance": HOUSE,
        "no harvesting": NO_HARVEST,
        "a 1% tracking budget": replace(HOUSE, te_limit=0.01),
    }
    output: dict[str, tuple[list[float], list[float]]] = {}
    chain = rebalance.SOLVER_CHAIN
    for name, settings in cases.items():
        first = demo.house.solve(settings)
        try:
            rebalance.SOLVER_CHAIN = (("SCS", {"eps_abs": 1e-10, "eps_rel": 1e-10, "max_iters": 200_000}),)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Solution may be inaccurate")
                second = demo.house.solve(settings)
        finally:
            rebalance.SOLVER_CHAIN = chain
        keys = sorted(first.after)
        output[name] = ([first.after[key] for key in keys], [second.after[key] for key in keys])
    return plot_solver_agreement(output)


def optimisation_revisited_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "century-tax-drag.png",
            "What tax cost an index account since 1931",
            "Four managers through each decade of real US returns: the index and each manager's tax drag.",
            century_drag_chart,
            "optimisation",
        ),
        GalleryItem(
            "century-tax-saved.png",
            "Harvesting saved tax in every decade",
            "Tax alpha set apart from tracking luck, and the losses harvested, decade by decade.",
            century_saved_chart,
            "optimisation",
        ),
        GalleryItem(
            "depression-harvest.png",
            "Harvesting through the Depression",
            "The 1930s month by month: the market, the losses harvested and carried, and each manager's result.",
            depression_chart,
            "optimisation",
        ),
        GalleryItem(
            "holding-period-calendar.png",
            "Long-term means after the anniversary",
            "IRS Publication 550's leap-year example, and how often a 365-day count was a day early.",
            holding_period_chart,
            "tax",
        ),
        GalleryItem(
            "carryover-schedule-d.png",
            "The capital loss carryover, as Schedule D computes it",
            "Day 7's year-end netting against the revisited one, on two cases.",
            carryover_chart,
            "tax",
        ),
        GalleryItem(
            "solver-agreement.png",
            "Two unrelated algorithms, one rebalance",
            "The demo rebalances solved by Clarabel and by SCS, weight by weight.",
            solver_chart,
            "validation",
        ),
    )
