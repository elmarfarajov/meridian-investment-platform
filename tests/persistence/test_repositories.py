from datetime import date
from decimal import Decimal

import pytest

from meridian.core import EntityNotFoundError
from meridian.domain import Bond, Equity, Fund, TaxLot
from meridian.persistence import UnitOfWork, seed_reference_data


@pytest.fixture
def seeded(unit_of_work: UnitOfWork, instruments, benchmark, client, household, account, portfolio) -> UnitOfWork:
    seed_reference_data(
        unit_of_work,
        instruments=instruments,
        benchmarks=[benchmark],
        clients=[client],
        households=[household],
        accounts=[account],
        portfolios=[portfolio],
    )
    return unit_of_work


def test_instrument_round_trip_preserves_type_and_identifiers(seeded: UnitOfWork):
    apple = seeded.instruments.get("AAPL")
    assert isinstance(apple, Equity)
    assert apple.identifiers.isin is not None and str(apple.identifiers.isin) == "US0378331005"
    assert apple.identifiers.ticker is not None and apple.identifiers.ticker.exchange == "XNAS"
    assert apple.sector == "Information Technology"
    assert apple.currency.code == "USD"

    etf = seeded.instruments.get("IVV")
    assert isinstance(etf, Fund)
    assert etf.expense_ratio == Decimal("0.0003")

    bond = seeded.instruments.get("T-2032")
    assert isinstance(bond, Bond)
    assert bond.maturity == date(2032, 5, 15)
    assert bond.face_value == Decimal(1000)


def test_instrument_lookups(seeded: UnitOfWork):
    assert seeded.instruments.by_isin("US0378331005").instrument_id == "AAPL"
    assert seeded.instruments.by_isin("XX0000000000") is None
    assert [item.instrument_id for item in seeded.instruments.by_ticker("MSFT")] == ["MSFT"]
    assert seeded.instruments.find("NOPE") is None
    with pytest.raises(EntityNotFoundError):
        seeded.instruments.get("NOPE")


def test_instrument_filters(seeded: UnitOfWork):
    equities = seeded.instruments.list(asset_class="equity")
    assert {item.instrument_id for item in equities} == {"AAPL", "MSFT", "SAP"}
    assert [item.instrument_id for item in seeded.instruments.list(currency="EUR")] == ["SAP"]
    assert len(seeded.instruments.list(sector="Information Technology")) == 3
    assert len(seeded.instruments.list(limit=2)) == 2
    assert seeded.instruments.count() == 5


def test_adding_an_instrument_twice_updates_rather_than_duplicates(seeded: UnitOfWork, instruments):
    renamed = Equity(
        instrument_id="AAPL",
        name="Apple Inc. (updated)",
        currency="USD",
        identifiers=instruments[0].identifiers,
        sector="Information Technology",
    )
    seeded.instruments.add(renamed)
    seeded.flush()
    assert seeded.instruments.count() == 5
    assert seeded.instruments.get("AAPL").name == "Apple Inc. (updated)"


def test_portfolio_and_account_hierarchy(seeded: UnitOfWork):
    portfolio = seeded.portfolios.get("P1")
    assert portfolio.benchmark_id == "SPX"
    assert portfolio.policy.target_equity_weight == Decimal("0.6")
    assert [item.portfolio_id for item in seeded.portfolios.list(account_id="A1")] == ["P1"]
    assert [item.portfolio_id for item in seeded.portfolios.for_household("H1")] == ["P1"]
    assert seeded.accounts.get("A1").is_taxable
    assert [item.account_id for item in seeded.accounts.list(household_id="H1")] == ["A1"]
    assert seeded.households.get("H1").name == "Karimov Household"
    assert seeded.clients.get("C1").tax_residence == "GB"
    assert [item.benchmark_id for item in seeded.benchmarks.list()] == ["SPX"]


