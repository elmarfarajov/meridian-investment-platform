"""Several vendors pricing the same instruments, each wrong in its own way.

No single source is right every day. An exchange feed is exact but misses
closed-market evaluations; a data vendor is broad but occasionally stale; an
evaluated pricing service is smooth but lags. A pricing desk's job is to
combine them, and the golden copy logic needs something realistic to combine.

A :class:`VendorProfile` describes one vendor's habits; :func:`vendor_panel`
applies each profile to a reference history and returns what each vendor would
have sent, together with the reference itself so the combination can be
scored.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np

from ...core.exceptions import ValidationError
from ..quotes import MarketDataset, Quote


@dataclass(frozen=True, slots=True)
class VendorProfile:
    """How one vendor deviates from the true close.

    ``noise_bps`` is the standard deviation of small, honest disagreements
    (different closing auctions, rounding, timing). ``stale_probability`` is the
    chance a day's value is simply the previous day's. ``error_probability`` is
    the chance of a gross error of ``error_size``. ``coverage`` is the share of
    days the vendor delivers anything at all.
    """

    name: str
    noise_bps: float = 0.0
    stale_probability: float = 0.0
    error_probability: float = 0.0
    error_size: float = 0.05
    coverage: float = 1.0

    def __post_init__(self) -> None:
        for label, value in (
            ("stale_probability", self.stale_probability),
            ("error_probability", self.error_probability),
            ("coverage", self.coverage),
        ):
            if not 0 <= value <= 1:
                raise ValidationError(f"{self.name}: {label} must be a probability")
        if self.noise_bps < 0:
            raise ValidationError(f"{self.name}: noise cannot be negative")


#: Three archetypal sources, in the priority order a pricing policy would rank them.
DEFAULT_VENDORS: tuple[VendorProfile, ...] = (
    VendorProfile("exchange", noise_bps=0.0, stale_probability=0.004, error_probability=0.002, coverage=0.985),
    VendorProfile("vendor-b", noise_bps=2.5, stale_probability=0.02, error_probability=0.004, coverage=0.995),
    VendorProfile("evaluated", noise_bps=6.0, stale_probability=0.05, error_probability=0.001, coverage=1.0),
)


def _scale(amount: Decimal, factor: Decimal, places: Decimal) -> Decimal:
    return (amount * factor).quantize(places, rounding=ROUND_HALF_EVEN)


def _scale_optional(amount: Decimal | None, factor: Decimal, places: Decimal) -> Decimal | None:
    return None if amount is None else _scale(amount, factor, places)


def vendor_panel(
    reference: MarketDataset,
    profiles: Sequence[VendorProfile] = DEFAULT_VENDORS,
    *,
    seed: int = 23,
) -> MarketDataset:
    """What each vendor would have sent for every instrument in ``reference``."""
    rng = np.random.default_rng(seed)
    produced: list[Quote] = []
    for profile in profiles:
        for instrument_id in reference.instruments:
            previous: Quote | None = None
            for truth in reference.for_instrument(instrument_id):
                if rng.random() > profile.coverage:
                    continue
                places = Decimal(1).scaleb(truth.close.as_tuple().exponent)  # type: ignore[arg-type]
                if previous is not None and rng.random() < profile.stale_probability:
                    value, bid, ask = previous.close, previous.bid, previous.ask
                else:
                    noise = rng.normal(0.0, profile.noise_bps / 10_000) if profile.noise_bps else 0.0
                    if rng.random() < profile.error_probability:
                        noise += profile.error_size * (1 if rng.random() < 0.5 else -1)
                    factor = Decimal(repr(1 + noise))
                    value = _scale(truth.close, factor, places)
                    # a quote is only as good as its source: the vendor's bid and ask move with its close
                    bid, ask = _scale_optional(truth.bid, factor, places), _scale_optional(truth.ask, factor, places)
                quote = Quote(
                    instrument_id=instrument_id,
                    day=truth.day,
                    close=value,
                    currency=truth.currency,
                    source=profile.name,
                    bid=bid,
                    ask=ask,
                    volume=truth.volume,
                )
                produced.append(quote)
                previous = quote
    return MarketDataset.from_records(produced)
