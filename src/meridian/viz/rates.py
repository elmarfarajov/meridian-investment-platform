"""Charts for curves, compounding and bond risk.

Each of these exists to make one argument visible:

* the zero curve is not the par curve, and the forward curve is neither;
* the interpolation method is a modelling choice with visible consequences;
* duration is a straight line drawn through a curved function;
* compounding conventions are not cosmetic.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
from matplotlib.figure import Figure

from ..analytics.bonds import FixedRateBond, price_yield_curve
from ..analytics.curves import YieldCurve, tenor_label
from ..core.compounding import Compounding, discount_factor
from ..core.interpolation import InterpolationMethod
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block


def plot_yield_curve(curve: YieldCurve, *, frequency: int = 2) -> Figure:
    """Zero, par and forward curves together, with the discount factors beside them."""
    figure = new_figure(12.0, 5.4)
    grid = figure.add_gridspec(
        1, 2, width_ratios=[1.35, 1.0], wspace=0.22, top=0.80, bottom=0.13, left=0.06, right=0.975
    )

    axis = figure.add_subplot(grid[0, 0])
    zero_times, zero_rates = curve.sample(140)
    par_times, par_rates = curve.par_curve(frequency, 60)
    fwd_times, fwd_rates = curve.forward_curve(0.25, 80)

    axis.plot([t for t in zero_times], [r * 100 for r in zero_rates], color=PALETTE["navy"], label="Zero (spot)")
    axis.plot([t for t in par_times], [r * 100 for r in par_rates], color=PALETTE["teal"], label="Par yield")
    axis.plot(
        [t for t in fwd_times],
        [r * 100 for r in fwd_rates],
        color=PALETTE["violet"],
        linestyle="--",
        label="3M forward",
    )
    pillars = curve.points()
    axis.scatter(
        [point.years for point in pillars],
        [point.rate * 100 for point in pillars],
        color=PALETTE["navy"],
        zorder=5,
        s=26,
        label="Quoted pillars",
    )
    style_axes(axis, title="The curve, three ways", xlabel="Years", ylabel="Rate (%)")
    axis.set_xscale("log")
    axis.set_xticks([0.25, 0.5, 1, 2, 5, 10, 20, 30])
    axis.set_xticklabels(["3M", "6M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y"])
    axis.legend(loc="lower right", ncol=1)

    spread = (curve.zero_rate(30) - curve.par_rate(30, frequency)) * 10_000
    annotate(
        axis,
        f"At 30Y the zero rate sits {spread:+.0f}bp above the par rate",
        xy=(0.02, 0.94),
        xycoords="axes fraction",
        highlight=True,
        fontsize=8.5,
    )

    factors = figure.add_subplot(grid[0, 1])
    times = np.linspace(0.05, curve.years[-1], 200)
    factors.plot(times, [curve.discount_factor(float(t)) for t in times], color=PALETTE["slate"])
    factors.fill_between(times, [curve.discount_factor(float(t)) for t in times], color=PALETTE["slate"], alpha=0.12)
    for point in pillars:
        factors.scatter([point.years], [curve.discount_factor(point.years)], color=PALETTE["navy"], s=18, zorder=5)
    style_axes(factors, title="Discount factors", xlabel="Years", ylabel="Present value of 1")
    factors.set_ylim(0, 1.02)
    half_life = next((float(t) for t in times if curve.discount_factor(float(t)) <= 0.5), None)
    if half_life:
        factors.axhline(0.5, color=PALETTE["grid"], linewidth=0.8)
        annotate(factors, f"a unit halves in {half_life:.1f} years", xy=(half_life + 0.4, 0.53), fontsize=8)

    title_block(
        figure,
        f"Yield curve - {curve.name}, {curve.valuation_date.isoformat()}",
        "Bootstrapped from par yields: each pillar is solved so a par bond of that maturity prices to exactly 100.",
    )
    caption(
        figure,
        f"Interpolation: {curve.interpolation.value} on discount factors. "
        f"Compounding: {curve.compounding.value}. Day count: {curve.day_count.value}.",
    )
    return figure


def plot_interpolation_comparison(curve: YieldCurve) -> Figure:
    """The same pillars, three interpolation methods, and what they do to forwards."""
    methods = (
        (InterpolationMethod.LINEAR, PALETTE["loss"], "Linear on the rate"),
        (InterpolationMethod.LOG_LINEAR, PALETTE["navy"], "Log-linear on DF (flat forwards)"),
        (InterpolationMethod.MONOTONE_CUBIC, PALETTE["teal"], "Monotone cubic"),
    )
    figure = new_figure(12.0, 5.2)
    grid = figure.add_gridspec(1, 2, wspace=0.2, top=0.80, bottom=0.14, left=0.06, right=0.975)
    rates_axis = figure.add_subplot(grid[0, 0])
    forward_axis = figure.add_subplot(grid[0, 1])

    times = np.linspace(0.3, curve.years[-1] - 0.3, 400)
    for method, colour, label in methods:
        variant = YieldCurve(
            curve.valuation_date,
            curve.years,
            curve.rates,
            compounding=curve.compounding,
            interpolation=method,
            name=str(method.value),
        )
        rates_axis.plot(times, [variant.zero_rate(float(t)) * 100 for t in times], color=colour, label=label)
        forward_axis.plot(
            times,
            [variant.instantaneous_forward(float(t)) * 100 for t in times],
            color=colour,
            label=label,
        )

    for axis, title, ylabel in (
        (rates_axis, "Zero rates between the pillars", "Zero rate (%)"),
        (forward_axis, "The instantaneous forward each method implies", "Forward rate (%)"),
    ):
        style_axes(axis, title=title, xlabel="Years", ylabel=ylabel)
    rates_axis.scatter(
        curve.years, [rate * 100 for rate in curve.rates], color=PALETTE["ink"], s=26, zorder=5, label="Pillars"
    )
    rates_axis.legend(loc="lower right", fontsize=7.5)

    annotate(
        forward_axis,
        "the forward curve is where a bad interpolation shows",
        xy=(0.03, 0.94),
        xycoords="axes fraction",
        highlight=True,
        fontsize=8.5,
    )

    title_block(
        figure,
        "Interpolation is a modelling choice",
        "The three methods agree at every quoted pillar and disagree everywhere else - most visibly in the forwards.",
    )
    caption(
        figure,
        "Linear interpolation on rates produces a sawtooth forward curve. Log-linear on discount factors is "
        "equivalent to assuming a constant forward between pillars. Monotone cubic is smooth without overshooting.",
    )
    return figure


def plot_price_yield(bond: FixedRateBond, settlement: date, base_yield: float = 0.045) -> Figure:
    """The convexity of the price-yield curve, and what a linear risk measure misses."""
    figure = new_figure(12.0, 5.4)
    grid = figure.add_gridspec(
        1, 2, width_ratios=[1.25, 1.0], wspace=0.22, top=0.80, bottom=0.13, left=0.07, right=0.975
    )

    axis = figure.add_subplot(grid[0, 0])
    yields, prices = price_yield_curve(bond, settlement, low=max(base_yield - 0.045, -0.005), high=base_yield + 0.045)
    axis.plot([y * 100 for y in yields], prices, color=PALETTE["navy"], label="Actual price")

    base_price = bond.clean_price_from_yield(base_yield, settlement)
    duration = bond.modified_duration(base_yield, settlement)
    convexity = bond.convexity(base_yield, settlement)
    dirty = bond.dirty_price_from_yield(base_yield, settlement)

    shifts = np.array([y - base_yield for y in yields])
    linear = base_price - duration * shifts * dirty
    quadratic = linear + 0.5 * convexity * shifts**2 * dirty
    axis.plot([y * 100 for y in yields], linear, color=PALETTE["loss"], linestyle="--", label="Duration only")
    axis.plot([y * 100 for y in yields], quadratic, color=PALETTE["teal"], linestyle=":", label="Duration + convexity")
    axis.scatter([base_yield * 100], [base_price], color=PALETTE["ink"], zorder=5, s=32)
    style_axes(axis, title=f"{bond.name}: price against yield", xlabel="Yield (%)", ylabel="Clean price")
    axis.legend(loc="upper right")
    annotate(
        axis,
        f"modified duration {duration:.2f}, convexity {convexity:.1f}",
        xy=(0.03, 0.08),
        xycoords="axes fraction",
        highlight=True,
    )

    error_axis = figure.add_subplot(grid[0, 1])
    shift_points = np.arange(-300, 301, 25)
    duration_error = []
    convexity_error = []
    for shift in shift_points:
        actual, linear_estimate, with_convexity = bond.price_change_estimate(base_yield, settlement, float(shift))
        duration_error.append(linear_estimate - actual)
        convexity_error.append(with_convexity - actual)
    error_axis.bar(shift_points, duration_error, width=18, color=PALETTE["loss"], label="Duration only")
    error_axis.plot(
        shift_points, convexity_error, color=PALETTE["teal"], marker="o", markersize=2.5, label="Duration + convexity"
    )
    error_axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    style_axes(error_axis, title="Estimation error", xlabel="Yield shift (bp)", ylabel="Error in price")
    error_axis.legend(loc="lower center")

    worst = max(abs(value) for value in duration_error)
    annotate(
        error_axis,
        f"up to {worst:.2f} per 100 of face at +/-300bp",
        xy=(0.03, 0.92),
        xycoords="axes fraction",
        fontsize=8,
    )

    title_block(
        figure,
        "Duration is a straight line through a curved function",
        f"Priced on {settlement.isoformat()}. The linear estimate always overstates the loss and understates the gain.",
    )
    caption(
        figure,
        "Actual price from discounting every remaining cash flow at the yield; estimates from the first and second "
        "derivatives at the base yield.",
    )
    return figure


def plot_key_rate_durations(bond: FixedRateBond, curve: YieldCurve, settlement: date | None = None) -> Figure:
    """Where on the curve a bond's risk actually sits."""
    settlement = settlement or curve.valuation_date
    durations = bond.key_rate_durations(curve, settlement)
    labels = [label for label, _ in durations]
    values = [value for _, value in durations]

    figure = new_figure(10.5, 5.0)
    axis = figure.add_subplot()
    figure.subplots_adjust(top=0.79, bottom=0.14, left=0.08, right=0.97)
    colours = [PALETTE["navy"] if value >= 0 else PALETTE["loss"] for value in values]
    axis.bar(labels, values, color=colours, width=0.62)
    style_axes(axis, title="Key rate durations", xlabel="Curve pillar", ylabel="Price sensitivity (bp per bp)")

    total = sum(values)
    peak = labels[values.index(max(values))]
    annotate(
        axis,
        f"{total:.2f} in total, concentrated at {peak}",
        xy=(0.03, 0.92),
        xycoords="axes fraction",
        highlight=True,
    )

    title_block(
        figure,
        f"{bond.name} - risk by maturity bucket",
        "A parallel shift is a convenient fiction; curves twist. Each bar bumps one pillar and leaves the rest alone.",
    )
    caption(figure, "Sum of the key rate durations approximates the modified duration of the bond.")
    return figure


