"""UK share identification: the same sales, a different tax code.

The United Kingdom does not tax lots. A disposal of shares is matched, in this
order (TCGA 1992 ss. 104-106A):

1. **Same day** - with shares of the same class acquired on the same day.
2. **Bed and breakfast** - with shares acquired in the **30 days after** the
   disposal, earliest first. The rule exists for the same reason as the US
   wash sale rule, and works the other way round: instead of disallowing the
   loss, it matches the sale to the repurchase, so the gain or loss is simply
   measured against the new shares' cost.
3. **The section 104 pool** - every other share held, at their average cost.
   Acquisitions join the pool; disposals take cost out of it pro rata.
4. **Later acquisitions** - if the pool cannot cover a disposal, the rest is matched
   with acquisitions after it, earliest first (HMRC HS284, section 2).

Everything acquired on one day is one acquisition, and everything disposed of on
one day is one disposal (s105(1)). The results are split back to the transactions
pro rata. Rights taken up are not an acquisition at all: under s127 the new shares
and the old are one asset, so the take-up joins the pool at its cost and is never
matched by the same-day or 30-day rules. A purchase is marked as one by naming the
rights issue in its metadata (``REORGANISATION``).

The engine reproduces HMRC's published worked examples (CG51560, CG51590 and HS284)
to the penny. HMRC rounds its figures to whole pounds.

Gains are measured in sterling: cost at the rate on the day of acquisition,
proceeds at the rate on the day of disposal. Shares transferred in join the
pool at their carried cost translated on the day they arrive, and quantities
are restated in post-split units, since a split changes neither the pool's
cost nor the identity of the shares. The tax year runs from 6 April
to 5 April, the annual exempt amount has been 3,000 pounds since April 2024,
and the rates on shares rose from 10%/20% to 18%/24% for disposals on or
after 30 October 2024.

A household with a US person resident in the UK files under both codes on the
same transactions, which is why the demonstration book is run through this
module as well as the lot engine: the two regimes give materially different
answers for the same year, and the chart that compares them is the argument.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from ..core.decimals import decimal_sum
from ..core.enums import TransactionType
from ..core.exceptions import ValidationError
from ..domain.corporate_actions import CorporateAction, StockDividend, StockSplit
from ..domain.instruments import Instrument, instrument_price_scale
from ..domain.transactions import Transaction
from .sources import FxSource

BED_AND_BREAKFAST_DAYS = 30
#: Transaction metadata naming the reorganisation a purchase belongs to - the rights issue taken up
REORGANISATION = "reorganisation"
RATE_CHANGE = date(2024, 10, 30)


class MatchRule(str, Enum):
    SAME_DAY = "same day"
    BED_AND_BREAKFAST = "30 days"
    SECTION_104 = "s104 pool"
    LATER_ACQUISITION = "later acquisition"


@dataclass(frozen=True, slots=True)
class UkMatch:
    rule: MatchRule
    quantity: Decimal
    cost: Decimal  # GBP
    acquisition_date: date | None = None
    acquisition_id: str | None = None


@dataclass(frozen=True)
class UkDisposal:
    disposal_id: str
    instrument_id: str
    day: date
    quantity: Decimal
    proceeds: Decimal  # GBP, net of costs
    matches: tuple[UkMatch, ...]

    @property
    def cost(self) -> Decimal:
        return decimal_sum(match.cost for match in self.matches)

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.cost

    @property
    def tax_year(self) -> str:
        return uk_tax_year(self.day)

    def quantity_by_rule(self) -> dict[MatchRule, Decimal]:
        totals: dict[MatchRule, Decimal] = defaultdict(Decimal)
        for match in self.matches:
            totals[match.rule] += match.quantity
        return dict(totals)

    def gain_by_rule(self) -> dict[MatchRule, Decimal]:
        """The gain attributed to each matching rule, proceeds divided by quantity."""
        totals: dict[MatchRule, Decimal] = defaultdict(Decimal)
        for match in self.matches:
            share = self.proceeds * match.quantity / self.quantity
            totals[match.rule] += share - match.cost
        return dict(totals)


@dataclass(frozen=True, slots=True)
class PoolState:
    instrument_id: str
    day: date
    quantity: Decimal
    cost: Decimal
    event: str

    @property
    def average_cost(self) -> Decimal:
        return self.cost / self.quantity if self.quantity else Decimal(0)


@dataclass(frozen=True)
class UkTaxYear:
    tax_year: str
    gains: Decimal
    losses: Decimal
    annual_exempt_amount: Decimal
    disposals: int
    proceeds: Decimal
    gains_after_rate_change: Decimal = Decimal(0)

    @property
    def net(self) -> Decimal:
        return self.gains + self.losses

    @property
    def taxable(self) -> Decimal:
        return max(self.net - self.annual_exempt_amount, Decimal(0))

    def estimated_tax(self) -> Decimal:
        """Higher-rate CGT on shares: 20% before 30 October 2024 and 24% from it, apportioned by gain."""
        if self.taxable <= 0:
            return Decimal(0)
        share_after = min(max(self.gains_after_rate_change, Decimal(0)), self.net) / self.net
        return self.taxable * (share_after * Decimal("0.24") + (1 - share_after) * Decimal("0.20"))


@dataclass
class UkMatchingResult:
    disposals: list[UkDisposal]
    pools: dict[str, list[PoolState]] = field(default_factory=dict)

    def by_tax_year(self) -> list[UkTaxYear]:
        years: dict[str, list[UkDisposal]] = defaultdict(list)
        for disposal in self.disposals:
            years[disposal.tax_year].append(disposal)
        summaries = []
        for year in sorted(years):
            items = years[year]
            summaries.append(
                UkTaxYear(
                    tax_year=year,
                    gains=decimal_sum(item.gain for item in items if item.gain > 0),
                    losses=decimal_sum(item.gain for item in items if item.gain < 0),
                    annual_exempt_amount=annual_exempt_amount(year),
                    disposals=len(items),
                    proceeds=decimal_sum(item.proceeds for item in items),
                    gains_after_rate_change=decimal_sum(item.gain for item in items if item.day >= RATE_CHANGE),
                )
            )
        return summaries

    def pool(self, instrument_id: str, day: date) -> PoolState | None:
        states = [state for state in self.pools.get(instrument_id, []) if state.day <= day]
        return states[-1] if states else None


def uk_tax_year(day: date) -> str:
    """'2025/26' for any day from 6 April 2025 to 5 April 2026."""
    start = day.year if (day.month, day.day) >= (4, 6) else day.year - 1
    return f"{start}/{(start + 1) % 100:02d}"


def annual_exempt_amount(tax_year: str) -> Decimal:
    start = int(tax_year[:4])
    if start >= 2024:
        return Decimal(3000)
    if start == 2023:
        return Decimal(6000)
    return Decimal(12300)


@dataclass
class _Event:
    transaction_ids: list[str]
    day: date
    quantity: Decimal  # in post-split units
    amount: Decimal  # GBP: cost for an acquisition, net proceeds for a disposal
    remaining: Decimal = Decimal(0)
    reorganisation: bool = False  # rights taken up: part of the original holding, never matched as new shares

    @property
    def transaction_id(self) -> str:
        return "+".join(self.transaction_ids)


def _split_factor(actions: Sequence[CorporateAction], instrument_id: str, day: date) -> Decimal:
    """Product of the share multipliers going ex after ``day``: restates a quantity in today's units."""
    factor = Decimal(1)
    for action in actions:
        if (
            isinstance(action, (StockSplit, StockDividend))
            and action.instrument_id == instrument_id
            and action.ex_date > day
        ):
            factor *= action.quantity_factor
    return factor


