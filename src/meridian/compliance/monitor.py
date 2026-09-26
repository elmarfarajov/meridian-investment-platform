"""Post-trade compliance: every day's check, and the register of breaches it opens.

After the close the whole mandate is checked against the book. A limit found
broken is a **breach**, and a breach is a record with a life of its own:

* it **opens** on the first day the rule is broken and **closes** on the first
  day it is not;
* it is **active** if the portfolio caused it - a trade on the opening day in
  a holding that makes up the breach - and **passive** if the market did,
  prices moving a compliant portfolio over a line nobody crossed on purpose;
* it has a **deadline**: an active breach must be reversed at once (the same
  day); a passive one may be cured within a grace period (thirty calendar days
  here, in the spirit of UCITS article 57, which asks for remedy "as a priority
  objective ... taking due account of the interests of unitholders");
* it ends **resolved by trading** (a trade on the closing day touched a
  contributor), **resolved by the market**, or it is still **open** - and past
  its deadline it is **overdue**, which is what a regulator asks about.

Severity comes from the rule (hard or soft) and how far past the limit the
breach went at its worst (its peak utilisation).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .engine import ComplianceReport, RuleResult

PASSIVE_GRACE_DAYS = 30


@dataclass
class Breach:
    breach_id: str
    rule_id: str
    rule_name: str
    severity: str  # hard | soft
    kind: str  # active | passive
    opened: date
    closed: date | None = None
    peak_utilisation: float = 0.0
    peak_value: float = 0.0
    peak_day: date | None = None
    days: int = 0  # evaluation days in breach
    resolution: str = "open"  # open | resolved by trading | resolved by the market
    contributors: tuple[str, ...] = ()

    @property
    def deadline(self) -> date:
        return self.opened if self.kind == "active" else self.opened + timedelta(days=PASSIVE_GRACE_DAYS)

    def age(self, as_of: date) -> int:
        return ((self.closed or as_of) - self.opened).days

    def state(self, as_of: date) -> str:
        if self.closed is not None:
            return self.resolution
        return "overdue" if as_of > self.deadline else "open"

    @property
    def grade(self) -> str:
        """Severity of the breach itself: how far past the limit it went, and how binding the limit is."""
        excess = self.peak_utilisation - 1.0
        if self.severity == "hard":
            return "critical" if excess > 0.10 else "high"
        return "medium" if excess > 0.10 else "low"


@dataclass
class ComplianceHistory:
    reports: list[ComplianceReport]
    breaches: list[Breach] = field(default_factory=list)

    @property
    def days(self) -> list[date]:
        return [report.day for report in self.reports]

    def series(self, rule_id: str) -> list[RuleResult]:
        return [report.result(rule_id) for report in self.reports]

    def open_breaches(self, as_of: date | None = None) -> list[Breach]:
        return [breach for breach in self.breaches if breach.closed is None]


def _contributor_keys(result: RuleResult, limit: int = 5) -> tuple[str, ...]:
    return tuple(label for label, _ in result.contributors[:limit])


def build_register(
    reports: Sequence[ComplianceReport],
    traded: Mapping[date, set[str]],
    groups_of: Mapping[str, set[str]] | None = None,
) -> list[Breach]:
    """Open and close breaches over a run of daily reports.

    ``traded`` maps a day to the instruments traded that day - every trade
    since the previous check counts, so a breach opened by a purchase
    settled over a weekend is still active; ``groups_of``
    maps an instrument to every label it can contribute under (its issuer,
    sector, country, currency and, for a fund, its constituents'), so a trade
    in the S&P 500 fund counts as touching Microsoft.
    """
    groups_of = groups_of or {}
    breaches: list[Breach] = []
    open_now: dict[str, Breach] = {}
    counter = 0

    trade_days = sorted(traded)
    previous: date | None = None

    def touched(day: date, result: RuleResult) -> bool:
        """Whether anything traded since the previous check is part of the result."""
        # a "max weight by" rule is broken by its heaviest group alone; other rules by what they add up
        labels = {result.group} if result.group else set(_contributor_keys(result, 50))
        for trade_day in trade_days:
            if trade_day > day or (previous is not None and trade_day <= previous):
                continue
            for instrument in traded[trade_day]:
                if instrument in labels or labels & groups_of.get(instrument, set()):
                    return True
        return False

    for report in reports:
        for result in report.results:
            rule_id = result.rule.rule_id
            current = open_now.get(rule_id)
            if result.is_breach:
                if current is None:
                    counter += 1
                    current = Breach(
                        breach_id=f"BR-{counter:04d}",
                        rule_id=rule_id,
                        rule_name=result.rule.name,
                        severity=result.rule.severity,
                        kind="active" if touched(report.day, result) else "passive",
                        opened=report.day,
                        contributors=_contributor_keys(result),
                    )
                    open_now[rule_id] = current
                    breaches.append(current)
                current.days += 1
                utilisation = result.utilisation or 0.0
                if utilisation >= current.peak_utilisation:
                    current.peak_utilisation = utilisation
                    current.peak_value = result.value or 0.0
                    current.peak_day = report.day
            elif current is not None and result.status != "not evaluable":
                current.closed = report.day
                current.resolution = "resolved by trading" if touched(report.day, result) else "resolved by the market"
                del open_now[rule_id]
        previous = report.day
    return breaches
