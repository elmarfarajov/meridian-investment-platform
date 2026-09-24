"""Shared fixtures for the accounting tests: a portfolio, the demonstration instruments and fixed rates."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from meridian.accounting.engine import AccountingEngine, AccountingPolicy
from meridian.accounting.sources import FixedFx
from meridian.domain import Portfolio
from meridian.domain.instruments import Instrument
from meridian.seed import demo_instruments


@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio(portfolio_id="P", name="Test book", base_currency="USD")


@pytest.fixture
def instruments() -> dict[str, Instrument]:
    return {item.instrument_id: item for item in demo_instruments()}


@pytest.fixture
def fx() -> FixedFx:
    return FixedFx({"EUR": "1.10", "GBP": "1.25", "CHF": "1.12"})


@pytest.fixture
def engine(portfolio: Portfolio, instruments: dict[str, Instrument], fx: FixedFx) -> AccountingEngine:
    return AccountingEngine(portfolio, instruments, fx)


@pytest.fixture
def make_engine(portfolio: Portfolio, instruments: dict[str, Instrument]) -> Callable[..., AccountingEngine]:
    """An engine with a chosen FX source, price source and policy."""

    def build(fx: object, *, prices: object = None, **policy: object) -> AccountingEngine:
        return AccountingEngine(portfolio, instruments, fx, prices=prices, policy=AccountingPolicy(**policy))  # type: ignore[arg-type]

    return build