def plot_compounding(rate: float = 0.05, horizon: float = 30.0) -> Figure:
    """What the compounding convention does to the value of a unit over time."""
    figure = new_figure(11.0, 5.0)
    grid = figure.add_gridspec(1, 2, wspace=0.22, top=0.80, bottom=0.14, left=0.07, right=0.975)
    axis = figure.add_subplot(grid[0, 0])
    bars = figure.add_subplot(grid[0, 1])

    times = np.linspace(0.1, horizon, 200)
    conventions = (
        (Compounding.SIMPLE, PALETTE["loss"]),
        (Compounding.ANNUAL, PALETTE["navy"]),
        (Compounding.QUARTERLY, PALETTE["sky"]),
        (Compounding.CONTINUOUS, PALETTE["teal"]),
    )
    for convention, colour in conventions:
        axis.plot(
            times,
            [discount_factor(rate, float(t), convention) for t in times],
            color=colour,
            label=convention.value.replace("_", " "),
        )
    style_axes(axis, title=f"Discount factor at {rate * 100:.0f}%", xlabel="Years", ylabel="Present value of 1")
    axis.legend(loc="upper right")

    labels = [convention.value.replace("_", " ") for convention, _ in conventions]
    gaps = [
        (discount_factor(rate, horizon, Compounding.SIMPLE) - discount_factor(rate, horizon, convention)) * 100
        for convention, _ in conventions
    ]
    bars.bar(labels, gaps, color=[colour for _, colour in conventions], width=0.6)
    style_axes(
        bars,
        title=f"Difference from simple discounting at {horizon:g} years",
        ylabel="Cents per unit of face",
    )
    bars.tick_params(axis="x", rotation=12)

    title_block(
        figure,
        "Compounding conventions are not cosmetic",
        f"The same quoted {rate * 100:.0f}% produces materially different money once the horizon is long.",
    )
    caption(figure, "Simple, annual, quarterly and continuous compounding of one identical nominal rate.")
    return figure


