"""Charting: one house style, so every chart the platform produces looks like one firm's."""

from .calendars import (
    divergence_matrix,
    divergent_days,
    month_grid,
    plot_divergence_matrix,
    plot_settlement_ladder,
    plot_trading_calendar,
    trading_days_by_month,
)
from .cashflows import plot_accrual_path, plot_cash_flows, plot_flow_composition, plot_schedule
from .money import plot_allocation, plot_daycount_comparison, plot_rounding_drift
from .rates import (
    plot_compounding,
    plot_curve_scenarios,
    plot_interpolation_comparison,
    plot_key_rate_durations,
    plot_price_yield,
    plot_yield_curve,
)
from .schema import plot_schema
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
    "divergence_matrix",
    "divergent_days",
    "legend_below",
    "month_grid",
    "new_figure",
    "plot_accrual_path",
    "plot_allocation",
    "plot_cash_flows",
    "plot_compounding",
    "plot_curve_scenarios",
    "plot_daycount_comparison",
    "plot_divergence_matrix",
    "plot_flow_composition",
    "plot_interpolation_comparison",
    "plot_key_rate_durations",
    "plot_price_yield",
    "plot_rounding_drift",
    "plot_schedule",
    "plot_schema",
    "plot_settlement_ladder",
    "plot_trading_calendar",
    "plot_yield_curve",
    "save_figure",
    "series_colours",
    "style_axes",
    "title_block",
    "trading_days_by_month",
]
