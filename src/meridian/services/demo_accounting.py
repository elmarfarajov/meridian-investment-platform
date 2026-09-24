"""The demonstration book of record, end to end.

One function turns the Day 2 demonstration market into two and a half years
of a real-looking portfolio's life, and books it:

* The Aliyeva family's **Global Equity Core** account - a US person resident
  in the UK, so every disposal is reported under both tax codes - funded with
  five million dollars in April 2024 and a further half million in March 2025.
* An initial allocation across ten holdings in four currencies, a US Treasury
  among them, funded by spot conversions; quarterly rebalancing back to target
  weights with commissions, UK stamp duty and European broker fees.
* Shares of Apple **transferred in** from a previous broker with their 2021
  cost and acquisition date, so they are long-term from the day they arrive.
* A **tax-loss harvest** done right (Johnson & Johnson sold at a loss and the
  exposure kept through the S&P 500 ETF, which is not substantially
  identical) and one done wrong (Bayer sold at a loss and bought back twenty
  days later - a wash sale).
* Management and custody fees, a client distribution, a trade whose price is
  corrected the next morning and a purchase whose settlement fails for three
  days.
* Every dividend in the market's corporate action feed, with German and Swiss
  withholding split into reclaimable and lost, and the 4-for-1 split.

Everything is deterministic: the same seed always gives the same book to the
cent, so the charts, the CLI and the tests show the same numbers.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from functools import cached_property, lru_cache

from ..accounting.blotter import TradeBlotter
from ..accounting.bridge import ValueBridge, value_bridge
from ..accounting.builders import cash_transaction, fx_conversion, purchase, sale, transfer_in
from ..accounting.custodian import PlantedBreak, ReconciliationScore, SyntheticCustodian, run_reconciliation
from ..accounting.engine import AccountingEngine, AccountingPolicy
from ..accounting.reconciliation import BreakRegister, Reconciler
from ..accounting.settlement import SettlementRules
from ..accounting.sources import HistoryFx, SeriesPrices
from ..accounting.tax import TaxYearSummary, tax_years
from ..accounting.uk_matching import UkMatchingResult, match_disposals
from ..accounting.valuation import PortfolioValuation, Valuator
from ..analytics.bonds import FixedRateBond
from ..core.calendars import JointCalendar, get_calendar
from ..core.currency import USD
from ..core.enums import AccountType, LotSelectionMethod, TransactionType
from ..domain.instruments import Bond, Instrument, instrument_price_scale
from ..domain.portfolios import Account, InvestmentPolicy, Portfolio
from ..domain.transactions import Transaction
from ..marketdata.fx_history import FxHistory
from ..marketdata.series import TimeSeries
from ..seed import demo_instruments
from .demo_market import DEMO_END, DEMO_START, DemoMarket, build_demo_market

PORTFOLIO_ID = "PF-GLOBAL-EQ"
ACCOUNT_ID = "AC-0001"
BOND_ID = "US-T-2032"

#: Target weights of NAV; the remainder is held as cash.
TARGET_WEIGHTS: dict[str, Decimal] = {
    "US-AAPL": Decimal("0.11"),
    "US-MSFT": Decimal("0.11"),
    "US-JNJ": Decimal("0.07"),
    "US-IVV": Decimal("0.17"),
    "IE-IWDA": Decimal("0.10"),
    "DEMO-SPLIT": Decimal("0.05"),
    "DE-BAYN": Decimal("0.07"),
    "GB-BAE": Decimal("0.07"),
    "CH-ROG": Decimal("0.06"),
    BOND_ID: Decimal("0.14"),
}
REBALANCE_BAND = Decimal("0.10")  # trade a holding more than 10% away from its target weight
BOOKED_AT_HOUR = 20  # trades are booked into the blotter at 20:00 UTC on the trade date


def demo_portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=PORTFOLIO_ID,
        name="Global Equity Core",
        base_currency=USD,
        account_id=ACCOUNT_ID,
        benchmark_id="MSCI-WORLD",
        strategy="global-equity",
        inception=DEMO_START,
        policy=InvestmentPolicy(
            target_equity_weight=Decimal("0.80"),
            max_single_issuer_weight=Decimal("0.15"),
            max_cash_weight=Decimal("0.08"),
        ),
    )


def demo_account() -> Account:
    return Account(
        account_id=ACCOUNT_ID,
        name="Aliyeva Taxable Brokerage",
        account_type=AccountType.TAXABLE,
        base_currency=USD,
        household_id="HH-0001",
        client_id="CL-0001",
        custodian="Northern Trust",
        opened=date(2024, 3, 1),
    )


# ---------------------------------------------------------------------------- the bond's prices
def treasury_prices(bond: Bond, start: date, end: date, *, seed: int = 29) -> TimeSeries:
    """Clean prices for the Treasury from a seeded yield path, priced by the analytics layer.

    The yield starts at 4.35% and moves by a few basis points a day with mild
    mean reversion towards 4.2%, which is enough to give the bond a realistic
    price history without a curve model the accounting does not need.
    """
    assert bond.issue_date is not None and bond.maturity is not None
    analytic = FixedRateBond.create(
        issue_date=bond.issue_date,
        maturity=bond.maturity,
        coupon_rate=float(bond.coupon),
        frequency=bond.coupon_frequency,
        day_count=bond.day_count,
        name=bond.instrument_id,
    )
    rng = random.Random(seed)
    calendar = get_calendar("SIFMA")
    level = 0.0435
    points: list[tuple[date, Decimal]] = []
    for day in calendar.business_days(start, end):
        level += 0.03 * (0.042 - level) + rng.gauss(0.0, 0.00045)
        price = analytic.clean_price_from_yield(level, day)
        points.append((day, Decimal(f"{price:.4f}")))
    return TimeSeries(points, name=f"{bond.instrument_id} clean")


# ---------------------------------------------------------------------------- the transaction history
@dataclass
class _Desk:
    """A small order generator with its own running view of the holdings and cash."""

    market: DemoMarket
    instruments: dict[str, Instrument]
    prices: SeriesPrices
    fx: FxHistory
    transactions: list[Transaction] = field(default_factory=list)
    quantity: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    cash: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    counter: int = 0

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter:04d}"

    def rate(self, currency: str, day: date) -> Decimal:
        return Decimal(1) if currency == "USD" else self.fx.rate(currency, "USD", day)

    def close(self, instrument_id: str, day: date) -> Decimal:
        price = self.prices.price(instrument_id, day)
        if price is None:
            raise ValueError(f"no price for {instrument_id} on {day}")
        return price

    def execution_price(self, instrument_id: str, day: date, buying: bool) -> Decimal:
        """The close, a couple of basis points worse for the side taken, at the instrument's tick."""
        close = self.close(instrument_id, day)
        rng = random.Random(f"{instrument_id}-{day.isoformat()}")
        slip = Decimal(repr(round(rng.uniform(0.5, 3.0) / 10_000, 6)))
        price = close * (1 + slip if buying else 1 - slip)
        places = (
            Decimal("0.001") if instrument_id == "GB-BAE" else Decimal("0.0001" if instrument_id == BOND_ID else "0.01")
        )
        return price.quantize(places, rounding=ROUND_HALF_EVEN)

    def costs(self, instrument: Instrument, quantity: Decimal, gross: Decimal, buying: bool) -> tuple[Decimal, Decimal]:
        """Commission and transaction tax, by market."""
        if instrument.instrument_id == BOND_ID:
            return Decimal("0.00"), Decimal("0.00")
        if instrument.currency.code == "USD" and (instrument.country or "US") == "US":
            return max(Decimal("1.00"), (quantity * Decimal("0.005")).quantize(Decimal("0.01"))), Decimal("0.00")
        commission = max(Decimal("5.00"), (gross * Decimal("0.0005")).quantize(Decimal("0.01")))
        stamp = (
            (gross * Decimal("0.005")).quantize(Decimal("0.01"))
            if buying and instrument.country == "GB"
            else Decimal(0)
        )
        return commission, stamp

    # ------------------------------------------------------------------ orders
    def deposit(self, day: date, amount: str) -> None:
        self.transactions.append(
            cash_transaction(
                transaction_id=self.next_id("DEP"),
                portfolio_id=PORTFOLIO_ID,
                kind=TransactionType.DEPOSIT,
                day=day,
                amount=amount,
                currency="USD",
                notes="client contribution",
            )
        )
        self.cash["USD"] += Decimal(amount)

    def cash_out(self, day: date, kind: TransactionType, amount: str, notes: str) -> None:
        self.transactions.append(
            cash_transaction(
                transaction_id=self.next_id(kind.value[:3].upper()),
                portfolio_id=PORTFOLIO_ID,
                kind=kind,
                day=day,
                amount=amount,
                currency="USD",
                notes=notes,
            )
        )
        self.cash["USD"] -= Decimal(amount)

    def convert(self, day: date, currency: str, amount: Decimal, *, to_usd: bool = False) -> None:
        """Buy ``amount`` of ``currency`` with dollars, or sell it for dollars, at the day's rate less a spread."""
        rate = self.rate(currency, day)
        spread = Decimal("0.0003")
        if to_usd:
            usd = (amount * rate * (1 - spread)).quantize(Decimal("0.01"))
            self.transactions.append(
                fx_conversion(
                    transaction_id=self.next_id("FX"),
                    portfolio_id=PORTFOLIO_ID,
                    trade_date=day,
                    sell_currency=currency,
                    sell_amount=amount,
                    buy_currency="USD",
                    rate=(usd / amount).quantize(Decimal("0.00000001")),
                )
            )
            self.cash[currency] -= amount
            self.cash["USD"] += usd
            return
        usd = (amount * rate * (1 + spread)).quantize(Decimal("0.01"))
        self.transactions.append(
            fx_conversion(
                transaction_id=self.next_id("FX"),
                portfolio_id=PORTFOLIO_ID,
                trade_date=day,
                sell_currency="USD",
                sell_amount=usd,
                buy_currency=currency,
                rate=(amount / usd).quantize(Decimal("0.00000001")),
            )
        )
        self.cash["USD"] -= usd
        self.cash[currency] += amount

    def trade(
        self, instrument_id: str, day: date, quantity: Decimal, *, prefix: str = "T", notes: str | None = None
    ) -> str:
        instrument = self.instruments[instrument_id]
        buying = quantity > 0
        size = abs(quantity)
        price = self.execution_price(instrument_id, day, buying)
        gross = size * price * instrument_price_scale(instrument)
        fees, taxes = self.costs(instrument, size, gross, buying)
        currency = instrument.currency.code
        shortfall = gross + fees + taxes - self.cash[currency]
        if buying and currency != "USD" and shortfall > 0:
            # fund a foreign purchase with a spot conversion on the same day; both settle T+2
            self.convert(day, currency, shortfall.quantize(Decimal("1"), rounding=ROUND_DOWN) + 100)
        tid = self.next_id(prefix)
        builder = purchase if buying else sale
        self.transactions.append(
            builder(
                transaction_id=tid,
                portfolio_id=PORTFOLIO_ID,
                instrument_id=instrument_id,
                day=day,
                quantity=size,
                price=price,
                currency=instrument.currency.code,
                fees=fees,
                taxes=taxes,
                notes=notes,
            )
        )
        self.quantity[instrument_id] += quantity
        self.cash[instrument.currency.code] -= (gross + fees + taxes) if buying else -(gross - fees - taxes)
        return tid

    # ------------------------------------------------------------------ portfolio arithmetic
    def value(self, instrument_id: str, day: date) -> Decimal:
        instrument = self.instruments[instrument_id]
        return (
            self.quantity[instrument_id]
            * self.close(instrument_id, day)
            * instrument_price_scale(instrument)
            * self.rate(instrument.currency.code, day)
        )

    def nav(self, day: date) -> Decimal:
        securities = sum((self.value(key, day) for key, held in self.quantity.items() if held), Decimal(0))
        cash = sum((amount * self.rate(currency, day) for currency, amount in self.cash.items()), Decimal(0))
        return securities + cash

    def rebalance(self, day: date, *, band: Decimal = REBALANCE_BAND, initial: bool = False) -> None:
        nav = self.nav(day)
        orders: dict[str, Decimal] = {}
        for instrument_id, weight in TARGET_WEIGHTS.items():
            if self.prices.price(instrument_id, day) is None:
                continue
            target = weight * nav
            current = self.value(instrument_id, day)
            if not initial and abs(current - target) <= band * target:
                continue
            instrument = self.instruments[instrument_id]
            unit = (
                self.close(instrument_id, day)
                * instrument_price_scale(instrument)
                * self.rate(instrument.currency.code, day)
            )
            change = ((target - current) / unit).to_integral_value(rounding=ROUND_DOWN)
            if change:
                orders[instrument_id] = change
        # sales first, so their proceeds fund the purchases
        for instrument_id, change in sorted(orders.items(), key=lambda item: item[1]):
            if change < 0:
                self.trade(instrument_id, day, change, prefix="RB")
        for instrument_id, change in sorted(orders.items()):
            if change > 0:
                self.trade(instrument_id, day, change, prefix="RB")
        # sweep foreign cash beyond a small working balance back into dollars
        for currency in ("EUR", "GBP", "CHF"):
            working = nav * Decimal("0.004") / self.rate(currency, day)
            excess = (self.cash[currency] - working).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if excess > 1000:
                self.convert(day, currency, excess, to_usd=True)


