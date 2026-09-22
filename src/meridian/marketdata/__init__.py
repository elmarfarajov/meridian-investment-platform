"""Market data: dated series, point-in-time storage, sources, adjustment and the golden copy.

``series``
    :class:`TimeSeries`, the exact, gap-aware container everything else passes around.
``bitemporal``
    Value date and knowledge time for every record, so any past state of knowledge
    can be rebuilt (ADR 0009).
``quotes`` and ``providers``
    What a source sent, and the sources themselves: synthetic, file-based, in memory,
    and ranked hierarchies of them.
``adjustments``
    Back-adjusted views of a history for corporate actions, derived on demand and
    never stored over the raw data (ADR 0011).
``golden``
    One published price per instrument and day from several sources (ADR 0010).
``fx_history``
    FX rates through time, with as-of lookup and staleness limits.
"""

from .adjustments import (
    AdjustedHistory,
    AdjustmentFactor,
    adjust_history,
    adjust_quantity,
    adjusted_history,
    adjustment_factors,
    cumulative_factor,
)
from .bitemporal import BitemporalStore, Observation, Revision, as_utc, end_of_day, lookahead_error
from .fx_history import FxHistory
from .golden import (
    GoldenCopy,
    GoldenMethod,
    GoldenPrice,
    PricingPolicy,
    build_golden_copy,
    choose_price,
    compare_to_reference,
)
from .quotes import FxQuote, MarketDataset, Quote
from .series import AsOfValue, FillMethod, Point, TimeSeries, merge_series

__all__ = [
    "AdjustedHistory",
    "AdjustmentFactor",
    "AsOfValue",
    "BitemporalStore",
    "FillMethod",
    "FxHistory",
    "FxQuote",
    "GoldenCopy",
    "GoldenMethod",
    "GoldenPrice",
    "MarketDataset",
    "Observation",
    "Point",
    "PricingPolicy",
    "Quote",
    "Revision",
    "TimeSeries",
    "adjust_history",
    "adjust_quantity",
    "adjusted_history",
    "adjustment_factors",
    "as_utc",
    "build_golden_copy",
    "choose_price",
    "compare_to_reference",
    "cumulative_factor",
    "end_of_day",
    "lookahead_error",
    "merge_series",
]
