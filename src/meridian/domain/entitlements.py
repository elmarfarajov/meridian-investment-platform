"""Applying corporate actions to tax lots.

Adjusting a price history is arithmetic; adjusting a *holding* has tax
consequences, and the rules are specific:

* **Splits and stock dividends** change the share count and the cost per share
  but not the total cost, and the holding period *tacks*: new shares inherit
  the acquisition date of the old ones. Fractional shares are not delivered;
  they are sold and paid as *cash in lieu*, which is a (small) realised gain or
  loss.
* **Spin-offs** divide the cost basis between parent and child by relative
  market value, using the fraction the issuer publishes. The child lots inherit
  the parent's acquisition dates. Total cost is conserved to the cent.
* **Cash dividends** leave the lots alone and produce cash, less any tax
  withheld at source, on the pay date - entitled on the lots held before the
  ex-date.
* **Cash mergers** close every lot at the offer price: a realised gain, split
  into long and short term by each lot's own holding period.
* **Stock mergers** exchange the lots into the acquirer. Under the US
  reorganisation rules (IRC 354/356/358) any cash received ("boot") is taxed
  only up to the gain realised, and the new basis is the old basis, less the
  cash, plus the gain recognised.

Every function returns an :class:`EntitlementResult` with the lots before and
after, the cash and transactions generated, and the realised amount - and the
tests assert that cost basis is conserved wherever the rules say it must be.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_DOWN, Decimal

from ..core.currency import Currency, get_currency
from ..core.decimals import decimal_sum, to_decimal
from ..core.enums import TransactionType
from ..core.exceptions import ValidationError
from ..core.money import Money
from .corporate_actions import (
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
from .positions import TaxLot
from .transactions import Transaction

COST_PLACES = Decimal("0.0000000001")


@dataclass(frozen=True, slots=True)
class CashEntitlement:
    """Cash an action produces for the holder."""

    kind: str  # dividend | cash_in_lieu | merger_consideration
    gross: Money
    tax_withheld: Money
    pay_date: date

    @property
    def net(self) -> Money:
        return self.gross - self.tax_withheld


@dataclass(frozen=True)
class EntitlementResult:
    """What one corporate action did to one holding."""

    action: CorporateAction
    lots_before: tuple[TaxLot, ...]
    lots_after: tuple[TaxLot, ...]
    cash: tuple[CashEntitlement, ...] = ()
    transactions: tuple[Transaction, ...] = ()
    realised_long_term: Decimal = Decimal(0)
    realised_short_term: Decimal = Decimal(0)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def quantity_before(self) -> Decimal:
        return decimal_sum(lot.quantity for lot in self.lots_before if lot.instrument_id == self.action.instrument_id)

    def quantity_after(self, instrument_id: str | None = None) -> Decimal:
        target = instrument_id or self.action.instrument_id
        return decimal_sum(lot.quantity for lot in self.lots_after if lot.instrument_id == target)

    @property
    def basis_before(self) -> Decimal:
        return decimal_sum(lot.cost_basis.amount for lot in self.lots_before)

    @property
    def basis_after(self) -> Decimal:
        return decimal_sum(lot.cost_basis.amount for lot in self.lots_after)

    @property
    def realised(self) -> Decimal:
        return self.realised_long_term + self.realised_short_term

    @property
    def cash_total(self) -> Decimal:
        return decimal_sum(item.net.amount for item in self.cash)


def entitled_lots(lots: Sequence[TaxLot], action: CorporateAction) -> tuple[list[TaxLot], list[TaxLot]]:
    """Split lots into (entitled, not entitled): only lots opened before the ex-date take part."""
    entitled = [lot for lot in lots if lot.instrument_id == action.instrument_id and lot.open_date < action.ex_date]
    others = [lot for lot in lots if lot not in entitled]
    return entitled, others


def _book_realised(lot: TaxLot, proceeds: Decimal, on: date) -> tuple[Decimal, Decimal]:
    gain = proceeds - lot.cost_basis.amount
    return (gain, Decimal(0)) if lot.is_long_term(on) else (Decimal(0), gain)


def apply_action(
    action: CorporateAction,
    lots: Sequence[TaxLot],
    *,
    portfolio_id: str,
    ex_price: Decimal | None = None,
    acquirer_price: Decimal | None = None,
    child_currency: str | Currency | None = None,
    take_up_rights: bool = False,
    whole_shares: bool = True,
) -> EntitlementResult:
    """Apply one corporate action to the lots of one holding.

    ``ex_price`` is the ex-date price, used to pay cash in lieu of fractional
    shares; ``acquirer_price`` values the shares received in a stock merger.
    """
    entitled, untouched = entitled_lots(lots, action)
    before = tuple(entitled)
    if not entitled:
        return EntitlementResult(action, before, tuple(untouched), notes=("no lots held before the ex-date",))

    if isinstance(action, (StockSplit, StockDividend)):
        result = _apply_share_multiplier(action, entitled, portfolio_id, ex_price, whole_shares)
    elif isinstance(action, CashDividend):
        result = _apply_cash_dividend(action, entitled, portfolio_id)
    elif isinstance(action, SpinOff):
        result = _apply_spin_off(action, entitled, portfolio_id, ex_price, child_currency, whole_shares)
    elif isinstance(action, RightsIssue):
        result = _apply_rights(action, entitled, portfolio_id, take_up_rights)
    elif isinstance(action, CashMerger):
        result = _apply_cash_merger(action, entitled, portfolio_id)
    elif isinstance(action, StockMerger):
        result = _apply_stock_merger(action, entitled, portfolio_id, acquirer_price)
    elif isinstance(action, SymbolChange):
        result = EntitlementResult(
            action,
            before,
            before,
            notes=(f"ticker {action.old_symbol} became {action.new_symbol}; lots and basis unchanged",),
        )
    else:  # pragma: no cover - every concrete action is handled above
        raise ValidationError(f"no entitlement rule for {action.action_type.value}")
    return replace(result, lots_after=tuple(untouched) + result.lots_after)


# ---------------------------------------------------------------------------- share multipliers
def _apply_share_multiplier(
    action: StockSplit | StockDividend,
    lots: list[TaxLot],
    portfolio_id: str,
    ex_price: Decimal | None,
    whole_shares: bool,
) -> EntitlementResult:
    factor = action.quantity_factor
    adjusted = [lot.rescaled(factor, (lot.cost_per_unit / factor).quantize(COST_PLACES)) for lot in lots]
    notes = [f"{action.describe()}: quantity x{factor.normalize()}, cost per share /{factor.normalize()}"]
    cash: list[CashEntitlement] = []
    transactions: list[Transaction] = []
    long_term = short_term = Decimal(0)
    currency = lots[0].currency

    total = decimal_sum(lot.quantity for lot in adjusted)
    fraction = total - total.to_integral_value(rounding=ROUND_DOWN)
    if whole_shares and fraction > 0:
        if ex_price is None:
            raise ValidationError(f"{action.action_id}: {fraction} fractional shares need an ex-date price")
        # the fraction is taken from the most recently acquired lot, which is how brokers settle it
        adjusted.sort(key=lambda lot: (lot.open_date, lot.lot_id))
        last = adjusted[-1]
        fractional_lot = replace(last, quantity=fraction)
        proceeds = (fraction * ex_price).quantize(currency.precision)
        long_term, short_term = _book_realised(fractional_lot, proceeds, action.ex_date)
        remainder = last.quantity - fraction
        if remainder > 0:
            adjusted[-1] = replace(last, quantity=remainder)
        else:
            adjusted.pop()
        cash.append(CashEntitlement("cash_in_lieu", Money(proceeds, currency), Money.zero(currency), action.ex_date))
        transactions.append(
            Transaction(
                transaction_id=f"{action.action_id}-{portfolio_id}-CIL",
                portfolio_id=portfolio_id,
                instrument_id=action.instrument_id,
                transaction_type=TransactionType.SELL,
                trade_date=action.ex_date,
                quantity=fraction,
                price=ex_price,
                currency=currency,
                lot_id=last.lot_id,
                notes=f"cash in lieu of {fraction} fractional shares",
            )
        )
        notes.append(f"{fraction} fractional shares paid as cash in lieu at {ex_price}")

    delta = decimal_sum(lot.quantity for lot in adjusted) - decimal_sum(lot.quantity for lot in lots)
    if delta != 0:
        transactions.insert(
            0,
            Transaction(
                transaction_id=f"{action.action_id}-{portfolio_id}",
                portfolio_id=portfolio_id,
                instrument_id=action.instrument_id,
                transaction_type=TransactionType.SPLIT,
                trade_date=action.ex_date,
                quantity=abs(delta),
                currency=currency,
                notes=f"{'received' if delta > 0 else 'surrendered'} {abs(delta)} shares: {action.describe()}",
            ),
        )
    return EntitlementResult(
        action,
        tuple(lots),
        tuple(adjusted),
        tuple(cash),
        tuple(transactions),
        long_term,
        short_term,
        tuple(notes),
    )


# ---------------------------------------------------------------------------- income
def _apply_cash_dividend(action: CashDividend, lots: list[TaxLot], portfolio_id: str) -> EntitlementResult:
    currency = get_currency(action.currency)
    quantity = decimal_sum(lot.quantity for lot in lots)
    gross = (quantity * action.amount).quantize(currency.precision)
    tax = (gross * action.withholding_rate).quantize(currency.precision)
    pay_date = action.pay_date or action.ex_date
    transaction = Transaction(
        transaction_id=f"{action.action_id}-{portfolio_id}",
        portfolio_id=portfolio_id,
        instrument_id=action.instrument_id,
        transaction_type=TransactionType.DIVIDEND,
        trade_date=action.ex_date,
        settlement_date=pay_date,
        quantity=quantity,
        price=action.amount,
        gross_amount=gross,
        taxes=tax,
        currency=currency,
        notes=f"{'special ' if action.special else ''}dividend {action.amount} per share on {quantity} shares",
    )
    notes = [f"{quantity} shares entitled at {action.amount} {currency.code}"]
    if tax:
        notes.append(f"{action.withholding_rate:.2%} withheld at source: {tax} {currency.code}")
    return EntitlementResult(
        action,
        tuple(lots),
        tuple(lots),
        (CashEntitlement("dividend", Money(gross, currency), Money(tax, currency), pay_date),),
        (transaction,),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------- spin-offs and rights
def _apply_spin_off(
    action: SpinOff,
    lots: list[TaxLot],
    portfolio_id: str,
    ex_price: Decimal | None,
    child_currency: str | Currency | None,
    whole_shares: bool,
) -> EntitlementResult:
    fraction = action.child_fraction(ex_price)
    currency = get_currency(child_currency) if child_currency else lots[0].currency
    parents: list[TaxLot] = []
    children: list[TaxLot] = []
    for lot in lots:
        basis = lot.cost_basis.amount
        child_basis = (basis * fraction).quantize(COST_PLACES)
        parent_basis = basis - child_basis  # the remainder, so the two always sum to the original
        child_quantity = lot.quantity * action.ratio
        if whole_shares:
            child_quantity = child_quantity.to_integral_value(rounding=ROUND_DOWN)
        # a disallowed wash sale loss follows the basis: divided in the same proportion
        wash_total = lot.wash_sale_adjustment * lot.quantity
        child_wash = wash_total * fraction if child_quantity > 0 else Decimal(0)
        parents.append(
            replace(
                lot,
                cost_per_unit=(parent_basis / lot.quantity).quantize(COST_PLACES),
                wash_sale_adjustment=(wash_total - child_wash) / lot.quantity,
            )
        )
        if child_quantity > 0:
            children.append(
                TaxLot(
                    lot_id=f"{lot.lot_id}-SO",
                    instrument_id=action.child_instrument_id,
                    open_date=lot.open_date,  # the holding period tacks
                    quantity=child_quantity,
                    cost_per_unit=(child_basis / child_quantity).quantize(COST_PLACES),
                    currency=currency,
                    transaction_id=f"{action.action_id}-{portfolio_id}",
                    holding_period_start=lot.holding_period_start,
                    open_fx_rate=lot.open_fx_rate,
                    wash_sale_adjustment=child_wash / child_quantity,
                )
            )
    received = decimal_sum(lot.quantity for lot in children)
    transaction = Transaction(
        transaction_id=f"{action.action_id}-{portfolio_id}",
        portfolio_id=portfolio_id,
        instrument_id=action.child_instrument_id,
        transaction_type=TransactionType.SPIN_OFF,
        trade_date=action.ex_date,
        quantity=received,
        currency=currency,
        notes=f"{received} {action.child_instrument_id} received; {fraction:.4%} of basis allocated to the child",
    )
    return EntitlementResult(
        action,
        tuple(lots),
        tuple(parents + children),
        (),
        (transaction,),
        notes=(
            f"{fraction:.4%} of cost basis moved to {action.child_instrument_id}",
            "child lots keep the parent's acquisition dates",
        ),
    )


def _apply_rights(action: RightsIssue, lots: list[TaxLot], portfolio_id: str, take_up: bool) -> EntitlementResult:
    held = decimal_sum(lot.quantity for lot in lots)
    new_shares = (held * action.ratio).to_integral_value(rounding=ROUND_DOWN)
    if not take_up or new_shares == 0:
        return EntitlementResult(
            action, tuple(lots), tuple(lots), notes=(f"{new_shares} rights not taken up; holding unchanged",)
        )
    currency = lots[0].currency
    subscribed_on = action.pay_date or action.ex_date
    new_lot = TaxLot(
        lot_id=f"{action.action_id}-{portfolio_id}",
        instrument_id=action.instrument_id,
        open_date=subscribed_on,  # new money: a new holding period
        quantity=new_shares,
        cost_per_unit=action.subscription_price,
        currency=currency,
        transaction_id=f"{action.action_id}-{portfolio_id}",
    )
    transaction = Transaction(
        transaction_id=f"{action.action_id}-{portfolio_id}",
        portfolio_id=portfolio_id,
        instrument_id=action.instrument_id,
        transaction_type=TransactionType.BUY,
        trade_date=subscribed_on,
        quantity=new_shares,
        price=action.subscription_price,
        currency=currency,
        notes=f"rights taken up: {new_shares} new shares at {action.subscription_price}",
    )
    return EntitlementResult(
        action,
        tuple(lots),
        (*lots, new_lot),
        (),
        (transaction,),
        notes=(f"{new_shares} new shares subscribed at {action.subscription_price}",),
    )


# ---------------------------------------------------------------------------- mergers
def _apply_cash_merger(action: CashMerger, lots: list[TaxLot], portfolio_id: str) -> EntitlementResult:
    currency = get_currency(action.currency)
    long_term = short_term = Decimal(0)
    quantity = decimal_sum(lot.quantity for lot in lots)
    for lot in lots:
        gains = _book_realised(lot, (lot.quantity * action.cash_per_share).quantize(currency.precision), action.ex_date)
        long_term += gains[0]
        short_term += gains[1]
    proceeds = (quantity * action.cash_per_share).quantize(currency.precision)
    pay_date = action.pay_date or action.ex_date
    transaction = Transaction(
        transaction_id=f"{action.action_id}-{portfolio_id}",
        portfolio_id=portfolio_id,
        instrument_id=action.instrument_id,
        transaction_type=TransactionType.SELL,
        trade_date=action.ex_date,
        settlement_date=pay_date,
        quantity=quantity,
        price=action.cash_per_share,
        currency=currency,
        notes=f"cash merger at {action.cash_per_share} per share",
    )
    return EntitlementResult(
        action,
        tuple(lots),
        (),
        (CashEntitlement("merger_consideration", Money(proceeds, currency), Money.zero(currency), pay_date),),
        (transaction,),
        long_term,
        short_term,
        (f"position closed at {action.cash_per_share}; gains split by each lot's holding period",),
    )


def _apply_stock_merger(
    action: StockMerger, lots: list[TaxLot], portfolio_id: str, acquirer_price: Decimal | None
) -> EntitlementResult:
    currency = get_currency(action.currency)
    if action.cash_per_share > 0 and acquirer_price is None:
        raise ValidationError(f"{action.action_id}: taxing the cash boot needs the acquirer's price")
    price = to_decimal(acquirer_price, field="acquirer_price") if acquirer_price is not None else None
    exchanged: list[TaxLot] = []
    long_term = short_term = Decimal(0)
    cash_total = Decimal(0)
    for lot in lots:
        new_quantity = lot.quantity * action.ratio
        basis = lot.cost_basis.amount
        boot = (lot.quantity * action.cash_per_share).quantize(currency.precision)
        recognised = Decimal(0)
        if boot > 0 and price is not None:
            realised = boot + new_quantity * price - basis
            recognised = min(boot, max(realised, Decimal(0)))
        if recognised:
            if lot.is_long_term(action.ex_date):
                long_term += recognised
            else:
                short_term += recognised
        new_basis = basis - boot + recognised
        cash_total += boot
        exchanged.append(
            TaxLot(
                lot_id=f"{lot.lot_id}-M",
                instrument_id=action.acquirer_instrument_id,
                open_date=lot.open_date,
                quantity=new_quantity,
                cost_per_unit=(new_basis / new_quantity).quantize(COST_PLACES),
                currency=lot.currency,
                transaction_id=f"{action.action_id}-{portfolio_id}",
                holding_period_start=lot.holding_period_start,
                open_fx_rate=lot.open_fx_rate,
                wash_sale_adjustment=lot.wash_sale_adjustment * lot.quantity / new_quantity,
            )
        )
    cash: tuple[CashEntitlement, ...] = ()
    if cash_total:
        cash = (
            CashEntitlement(
                "merger_consideration",
                Money(cash_total, currency),
                Money.zero(currency),
                action.pay_date or action.ex_date,
            ),
        )
    return EntitlementResult(
        action,
        tuple(lots),
        tuple(exchanged),
        cash,
        (),
        long_term,
        short_term,
        (
            f"exchanged at {action.ratio} {action.acquirer_instrument_id} per share"
            + (f" plus {action.cash_per_share} cash" if action.cash_per_share else ""),
            "new basis = old basis - cash received + gain recognised (IRC 358)",
        ),
    )


def apply_actions(
    actions: Sequence[CorporateAction],
    lots: Sequence[TaxLot],
    *,
    portfolio_id: str,
    prices: dict[tuple[str, date], Decimal] | None = None,
) -> tuple[list[TaxLot], list[EntitlementResult]]:
    """Apply a sequence of actions in ex-date order, threading the lots through each one."""
    current = list(lots)
    results: list[EntitlementResult] = []
    lookup = prices or {}
    for action in sorted(actions, key=lambda item: (item.ex_date, item.action_id)):
        ex_price = lookup.get((action.instrument_id, action.ex_date))
        acquirer_price = (
            lookup.get((action.acquirer_instrument_id, action.ex_date)) if isinstance(action, StockMerger) else None
        )
        result = apply_action(
            action, current, portfolio_id=portfolio_id, ex_price=ex_price, acquirer_price=acquirer_price
        )
        results.append(result)
        current = list(result.lots_after)
    return current, results
