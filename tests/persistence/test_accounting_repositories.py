"""The book of record in the database: the journal, lots, realised gains, valuations and breaks."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from meridian.accounting.chart_of_accounts import Accounts
from meridian.core import ValidationError
from meridian.persistence import UnitOfWork
from meridian.services.accounting_run import persist_book, run_demo_accounting, tie_out
from meridian.services.demo_accounting import PORTFOLIO_ID, build_demo_accounting


@pytest.fixture(scope="module")
def demo():
    return build_demo_accounting()


@pytest.fixture
def stored(unit_of_work: UnitOfWork, demo):
    result = run_demo_accounting(demo, unit_of_work)
    unit_of_work.commit()
    return result


def test_the_run_writes_everything_and_passes_its_controls(stored, demo):
    assert stored.passed
    assert stored.entries == len(demo.book.ledger)
    assert stored.realised_lots == len(demo.book.realised)
    assert stored.valuations == len(demo.valuations)
    assert stored.breaks > 0
    assert stored.nav == demo.valuations[-1].nav
    labels = [label for label, _ in stored.summary_rows()]
    assert "net asset value" in labels and "check: trial balance balances" in labels


def test_the_database_trial_balance_equals_the_ledger_account_by_account(stored, unit_of_work, demo):
    for as_of in (date(2024, 12, 31), date(2025, 6, 30), None):
        in_sql = unit_of_work.ledger.trial_balance(PORTFOLIO_ID, as_of)
        in_memory = demo.book.ledger.trial_balance(as_of)
        assert {line.account.code: line.balance for line in in_sql.lines} == pytest.approx(
            {line.account.code: line.balance for line in in_memory.lines}, abs=Decimal("1e-6")
        )
        assert in_sql.is_balanced or abs(in_sql.difference) < Decimal("1e-6")


def test_entries_and_realised_lots_round_trip(stored, unit_of_work, demo):
    entries = unit_of_work.ledger.entries(PORTFOLIO_ID)
    assert len(entries) == unit_of_work.ledger.count(PORTFOLIO_ID) == len(demo.book.ledger)
    first = demo.book.ledger.entries[0]
    (loaded,) = [item for item in entries if item.entry_id == first.entry_id]
    assert loaded.postings == first.postings
    assert unit_of_work.ledger.entries(PORTFOLIO_ID, source_id=first.source_id)
    realised = unit_of_work.realised.for_portfolio(PORTFOLIO_ID)
    assert [item.reportable_gain for item in realised] == pytest.approx(
        [
            item.reportable_gain
            for item in sorted(demo.book.realised, key=lambda x: (x.close_date, x.disposal_id, x.lot_id))
        ],
        abs=Decimal("1e-6"),
    )
    assert unit_of_work.realised.for_portfolio(PORTFOLIO_ID, year=2025)
    assert unit_of_work.realised.for_portfolio(PORTFOLIO_ID, instrument_id="DE-BAYN")


def test_the_sub_ledger_in_sql_ties_to_the_stored_lots(stored, unit_of_work):
    by_instrument = unit_of_work.ledger.balance_by_instrument(PORTFOLIO_ID, Accounts.INVESTMENTS.code)
    lots = unit_of_work.tax_lots.open_lots(PORTFOLIO_ID)
    assert {lot.instrument_id for lot in lots} == set(by_instrument)
    for instrument_id, balance in by_instrument.items():
        cost = sum((lot.base_cost for lot in lots if lot.instrument_id == instrument_id), Decimal(0))
        assert abs(balance - cost) < Decimal("1e-6"), instrument_id
    # the wash sale replacements were sold later: the disallowed loss reached the realised lots, tacked
    carried = [item for item in unit_of_work.realised.for_portfolio(PORTFOLIO_ID) if item.wash_sale_basis]
    assert carried and all(item.holding_start < item.open_date for item in carried)
    assert sum(item.wash_sale_basis for item in carried) > Decimal(80000)


def test_valuations_and_breaks_are_queryable(stored, unit_of_work, demo):
    series = unit_of_work.valuations.nav_series(PORTFOLIO_ID)
    assert len(series) == len(demo.valuations)
    assert series[-1][1] == pytest.approx(demo.valuations[-1].nav, abs=Decimal("1e-6"))
    assert unit_of_work.valuations.nav_series(PORTFOLIO_ID, date(2025, 1, 1), date(2025, 1, 31))
    latest = unit_of_work.valuations.latest_date(PORTFOLIO_ID)
    assert latest == demo.valuations[-1].day
    assert {row.instrument_id for row in unit_of_work.valuations.positions_on(PORTFOLIO_ID, latest)}
    counts = unit_of_work.reconciliation.counts_by_cause(PORTFOLIO_ID)
    assert "unexplained" not in counts and sum(counts.values()) == stored.breaks
    first_day = unit_of_work.reconciliation.breaks(PORTFOLIO_ID)[0].as_of
    assert unit_of_work.reconciliation.breaks(PORTFOLIO_ID, first_day)


def test_persisting_again_replaces_rather_than_duplicates(stored, unit_of_work, demo):
    again = run_demo_accounting(demo, unit_of_work)
    unit_of_work.commit()
    assert again.entries == stored.entries
    assert unit_of_work.ledger.count(PORTFOLIO_ID) == stored.entries
    assert len(unit_of_work.realised.for_portfolio(PORTFOLIO_ID)) == stored.realised_lots


def test_a_book_that_fails_its_controls_writes_nothing(unit_of_work, demo):
    book = demo.book
    broken_lots = dict(book.open_lots)
    instrument, lots = next(iter(broken_lots.items()))
    broken_lots[instrument] = (replace(lots[0], cost_per_unit=lots[0].cost_per_unit + 1), *lots[1:])
    broken = replace(book, open_lots=broken_lots)
    assert not tie_out(broken)["sub-ledger ties to lots"]
    with pytest.raises(ValidationError, match="nothing written"):
        persist_book(unit_of_work, broken, demo.valuations[:2])


def test_the_dry_run_reports_without_a_database(demo):
    result = run_demo_accounting(demo)
    assert result.passed and result.entries == len(demo.book.ledger)