def _business_day(calendar: JointCalendar, day: date) -> date:
    return day if calendar.is_business_day(day) else calendar.adjust(day)


def _first_loss_day(desk: _Desk, instrument_id: str, after: date, threshold: Decimal) -> date:
    """The first day after ``after`` when the holding trades below ``threshold`` times its entry price."""
    series = desk.prices.series(instrument_id)
    assert series is not None
    entry = desk.close(instrument_id, DEMO_START + timedelta(days=2))
    for point in series:
        if point.day > after and point.value < entry * threshold:
            return point.day
    return after + timedelta(days=30)


def demo_transactions(market: DemoMarket, prices: SeriesPrices, fx: FxHistory) -> list[Transaction]:
    """The account's whole transaction history, generated deterministically from the market."""
    instruments = {item.instrument_id: item for item in demo_instruments()}
    desk = _Desk(market, instruments, prices, fx)
    trading = JointCalendar(["XNYS", "XLON", "TARGET"], name="demo-trading")

    start = _business_day(trading, DEMO_START)
    desk.deposit(start, "5000000.00")
    first = trading.add_business_days(start, 2)
    for currency, amount in (("EUR", Decimal(700_000)), ("GBP", Decimal(290_000)), ("CHF", Decimal(270_000))):
        desk.convert(start, currency, amount)
    desk.rebalance(first, initial=True)

    desk.transactions.append(
        transfer_in(
            transaction_id="TIN-0001",
            portfolio_id=PORTFOLIO_ID,
            instrument_id="US-AAPL",
            day=date(2024, 5, 15),
            quantity=400,
            cost_per_unit="125.00",
            currency="USD",
            acquired=date(2021, 3, 10),
            open_fx_rate="1",
        )
    )
    desk.quantity["US-AAPL"] += 400

    events: list[tuple[date, str]] = []
    for year in (2024, 2025, 2026):
        for month in (1, 4, 7, 10):
            day = date(year, month, 1)
            if first < day <= DEMO_END:
                events.append((_business_day(trading, day), "rebalance"))
                events.append((_business_day(trading, day + timedelta(days=14)), "fees"))
    events.append((_business_day(trading, date(2025, 3, 3)), "deposit"))
    events.append((_business_day(trading, date(2025, 12, 15)), "distribution"))
    harvest_right = _business_day(trading, _first_loss_day(desk, "US-JNJ", date(2024, 8, 1), Decimal("0.90")))
    harvest_wrong = _business_day(trading, _first_loss_day(desk, "DE-BAYN", date(2024, 11, 1), Decimal("0.80")))
    events.append((harvest_right, "harvest-right"))
    events.append((harvest_wrong, "harvest-wrong"))
    events.append((trading.add_business_days(harvest_wrong, 14), "wash-rebuy"))
    wrong_held = Decimal(0)

    for day, kind in sorted(events):
        if kind == "rebalance":
            desk.rebalance(day)
        elif kind == "fees":
            desk.cash_out(
                day, TransactionType.FEE, f"{desk.nav(day) * Decimal('0.0025') / 4:.2f}", "quarterly management fee"
            )
            desk.cash_out(day, TransactionType.FEE, "450.00", "custody fee")
        elif kind == "deposit":
            desk.deposit(day, "500000.00")
        elif kind == "distribution":
            desk.cash_out(day, TransactionType.WITHDRAWAL, "250000.00", "distribution to the client")
        elif kind == "harvest-right":
            held = desk.quantity["US-JNJ"]
            sold_value = held * desk.close("US-JNJ", day)
            desk.trade("US-JNJ", day, -held, prefix="TLH", notes="tax-loss harvest: exposure kept through IVV")
            units = (sold_value / desk.close("US-IVV", day)).to_integral_value(rounding=ROUND_DOWN)
            desk.trade("US-IVV", day, units, prefix="TLH", notes="replacement exposure, not substantially identical")
        elif kind == "harvest-wrong":
            wrong_held = desk.quantity["DE-BAYN"]
            desk.trade("DE-BAYN", day, -wrong_held, prefix="TLH", notes="tax-loss harvest")
        elif kind == "wash-rebuy":
            desk.trade("DE-BAYN", day, wrong_held, prefix="TLH", notes="bought back within 30 days: a wash sale")
    return sorted(desk.transactions, key=lambda item: (item.trade_date, item.transaction_id))


