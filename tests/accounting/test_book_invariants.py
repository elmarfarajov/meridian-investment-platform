"""What must hold for any history of trades, however it is generated.

Hypothesis writes the histories: purchases and sales of a US and a UK share,
some at a loss and repurchased inside the wash sale window, under each lot
relief method, with the pound moving between trades. Whatever it writes:

* the trial balance is zero;
* the investment sub-ledger in the general ledger ties to the open lots, per
  instrument, at historical cost in base currency, to the last decimal;
* the quantity held is what was bought less what was sold;
* a wash sale only defers: every dollar of loss disallowed is carried in the
  basis of a replacement lot, open or since sold, so the reportable gains of the
  life of the book plus the tax gain still unrealised equal the economic gain;
* a replacement share carries at most one disallowed loss, and the holding
  period of a lot never starts after it was opened.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from meridian.accounting.builders import cash_transaction, purchase, sale
from meridian.accounting.chart_of_accounts import Accounts
from meridian.accounting.engine import AccountingEngine, AccountingPolicy
from meridian.accounting.sources import FixedFx
from meridian.core.decimals import decimal_sum
from meridian.core.enums import LotSelectionMethod, TransactionType
from meridian.domain import Portfolio
from meridian.seed import demo_instruments

INSTRUMENTS = {item.instrument_id: item for item in demo_instruments()}
START = date(2025, 1, 6)
CURRENCY = {"US-AAPL": "USD", "GB-BAE": "GBP"}
METHODS = [LotSelectionMethod.FIFO, LotSelectionMethod.LIFO, LotSelectionMethod.HIFO]

trade = st.tuples(
    st.sampled_from(sorted(CURRENCY)),
    st.integers(min_value=0, max_value=200),  # trading day offset
    st.integers(min_value=1, max_value=60),  # quantity
    st.integers(min_value=50, max_value=150),  # price, a whole number to keep the arithmetic readable
    st.booleans(),  # a sale, if anything is held
)


def _history(trades):
    """Turn generated tuples into a history that never sells more than it holds."""
    held = dict.fromkeys(CURRENCY, 0)
    rows = [
        cash_transaction(
            transaction_id="DEP",
            portfolio_id="P",
            kind=TransactionType.DEPOSIT,
            day=START,
            amount="10000000",
            currency="USD",
        ),
        cash_transaction(
            transaction_id="DEP-GBP",
            portfolio_id="P",
            kind=TransactionType.DEPOSIT,
            day=START,
            amount="10000000",
            currency="GBP",
        ),
    ]
    for index, (instrument, offset, quantity, price, selling) in enumerate(sorted(trades, key=lambda item: item[1])):
        day = START + timedelta(days=offset + 1)
        if day.weekday() >= 5:
            day += timedelta(days=7 - day.weekday())
        if selling and held[instrument] > 0:
            quantity = min(quantity, held[instrument])
            held[instrument] -= quantity
            maker = sale
        else:
            held[instrument] += quantity
            maker = purchase
        rows.append(
            maker(
                transaction_id=f"T{index:03d}",
                portfolio_id="P",
                instrument_id=instrument,
                day=day,
                quantity=quantity,
                price=str(price),
                currency=CURRENCY[instrument],
            )
        )
    return rows, held


def _fx(seed: int) -> FixedFx:
    path: dict[object, str] = {"GBP": "1.25"}
    for week in range(40):
        day = START + timedelta(days=7 * week)
        path[("GBP", day)] = f"{1.25 + ((seed * (week + 3)) % 17 - 8) / 200:.4f}"
    return FixedFx(path)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    trades=st.lists(trade, min_size=1, max_size=30),
    method=st.sampled_from(METHODS),
    seed=st.integers(min_value=0, max_value=1000),
)
def test_any_history_keeps_the_book_whole(trades, method, seed):
    rows, held = _history(trades)
    engine = AccountingEngine(
        Portfolio(portfolio_id="P", name="property", base_currency="USD"),
        INSTRUMENTS,
        _fx(seed),
        policy=AccountingPolicy(lot_method=method),
    )
    book = engine.run(rows, until=START + timedelta(days=240))

    assert book.ledger.trial_balance().is_balanced

    sub_ledger = book.ledger.instrument_balances(Accounts.INVESTMENTS)
    for instrument in CURRENCY:
        lots = book.open_lots.get(instrument, ())
        assert decimal_sum(lot.quantity for lot in lots) == held[instrument]
        lot_cost = decimal_sum(lot.base_cost for lot in lots)
        assert abs(sub_ledger.get(instrument, Decimal(0)) - lot_cost) < Decimal("1e-9"), instrument
        for lot in lots:
            assert lot.holding_start <= lot.open_date

    # a wash sale defers a loss, it never destroys one
    disallowed = decimal_sum(record.disallowed_loss for record in book.realised)
    carried_open = decimal_sum(
        lot.quantity * lot.wash_sale_adjustment for lots in book.open_lots.values() for lot in lots
    )
    carried_closed = decimal_sum(record.wash_sale_basis for record in book.realised)
    assert abs(disallowed - carried_open - carried_closed) < Decimal("1e-9")
    assert abs(disallowed - decimal_sum(match.disallowed for match in book.wash_sales)) < Decimal("1e-9")

    # no replacement share carries more than one sold share's loss
    replaced: dict[str, Decimal] = {}
    for match in book.wash_sales:
        replaced[match.replacement_id] = replaced.get(match.replacement_id, Decimal(0)) + match.quantity
    bought = {row.transaction_id: row.quantity for row in rows if row.transaction_type is TransactionType.BUY}
    assert all(quantity <= bought[transaction_id] for transaction_id, quantity in replaced.items())


def _engine(method=LotSelectionMethod.FIFO):
    return AccountingEngine(
        Portfolio(portfolio_id="P", name="t", base_currency="USD"),
        INSTRUMENTS,
        FixedFx({}),
        policy=AccountingPolicy(lot_method=method),
    )


def _trade(maker, transaction_id, day, quantity, price):
    return maker(
        transaction_id=transaction_id,
        portfolio_id="P",
        instrument_id="US-AAPL",
        day=day,
        quantity=quantity,
        price=price,
        currency="USD",
    )


def test_an_intraday_round_trip_is_booked_not_refused():
    deposit = cash_transaction(
        transaction_id="DEP", portfolio_id="P", kind=TransactionType.DEPOSIT, day=START, amount="100000", currency="USD"
    )
    day = date(2025, 1, 8)
    book = _engine().run([deposit, _trade(purchase, "B", day, 100, "200"), _trade(sale, "S", day, 100, "201")])
    (record,) = book.realised
    assert record.gain == Decimal(100) and not book.open_lots.get("US-AAPL")


def test_shares_sold_together_cannot_replace_each_other():
    deposit = cash_transaction(
        transaction_id="DEP", portfolio_id="P", kind=TransactionType.DEPOSIT, day=START, amount="100000", currency="USD"
    )
    rows = [
        deposit,
        _trade(purchase, "B1", date(2025, 1, 7), 10, "100"),
        _trade(purchase, "B2", date(2025, 1, 7), 10, "110"),
        _trade(purchase, "B3", date(2025, 1, 7), 10, "100"),
        _trade(sale, "S", date(2025, 1, 8), 20, "100"),  # HIFO closes B2 at a loss of 100, and B1
    ]
    book = _engine(LotSelectionMethod.HIFO).run(rows)
    (match,) = book.wash_sales
    # B1 is sold in the same sale, so the loss lands on B3, the shares still held
    assert match.replacement_id == "B3" and match.disallowed == Decimal(100)
    (lot,) = book.open_lots["US-AAPL"]
    assert lot.transaction_id == "B3" and lot.tax_basis == Decimal(1100)
