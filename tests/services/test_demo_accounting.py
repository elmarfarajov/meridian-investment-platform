"""The demonstration book of record: two and a half years, checked end to end."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from meridian.accounting.chart_of_accounts import Accounts
from meridian.accounting.reconciliation import BreakCause
from meridian.core.enums import TransactionType
from meridian.services.demo_accounting import (
    AMENDED_PRICE_NOTE,
    BOND_ID,
    PORTFOLIO_ID,
    TARGET_WEIGHTS,
    DemoAccounting,
    build_demo_accounting,
    demo_account,
    treasury_prices,
)
from meridian.services.demo_market import DEMO_END, DEMO_START

TOLERANCE = Decimal("1e-12")


@pytest.fixture(scope="module")
def demo() -> DemoAccounting:
    return build_demo_accounting()


def test_the_history_has_every_kind_of_event(demo: DemoAccounting):
    kinds = Counter(item.transaction_type for item in demo.transactions)
    assert kinds[TransactionType.BUY] >= 25 and kinds[TransactionType.SELL] >= 12
    assert kinds[TransactionType.FX] >= 10 and kinds[TransactionType.FEE] >= 12
    assert kinds[TransactionType.DEPOSIT] == 2 and kinds[TransactionType.WITHDRAWAL] == 1
    assert kinds[TransactionType.TRANSFER_IN] == 1
    assert {item.portfolio_id for item in demo.transactions} == {PORTFOLIO_ID}
    assert set(TARGET_WEIGHTS) <= {item.instrument_id for item in demo.transactions if item.instrument_id}
    assert sum(TARGET_WEIGHTS.values()) < 1
    assert demo_account().is_taxable


def test_the_book_balances_and_the_ledger_ties_to_the_lots(demo: DemoAccounting):
    book = demo.book
    assert book.ledger.trial_balance().is_balanced
    for month in range(1, 13):
        assert book.ledger.trial_balance(date(2025, month, 28)).is_balanced
    # the investment sub-ledger equals the open lots at historical cost, instrument by instrument
    by_instrument = book.ledger.instrument_balances(Accounts.INVESTMENTS)
    for instrument_id, lots in book.open_lots.items():
        at_cost = sum((lot.base_cost for lot in lots), Decimal(0))
        assert abs(by_instrument.get(instrument_id, Decimal(0)) - at_cost) < Decimal("1e-8"), instrument_id
    # and the cash account equals the settled cash in the snapshots, currency by currency
    last = book.snapshot_on(DEMO_END)
    for currency, amount in book.ledger.local_balances(Accounts.CASH).items():
        assert last.cash(currency) == amount


def test_cash_is_never_overdrawn(demo: DemoAccounting):
    for valuation in demo.valuations:
        for line in valuation.cash:
            assert line.cash >= 0, (valuation.day, line.currency)


def test_every_day_is_priced_and_the_bridge_explains_every_cent(demo: DemoAccounting):
    assert all(not valuation.missing for valuation in demo.valuations)
    assert len(demo.valuations) > 600
    assert all(abs(step.residual) < TOLERANCE for step in demo.daily_bridges)
    whole = demo.bridge(demo.valuation_days[0], demo.valuation_days[-1])
    assert abs(whole.residual) < TOLERANCE
    # five million in, half a million more, a quarter of a million out, and Apple shares transferred in at market
    assert Decimal(5_250_000) < whole.flows + whole.opening < Decimal(5_350_000)
    assert whole.opening == demo.valuations[0].nav
    assert whole.closing == demo.valuations[-1].nav
    assert whole.income > 0 and whole.costs < 0
    with pytest.raises(ValueError, match="no valuation days"):
        demo.bridge(date(2030, 1, 1), date(2030, 2, 1))


def test_the_transfer_in_is_long_term_from_the_day_it_arrives(demo: DemoAccounting):
    transferred = [lot for lot in demo.book.lots_on(date(2024, 5, 15), "US-AAPL") if lot.lot_id == "TIN-0001"]
    (lot,) = transferred
    assert lot.holding_start == date(2021, 3, 10)
    assert lot.is_long_term(date(2024, 5, 15))


def test_one_harvest_is_a_wash_sale_and_the_other_is_not(demo: DemoAccounting):
    washes = demo.book.wash_sales
    assert washes and all(match.instrument_id == "DE-BAYN" for match in washes)
    assert sum(match.disallowed for match in washes) > Decimal(50000)
    harvested = [
        item for item in demo.book.realised if item.disposal_id.startswith("TLH") and item.instrument_id == "US-JNJ"
    ]
    assert harvested and all(item.is_loss and item.disallowed_loss == 0 for item in harvested)
    assert any(year.disallowed > 0 for year in demo.us_tax_years)


def test_the_split_quadruples_the_holding(demo: DemoAccounting):
    before = demo.book.snapshot_on(date(2025, 6, 9)).quantity("DEMO-SPLIT")
    after = demo.book.snapshot_on(date(2025, 6, 10)).quantity("DEMO-SPLIT")
    assert after == before * 4


def test_german_and_swiss_withholding_is_partly_reclaimable(demo: DemoAccounting):
    reclaimable = demo.book.ledger.local_balances(Accounts.TAX_RECLAIMABLE)
    assert set(reclaimable) == {"CHF", "EUR"}
    assert all(amount > 0 for amount in reclaimable.values())


def test_the_corrected_price_is_a_restatement_and_the_failed_settlement_is_visible(demo: DemoAccounting):
    (correction,) = demo.blotter.corrections(datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert correction.reason == AMENDED_PRICE_NOTE
    evening = correction.recorded_at.replace(hour=0)
    before = demo.engine.run(demo.blotter.as_known_at(evening), demo.market.actions, until=DEMO_END)
    assert before.ledger.balance(Accounts.INVESTMENTS) != demo.book.ledger.balance(Accounts.INVESTMENTS)
    (fail,) = demo.blotter.fails()
    assert (fail.actual - fail.contractual).days >= 3
    payable = demo.book.snapshot_on(fail.contractual).balance(Accounts.PURCHASES_PAYABLE.code, "CHF")
    assert payable < 0  # still owed while the trade fails


def test_both_tax_codes_are_computed_and_they_disagree(demo: DemoAccounting):
    us = {item.year: item.net for item in demo.us_tax_years}
    uk = {item.tax_year: item.net for item in demo.uk_matching.by_tax_year()}
    assert set(us) == {2024, 2025, 2026}
    assert set(uk) >= {"2024/25", "2025/26"}
    assert demo.uk_matching.pools
    assert us[2025] != uk["2025/26"]


def test_reconciliation_on_the_demonstration_book(demo: DemoAccounting):
    days = demo.reconciliation_days()
    assert all(not demo.reconciler.reconcile(demo.custodian.clean_statement(day)).breaks for day in days)
    register, score = demo.reconciliation
    assert score.recall == 1.0 and score.precision == 1.0
    assert len({item.cause for item in demo.planted_breaks}) >= 6
    assert BreakCause.UNEXPLAINED not in {record.cause for record in register.records}


def test_the_treasury_prices_are_plausible_and_deterministic(demo: DemoAccounting):
    bond = demo.instruments[BOND_ID]
    series = treasury_prices(bond, DEMO_START, date(2024, 12, 31))  # type: ignore[arg-type]
    assert len(series) > 150
    assert all(Decimal(85) < value < Decimal(105) for value in series.values)
    assert series == treasury_prices(bond, DEMO_START, date(2024, 12, 31))  # type: ignore[arg-type]


def test_the_demonstration_is_deterministic(demo: DemoAccounting):
    assert build_demo_accounting() is demo  # cached
    rebuilt = build_demo_accounting.__wrapped__()
    assert rebuilt.valuations[-1].nav == demo.valuations[-1].nav
    assert [item.transaction_id for item in rebuilt.transactions] == [item.transaction_id for item in demo.transactions]
