"""Charting: one house style, so every chart the platform produces looks like one firm's."""

from .calendars import divergent_days, month_grid, plot_trading_calendar, trading_days_by_month
from .style import (
    PALETTE,
    SERIES,
    annotate,
    apply_house_style,
    caption,
    legend_below,
    new_figure,
    save_figure,
    series_colours,
    style_axes,
    title_block,
)

__all__ = [
    "PALETTE",
    "SERIES",
    "annotate",
    "apply_house_style",
    "caption",
    "divergent_days",
    "legend_below",
    "month_grid",
    "new_figure",
    "plot_trading_calendar",
    "save_figure",
    "series_colours",
    "style_axes",
    "title_block",
    "trading_days_by_month",
]
