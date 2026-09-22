"""Scoring the quality rules against faults whose location is known.

"The rules look sensible" is an opinion. Planting faults in clean data and
counting how many the rules find - and how much else they flag - is a
measurement. Two numbers matter, and they pull against each other:

* **Recall**: of the faults planted, how many did the rules catch? A missed
  fault is a wrong price in a client's valuation.
* **Precision**: of everything flagged, how much was a real fault? A false
  alarm costs an analyst's time, and a rule with too many of them gets
  switched off, which is worse than never having had it.

Genuine fat-tailed market moves in the synthetic data are *not* faults, so a
rule that flags them loses precision here exactly as it would on a real desk.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..marketdata.providers.faults import FaultKind, InjectedFault
from .findings import Finding

#: The rules each kind of fault should be caught by. A fault counts as detected
#: when any of its rules raises a finding overlapping it.
EXPECTED_RULES: dict[FaultKind, frozenset[str]] = {
    FaultKind.STALE_RUN: frozenset({"stale_mark"}),
    FaultKind.SPIKE: frozenset({"spike_reversal", "robust_outlier", "close_outside_quote"}),
    FaultKind.MISSING_RUN: frozenset({"missing_days"}),
    FaultKind.UNRECORDED_SPLIT: frozenset({"unexplained_jump"}),
    FaultKind.UNIT_ERROR: frozenset({"unexplained_jump"}),
    FaultKind.CROSSED_QUOTE: frozenset({"crossed_quote"}),
    FaultKind.HOLIDAY_PRINT: frozenset({"non_trading_day"}),
    FaultKind.NON_POSITIVE: frozenset({"non_positive_price"}),
    FaultKind.FX_TRIANGLE_BREAK: frozenset({"fx_triangle"}),
}


@dataclass(frozen=True, slots=True)
class KindScore:
    kind: FaultKind
    planted: int
    detected: int

    @property
    def recall(self) -> float:
        return self.detected / self.planted if self.planted else 1.0


@dataclass(frozen=True, slots=True)
class RuleScore:
    rule: str
    flagged: int
    true_positives: int

    @property
    def precision(self) -> float:
        return self.true_positives / self.flagged if self.flagged else 1.0

    @property
    def false_positives(self) -> int:
        return self.flagged - self.true_positives


@dataclass
class DetectionScore:
    kinds: list[KindScore]
    rules: list[RuleScore]
    missed: list[InjectedFault] = field(default_factory=list)
    false_alarms: list[Finding] = field(default_factory=list)

    @property
    def planted(self) -> int:
        return sum(item.planted for item in self.kinds)

    @property
    def detected(self) -> int:
        return sum(item.detected for item in self.kinds)

    @property
    def recall(self) -> float:
        return self.detected / self.planted if self.planted else 1.0

    @property
    def flagged(self) -> int:
        return sum(item.flagged for item in self.rules)

    @property
    def precision(self) -> float:
        flagged = self.flagged
        return sum(item.true_positives for item in self.rules) / flagged if flagged else 1.0

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)

    def kind(self, kind: FaultKind) -> KindScore:
        for item in self.kinds:
            if item.kind is kind:
                return item
        raise KeyError(kind)


def evaluate(
    findings: Sequence[Finding],
    faults: Sequence[InjectedFault],
    *,
    slack_days: int = 4,
    expected_rules: Mapping[FaultKind, frozenset[str]] = EXPECTED_RULES,
) -> DetectionScore:
    """Match findings to planted faults.

    ``slack_days`` allows for rules that legitimately flag a neighbouring day -
    a spike's reversal is flagged the day after the spike, a gap's end is
    judged on the first day after it.
    """
    by_key: dict[str, list[InjectedFault]] = defaultdict(list)
    for fault in faults:
        by_key[fault.key].append(fault)

    def overlapping(finding: Finding) -> list[InjectedFault]:
        return [
            fault
            for fault in by_key.get(finding.key, [])
            if fault.overlaps(finding.day, finding.last_day, slack_days=slack_days)
        ]

    detected: set[int] = set()
    rule_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    false_alarms: list[Finding] = []
    for finding in findings:
        matches = overlapping(finding)
        counts = rule_counts[finding.rule]
        counts[0] += 1
        if matches:
            counts[1] += 1
        else:
            false_alarms.append(finding)
        for fault in matches:
            if finding.rule in expected_rules.get(fault.kind, frozenset()):
                detected.add(id(fault))

    kinds: list[KindScore] = []
    missed: list[InjectedFault] = []
    for kind in FaultKind:
        planted = [fault for fault in faults if fault.kind is kind]
        if not planted:
            continue
        hits = [fault for fault in planted if id(fault) in detected]
        missed.extend(fault for fault in planted if id(fault) not in detected)
        kinds.append(KindScore(kind, len(planted), len(hits)))

    rules = [RuleScore(rule, counts[0], counts[1]) for rule, counts in sorted(rule_counts.items())]
    return DetectionScore(kinds=kinds, rules=rules, missed=missed, false_alarms=false_alarms)
