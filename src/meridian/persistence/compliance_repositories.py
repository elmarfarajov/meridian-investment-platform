"""Compliance in the database: the rules as written, every day's results, the breaches and the orders.

A compliance record has to answer an auditor's questions years later: which
rule, in which words, was in force on the day; what it measured; when a breach
opened and how it ended; which orders were stopped and why. Rules are stored
as the text they were written in, with a SHA-256 hash, so a result can be
traced to the exact wording that produced it and any later edit is visible as
a new version rather than a silent change.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ..compliance.engine import ComplianceReport
from ..compliance.language import Mandate, to_text
from ..compliance.monitor import Breach
from ..compliance.pretrade import PreTradeDecision
from .base import utcnow
from .models import ComplianceBreachRow, ComplianceResultRow, ComplianceRuleRow, PreTradeCheckRow


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ComplianceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ rules
    def save_mandate(self, mandate: Mandate) -> int:
        """Store one version of a mandate; storing the same version again replaces it."""
        self.session.execute(
            delete(ComplianceRuleRow).where(
                ComplianceRuleRow.mandate == mandate.name, ComplianceRuleRow.version == mandate.version
            )
        )
        now = utcnow()
        rows = [
            {
                "mandate": mandate.name,
                "version": mandate.version,
                "rule_id": rule.rule_id,
                "title": rule.title,
                "severity": rule.severity,
                "text": to_text(rule),
                "text_hash": text_hash(to_text(rule)),
                "effective": mandate.effective,
                "created_at": now,
                "updated_at": now,
            }
            for rule in mandate.rules
        ]
        self.session.execute(insert(ComplianceRuleRow), rows)
        return len(rows)

    def rules(self, mandate: str, version: int | None = None) -> list[ComplianceRuleRow]:
        statement = select(ComplianceRuleRow).where(ComplianceRuleRow.mandate == mandate)
        if version is None:
            latest = select(func.max(ComplianceRuleRow.version)).where(ComplianceRuleRow.mandate == mandate)
            statement = statement.where(ComplianceRuleRow.version == latest.scalar_subquery())
        else:
            statement = statement.where(ComplianceRuleRow.version == version)
        return list(self.session.scalars(statement.order_by(ComplianceRuleRow.rule_id)))

    # ------------------------------------------------------------------ results
    def replace_results(self, portfolio_id: str, reports: Sequence[ComplianceReport]) -> int:
        self.session.execute(delete(ComplianceResultRow).where(ComplianceResultRow.portfolio_id == portfolio_id))
        now = utcnow()
        rows = [
            {
                "portfolio_id": portfolio_id,
                "check_date": report.day,
                "rule_id": result.rule.rule_id,
                "mandate_version": report.mandate.version,
                "status": result.status,
                "value": result.value,
                "utilisation": None
                if result.utilisation is None or result.utilisation == float("inf")
                else result.utilisation,
                "headroom": result.headroom,
                "top_contributor": result.group or (result.contributors[0][0] if result.contributors else None),
                "created_at": now,
                "updated_at": now,
            }
            for report in reports
            for result in report.results
        ]
        for start in range(0, len(rows), 5_000):
            self.session.execute(insert(ComplianceResultRow), rows[start : start + 5_000])
        return len(rows)

    def status_counts(self, portfolio_id: str, check_date: date | None = None) -> dict[str, int]:
        """How many rule results had each status, counted in SQL (on one day, or over the history)."""
        statement = (
            select(ComplianceResultRow.status, func.count())
            .where(ComplianceResultRow.portfolio_id == portfolio_id)
            .group_by(ComplianceResultRow.status)
        )
        if check_date is not None:
            statement = statement.where(ComplianceResultRow.check_date == check_date)
        return {status: int(count) for status, count in self.session.execute(statement)}

    def results(self, portfolio_id: str, rule_id: str) -> list[ComplianceResultRow]:
        return list(
            self.session.scalars(
                select(ComplianceResultRow)
                .where(ComplianceResultRow.portfolio_id == portfolio_id, ComplianceResultRow.rule_id == rule_id)
                .order_by(ComplianceResultRow.check_date)
            )
        )

    # ------------------------------------------------------------------ breaches
    def replace_breaches(self, portfolio_id: str, breaches: Iterable[Breach]) -> int:
        self.session.execute(delete(ComplianceBreachRow).where(ComplianceBreachRow.portfolio_id == portfolio_id))
        now = utcnow()
        rows = [
            {
                "breach_id": breach.breach_id,
                "portfolio_id": portfolio_id,
                "rule_id": breach.rule_id,
                "severity": breach.severity,
                "kind": breach.kind,
                "opened": breach.opened,
                "closed": breach.closed,
                "deadline": breach.deadline,
                "days": breach.days,
                "peak_utilisation": breach.peak_utilisation,
                "peak_value": breach.peak_value,
                "resolution": breach.resolution,
                "created_at": now,
                "updated_at": now,
            }
            for breach in breaches
        ]
        if rows:
            self.session.execute(insert(ComplianceBreachRow), rows)
        return len(rows)

    def breaches(self, portfolio_id: str, *, open_only: bool = False) -> list[ComplianceBreachRow]:
        statement = select(ComplianceBreachRow).where(ComplianceBreachRow.portfolio_id == portfolio_id)
        if open_only:
            statement = statement.where(ComplianceBreachRow.closed.is_(None))
        return list(self.session.scalars(statement.order_by(ComplianceBreachRow.opened, ComplianceBreachRow.breach_id)))

    def breach_days(self, portfolio_id: str) -> dict[tuple[str, str], int]:
        """Days in breach by (kind, severity), summed in SQL."""
        statement = (
            select(ComplianceBreachRow.kind, ComplianceBreachRow.severity, func.sum(ComplianceBreachRow.days))
            .where(ComplianceBreachRow.portfolio_id == portfolio_id)
            .group_by(ComplianceBreachRow.kind, ComplianceBreachRow.severity)
        )
        return {(kind, severity): int(total) for kind, severity, total in self.session.execute(statement)}

    # ------------------------------------------------------------------ pre-trade
    def save_pretrade(self, portfolio_id: str, check_date: date, decisions: Iterable[PreTradeDecision]) -> int:
        now = utcnow()
        rows = []
        for decision in decisions:
            order = decision.order
            self.session.execute(delete(PreTradeCheckRow).where(PreTradeCheckRow.check_id == order.order_id))
            rows.append(
                {
                    "check_id": order.order_id,
                    "portfolio_id": portfolio_id,
                    "check_date": check_date,
                    "instrument_id": order.instrument_id,
                    "side": order.side,
                    "amount": order.amount,
                    "decision": decision.decision,
                    "maximum": decision.maximum,
                    "reasons": "; ".join(f"{change.rule_id}: {change.effect}" for change in decision.reasons),
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if rows:
            self.session.execute(insert(PreTradeCheckRow), rows)
        return len(rows)

    def pretrade(self, portfolio_id: str, decision: str | None = None) -> list[PreTradeCheckRow]:
        statement = select(PreTradeCheckRow).where(PreTradeCheckRow.portfolio_id == portfolio_id)
        if decision is not None:
            statement = statement.where(PreTradeCheckRow.decision == decision)
        return list(self.session.scalars(statement.order_by(PreTradeCheckRow.check_id)))
