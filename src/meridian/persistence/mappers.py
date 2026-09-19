"""Translation between domain objects and database rows.

Keeping the mapping explicit - rather than persisting the domain classes directly -
means the schema can change for storage reasons without loosening the domain
invariants, and the domain never inherits from an ORM base class it does not need.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from ..core.currency import get_currency
from ..core.enums import AccountType, InstrumentType, SecurityStatus, TransactionType
from ..core.identifiers import CUSIP, FIGI, ISIN, SEDOL, Ticker
from ..domain.instruments import Bond, CashInstrument, Equity, Fund, Instrument, SecurityIdentifiers
from ..domain.portfolios import Account, Benchmark, Client, Household, InvestmentPolicy, Portfolio
from ..domain.positions import TaxLot
from ..domain.transactions import Transaction
from .models import (
    AccountRow,
    BenchmarkRow,
    ClientRow,
    HouseholdRow,
    InstrumentRow,
    PortfolioRow,
    TaxLotRow,
    TransactionRow,
)

_EQUITY_TYPES = {InstrumentType.COMMON_STOCK, InstrumentType.PREFERRED_STOCK}
_FUND_TYPES = {InstrumentType.ETF, InstrumentType.MUTUAL_FUND, InstrumentType.PRIVATE_FUND}
_BOND_TYPES = {InstrumentType.GOVERNMENT_BOND, InstrumentType.CORPORATE_BOND, InstrumentType.MONEY_MARKET}


def instrument_to_row(instrument: Instrument) -> InstrumentRow:
    identifiers = instrument.identifiers
    row = InstrumentRow(
        instrument_id=instrument.instrument_id,
        name=instrument.name,
        instrument_type=instrument.instrument_type.value,
        asset_class=instrument.asset_class.value,
        currency=instrument.currency.code,
        isin=str(identifiers.isin) if identifiers.isin else None,
        cusip=str(identifiers.cusip) if identifiers.cusip else None,
        sedol=str(identifiers.sedol) if identifiers.sedol else None,
        figi=str(identifiers.figi) if identifiers.figi else None,
        ticker=str(identifiers.ticker) if identifiers.ticker else None,
        exchange=instrument.exchange,
        country=instrument.country,
        calendar=instrument.calendar,
        status=instrument.status.value,
        multiplier=instrument.multiplier,
    )
    if isinstance(instrument, Equity):
        row.sector = instrument.sector
        row.industry = instrument.industry
        row.issuer_id = instrument.issuer_id
    elif isinstance(instrument, Fund):
        row.expense_ratio = instrument.expense_ratio
        row.benchmark_id = instrument.benchmark_id
    elif isinstance(instrument, Bond):
        row.coupon = instrument.coupon
        row.maturity = instrument.maturity
        row.face_value = instrument.face_value
        row.issuer_id = instrument.issuer_id
    return row


def row_to_instrument(row: InstrumentRow) -> Instrument:
    identifiers = SecurityIdentifiers(
        isin=ISIN(row.isin) if row.isin else None,
        cusip=CUSIP(row.cusip) if row.cusip else None,
        sedol=SEDOL(row.sedol) if row.sedol else None,
        figi=FIGI(row.figi) if row.figi else None,
        ticker=_parse_ticker(row.ticker),
    )
    instrument_type = InstrumentType(row.instrument_type)
    common: dict[str, Any] = {
        "instrument_id": row.instrument_id,
        "name": row.name,
        "instrument_type": instrument_type,
        "currency": row.currency,
        "identifiers": identifiers,
        "country": row.country,
        "exchange": row.exchange,
        "calendar": row.calendar,
        "status": SecurityStatus(row.status),
        "multiplier": row.multiplier if row.multiplier is not None else Decimal(1),
    }
    if instrument_type in _EQUITY_TYPES:
        return Equity(**common, sector=row.sector, industry=row.industry, issuer_id=row.issuer_id)
    if instrument_type in _FUND_TYPES:
        return Fund(**common, expense_ratio=row.expense_ratio, benchmark_id=row.benchmark_id)
    if instrument_type in _BOND_TYPES:
        return Bond(
            **common,
            coupon=row.coupon if row.coupon is not None else Decimal(0),
            maturity=row.maturity,
            face_value=row.face_value if row.face_value is not None else Decimal(100),
            issuer_id=row.issuer_id,
        )
    if instrument_type is InstrumentType.CASH:
        return CashInstrument(**common)
    return Instrument(**common)


def _parse_ticker(value: str | None) -> Ticker | None:
    if not value:
        return None
    if "." in value:
        symbol, _, exchange = value.rpartition(".")
        if exchange.isalpha() and len(exchange) >= 3:
            return Ticker(symbol, exchange)
    return Ticker(value)


def transaction_to_row(transaction: Transaction) -> TransactionRow:
    return TransactionRow(
        transaction_id=transaction.transaction_id,
        portfolio_id=transaction.portfolio_id,
        instrument_id=transaction.instrument_id,
        transaction_type=transaction.transaction_type.value,
        trade_date=transaction.trade_date,
        settlement_date=transaction.settlement_date,
        quantity=transaction.quantity,
        price=transaction.price,
        gross_amount=transaction.gross_amount,
        fees=transaction.fees,
        taxes=transaction.taxes,
        currency=transaction.currency.code,
        fx_rate=transaction.fx_rate,
        lot_id=transaction.lot_id,
        external_id=transaction.external_id,
        notes=transaction.notes,
    )


def row_to_transaction(row: TransactionRow) -> Transaction:
    return Transaction(
        transaction_id=row.transaction_id,
        portfolio_id=row.portfolio_id,
        instrument_id=row.instrument_id,
        transaction_type=TransactionType(row.transaction_type),
        trade_date=row.trade_date,
        settlement_date=row.settlement_date,
        quantity=row.quantity,
        price=row.price,
        gross_amount=row.gross_amount,
        fees=row.fees,
        taxes=row.taxes,
        currency=get_currency(row.currency),
        fx_rate=row.fx_rate,
        lot_id=row.lot_id,
        external_id=row.external_id,
        notes=row.notes,
    )


def portfolio_to_row(portfolio: Portfolio) -> PortfolioRow:
    policy = {key: str(value) for key, value in asdict(portfolio.policy).items() if value not in (None, (), "")}
    return PortfolioRow(
        portfolio_id=portfolio.portfolio_id,
        name=portfolio.name,
        base_currency=portfolio.base_currency.code,
        account_id=portfolio.account_id,
        benchmark_id=portfolio.benchmark_id,
        strategy=portfolio.strategy,
        inception=portfolio.inception,
        policy_json=json.dumps(policy) if policy else None,
    )


def row_to_portfolio(row: PortfolioRow) -> Portfolio:
    policy = InvestmentPolicy()
    if row.policy_json:
        payload = json.loads(row.policy_json)
        policy = InvestmentPolicy(
            target_equity_weight=payload.get("target_equity_weight"),
            max_single_issuer_weight=payload.get("max_single_issuer_weight"),
            max_cash_weight=payload.get("max_cash_weight"),
            tracking_error_budget=payload.get("tracking_error_budget"),
            notes=payload.get("notes"),
        )
    return Portfolio(
        portfolio_id=row.portfolio_id,
        name=row.name,
        base_currency=get_currency(row.base_currency),
        account_id=row.account_id,
        benchmark_id=row.benchmark_id,
        strategy=row.strategy,
        inception=row.inception,
        policy=policy,
    )


def account_to_row(account: Account) -> AccountRow:
    return AccountRow(
        account_id=account.account_id,
        name=account.name,
        account_type=account.account_type.value,
        base_currency=account.base_currency.code,
        household_id=account.household_id,
        client_id=account.client_id,
        custodian=account.custodian,
        opened=account.opened,
        closed=account.closed,
        calendar=account.calendar,
    )


def row_to_account(row: AccountRow) -> Account:
    return Account(
        account_id=row.account_id,
        name=row.name,
        account_type=AccountType(row.account_type),
        base_currency=get_currency(row.base_currency),
        household_id=row.household_id,
        client_id=row.client_id,
        custodian=row.custodian,
        opened=row.opened,
        closed=row.closed,
        calendar=row.calendar,
    )


def household_to_row(household: Household) -> HouseholdRow:
    return HouseholdRow(
        household_id=household.household_id,
        name=household.name,
        base_currency=household.base_currency.code,
    )


def row_to_household(row: HouseholdRow) -> Household:
    return Household(household_id=row.household_id, name=row.name, base_currency=get_currency(row.base_currency))


def client_to_row(client: Client) -> ClientRow:
    return ClientRow(
        client_id=client.client_id,
        name=client.name,
        domicile=client.domicile,
        tax_residence=client.tax_residence,
        onboarded=client.onboarded,
    )


def row_to_client(row: ClientRow) -> Client:
    return Client(
        client_id=row.client_id,
        name=row.name,
        domicile=row.domicile,
        tax_residence=row.tax_residence,
        onboarded=row.onboarded,
    )


def benchmark_to_row(benchmark: Benchmark) -> BenchmarkRow:
    return BenchmarkRow(
        benchmark_id=benchmark.benchmark_id,
        name=benchmark.name,
        currency=benchmark.currency.code,
        description=benchmark.description,
    )


def row_to_benchmark(row: BenchmarkRow) -> Benchmark:
    return Benchmark(
        benchmark_id=row.benchmark_id,
        name=row.name,
        currency=get_currency(row.currency),
        description=row.description,
    )


def tax_lot_to_row(lot: TaxLot, portfolio_id: str) -> TaxLotRow:
    return TaxLotRow(
        lot_id=lot.lot_id,
        portfolio_id=portfolio_id,
        instrument_id=lot.instrument_id,
        open_date=lot.open_date,
        quantity=lot.quantity,
        cost_per_unit=lot.cost_per_unit,
        currency=lot.currency.code,
        transaction_id=lot.transaction_id,
    )


def row_to_tax_lot(row: TaxLotRow) -> TaxLot:
    return TaxLot(
        lot_id=row.lot_id,
        instrument_id=row.instrument_id,
        open_date=row.open_date,
        quantity=row.quantity,
        cost_per_unit=row.cost_per_unit,
        currency=get_currency(row.currency),
        transaction_id=row.transaction_id,
    )
