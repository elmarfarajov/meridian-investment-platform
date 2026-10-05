"""The optimiser's tax ledger against the IRS's examples and against Day 3's book of record."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.accounting.tax import DEFAULT_RATES, TaxYearSummary
from meridian.optimisation.taxes import TaxAccount


# ---------------------------------------------------------------- the carryover, as the IRS and Day 3 compute it
def test_publication_550_the_deduction_uses_short_term_losses_first():
    account = TaxAccount()
    account.realise(date(2025, 3, 1), -2_000.0, long_term=False)
    account.realise(date(2025, 3, 1), -5_000.0, long_term=True)
    tax = account.close_year(2025)
    assert account.carried == pytest.approx((0.0, 4_000.0))  # $3,000 deducted: $2,000 short, $1,000 long
    assert tax == pytest.approx(-3_000.0 * float(DEFAULT_RATES.short_term))  # ordinary rate, no NIIT


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(2023, 2026), st.integers(-20_000, 20_000), st.booleans()),
        max_size=12,
    )
)
def test_the_optimiser_ledger_agrees_with_the_book_of_record(realisations):
    account = TaxAccount()
    for year, gain, long_term in realisations:
        account.realise(date(year, 6, 30), float(gain), long_term)
    carried = (Decimal(0), Decimal(0))
    for year in range(2023, 2027):
        gains = [(Decimal(g), lt) for y, g, lt in realisations if y == year]
        summary = TaxYearSummary(
            year=year,
            short_term_gains=sum((g for g, lt in gains if not lt and g > 0), Decimal(0)),
            short_term_losses=sum((g for g, lt in gains if not lt and g < 0), Decimal(0)),
            long_term_gains=sum((g for g, lt in gains if lt and g > 0), Decimal(0)),
            long_term_losses=sum((g for g, lt in gains if lt and g < 0), Decimal(0)),
            disallowed=Decimal(0),
            carryforward_in_short=carried[0],
            carryforward_in_long=carried[1],
        )
        tax = account.close_year(year)
        assert tax == pytest.approx(float(summary.estimated_tax()), abs=1e-6)
        carried = summary.carryforward()
        assert account.carried == pytest.approx((float(carried[0]), float(carried[1])), abs=1e-6)


def test_a_long_term_loss_larger_than_a_short_term_gain_carries_as_long_term():
    account = TaxAccount()
    account.realise(date(2025, 3, 1), 1_000.0, long_term=False)
    account.realise(date(2025, 3, 1), -9_000.0, long_term=True)
    account.close_year(2025)
    assert account.carried == pytest.approx((0.0, 5_000.0))  # Schedule D line 16: an $8,000 long-term loss
