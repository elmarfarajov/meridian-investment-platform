"""Every chart the platform can draw, in one reproducible place.

The README, the documentation and the pull requests all show charts. Generating
them from one function means they are never stale, never hand-edited, and never
disagree with the code that produced them: ``meridian charts gallery`` rebuilds
all of them from the current source in one command.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from matplotlib.figure import Figure

from .analytics.bonds import FixedRateBond
from .analytics.curves import YieldCurve, bootstrap_par_curve
from .core.enums import Frequency
from .core.money import Money
from .core.schedules import StubConvention, generate_schedule
from .viz import (
    plot_accrual_path,
    plot_allocation,
    plot_cash_flows,
    plot_compounding,
    plot_curve_scenarios,
    plot_daycount_comparison,
    plot_divergence_matrix,
    plot_flow_composition,
    plot_interpolation_comparison,
    plot_key_rate_durations,
    plot_price_yield,
    plot_rounding_drift,
    plot_schedule,
    plot_schema,
    plot_settlement_ladder,
    plot_trading_calendar,
    plot_yield_curve,
    save_figure,
)

#: A fixed valuation date, so the gallery is byte-comparable between runs.
VALUATION_DATE = date(2026, 9, 18)
SETTLEMENT_DATE = date(2026, 9, 21)
CHART_YEAR = 2026

REFERENCE_TENORS = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0)
REFERENCE_PAR_RATES = (0.0425, 0.0432, 0.0418, 0.0395, 0.0388, 0.0390, 0.0402, 0.0415, 0.0448, 0.0455)


def reference_curve() -> YieldCurve:
    """The curve used across the documentation: a realistic dip-and-rise shape."""
    return bootstrap_par_curve(
        VALUATION_DATE,
        list(REFERENCE_TENORS),
        list(REFERENCE_PAR_RATES),
        name="USD par curve",
    )


def reference_bond() -> FixedRateBond:
    return FixedRateBond.create(
        issue_date=date(2024, 5, 15),
        maturity=date(2034, 5, 15),
        coupon_rate=0.04,
        frequency=Frequency.SEMI_ANNUAL,
        name="UST 4% May 2034",
    )


@dataclass(frozen=True, slots=True)
class GalleryItem:
    """One chart: the file it writes, what it shows, and how to build it."""

    filename: str
    title: str
    description: str
    builder: Callable[[], Figure]
    group: str = "general"


def gallery_items() -> tuple[GalleryItem, ...]:
    curve = reference_curve()
    bond = reference_bond()

    return (
        GalleryItem(
            "trading-calendar-2026.png",
            "Exchange trading calendars",
            "A year of NYSE, London and TARGET, and the days on which they disagree.",
            lambda: plot_trading_calendar(CHART_YEAR, ("XNYS", "XLON", "TARGET")),
            "calendars",
        ),
        GalleryItem(
            "calendar-divergence.png",
            "Where the markets disagree",
            "Pairwise count of weekdays when one market trades and another is shut.",
            lambda: plot_divergence_matrix(CHART_YEAR),
            "calendars",
        ),
        GalleryItem(
            "settlement-ladder.png",
            "Settlement ladder",
            "Where T+0 to T+3 land in each market, and in the joint settlement calendar.",
            lambda: plot_settlement_ladder(date(CHART_YEAR, 12, 23)),
            "calendars",
        ),
        GalleryItem(
            "yield-curve.png",
            "Yield curve, three ways",
            "Zero, par and forward curves from one set of quoted par yields.",
            lambda: plot_yield_curve(curve),
            "rates",
        ),
        GalleryItem(
            "curve-interpolation.png",
            "Interpolation is a modelling choice",
            "Three methods that agree at the pillars and disagree everywhere else.",
            lambda: plot_interpolation_comparison(curve),
            "rates",
        ),
        GalleryItem(
            "curve-scenarios.png",
            "Curve scenarios",
            "Parallel shifts and key-rate twists applied to the pillars.",
            lambda: plot_curve_scenarios(curve),
            "rates",
        ),
        GalleryItem(
            "price-yield.png",
            "Duration is a straight line",
            "The price-yield curve against its first- and second-order approximations.",
            lambda: plot_price_yield(bond, SETTLEMENT_DATE),
            "rates",
        ),
        GalleryItem(
            "key-rate-durations.png",
            "Key rate durations",
            "Where on the curve a bond's interest rate risk actually sits.",
            lambda: plot_key_rate_durations(bond, curve, SETTLEMENT_DATE),
            "rates",
        ),
        GalleryItem(
            "compounding.png",
            "Compounding conventions",
            "The same quoted rate, four conventions, materially different money.",
            lambda: plot_compounding(),
            "rates",
        ),
        GalleryItem(
            "bond-schedule.png",
            "Payment schedule",
            "Accrual periods, the stub, and the payments moved by the business-day rule.",
            lambda: plot_schedule(
                generate_schedule(
                    date(2025, 2, 10),
                    date(2028, 5, 15),
                    Frequency.SEMI_ANNUAL,
                    stub=StubConvention.SHORT_FRONT,
                )
            ),
            "cashflows",
        ),
        GalleryItem(
            "bond-cashflows.png",
            "Cash flows and their present value",
            "What the bond pays, and what each payment is worth on the curve today.",
            lambda: plot_cash_flows(bond, SETTLEMENT_DATE, curve),
            "cashflows",
        ),
        GalleryItem(
            "accrued-interest.png",
            "Accrued interest",
            "The sawtooth the buyer pays the seller, resetting at every coupon.",
            lambda: plot_accrual_path(bond, date(2026, 1, 1), date(2029, 1, 1)),
            "cashflows",
        ),
        GalleryItem(
            "value-composition.png",
            "Where a bond's value comes from",
            "Coupons against the return of principal, discounted on the curve.",
            lambda: plot_flow_composition(bond, SETTLEMENT_DATE, curve),
            "cashflows",
        ),
        GalleryItem(
            "allocation.png",
            "Allocating an amount",
            "A conserving split against naive rounding, and the cash the naive one loses.",
            lambda: plot_allocation(Money(Decimal("1000.00"), "USD")),
            "money",
        ),
        GalleryItem(
            "rounding-drift.png",
            "Rounding error accumulates",
            "The same split repeated: one method stays on zero, the other walks away.",
            lambda: plot_rounding_drift(Money(Decimal("2500.00"), "USD")),
            "money",
        ),
        GalleryItem(
            "day-counts.png",
            "Day-count conventions",
            "Year fractions and accrued interest for one period under every convention.",
            lambda: plot_daycount_comparison(date(2026, 1, 15), date(2026, 7, 15)),
            "money",
        ),
        GalleryItem(
            "data-model.png",
            "The data model",
            "Every table, column and foreign key, drawn from the live SQLAlchemy metadata.",
            lambda: plot_schema(),
            "platform",
        ),
    )


def build_gallery(
    out_dir: str | Path = "docs/images",
    *,
    only: str | None = None,
    dpi: int = 130,
) -> list[Path]:
    """Render every chart into a directory and return the paths written."""
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in gallery_items():
        if only and only not in {item.group, item.filename}:
            continue
        written.append(save_figure(item.builder(), destination / item.filename, dpi=dpi))
    return written


def gallery_markdown(prefix: str = "docs/images") -> str:
    """The markdown block the README uses, so the gallery and the docs cannot drift."""
    lines: list[str] = []
    for group in ("calendars", "rates", "cashflows", "money", "platform"):
        items = [item for item in gallery_items() if item.group == group]
        if not items:
            continue
        lines.append(f"### {group.title()}\n")
        for item in items:
            lines.append(f"**{item.title}** - {item.description}\n")
            lines.append(f"![{item.title}]({prefix}/{item.filename})\n")
    return "\n".join(lines)
