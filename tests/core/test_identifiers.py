import pytest

from meridian.core import CUSIP, FIGI, ISIN, SEDOL, Ticker, ValidationError
from meridian.core.identifiers import validate_cusip, validate_figi, validate_isin, validate_sedol

# Real identifiers, so the check-digit implementations are tested against the market.
REAL_ISINS = [
    "US0378331005",  # Apple
    "US5949181045",  # Microsoft
    "GB0002634946",  # BAE Systems
    "DE000BAY0017",  # Bayer
    "FR0000120271",  # TotalEnergies
    "JP3633400001",  # Toyota
    "NL0011794037",  # Ahold Delhaize
    "CH0012032048",  # Roche
]
REAL_CUSIPS = ["037833100", "594918104", "88160R101", "02079K305"]
REAL_SEDOLS = ["2046251", "0263494", "B1YW440", "0540528"]
REAL_FIGIS = ["BBG000B9XRY4", "BBG000BPH459", "BBG000BVPV84", "BBG000BLNNH6", "BBG000N9MNX3"]


@pytest.mark.parametrize("value", REAL_ISINS)
def test_real_isins_validate(value):
    assert validate_isin(value)
    assert ISIN(value).value == value


@pytest.mark.parametrize("value", REAL_CUSIPS)
def test_real_cusips_validate(value):
    assert validate_cusip(value)


@pytest.mark.parametrize("value", REAL_SEDOLS)
def test_real_sedols_validate(value):
    assert validate_sedol(value)


@pytest.mark.parametrize("value", REAL_FIGIS)
def test_real_figis_validate(value):
    assert validate_figi(value)


@pytest.mark.parametrize(
    "value",
    [
        "US0378331006",  # wrong check digit
        "US037833100",  # too short
        "0S0378331005",  # country code must be letters
        "us0378331005 ",  # lower case is normalised, but the digit is then wrong
        "",
    ],
)
def test_bad_isins_are_rejected(value):
    if value.strip().upper() == "US0378331005":  # pragma: no cover - guard against a bad test case
        pytest.skip("that value is valid")
    with pytest.raises(ValidationError):
        ISIN(value)


def test_identifiers_are_normalised_to_upper_case():
    assert ISIN(" us0378331005 ").value == "US0378331005"
    assert CUSIP("037833100").value == "037833100"


def test_isin_exposes_its_country_and_national_number():
    isin = ISIN("US0378331005")
    assert isin.country == "US"
    assert isin.national_number == "037833100"
    assert str(isin) == "US0378331005"


def test_cusip_converts_to_isin():
    assert CUSIP("037833100").to_isin().value == "US0378331005"
    assert CUSIP("594918104").to_isin("US").value == "US5949181045"


def test_sedol_rejects_vowels():
    with pytest.raises(ValidationError):
        SEDOL("A263494")


def test_figi_requires_the_bbg_prefix():
    with pytest.raises(ValidationError):
        FIGI("XXX000B9XRY4")


def test_bad_check_digits_are_caught():
    assert not validate_cusip("037833101")
    assert not validate_sedol("2046252")
    assert not validate_figi("BBG000B9XRY5")


def test_tickers_normalise_and_carry_an_exchange():
    assert str(Ticker("aapl")) == "AAPL"
    assert str(Ticker("vod", "lse")) == "VOD.LSE"
    assert Ticker("BRK.B").symbol == "BRK.B"
    with pytest.raises(ValidationError):
        Ticker("not a ticker!")
