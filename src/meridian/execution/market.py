"""A trading day, minute by minute: volume, prices, the spread, and what our own trades do to them.

The daily market data of Day 2 says how much a stock trades and how much it
moves in a day; it says nothing about the shape of the day, and nothing about
what a large order does to the price. Execution needs both, so each stock's day
is simulated on a grid of 390 one-minute bars (09:30 to 16:00 in its own
session):

* **Volume** follows the U-shape every equity market shows - heavy at the open,
  a lull at lunch, heavier still into the close - scaled to the stock's average
  daily volume, with a random day-level multiplier.
* **The unimpacted mid-price** is a random walk whose minute-by-minute variance
  follows the same U-shape (the open is the most volatile part of the day), and
  whose total over the day is the stock's daily variance. The day opens away
  from the previous close by an overnight gap.
* **Our trades** move it: each share traded shifts the mid permanently by
  ``γ σ`` per unit of daily volume (Almgren and Chriss's linear permanent
  impact), and each fill pays half the spread plus a temporary impact of
  ``η σ √(q / V)`` for ``q`` shares in a bar of ``V`` - the square-root law,
  which lasts only for that fill.

The simulator keeps both paths: the market as it would have been without us,
and as it was with us. That is what an empirical study of trading cost can
never observe and what makes the cost decomposition in :mod:`.tca` exact - the
impact of an order is measured, not estimated, and a calibration of the impact
model can be checked against the parameters that generated the data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..core.exceptions import ValidationError

SESSION_MINUTES = 390
OVERNIGHT_SHARE = 0.25  # the overnight gap's standard deviation, as a share of the daily volatility


def volume_profile(
    minutes: int = SESSION_MINUTES, *, open_weight: float = 2.2, close_weight: float = 3.0
) -> np.ndarray:
    """The expected share of the day's volume in each minute: a U-shape, heavier into the close, summing to one."""
    t = np.arange(minutes) + 0.5
    shape = 1.0 + open_weight * np.exp(-t / 25.0) + close_weight * np.exp(-(minutes - t) / 18.0)
    return shape / shape.sum()


@dataclass(frozen=True)
class ImpactModel:
    """How our trades move the price, in units of the stock's daily volatility."""

    temporary: float = 0.35  # eta: a fill of q shares in a bar of V pays eta * sigma * sqrt(q / V)
    permanent: float = 0.25  # gamma: trading one day's volume moves the mid by gamma * sigma for good

    def temporary_cost(self, sigma: float, quantity: float, bar_volume: float) -> float:
        """Temporary impact as a fraction of the price."""
        if quantity <= 0 or bar_volume <= 0:
            return 0.0
        return self.temporary * sigma * math.sqrt(quantity / bar_volume)

    def permanent_shift(self, sigma: float, quantity: float, daily_volume: float) -> float:
        """Permanent move of the mid, as a fraction of the price, for ``quantity`` shares."""
        return self.permanent * sigma * quantity / daily_volume


@dataclass(frozen=True)
class StockProfile:
    """What the day needs to know about a stock: its last close, volatility, volume and spread."""

    instrument_id: str
    previous_close: float  # base currency per share
    daily_volatility: float
    average_volume: float  # shares a day
    spread_bps: float

    def __post_init__(self) -> None:
        if self.previous_close <= 0 or self.daily_volatility <= 0 or self.average_volume <= 0:
            raise ValidationError(f"{self.instrument_id}: price, volatility and volume must be positive")


@dataclass
class ExecutionRecord:
    """One fill, with the two prices the simulator knows and a trading desk never does."""

    minute: int
    quantity: float
    price: float  # what we paid (bought) or received (sold)
    mid: float  # the mid-price we traded against, with our earlier trades' permanent impact in it
    unimpacted: float  # the mid-price as it would have been had we never traded
    half_spread: float  # as a fraction of the mid
    temporary: float  # as a fraction of the mid