def test_transactions_are_returned_in_trade_date_order(seeded: UnitOfWork, transactions):
    seeded.transactions.add_all(transactions)
    seeded.flush()
    stored = seeded.transactions.for_portfolio("P1")
    assert [item.transaction_id for item in stored] == ["T1", "T2", "T3"]
    assert stored[0].settlement_date == date(2026, 1, 6)
    assert stored[0].cash_impact.amount == Decimal("-18554.95")
    assert seeded.transactions.count("P1") == 3


def test_transaction_filters(seeded: UnitOfWork, transactions):
    seeded.transactions.add_all(transactions)
    seeded.flush()
    assert len(seeded.transactions.for_portfolio("P1", instrument_id="AAPL")) == 2
    assert len(seeded.transactions.for_portfolio("P1", start=date(2026, 2, 1))) == 2
    assert len(seeded.transactions.for_portfolio("P1", end=date(2026, 1, 31))) == 1
    with pytest.raises(EntityNotFoundError):
        seeded.transactions.get("NOPE")


def test_tax_lots_open_and_close(seeded: UnitOfWork):
    lot = TaxLot(
        lot_id="L1",
        instrument_id="AAPL",
        open_date=date(2026, 1, 5),
        quantity=Decimal(100),
        cost_per_unit=Decimal("185.55"),
        currency="USD",
        transaction_id="T1",
    )
    seeded.tax_lots.add(lot, "P1")
    seeded.flush()
    assert [item.lot_id for item in seeded.tax_lots.open_lots("P1")] == ["L1"]
    assert [item.lot_id for item in seeded.tax_lots.open_lots("P1", "MSFT")] == []
    seeded.tax_lots.close("L1", date(2026, 6, 15))
    seeded.flush()
    assert seeded.tax_lots.open_lots("P1") == []
    with pytest.raises(EntityNotFoundError):
        seeded.tax_lots.close("NOPE", date(2026, 6, 15))


def test_prices_and_latest_mark(seeded: UnitOfWork):
    for day, price in [(date(2026, 9, 14), "225.10"), (date(2026, 9, 15), "227.40"), (date(2026, 9, 17), "224.85")]:
        seeded.prices.upsert("AAPL", day, Decimal(price), "USD", source="test")
    seeded.flush()
    series = seeded.prices.series("AAPL")
    assert [day for day, _ in series] == [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 17)]
    # A stale mark is used when the valuation date has no price of its own
    assert seeded.prices.latest("AAPL", date(2026, 9, 16)) == Decimal("227.40")
    assert seeded.prices.latest("AAPL", date(2026, 9, 18)) == Decimal("224.85")
    assert seeded.prices.latest("AAPL", date(2026, 9, 1)) is None
    assert len(seeded.prices.series("AAPL", start=date(2026, 9, 15))) == 2


def test_fx_rates_round_trip(seeded: UnitOfWork):
    seeded.fx_rates.upsert("EUR", "USD", date(2026, 9, 18), Decimal("1.0850"), source="test")
    seeded.fx_rates.upsert("GBP", "USD", date(2026, 9, 18), Decimal("1.2700"))
    seeded.flush()
    rates = dict(((base, quote), rate) for base, quote, rate in seeded.fx_rates.on(date(2026, 9, 18)))
    assert rates[("EUR", "USD")] == Decimal("1.0850")
    assert len(rates) == 2


def test_seed_reports_what_it_wrote(
    unit_of_work: UnitOfWork, instruments, benchmark, portfolio, account, household, client
):
    counts = seed_reference_data(
        unit_of_work,
        instruments=instruments,
        benchmarks=[benchmark],
        clients=[client],
        households=[household],
        accounts=[account],
        portfolios=[portfolio],
    )
    assert counts == {
        "clients": 1,
        "households": 1,
        "benchmarks": 1,
        "instruments": 5,
        "accounts": 1,
        "portfolios": 1,
    }


def test_deleting_an_instrument(seeded: UnitOfWork):
    seeded.instruments.delete("SAP")
    seeded.flush()
    assert seeded.instruments.find("SAP") is None
