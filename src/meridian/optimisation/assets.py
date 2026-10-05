"""What the optimiser trades: assets, the tax lots inside them, and what trading them costs.

Every quantity the optimiser works with is a fraction of net asset value, so a
problem is the same size whatever the account is worth. An asset carries:

* its **price** and the **lots** held, each with its tax basis and the date its
  holding period runs from, so every sale can be priced in tax lot by lot;
* its **trading costs**: commission and half the bid-ask spread per unit
  traded, and a market impact that grows with the square root of the trade's
  share of daily volume - so impact per unit grows as sqrt(x), and the cost of a
  trade of size x as x^1.5, the form commercial cost models use;
* its **risk row**: how one unit of the asset loads on the risk model's
  coverage assets. A stock is itself; an index fund is its constituents in
  index weights plus its own basis, so the optimiser sees a fund's risk
  exactly as the risk report does.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from ..core.exceptions import ValidationError
from ..domain.positions import is_long_term, long_term_from


@dataclass(frozen=True)
class LotState:
    """One open tax lot, in base-currency terms."""

    lot_id: str
    asset_id: str
    quantity: float
    basis_per_unit: float  # tax basis in base currency, wash-sale adjustments included
    holding_start: date
    opened: date

    def is_long_term(self, as_of: date) -> bool:
        return is_long_term(self.holding_start, as_of)

    def days_to_long_term(self, as_of: date) -> int:
        return max((long_term_from(self.holding_start) - as_of).days, 0)


@dataclass(frozen=True)
class TradableAsset:
    asset_id: str
    price: float  # base currency per unit, clean: what the tax gain is measured on
    quantity: float  # units held
    lots: tuple[LotState, ...] = ()
    spread_bps: float = 5.0
    daily_volatility: float = 0.015
    daily_volume: float = 0.0  # average daily traded value, base currency
    lot_size: float = 1.0  # the smallest tradable number of units
    attributes: Mapping[str, str | float | None] = field(default_factory=dict)
    risk_row: Mapping[str, float] = field(default_factory=dict)  # coverage asset -> loading per unit of weight
    #: accrued interest per unit, base currency: part of what a bond is worth and what a sale receives,
    #: but income rather than a capital gain, so it stays out of the tax gain
    accrued_per_unit: float = 0.0

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValidationError(f"{self.asset_id}: the price must be positive")
        if self.lot_size <= 0:
            raise ValidationError(f"{self.asset_id}: the lot size must be positive")
        held = sum(lot.quantity for lot in self.lots)
        if self.lots and abs(held - self.quantity) > 1e-6 * max(1.0, self.quantity):
            raise ValidationError(f"{self.asset_id}: lots hold {held}, the position {self.quantity}")

    @property
    def unit_value(self) -> float:
        """What one unit is worth, accrued interest included."""
        return self.price + self.accrued_per_unit

    @property
    def value(self) -> float:
        return self.unit_value * self.quantity


@dataclass(frozen=True)
class CostModel:
    """Linear costs (commission and half-spread) and square-root market impact, per unit of NAV traded."""

    commission_bps: float = 5.0
    impact_coefficient: float = 0.1  # the "eta" of the square-root law

    def linear(self, asset: TradableAsset) -> float:
        return (self.commission_bps + asset.spread_bps / 2) / 1e4

    def impact(self, asset: TradableAsset, nav: float) -> float:
        """The coefficient ``k`` in cost = k * x^1.5 for a trade of x (fraction of NAV).

        Impact per unit traded is eta * daily volatility * sqrt(traded value / daily volume);
        with traded value x * NAV, the total cost is eta * sigma * sqrt(NAV / volume) * x^1.5.
        """
        if asset.daily_volume <= 0:
            return 0.0
        return self.impact_coefficient * asset.daily_volatility * math.sqrt(nav / asset.daily_volume)

    def cost(self, asset: TradableAsset, nav: float, traded: float) -> float:
        """Cost of trading ``traded`` (fraction of NAV, either sign), as a fraction of NAV."""
        size = abs(traded)
        return float(self.linear(asset) * size + self.impact(asset, nav) * size**1.5)
