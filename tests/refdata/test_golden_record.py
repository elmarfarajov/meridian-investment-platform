"""Golden records: validated, normalised, ranked, with lineage and the conflicts kept."""

from __future__ import annotations

import pytest

from meridian.core.exceptions import ValidationError
from meridian.refdata import (
    SurvivorshipPolicy,
    VendorRecord,
    build_golden_record,
    build_security_master,
    demo_policy,
    demo_vendor_records,
    normalise,
)


@pytest.fixture(scope="module")
def master():
    return build_security_master(demo_vendor_records(), demo_policy())


def test_every_field_says_where_it_came_from(master):
    apple = master["US-AAPL"]
    assert set(apple.lineage) == set(apple.values)
    assert apple.lineage["isin"] == "exchange"
    assert apple.lineage["sector"] == "vendor-b"


def test_an_identifier_that_fails_its_check_digit_cannot_win(master):
    apple = master["US-AAPL"]
    assert apple.values["isin"] == "US0378331005"
    (rejected,) = [item for item in apple.rejected if item.field == "isin"]
    assert rejected.source == "evaluated"
    assert "check digit" in rejected.reason
    bae = master["GB-BAE"]
    assert bae.values["sedol"] == "0263494"


def test_values_are_normalised_before_they_are_compared(master):
    bond = master["US-T-2032"]
    assert bond.values["coupon"] == "2.875"  # "2.875" and "2.87500" are one value
    assert not [item for item in bond.conflicts if item.field == "coupon"]
    apple = master["US-AAPL"]
    assert apple.values["sector"] == "Information Technology"  # "Information Tech" and "Technology" map to it
    assert apple.values["shares_outstanding"] == "14840390000"
    assert apple.values["currency"] == "USD"


def test_real_disagreements_are_kept_even_when_a_winner_is_chosen(master):
    bond = master["US-T-2032"]
    (issue,) = [item for item in bond.conflicts if item.field == "issue_date"]
    assert issue.chosen_source == "vendor-b"
    assert dict(issue.values) == {"vendor-b": "2022-05-16", "evaluated": "2022-05-15"}
    bae = master["GB-BAE"]
    (currency,) = [item for item in bae.conflicts if item.field == "currency"]
    assert "GBX" in currency.describe()  # pence against pounds: the classic unit trap
    assert bae.values["currency"] == "GBP"


def test_field_level_precedence_overrides_the_default_ranking(master):
    bond = master["US-T-2032"]
    assert bond.lineage["coupon"] == "evaluated"
    assert bond.lineage["name"] == "vendor-b"
    assert bond.lineage["isin"] == "exchange"


def test_source_share_and_completeness(master):
    apple = master["US-AAPL"]
    assert sum(apple.source_share().values()) == len(apple.values)
    assert 0 < apple.completeness <= 1


def test_an_unlisted_source_ranks_last():
    policy = SurvivorshipPolicy(default_ranking=("a",))
    record = build_golden_record(
        [VendorRecord("z", "X", {"name": "From Z"}), VendorRecord("a", "X", {"name": "From A"})], policy
    )
    assert record.values["name"] == "From A"
    assert policy.rank("name", "z") == 1


def test_records_for_different_instruments_cannot_be_merged():
    with pytest.raises(ValidationError, match="more than one instrument"):
        build_golden_record(
            [VendorRecord("a", "X", {}), VendorRecord("b", "Y", {})], SurvivorshipPolicy(default_ranking=("a",))
        )
    with pytest.raises(ValidationError):
        build_golden_record([], SurvivorshipPolicy(default_ranking=("a",)))


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("coupon", "4.12500", "4.125"),
        ("shares_outstanding", "1,000", "1000"),
        ("maturity", "2032-05-15", "2032-05-15"),
        ("country", "gb", "GB"),
        ("name", "  Apple   Inc  ", "Apple Inc"),
        ("sector", "Banks", "Financials"),
        ("sector", "Utilities", "Utilities"),
    ],
)
def test_normalise(field: str, raw: str, expected: str):
    assert normalise(field, raw) == expected


@pytest.mark.parametrize(
    ("field", "raw"), [("coupon", "four"), ("maturity", "15/05/2032"), ("name", " "), ("isin", "XX")]
)
def test_normalise_rejects(field: str, raw: str):
    with pytest.raises(ValidationError):
        normalise(field, raw)
