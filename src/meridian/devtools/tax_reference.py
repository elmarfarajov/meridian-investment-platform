"""The accounting engine against the tax authorities' own worked examples.

The Day 3 tests were written from the rules. This module goes further and runs the
**published examples** - the cases the tax authorities themselves use to explain
their rules - through the engine exactly as published, dates and amounts included,
and sets every figure the authority states beside the figure the engine computes:

- **IRS Publication 550** (2025), *Wash Sales*: the replacement basis, a partial
  replacement bought *before* the sale, replacements taken in order of purchase, and
  a loss that may not reduce gains on other blocks sold the same day;
- **HMRC Capital Gains Manual CG51560 and CG51590**, and **Helpsheet HS284**: the
  same-day, 30-day and section 104 rules, rights issues joining the pool, and a
  30-day window that excludes the thirty-first day.

HMRC states its figures in whole pounds and rounds them, not always in the same
direction. The engine keeps pence, so HMRC figures are compared to within a pound.
One published figure does not follow from HMRC's own arithmetic, and it is recorded
as such rather than matched (``KNOWN_ERRATA``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..accounting.builders import cash_transaction, purchase, rights_take_up, sale
from ..accounting.engine import AccountingEngine
from ..accounting.sources import FixedFx
from ..accounting.uk_matching import MatchRule, UkMatchingResult, match_disposals
from ..core.currency import get_currency
from ..core.enums import TransactionType
from ..domain import Portfolio
from ..domain.transactions import Transaction
from ..seed import demo_instruments

D = Decimal
US_STOCK = "US-AAPL"
UK_STOCK = "GB-BAE"


@dataclass(frozen=True, slots=True)
class Figure:
    """One number an authority publishes, and the one the engine computes."""

    label: str
    published: Decimal
    computed: Decimal
    tolerance: Decimal

    @property
    def difference(self) -> Decimal:
        return self.computed - self.published

    @property
    def agrees(self) -> bool:
        return abs(self.difference) <= self.tolerance


@dataclass
class Case:
    authority: str
    source: str
    title: str
    figures: list[Figure] = field(default_factory=list)

    @property
    def agrees(self) -> bool:
        return all(figure.agrees for figure in self.figures)


#: Published figures that do not follow from the authority's own arithmetic.
KNOWN_ERRATA: dict[tuple[str, str], str] = {
    ("CG51590 Example 2", "pool cost after the disposal"): (
        "HMRC prints GBP 4,236, but its own figures give 6,160 - 1,925 = GBP 4,235; the apportioned cost "
        "(7,500 / 24,000 x 6,160) is exactly 1,925, so there is no rounding to explain the pound."
    ),
}


# ---------------------------------------------------------------------------- the United States
def _us_book(rows: Sequence[tuple[str, str, date, int, str]]):  # type: ignore[no-untyped-def]
    instruments = {item.instrument_id: item for item in demo_instruments()}
    engine = AccountingEngine(
        Portfolio(portfolio_id="IRS", name="Publication 550", base_currency=get_currency("USD")),
        instruments,
        FixedFx({"EUR": "1.10", "GBP": "1.25", "CHF": "1.12"}),
    )
    transactions: list[Transaction] = [
        cash_transaction(transaction_id="CASH", portfolio_id="IRS", kind=TransactionType.DEPOSIT,
                         day=date(2019, 1, 2), amount="1000000", currency="USD")
    ]  # fmt: skip
    for kind, transaction_id, day, quantity, total in rows:
        maker = purchase if kind == "buy" else sale
        transactions.append(maker(transaction_id=transaction_id, portfolio_id="IRS", instrument_id=US_STOCK, day=day,
                                  quantity=quantity, price=str(D(total) / quantity), currency="USD"))  # fmt: skip
    return engine.run(transactions)


def _lot_basis(book, lot_id: str) -> Decimal:  # type: ignore[no-untyped-def]
    return Decimal(next(lot.tax_basis for lot in book.open_lots[US_STOCK] if lot.lot_id == lot_id))


def irs_cases() -> list[Case]:
    cent = D("0.005")
    cases = []

    book = _us_book([("buy", "B1", date(2025, 1, 6), 100, "1000"), ("sell", "S1", date(2025, 3, 10), 100, "750"),
                     ("buy", "B2", date(2025, 3, 25), 100, "800")])  # fmt: skip
    (realised,) = book.realised
    cases.append(Case("IRS", "Publication 550, Wash Sales, Example 1", "The disallowed loss joins the new basis", [
        Figure("loss on the sale", D(-250), realised.tax_gain_before_wash, cent),
        Figure("loss disallowed", D(250), realised.disallowed_loss, cent),
        Figure("basis of the new shares", D(1050), _lot_basis(book, "B2"), cent),
    ]))  # fmt: skip

    book = _us_book([("buy", "SEP", date(2024, 9, 20), 100, "5000"), ("buy", "D13", date(2024, 12, 13), 50, "2750"),
                     ("buy", "D20", date(2024, 12, 20), 25, "1125"),
                     ("sell", "S", date(2025, 1, 3), 100, "4000")])  # fmt: skip
    (realised,) = book.realised
    cases.append(Case("IRS", "Publication 550, More or less stock bought than sold, Example 1",
                      "Replacements bought in the 30 days before the sale", [
        Figure("loss on the sale", D(-1000), realised.tax_gain_before_wash, cent),
        Figure("loss disallowed (75 shares)", D(750), realised.disallowed_loss, cent),
        Figure("loss deductible (25 shares)", D(-250), realised.reportable_gain, cent),
        Figure("basis of the 50 shares of 13 December", D(3250), _lot_basis(book, "D13"), cent),
        Figure("basis of the 25 shares of 20 December", D(1375), _lot_basis(book, "D20"), cent),
    ]))  # fmt: skip

    book = _us_book([("buy", "SEP", date(2024, 9, 16), 100, "2000"), ("sell", "S", date(2025, 1, 29), 100, "1000"),
                     ("buy", "F3", date(2025, 2, 3), 50, "500"), ("buy", "F4", date(2025, 2, 4), 50, "500"),
                     ("buy", "F5", date(2025, 2, 5), 50, "500"),
                     ("buy", "F6", date(2025, 2, 6), 50, "500")])  # fmt: skip
    (realised,) = book.realised
    cases.append(Case("IRS", "Publication 550, More or less stock bought than sold, Example 2",
                      "Replacements matched in the order bought", [
        Figure("loss disallowed", D(1000), realised.disallowed_loss, cent),
        Figure("added to the shares of 3 February", D(500), _lot_basis(book, "F3") - D(500), cent),
        Figure("added to the shares of 4 February", D(500), _lot_basis(book, "F4") - D(500), cent),
        Figure("added to the shares of 5 February", D(0), _lot_basis(book, "F5") - D(500), cent),
    ]))  # fmt: skip

    book = _us_book([("buy", "B1", date(2019, 3, 1), 100, "15800"), ("buy", "B2", date(2019, 6, 3), 100, "10000"),
                     ("buy", "B3", date(2019, 9, 3), 100, "9500"), ("sell", "S", date(2024, 12, 27), 300, "37500"),
                     ("buy", "J10", date(2025, 1, 10), 250, "31250")])  # fmt: skip
    by_lot = {realised.lot_id: realised for realised in book.realised}
    cases.append(Case("IRS", "Publication 550, Loss and gain on same day",
                      "A wash-sale loss cannot reduce gains on other blocks", [
        Figure("loss disallowed on the first block", D(3300), by_lot["B1"].disallowed_loss, cent),
        Figure("gain on the second block, unreduced", D(2500), by_lot["B2"].reportable_gain, cent),
        Figure("gain on the third block, unreduced", D(3000), by_lot["B3"].reportable_gain, cent),
    ]))  # fmt: skip
    return cases


# ---------------------------------------------------------------------------- the United Kingdom
def _uk_match(rows: Sequence[tuple[str, str, date, int, str]], *, rights: Sequence[str] = ()) -> UkMatchingResult:
    instruments = {item.instrument_id: item for item in demo_instruments()}
    transactions = []
    for kind, transaction_id, day, quantity, total in rows:
        price = str(D(total) / quantity)
        common = {"transaction_id": transaction_id, "portfolio_id": "HMRC", "instrument_id": UK_STOCK, "day": day,
                  "quantity": quantity, "price": price, "currency": "GBP"}  # fmt: skip
        if kind == "sell":
            transactions.append(sale(**common))  # type: ignore[arg-type]
        elif transaction_id in rights:
            transactions.append(rights_take_up(**common, rights_issue_id=f"RIGHTS-{day}"))  # type: ignore[arg-type]
        else:
            transactions.append(purchase(**common))  # type: ignore[arg-type]
    return match_disposals(transactions, instruments, FixedFx({}))


def _disposal(result: UkMatchingResult, disposal_id: str):  # type: ignore[no-untyped-def]
    return next(item for item in result.disposals if item.disposal_id == disposal_id)


def _pool_after(result: UkMatchingResult) -> tuple[Decimal, Decimal]:
    state = result.pools[UK_STOCK][-1]
    return state.quantity, state.cost


def hmrc_cases() -> list[Case]:
    pound = D(1)
    exact = D("0.005")
    cases = []

    result = _uk_match([
        ("buy", "B1", date(2006, 4, 15), 1000, "1300"), ("buy", "B2", date(2006, 8, 4), 1000, "1450"),
        ("buy", "B3", date(2007, 1, 19), 500, "950"), ("sell", "S1", date(2010, 3, 16), 2000, "6850"),
        ("buy", "B4", date(2010, 4, 7), 2000, "6790"), ("sell", "S2", date(2010, 12, 10), 2200, "7700"),
    ])  # fmt: skip
    first, second = _disposal(result, "S1"), _disposal(result, "S2")
    quantity, cost = _pool_after(result)
    cases.append(Case("HMRC", "CG51590 Example 1", "Ms Davy: a bed and breakfast, then a part disposal", [
        Figure("gain on the March 2010 disposal (30-day rule)", D(60), first.gain, pound),
        Figure("cost of the 2,200 shares from the pool", D(3256), second.cost, pound),
        Figure("gain on the December 2010 disposal", D(4444), second.gain, pound),
        Figure("shares left in the pool", D(300), quantity, exact),
        Figure("pool cost left", D(444), cost, pound),
    ]))  # fmt: skip

    result = _uk_match([
        ("buy", "B1", date(2008, 8, 17), 10000, "2500"), ("buy", "B2", date(2009, 4, 1), 10000, "2600"),
        ("buy", "R1", date(2009, 10, 8), 4000, "1060"), ("sell", "S1", date(2012, 12, 10), 7500, "3000"),
    ], rights=("R1",))  # fmt: skip
    disposal = _disposal(result, "S1")
    quantity, cost = _pool_after(result)
    cases.append(Case("HMRC", "CG51590 Example 2", "Mr Browne: a rights issue taken up joins the pool", [
        Figure("cost of the 7,500 shares", D(1925), disposal.cost, pound),
        Figure("chargeable gain", D(1075), disposal.gain, pound),
        Figure("shares left in the pool", D(16500), quantity, exact),
        Figure("pool cost after the disposal", D(4236), cost, pound),
    ]))  # fmt: skip

    result = _uk_match([
        # 31 March 1982 market value replaces the 1979 cost: TCGA 1992 s35 rebasing, entered as the cost
        ("buy", "B1", date(1979, 5, 27), 7500, "21000"), ("buy", "B2", date(1988, 2, 6), 4000, "16500"),
        ("buy", "B3", date(1993, 7, 28), 4000, "17000"), ("buy", "B4", date(2005, 3, 31), 6000, "29000"),
        ("sell", "S1", date(2013, 6, 13), 16500, "114675"),
    ])  # fmt: skip
    disposal = _disposal(result, "S1")
    quantity, cost = _pool_after(result)
    cases.append(Case("HMRC", "CG51590 Example 3", "Mrs Mountain: a holding rebased to 31 March 1982", [
        Figure("cost of the 16,500 shares", D(64081), disposal.cost, pound),
        Figure("chargeable gain", D(50594), disposal.gain, pound),
        Figure("shares left in the pool", D(5000), quantity, exact),
        Figure("pool cost left", D(19419), cost, pound),
    ]))  # fmt: skip

    result = _uk_match([
        ("buy", "B1", date(1997, 9, 24), 15000, "6750"), ("buy", "R1", date(2001, 1, 30), 9000, "3600"),
        ("buy", "B2", date(2004, 6, 14), 12000, "13800"), ("buy", "R2", date(2005, 11, 26), 9000, "9450"),
        ("sell", "S1", date(2010, 2, 23), 20000, "39000"),
    ], rights=("R1", "R2"))  # fmt: skip
    disposal = _disposal(result, "S1")
    quantity, cost = _pool_after(result)
    cases.append(Case("HMRC", "CG51590 Example 4", "The Peninsula Trust: two rights issues", [
        Figure("cost of the 20,000 shares", D(14934), disposal.cost, pound),
        Figure("chargeable gain", D(24066), disposal.gain, pound),
        Figure("shares left in the pool", D(25000), quantity, exact),
        Figure("pool cost left", D(18666), cost, pound),
    ]))  # fmt: skip

    result = _uk_match([
        ("buy", "B1", date(2015, 1, 5), 9500, "9500"), ("sell", "S1", date(2024, 8, 30), 4000, "6000"),
        ("buy", "B2", date(2024, 9, 11), 500, "850"),
    ])  # fmt: skip
    disposal = _disposal(result, "S1")
    by_rule = disposal.quantity_by_rule()
    bed = [match for match in disposal.matches if match.rule is MatchRule.BED_AND_BREAKFAST]
    proceeds_share = disposal.proceeds * D(500) / D(4000)
    cases.append(Case("HMRC", "HS284 Example 2", "Mr Schneider: 500 shares bought back within 30 days", [
        Figure("shares matched under the 30-day rule", D(500), by_rule.get(MatchRule.BED_AND_BREAKFAST, D(0)), exact),
        Figure("shares matched with the pool", D(3500), by_rule.get(MatchRule.SECTION_104, D(0)), exact),
        Figure("proceeds apportioned to the 500", D(750), proceeds_share, pound),
        Figure("loss on the 500 (proceeds less GBP 850)", D(-100),
               proceeds_share - sum((match.cost for match in bed), D(0)), pound),
    ]))  # fmt: skip

    cases.append(_identification_case("CG51560 Example 1", "Miss A: sold and bought back 30 days later", 1000,
                                      date(2011, 7, 1), 1000, date(2011, 7, 31), 1000, 1000))  # fmt: skip
    cases.append(_identification_case("CG51560 Example 2", "Mr B: 500 of 1,700 bought back within 30 days", 2500,
                                      date(2012, 3, 27), 1700, date(2012, 3, 30), 500, 500))  # fmt: skip
    cases.append(_identification_case("CG51560 Example 3", "Mrs C: bought back on the thirty-first day", 10000,
                                      date(2009, 2, 28), 2000, date(2009, 3, 31), 3000, 0))  # fmt: skip
    return cases


def _identification_case(source: str, title: str, holding: int, sold_on: date, sold: int, bought_on: date,
                         bought: int, expected_30_day: int) -> Case:  # fmt: skip
    result = _uk_match([
        ("buy", "B1", date(2005, 1, 4), holding, str(holding)), ("sell", "S1", sold_on, sold, str(sold * 2)),
        ("buy", "B2", bought_on, bought, str(bought * 2)),
    ])  # fmt: skip
    by_rule = _disposal(result, "S1").quantity_by_rule()
    exact = D("0.005")
    return Case("HMRC", source, title, [
        Figure("shares matched under the 30-day rule", D(expected_30_day),
               by_rule.get(MatchRule.BED_AND_BREAKFAST, D(0)), exact),
        Figure("shares matched with the pool", D(sold - expected_30_day),
               by_rule.get(MatchRule.SECTION_104, D(0)), exact),
    ])  # fmt: skip


def all_cases() -> list[Case]:
    return [*irs_cases(), *hmrc_cases()]


def errata(case: Case, figure: Figure) -> str | None:
    return KNOWN_ERRATA.get((case.source, figure.label))


CaseBuilder = Callable[[], list[Case]]
