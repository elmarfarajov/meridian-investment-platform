"""Mapping between the accounting objects and their tables.

Each function produces plain column dictionaries rather than ORM objects where
the rows are written in bulk: a book of record is rebuilt in full whenever it
is persisted, and thousands of postings go through one executemany rather
than one merge each.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..accounting.journal import EntryKind, JournalEntry, Posting
from ..accounting.lots import RealisationKind, RealisedLot
from ..accounting.reconciliation import Break
from ..accounting.valuation import PortfolioValuation, PositionValuation
from .base import utcnow
from .models import JournalEntryRow, JournalPostingRow, RealisedLotRow


def entry_values(entry: JournalEntry) -> dict[str, Any]:
    now = utcnow()
    return {
        "entry_id": entry.entry_id,
        "portfolio_id": entry.portfolio_id,
        "effective_date": entry.effective_date,
        "kind": entry.kind.value,
        "description": entry.description[:256],
        "source_id": entry.source_id,
        "reverses": entry.reverses,
        "cross_currency": entry.cross_currency,
        "created_at": now,
        "updated_at": now,
    }


def posting_values(entry: JournalEntry) -> list[dict[str, Any]]:
    return [
        {
            "entry_id": entry.entry_id,
            "line_no": index,
            "account_code": posting.account_code,
            "currency": posting.currency,
            "amount": posting.amount,
            "base_amount": posting.base_amount,
            "instrument_id": posting.instrument_id,
            "memo": posting.memo[:128] if posting.memo else None,
        }
        for index, posting in enumerate(entry.postings, start=1)
    ]


def row_to_entry(row: JournalEntryRow) -> JournalEntry:
    return JournalEntry(
        entry_id=row.entry_id,
        portfolio_id=row.portfolio_id,
        effective_date=row.effective_date,
        kind=EntryKind(row.kind),
        postings=tuple(row_to_posting(line) for line in row.postings),
        description=row.description,
        source_id=row.source_id,
        reverses=row.reverses,
        cross_currency=row.cross_currency,
    )


def row_to_posting(row: JournalPostingRow) -> Posting:
    return Posting(row.account_code, row.amount, row.currency, row.base_amount, row.instrument_id, row.memo or "")


def realised_values(item: RealisedLot) -> dict[str, Any]:
    now = utcnow()
    return {
        "portfolio_id": item.portfolio_id,
        "disposal_id": item.disposal_id,
        "lot_id": item.lot_id,
        "instrument_id": item.instrument_id,
        "open_date": item.open_date,
        "holding_start": item.holding_start,
        "close_date": item.close_date,
        "quantity": item.quantity,
        "currency": item.currency,
        "proceeds": item.proceeds,
        "cost": item.cost,
        "open_fx_rate": item.open_fx_rate,
        "close_fx_rate": item.close_fx_rate,
        "wash_sale_basis": item.wash_sale_basis,
        "disallowed_loss": item.disallowed_loss,
        "kind": item.kind.value,
        "term": item.term.value,
        "created_at": now,
        "updated_at": now,
    }


def row_to_realised(row: RealisedLotRow) -> RealisedLot:
    return RealisedLot(
        portfolio_id=row.portfolio_id,
        instrument_id=row.instrument_id,
        lot_id=row.lot_id,
        disposal_id=row.disposal_id,
        open_date=row.open_date,
        holding_start=row.holding_start,
        close_date=row.close_date,
        quantity=row.quantity,
        currency=row.currency,
        proceeds=row.proceeds,
        cost=row.cost,
        open_fx_rate=row.open_fx_rate,
        close_fx_rate=row.close_fx_rate,
        wash_sale_basis=row.wash_sale_basis,
        disallowed_loss=row.disallowed_loss,
        kind=RealisationKind(row.kind),
    )


def valuation_values(valuation: PortfolioValuation) -> dict[str, Any]:
    now = utcnow()
    return {
        "portfolio_id": valuation.portfolio_id,
        "valuation_date": valuation.day,
        "base_currency": valuation.base_currency,
        "nav": valuation.nav,
        "securities": valuation.securities,
        "accrued_interest": valuation.accrued_interest,
        "cash_like": valuation.cash_like,
        "settled_cash": valuation.settled_cash,
        "receivables": valuation.receivables,
        "payables": valuation.payables,
        "cost_base": valuation.cost_base,
        "unrealised_price": valuation.unrealised_price,
        "unrealised_fx": valuation.unrealised_fx,
        "missing_prices": len(valuation.missing),
        "created_at": now,
        "updated_at": now,
    }


def position_values(portfolio_id: str, day: date, item: PositionValuation) -> dict[str, Any]:
    now = utcnow()
    return {
        "portfolio_id": portfolio_id,
        "valuation_date": day,
        "instrument_id": item.instrument_id,
        "currency": item.currency,
        "quantity": item.quantity,
        "price": item.price,
        "price_date": item.price_date,
        "fx_rate": item.fx_rate,
        "market_value": item.market_value,
        "market_value_base": item.market_value_base,
        "accrued_base": item.accrued_base,
        "cost_base": item.cost_base,
        "unrealised_price_base": item.unrealised_price_base,
        "unrealised_fx_base": item.unrealised_fx_base,
        "created_at": now,
        "updated_at": now,
    }


def break_values(portfolio_id: str, item: Break) -> dict[str, Any]:
    now = utcnow()
    return {
        "portfolio_id": portfolio_id,
        "as_of": item.as_of,
        "kind": item.kind.value,
        "break_key": item.key,
        "cause": item.cause.value,
        "causes": ",".join(cause.value for cause in item.causes),
        "currency": item.currency,
        "book_value": item.book,
        "custodian_value": item.custodian,
        "value_base": item.value_base,
        "explanation": item.explanation[:256],
        "created_at": now,
        "updated_at": now,
    }
