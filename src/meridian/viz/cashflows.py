"""Charts for schedules and cash flows.

A payment schedule is a list of dates until you draw it, at which point the stub
period, the business-day adjustment and the shape of the redemption become
obvious. These charts are the ones to look at when a bond's accrued interest or
its first coupon does not match a counterparty's.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from ..analytics.bonds import FixedRateBond
from ..analytics.curves import YieldCurve
from ..core.schedules import Schedule
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block


def plot_schedule(schedule: Schedule, *, title: str | None = None) -> Figure:
    """Accrual periods as bars on a timeline, with the payment dates marked.

    Where a payment sits to the right of its accrual period, the business-day
    convention moved it - which is exactly the discrepancy that shows up as a
    one-day interest difference in a reconciliation.
    """
    figure = new_figure(12.0, max(3.6, 0.32 * len(schedule) + 2.6))
    axis = figure.add_subplot()
    figure.subplots_adjust(
        top=1 - 1.15 / figure.get_figheight(), bottom=0.62 / figure.get_figheight(), left=0.085, right=0.975
    )

    for index, period in enumerate(schedule):
        colour = PALETTE["violet"] if period.is_stub else PALETTE["navy"]
        axis.barh(
            index,
            (period.end - period.start).days,
            left=period.start.toordinal(),
            height=0.62,
            color=colour,
            alpha=0.85,
        )
        axis.scatter([period.payment_date.toordinal()], [index], color=PALETTE["teal"], s=22, zorder=5)
        if period.payment_date != period.end:
            axis.plot(
                [period.end.toordinal(), period.payment_date.toordinal()],
                [index, index],
                color=PALETTE["accent"],
                linewidth=2.4,
                zorder=4,
            )

    ticks = list(range(len(schedule)))
    axis.set_yticks(ticks, labels=[f"{index + 1}" for index in ticks])
    axis.invert_yaxis()
    first, last = schedule.start, schedule.end
    span = (last - first).days
    tick_days = [first + timedelta(days=int(offset)) for offset in np.linspace(0, span, 8)]
    axis.set_xticks([day.toordinal() for day in tick_days], labels=[day.strftime("%b %y") for day in tick_days])
    style_axes(axis, xlabel="", ylabel="Period", grid="x")

    moved = sum(1 for period in schedule if period.payment_date != period.end)
    legend = [
        Patch(facecolor=PALETTE["navy"], label="Regular accrual period"),
        Patch(facecolor=PALETTE["violet"], label="Stub period"),
        Patch(facecolor=PALETTE["teal"], label="Payment date"),
        Patch(facecolor=PALETTE["accent"], label="Moved by the business-day convention"),
    ]
    axis.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, frameon=False)

    title_block(
        figure,
        title or f"Payment schedule - {schedule.describe()}",
        f"{len(schedule)} periods, {moved} payment date(s) moved onto a business day"
        + (", one stub period" if schedule.has_stub else ", no stub"),
    )
    caption(
        figure,
        f"Rolled backwards from {schedule.end.isoformat()} on the {schedule.roll.value.replace('_', ' ')} rule, "
        f"{schedule.stub.value.replace('_', ' ')} stub, {schedule.convention.value.replace('_', ' ')} adjustment.",
    )
    return figure


def plot_cash_flows(bond: FixedRateBond, settlement: date, curve: YieldCurve | None = None) -> Figure:
    """The cash flow ladder, and what each flow is worth today."""
    flows = bond.cash_flows(settlement)
    if not flows:
        raise ValueError("The bond has no remaining cash flows")

    figure = new_figure(12.0, 5.6)
    grid = figure.add_gridspec(
        1, 2, width_ratios=[1.35, 1.0], wspace=0.2, top=0.80, bottom=0.14, left=0.07, right=0.975
    )
    axis = figure.add_subplot(grid[0, 0])
    positions = np.arange(len(flows))
    coupons = [flow.amount if flow.kind == "coupon" else 0.0 for flow in flows]
    finals = [flow.amount if flow.kind != "coupon" else 0.0 for flow in flows]
    axis.bar(positions, coupons, color=PALETTE["navy"], width=0.62, label="Coupon")
    axis.bar(positions, finals, color=PALETTE["teal"], width=0.62, label="Coupon + redemption")
    labels = [flow.payment_date.strftime("%b %y") for flow in flows]
    step = max(1, len(flows) // 10)
    axis.set_xticks(positions[::step], labels=labels[::step], rotation=35, ha="right")
    style_axes(axis, title="Cash flows still to come", ylabel=f"Amount per {bond.face_value:g} of face")
    axis.legend(loc="upper left")

    present = figure.add_subplot(grid[0, 1])
    if curve is not None:
        values = [flow.amount * curve.discount_factor(flow.payment_date) for flow in flows]
        subtitle = f"discounted on {curve.name}"
    else:
        ytm = bond.yield_to_maturity(bond.clean_price_from_yield(bond.coupon_rate, settlement), settlement)
        grid_times = bond.period_grid(settlement)
        values = [
            flow.amount / (1 + ytm / bond.frequency) ** periods for flow, periods in zip(flows, grid_times, strict=True)
        ]
        subtitle = f"discounted at {ytm * 100:.2f}%"
    present.bar(positions, values, color=PALETTE["slate"], width=0.62)
    present.set_xticks(positions[::step], labels=labels[::step], rotation=35, ha="right")
    style_axes(present, title=f"Present value of each flow, {subtitle}", ylabel="Present value")
    total = sum(values)
    annotate(
        present,
        f"total {total:,.2f}",
        xy=(0.03, 0.92),
        xycoords="axes fraction",
        highlight=True,
    )

    accrued = bond.accrued_interest(settlement)
    days, period_days = bond.days_accrued(settlement)
    title_block(
        figure,
        f"{bond.name} - cash flows from {settlement.isoformat()}",
        f"Accrued interest {accrued:.4f} per {bond.face_value:g} of face ({days} of {period_days} days), "
        "which is paid by the buyer on settlement and is not part of the quoted price.",
    )
    caption(
        figure,
        f"Day count {bond.day_count.value}, {bond.frequency} coupons a year, calendar {bond.schedule.calendar_name}.",
    )
    return figure


def plot_accrual_path(bond: FixedRateBond, start: date, end: date) -> Figure:
    """Accrued interest through time: the sawtooth that resets at every coupon."""
    days = (end - start).days
    dates = [start + timedelta(days=offset) for offset in range(0, days + 1, max(1, days // 400))]
    accrued = [bond.accrued_interest(day) for day in dates]

    figure = new_figure(11.0, 4.6)
    axis = figure.add_subplot()
    figure.subplots_adjust(top=0.78, bottom=0.16, left=0.08, right=0.97)
    axis.plot([day.toordinal() for day in dates], accrued, color=PALETTE["navy"])
    axis.fill_between([day.toordinal() for day in dates], accrued, color=PALETTE["navy"], alpha=0.12)
    for period in bond.schedule:
        if start <= period.end <= end:
            axis.axvline(period.end.toordinal(), color=PALETTE["grid"], linewidth=0.8)

    ticks = [dates[index] for index in np.linspace(0, len(dates) - 1, 8).astype(int)]
    axis.set_xticks([day.toordinal() for day in ticks], labels=[day.strftime("%b %y") for day in ticks])
    style_axes(axis, ylabel=f"Accrued per {bond.face_value:g} of face")
    annotate(
        axis,
        "each vertical line is a coupon payment, where the accrual resets to zero",
        xy=(0.03, 0.9),
        xycoords="axes fraction",
        highlight=True,
    )
    title_block(
        figure,
        f"{bond.name} - accrued interest",
        "The buyer of a bond pays the seller for the part of the coupon the seller earned. "
        "A valuation that forgets it is wrong by up to a full coupon.",
    )
    caption(figure, f"Computed on {bond.day_count.value} within each accrual period.")
    return figure


def plot_flow_composition(bond: FixedRateBond, settlement: date, curve: YieldCurve) -> Figure:
    """How much of a bond's value is coupons and how much is the return of principal."""
    flows = bond.cash_flows(settlement)
    coupon_pv = sum(
        (flow.amount - (bond.face_value if flow.kind != "coupon" else 0.0)) * curve.discount_factor(flow.payment_date)
        for flow in flows
    )
    principal_pv = bond.face_value * curve.discount_factor(flows[-1].payment_date)

    figure = new_figure(9.0, 4.6)
    axis = figure.add_subplot()
    figure.subplots_adjust(top=0.78, bottom=0.14, left=0.1, right=0.97)
    axis.barh(["Present value"], [coupon_pv], color=PALETTE["navy"], height=0.42, label="Coupons")
    axis.barh(
        ["Present value"], [principal_pv], left=[coupon_pv], color=PALETTE["teal"], height=0.42, label="Principal"
    )
    total = coupon_pv + principal_pv
    axis.set_xlim(0, total * 1.12)
    for value, left, label in ((coupon_pv, 0.0, "Coupons"), (principal_pv, coupon_pv, "Principal")):
        axis.text(
            left + value / 2,
            0,
            f"{label}\n{value:,.2f} ({value / total:.0%})",
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="bold",
        )
    style_axes(axis, xlabel="Present value per 100 of face", grid="x")
    axis.legend().remove()

    title_block(
        figure,
        f"{bond.name} - where the value comes from",
        f"Total {total:,.2f} on {curve.name}. A low coupon bond is mostly a claim on principal, "
        "which is why its duration is long.",
    )
    caption(figure, f"Discounted on the zero curve at {curve.valuation_date.isoformat()}.")
    return figure
