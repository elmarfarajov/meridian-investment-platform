"""What a quality rule reports.

Findings are classified along the data quality dimensions used in data
governance frameworks (DAMA-DMBOK), because "the price is wrong" is not
actionable and "the price is *late*" or "the price is *inconsistent with its
own bid and ask*" is. Each dimension points to a different fix: completeness
to the vendor's coverage, timeliness to the feed schedule, validity to the
load, accuracy to the source, consistency to the reference data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Severity(str, Enum):
    """How urgently a human needs to look. Ordered from least to most severe."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    @property
    def blocks_publication(self) -> bool:
        """An error or worse stops the value reaching the golden copy until someone signs it off."""
        return self.rank >= Severity.ERROR.rank

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


_SEVERITY_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2, Severity.CRITICAL: 3}


class Dimension(str, Enum):
    COMPLETENESS = "completeness"  # is every expected value there?
    TIMELINESS = "timeliness"  # is it current?
    VALIDITY = "validity"  # is it a legal value at all?
    ACCURACY = "accuracy"  # is it plausibly the true value?
    CONSISTENCY = "consistency"  # does it agree with related data?


#: How much each dimension contributes to an overall score. Accuracy and completeness
#: weigh most because they are the ones that reach a valuation unnoticed.
DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.COMPLETENESS: 0.25,
    Dimension.TIMELINESS: 0.15,
    Dimension.VALIDITY: 0.20,
    Dimension.ACCURACY: 0.25,
    Dimension.CONSISTENCY: 0.15,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    """One problem found by one rule in one series.

    ``day`` is where the problem starts and ``end_day`` where it stops, for
    problems that are runs (a stale stretch, a gap). ``observed`` and
    ``expected`` carry the numbers behind the message so a dashboard can plot
    them without parsing text.
    """

    rule: str
    key: str
    day: date
    severity: Severity
    dimension: Dimension
    message: str
    end_day: date | None = None
    source: str = ""
    observed: float | None = None
    expected: float | None = None
    score: float | None = None

    @property
    def last_day(self) -> date:
        return self.end_day or self.day

    @property
    def span_days(self) -> int:
        return (self.last_day - self.day).days + 1

    @property
    def identifier(self) -> str:
        """Stable id: the same problem found twice has the same id, so reruns do not duplicate it."""
        source = f"@{self.source}" if self.source else ""
        return f"{self.rule}:{self.key}{source}:{self.day.isoformat()}"

    def __str__(self) -> str:
        span = f"..{self.end_day.isoformat()}" if self.end_day and self.end_day != self.day else ""
        return f"[{self.severity.value}] {self.key} {self.day.isoformat()}{span} {self.rule}: {self.message}"
