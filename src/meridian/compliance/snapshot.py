"""What a rule is checked against: the portfolio on one day, holding by holding.

A snapshot is the list of holdings with their weights in NAV and the attributes
a mandate can refer to - asset class, sector, industry, issuer, country,
currency, credit rating, days to liquidate - plus the portfolio-level metrics
from the risk model. Cash is a holding like any other (``CASH.USD``), so
"cash between 1% and 10%" is an ordinary weight rule and every snapshot's
weights add up to one.

**Look-through.** An index fund is one line in the book but a few hundred
companies in the market. ``expanded()`` replaces each fund by its constituents
in index weights, so a rule "with look-through" sees the Microsoft held
directly *and* the Microsoft inside the S&P 500 fund as one issuer - the
question a regulator asks, and the one a direct-holdings check misses.

Weights are floats (analytics, ADR 0008). Limits are exact decimals, and a
value within 1e-12 of its limit counts as at the limit, so a weight of exactly
10% computed through floating point is not a breach of "<= 10%".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date

from ..core.exceptions import ValidationError

Attribute = str | float | None

#: Long-term credit ratings, best first; a rating compares by its place in this list.
RATING_SCALE: tuple[str, ...] = (
    "AAA",
    "AA+",
    "AA",
    "AA-",
    "A+",
    "A",
    "A-",
    "BBB+",
    "BBB",
    "BBB-",
    "BB+",
    "BB",
    "BB-",
    "B+",
    "B",
    "B-",
    "CCC+",
    "CCC",
    "CCC-",
    "CC",
    "C",
    "D",
)
CASH_PREFIX = "CASH."


def rating_score(rating: str) -> int:
    """Higher is better: AAA is 22, D is 1, so ``rating < "BBB-"`` means below investment grade."""
    try:
        return len(RATING_SCALE) - RATING_SCALE.index(rating.strip().upper())
    except ValueError as error:
        raise ValidationError(f"unknown credit rating {rating!r}") from error


@dataclass(frozen=True)
class Holding:
    key: str  # instrument identifier, or CASH.<currency>
    weight: float
    attributes: Mapping[str, Attribute] = field(default_factory=dict)
    via: str | None = None  # the fund a looked-through holding came from

    def attribute(self, name: str) -> Attribute:
        if name == "weight":
            return self.weight
        if name == "instrument":
            return self.key
        return self.attributes.get(name)


@dataclass(frozen=True)
class Snapshot:
    day: date
    nav: float
    holdings: tuple[Holding, ...]
    metrics: Mapping[str, float] = field(default_factory=dict)
    #: fund -> its constituents as holdings whose weights are shares of the fund (summing to one)
    look_through: Mapping[str, tuple[Holding, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        keys = [holding.key for holding in self.holdings]
        if len(set(keys)) != len(keys):
            raise ValidationError(f"{self.day}: a snapshot lists each holding once")

    @property
    def total(self) -> float:
        return sum(holding.weight for holding in self.holdings)

    def holding(self, key: str) -> Holding | None:
        return next((item for item in self.holdings if item.key == key), None)

    def expanded(self) -> tuple[Holding, ...]:
        """Every fund replaced by its constituents, weighted by the fund's weight."""
        output: list[Holding] = []
        for holding in self.holdings:
            constituents = self.look_through.get(holding.key)
            if not constituents:
                output.append(holding)
                continue
            for constituent in constituents:
                output.append(replace(constituent, weight=holding.weight * constituent.weight, via=holding.key))
        return tuple(output)

    def with_weights(
        self, changes: Mapping[str, float], new_attributes: Mapping[str, Mapping[str, Attribute]] | None = None
    ) -> Snapshot:
        """A copy with some weights moved (a trade), adding holdings that were not there."""
        holdings = {holding.key: holding for holding in self.holdings}
        for key, change in changes.items():
            if key in holdings:
                holdings[key] = replace(holdings[key], weight=holdings[key].weight + change)
            else:
                attributes = (new_attributes or {}).get(key)
                if attributes is None:
                    raise ValidationError(f"no reference data for {key}")
                holdings[key] = Holding(key, change, attributes)
        kept = tuple(holding for holding in holdings.values() if abs(holding.weight) > 1e-15)
        return replace(self, holdings=kept)