@dataclass
class MarketDay:
    """One stock's simulated day."""

    profile: StockProfile
    impact: ImpactModel
    volumes: np.ndarray  # shares traded by the rest of the market in each minute
    unimpacted: np.ndarray  # mid-price path with no trades of ours, one per minute (the price at the bar's end)
    open_price: float
    shift: np.ndarray = field(init=False)  # our cumulative permanent impact, a fraction, per minute

    def __post_init__(self) -> None:
        self.shift = np.zeros(len(self.volumes))

    @classmethod
    def simulate(
        cls,
        profile: StockProfile,
        *,
        seed: int,
        impact: ImpactModel | None = None,
        minutes: int = SESSION_MINUTES,
        volume_noise: float = 0.25,
    ) -> MarketDay:
        rng = np.random.default_rng(seed)
        expected = volume_profile(minutes)
        day_level = math.exp(volume_noise * rng.standard_normal() - 0.5 * volume_noise**2)
        noise = rng.gamma(shape=8.0, scale=1 / 8.0, size=minutes)  # bar-to-bar variation, mean one
        volumes = profile.average_volume * day_level * expected * noise
        sigma = profile.daily_volatility
        gap = OVERNIGHT_SHARE * sigma * rng.standard_normal()
        open_price = profile.previous_close * math.exp(gap)
        steps = rng.standard_normal(minutes) * sigma * np.sqrt(expected)  # variance follows the volume U-shape
        path = open_price * np.exp(np.cumsum(steps) - 0.5 * np.cumsum(sigma**2 * expected))
        return cls(profile, impact or ImpactModel(), volumes, path, open_price)

    # ------------------------------------------------------------------ prices
    @property
    def minutes(self) -> int:
        return len(self.volumes)

    def mid(self, minute: int) -> float:
        """The mid-price at a minute, with our permanent impact so far."""
        return float(self.unimpacted[minute] * (1.0 + self.shift[minute]))

    def arrival(self, minute: int) -> float:
        """The mid when an order reaches the desk at the start of ``minute``: the open, or the previous bar's close.

        A bar's price is the price at its end, so the price an order released at
        minute m arrives to is the one at the end of minute m - 1, before it can
        trade; minute m's own move belongs to the trading.
        """
        if not 0 <= minute < self.minutes:
            raise ValidationError(f"minute {minute} is outside the session")
        return self.open_price if minute == 0 else self.mid(minute - 1)

    @property
    def close(self) -> float:
        return self.mid(self.minutes - 1)

    @property
    def unimpacted_close(self) -> float:
        return float(self.unimpacted[-1])

    def vwap(self, start: int = 0, end: int | None = None, own: list[ExecutionRecord] | None = None) -> float:
        """The interval's volume-weighted average price, the market's trades and our own together."""
        end = self.minutes if end is None else end
        prices = self.unimpacted[start:end] * (1.0 + self.shift[start:end])
        volume = self.volumes[start:end]
        value = float(prices @ volume)
        total = float(volume.sum())
        for record in own or []:
            if start <= record.minute < end:
                value += record.price * record.quantity
                total += record.quantity
        return value / total

    # ------------------------------------------------------------------ trading
    def trade(self, minute: int, quantity: float, sign: int, limit: float | None = None) -> ExecutionRecord | None:
        """Take ``quantity`` shares in one bar; returns the fill, or None if the limit forbids it.

        The fill pays half the spread and the temporary impact; the permanent
        impact then moves the mid for the rest of the day.
        """
        if quantity <= 0:
            return None
        sigma = self.profile.daily_volatility
        mid = self.mid(minute)
        half_spread = self.profile.spread_bps / 2e4
        temporary = self.impact.temporary_cost(sigma, quantity, float(self.volumes[minute]))
        price = mid * (1.0 + sign * (half_spread + temporary))
        if limit is not None and sign * (price - limit) > 0:
            return None
        record = ExecutionRecord(minute, quantity, price, mid, float(self.unimpacted[minute]), half_spread, temporary)
        shift = self.impact.permanent_shift(sigma, quantity, self.profile.average_volume)
        # the mid moves after the fill, for the rest of the day
        self.shift[minute + 1 :] += sign * shift
        return record
