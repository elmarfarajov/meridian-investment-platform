"""Charts for the trading calendars.

An exchange calendar looks like plumbing until a trade breaks. Two markets that
are open on different days are the reason a cross-border settlement fails, a
coupon lands a day late, or a performance series is compared against a benchmark
that did not trade that day. These charts make those days visible, which is why
this is the first thing the platform draws.
"""

from __future__ import annotations

import calendar as stdlib_calendar
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from ..core.calendars import TradingCalendar, get_calendar
from .style import PALETTE, annotate, caption, new_figure, series_colours, style_axes, title_block

MONTH_LABELS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_NOT_A_DAY, _WEEKEND, _TRADING, _HOLIDAY = 0, 1, 2, 3


def _to_rgb(colour: str) -> tuple[float, float, float]:
    value = colour.lstrip("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]


def _tint(colour: str, weight: float) -> tuple[float, float, float]:
    """Mix a colour towards white; ``weight`` is how much of the colour survives."""
    red, green, blue = _to_rgb(colour)
    return (
        red * weight + (1 - weight),
        green * weight + (1 - weight),
        blue * weight + (1 - weight),
    )


def month_grid(trading_calendar: TradingCalendar, year: int) -> np.ndarray:
    """A 12x31 grid classifying every day of the year for one calendar."""
    grid = np.full((12, 31), _NOT_A_DAY, dtype=np.int8)
    for month in range(1, 13):
        days_in_month = stdlib_calendar.monthrange(year, month)[1]
        for day_number in range(1, days_in_month + 1):
            day = date(year, month, day_number)
            if trading_calendar.is_weekend(day):
                state = _WEEKEND
            elif trading_calendar.is_holiday(day):
                state = _HOLIDAY
            else:
                state = _TRADING
            grid[month - 1, day_number - 1] = state
    return grid


def trading_days_by_month(trading_calendar: TradingCalendar, year: int) -> list[int]:
    grid = month_grid(trading_calendar, year)
    return [int((row == _TRADING).sum()) for row in grid]


def divergent_days(calendars: Sequence[TradingCalendar], year: int) -> list[date]:
    """Weekdays on which at least one market trades while another is shut.

    These are the days that generate settlement breaks and stale prices in a
    multi-currency book, so the count belongs on the front of the chart.
    """
    if len(calendars) < 2:
        return []
    days: list[date] = []
    day = date(year, 1, 1)
    end = date(year, 12, 31)
    while day <= end:
        if day.weekday() < 5:
            states = {item.is_business_day(day) for item in calendars}
            if len(states) > 1:
                days.append(day)
        day += timedelta(days=1)
    return days


def _draw_year_grid(ax: Axes, trading_calendar: TradingCalendar, year: int, colour: str) -> None:
    grid = month_grid(trading_calendar, year)
    image = np.zeros((12, 31, 3))
    palette = {
        _NOT_A_DAY: (1.0, 1.0, 1.0),
        _WEEKEND: _to_rgb(PALETTE["band"]),
        _TRADING: _tint(colour, 0.28),
        _HOLIDAY: _to_rgb(colour),
    }
    for state, rgb in palette.items():
        image[grid == state] = rgb

    ax.imshow(image, aspect="auto", interpolation="nearest")
    ax.set_xticks([0, 4, 9, 14, 19, 24, 29], labels=["1", "5", "10", "15", "20", "25", "30"])
    ax.set_yticks(range(12), labels=list(MONTH_LABELS))
    ax.set_xticks(np.arange(-0.5, 31, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 12, 1), minor=True)
    ax.grid(which="minor", color=PALETTE["surface"], linewidth=1.1)
    ax.grid(which="major", visible=False)
    ax.tick_params(which="minor", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    holiday_count = int((grid == _HOLIDAY).sum())
    trading_count = int((grid == _TRADING).sum())
    ax.set_title(
        f"{trading_calendar.name}  -  {trading_count} trading days, {holiday_count} holidays",
        color=PALETTE["ink"],
    )


def plot_trading_calendar(
    year: int,
    calendar_names: Sequence[str] = ("XNYS", "XLON", "TARGET"),
) -> Figure:
    """One year, one row per exchange, plus the monthly trading-day comparison."""
    calendars = [get_calendar(name) for name in calendar_names]
    colours = series_colours(len(calendars))

    figure = new_figure(width=11.5, height=3.2 + 2.4 * len(calendars))
    grid_spec = figure.add_gridspec(
        len(calendars) + 1,
        1,
        height_ratios=[1.0] * len(calendars) + [1.2],
        hspace=0.6,
        top=0.885,
        bottom=0.085,
        left=0.062,
        right=0.985,
    )

    for index, (trading_calendar, colour) in enumerate(zip(calendars, colours, strict=True)):
        _draw_year_grid(figure.add_subplot(grid_spec[index]), trading_calendar, year, colour)

    axis = figure.add_subplot(grid_spec[len(calendars)])
    positions = np.arange(12)
    width = 0.8 / len(calendars)
    for index, (trading_calendar, colour) in enumerate(zip(calendars, colours, strict=True)):
        counts = trading_days_by_month(trading_calendar, year)
        offset = (index - (len(calendars) - 1) / 2) * width
        axis.bar(
            positions + offset,
            counts,
            width=width * 0.92,
            color=colour,
            label=f"{trading_calendar.name} ({sum(counts)} days)",
        )
    axis.set_xticks(positions, labels=list(MONTH_LABELS))
    axis.set_ylim(0, 27)
    style_axes(axis, title="Trading days per month", ylabel="Days")
    axis.legend(loc="lower center", bbox_to_anchor=(0.5, -0.38), ncol=len(calendars), frameon=False)

    divergences = divergent_days(calendars, year)
    if divergences:
        annotate(
            axis,
            f"{len(divergences)} weekdays when one market trades and another is closed",
            xy=(11.55, 24.6),
            highlight=True,
            ha="right",
        )

    legend_handles = [
        Patch(facecolor=_tint(colours[0], 0.28), label="Trading day"),
        Patch(facecolor=_to_rgb(PALETTE["band"]), label="Weekend"),
        Patch(facecolor=_to_rgb(colours[0]), label="Exchange holiday"),
    ]
    figure.legend(
        handles=legend_handles,
        loc="upper right",
        bbox_to_anchor=(0.985, 0.995),
        ncol=3,
        frameon=False,
        fontsize=8,
    )

    title_block(
        figure,
        f"Exchange trading calendars, {year}",
        "Rule-based calendars, with no holiday file to go stale. "
        "Settlement, accrual and performance dates all derive from these.",
    )
    caption(
        figure,
        "Source: meridian.core.calendars. Holidays are computed from statutory rules, "
        "including Easter by the Meeus/Jones/Butcher algorithm and UK substitute days.",
    )
    return figure