def _same_day(events: list[_Event]) -> list[_Event]:
    """TCGA 1992 s105(1): everything acquired (or disposed of) on one day is one transaction.

    A take-up of rights stays apart: it is not an acquisition at all but part of the
    holding it was offered on (s127), so it must never be merged into one that is.
    """
    merged: dict[tuple[date, bool], _Event] = {}
    for event in events:
        key = (event.day, event.reorganisation)
        if key not in merged:
            merged[key] = _Event(list(event.transaction_ids), event.day, Decimal(0), Decimal(0), Decimal(0),
                                 event.reorganisation)  # fmt: skip
        target = merged[key]
        if event.transaction_ids[0] not in target.transaction_ids:
            target.transaction_ids.extend(event.transaction_ids)
        target.quantity += event.quantity
        target.amount += event.amount
        target.remaining += event.remaining
    return sorted(merged.values(), key=lambda item: (item.day, item.reorganisation, item.transaction_id))


def match_disposals(
    transactions: Iterable[Transaction],
    instruments: Mapping[str, Instrument],
    fx: FxSource,
    *,
    actions: Sequence[CorporateAction] = (),
    currency: str = "GBP",
) -> UkMatchingResult:
    """Apply the same-day, 30-day, section 104 and later-acquisition rules to every disposal in ``transactions``."""
    acquisitions: dict[str, list[_Event]] = defaultdict(list)
    disposals: dict[str, list[_Event]] = defaultdict(list)
    quantities: dict[str, Decimal] = {}
    for transaction in sorted(transactions, key=lambda item: (item.trade_date, item.transaction_id)):
        kind = transaction.transaction_type
        if kind not in {TransactionType.BUY, TransactionType.SELL, TransactionType.TRANSFER_IN}:
            continue
        instrument_id = transaction.instrument_id or ""
        instrument = instruments.get(instrument_id)
        if instrument is None:
            raise ValidationError(f"{transaction.transaction_id}: {instrument_id} is not in the security master")
        rate = fx.rate(transaction.currency.code, currency, transaction.trade_date)
        factor = _split_factor(actions, instrument_id, transaction.trade_date)
        quantity = transaction.quantity * factor
        quantities[transaction.transaction_id] = quantity
        gross = (
            transaction.gross_amount
            if transaction.gross_amount is not None
            else transaction.quantity * transaction.price * instrument_price_scale(instrument)
        )
        costs = transaction.fees + transaction.taxes
        if kind is TransactionType.SELL:
            disposals[instrument_id].append(
                _Event([transaction.transaction_id], transaction.trade_date, quantity, (gross - costs) * rate, quantity)
            )
        else:
            acquisitions[instrument_id].append(
                _Event(
                    [transaction.transaction_id],
                    transaction.trade_date,
                    quantity,
                    (gross + costs) * rate,
                    quantity,
                    reorganisation=REORGANISATION in transaction.metadata,
                )
            )

    acquisitions = defaultdict(list, {key: _same_day(items) for key, items in acquisitions.items()})
    disposals = defaultdict(list, {key: _same_day(items) for key, items in disposals.items()})

    matches: dict[str, list[UkMatch]] = defaultdict(list)
    for instrument_id, sold in disposals.items():
        bought = [item for item in acquisitions.get(instrument_id, []) if not item.reorganisation]
        # 1. same day, for every disposal before any 30-day matching
        for disposal in sold:
            for acquisition in bought:
                if acquisition.day == disposal.day and acquisition.remaining > 0 and disposal.remaining > 0:
                    matches[disposal.transaction_id].append(_take(acquisition, disposal, MatchRule.SAME_DAY))
        # 2. bed and breakfast, earlier disposals first, earliest acquisitions first
        for disposal in sold:
            window_end = disposal.day + timedelta(days=BED_AND_BREAKFAST_DAYS)
            for acquisition in bought:
                if (
                    disposal.day < acquisition.day <= window_end
                    and acquisition.remaining > 0
                    and disposal.remaining > 0
                ):
                    matches[disposal.transaction_id].append(_take(acquisition, disposal, MatchRule.BED_AND_BREAKFAST))

    # 3. the pool, chronologically, with whatever the first two rules left; 4. then later acquisitions
    merged_results: list[UkDisposal] = []
    pools: dict[str, list[PoolState]] = {}
    for instrument_id in sorted(set(acquisitions) | set(disposals)):
        events = sorted(
            [(item.day, 0, item) for item in acquisitions.get(instrument_id, [])]
            + [(item.day, 1, item) for item in disposals.get(instrument_id, [])],
            key=lambda entry: (entry[0], entry[1], entry[2].transaction_id),
        )
        later = [item for item in acquisitions.get(instrument_id, []) if not item.reorganisation]
        pool_quantity = pool_cost = Decimal(0)
        history: list[PoolState] = []
        for day, is_disposal, event in events:
            if not is_disposal:
                if event.remaining > 0:
                    pool_cost += event.amount * event.remaining / event.quantity
                    pool_quantity += event.remaining
                    label = "rights " if event.reorganisation else "acquire "
                    history.append(
                        PoolState(instrument_id, day, pool_quantity, pool_cost, label + event.transaction_id)
                    )
                continue
            found = matches.get(event.transaction_id, [])
            if event.remaining > 0 and pool_quantity > 0:
                taken = min(event.remaining, pool_quantity)
                cost = pool_cost * taken / pool_quantity
                found.append(UkMatch(MatchRule.SECTION_104, taken, cost))
                pool_cost -= cost
                pool_quantity -= taken
                event.remaining -= taken
                history.append(
                    PoolState(instrument_id, day, pool_quantity, pool_cost, "dispose " + event.transaction_id)
                )
            # 4. what the pool could not cover is matched with later acquisitions, earliest first
            for acquisition in later:
                if event.remaining <= 0:
                    break
                if acquisition.day > day and acquisition.remaining > 0:
                    found.append(_take(acquisition, event, MatchRule.LATER_ACQUISITION))
            if event.remaining > 0:
                raise ValidationError(
                    f"{event.transaction_id}: disposes of {event.remaining} more {instrument_id} than was ever acquired"
                )
            merged_results.append(
                UkDisposal(event.transaction_id, instrument_id, day, event.quantity, event.amount, tuple(found))
            )
        pools[instrument_id] = history

    results = [part for merged in merged_results for part in _apportion(merged, quantities)]
    results.sort(key=lambda item: (item.day, item.disposal_id))
    return UkMatchingResult(results, pools)


def _apportion(disposal: UkDisposal, quantities: Mapping[str, Decimal]) -> list[UkDisposal]:
    """Split a same-day disposal back into its transactions, each taking its share of every match."""
    ids = disposal.disposal_id.split("+")
    if len(ids) == 1:
        return [disposal]
    parts = []
    for transaction_id in ids:
        share = quantities[transaction_id] / disposal.quantity
        parts.append(
            UkDisposal(
                transaction_id,
                disposal.instrument_id,
                disposal.day,
                quantities[transaction_id],
                disposal.proceeds * share,
                tuple(
                    UkMatch(
                        match.rule,
                        match.quantity * share,
                        match.cost * share,
                        match.acquisition_date,
                        match.acquisition_id,
                    )
                    for match in disposal.matches
                ),
            )
        )
    return parts


def _take(acquisition: _Event, disposal: _Event, rule: MatchRule) -> UkMatch:
    quantity = min(acquisition.remaining, disposal.remaining)
    cost = acquisition.amount * quantity / acquisition.quantity
    acquisition.remaining -= quantity
    disposal.remaining -= quantity
    return UkMatch(rule, quantity, cost, acquisition.day, acquisition.transaction_id)