# ---------------------------------------------------------------------------- the blotter
AMENDED_PRICE_NOTE = "price corrected the next morning"


def demo_blotter(transactions: list[Transaction]) -> TradeBlotter:
    """Every transaction booked on its trade date, one price corrected and one settlement failed."""
    blotter = TradeBlotter()
    for item in transactions:
        blotter.book(
            item, datetime.combine(item.trade_date, datetime.min.time(), timezone.utc) + timedelta(hours=BOOKED_AT_HOUR)
        )
    trades = [
        item
        for item in transactions
        if item.transaction_type is TransactionType.BUY and item.instrument_id == "US-MSFT"
    ]
    if len(trades) >= 2:
        corrected = trades[1]
        wrong = replace(corrected, price=(corrected.price * Decimal("1.01")).quantize(Decimal("0.01")))
        # the version booked that evening carried a price one percent too high
        blotter = TradeBlotter()
        for item in transactions:
            booked_at = datetime.combine(item.trade_date, datetime.min.time(), timezone.utc) + timedelta(
                hours=BOOKED_AT_HOUR
            )
            blotter.book(wrong if item.transaction_id == corrected.transaction_id else item, booked_at)
        blotter.amend(
            corrected,
            datetime.combine(corrected.trade_date + timedelta(days=1), datetime.min.time(), timezone.utc)
            + timedelta(hours=9),
            reason=AMENDED_PRICE_NOTE,
        )
    late = [
        item for item in transactions if item.transaction_type is TransactionType.BUY and item.instrument_id == "CH-ROG"
    ]
    if late:
        failed = late[-1]
        rules = SettlementRules()
        instrument = {item.instrument_id: item for item in demo_instruments()}["CH-ROG"]
        contractual = rules.settlement_date(instrument, failed.trade_date)
        calendar = rules.calendar_for(instrument)
        blotter.fail(
            failed.transaction_id,
            actual=calendar.add_business_days(contractual, 3),
            contractual=contractual,
            reason="counterparty short of stock",
        )
    return blotter


