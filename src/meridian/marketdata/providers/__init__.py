"""Market data sources: synthetic, file-based, in-memory, and combinations of them."""

from .base import MarketDataProvider, ProviderError, StaticProvider, load
from .csv_source import CsvProvider, LoadIssue, LoadResult, read_fx, read_quotes, write_fx, write_quotes
from .faults import FaultInjector, FaultKind, FaultSpec, InjectedFault
from .hierarchy import WaterfallProvider
from .synthetic import (
    FxSpec,
    InstrumentSpec,
    SyntheticHistory,
    SyntheticMarket,
    cross_rates,
    demo_market,
    garch_fourth_moment_finite,
    student_t_kurtosis,
    weekdays,
)
from .vendors import DEFAULT_VENDORS, VendorProfile, vendor_panel

__all__ = [
    "DEFAULT_VENDORS",
    "CsvProvider",
    "FaultInjector",
    "FaultKind",
    "FaultSpec",
    "FxSpec",
    "InjectedFault",
    "InstrumentSpec",
    "LoadIssue",
    "LoadResult",
    "MarketDataProvider",
    "ProviderError",
    "StaticProvider",
    "SyntheticHistory",
    "SyntheticMarket",
    "VendorProfile",
    "WaterfallProvider",
    "cross_rates",
    "demo_market",
    "garch_fourth_moment_finite",
    "load",
    "read_fx",
    "read_quotes",
    "student_t_kurtosis",
    "vendor_panel",
    "weekdays",
    "write_fx",
    "write_quotes",
]
