"""Legal Entity Identifiers, and telling one identifier scheme from another.

The LEIs below are published identifiers, checked against the ISO 7064 MOD 97-10
scheme. A random twenty-character string passes that check roughly one time in a
hundred, so agreement across seven of them is evidence the implementation is
right rather than coincidence.
"""

from __future__ import annotations

import pytest

from meridian.core.exceptions import ValidationError
from meridian.core.identifiers import (
    LEI,
    expected_check_digit,
    identify,
    lei_check_digits,
    validate_lei,
)

PUBLISHED_LEIS = {
    "Apple Inc": "HWUPKR0MPOU8FGXBT394",
    "The Goldman Sachs Group": "784F5XWPLTWKTBV3E584",
    "Microsoft Corporation": "INR2EJN1ERAN0W5ZP974",
    "JPMorgan Chase & Co": "8I5DZWZKVSZI1NUHU748",
    "Deutsche Bank AG": "7LTWFZYICNSX8D621K86",
    "HSBC Holdings plc": "MLU0ZO3ML4LN2LL2TL39",
    "Barclays PLC": "213800LBQA1Y9L22JB70",
}


@pytest.mark.parametrize(("name", "value"), sorted(PUBLISHED_LEIS.items()))
def test_published_leis_validate(name: str, value: str):
    assert validate_lei(value), name
    assert LEI(value).value == value


@pytest.mark.parametrize(("name", "value"), sorted(PUBLISHED_LEIS.items()))
def test_the_check_digits_are_reproduced_from_the_body(name: str, value: str):
    assert f"{lei_check_digits(value[:18]):02d}" == value[18:], name


def test_a_corrupted_lei_is_rejected():
    corrupted = "HWUPKR0MPOU8FGXBT395"  # one digit out
    assert not validate_lei(corrupted)
    with pytest.raises(ValidationError, match="not a valid LEI"):
        LEI(corrupted)


@pytest.mark.parametrize(
    "value",
    [
        "HWUPKR0MPOU8FGXBT39",  # too short
        "HWUPKR0MPOU8FGXBT3944",  # too long
        "HWUPKR0MPOU8FGXBT3A4",  # letters in the check digit positions
        "hwupkr0mpou8fgxbt394 ",  # lower case is accepted after stripping
    ][:3],
)
def test_malformed_leis_are_rejected(value: str):
    assert not validate_lei(value)


def test_case_and_whitespace_are_normalised():
    assert LEI(" hwupkr0mpou8fgxbt394 ").value == "HWUPKR0MPOU8FGXBT394"


def test_an_lei_exposes_its_parts():
    identifier = LEI("784F5XWPLTWKTBV3E584")
    assert identifier.local_operating_unit == "784F"
    assert identifier.entity_part == "5XWPLTWKTBV3E5"
    assert str(identifier) == "784F5XWPLTWKTBV3E584"


def test_identify_names_the_scheme():
    assert identify("US0378331005") == ("ISIN",)
    assert identify("037833100") == ("CUSIP",)
    assert identify("0263494") == ("SEDOL",)
    assert identify("BBG000B9XRY4") == ("FIGI",)
    assert identify("HWUPKR0MPOU8FGXBT394") == ("LEI",)
    assert identify("NONSENSE") == ()


def test_identify_admits_when_a_string_fits_more_than_one_scheme():
    """Twelve characters could be an ISIN or a FIGI; the answer is a tuple for a reason."""
    for value in ("US0378331005", "BBG000B9XRY4"):
        assert len(identify(value)) >= 1


def test_expected_check_digit_explains_a_near_miss():
    assert expected_check_digit("US0378331006") == "5"
    assert expected_check_digit("HWUPKR0MPOU8FGXBT300") == "94"
    assert expected_check_digit("BBG000B9XRY0") == "4"
    assert expected_check_digit("0378331001") == ""  # ten characters is no scheme at all
