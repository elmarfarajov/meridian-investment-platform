"""Convenience constructors for the transactions the engine books.

The domain :class:`~meridian.domain.transactions.Transaction` is deliberately
general. These functions fill it in the way the posting rules expect for each
kind of event - where the second currency of a conversion goes, how a transfer
in kind carries its original acquisition date, how a sale names the lots it
relieves - so that callers, the demonstration book and the tests all describe
events the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from ..core.currency import get_currency
from ..core.enums import LotSelectionMethod, TransactionType
from ..core.exceptions import ValidationError
from ..domain.transactions import Transaction

BUY_CURRENCY = "buy_currency"
BUY_AMOUNT = "buy_amount"
ACQUIRED = "acquired"
RECLAIMABLE = "reclaimable"
LOT_METHOD = "lot_method"
LOT_IDS = "lot_ids"


def fx_conversion(
    *,
    transaction_id: str,
    portfolio_id: str,
    trade_date: date,
    sell_currency: str,
    sell_amount: Decimal | str,
    buy_currency: str,
    rate: Decimal | str,
    settlement_date: date | None = None,
) -> Transaction:
    """A spot currency conversion: sell ``sell_amount``, receive ``sell_amount * rate`` of ``buy_currency``."""
    return Transaction(
        transaction_id=transaction_id,
        portfolio_id=portfolio_id,
        transaction_type=TransactionType.FX,
        trade_date=trade_date,
        settlement_date=settlement_date,
        currency=get_currency(sell_currency),
        gross_amount=Decimal(str(sell_amount)),
        price=Decimal(str(rate)),
        metadata={BUY_CURRENCY: get_currency(buy_currency).code},
    )


def cash_transaction(
    *,
    transaction_id: str,
    portfolio_id: str,
    kind: TransactionType,
    day: date,
    amount: Decimal | str,
    currency: str,
    notes: str | None = None,
) -> Transaction:
    """Deposits, withdrawals, fees and taxes: cash with no instrument."""
    if kind not in {TransactionType.DEPOSIT, TransactionType.WITHDRAWAL, TransactionType.FEE, TransactionType.TAX}:
        raise ValidationError(f"{kind.value} is not a cash-only transaction")
    return Transaction(
        transaction_id=transaction_id,
        portfolio_id=portfolio_id,
        transaction_type=kind,
        trade_date=day,
        settlement_date=day,
        currency=get_currency(currency),
        gross_amount=Decimal(str(amount)),
        notes=notes,
    )


def transfer_in(
    *,
    transaction_id: str,
    portfolio_id: str,
    instrument_id: str,
    day: date,
    quantity: Decimal | str | int,
    cost_per_unit: Decimal | str,
    currency: str,
    acquired: date,
    open_fx_rate: Decimal | str | None = None,
) -> Transaction:
    """Securities received from another custodian with their original cost and acquisition date."""
    metadata = {ACQUIRED: acquired.isoformat()}
    if open_fx_rate is not None:
        metadata["open_fx_rate"] = str(open_fx_rate)
    return Transaction(
        transaction_id=transaction_id,
        portfolio_id=portfolio_id,
        transaction_type=TransactionType.TRANSFER_IN,
        instrument_id=instrument_id,
        trade_date=day,
        settlement_date=day,
        quantity=Decimal(str(quantity)),
        price=Decimal(str(cost_per_unit)),
        currency=get_currency(currency),
        metadata=metadata,
    )


def purchase(
    *,
    transaction_id: str,
    portfolio_id: str,
    instrument_id: str,
    day: date,
    quantity: Decimal | str | int,
    price: Decimal | str,
    currency: str,
    fees: Decimal | str = "0",
    taxes: Decimal | str = "0",
    settlement_date: date | None = None,
    notes: str | None = None,
) -> Transaction:
    """A purchase. The settlement date is left to the engine's rule table unless given."""
    return Transaction(
        transaction_id=transaction_id,
        portfolio_id=portfolio_id,
        transaction_type=TransactionType.BUY,
        instrument_id=instrument_id,
        trade_date=day,
        settlement_date=settlement_date,
        quantity=Decimal(str(quantity)),
        price=Decimal(str(price)),
        currency=get_currency(currency),
        fees=Decimal(str(fees)),
        taxes=Decimal(str(taxes)),
        notes=notes,
    )


def sale(
    *,
    transaction_id: str,
    portfolio_id: str,
    instrument_id: str,
    day: date,
    quantity: Decimal | str | int,
    price: Decimal | str,
    currency: str,
    fees: Decimal | str = "0",
    taxes: Decimal | str = "0",
    settlement_date: date | None = None,
    method: LotSelectionMethod | None = None,
    lots: Sequence[str] = (),
    notes: str | None = None,
) -> Transaction:
    """A sale, optionally naming the relief method or the exact lots to close."""
    metadata: dict[str, str] = {}
    if method is not None:
        metadata[LOT_METHOD] = method.value
    if lots:
        metadata[LOT_IDS] = ",".join(lots)
    return Transaction(
        transaction_id=transaction_id,
        portfolio_id=portfolio_id,
        transaction_type=TransactionType.SELL,
        instrument_id=instrument_id,
        trade_date=day,
        settlement_date=settlement_date,
        quantity=Decimal(str(quantity)),
        price=Decimal(str(price)),
        currency=get_currency(currency),
        fees=Decimal(str(fees)),
        taxes=Decimal(str(taxes)),
        notes=notes,
        metadata=metadata,
    )
