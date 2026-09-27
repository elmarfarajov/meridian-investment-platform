"""A small market to optimise in: six stocks, one factor, and an account with lots at gains and losses."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from meridian.optimisation.assets import LotState, TradableAsset
from meridian.optimisation.rebalance import Rebalancer, RiskView

AS_OF = date(2026, 9, 25)
NAV = 1_000_000.0
KEYS = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
PRICES = {"AAA": 100.0, "BBB": 50.0, "CCC": 80.0, "DDD": 40.0, "EEE": 120.0, "FFF": 60.0}


def lot(lot_id: str, asset_id: str, quantity: float, basis: float, days_ago: int) -> LotState:
    opened = AS_OF - timedelta(days=days_ago)
    return LotState(lot_id, asset_id, quantity, basis, opened, opened)


def make_lots() -> dict[str, tuple[LotState, ...]]:
    return {
        # AAA: an old gain, a young gain and a young loss - the lots the choice is about
        "AAA": (
            lot("A1", "AAA", 1_000, 60.0, 900),
            lot("A2", "AAA", 800, 90.0, 200),
            lot("A3", "AAA", 700, 130.0, 100),
        ),
        # BBB: one lot standing at a loss
        "BBB": (lot("B1", "BBB", 3_000, 70.0, 500),),
        # EEE: a large long-term gain
        "EEE": (lot("E1", "EEE", 1_000, 50.0, 1_200),),
    }


def make_assets(lots: dict[str, tuple[LotState, ...]] | None = None, **attributes: dict) -> list[TradableAsset]:
    lots = make_lots() if lots is None else lots
    output = []
    for key in KEYS:
        held = lots.get(key, ())
        output.append(
            TradableAsset(
                asset_id=key,
                price=PRICES[key],
                quantity=sum(item.quantity for item in held),
                lots=held,
                spread_bps=4.0,
                daily_volatility=0.015,
                daily_volume=50_000_000.0,
                attributes={"asset_class": "equity", "issuer": key, "sector": "S" + key[0], **attributes.get(key, {})},
                risk_row={key: 1.0},
            )
        )
    return output


def make_risk(benchmark: np.ndarray | None = None) -> RiskView:
    exposures = np.column_stack([np.ones(6), np.array([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])])
    return RiskView(
        keys=KEYS,
        exposures=exposures,
        factor_covariance=np.diag([0.01**2, 0.004**2]),
        specific=np.full(6, 0.012**2),
        benchmark=np.full(6, 0.95 / 6) if benchmark is None else benchmark,
        benchmark_cash=0.05,
    )


def make_rebalancer(**kwargs: object) -> Rebalancer:
    assets = kwargs.pop("assets", None) or make_assets()
    held = sum(asset.value for asset in assets)
    cash = 0.03
    nav = held / (1 - cash)
    return Rebalancer(AS_OF, nav, assets, cash, kwargs.pop("risk", None) or make_risk(), **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def rebalancer() -> Rebalancer:
    return make_rebalancer()


class Market:
    """The helpers, handed to tests as one fixture (test modules cannot import a conftest)."""

    as_of = AS_OF
    keys = KEYS
    prices = PRICES
    lot = staticmethod(lot)
    lots = staticmethod(make_lots)
    assets = staticmethod(make_assets)
    risk = staticmethod(make_risk)
    rebalancer = staticmethod(make_rebalancer)


@pytest.fixture(scope="session")
def market() -> type[Market]:
    return Market
