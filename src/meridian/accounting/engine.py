"""The accounting engine: transactions in, a balanced book out.

The engine replays a portfolio's transactions and corporate actions in date
order and produces the :class:`~meridian.accounting.book.Book`. On each date it
does, in this order:

1. **Corporate actions going ex** - before the market opens, as they do: a
   split changes the lots, a dividend becomes a receivable for the shares held
   the night before.
2. **Coupons paid** to the holders of record.
3. **The day's transactions**: deposits and transfers first, then currency
   conversions, then sales before purchases, so a same-day switch never
   borrows shares it does not yet own.
4. **Settlements falling due**, including trades agreed the same day.
5. **An end-of-day snapshot.**

Every step is one or more balanced journal entries, and the posting rules are
the ones a fund accountant uses:

====================  =====================================  =====================================
Event                 On trade date (or ex-date)             On settlement (or pay) date
====================  =====================================  =====================================
Purchase              Dr investments, Cr payable             Dr payable, Cr cash, FX on settlement
Sale                  Dr receivable, Cr investments at       Dr cash, Cr receivable, FX on
                      cost, Cr realised gain (price, FX)     settlement
Dividend              Dr receivable (net), Dr reclaimable,   Dr cash, Cr receivable
                      Dr withholding, Cr dividend income
Coupon                                                       Dr cash, Cr accrued interest
                                                             purchased, Cr interest income
Deposit / withdrawal  Dr cash, Cr capital (and reverse)
Transfer in kind      Dr investments, Cr transfers in kind
Currency conversion                                          Dr cash (bought), Cr cash (sold), FX
====================  =====================================  =====================================

Commissions and transaction taxes are capitalised into the cost of a purchase
and deducted from the proceeds of a sale, which is how both the IRS and HMRC
treat them; the value bridge still shows them separately as costs.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

from ..core.currency import get_currency
from ..core.decimals import decimal_sum
from ..core.enums import LotSelectionMethod, TransactionType
from ..core.exceptions import ValidationError
from ..domain.corporate_actions import (
    CashDividend,
    CashMerger,
    CorporateAction,
    RightsIssue,
    SpinOff,
    StockDividend,
    StockMerger,
    StockSplit,
    SymbolChange,
)
from ..domain.entitlements import apply_action, entitled_lots
from ..domain.instruments import Bond, Instrument, instrument_price_scale
from ..domain.portfolios import Portfolio
from ..domain.positions import TaxLot
from ..domain.transactions import Transaction
from .blotter import FAILING_FLAG
from .book import (
    CASH_LIKE_ACCOUNTS,
    Book,
    BookSnapshot,
    CashMovement,
    CorporateActionRecord,
    DayActivity,
    TradeActivity,
)
from .builders import ACQUIRED, BUY_AMOUNT, BUY_CURRENCY, LOT_IDS, LOT_METHOD, RECLAIMABLE
from .chart_of_accounts import Accounts, LedgerAccount
from .income import WithholdingPolicy, accrued_per_unit, coupon_schedule, split_dividend
from .journal import EntryKind, JournalEntry, Posting, base_only, credit, debit
from .ledger import GeneralLedger
from .lots import LotBook, RealisationKind, RealisedLot, Term, allocate_pro_rata
from .settlement import SettlementRules
from .sources import FxSource, PriceSource
from .wash_sales import Acquisition, WashSaleTracker

#: Within a day: money and securities arriving first, then conversions, then sales before purchases.
DAY_ORDER: dict[TransactionType, int] = {
    TransactionType.DEPOSIT: 0,
    TransactionType.TRANSFER_IN: 1,
    TransactionType.FX: 2,
    TransactionType.SELL: 3,
    TransactionType.TRANSFER_OUT: 4,
    TransactionType.BUY: 5,
    TransactionType.DIVIDEND: 6,
    TransactionType.INTEREST: 7,
    TransactionType.FEE: 8,
    TransactionType.TAX: 9,
    TransactionType.WITHDRAWAL: 10,
}


@dataclass(frozen=True)
class AccountingPolicy:
    lot_method: LotSelectionMethod = LotSelectionMethod.FIFO
    wash_sales: bool = True
    withholding: WithholdingPolicy = field(default_factory=WithholdingPolicy)
    generate_coupons: bool = True


@dataclass(frozen=True, slots=True)
class _Settlement:
    day: date
    transaction_id: str
    account: LedgerAccount
    currency: str
    amount: Decimal  # local, positive
    trade_rate: Decimal
    description: str


class AccountingEngine:
    """Replays transactions and corporate actions into a :class:`Book`."""

    def __init__(
        self,
        portfolio: Portfolio,
        instruments: Mapping[str, Instrument] | Iterable[Instrument],
        fx: FxSource,
        *,
        prices: PriceSource | None = None,
        policy: AccountingPolicy | None = None,
        settlement: SettlementRules | None = None,
    ) -> None:
        self.portfolio = portfolio
        self.instruments: dict[str, Instrument] = (
            dict(instruments)
            if isinstance(instruments, Mapping)
            else {item.instrument_id: item for item in instruments}
        )
        self.fx = fx
        self.prices = prices
        self.policy = policy or AccountingPolicy()
        self.settlement = settlement or SettlementRules()

    @property
    def base(self) -> str:
        return self.portfolio.base_currency.code

    def instrument(self, instrument_id: str | None) -> Instrument:
        if instrument_id is None or instrument_id not in self.instruments:
            raise ValidationError(f"{instrument_id!r} is not in the security master")
        return self.instruments[instrument_id]

    def rate(self, currency: str, day: date) -> Decimal:
        return self.fx.rate(currency, self.base, day)

    # ------------------------------------------------------------------ normalisation
    def normalise(self, transaction: Transaction) -> Transaction:
        """Fill in the settlement date from the rule table where the transaction does not carry one."""
        if transaction.portfolio_id != self.portfolio.portfolio_id:
            raise ValidationError(f"{transaction.transaction_id} belongs to {transaction.portfolio_id}")
        kind = transaction.transaction_type
        if kind in {TransactionType.SPLIT, TransactionType.SPIN_OFF}:
            raise ValidationError(
                f"{transaction.transaction_id}: capital events are applied from corporate actions, not booked by hand"
            )
        if transaction.settlement_date is not None:
            return transaction
        if kind in {TransactionType.BUY, TransactionType.SELL}:
            instrument = self.instrument(transaction.instrument_id)
            return replace(
                transaction, settlement_date=self.settlement.settlement_date(instrument, transaction.trade_date)
            )
        if kind is TransactionType.FX:
            bought = transaction.metadata.get(BUY_CURRENCY)
            if not bought:
                raise ValidationError(f"{transaction.transaction_id}: a conversion needs {BUY_CURRENCY!r}")
            settles = self.settlement.fx_settlement_date(transaction.currency.code, bought, transaction.trade_date)
            return replace(transaction, settlement_date=settles)
        return replace(transaction, settlement_date=transaction.trade_date)

    # ------------------------------------------------------------------ run
    def run(
        self,
        transactions: Iterable[Transaction],
        actions: Sequence[CorporateAction] = (),
        *,
        until: date | None = None,
    ) -> Book:
        normalised = sorted(
            (self.normalise(item) for item in transactions),
            key=lambda item: (item.trade_date, DAY_ORDER.get(item.transaction_type, 99), item.transaction_id),
        )
        if until is not None:
            normalised = [item for item in normalised if item.trade_date <= until]
        seen: set[str] = set()
        for item in normalised:
            if item.transaction_id in seen:
                raise ValidationError(f"transaction {item.transaction_id} appears twice")
            seen.add(item.transaction_id)
        run = _Run(self, normalised, actions, until)
        return run.execute()


class _Run:
    """The state of one replay. Kept separate so the engine itself holds only configuration."""

    def __init__(
        self,
        engine: AccountingEngine,
        transactions: list[Transaction],
        actions: Sequence[CorporateAction],
        until: date | None,
    ) -> None:
        self.engine = engine
        self.portfolio_id = engine.portfolio.portfolio_id
        self.transactions = transactions
        self.until = until
        held = {item.instrument_id for item in transactions if item.instrument_id}
        self.actions = sorted(
            (action for action in actions if action.instrument_id in held),
            key=lambda action: (action.ex_date, action.action_id),
        )
        self.ledger = GeneralLedger(self.portfolio_id, engine.base)
        self.lots = LotBook(self.portfolio_id, method=engine.policy.lot_method)
        self.realised: list[RealisedLot] = []
        self.movements: list[CashMovement] = []
        self.snapshots: list[BookSnapshot] = []
        self.activity: dict[date, DayActivity] = {}
        self.records: list[CorporateActionRecord] = []
        self.balances: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        self.settlements: dict[date, list[_Settlement]] = defaultdict(list)
        self.accrued_purchased: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
        self.opened: set[str] = set()
        self.failing = {item.transaction_id for item in transactions if item.metadata.get(FAILING_FLAG)}
        self.tracker = WashSaleTracker(
            Acquisition(item.transaction_id, item.instrument_id or "", item.trade_date, item.quantity)
            for item in transactions
            if item.transaction_type is TransactionType.BUY
        )
        self.coupons = self._coupon_calendar()

    # ------------------------------------------------------------------ helpers
    def day(self, day: date) -> DayActivity:
        if day not in self.activity:
            self.activity[day] = DayActivity(day)
        return self.activity[day]

    def post(self, entry: JournalEntry) -> None:
        self.ledger.post(entry)
        for posting in entry.postings:
            if posting.account_code in CASH_LIKE_ACCOUNTS:
                self.balances[posting.account_code][posting.currency] += posting.amount

    def entry(
        self,
        entry_id: str,
        day: date,
        kind: EntryKind,
        postings: Sequence[Posting],
        description: str,
        source_id: str | None,
        *,
        cross_currency: bool = False,
    ) -> None:
        self.post(
            JournalEntry(
                entry_id=entry_id,
                portfolio_id=self.portfolio_id,
                effective_date=day,
                kind=kind,
                postings=tuple(postings),
                description=description,
                source_id=source_id,
                cross_currency=cross_currency,
            )
        )

    def precision(self, currency: str) -> Decimal:
        return get_currency(currency).precision

    def money(self, amount: Decimal, currency: str) -> Decimal:
        return amount.quantize(self.precision(currency), rounding=ROUND_HALF_EVEN)

    def rate(self, currency: str, day: date) -> Decimal:
        return self.engine.rate(currency, day)

    def schedule(self, settlement: _Settlement, failing: bool) -> None:
        if not failing:
            self.settlements[settlement.day].append(settlement)

    def _coupon_calendar(self) -> dict[date, list[tuple[Bond, Decimal]]]:
        calendar: dict[date, list[tuple[Bond, Decimal]]] = defaultdict(list)
        if not self.engine.policy.generate_coupons or not self.transactions:
            return calendar
        start = self.transactions[0].trade_date
        end = self.until or max(item.settles_on for item in self.transactions)
        for instrument_id in {item.instrument_id for item in self.transactions if item.instrument_id}:
            instrument = self.engine.instrument(instrument_id)
            if isinstance(instrument, Bond) and instrument.coupon > 0:
                for payment in coupon_schedule(instrument, start, end):
                    calendar[payment.payment_date].append((instrument, payment.per_unit))
        return calendar

    # ------------------------------------------------------------------ main loop
    def execute(self) -> Book:
        by_day: dict[date, list[Transaction]] = defaultdict(list)
        for item in self.transactions:
            by_day[item.trade_date].append(item)
        actions_by_day: dict[date, list[CorporateAction]] = defaultdict(list)
        for action in self.actions:
            actions_by_day[action.ex_date].append(action)
        days = set(by_day) | set(actions_by_day) | set(self.coupons)
        days |= {item.settles_on for item in self.transactions if item.transaction_id not in self.failing}
        if self.transactions:
            first = self.transactions[0].trade_date
            days = {day for day in days if day >= first}
        if self.until is not None:
            days = {day for day in days if day <= self.until}

        # a heap rather than a sorted list: pay dates of dividends and cash in lieu
        # only become known when the corporate action is processed
        queue = sorted(days)
        heapq.heapify(queue)
        self._queued = set(queue)
        last: date | None = None
        while queue:
            today = heapq.heappop(queue)
            self._today = today
            for action in actions_by_day.get(today, []):
                self.corporate_action(action)
            for bond, per_unit in self.coupons.get(today, []):
                self.coupon(bond, per_unit, today)
            for transaction in by_day.get(today, []):
                self.transaction(transaction)
            for due in self.settlements.pop(today, []):
                self.settle(due, today)
            self._settle_conversions(today)
            for future in sorted(set(self.settlements) | set(self._pending_conversions)):
                if future > today and future not in self._queued and (self.until is None or future <= self.until):
                    heapq.heappush(queue, future)
                    self._queued.add(future)
            self.snapshot(today)
            last = today
        return Book(
            portfolio=self.engine.portfolio,
            ledger=self.ledger,
            open_lots=self.lots.snapshot(),
            realised=self.realised,
            wash_sales=list(self.tracker.matches),
            cash_movements=self.movements,
            snapshots=self.snapshots,
            activity={day: item for day, item in self.activity.items() if not item.is_empty},
            transactions=self.transactions,
            corporate_actions=self.records,
            as_of=last,
        )

    def snapshot(self, today: date) -> None:
        self.snapshots.append(
            BookSnapshot(
                today,
                self.lots.snapshot(),
                {code: {ccy: amount for ccy, amount in values.items()} for code, values in self.balances.items()},
            )
        )

    # ------------------------------------------------------------------ dispatch
    def transaction(self, transaction: Transaction) -> None:
        kind = transaction.transaction_type
        handler = {
            TransactionType.BUY: self.buy,
            TransactionType.SELL: self.sell,
            TransactionType.DEPOSIT: self.cash_flow,
            TransactionType.WITHDRAWAL: self.cash_flow,
            TransactionType.FEE: self.charge,
            TransactionType.TAX: self.charge,
            TransactionType.TRANSFER_IN: self.transfer_in,
            TransactionType.TRANSFER_OUT: self.transfer_out,
            TransactionType.DIVIDEND: self.dividend_transaction,
            TransactionType.INTEREST: self.interest_transaction,
            TransactionType.FX: self.conversion,
        }.get(kind)
        if handler is None:  # pragma: no cover - every type is routed above or refused in normalise
            raise ValidationError(f"no posting rule for {kind.value}")
        handler(transaction)

    # ------------------------------------------------------------------ purchases
    def buy(self, transaction: Transaction) -> None:
        instrument = self.engine.instrument(transaction.instrument_id)
        currency = self._currency_of(transaction, instrument)
        today, settles = transaction.trade_date, transaction.settles_on
        scale = instrument_price_scale(instrument)
        quantity = transaction.quantity
        gross = self.money(
            transaction.gross_amount if transaction.gross_amount is not None else quantity * transaction.price * scale,
            currency,
        )
        costs = transaction.fees + transaction.taxes
        cost = gross + costs
        accrued = self.money(accrued_per_unit(instrument, settles) * quantity, currency)
        rate = self.rate(currency, today)
        payable = cost + accrued
        postings = [
            debit(Accounts.INVESTMENTS, cost, currency, rate, instrument_id=instrument.instrument_id),
            credit(Accounts.PURCHASES_PAYABLE, payable, currency, rate, instrument_id=instrument.instrument_id),
        ]
        if accrued:
            postings.append(
                debit(
                    Accounts.ACCRUED_INTEREST_PURCHASED, accrued, currency, rate, instrument_id=instrument.instrument_id
                )
            )
            held = self.accrued_purchased[instrument.instrument_id]
            held[0] += accrued
            held[1] += accrued * rate
        self.entry(
            f"{transaction.transaction_id}:T",
            today,
            EntryKind.TRADE,
            postings,
            f"buy {quantity:,} {instrument.instrument_id} @ {transaction.price}",
            transaction.transaction_id,
        )
        lot = TaxLot(
            lot_id=transaction.transaction_id,
            instrument_id=instrument.instrument_id,
            open_date=today,
            quantity=quantity,
            cost_per_unit=cost / quantity,
            currency=instrument.currency,
            transaction_id=transaction.transaction_id,
            open_fx_rate=rate,
        )
        self.lots.open(lot)
        self.opened.add(transaction.transaction_id)
        for pending in self.tracker.pending_for(transaction.transaction_id):
            self.lots.adjust_for_wash_sale(
                instrument.instrument_id,
                transaction.transaction_id,
                pending.quantity,
                pending.per_unit,
                pending.tacked_days,
            )
        failing = transaction.transaction_id in self.failing
        self.movements.append(
            CashMovement(
                transaction.transaction_id,
                currency,
                -payable,
                today,
                settles,
                "buy",
                f"buy {instrument.instrument_id}",
                failing,
            )
        )
        self.schedule(
            _Settlement(
                settles, transaction.transaction_id, Accounts.PURCHASES_PAYABLE, currency, payable, rate, "purchase"
            ),
            failing,
        )
        activity = self.day(today)
        activity.trades.append(
            TradeActivity(
                transaction.transaction_id, instrument.instrument_id, quantity, gross, currency, "trade", accrued
            )
        )
        if costs:
            activity.costs[currency] += costs

    # ------------------------------------------------------------------ disposals
    def sell(self, transaction: Transaction) -> None:
        instrument = self.engine.instrument(transaction.instrument_id)
        currency = self._currency_of(transaction, instrument)
        scale = instrument_price_scale(instrument)
        quantity = transaction.quantity
        gross = self.money(
            transaction.gross_amount if transaction.gross_amount is not None else quantity * transaction.price * scale,
            currency,
        )
        costs = transaction.fees + transaction.taxes
        method = transaction.metadata.get(LOT_METHOD)
        specific = [item for item in transaction.metadata.get(LOT_IDS, "").split(",") if item]
        if transaction.lot_id:
            specific = [transaction.lot_id]
        self.dispose(
            instrument,
            quantity,
            gross,
            costs,
            transaction.trade_date,
            transaction.settles_on,
            transaction.transaction_id,
            kind=RealisationKind.SALE,
            method=LotSelectionMethod(method) if method else None,
            specific=specific or None,
            failing=transaction.transaction_id in self.failing,
            description=f"sell {quantity:,} {instrument.instrument_id} @ {transaction.price}",
        )

    def dispose(
        self,
        instrument: Instrument,
        quantity: Decimal,
        gross: Decimal,
        costs: Decimal,
        today: date,
        settles: date,
        disposal_id: str,
        *,
        kind: RealisationKind,
        method: LotSelectionMethod | None = None,
        specific: Sequence[str] | None = None,
        failing: bool = False,
        description: str = "",
        entry_kind: EntryKind = EntryKind.TRADE,
    ) -> list[RealisedLot]:
        instrument_id = instrument.instrument_id
        currency = instrument.currency.code
        held = self.lots.quantity(instrument_id)
        if quantity > held:
            raise ValidationError(f"{disposal_id}: cannot dispose of {quantity} {instrument_id}; {held} held")
        net = gross - costs
        rate = self.rate(currency, today)
        sold = self.lots.relieve(instrument_id, quantity, today, method=method, specific_lot_ids=specific)
        proceeds = allocate_pro_rata(net, [lot.quantity for lot in sold])
        accrued = self.money(accrued_per_unit(instrument, settles) * quantity, currency)
        receivable = net + accrued
        postings = [debit(Accounts.SALES_RECEIVABLE, receivable, currency, rate, instrument_id=instrument_id)]
        realised: list[RealisedLot] = []
        for lot, lot_proceeds in zip(sold, proceeds, strict=True):
            self.tracker.consume_sold(lot.transaction_id, lot.quantity)
            record = RealisedLot(
                portfolio_id=self.portfolio_id,
                instrument_id=instrument_id,
                lot_id=lot.lot_id,
                disposal_id=disposal_id,
                open_date=lot.open_date,
                holding_start=lot.holding_start,
                close_date=today,
                quantity=lot.quantity,
                currency=currency,
                proceeds=lot_proceeds,
                cost=lot.quantity * lot.cost_per_unit,
                open_fx_rate=lot.open_fx_rate,
                close_fx_rate=rate,
                wash_sale_basis=lot.wash_sale_adjustment * lot.quantity,
                kind=kind,
            )
            if self.engine.policy.wash_sales and kind is RealisationKind.SALE:
                record = self.apply_wash_sale(record)
            realised.append(record)
            gain_account = Accounts.REALISED_LONG_TERM if record.term is Term.LONG else Accounts.REALISED_SHORT_TERM
            postings.append(
                Posting(Accounts.INVESTMENTS.code, -record.cost, currency, -record.cost_base, instrument_id)
            )
            postings.append(Posting(gain_account.code, -record.gain, currency, -record.price_gain_base, instrument_id))
            if record.fx_gain_base:
                postings.append(
                    base_only(
                        Accounts.REALISED_FX_INVESTMENTS, -record.fx_gain_base, currency, instrument_id=instrument_id
                    )
                )
        if accrued:
            postings.extend(self._relieve_accrued(instrument_id, accrued, currency, rate, held, quantity))
        self.entry(f"{disposal_id}:T", today, entry_kind, postings, description, disposal_id)
        self.realised.extend(realised)
        self.movements.append(
            CashMovement(disposal_id, currency, receivable, today, settles, "sell", description, failing)
        )
        self.schedule(
            _Settlement(settles, disposal_id, Accounts.SALES_RECEIVABLE, currency, receivable, rate, "sale"), failing
        )
        activity = self.day(today)
        activity.trades.append(
            TradeActivity(
                disposal_id,
                instrument_id,
                -quantity,
                -gross,
                currency,
                kind.value if kind is not RealisationKind.SALE else "trade",
                -accrued,
            )
        )
        if costs:
            activity.costs[currency] += costs
        return realised

    def apply_wash_sale(self, record: RealisedLot) -> RealisedLot:
        matches = self.tracker.match(record)
        if not matches:
            return record
        for match in matches:
            if match.replacement_id in self.opened:
                self.lots.adjust_for_wash_sale(
                    record.instrument_id,
                    match.replacement_id,
                    match.quantity,
                    match.disallowed_per_unit,
                    match.tacked_days,
                )
            else:
                self.tracker.defer(match)
        return replace(record, disallowed_loss=decimal_sum(match.disallowed for match in matches))

    def _relieve_accrued(
        self, instrument_id: str, accrued: Decimal, currency: str, rate: Decimal, held: Decimal, quantity: Decimal
    ) -> list[Posting]:
        """Accrued interest sold: first recover the part that was bought, the rest is income."""
        balance = self.accrued_purchased[instrument_id]
        share = quantity / held if held else Decimal(0)
        local = min(balance[0] * share, accrued)
        base = balance[1] * local / balance[0] if balance[0] else Decimal(0)
        balance[0] -= local
        balance[1] -= base
        income = accrued - local
        postings: list[Posting] = []
        if local:
            postings.append(Posting(Accounts.ACCRUED_INTEREST_PURCHASED.code, -local, currency, -base, instrument_id))
        if income:
            postings.append(credit(Accounts.INTEREST_INCOME, income, currency, rate, instrument_id=instrument_id))
        plug = local * rate - base
        if plug:
            postings.append(base_only(Accounts.REALISED_FX_SETTLEMENT, -plug, currency, instrument_id=instrument_id))
        return postings

    # ------------------------------------------------------------------ settlement
    def settle(self, due: _Settlement, today: date) -> None:
        rate = self.rate(due.currency, today)
        difference = due.amount * (rate - due.trade_rate)
        if due.account is Accounts.PURCHASES_PAYABLE:
            postings = [
                Posting(due.account.code, due.amount, due.currency, due.amount * due.trade_rate),
                Posting(Accounts.CASH.code, -due.amount, due.currency, -(due.amount * rate)),
            ]
            if difference:
                postings.append(base_only(Accounts.REALISED_FX_SETTLEMENT, difference, due.currency))
        else:
            postings = [
                Posting(Accounts.CASH.code, due.amount, due.currency, due.amount * rate),
                Posting(due.account.code, -due.amount, due.currency, -(due.amount * due.trade_rate)),
            ]
            if difference:
                postings.append(base_only(Accounts.REALISED_FX_SETTLEMENT, -difference, due.currency))
        self.entry(
            f"{due.transaction_id}:S",
            today,
            EntryKind.SETTLEMENT,
            postings,
            f"settle {due.description} {due.transaction_id}",
            due.transaction_id,
        )

    # ------------------------------------------------------------------ cash
    def cash_flow(self, transaction: Transaction) -> None:
        currency = transaction.currency.code
        amount = self._amount(transaction)
        rate = self.rate(currency, transaction.trade_date)
        deposit = transaction.transaction_type is TransactionType.DEPOSIT
        signed = amount if deposit else -amount
        postings = (
            [debit(Accounts.CASH, amount, currency, rate), credit(Accounts.CONTRIBUTED_CAPITAL, amount, currency, rate)]
            if deposit
            else [
                debit(Accounts.CONTRIBUTED_CAPITAL, amount, currency, rate),
                credit(Accounts.CASH, amount, currency, rate),
            ]
        )
        self.entry(
            f"{transaction.transaction_id}:C",
            transaction.trade_date,
            EntryKind.CASH_MOVEMENT,
            postings,
            f"{transaction.transaction_type.value} {amount:,} {currency}",
            transaction.transaction_id,
        )
        self.movements.append(
            CashMovement(
                transaction.transaction_id,
                currency,
                signed,
                transaction.trade_date,
                transaction.trade_date,
                transaction.transaction_type.value,
                transaction.notes or "",
            )
        )
        self.day(transaction.trade_date).flows[currency] += signed

    def charge(self, transaction: Transaction) -> None:
        currency = transaction.currency.code
        amount = self._amount(transaction)
        rate = self.rate(currency, transaction.trade_date)
        expense = Accounts.FEES if transaction.transaction_type is TransactionType.FEE else Accounts.TRANSACTION_TAXES
        self.entry(
            f"{transaction.transaction_id}:C",
            transaction.trade_date,
            EntryKind.FEE,
            [debit(expense, amount, currency, rate), credit(Accounts.CASH, amount, currency, rate)],
            transaction.notes or f"{transaction.transaction_type.value} {amount:,} {currency}",
            transaction.transaction_id,
        )
        self.movements.append(
            CashMovement(
                transaction.transaction_id,
                currency,
                -amount,
                transaction.trade_date,
                transaction.trade_date,
                transaction.transaction_type.value,
                transaction.notes or "",
            )
        )
        self.day(transaction.trade_date).costs[currency] += amount

    def conversion(self, transaction: Transaction) -> None:
        sold_currency = transaction.currency.code
        bought_currency = transaction.metadata[BUY_CURRENCY]
        sold = self._amount(transaction)
        bought = (
            Decimal(transaction.metadata[BUY_AMOUNT])
            if BUY_AMOUNT in transaction.metadata
            else self.money(sold * transaction.price, bought_currency)
        )
        settles = transaction.settles_on
        for currency, amount in ((sold_currency, -sold), (bought_currency, bought)):
            self.movements.append(
                CashMovement(
                    transaction.transaction_id,
                    currency,
                    amount,
                    transaction.trade_date,
                    settles,
                    "fx",
                    f"sell {sold:,} {sold_currency} for {bought:,} {bought_currency}",
                    transaction.transaction_id in self.failing,
                )
            )
        if transaction.transaction_id in self.failing:
            return
        self._pending_conversions.setdefault(settles, []).append((transaction, sold, bought))

    @property
    def _pending_conversions(self) -> dict[date, list[tuple[Transaction, Decimal, Decimal]]]:
        if not hasattr(self, "_conversions"):
            self._conversions: dict[date, list[tuple[Transaction, Decimal, Decimal]]] = {}
        return self._conversions

    def _settle_conversions(self, today: date) -> None:
        for transaction, sold, bought in self._pending_conversions.pop(today, []):
            sold_currency = transaction.currency.code
            bought_currency = transaction.metadata[BUY_CURRENCY]
            sold_base = sold * self.rate(sold_currency, today)
            bought_base = bought * self.rate(bought_currency, today)
            postings = [
                Posting(Accounts.CASH.code, bought, bought_currency, bought_base),
                Posting(Accounts.CASH.code, -sold, sold_currency, -sold_base),
            ]
            if bought_base != sold_base:
                postings.append(base_only(Accounts.REALISED_FX_SETTLEMENT, sold_base - bought_base, self.engine.base))
            self.entry(
                f"{transaction.transaction_id}:S",
                today,
                EntryKind.CURRENCY_EXCHANGE,
                postings,
                f"sell {sold:,} {sold_currency} buy {bought:,} {bought_currency}",
                transaction.transaction_id,
                cross_currency=True,
            )
            self.day(today).conversions.append((sold_currency, sold, bought_currency, bought))

    # ------------------------------------------------------------------ transfers
    def transfer_in(self, transaction: Transaction) -> None:
        instrument = self.engine.instrument(transaction.instrument_id)
        currency = self._currency_of(transaction, instrument)
        today = transaction.trade_date
        acquired = date.fromisoformat(transaction.metadata.get(ACQUIRED, today.isoformat()))
        rate = (
            Decimal(transaction.metadata["open_fx_rate"])
            if "open_fx_rate" in transaction.metadata
            else self.rate(currency, acquired if acquired <= today else today)
        )
        cost = transaction.quantity * transaction.price
        self.entry(
            f"{transaction.transaction_id}:X",
            today,
            EntryKind.TRANSFER,
            [
                Posting(Accounts.INVESTMENTS.code, cost, currency, cost * rate, instrument.instrument_id),
                Posting(Accounts.TRANSFERRED_IN_KIND.code, -cost, currency, -(cost * rate), instrument.instrument_id),
            ],
            f"transfer in {transaction.quantity:,} {instrument.instrument_id}, acquired {acquired}",
            transaction.transaction_id,
        )
        self.lots.open(
            TaxLot(
                lot_id=transaction.transaction_id,
                instrument_id=instrument.instrument_id,
                open_date=today,
                quantity=transaction.quantity,
                cost_per_unit=transaction.price,
                currency=instrument.currency,
                transaction_id=transaction.transaction_id,
                holding_period_start=min(acquired, today),
                open_fx_rate=rate,
            )
        )
        self.day(today).trades.append(
            TradeActivity(
                transaction.transaction_id,
                instrument.instrument_id,
                transaction.quantity,
                Decimal(0),
                currency,
                "transfer",
            )
        )

    def transfer_out(self, transaction: Transaction) -> None:
        instrument = self.engine.instrument(transaction.instrument_id)
        currency = self._currency_of(transaction, instrument)
        today = transaction.trade_date
        specific = [transaction.lot_id] if transaction.lot_id else None
        lots = self.lots.relieve(instrument.instrument_id, transaction.quantity, today, specific_lot_ids=specific)
        for lot in lots:
            self.tracker.consume_sold(lot.transaction_id, lot.quantity)
        cost = decimal_sum(lot.quantity * lot.cost_per_unit for lot in lots)
        base = decimal_sum(lot.quantity * lot.base_cost_per_unit for lot in lots)
        self.entry(
            f"{transaction.transaction_id}:X",
            today,
            EntryKind.TRANSFER,
            [
                Posting(Accounts.TRANSFERRED_IN_KIND.code, cost, currency, base, instrument.instrument_id),
                Posting(Accounts.INVESTMENTS.code, -cost, currency, -base, instrument.instrument_id),
            ],
            f"transfer out {transaction.quantity:,} {instrument.instrument_id} at cost",
            transaction.transaction_id,
        )
        self.day(today).trades.append(
            TradeActivity(
                transaction.transaction_id,
                instrument.instrument_id,
                -transaction.quantity,
                Decimal(0),
                currency,
                "transfer",
            )
        )

    # ------------------------------------------------------------------ income
    def dividend_transaction(self, transaction: Transaction) -> None:
        instrument = self.engine.instrument(transaction.instrument_id)
        currency = transaction.currency.code
        gross = (
            self._amount(transaction)
            if transaction.gross_amount is not None
            else transaction.quantity * transaction.price
        )
        withheld = transaction.taxes
        reclaimable = Decimal(transaction.metadata.get(RECLAIMABLE, "0"))
        self.book_dividend(
            instrument.instrument_id,
            currency,
            self.money(gross, currency),
            withheld,
            reclaimable,
            transaction.trade_date,
            transaction.settles_on,
            transaction.transaction_id,
            f"dividend {instrument.instrument_id}",
        )

    def book_dividend(
        self,
        instrument_id: str,
        currency: str,
        gross: Decimal,
        withheld: Decimal,
        reclaimable: Decimal,
        ex_date: date,
        pay_date: date,
        source_id: str,
        description: str,
    ) -> None:
        rate = self.rate(currency, ex_date)
        net = gross - withheld
        expense = withheld - reclaimable
        postings = [
            debit(Accounts.DIVIDENDS_RECEIVABLE, net, currency, rate, instrument_id=instrument_id),
            credit(Accounts.DIVIDEND_INCOME, gross, currency, rate, instrument_id=instrument_id),
        ]
        if reclaimable:
            postings.append(debit(Accounts.TAX_RECLAIMABLE, reclaimable, currency, rate, instrument_id=instrument_id))
        if expense:
            postings.append(debit(Accounts.WITHHOLDING_TAX, expense, currency, rate, instrument_id=instrument_id))
        self.entry(f"{source_id}:D", ex_date, EntryKind.INCOME, postings, description, source_id)
        self.movements.append(CashMovement(source_id, currency, net, ex_date, pay_date, "dividend", description))
        self.schedule(
            _Settlement(pay_date, source_id, Accounts.DIVIDENDS_RECEIVABLE, currency, net, rate, "dividend"), False
        )
        activity = self.day(ex_date)
        activity.income[currency] += gross
        if expense:
            activity.costs[currency] += expense

    def coupon(self, bond: Bond, per_unit: Decimal, today: date) -> None:
        quantity = self.lots.quantity(bond.instrument_id)
        if quantity <= 0:
            return
        currency = bond.currency.code
        amount = self.money(per_unit * quantity, currency)
        self._receive_interest(
            bond.instrument_id, currency, amount, today, f"{bond.instrument_id}-CPN-{today.isoformat()}"
        )

    def interest_transaction(self, transaction: Transaction) -> None:
        currency = transaction.currency.code
        amount = (
            self._amount(transaction)
            if transaction.gross_amount is not None
            else transaction.quantity * transaction.price
        )
        self._receive_interest(
            transaction.instrument_id or currency,
            currency,
            self.money(amount, currency),
            transaction.trade_date,
            transaction.transaction_id,
        )

    def _receive_interest(
        self, instrument_id: str, currency: str, amount: Decimal, today: date, source_id: str
    ) -> None:
        rate = self.rate(currency, today)
        balance = self.accrued_purchased[instrument_id]
        recovered = min(balance[0], amount)
        recovered_base = balance[1] * recovered / balance[0] if balance[0] else Decimal(0)
        balance[0] -= recovered
        balance[1] -= recovered_base
        income = amount - recovered
        postings = [debit(Accounts.CASH, amount, currency, rate, instrument_id=instrument_id)]
        if recovered:
            postings.append(
                Posting(Accounts.ACCRUED_INTEREST_PURCHASED.code, -recovered, currency, -recovered_base, instrument_id)
            )
        if income:
            postings.append(credit(Accounts.INTEREST_INCOME, income, currency, rate, instrument_id=instrument_id))
        plug = recovered * rate - recovered_base
        if plug:
            postings.append(base_only(Accounts.REALISED_FX_SETTLEMENT, -plug, currency, instrument_id=instrument_id))
        self.entry(f"{source_id}:I", today, EntryKind.INCOME, postings, f"coupon {instrument_id}", source_id)
        self.movements.append(
            CashMovement(source_id, currency, amount, today, today, "interest", f"coupon {instrument_id}")
        )
        self.day(today).income[currency] += amount

    # ------------------------------------------------------------------ corporate actions
    def corporate_action(self, action: CorporateAction) -> None:
        instrument_id = action.instrument_id
        before = self.lots.quantity(instrument_id)
        if before <= 0 and not isinstance(action, CashDividend):
            return
        notes: tuple[str, ...] = ()
        if isinstance(action, CashDividend):
            notes = self._cash_dividend(action)
        elif isinstance(action, (StockSplit, StockDividend)):
            notes = self._share_multiplier(action)
        elif isinstance(action, SpinOff):
            notes = self._spin_off(action)
        elif isinstance(action, CashMerger):
            notes = self._cash_merger(action)
        elif isinstance(action, StockMerger):
            notes = self._stock_merger(action)
        elif isinstance(action, (RightsIssue, SymbolChange)):
            notes = (f"{action.describe()}: no change to the book",)
        if notes:
            self.records.append(
                CorporateActionRecord(
                    action.action_id,
                    instrument_id,
                    action.ex_date,
                    action.action_type.value,
                    notes,
                    before,
                    self.lots.quantity(instrument_id),
                )
            )

    def _cash_dividend(self, action: CashDividend) -> tuple[str, ...]:
        entitled, _ = entitled_lots(self.lots.lots(action.instrument_id), action)
        quantity = decimal_sum(lot.quantity for lot in entitled)
        if quantity <= 0:
            return ()
        instrument = self.engine.instrument(action.instrument_id)
        currency = action.currency
        gross = self.money(quantity * action.amount, currency)
        if action.withholding_rate > 0:
            withheld = self.money(gross * action.withholding_rate, currency)
            parts = (withheld, Decimal(0))
        else:
            rate = self.engine.policy.withholding.rate_for(instrument.country)
            split = split_dividend(
                gross, rate, reclaim=self.engine.policy.withholding.reclaim, precision=self.precision(currency)
            )
            parts = (split.withheld, split.reclaimable)
        self.book_dividend(
            action.instrument_id,
            currency,
            gross,
            parts[0],
            parts[1],
            action.ex_date,
            action.pay_date or action.ex_date,
            f"{action.action_id}-{self.portfolio_id}",
            f"dividend {action.amount} x {quantity:,} {action.instrument_id}",
        )
        return (
            f"{quantity:,} shares entitled; gross {gross:,} {currency}, "
            f"withheld {parts[0]:,}, reclaimable {parts[1]:,}",
        )

    def _share_multiplier(self, action: StockSplit | StockDividend) -> tuple[str, ...]:
        instrument = self.engine.instrument(action.instrument_id)
        result = apply_action(
            action, self.lots.lots(action.instrument_id), portfolio_id=self.portfolio_id, whole_shares=False
        )
        self.lots.replace_instrument(
            action.instrument_id, [lot for lot in result.lots_after if lot.instrument_id == action.instrument_id]
        )
        total = self.lots.quantity(action.instrument_id)
        fraction = total - total.to_integral_value(rounding=ROUND_DOWN)
        notes = list(result.notes)
        if fraction > 0:
            price = self._price(action.instrument_id, action.ex_date)
            gross = self.money(fraction * price * instrument_price_scale(instrument), instrument.currency.code)
            self.dispose(
                instrument,
                fraction,
                gross,
                Decimal(0),
                action.ex_date,
                action.pay_date or action.ex_date,
                f"{action.action_id}-{self.portfolio_id}-CIL",
                kind=RealisationKind.CASH_IN_LIEU,
                method=LotSelectionMethod.LIFO,
                description=f"cash in lieu of {fraction} {action.instrument_id}",
                entry_kind=EntryKind.CORPORATE_ACTION,
            )
            notes.append(f"{fraction} fractional shares sold for cash in lieu at {price}")
        return tuple(notes)

    def _spin_off(self, action: SpinOff) -> tuple[str, ...]:
        parent = self.engine.instrument(action.instrument_id)
        child = self.engine.instrument(action.child_instrument_id)
        if child.currency != parent.currency:
            raise ValidationError(f"{action.action_id}: a spin-off into another currency is not supported")
        lots = self.lots.lots(action.instrument_id)
        cum = self._price(action.instrument_id, action.ex_date) if action.cost_allocation is None else None
        result = apply_action(action, lots, portfolio_id=self.portfolio_id, ex_price=cum)
        parents = [lot for lot in result.lots_after if lot.instrument_id == action.instrument_id]
        children = [lot for lot in result.lots_after if lot.instrument_id == action.child_instrument_id]
        self.lots.replace_instrument(action.instrument_id, parents)
        for lot in children:
            self.lots.open(lot)
        currency = parent.currency.code
        moved = decimal_sum(lot.quantity * lot.cost_per_unit for lot in children)
        moved_base = decimal_sum(lot.quantity * lot.base_cost_per_unit for lot in children)
        if moved:
            self.entry(
                f"{action.action_id}-{self.portfolio_id}:CA",
                action.ex_date,
                EntryKind.CORPORATE_ACTION,
                [
                    Posting(Accounts.INVESTMENTS.code, moved, currency, moved_base, child.instrument_id),
                    Posting(Accounts.INVESTMENTS.code, -moved, currency, -moved_base, parent.instrument_id),
                ],
                f"spin-off of {child.instrument_id}: basis moved from {parent.instrument_id}",
                action.action_id,
            )
        return result.notes

    def _cash_merger(self, action: CashMerger) -> tuple[str, ...]:
        instrument = self.engine.instrument(action.instrument_id)
        quantity = self.lots.quantity(action.instrument_id)
        gross = self.money(quantity * action.cash_per_share, instrument.currency.code)
        self.dispose(
            instrument,
            quantity,
            gross,
            Decimal(0),
            action.ex_date,
            action.pay_date or action.ex_date,
            f"{action.action_id}-{self.portfolio_id}",
            kind=RealisationKind.CASH_MERGER,
            description=f"cash merger at {action.cash_per_share}",
            entry_kind=EntryKind.CORPORATE_ACTION,
        )
        return (f"{quantity:,} shares taken out at {action.cash_per_share} in cash",)

    def _stock_merger(self, action: StockMerger) -> tuple[str, ...]:
        target = self.engine.instrument(action.instrument_id)
        acquirer = self.engine.instrument(action.acquirer_instrument_id)
        currency = target.currency.code
        lots = self.lots.lots(action.instrument_id)
        price = self._price(acquirer.instrument_id, action.ex_date) if action.cash_per_share > 0 else None
        result = apply_action(action, lots, portfolio_id=self.portfolio_id, acquirer_price=price)
        self.lots.replace_instrument(
            action.instrument_id, [lot for lot in result.lots_after if lot.instrument_id == action.instrument_id]
        )
        new_lots = [lot for lot in result.lots_after if lot.instrument_id == acquirer.instrument_id]
        for lot in new_lots:
            self.lots.open(lot)
        old_cost = decimal_sum(lot.quantity * lot.cost_per_unit for lot in result.lots_before)
        old_base = decimal_sum(lot.quantity * lot.base_cost_per_unit for lot in result.lots_before)
        new_cost = decimal_sum(lot.quantity * lot.cost_per_unit for lot in new_lots)
        new_base = decimal_sum(lot.quantity * lot.base_cost_per_unit for lot in new_lots)
        rate = self.rate(currency, action.ex_date)
        boot = result.cash_total
        postings = [
            Posting(Accounts.INVESTMENTS.code, new_cost, currency, new_base, acquirer.instrument_id),
            Posting(Accounts.INVESTMENTS.code, -old_cost, currency, -old_base, target.instrument_id),
        ]
        if boot:
            postings.append(debit(Accounts.SALES_RECEIVABLE, boot, currency, rate, instrument_id=target.instrument_id))
            pay_date = action.pay_date or action.ex_date
            self.movements.append(
                CashMovement(action.action_id, currency, boot, action.ex_date, pay_date, "sell", "merger cash")
            )
            self.schedule(
                _Settlement(pay_date, action.action_id, Accounts.SALES_RECEIVABLE, currency, boot, rate, "merger cash"),
                False,
            )
            self.day(action.ex_date).trades.append(
                TradeActivity(action.action_id, target.instrument_id, Decimal(0), -boot, currency, "merger")
            )
        for amount, ledger_account in (
            (result.realised_long_term, Accounts.REALISED_LONG_TERM),
            (result.realised_short_term, Accounts.REALISED_SHORT_TERM),
        ):
            if amount:
                postings.append(credit(ledger_account, amount, currency, rate, instrument_id=target.instrument_id))
        residual = -decimal_sum(posting.base_amount for posting in postings)
        if residual:
            postings.append(
                base_only(Accounts.REALISED_FX_INVESTMENTS, residual, currency, instrument_id=target.instrument_id)
            )
        self.entry(
            f"{action.action_id}-{self.portfolio_id}:CA",
            action.ex_date,
            EntryKind.CORPORATE_ACTION,
            postings,
            f"{target.instrument_id} exchanged into {acquirer.instrument_id}",
            action.action_id,
        )
        return result.notes

    # ------------------------------------------------------------------ small helpers
    def _price(self, instrument_id: str, day: date) -> Decimal:
        price = self.engine.prices.price(instrument_id, day) if self.engine.prices else None
        if price is None:
            raise ValidationError(f"{instrument_id} has no price on {day}, which this corporate action needs")
        return price

    @staticmethod
    def _amount(transaction: Transaction) -> Decimal:
        amount = (
            transaction.gross_amount
            if transaction.gross_amount is not None
            else transaction.quantity * transaction.price
        )
        if amount <= 0:
            raise ValidationError(f"{transaction.transaction_id}: the amount must be positive")
        return amount

    @staticmethod
    def _currency_of(transaction: Transaction, instrument: Instrument) -> str:
        if transaction.currency != instrument.currency:
            raise ValidationError(
                f"{transaction.transaction_id}: {instrument.instrument_id} settles in {instrument.currency.code}, "
                f"not {transaction.currency.code}"
            )
        return instrument.currency.code