def plot_curve_scenarios(curve: YieldCurve, shifts: Sequence[float] = (-100, -50, 50, 100)) -> Figure:
    """Parallel shifts and a steepening, which is how a rates book is stress tested."""
    figure = new_figure(11.0, 5.0)
    grid = figure.add_gridspec(1, 2, wspace=0.22, top=0.80, bottom=0.14, left=0.07, right=0.975)
    parallel = figure.add_subplot(grid[0, 0])
    twist = figure.add_subplot(grid[0, 1])

    times = np.linspace(0.25, curve.years[-1], 150)
    base = [curve.zero_rate(float(t)) * 100 for t in times]
    parallel.plot(times, base, color=PALETTE["ink"], linewidth=2.0, label="Base")
    palette = [PALETTE["loss"], PALETTE["sky"], PALETTE["teal"], PALETTE["navy"]]
    for colour, shift in zip(palette, shifts, strict=False):
        moved = curve.shifted(shift)
        parallel.plot(
            times,
            [moved.zero_rate(float(t)) * 100 for t in times],
            color=colour,
            linewidth=1.2,
            label=f"{shift:+.0f}bp",
        )
    style_axes(parallel, title="Parallel shifts", xlabel="Years", ylabel="Zero rate (%)")
    parallel.legend(loc="lower right", ncol=2, fontsize=7.5)

    twist.plot(times, base, color=PALETTE["ink"], linewidth=2.0, label="Base")
    for index, colour in ((0, PALETTE["violet"]), (len(curve.years) - 1, PALETTE["teal"])):
        bumped = curve.key_rate_shifted(index, 50)
        twist.plot(
            times,
            [bumped.zero_rate(float(t)) * 100 for t in times],
            color=colour,
            label=f"{tenor_label(curve.years[index])} +50bp",
        )
    style_axes(twist, title="Key rate bumps", xlabel="Years", ylabel="Zero rate (%)")
    twist.legend(loc="lower right", fontsize=7.5)

    title_block(
        figure,
        "Curve scenarios",
        "The parallel shift is the one every textbook uses; the twist is the one that actually happens.",
    )
    caption(figure, "Bumps are applied to the pillar rates and the curve is rebuilt, not shifted after the fact.")
    return figure
