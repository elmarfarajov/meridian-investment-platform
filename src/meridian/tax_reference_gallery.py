"""The Day 3 revisit charts: the book of record against the tax authorities and its own invariants.

The published examples come from :mod:`meridian.devtools.tax_reference`, run
through the engine exactly as the tests run them, so a chart cannot show a figure
the tests do not check.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from matplotlib.figure import Figure

from .accounting.builders import cash_transaction, purchase, sale
from .accounting.engine import AccountingEngine, AccountingPolicy
from .accounting.income import analytic_bond
from .accounting.sources import FixedFx
from .accounting.uk_matching import MatchRule, match_disposals
from .core.currency import get_currency
from .core.daycount import DayCountConvention
from .core.decimals import decimal_sum
from .core.enums import LotSelectionMethod, TransactionType
from .devtools.tax_reference import (
    HMRC_HISTORIES,
    IDENTIFICATION_EXAMPLES,
    IRS_BEFORE,
    IRS_EXAMPLE_1,
    IRS_HISTORIES,
    IRS_ORDER,
    IRS_SAME_DAY,
    UK_STOCK,
    all_cases,
    errata,
    hmrc_matching,
    irs_book,
)
from .domain import Portfolio
from .domain.instruments import Bond
from .domain.transactions import Transaction
from .seed import demo_instruments
from .viz.tax_reference import (
    LotBox,
    MatchBar,
    PoolPanel,
    PoolStep,
    Purchase,
    ScoreRow,
    WashPanel,
    plot_invariants,
    plot_pools,
    plot_scorecard,
    plot_treasury_day_count,
    plot_uk_matching,
    plot_wash_timelines,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

SHORT_NAMES = {
    IRS_EXAMPLE_1: "IRS  Wash sales, Example 1",
    IRS_BEFORE: "IRS  More or less stock, Example 1",
    IRS_ORDER: "IRS  More or less stock, Example 2",
    IRS_SAME_DAY: "IRS  Loss and gain on the same day",
}
RULE_NAMES = {
    MatchRule.SAME_DAY: "same day",
    MatchRule.BED_AND_BREAKFAST: "bed and breakfast",
    MatchRule.SECTION_104: "section 104",
    MatchRule.LATER_ACQUISITION: "later acquisition",
}
PROPERTY_BOOKS = 300


# ---------------------------------------------------------------------------- scorecard
def scorecard_chart() -> Figure:
    rows = []
    for case in all_cases():
        name = SHORT_NAMES.get(case.source, f"HMRC  {case.source}")
        for figure in case.figures:
            difference = float(figure.difference) * (100 if case.authority == "IRS" else 1)
            is_count = figure.label.startswith("shares")
            unit = "" if is_count else ("$" if case.authority == "IRS" else "£")
            if is_count:
                difference = float(figure.difference)
            rows.append(
                ScoreRow(
                    case.authority,
                    name,
                    figure.label,
                    float(figure.published),
                    difference,
                    unit,
                    erratum=errata(case, figure) is not None,
                )
            )
    return plot_scorecard(rows)


# ---------------------------------------------------------------------------- wash sales
LESSONS = {
    IRS_EXAMPLE_1: "All 100 shares are replaced, so the whole $250 loss is disallowed and the new shares' basis "
    "becomes $1,050.",
    IRS_BEFORE: "The window looks back as well as forward: 75 shares bought in December replace 75 of the 100 sold "
    "in January. The other 25 shares' loss stays deductible.",
    IRS_ORDER: "Replacements are taken in the order bought: the 3 and 4 February lots take the $1,000; the 5 and 6 "
    "February lots take nothing.",
    IRS_SAME_DAY: "Three blocks sold in one sale. Only the first is a loss, and its $3,300 cannot reduce the gains "
    "on the other two; it moves to the January shares.",
}


def wash_chart() -> Figure:
    panels = []
    for source, history in IRS_HISTORIES.items():
        book = irs_book(source)
        added: dict[str, Decimal] = {}
        replaced: dict[str, Decimal] = {}
        for match in book.wash_sales:
            added[match.replacement_id] = added.get(match.replacement_id, Decimal(0)) + match.disallowed
            replaced[match.replacement_id] = replaced.get(match.replacement_id, Decimal(0)) + match.quantity
        sale_day = next(day for kind, _, day, _, _ in history if kind == "sell")
        sold = next(quantity for kind, _, _, quantity, _ in history if kind == "sell")
        losses = [record for record in book.realised if record.is_loss]
        purchases = tuple(
            Purchase(day, quantity, float(added.get(tid, 0)), int(replaced.get(tid, 0)))
            for kind, tid, day, quantity, _ in history
            if kind == "buy"
        )
        panels.append(
            WashPanel(
                SHORT_NAMES[source].replace("IRS  ", "Publication 550: "),
                sale_day,
                sold,
                float(-decimal_sum(record.tax_gain_before_wash for record in losses)),
                float(decimal_sum(record.disallowed_loss for record in book.realised)),
                purchases,
                tuple(sorted({record.open_date for record in book.realised})),
                LESSONS[source],
            )
        )
    return plot_wash_timelines(panels)


# ---------------------------------------------------------------------------- UK identification
UK_LABELS = {
    ("CG51590 Example 1", "S1"): "Ms Davy, March 2010",
    ("CG51590 Example 1", "S2"): "Ms Davy, December 2010",
    ("CG51590 Example 2", "S1"): "Mr Browne (after rights)",
    ("CG51590 Example 3", "S1"): "Mrs Mountain (1982 rebasing)",
    ("CG51590 Example 4", "S1"): "Peninsula Trust (two rights)",
    ("HS284 Example 2", "S1"): "Mr Schneider (HS284)",
    ("CG51560 Example 1", "S1"): "Miss A: back on day 30",
    ("CG51560 Example 2", "S1"): "Mr B: 500 of 1,700 back",
    ("CG51560 Example 3", "S1"): "Mrs C: back on day 31",
}
UK_NOTES = {
    ("CG51560 Example 3", "S1"): "day 31: outside the rule",
    ("CG51590 Example 2", "S1"): "rights never B&B-matched",
}


def uk_matching_chart() -> Figure:
    bars = []
    for source in [*HMRC_HISTORIES, *IDENTIFICATION_EXAMPLES]:
        for disposal in hmrc_matching(source).disposals:
            key = (source, disposal.disposal_id)
            by_rule = {RULE_NAMES[rule]: float(quantity) for rule, quantity in disposal.quantity_by_rule().items()}
            bars.append(MatchBar(UK_LABELS[key], float(disposal.quantity), by_rule, UK_NOTES.get(key, "")))
    # the two rules HMRC's examples do not reach, on the cases the engine used to get wrong
    for label, rows, note in ENGINE_CASES:
        transactions = [
            (purchase if kind == "buy" else sale)(
                transaction_id=tid,
                portfolio_id="P",
                instrument_id=UK_STOCK,
                day=day,
                quantity=quantity,
                price=str(Decimal(total) / quantity),
                currency="GBP",
            )
            for kind, tid, day, quantity, total in rows
        ]
        result = match_disposals(transactions, {item.instrument_id: item for item in demo_instruments()}, FixedFx({}))
        for disposal in result.disposals:
            by_rule = {RULE_NAMES[rule]: float(quantity) for rule, quantity in disposal.quantity_by_rule().items()}
            bars.append(MatchBar(f"{label} ({disposal.disposal_id})", float(disposal.quantity), by_rule, note))
    return plot_uk_matching(bars)


#: Cases outside HMRC's examples: two sales on one day are one disposal (s105), and a pool that runs out.
ENGINE_CASES = (
    (
        "Two sales on one day",
        [
            ("buy", "B1", date(2024, 1, 3), 1000, "1000"),
            ("buy", "B2", date(2024, 6, 3), 100, "300"),
            ("sell", "S1", date(2024, 6, 3), 100, "250"),
            ("sell", "S2", date(2024, 6, 3), 100, "250"),
        ],
        "s105: shared, not first-come",
    ),
    (
        "Pool runs out",
        [
            ("buy", "B1", date(2024, 1, 3), 100, "100"),
            ("sell", "S", date(2024, 3, 1), 150, "300"),
            ("buy", "B2", date(2024, 6, 3), 200, "600"),
        ],
        "HS284: later purchases",
    ),
)


# ---------------------------------------------------------------------------- the pool
POOL_NOTES = {
    "CG51590 Example 2": "Mr Browne. 4,000 rights at 26.5p join 20,000 shares at about 25.5p: the average barely "
    "moves. Selling 7,500 takes 7,500/24,000 of the pool cost, £1,925. HMRC then prints £4,236 for what is left; "
    "its own subtraction gives £4,235.",
    "CG51590 Example 4": "The Peninsula Trust. Two rights issues and a purchase at more than twice the first price "
    "lift the average from 45p to 74.7p; the 20,000 sold take £14,934 of cost, as HMRC states.",
}


def pool_chart() -> Figure:
    panels = []
    for source in ("CG51590 Example 2", "CG51590 Example 4"):
        history = hmrc_matching(source).pools[UK_STOCK]
        steps = []
        previous = Decimal(0)
        for state in history:
            event = state.event.split(" ")[0]
            steps.append(
                PoolStep(
                    state.day, float(state.quantity), float(state.cost), event, float(abs(state.quantity - previous))
                )
            )
            previous = state.quantity
        panels.append(PoolPanel(f"HMRC {source}", tuple(steps), POOL_NOTES[source]))
    return plot_pools(panels)


# ---------------------------------------------------------------------------- invariants
def _random_book(rng: random.Random, method: LotSelectionMethod) -> tuple[float, float]:
    """One random history of one share: the loss disallowed, and the basis carried for it."""
    start = date(2025, 1, 6)
    rows = [
        cash_transaction(
            transaction_id="DEP",
            portfolio_id="P",
            kind=TransactionType.DEPOSIT,
            day=start,
            amount="10000000",
            currency="USD",
        )
    ]
    held = 0
    offsets = sorted(rng.randrange(0, 150) for _ in range(rng.randrange(4, 25)))
    for index, offset in enumerate(offsets):
        day = start + timedelta(days=offset)
        if day.weekday() >= 5:
            day += timedelta(days=7 - day.weekday())
        quantity, price = rng.randrange(1, 60), rng.randrange(50, 150)
        if held and rng.random() < 0.45:
            quantity = min(quantity, held)
            held -= quantity
            maker: Callable[..., Transaction] = sale
        else:
            held += quantity
            maker = purchase
        rows.append(
            maker(
                transaction_id=f"T{index:03d}",
                portfolio_id="P",
                instrument_id="US-AAPL",
                day=day,
                quantity=quantity,
                price=str(price),
                currency="USD",
            )
        )
    engine = AccountingEngine(
        Portfolio(portfolio_id="P", name="random", base_currency=get_currency("USD")),
        {item.instrument_id: item for item in demo_instruments()},
        FixedFx({}),
        policy=AccountingPolicy(lot_method=method),
    )
    book = engine.run(rows)
    disallowed = decimal_sum(record.disallowed_loss for record in book.realised)
    carried = decimal_sum(lot.quantity * lot.wash_sale_adjustment for lots in book.open_lots.values() for lot in lots)
    carried += decimal_sum(record.wash_sale_basis for record in book.realised)
    return float(disallowed), float(carried)


def invariants_chart() -> Figure:
    rng = random.Random(20261004)
    methods = [LotSelectionMethod.FIFO, LotSelectionMethod.LIFO, LotSelectionMethod.HIFO]
    disallowed, carried, labels = [], [], []
    for index in range(PROPERTY_BOOKS):
        method = methods[index % 3]
        lost, kept = _random_book(rng, method)
        if lost:
            disallowed.append(lost)
            carried.append(kept)
            labels.append(method.value)
    lots = [LotBox("B1", 100, True), LotBox("B2", 110, True), LotBox("B3", 100, False)]
    return plot_invariants(lots, 100, "B1", "B3", disallowed, carried, labels, PROPERTY_BOOKS)


# ---------------------------------------------------------------------------- the Treasury
def treasury_chart() -> Figure:
    bond = next(item for item in demo_instruments() if isinstance(item, Bond))
    face = 250_000.0
    start, end = date(2025, 11, 15), date(2026, 5, 15)
    days = [start + timedelta(days=offset) for offset in range((end - start).days)]  # to the day before the coupon
    curves = {}
    for convention in (DayCountConvention.THIRTY_360_US, DayCountConvention.ACT_ACT_ICMA):
        analytic = analytic_bond(replace(bond, day_count=convention))
        curves[convention] = [analytic.accrued_interest(day) * face / 100 for day in days]
    return plot_treasury_day_count(
        days,
        curves[DayCountConvention.THIRTY_360_US],
        curves[DayCountConvention.ACT_ACT_ICMA],
        date(2026, 2, 3),
        face,
        bond.name,
    )


def tax_reference_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "published-examples.png",
            "The tax authorities' own examples, reproduced",
            "Every figure in the IRS's and HMRC's worked examples against the engine; one HMRC slip.",
            scorecard_chart,
            "tax",
        ),
        GalleryItem(
            "wash-sale-timelines.png",
            "Where each disallowed dollar goes",
            "Publication 550's wash sale examples on a timeline: the window, the replacements, the basis.",
            wash_chart,
            "tax",
        ),
        GalleryItem(
            "uk-share-matching.png",
            "Which shares a UK disposal is matched with",
            "Same day, 30 days, the pool, later purchases: HMRC's examples, rule by rule.",
            uk_matching_chart,
            "tax",
        ),
        GalleryItem(
            "section-104-pool.png",
            "The section 104 pool",
            "One holding, one average cost, through two rights issues.",
            pool_chart,
            "tax",
        ),
        GalleryItem(
            "book-invariants.png",
            "Property-testing the book",
            "The wash-sale loss that went nowhere, and every random book after the fix.",
            invariants_chart,
            "accounting",
        ),
        GalleryItem(
            "treasury-day-count.png",
            "Accrued interest on the Treasury convention",
            "The demonstration Treasury moved from 30/360 to actual/actual ICMA.",
            treasury_chart,
            "accounting",
        ),
    )
