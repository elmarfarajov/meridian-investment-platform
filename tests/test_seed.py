"""The demonstration book is fixture data every later module builds on, so it is
tested like production data: identifiers must validate, references must resolve,
and the cash effects of the trades must have the right sign.
"""

from __future__ import annotations

from decimal import Decimal

from meridian.core.enums import AccountType, TransactionType
from meridian.core.identifiers import validate_cusip, validate_isin, validate_sedol
from meridian.seed import demo_book


def test_every_identifier_in_the_book_is_valid():
    for instrument in demo_book().instruments:
        identifiers = instrument.identifiers
        if identifiers.isin:
            assert validate_isin(str(identifiers.isin)), instrument.instrument_id
        if identifiers.cusip:
            assert validate_cusip(str(identifiers.cusip)), instrument.instrument_id
        if identifiers.sedol:
            assert validate_sedol(str(identifiers.sedol)), instrument.instrument_id


def test_references_resolve():
    book = demo_book()
    account_ids = {account.account_id for account in book.accounts}
    benchmark_ids = {benchmark.benchmark_id for benchmark in book.benchmarks}
    instrument_ids = {instrument.instrument_id for instrument in book.instruments}
    portfolio_ids = {portfolio.portfolio_id for portfolio in book.portfolios}
    household_ids = {household.household_id for household in book.households}
    client_ids = {client.client_id for client in book.clients}

    for account in book.accounts:
        assert account.household_id in household_ids
        assert account.client_id in client_ids
    for portfolio in book.portfolios:
        assert portfolio.account_id in account_ids
        assert portfolio.benchmark_id in benchmark_ids
    for transaction in book.transactions:
        assert transaction.portfolio_id in portfolio_ids
        assert transaction.instrument_id in instrument_ids


def test_the_book_spans_several_currencies_and_both_tax_treatments():
    book = demo_book()
    currencies = {instrument.currency.code for instrument in book.instruments}
    assert {"USD", "GBP", "EUR", "CHF"} <= currencies
    assert {account.account_type for account in book.accounts} == {AccountType.TAXABLE, AccountType.PENSION}
    assert any(account.is_taxable for account in book.accounts)
    assert any(not account.is_taxable for account in book.accounts)


def test_buys_consume_cash_and_sells_produce_it():
    for transaction in demo_book().transactions:
        if transaction.transaction_type is TransactionType.BUY:
            assert transaction.cash_impact.amount < 0
        if transaction.transaction_type is TransactionType.SELL:
            assert transaction.cash_impact.amount > 0


def test_stamp_duty_is_charged_on_the_uk_purchase():
    stamped = next(item for item in demo_book().transactions if item.instrument_id == "GB-BAE")
    assert stamped.taxes == Decimal("514.40")
    assert stamped.taxes == (stamped.gross * Decimal("0.005")).amount
    assert stamped.total_costs.amount == Decimal("544.40")
