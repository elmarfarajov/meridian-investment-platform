"""Consistency rules across FX rates.

Exchange rates are not independent numbers: EURGBP has to equal EURUSD divided
by GBPUSD, to within a spread, or there is a riskless profit in going round the
triangle. Real markets close such gaps in milliseconds, so in *end-of-day
reference data* a broken triangle is never an opportunity - it is a stale leg,
a mis-keyed cross or a rate taken at a different fixing time. Because a
multi-currency book is translated through these rates, one bad cross misstates
every position held in either currency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..marketdata.series import TimeSeries
from .findings import Dimension, Finding, Severity


@dataclass(frozen=True, slots=True)
class Triangle:
    """A cross and the two pivot legs it should be derivable from."""

    cross: str
    base_leg: str
    quote_leg: str
    pivot: str

    def implied(self, legs: Mapping[str, Decimal]) -> Decimal | None:
        """The cross implied by the legs on one day, or ``None`` if a leg is missing."""
        base = self._to_pivot(self.cross[:3], legs)
        quote = self._to_pivot(self.cross[3:], legs)
        if base is None or quote is None or quote == 0:
            return None
        return base / quote

    def _to_pivot(self, currency: str, legs: Mapping[str, Decimal]) -> Decimal | None:
        if currency == self.pivot:
            return Decimal(1)
        direct = legs.get(f"{currency}{self.pivot}")
        if direct is not None:
            return direct
        inverse = legs.get(f"{self.pivot}{currency}")
        return Decimal(1) / inverse if inverse else None


def find_triangles(pairs: Mapping[str, TimeSeries] | list[str], pivot: str = "USD") -> list[Triangle]:
    """Every cross in ``pairs`` whose two pivot legs are also present."""
    names = set(pairs)
    pivot = pivot.upper()

    def leg(currency: str) -> str | None:
        for candidate in (f"{currency}{pivot}", f"{pivot}{currency}"):
            if candidate in names:
                return candidate
        return None

    triangles: list[Triangle] = []
    for pair in sorted(names):
        base, quote = pair[:3], pair[3:]
        if pivot in (base, quote):
            continue
        base_leg, quote_leg = leg(base), leg(quote)
        if base_leg and quote_leg:
            triangles.append(Triangle(pair, base_leg, quote_leg, pivot))
    return triangles


@dataclass
class FxTriangleRule:
    """A cross rate that disagrees with the product of its legs by more than ``tolerance_bps``."""

    tolerance_bps: float = 2.0
    pivot: str = "USD"
    name: str = "fx_triangle"
    dimension: Dimension = Dimension.CONSISTENCY

    def residuals(self, pairs: Mapping[str, TimeSeries]) -> dict[str, list[tuple[date, float]]]:
        """Per cross, the daily gap between the quoted and the implied rate, in basis points."""
        results: dict[str, list[tuple[date, float]]] = {}
        for triangle in find_triangles(pairs, self.pivot):
            quoted = pairs[triangle.cross]
            legs = {triangle.base_leg: pairs[triangle.base_leg], triangle.quote_leg: pairs[triangle.quote_leg]}
            gaps: list[tuple[date, float]] = []
            for point in quoted:
                values = {name: series.get(point.day) for name, series in legs.items()}
                available = {name: value for name, value in values.items() if value is not None}
                implied = triangle.implied(available)
                if implied is None or implied == 0:
                    continue
                gaps.append((point.day, float(point.value / implied - 1) * 10_000))
            results[triangle.cross] = gaps
        return results

    def check(self, pairs: Mapping[str, TimeSeries]) -> list[Finding]:
        findings: list[Finding] = []
        triangles = {triangle.cross: triangle for triangle in find_triangles(pairs, self.pivot)}
        for cross, gaps in self.residuals(pairs).items():
            triangle = triangles[cross]
            for day, gap in gaps:
                if abs(gap) <= self.tolerance_bps:
                    continue
                severity = Severity.ERROR if abs(gap) > 10 * self.tolerance_bps else Severity.WARNING
                findings.append(
                    Finding(
                        rule=self.name,
                        key=cross,
                        day=day,
                        severity=severity,
                        dimension=self.dimension,
                        message=f"{cross} is {gap:+.1f} bp from {triangle.base_leg} / {triangle.quote_leg}",
                        observed=gap,
                        expected=0.0,
                    )
                )
        return findings


@dataclass
class FxInverseRule:
    """Both directions of a pair supplied, and their product is not one."""

    tolerance_bps: float = 1.0
    name: str = "fx_inverse"
    dimension: Dimension = Dimension.CONSISTENCY

    def check(self, pairs: Mapping[str, TimeSeries]) -> list[Finding]:
        findings: list[Finding] = []
        for pair in sorted(pairs):
            inverse = pair[3:] + pair[:3]
            if inverse not in pairs or pair > inverse:
                continue
            forward, backward = pairs[pair], pairs[inverse]
            for point in forward:
                other = backward.get(point.day)
                if other is None:
                    continue
                gap = float(point.value * other - 1) * 10_000
                if abs(gap) > self.tolerance_bps:
                    findings.append(
                        Finding(
                            rule=self.name,
                            key=pair,
                            day=point.day,
                            severity=Severity.ERROR,
                            dimension=self.dimension,
                            message=f"{pair} x {inverse} = {1 + gap / 10_000:.6f}, {gap:+.1f} bp away from 1",
                            observed=gap,
                            expected=0.0,
                        )
                    )
        return findings
