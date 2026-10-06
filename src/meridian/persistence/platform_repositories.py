"""The platform's own records: users, the audit chain, idempotency keys and order requests."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..core.audit_chain import GENESIS, AuditRecord
from .base import utcnow
from .models import AuditLogRow, CounterRow, IdempotencyKeyRow, OrderRequestRow, PlatformUserRow

#: one writer at a time appends to the chain: read the head, seal, insert
CHAIN_LOCK = threading.Lock()


def _record(row: AuditLogRow) -> AuditRecord:
    return AuditRecord(
        row.sequence,
        row.recorded_at,
        row.request_id,
        row.username,
        row.method,
        row.path,
        row.status,
        row.latency_ms,
        row.idempotency_key,
        row.detail,
        row.previous_hash,
        row.record_hash,
    )


class PlatformRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ users
    def user(self, username: str) -> PlatformUserRow | None:
        return self.session.get(PlatformUserRow, username)

    def users(self) -> list[PlatformUserRow]:
        return list(self.session.scalars(select(PlatformUserRow).order_by(PlatformUserRow.username)))

    def save_user(
        self, username: str, full_name: str, password_hash: str, roles: Sequence[str], portfolios: Sequence[str] | None
    ) -> PlatformUserRow:
        row = self.user(username)
        now = utcnow()
        if row is None:
            row = PlatformUserRow(username=username, created_at=now)
            self.session.add(row)
        row.full_name = full_name
        row.password_hash = password_hash
        row.roles = ",".join(sorted(roles))
        row.portfolios = None if portfolios is None else ",".join(sorted(portfolios))
        row.active = True
        row.updated_at = now
        return row

    # ------------------------------------------------------------------ the audit chain
    def head(self) -> AuditLogRow | None:
        return self.session.scalars(select(AuditLogRow).order_by(AuditLogRow.sequence.desc()).limit(1)).first()

    def append(self, entry: AuditRecord) -> AuditRecord:
        """Seal an entry onto the end of the chain. The caller holds ``CHAIN_LOCK`` and commits."""
        head = self.head()
        sequence = 1 if head is None else head.sequence + 1
        previous = GENESIS if head is None else head.record_hash
        from dataclasses import replace

        sealed = replace(entry, sequence=sequence, previous_hash=previous).sealed()
        self.session.add(
            AuditLogRow(
                sequence=sealed.sequence,
                recorded_at=sealed.recorded_at,
                request_id=sealed.request_id,
                username=sealed.username,
                method=sealed.method,
                path=sealed.path,
                status=sealed.status,
                latency_ms=sealed.latency_ms,
                idempotency_key=sealed.idempotency_key,
                detail=sealed.detail,
                previous_hash=sealed.previous_hash,
                record_hash=sealed.record_hash,
            )
        )
        return sealed

    def records(self, *, after: int = 0, limit: int | None = None, username: str | None = None) -> list[AuditRecord]:
        statement = select(AuditLogRow).where(AuditLogRow.sequence > after).order_by(AuditLogRow.sequence)
        if username is not None:
            statement = statement.where(AuditLogRow.username == username)
        if limit is not None:
            statement = statement.limit(limit)
        return [_record(row) for row in self.session.scalars(statement)]

    def status_counts(self) -> dict[int, int]:
        statement = select(AuditLogRow.status, func.count()).group_by(AuditLogRow.status)
        return {int(status): int(count) for status, count in self.session.execute(statement)}

    # ------------------------------------------------------------------ idempotency
    def idempotent(self, key: str, username: str) -> IdempotencyKeyRow | None:
        return self.session.get(IdempotencyKeyRow, (key, username))

    def remember(
        self, key: str, username: str, method: str, path: str, request_hash: str, status: int, body: str
    ) -> None:
        now = utcnow()
        self.session.add(
            IdempotencyKeyRow(
                key=key,
                username=username,
                method=method,
                path=path,
                request_hash=request_hash,
                status=status,
                response_body=body[:20000],
                created_at=now,
                updated_at=now,
            )
        )

    def forget_before(self, moment: datetime) -> int:
        result = self.session.execute(delete(IdempotencyKeyRow).where(IdempotencyKeyRow.created_at < moment))
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ order requests
    def order(self, order_id: str) -> OrderRequestRow | None:
        return self.session.get(OrderRequestRow, order_id)

    def orders(self, portfolio_ids: Sequence[str] | None = None, *, limit: int = 100) -> list[OrderRequestRow]:
        statement = select(OrderRequestRow).order_by(OrderRequestRow.created_at.desc(), OrderRequestRow.order_id)
        if portfolio_ids is not None:
            statement = statement.where(OrderRequestRow.portfolio_id.in_(portfolio_ids))
        return list(self.session.scalars(statement.limit(limit)))

    def next_order_id(self) -> str:
        """The next order number: one atomic increment of the counter, inside the order's own transaction.

        The counter row stays locked until the order commits, so two orders never
        share a number, and an order rolled back gives its number back. Counting
        the orders instead (Day 9) handed two simultaneous orders the same number.
        """
        statement = (
            update(CounterRow)
            .where(CounterRow.name == "orders")
            .values(value=CounterRow.value + 1)
            .returning(CounterRow.value)
        )
        value = self.session.execute(statement).scalar_one_or_none()
        if value is None:  # a database made without the migration's seed row: start from the orders on record
            value = int(self.session.scalar(select(func.count()).select_from(OrderRequestRow)) or 0) + 1
            self.session.add(CounterRow(name="orders", value=value))
            self.session.flush()  # two first orders at once: the second insert fails, and is retried
        return f"ORD-{int(value):06d}"

    def decide_order(self, order_id: str, status: str, decided_by: str, note: str | None) -> bool:
        """Decide a pending order, if it is still pending; False if another decision got there first.

        One conditional UPDATE: the database decides between two approvers, not
        the order in which two requests happened to read the row.
        """
        result = self.session.execute(
            update(OrderRequestRow)
            .where(OrderRequestRow.order_id == order_id, OrderRequestRow.status == "pending approval")
            .values(status=status, decided_by=decided_by, decision_note=note, updated_at=utcnow())
        )
        return int(result.rowcount or 0) == 1  # type: ignore[attr-defined]

    def add_order(self, row: OrderRequestRow) -> None:
        now = utcnow()
        row.created_at = now
        row.updated_at = now
        self.session.add(row)
