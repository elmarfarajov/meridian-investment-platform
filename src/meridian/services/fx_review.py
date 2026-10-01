"""The quality engine on 27 years of real exchange rates, and two central banks set side by side.

Two studies on the packaged ECB and Federal Reserve data (``marketdata.fx_reference``):

- :func:`fx_quality_review` runs the FX quality rules over every currency the ECB has
  fixed since 1999. It runs them five times, each run adding one piece of what the
  rules need to know:
  1. as written for share prices (version 1.1.0);
  2. aware of the quote's resolution;
  3. aware of each currency's lifecycle;
  4. aware of its regime;
  5. reviewed against a register of market events.
  The stages show where 1,282 findings went, and what is left for a person to read.
- :func:`source_comparison` compares the ECB's 14:15 Frankfurt fixing with the
  Federal Reserve's New York noon rate for the same four pairs. It measures what
  "the same price from two sources" means when the sources fix at different
  moments.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import numpy as np

from ..marketdata.fx_reference import ecb_cross, ecb_rates, fed_rates
from ..quality.context import SeriesContext
from ..quality.engine import fx_series_rules
from ..quality.findings import Finding
from ..quality.fx_regimes import MarketEvent, PegBand, Review, fx_context, managed_days, review
from ..refdata.currency_regimes import inactive_spans

AS_OF = date(2026, 10, 1)
STAGES = (
    "as written for share prices",
    "+ the resolution of the quote",
    "+ each currency's lifecycle",
    "+ each currency's regime",
    "+ the register of market events",
)


@dataclass
class Stage:
    name: str
    findings: list[Finding]
    explained: int = 0

    @property
    def open(self) -> int:
        return len(self.findings) - self.explained

    def by_rule(self) -> Counter[str]:
        return Counter(finding.rule for finding in self.findings)


@dataclass
class FxQualityReview:
    stages: list[Stage]
    reviews: dict[str, Review]
    pairs: tuple[str, ...]
    observations: int
    first: date
    last: date
    open_findings: list[Finding] = field(default_factory=list)

    @property
    def explained(self) -> list[tuple[Finding, MarketEvent]]:
        return [item for entry in self.reviews.values() for item in entry.explained]


def _run(contexts: dict[str, SeriesContext], *, resolution_aware: bool, peg_band: bool) -> list[Finding]:
    rules = [*fx_series_rules(resolution_aware=resolution_aware), *([PegBand()] if peg_band else [])]
    return [finding for context in contexts.values() for rule in rules for finding in rule.check(context)]


@lru_cache(maxsize=1)
def fx_quality_review(as_of: date = AS_OF) -> FxQualityReview:
    rates = ecb_rates()
    plain = {pair: SeriesContext.from_series(pair, series, "TARGET", as_of=as_of) for pair, series in rates.items()}
    lifecycle = {
        pair: SeriesContext.from_series(pair, series, "TARGET", as_of=as_of, inactive=inactive_spans(pair[3:]))
        for pair, series in rates.items()
    }
    aware = {pair: fx_context(pair, series, as_of=as_of) for pair, series in rates.items()}
    final = _run(aware, resolution_aware=True, peg_band=True)
    reviews = review(final)
    explained = sum(len(entry.explained) for entry in reviews.values())
    stages = [
        Stage(STAGES[0], _run(plain, resolution_aware=False, peg_band=False)),
        Stage(STAGES[1], _run(plain, resolution_aware=True, peg_band=False)),
        Stage(STAGES[2], _run(lifecycle, resolution_aware=True, peg_band=False)),
        Stage(STAGES[3], final),
        Stage(STAGES[4], final, explained),
    ]
    return FxQualityReview(
        stages=stages,
        reviews=reviews,
        pairs=tuple(sorted(rates)),
        observations=sum(len(series) for series in rates.values()),
        first=min(series.first.day for series in rates.values()),
        last=max(series.last.day for series in rates.values()),
        open_findings=sorted(
            (finding for entry in reviews.values() for finding in entry.open), key=lambda f: (f.key, f.day)
        ),
    )


# ---------------------------------------------------------------------------- two central banks
@dataclass(frozen=True)
class SourceGap:
    """The ECB's fixing against the Fed's for one pair: every day both published, in basis points."""

    pair: str
    days: tuple[date, ...]
    gaps_bp: tuple[float, ...]
    next_ecb_move_bp: tuple[float, ...]

    @property
    def median_abs(self) -> float:
        return float(np.median(np.abs(self.gaps_bp)))

    @property
    def std(self) -> float:
        return float(np.std(self.gaps_bp))

    @property
    def lead_correlation(self) -> float:
        """How much of tomorrow's ECB move the Fed's later fix already shows."""
        return float(np.corrcoef(self.gaps_bp[:-1], self.next_ecb_move_bp[:-1])[0, 1])

    def largest(self, count: int = 3) -> list[tuple[date, float]]:
        order = np.argsort(np.abs(self.gaps_bp))[::-1][:count]
        return [(self.days[index], self.gaps_bp[index]) for index in order]


PAIRS = ("EURUSD", "GBPUSD", "USDCHF", "USDJPY")


@lru_cache(maxsize=1)
def source_comparison() -> tuple[SourceGap, ...]:
    fed = fed_rates()
    results = []
    for pair in PAIRS:
        ecb = ecb_rates()["EURUSD"] if pair == "EURUSD" else ecb_cross(pair[:3], pair[3:])
        days = [day for day in ecb.days if day in fed[pair]]
        ecb_days = ecb.days
        index = {day: position for position, day in enumerate(ecb_days)}
        gaps, moves = [], []
        for day in days:
            gaps.append(math.log(float(fed[pair][day]) / float(ecb[day])) * 1e4)
            position = index[day]
            following = ecb_days[position + 1] if position + 1 < len(ecb_days) else day
            moves.append(math.log(float(ecb[following]) / float(ecb[day])) * 1e4)
        results.append(SourceGap(pair, tuple(days), tuple(gaps), tuple(moves)))
    return tuple(results)


def regime_days(currency: str) -> frozenset[date]:
    """The days statistics leave alone for one currency, for charts."""
    pair = f"EUR{currency}"
    rates = ecb_rates()
    return managed_days(currency, rates[pair].days) if pair in rates else frozenset()
