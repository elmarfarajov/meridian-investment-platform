"""Meridian: an institutional investment management platform.

The package is layered so that each concern can be tested on its own:

``meridian.core``
    Value objects every other layer depends on - money, currencies, FX,
    security identifiers, trading calendars and day-count conventions.
``meridian.domain``
    The business model: instruments, portfolios, accounts, positions and
    transactions, expressed as immutable dataclasses with validation.
``meridian.persistence``
    SQLAlchemy mappings, migrations and repositories. Nothing above this layer
    knows which database is in use.
``meridian.viz``
    The house chart style and figure builders, so every module can ship a
    visual result rather than only numbers.
"""

__version__ = "0.1.0"
