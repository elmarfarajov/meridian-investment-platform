"""The accounting engine: posting rules, settlement, income, corporate actions and replay."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from meridian.accounting.blotter import TradeBlotter
from meridian.accounting.builders import (
    cash_transaction,
    fx_conversion,
    purchase,
    sale,
    transfer_in,
)
from meridian.accounting.chart_of_accounts import Accounts
from meridian.accounting.engine import AccountingEngine
from meridian.accounting.journal import EntryKind
from meridian.accounting.lots import RealisationKind, Term
from meridian.accounting.sources import FixedFx, FixedPrices
from meridian.core import Ticker, ValidationError
from meridian.core.enums import LotSelectionMethod, TransactionType
from meridian.domain import Transaction
from meridian.domain.corporate_actions import CashMerger, SpinOff, StockMerger, dividend, split
from meridian.domain.instruments import Equity, SecurityIdentifiers

D = date


def deposit(day: date, amount: str, currency: str = "USD", tid: str | None = None) -> Transaction:
    return cash_transaction(
        transaction_id=tid or f"DEP-{day}-{currency}",
        portfolio_id="P",
        kind=TransactionType.DEPOSIT,
        day=day,
        amount=amount,
        currency=currency,
    )


def buy(tid: str, day: date, quantity, price: str, instrument: str = "US-AAPL", currency: str = "USD", **extra):
    return purchase(
        transaction_id=tid,
        portfolio_id="P",
        instrument_id=instrument,
        day=day,
        quantity=quantity,
        price=price,
        currency=currency,
        **extra,
    )


def sell(tid: str, day: date, quantity, price: str, instrument: str = "US-AAPL", currency: str = "USD", **extra):
    return sale(
        transaction_id=tid,
        portfolio_id="P",
        instrument_id=instrument,
        day=day,
        quantity=quantity,
        price=price,
        currency=currency,
        **extra,
    )


# ---------------------------------------------------------------------------- trades and settlement
def test_a_purchase_is_a_payable_until_it_settles_and_commission_is_capitalised(engine: AccountingEngine):
    book = engine.run([deposit(D(2026, 3, 2), "50000"), buy("B1", D(2026, 3, 2), 100, "200", fees="9.95")])
    trade = book.ledger.entry("B1:T")
    assert trade.kind is EntryKind.TRADE
    assert book.ledger.balance(Accounts.INVESTMENTS) == Decimal("20009.95")
    # T+1: the payable exists on trade date and is gone after settlement
    assert book.snapshot_on(D(2026, 3, 2)).balance(Accounts.PURCHASES_PAYABLE.code, "USD") == Decimal("-20009.95")
    assert book.snapshot_on(D(2026, 3, 3)).balance(Accounts.PURCHASES_PAYABLE.code, "USD") == 0
    assert book.settled_cash("USD", D(2026, 3, 2)) == Decimal(50000)
    assert book.settled_cash("USD", D(2026, 3, 3)) == Decimal("29990.05")
    assert book.projected_cash("USD", D(2026, 3, 2)) == Decimal("29990.05")
    (lot,) = book.open_lots["US-AAPL"]
    assert lot.cost_per_unit == Decimal("200.0995")
    assert book.ledger.trial_balance().is_balanced


def test_a_sale_realises_a_gain_net_of_costs_split_by_holding_period(engine: AccountingEngine):
    book = engine.run(
        [
            deposit(D(2024, 1, 2), "100000"),
            buy("B1", D(2024, 1, 3), 100, "100"),
            buy("B2", D(2025, 6, 2), 100, "150"),
            sell("S1", D(2025, 6, 16), 150, "160", fees="15"),
        ]
    )
    long_lot, short_lot = book.realised
    assert (long_lot.lot_id, long_lot.term, long_lot.quantity) == ("B1", Term.LONG, Decimal(100))
    assert (short_lot.lot_id, short_lot.term, short_lot.quantity) == ("B2", Term.SHORT, Decimal(50))
    assert long_lot.proceeds + short_lot.proceeds == Decimal(150 * 160 - 15)
    assert book.ledger.balance(Accounts.REALISED_LONG_TERM) == -long_lot.gain
    assert book.ledger.balance(Accounts.REALISED_SHORT_TERM) == -short_lot.gain
    summary = book.realised_summary()
    assert summary["net"] == long_lot.gain + short_lot.gain
    assert summary["long_gains"] == long_lot.gain


def test_a_currency_move_between_trade_and_settlement_is_a_realised_currency_result(make_engine):
    fx = FixedFx({"EUR": "1.10", ("EUR", D(2026, 3, 4)): "1.12"})
    book = make_engine(fx).run(
        [deposit(D(2026, 3, 2), "30000", "EUR"), buy("B1", D(2026, 3, 2), 1000, "20", "DE-BAYN", "EUR")]
    )
    # bought at 1.10, paid for two days later at 1.12: the euros cost 400 dollars more
    assert book.ledger.balance(Accounts.REALISED_FX_SETTLEMENT) == Decimal("400.00")
    assert book.ledger.balance(Accounts.INVESTMENTS) == Decimal("22000.00")
    assert book.ledger.trial_balance().is_balanced
    assert book.ledger.local_balances(Accounts.CASH) == {"EUR": Decimal(10000)}


def test_specific_lots_and_a_method_can_be_named_on_the_sale(engine: AccountingEngine):
    trades = [
        deposit(D(2025, 1, 2), "100000"),
        buy("B1", D(2025, 1, 3), 10, "100"),
        buy("B2", D(2025, 1, 6), 10, "300"),
        buy("B3", D(2025, 1, 7), 10, "200"),
    ]
    by_method = engine.run([*trades, sell("S1", D(2025, 9, 2), 10, "250", method=LotSelectionMethod.HIFO)])
    assert by_method.realised[0].lot_id == "B2"
    by_lot = engine.run([*trades, sell("S1", D(2025, 9, 2), 10, "250", lots=("B3",))])
    assert by_lot.realised[0].lot_id == "B3"


def test_an_open_settlement_fail_leaves_the_payable_and_the_cash_where_they_were(engine: AccountingEngine):
    blotter = TradeBlotter()
    moment = datetime(2026, 3, 2, 20, tzinfo=timezone.utc)
    blotter.book(deposit(D(2026, 3, 2), "50000"), moment)
    blotter.book(buy("B1", D(2026, 3, 2), 100, "200", settlement_date=D(2026, 3, 3)), moment)
    blotter.fail("B1", reason="stock not delivered")
    book = engine.run(blotter.as_known_at(), until=D(2026, 3, 10))
    assert book.settled_cash("USD", D(2026, 3, 10)) == Decimal(50000)
    assert book.snapshot_on(D(2026, 3, 10)).balance(Accounts.PURCHASES_PAYABLE.code, "USD") == Decimal(-20000)
    (movement,) = [item for item in book.pending_movements(D(2026, 3, 10)) if item.transaction_id == "B1"]
    assert movement.failing
    assert book.settled_position("US-AAPL", D(2026, 3, 10)) == 0
    assert book.snapshot_on(D(2026, 3, 10)).quantity("US-AAPL") == 100


def test_the_settlement_date_view_of_a_position(engine: AccountingEngine):
    book = engine.run([deposit(D(2026, 3, 2), "50000"), buy("B1", D(2026, 3, 2), 100, "200")])
    assert book.settled_position("US-AAPL", D(2026, 3, 2)) == 0
    assert book.settled_position("US-AAPL", D(2026, 3, 3)) == 100


def test_a_cash_ladder_shows_settlements_to_come(engine: AccountingEngine):
    book = engine.run(
        [
            deposit(D(2026, 3, 2), "10000"),
            buy("B1", D(2026, 3, 2), 10, "100", "DE-BAYN", "EUR"),
            deposit(D(2026, 3, 2), "5000", "EUR", "DEP-EUR"),
        ]
    )
    ladder = book.cash_ladder(D(2026, 3, 2), horizon_days=5)
    eur = {day: (settling, balance) for day, settling, balance in ladder["EUR"]}
    assert eur[D(2026, 3, 3)] == (0, Decimal(5000))
    assert eur[D(2026, 3, 4)] == (Decimal(-1000), Decimal(4000))
    assert all(day.weekday() < 5 for day in eur)


# ---------------------------------------------------------------------------- cash and currencies
def test_a_conversion_is_a_cross_currency_entry_with_the_spread_as_a_currency_cost(make_engine):
    fx = FixedFx({"EUR": "1.10"})
    book = make_engine(fx).run(
        [
            deposit(D(2026, 3, 2), "11000"),
            fx_conversion(
                transaction_id="FX1",
                portfolio_id="P",
                trade_date=D(2026, 3, 2),
                sell_currency="USD",
                sell_amount="11000",
                buy_currency="EUR",
                rate="0.9",  # the market rate is 1/1.10 = 0.909; the bank kept the difference
            ),
        ]
    )
    entry = book.ledger.entry("FX1:S")
    assert entry.cross_currency and entry.kind is EntryKind.CURRENCY_EXCHANGE
    assert entry.effective_date == D(2026, 3, 4)  # spot, T+2
    assert book.ledger.local_balances(Accounts.CASH) == {"EUR": Decimal("9900.00")}
    assert book.ledger.balance(Accounts.REALISED_FX_SETTLEMENT) == Decimal("110.00")
    assert book.ledger.trial_balance().is_balanced


def test_withdrawals_fees_and_taxes(engine: AccountingEngine):
    book = engine.run(
        [
            deposit(D(2026, 1, 5), "1000"),
            cash_transaction(
                transaction_id="W1",
                portfolio_id="P",
                kind=TransactionType.WITHDRAWAL,
                day=D(2026, 1, 6),
                amount="300",
                currency="USD",
            ),
            cash_transaction(
                transaction_id="F1",
                portfolio_id="P",
                kind=TransactionType.FEE,
                day=D(2026, 1, 7),
                amount="25",
                currency="USD",
            ),
            cash_transaction(
                transaction_id="X1",
                portfolio_id="P",
                kind=TransactionType.TAX,
                day=D(2026, 1, 7),
                amount="5",
                currency="USD",
            ),
        ]
    )
    assert book.settled_cash("USD", D(2026, 1, 8)) == Decimal(670)
    assert book.ledger.balance(Accounts.CONTRIBUTED_CAPITAL) == Decimal(-700)
    assert book.ledger.balance(Accounts.FEES) == Decimal(25)
    assert book.ledger.balance(Accounts.TRANSACTION_TAXES) == Decimal(5)
    with pytest.raises(ValidationError, match="cash-only"):
        cash_transaction(
            transaction_id="B",
            portfolio_id="P",
            kind=TransactionType.BUY,
            day=D(2026, 1, 7),
            amount="1",
            currency="USD",
        )


# ---------------------------------------------------------------------------- transfers
def test_a_transfer_in_keeps_its_cost_and_acquisition_date(engine: AccountingEngine):
    book = engine.run(
        [
            transfer_in(
                transaction_id="TI1",
                portfolio_id="P",
                instrument_id="US-AAPL",
                day=D(2026, 3, 2),
                quantity=400,
                cost_per_unit="125",
                currency="USD",
                acquired=D(2021, 3, 10),
            ),
            sell("S1", D(2026, 3, 9), 100, "180"),
        ]
    )
    record = book.realised[0]
    assert record.term is Term.LONG  # long-term on day one, because the holding period tacks
    assert record.gain == Decimal(5500)
    assert book.ledger.balance(Accounts.TRANSFERRED_IN_KIND) == Decimal(-50000)
    assert book.ledger.balance(Accounts.CONTRIBUTED_CAPITAL) == 0


def test_a_transfer_out_moves_cost_without_realising_anything(engine: AccountingEngine):
    book = engine.run(
        [
            deposit(D(2026, 1, 5), "10000"),
            buy("B1", D(2026, 1, 5), 10, "100"),
            Transaction(
                transaction_id="TO1",
                portfolio_id="P",
                transaction_type=TransactionType.TRANSFER_OUT,
                instrument_id="US-AAPL",
                trade_date=D(2026, 2, 2),
                settlement_date=D(2026, 2, 2),
                quantity=Decimal(4),
                currency="USD",
            ),
        ]
    )
    assert book.realised == []
    assert book.ledger.balance(Accounts.TRANSFERRED_IN_KIND) == Decimal(400)
    assert book.open_lots["US-AAPL"][0].quantity == 6


# ---------------------------------------------------------------------------- income
def test_a_dividend_is_receivable_from_ex_date_and_withholding_is_split_into_reclaimable_and_lost(make_engine, fx):
    engine = make_engine(fx)
    action = dividend("DIV1", "DE-BAYN", D(2026, 4, 28), "2.00", "EUR", pay_date=D(2026, 5, 12))
    book = engine.run(
        [
            deposit(D(2026, 4, 1), "50000", "EUR"),
            buy("B1", D(2026, 4, 1), 1000, "25", "DE-BAYN", "EUR"),
            buy("B2", D(2026, 4, 28), 500, "24", "DE-BAYN", "EUR"),  # bought on the ex-date: not entitled
        ],
        [action],
        until=D(2026, 5, 31),
    )
    gross = Decimal(2000)
    assert book.ledger.local_balances(Accounts.DIVIDEND_INCOME) == {"EUR": -gross}
    withheld = Decimal("527.50")  # 26.375%
    reclaimable = Decimal("227.50")  # the 11.375% above the 15% treaty rate
    assert book.ledger.local_balances(Accounts.TAX_RECLAIMABLE) == {"EUR": reclaimable}
    assert book.ledger.local_balances(Accounts.WITHHOLDING_TAX) == {"EUR": withheld - reclaimable}
    ex_state = book.snapshot_on(D(2026, 4, 28))
    assert ex_state.balance(Accounts.DIVIDENDS_RECEIVABLE.code, "EUR") == gross - withheld
    assert book.snapshot_on(D(2026, 5, 12)).balance(Accounts.DIVIDENDS_RECEIVABLE.code, "EUR") == 0
    assert book.ledger.trial_balance().is_balanced
    (record,) = book.corporate_actions
    assert "reclaimable 227.50" in record.notes[0]


def test_a_dividend_with_its_own_withholding_rate_overrides_the_policy(make_engine, fx):
    action = dividend("DIV1", "US-AAPL", D(2026, 5, 11), "0.26", "USD", pay_date=D(2026, 5, 14), withholding_rate="0.3")
    book = make_engine(fx).run(
        [deposit(D(2026, 5, 1), "5000"), buy("B1", D(2026, 5, 1), 100, "20")], [action], until=D(2026, 5, 20)
    )
    assert book.ledger.balance(Accounts.WITHHOLDING_TAX) == Decimal("7.80")
    assert book.ledger.balance(Accounts.TAX_RECLAIMABLE) == 0


def test_a_bond_purchase_pays_accrued_interest_which_the_next_coupon_recovers(engine: AccountingEngine):
    # US-T-2032: 2.875% semi-annual, face 1,000, coupons 15 May and 15 November
    book = engine.run(
        [deposit(D(2026, 2, 2), "300000"), buy("B1", D(2026, 2, 2), 250, "96.42", "US-T-2032")],
        until=D(2026, 5, 29),
    )
    purchase_entry = book.ledger.entry("B1:T")
    accrued = next(
        p.amount for p in purchase_entry.postings if p.account_code == Accounts.ACCRUED_INTEREST_PURCHASED.code
    )
    # 78 days of 30/360 from 15 November to 3 February (settlement) on 250,000 face
    assert accrued == Decimal("1557.29")
    assert book.ledger.balance(Accounts.INVESTMENTS) == Decimal("241050.00")
    coupon = Decimal("3593.75")
    assert book.settled_cash("USD", D(2026, 5, 29)) == Decimal(300000) - Decimal("241050") - accrued + coupon
    assert book.ledger.balance(Accounts.INTEREST_INCOME) == -(coupon - accrued)
    assert book.ledger.balance(Accounts.ACCRUED_INTEREST_PURCHASED) == 0


def test_selling_a_bond_between_coupons_receives_accrued_interest(engine: AccountingEngine):
    book = engine.run(
        [
            deposit(D(2026, 2, 2), "300000"),
            buy("B1", D(2026, 2, 2), 250, "96.42", "US-T-2032"),
            sell("S1", D(2026, 3, 16), 100, "97.00", "US-T-2032"),
        ],
        until=D(2026, 3, 31),
    )
    assert book.realised[0].gain == Decimal(100 * 10 * (Decimal("97.00") - Decimal("96.42")))
    sale_entry = book.ledger.entry("S1:T")
    codes = {posting.account_code for posting in sale_entry.postings}
    assert Accounts.ACCRUED_INTEREST_PURCHASED.code in codes
    assert Accounts.INTEREST_INCOME.code in codes
    assert book.ledger.trial_balance().is_balanced


# ---------------------------------------------------------------------------- corporate actions
def test_a_split_quadruples_the_lots_and_pays_cash_in_lieu_for_the_fraction(make_engine, fx):
    prices = FixedPrices({"DEMO-SPLIT": {D(2025, 6, 10): "120.00"}})
    engine = make_engine(fx, prices=prices)
    action = split("SPLIT", "DEMO-SPLIT", D(2025, 6, 10), 3, 2)
    book = engine.run(
        [deposit(D(2025, 1, 2), "100000"), buy("B1", D(2025, 1, 3), 101, "180", "DEMO-SPLIT")],
        [action],
        until=D(2025, 6, 20),
    )
    (lot,) = book.open_lots["DEMO-SPLIT"]
    assert lot.quantity == 151  # 151.5 before the fraction was paid out
    (record,) = book.realised
    assert record.kind is RealisationKind.CASH_IN_LIEU
    assert record.quantity == Decimal("0.5")
    assert record.proceeds == Decimal("60.00")
    assert record.cost == Decimal("0.5") * Decimal(120)  # 180 / 1.5 per new share
    assert book.corporate_actions[0].quantity_after == 151
    assert book.ledger.trial_balance().is_balanced


def test_a_split_without_a_price_for_the_fraction_is_refused(make_engine, fx):
    action = split("SPLIT", "DEMO-SPLIT", D(2025, 6, 10), 3, 2)
    with pytest.raises(ValidationError, match="no price"):
        make_engine(fx).run([buy("B1", D(2025, 1, 3), 101, "180", "DEMO-SPLIT")], [action])


def test_a_spin_off_moves_basis_to_the_child_with_the_holding_period(make_engine, fx, instruments):
    child = Equity(
        instrument_id="CHILD",
        name="Spun-off child",
        currency="USD",
        identifiers=SecurityIdentifiers(ticker=Ticker("CHLD")),
        country="US",
    )
    engine = AccountingEngine(make_engine(fx).portfolio, {**instruments, "CHILD": child}, fx)
    action = SpinOff(
        action_id="SO1",
        instrument_id="US-JNJ",
        ex_date=D(2026, 3, 2),
        child_instrument_id="CHILD",
        ratio=Decimal("0.5"),
        cost_allocation=Decimal("0.25"),
    )
    book = engine.run(
        [deposit(D(2025, 1, 2), "20000"), buy("B1", D(2025, 1, 3), 100, "160", "US-JNJ")], [action], until=D(2026, 3, 5)
    )
    (parent,) = book.open_lots["US-JNJ"]
    (spun,) = book.open_lots["CHILD"]
    assert parent.cost_basis.amount + spun.cost_basis.amount == Decimal(16000)
    assert spun.cost_basis.amount == Decimal(4000)
    assert spun.quantity == 50 and spun.open_date == D(2025, 1, 3)
    assert book.ledger.instrument_balances(Accounts.INVESTMENTS) == {"CHILD": Decimal(4000), "US-JNJ": Decimal(12000)}


def test_a_cash_merger_closes_the_holding_and_a_stock_merger_exchanges_it(make_engine, fx):
    engine = make_engine(fx, prices=FixedPrices({"US-MSFT": {D(2026, 3, 2): "400"}}))
    trades = [deposit(D(2025, 1, 2), "50000"), buy("B1", D(2025, 1, 3), 100, "150", "US-JNJ")]
    cash = CashMerger(
        action_id="M1", instrument_id="US-JNJ", ex_date=D(2026, 3, 2), cash_per_share=Decimal(170), currency="USD"
    )
    book = engine.run(trades, [cash], until=D(2026, 3, 10))
    (record,) = book.realised
    assert record.kind is RealisationKind.CASH_MERGER and record.gain == Decimal(2000) and record.is_long_term
    assert "US-JNJ" not in book.open_lots
    stock = StockMerger(
        action_id="M2",
        instrument_id="US-JNJ",
        ex_date=D(2026, 3, 2),
        acquirer_instrument_id="US-MSFT",
        ratio=Decimal("0.4"),
        cash_per_share=Decimal(10),
        currency="USD",
    )
    book = engine.run(trades, [stock], until=D(2026, 3, 10))
    (acquired,) = book.open_lots["US-MSFT"]
    assert acquired.quantity == 40
    # gain realised = 1000 cash + 40 x 400 - 15,000 = 2,000; recognised = min(cash, gain) = 1,000
    assert book.ledger.balance(Accounts.REALISED_LONG_TERM) == Decimal(-1000)
    assert acquired.cost_basis.amount == Decimal(15000) - Decimal(1000) + Decimal(1000)
    assert book.ledger.trial_balance().is_balanced


# ---------------------------------------------------------------------------- refusals and replay
def test_the_engine_refuses_what_it_cannot_book(engine: AccountingEngine):
    with pytest.raises(ValidationError, match="cannot dispose"):
        engine.run([buy("B1", D(2026, 3, 2), 10, "1"), sell("S1", D(2026, 3, 3), 11, "1")])
    with pytest.raises(ValidationError, match="settles in USD"):
        engine.run([buy("B1", D(2026, 3, 2), 10, "1", currency="EUR")])
    with pytest.raises(ValidationError, match="security master"):
        engine.run([buy("B1", D(2026, 3, 2), 10, "1", instrument="NOPE")])
    with pytest.raises(ValidationError, match="appears twice"):
        engine.run([buy("B1", D(2026, 3, 2), 10, "1"), buy("B1", D(2026, 3, 3), 10, "1")])
    with pytest.raises(ValidationError, match="belongs to"):
        engine.run([replace(buy("B1", D(2026, 3, 2), 10, "1"), portfolio_id="Q")])
    split_tx = Transaction(
        transaction_id="X",
        portfolio_id="P",
        transaction_type=TransactionType.SPLIT,
        instrument_id="US-AAPL",
        trade_date=D(2026, 3, 2),
        quantity=Decimal(1),
        currency="USD",
    )
    with pytest.raises(ValidationError, match="capital events"):
        engine.run([split_tx])


def test_until_cuts_the_book_at_a_date(engine: AccountingEngine):
    trades = [deposit(D(2026, 3, 2), "1000"), buy("B1", D(2026, 3, 2), 1, "10"), buy("B2", D(2026, 3, 9), 1, "10")]
    book = engine.run(trades, until=D(2026, 3, 5))
    assert [item.transaction_id for item in book.transactions] == ["DEP-2026-03-02-USD", "B1"]
    assert book.as_of == D(2026, 3, 3)


def test_the_book_is_a_pure_function_of_the_blotter_and_a_correction_is_a_restatement(engine: AccountingEngine):
    blotter = TradeBlotter()
    evening = datetime(2026, 3, 2, 22, tzinfo=timezone.utc)
    blotter.book(deposit(D(2026, 3, 2), "10000"), evening)
    blotter.book(buy("B1", D(2026, 3, 2), 50, "100"), evening)
    blotter.book(sell("S1", D(2026, 3, 16), 50, "120"), datetime(2026, 3, 16, 22, tzinfo=timezone.utc))
    blotter.amend(buy("B1", D(2026, 3, 2), 50, "101"), datetime(2026, 3, 18, 9, tzinfo=timezone.utc), reason="price")
    before = engine.run(blotter.as_known_at(datetime(2026, 3, 17, tzinfo=timezone.utc)))
    after = engine.run(blotter.as_known_at())
    assert before.realised[0].gain == Decimal(1000)
    assert after.realised[0].gain == Decimal(950)
    again = engine.run(blotter.as_known_at())
    assert [e.entry_id for e in again.ledger] == [e.entry_id for e in after.ledger]
    assert again.ledger.trial_balance().lines == after.ledger.trial_balance().lines
