from __future__ import annotations

from datetime import date

import matplotlib.pyplot as plt

from meridian.core.calendars import get_calendar
from meridian.viz.calendars import (
    _HOLIDAY,
    _TRADING,
    _WEEKEND,
    divergent_days,
    month_grid,
    plot_trading_calendar,
    trading_days_by_month,
)


def test_month_grid_classifies_every_day_of_the_year():
    calendar = get_calendar("XNYS")
    grid = month_grid(calendar, 2026)
    classified = int((grid > 0).sum())
    assert classified == 365  # 2026 is not a leap year
    assert int((grid == _HOLIDAY).sum()) == len(calendar.holidays(2026))
    assert int((grid == _WEEKEND).sum()) == 104  # 52 weekends
    assert int((grid == _TRADING).sum()) == classified - 104 - len(calendar.holidays(2026))


def test_trading_days_by_month_sums_to_the_year():
    counts = trading_days_by_month(get_calendar("XNYS"), 2026)
    assert len(counts) == 12
    assert sum(counts) == 251  # NYSE trades 251 days in 2026


def test_divergent_days_are_the_days_that_break_settlement():
    calendars = [get_calendar(name) for name in ("XNYS", "XLON")]
    days = divergent_days(calendars, 2026)
    assert date(2026, 7, 3) in days  # Independence Day observed in the US, London open
    assert date(2026, 8, 31) in days  # UK summer bank holiday, New York open
    assert date(2026, 4, 3) not in days  # Good Friday closes both
    assert date(2026, 1, 1) not in days  # New Year closes both


def test_a_single_calendar_cannot_diverge_from_itself():
    assert divergent_days([get_calendar("XNYS")], 2026) == []


def test_the_chart_has_one_panel_per_calendar_plus_the_comparison():
    figure = plot_trading_calendar(2026, ("XNYS", "XLON", "TARGET"))
    try:
        assert len(figure.axes) == 4
        titles = [axis.get_title(loc="left") for axis in figure.axes]  # the house style titles left
        assert titles[0].startswith("XNYS")
        assert titles[-1] == "Trading days per month"
        assert "251 trading days" in titles[0]
    finally:
        plt.close(figure)


def test_the_chart_is_written_as_a_png(tmp_path):
    from meridian.viz import save_figure

    path = save_figure(plot_trading_calendar(2026, ("XNYS", "XLON")), tmp_path / "calendar.png", dpi=80)
    assert path.stat().st_size > 10_000