# ---------------------------------------------------------------------------- the whole thing
@dataclass
class DemoAccounting:
    market: DemoMarket
    portfolio: Portfolio
    instruments: dict[str, Instrument]
    prices: SeriesPrices
    fx: HistoryFx
    transactions: list[Transaction]
    blotter: TradeBlotter
    engine: AccountingEngine
    end: date = DEMO_END

    @cached_property
    def book(self):  # type: ignore[no-untyped-def]
        return self.engine.run(self.blotter.as_known_at(), self.market.actions, until=self.end)

    @cached_property
    def valuator(self) -> Valuator:
        return Valuator(self.book, self.instruments, self.prices, self.fx)

    @cached_property
    def valuation_days(self) -> list[date]:
        first = self.book.first_day or DEMO_START
        return self.valuator.valuation_days(first, self.end, "XNYS")

    @cached_property
    def valuations(self) -> list[PortfolioValuation]:
        return [self.valuator.value(day) for day in self.valuation_days]

    def valuation_on(self, day: date) -> PortfolioValuation:
        return self.valuator.value(day)

    @cached_property
    def daily_bridges(self) -> list[ValueBridge]:
        return value_bridge(self.valuator, self.valuation_days)[1]

    def bridge(self, start: date, end: date) -> ValueBridge:
        """The bridge between two valuation dates, summed from the daily steps."""
        steps = [step for step in self.daily_bridges if start <= step.start and step.end <= end]
        if not steps:
            raise ValueError(f"no valuation days between {start} and {end}")
        total = steps[0]
        for step in steps[1:]:
            total = total + step
        return total

    @cached_property
    def us_tax_years(self) -> list[TaxYearSummary]:
        return tax_years(self.book.realised)

    @cached_property
    def uk_matching(self) -> UkMatchingResult:
        return match_disposals(self.book.transactions, self.instruments, self.fx, actions=self.market.actions)

    @cached_property
    def custodian(self) -> SyntheticCustodian:
        return SyntheticCustodian(self.book, self.instruments, self.prices)

    @cached_property
    def reconciler(self) -> Reconciler:
        return Reconciler(self.book, self.instruments, self.prices, self.fx)

    def reconciliation_days(self, start: date = date(2026, 3, 2), end: date = date(2026, 8, 31)) -> list[date]:
        return [day for day in self.valuation_days if start <= day <= end]

    @cached_property
    def planted_breaks(self) -> list[PlantedBreak]:
        return self.custodian.random_plan(self.reconciliation_days(), per_cause=5, seed=11)

    @cached_property
    def reconciliation(self) -> tuple[BreakRegister, ReconciliationScore]:
        return run_reconciliation(self.reconciler, self.custodian, self.reconciliation_days(), self.planted_breaks)


@lru_cache(maxsize=2)
def build_demo_accounting(seed: int = 7) -> DemoAccounting:
    market = build_demo_market(seed=seed)
    instruments = {item.instrument_id: item for item in demo_instruments()}
    bond = instruments[BOND_ID]
    assert isinstance(bond, Bond)
    prices = SeriesPrices.from_dataset(market.clean).with_series(BOND_ID, treasury_prices(bond, DEMO_START, DEMO_END))
    history = FxHistory.from_dataset(market.clean)
    fx = HistoryFx(history)
    transactions = demo_transactions(market, prices, history)
    blotter = demo_blotter(transactions)
    engine = AccountingEngine(
        demo_portfolio(),
        instruments,
        fx,
        prices=prices,
        policy=AccountingPolicy(lot_method=LotSelectionMethod.FIFO, wash_sales=True),
    )
    return DemoAccounting(market, demo_portfolio(), instruments, prices, fx, transactions, blotter, engine)
