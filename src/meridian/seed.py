"""A small but realistic demonstration book.

Every module from here on needs something to run against, and a hand-made book
is better than random data: the identifiers are real, the currencies are mixed,
one account is taxable and one is not, and the trades produce tax lots with both
short and long holding periods. That is enough to exercise accounting,
attribution, compliance and tax logic in later modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .core.currency import CHF, EUR, GBP, USD
from .core.enums import AccountType
from .core.identifiers import CUSIP, ISIN, SEDOL, Ticker
from .domain.instruments import Bond, CashInstrument, Equity, Fund, Instrument, SecurityIdentifiers
from .domain.portfolios import Account, Benchmark, Client, Household, InvestmentPolicy, Portfolio
from .domain.transactions import Transaction, build_trade


@dataclass(frozen=True)
class DemoBook:
    """Everything needed to populate an empty database."""

    clients: tuple[Client, ...]
    households: tuple[Household, ...]
    benchmarks: tuple[Benchmark, ...]
    instruments: tuple[Instrument, ...]
    accounts: tuple[Account, ...]
    portfolios: tuple[Portfolio, ...]
    transactions: tuple[Transaction, ...]


def demo_instruments() -> tuple[Instrument, ...]:
    return (
        Equity(
            instrument_id="US-AAPL",
            name="Apple Inc",
            currency=USD,
            identifiers=SecurityIdentifiers(
                isin=ISIN("US0378331005"), cusip=CUSIP("037833100"), ticker=Ticker("AAPL", "XNAS")
            ),
            country="US",
            exchange="XNAS",
            sector="Information Technology",
            industry="Technology Hardware",
            issuer_id="APPLE",
        ),
        Equity(
            instrument_id="US-MSFT",
            name="Microsoft Corporation",
            currency=USD,
            identifiers=SecurityIdentifiers(
                isin=ISIN("US5949181045"), cusip=CUSIP("594918104"), ticker=Ticker("MSFT", "XNAS")
            ),
            country="US",
            exchange="XNAS",
            sector="Information Technology",
            industry="Software",
            issuer_id="MICROSOFT",
        ),
        Equity(
            instrument_id="US-JNJ",
            name="Johnson & Johnson",
            currency=USD,
            identifiers=SecurityIdentifiers(isin=ISIN("US4781601046"), ticker=Ticker("JNJ", "XNYS")),
            country="US",
            exchange="XNYS",
            sector="Health Care",
            industry="Pharmaceuticals",
            issuer_id="JNJ",
        ),
        Equity(
            instrument_id="GB-BAE",
            name="BAE Systems plc",
            currency=GBP,
            identifiers=SecurityIdentifiers(
                isin=ISIN("GB0002634946"), sedol=SEDOL("0263494"), ticker=Ticker("BA", "XLON")
            ),
            country="GB",
            exchange="XLON",
            calendar="XLON",
            sector="Industrials",
            industry="Aerospace and Defence",
            issuer_id="BAE",
        ),
        Equity(
            instrument_id="DE-BAYN",
            name="Bayer AG",
            currency=EUR,
            identifiers=SecurityIdentifiers(isin=ISIN("DE000BAY0017"), ticker=Ticker("BAYN", "XETR")),
            country="DE",
            exchange="XETR",
            calendar="TARGET",
            sector="Health Care",
            industry="Pharmaceuticals",
            issuer_id="BAYER",
        ),
        Equity(
            instrument_id="CH-ROG",
            name="Roche Holding AG",
            currency=CHF,
            identifiers=SecurityIdentifiers(isin=ISIN("CH0012032048"), ticker=Ticker("ROG", "XSWX")),
            country="CH",
            exchange="XSWX",
            calendar="TARGET",
            sector="Health Care",
            industry="Pharmaceuticals",
            issuer_id="ROCHE",
        ),
        Fund(
            instrument_id="US-IVV",
            name="iShares Core S&P 500 ETF",
            currency=USD,
            identifiers=SecurityIdentifiers(isin=ISIN("US4642872000"), ticker=Ticker("IVV", "ARCX")),
            country="US",
            exchange="ARCX",
            expense_ratio=Decimal("0.0003"),
            benchmark_id="SPX",
        ),
        Fund(
            instrument_id="IE-IWDA",
            name="iShares Core MSCI World UCITS ETF",
            currency=USD,
            identifiers=SecurityIdentifiers(isin=ISIN("IE00B4L5Y983"), ticker=Ticker("IWDA", "XAMS")),
            country="IE",
            exchange="XAMS",
            calendar="TARGET",
            expense_ratio=Decimal("0.0020"),
            benchmark_id="MSCI-WORLD",
        ),
        Bond(
            instrument_id="US-T-2032",
            name="US Treasury 2.875% 15 May 2032",
            currency=USD,
            identifiers=SecurityIdentifiers(
                isin=ISIN("US91282CEF41"), cusip=CUSIP("91282CEF4"), ticker=Ticker("T2032")
            ),
            coupon=Decimal("0.02875"),
            issue_date=date(2022, 5, 16),
            maturity=date(2032, 5, 15),
            face_value=Decimal(1000),
            issuer_id="US-TREASURY",
        ),
        CashInstrument.for_currency("USD"),
        CashInstrument.for_currency("GBP"),
        CashInstrument.for_currency("EUR"),
    )


def demo_book() -> DemoBook:
    """The full demonstration book, deterministic so tests can assert on it."""
    client = Client(client_id="CL-0001", name="Aliyeva Family Office", domicile="AZ", tax_residence="GB")
    household = Household(household_id="HH-0001", name="Aliyeva Household", base_currency=USD)

    benchmarks = (
        Benchmark(benchmark_id="SPX", name="S&P 500", currency=USD, description="US large cap"),
        Benchmark(benchmark_id="MSCI-WORLD", name="MSCI World", currency=USD, description="Developed markets"),
        Benchmark(benchmark_id="AGG", name="Bloomberg US Aggregate", currency=USD, description="US investment grade"),
    )

    accounts = (
        Account(
            account_id="AC-0001",
            name="Aliyeva Taxable Brokerage",
            account_type=AccountType.TAXABLE,
            base_currency=USD,
            household_id="HH-0001",
            client_id="CL-0001",
            custodian="Northern Trust",
            opened=date(2024, 3, 1),
        ),
        Account(
            account_id="AC-0002",
            name="Aliyeva SIPP",
            account_type=AccountType.PENSION,
            base_currency=GBP,
            household_id="HH-0001",
            client_id="CL-0001",
            custodian="Northern Trust",
            opened=date(2024, 3, 1),
            calendar="XLON",
        ),
    )

    portfolios = (
        Portfolio(
            portfolio_id="PF-GLOBAL-EQ",
            name="Global Equity Core",
            base_currency=USD,
            account_id="AC-0001",
            benchmark_id="MSCI-WORLD",
            strategy="global-equity",
            inception=date(2024, 4, 1),
            policy=InvestmentPolicy(
                target_equity_weight=Decimal("0.95"),
                max_single_issuer_weight=Decimal("0.08"),
                max_cash_weight=Decimal("0.05"),
                tracking_error_budget=Decimal("0.03"),
            ),
        ),
        Portfolio(
            portfolio_id="PF-BALANCED",
            name="Balanced Pension",
            base_currency=GBP,
            account_id="AC-0002",
            benchmark_id="SPX",
            strategy="balanced",
            inception=date(2024, 4, 1),
            policy=InvestmentPolicy(
                target_equity_weight=Decimal("0.60"),
                max_single_issuer_weight=Decimal("0.05"),
                max_cash_weight=Decimal("0.10"),
            ),
        ),
    )

    transactions = (
        build_trade(
            transaction_id="TX-0001",
            portfolio_id="PF-GLOBAL-EQ",
            instrument_id="US-AAPL",
            trade_date=date(2024, 4, 3),
            quantity=1_200,
            price="169.65",
            currency=USD,
            fees="24.00",
        ),
        build_trade(
            transaction_id="TX-0002",
            portfolio_id="PF-GLOBAL-EQ",
            instrument_id="US-MSFT",
            trade_date=date(2024, 4, 3),
            quantity=650,
            price="420.45",
            currency=USD,
            fees="24.00",
        ),
        build_trade(
            transaction_id="TX-0003",
            portfolio_id="PF-GLOBAL-EQ",
            instrument_id="DE-BAYN",
            trade_date=date(2024, 6, 12),
            quantity=3_400,
            price="27.35",
            currency=EUR,
            fees="41.00",
        ),
        build_trade(
            transaction_id="TX-0004",
            portfolio_id="PF-GLOBAL-EQ",
            instrument_id="CH-ROG",
            trade_date=date(2024, 9, 18),
            quantity=420,
            price="268.10",
            currency=CHF,
            fees="52.00",
        ),
        build_trade(
            transaction_id="TX-0005",
            portfolio_id="PF-GLOBAL-EQ",
            instrument_id="US-AAPL",
            trade_date=date(2025, 2, 14),
            quantity=300,
            price="241.80",
            currency=USD,
            buy=False,
            fees="18.00",
            taxes="0",
        ),
        build_trade(
            transaction_id="TX-0006",
            portfolio_id="PF-BALANCED",
            instrument_id="GB-BAE",
            trade_date=date(2024, 4, 9),
            quantity=8_000,
            price="12.86",
            currency=GBP,
            fees="30.00",
            taxes="514.40",  # UK stamp duty reserve tax, 0.5%
        ),
        build_trade(
            transaction_id="TX-0007",
            portfolio_id="PF-BALANCED",
            instrument_id="IE-IWDA",
            trade_date=date(2024, 5, 7),
            quantity=1_500,
            price="88.42",
            currency=USD,
            fees="30.00",
        ),
        build_trade(
            transaction_id="TX-0008",
            portfolio_id="PF-BALANCED",
            instrument_id="US-T-2032",
            trade_date=date(2024, 7, 2),
            quantity=250,
            price="96.42",
            currency=USD,
            fees="15.00",
        ),
    )

    return DemoBook(
        clients=(client,),
        households=(household,),
        benchmarks=benchmarks,
        instruments=demo_instruments(),
        accounts=accounts,
        portfolios=portfolios,
        transactions=transactions,
    )
