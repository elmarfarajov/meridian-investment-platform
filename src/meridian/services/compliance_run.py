"""The compliance run: check the mandate over the history, open the register, record the orders.

Before anything is written the run checks its own controls:

* the mandate stored is the mandate checked - every rule printed and parsed
  back is the same rule, so the text in the database is the rule that ran;
* every result has a known status, and every breach in the register opened on
  a day the rule was in breach;
* no hard breach is overdue on the last day - an overdue hard breach is not
  a number to store quietly but an escalation.

A failed control writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..compliance.engine import STATUSES
from ..compliance.language import to_text
from ..compliance.parser import parse_rule
from ..core.exceptions import ValidationError
from ..persistence.repositories import UnitOfWork, seed_reference_data
from ..seed import demo_book
from .demo_compliance import DemoCompliance


@dataclass
class ComplianceRunResult:
    portfolio_id: str
    mandate: str
    version: int
    days: int
    today: dict[str, int]
    breaches: int
    open_breaches: int
    orders_checked: int
    stored: dict[str, int] = field(default_factory=dict)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("portfolio", self.portfolio_id),
            ("mandate", f"{self.mandate}, version {self.version}"),
            ("days checked", f"{self.days:,}"),
            ("rules today", ", ".join(f"{count} {status}" for status, count in self.today.items() if count)),
            ("breaches in the register", f"{self.breaches} ({self.open_breaches} open)"),
            ("orders checked before trading", f"{self.orders_checked}"),
        ]
        rows += [(f"{table} rows stored", f"{count:,}") for table, count in self.stored.items()]
        return rows


def check_controls(compliance: DemoCompliance) -> None:
    for rule in compliance.mandate.rules:
        if parse_rule(to_text(rule)) != rule:
            raise ValidationError(f"{rule.rule_id}: the stored text would not reproduce the rule; nothing written")
    history = compliance.history
    for report in history.reports:
        for result in report.results:
            if result.status not in STATUSES:
                raise ValidationError(
                    f"{report.day} {result.rule.rule_id}: unknown status {result.status}; nothing written"
                )
    by_day = {report.day: report for report in history.reports}
    for breach in history.breaches:
        if not by_day[breach.opened].result(breach.rule_id).is_breach:
            raise ValidationError(f"{breach.breach_id} opened on a day its rule was not breached; nothing written")
    last = history.reports[-1].day
    overdue = [breach for breach in history.breaches if breach.severity == "hard" and breach.state(last) == "overdue"]
    if overdue:
        names = ", ".join(breach.breach_id for breach in overdue)
        raise ValidationError(f"hard breaches overdue on {last}: {names}; escalate before storing")


def run_demo_compliance(compliance: DemoCompliance, unit_of_work: UnitOfWork | None = None) -> ComplianceRunResult:
    check_controls(compliance)
    history = compliance.history
    today = history.reports[-1]
    portfolio = compliance.accounting.portfolio
    decisions = compliance.demo_decisions
    outcome = ComplianceRunResult(
        portfolio_id=portfolio.portfolio_id,
        mandate=compliance.mandate.name,
        version=compliance.mandate.version,
        days=len(history.reports),
        today={status: today.count(status) for status in STATUSES},
        breaches=len(history.breaches),
        open_breaches=len(history.open_breaches()),
        orders_checked=len(decisions),
    )
    if unit_of_work is None:
        return outcome
    if unit_of_work.portfolios.find(portfolio.portfolio_id) is None:
        reference = demo_book()
        seed_reference_data(
            unit_of_work,
            instruments=reference.instruments,
            benchmarks=reference.benchmarks,
            clients=reference.clients,
            households=reference.households,
            accounts=reference.accounts,
            portfolios=reference.portfolios,
        )
        unit_of_work.portfolios.add(portfolio)
        unit_of_work.flush()
    repository = unit_of_work.compliance
    outcome.stored["rule"] = repository.save_mandate(compliance.mandate)
    outcome.stored["result"] = repository.replace_results(portfolio.portfolio_id, history.reports)
    outcome.stored["breach"] = repository.replace_breaches(portfolio.portfolio_id, history.breaches)
    outcome.stored["pre-trade check"] = repository.save_pretrade(portfolio.portfolio_id, today.day, decisions)
    unit_of_work.flush()
    return outcome
