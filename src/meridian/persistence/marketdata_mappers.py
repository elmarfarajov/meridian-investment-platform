"""Mappings for the market data tables.

Corporate actions are a small type hierarchy with different terms per type. The
dates every action shares are real columns, because every query filters on
them; the terms that differ by type go into one JSON document. Decimals are
written as strings, so a dividend of 0.2475 comes back as exactly 0.2475.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ..core.exceptions import ValidationError
from ..domain.corporate_actions import (
    CashDividend,
    CashMerger,
    CorporateAction,
    CorporateActionType,
    RightsIssue,
    SpinOff,
    StockDividend,
    StockMerger,
    StockSplit,
    SymbolChange,
)
from ..marketdata.quotes import Quote
from ..quality.findings import Dimension, Finding, Severity
from ..refdata.xref import IdentifierScheme, XrefEntry
from .models import CorporateActionRow, IdentifierXrefRow, PriceObservationRow, QualityFindingRow

_ACTION_CLASSES: dict[CorporateActionType, type[CorporateAction]] = {
    CorporateActionType.CASH_DIVIDEND: CashDividend,
    CorporateActionType.STOCK_DIVIDEND: StockDividend,
    CorporateActionType.SPLIT: StockSplit,
    CorporateActionType.SPIN_OFF: SpinOff,
    CorporateActionType.RIGHTS_ISSUE: RightsIssue,
    CorporateActionType.CASH_MERGER: CashMerger,
    CorporateActionType.STOCK_MERGER: StockMerger,
    CorporateActionType.SYMBOL_CHANGE: SymbolChange,
}
_COMMON = {"action_id", "instrument_id", "ex_date", "record_date", "pay_date", "announced", "notes"}
_RELATED = {"child_instrument_id", "acquirer_instrument_id"}
#: Terms held as Decimal on the domain object; everything else in the JSON is a string, int or bool.
_DECIMAL_TERMS = {
    "amount",
    "withholding_rate",
    "rate",
    "ratio",
    "child_price",
    "cost_allocation",
    "subscription_price",
    "cash_per_share",
}


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def corporate_action_to_row(action: CorporateAction) -> CorporateActionRow:
    terms = {
        name: _encode(getattr(action, name))
        for name in action.__dataclass_fields__
        if name not in _COMMON and getattr(action, name) is not None
    }
    related = next((str(terms[name]) for name in _RELATED if name in terms), None)
    return CorporateActionRow(
        action_id=action.action_id,
        instrument_id=action.instrument_id,
        action_type=action.action_type.value,
        ex_date=action.ex_date,
        record_date=action.record_date,
        pay_date=action.pay_date,
        announced=action.announced,
        related_instrument_id=related,
        terms_json=json.dumps(terms, sort_keys=True),
        notes=action.notes or None,
    )


def row_to_corporate_action(row: CorporateActionRow) -> CorporateAction:
    try:
        action_class = _ACTION_CLASSES[CorporateActionType(row.action_type)]
    except (KeyError, ValueError) as error:
        raise ValidationError(f"{row.action_id}: unknown corporate action type {row.action_type!r}") from error
    terms: dict[str, Any] = json.loads(row.terms_json or "{}")
    for name in list(terms):
        if name in _DECIMAL_TERMS and terms[name] is not None:
            terms[name] = Decimal(terms[name])
    return action_class(
        action_id=row.action_id,
        instrument_id=row.instrument_id,
        ex_date=row.ex_date,
        record_date=row.record_date,
        pay_date=row.pay_date,
        announced=row.announced,
        notes=row.notes or "",
        **terms,
    )


def quote_to_observation_row(quote: Quote, recorded_at: datetime, run_id: str | None = None) -> PriceObservationRow:
    return PriceObservationRow(
        instrument_id=quote.instrument_id,
        price_date=quote.day,
        price_type=quote.price_type.value,
        source=quote.source,
        recorded_at=recorded_at,
        price=quote.close,
        currency=quote.currency,
        bid=quote.bid,
        ask=quote.ask,
        volume=Decimal(quote.volume) if quote.volume is not None else None,
        run_id=run_id,
    )


def observation_values(quote: Quote, recorded_at: datetime, run_id: str | None = None) -> dict[str, Any]:
    """The same row as :func:`quote_to_observation_row`, as a dict for bulk insertion."""
    row = quote_to_observation_row(quote, recorded_at, run_id)
    audit = {"created_at", "updated_at"}
    return {
        column.name: getattr(row, column.name)
        for column in PriceObservationRow.__table__.columns
        if column.name not in audit
    }


def xref_to_row(entry: XrefEntry) -> IdentifierXrefRow:
    return IdentifierXrefRow(
        scheme=entry.scheme.value,
        value=entry.value,
        valid_from=entry.valid_from,
        valid_to=entry.valid_to,
        instrument_id=entry.instrument_id,
        source=entry.source or None,
    )


def row_to_xref(row: IdentifierXrefRow) -> XrefEntry:
    return XrefEntry(
        scheme=IdentifierScheme(row.scheme),
        value=row.value,
        instrument_id=row.instrument_id,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        source=row.source or "",
    )


def finding_to_row(finding: Finding, run_id: str) -> QualityFindingRow:
    return QualityFindingRow(
        run_id=run_id,
        finding_id=finding.identifier[:160],
        rule=finding.rule,
        series_key=finding.key,
        source=finding.source or None,
        day=finding.day,
        end_day=finding.end_day,
        severity=finding.severity.value,
        dimension=finding.dimension.value,
        message=finding.message[:512],
        observed=finding.observed,
        score=finding.score,
    )


def row_to_finding(row: QualityFindingRow) -> Finding:
    return Finding(
        rule=row.rule,
        key=row.series_key,
        day=row.day,
        end_day=row.end_day,
        severity=Severity(row.severity),
        dimension=Dimension(row.dimension),
        message=row.message,
        source=row.source or "",
        observed=row.observed,
        score=row.score,
    )
