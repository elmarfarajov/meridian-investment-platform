"""Repositories for observations, corporate actions, the cross-reference and quality results.

The observation repository answers the same "as known at" question as the
in-memory :class:`~meridian.marketdata.bitemporal.BitemporalStore`, in SQL:
filter to rows recorded on or before the knowledge time, then keep the latest
row per value date. Both implementations are tested against the same cases, so
the reference model and the database cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core.exceptions import EntityNotFoundError
from ..domain.corporate_actions import CorporateAction
from ..marketdata.bitemporal import as_utc
from ..marketdata.quotes import Quote
from ..marketdata.series import TimeSeries
from ..quality.engine import QualityReport
from ..quality.findings import Finding
from ..refdata.xref import CrossReference, IdentifierScheme, XrefEntry
from . import marketdata_mappers as mappers
from .bulk import insert_missing
from .models import CorporateActionRow, IdentifierXrefRow, PriceObservationRow, QualityFindingRow, QualityRunRow


class PriceObservationRepository:
    """Append-only raw quotes from every source, with their knowledge times."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, quote: Quote, recorded_at: datetime, *, run_id: str | None = None) -> None:
        self.session.merge(mappers.quote_to_observation_row(quote, as_utc(recorded_at), run_id))

    def record_many(self, quotes: Iterable[Quote], recorded_at: datetime, *, run_id: str | None = None) -> int:
        """Record a batch at one knowledge time; exact resends are skipped. Returns the rows written."""
        moment = as_utc(recorded_at)
        rows = [mappers.observation_values(quote, moment, run_id) for quote in quotes]
        self.session.flush()
        return insert_missing(self.session, PriceObservationRow, rows)

    def as_known_at(
        self,
        instrument_id: str,
        known_at: datetime | None = None,
        *,
        source: str | None = None,
        price_type: str = "close",
        start: date | None = None,
        end: date | None = None,
    ) -> TimeSeries:
        """The series as it stood at ``known_at``: per date, the latest row recorded by then."""
        statement = (
            select(PriceObservationRow.price_date, PriceObservationRow.price, PriceObservationRow.recorded_at)
            .where(
                PriceObservationRow.instrument_id == instrument_id,
                PriceObservationRow.price_type == price_type,
            )
            .order_by(PriceObservationRow.price_date, PriceObservationRow.recorded_at)
        )
        if known_at is not None:
            statement = statement.where(PriceObservationRow.recorded_at <= as_utc(known_at))
        if source is not None:
            statement = statement.where(PriceObservationRow.source == source)
        if start is not None:
            statement = statement.where(PriceObservationRow.price_date >= start)
        if end is not None:
            statement = statement.where(PriceObservationRow.price_date <= end)
        latest: dict[date, Decimal] = {}
        for row in self.session.execute(statement):
            latest[row.price_date] = row.price  # rows arrive in knowledge order, so the last one wins
        return TimeSeries(latest.items(), name=instrument_id)

    def versions(
        self, instrument_id: str, price_date: date, *, source: str | None = None
    ) -> Sequence[tuple[datetime, str, Decimal]]:
        statement = (
            select(PriceObservationRow.recorded_at, PriceObservationRow.source, PriceObservationRow.price)
            .where(PriceObservationRow.instrument_id == instrument_id, PriceObservationRow.price_date == price_date)
            .order_by(PriceObservationRow.recorded_at)
        )
        if source is not None:
            statement = statement.where(PriceObservationRow.source == source)
        return [(row.recorded_at, row.source, row.price) for row in self.session.execute(statement)]

    def count(self, instrument_id: str | None = None) -> int:
        statement = select(func.count()).select_from(PriceObservationRow)
        if instrument_id is not None:
            statement = statement.where(PriceObservationRow.instrument_id == instrument_id)
        return int(self.session.scalar(statement) or 0)

    def sources(self) -> Sequence[str]:
        return list(
            self.session.scalars(select(PriceObservationRow.source).distinct().order_by(PriceObservationRow.source))
        )


class CorporateActionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, action: CorporateAction) -> CorporateAction:
        self.session.merge(mappers.corporate_action_to_row(action))
        return action

    def add_all(self, actions: Iterable[CorporateAction]) -> int:
        count = 0
        for action in actions:
            self.add(action)
            count += 1
        return count

    def get(self, action_id: str) -> CorporateAction:
        row = self.session.get(CorporateActionRow, action_id)
        if row is None:
            raise EntityNotFoundError("CorporateAction", action_id)
        return mappers.row_to_corporate_action(row)

    def for_instrument(
        self, instrument_id: str, *, start: date | None = None, end: date | None = None
    ) -> Sequence[CorporateAction]:
        statement = (
            select(CorporateActionRow)
            .where(CorporateActionRow.instrument_id == instrument_id)
            .order_by(CorporateActionRow.ex_date, CorporateActionRow.action_id)
        )
        if start is not None:
            statement = statement.where(CorporateActionRow.ex_date >= start)
        if end is not None:
            statement = statement.where(CorporateActionRow.ex_date <= end)
        return [mappers.row_to_corporate_action(row) for row in self.session.scalars(statement)]

    def list(
        self, *, action_type: str | None = None, start: date | None = None, end: date | None = None
    ) -> Sequence[CorporateAction]:
        statement = select(CorporateActionRow).order_by(CorporateActionRow.ex_date, CorporateActionRow.action_id)
        if action_type is not None:
            statement = statement.where(CorporateActionRow.action_type == action_type)
        if start is not None:
            statement = statement.where(CorporateActionRow.ex_date >= start)
        if end is not None:
            statement = statement.where(CorporateActionRow.ex_date <= end)
        return [mappers.row_to_corporate_action(row) for row in self.session.scalars(statement)]

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(CorporateActionRow)) or 0)


class XrefRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entry: XrefEntry) -> XrefEntry:
        self.session.merge(mappers.xref_to_row(entry))
        return entry

    def save(self, reference: CrossReference) -> int:
        """Replace the stored cross-reference with ``reference`` (validated in memory first)."""
        self.session.execute(delete(IdentifierXrefRow))
        count = 0
        for entry in reference.entries():
            self.add(entry)
            count += 1
        return count

    def load(self) -> CrossReference:
        rows = self.session.scalars(select(IdentifierXrefRow).order_by(IdentifierXrefRow.valid_from))
        return CrossReference(mappers.row_to_xref(row) for row in rows)

    def resolve(self, scheme: IdentifierScheme | str, value: str, on: date) -> str | None:
        statement = select(IdentifierXrefRow.instrument_id).where(
            IdentifierXrefRow.scheme == IdentifierScheme(scheme).value,
            IdentifierXrefRow.value == value.strip().upper(),
            IdentifierXrefRow.valid_from <= on,
            IdentifierXrefRow.valid_to > on,
        )
        return self.session.scalar(statement)


class QualityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, report: QualityReport) -> int:
        """Persist a run and its findings; saving the same run twice replaces it."""
        self.session.execute(delete(QualityFindingRow).where(QualityFindingRow.run_id == report.run_id))
        self.session.merge(
            QualityRunRow(
                run_id=report.run_id,
                as_of=report.as_of,
                series_count=len(report.scores),
                finding_count=len(report.findings),
                blocking_count=len(report.blocking()),
                overall_score=report.overall,
            )
        )
        self.session.flush()
        seen: set[str] = set()
        for finding in report.findings:
            row = mappers.finding_to_row(finding, report.run_id)
            if row.finding_id in seen:
                continue
            seen.add(row.finding_id)
            self.session.add(row)
        return len(seen)

    def runs(self) -> Sequence[QualityRunRow]:
        return list(self.session.scalars(select(QualityRunRow).order_by(QualityRunRow.created_at.desc())))

    def latest_run(self) -> QualityRunRow | None:
        return self.session.scalar(
            select(QualityRunRow).order_by(QualityRunRow.as_of.desc(), QualityRunRow.created_at.desc()).limit(1)
        )

    def findings(self, run_id: str, *, key: str | None = None, severity: str | None = None) -> Sequence[Finding]:
        statement = (
            select(QualityFindingRow)
            .where(QualityFindingRow.run_id == run_id)
            .order_by(QualityFindingRow.series_key, QualityFindingRow.day, QualityFindingRow.rule)
        )
        if key is not None:
            statement = statement.where(QualityFindingRow.series_key == key)
        if severity is not None:
            statement = statement.where(QualityFindingRow.severity == severity)
        return [mappers.row_to_finding(row) for row in self.session.scalars(statement)]
