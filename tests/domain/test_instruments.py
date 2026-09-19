from datetime import date
from decimal import Decimal

import pytest

from meridian.core import ISIN, AssetClass, DayCountConvention, InstrumentType, SecurityStatus, Ticker, ValidationError
from meridian.core.identifiers import CUSIP
from meridian.domain import (
    Bond,
    CashInstrument,
    Equity,
    Fund,
    Instrument,
    SecurityIdentifiers,
    instrument_price_scale,
)

APPLE_IDS = SecurityIdentifiers(isin=ISIN("US0378331005"), cusip=CUSIP("037833100"), ticker=Ticker("AAPL", "XNAS"))


def test_identifier_set_needs_at_least_one_identifier():
    with pytest.raises(ValidationError):
        SecurityIdentifiers()


def test_identifier_set_prefers_isin_then_figi():
    assert APPLE_IDS.primary == "US0378331005"
    assert SecurityIdentifiers(ticker=Ticker("VOD", "XLON")).primary == "VOD.XLON"
    assert APPLE_IDS.as_dict() == {
        "isin": "US0378331005",
        "cusip": "037833100",
        "ticker": "AAPL.XNAS",
    }


def test_equity_reference_data():
    apple = Equity(
        instrument_id="AAPL",
        name="Apple Inc",
        currency="USD",
        identifiers=APPLE_IDS,
        country="US",
        exchange="XNAS",
        sector="Information Technology",
        shares_outstanding=Decimal("15000000000"),
    )
    assert apple.asset_class is AssetClass.EQUITY
    assert apple.is_tradable
    assert instrument_price_scale(apple) == Decimal(1)
    assert str(apple) == "AAPL (Apple Inc)"


def test_instrument_validation():
    with pytest.raises(ValidationError):
        Equity(instrument_id=" ", name="Blank", currency="USD", identifiers=APPLE_IDS)
    with pytest.raises(ValidationError):
        Equity(instrument_id="X", name="", currency="USD", identifiers=APPLE_IDS)
    with pytest.raises(ValidationError):
        Equity(instrument_id="X", name="Bad country", currency="USD", identifiers=APPLE_IDS, country="USA")
    with pytest.raises(ValidationError):
        Equity(instrument_id="X", name="Bad shares", currency="USD", identifiers=APPLE_IDS, shares_outstanding=0)
    with pytest.raises(ValidationError):
        Instrument(
            instrument_id="X",
            name="Bad multiplier",
            instrument_type=InstrumentType.COMMON_STOCK,
            currency="USD",
            identifiers=APPLE_IDS,
            multiplier=0,
        )


def test_equity_type_must_be_an_equity():
    with pytest.raises(ValidationError):
        Equity(
            instrument_id="X",
            name="Not an equity",
            currency="USD",
            identifiers=APPLE_IDS,
            instrument_type=InstrumentType.CORPORATE_BOND,
        )


def test_fund_expense_ratio_is_a_fraction():
    etf = Fund(
        instrument_id="IVV",
        name="iShares Core S&P 500 ETF",
        currency="USD",
        identifiers=SecurityIdentifiers(ticker=Ticker("IVV")),
        expense_ratio="0.0003",
        benchmark_id="SPX",
    )
    assert etf.expense_ratio == Decimal("0.0003")
    assert etf.asset_class is AssetClass.MULTI_ASSET
    with pytest.raises(ValidationError):
        Fund(
            instrument_id="BAD",
            name="Too expensive",
            currency="USD",
            identifiers=SecurityIdentifiers(ticker=Ticker("BAD")),
            expense_ratio="1.5",
        )


def test_bond_terms_and_price_scale():
    bond = Bond(
        instrument_id="US912828ZT01",
        name="US Treasury 2.5% 2032",
        currency="USD",
        identifiers=SecurityIdentifiers(isin=ISIN("US0378331005")),
        instrument_type=InstrumentType.GOVERNMENT_BOND,
        coupon="0.025",
        issue_date=date(2022, 5, 15),
        maturity=date(2032, 5, 15),
        face_value=1000,
        day_count=DayCountConvention.ACT_ACT_ISDA,
    )
    assert bond.asset_class is AssetClass.FIXED_INCOME
    assert not bond.is_matured(date(2030, 1, 1))
    assert bond.is_matured(date(2032, 5, 15))
    # A bond quoted at 98.5 per 100 of face on 1,000 face scales by 10
    assert instrument_price_scale(bond) == Decimal(10)


def test_bond_validation():
    ids = SecurityIdentifiers(ticker=Ticker("BND"))
    with pytest.raises(ValidationError):
        Bond(instrument_id="B", name="Negative coupon", currency="USD", identifiers=ids, coupon="-0.01")
    with pytest.raises(ValidationError):
        Bond(instrument_id="B", name="No face", currency="USD", identifiers=ids, face_value=0)
    with pytest.raises(ValidationError):
        Bond(
            instrument_id="B",
            name="Backwards",
            currency="USD",
            identifiers=ids,
            issue_date=date(2030, 1, 1),
            maturity=date(2029, 1, 1),
        )


def test_cash_instruments_are_built_per_currency():
    cash = CashInstrument.for_currency("EUR")
    assert cash.instrument_id == "CASH.EUR"
    assert cash.asset_class is AssetClass.CASH
    assert cash.status is SecurityStatus.ACTIVE
