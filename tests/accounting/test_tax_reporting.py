"""US tax years, Form 8949 and lot choice; UK same-day, 30-day and section 104 matching."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.accounting.builders import purchase, sale, transfer_in
from meridian.accounting.lots import RealisedLot, Term
from meridian.accounting.sources import FixedFx
from meridian.accounting.tax import (
    CAPITAL_LOSS_LIMIT,
    TaxRates,
    TaxYearSummary,
    compare_lot_methods,
    evaluate_sale,
    form_8949,
    minimum_tax_lots,
    tax_years,
)
from meridian.accounting.uk_matching import (
    MatchRule,
    annual_exempt_amount,
    match_disposals,
    uk_tax_year,
)
from meridian.core import ValidationError
from meridian.core.enums import LotSelectionMethod
from meridian.domain.corporate_actions import split
from meridian.domain.positions import TaxLot
from meridian.seed import demo_instruments

D = date
INSTRUMENTS = {item.instrument_id: item for item in demo_instruments()}


def realised(gain: str, term: Term, year: int = 2025, disallowed: str = "0", instrument: str = "X") -> RealisedLot:
    opened = D(year - 2, 1, 2) if term is Term.LONG else D(year, 1, 2)
    return RealisedLot(
        portfolio_id="P",
        instrument_id=instrument,
        lot_id=f"L-{gain}",
        disposal_id="S",
        open_date=opened,
        holding_start=opened,
        close_date=D(year, 6, 2),
        quantity=Decimal(10),
        currency="USD",
        proceeds=Decimal(1000) + Decimal(gain) - Decimal(disallowed),
        cost=Decimal(1000),
        open_fx_rate=Decimal(1),
        close_fx_rate=Decimal(1),
        disallowed_loss=Decimal(disallowed),
    )


# ---------------------------------------------------------------------------- US tax years
def test_schedule_d_nets_within_and_then_across_terms():
    (year,) = tax_years([realised("500", Term.SHORT), realised("-200", Term.SHORT), realised("1000", Term.LONG)])
    assert (year.short_term_gains, year.short_term_losses) == (Decimal(500), Decimal(-200))
    assert year.net_short == 300 and year.net_long == 1000 and year.net == 1300
    rates = TaxRates()
    assert year.estimated_tax(rates) == Decimal(300) * Decimal("0.408") + Decimal(1000) * Decimal("0.238")
    assert year.carryforward() == (0, 0)


def test_a_net_loss_is_deductible_up_to_three_thousand_and_the_rest_carries_forward():
    summaries = tax_years(
        [
            realised("-10000", Term.SHORT, 2024),
            realised("2000", Term.LONG, 2024),
            realised("1000", Term.SHORT, 2025),
            realised("10000", Term.LONG, 2025),
        ]
    )
    first, second = summaries
    assert first.net == Decimal(-8000)
    assert first.deductible_loss == CAPITAL_LOSS_LIMIT
    assert first.carryforward() == (Decimal(5000), 0)
    assert first.estimated_tax() == Decimal(-3000) * Decimal("0.37")
    assert second.carryforward_in_short == Decimal(5000)
    assert second.net_short == Decimal(-4000) and second.net_long == Decimal(10000)
    # the short-term loss is netted against the long-term gain before tax
    assert second.estimated_tax() == Decimal(6000) * Decimal("0.238")


def test_a_long_term_loss_carries_forward_as_long_term():
    summary = TaxYearSummary(2025, Decimal(1000), Decimal(0), Decimal(0), Decimal(-9000), Decimal(0))
    assert summary.net == Decimal(-8000)
    assert summary.carryforward() == (0, Decimal(5000))
    both = TaxYearSummary(2025, Decimal(0), Decimal(-2000), Decimal(0), Decimal(-4000), Decimal(0))
    assert both.carryforward() == (0, Decimal(3000))


def test_years_without_disposals_still_carry_losses_through():
    summaries = tax_years([realised("-5000", Term.SHORT, 2023), realised("100", Term.SHORT, 2025)])
    assert [item.year for item in summaries] == [2023, 2024, 2025]
    # 2023: 3,000 deducted, 2,000 carried; 2024: the 2,000 is deducted in a year with no sales
    assert summaries[0].carryforward() == (Decimal(2000), 0)
    assert summaries[1].carryforward_in_short == Decimal(2000)
    assert summaries[1].deductible_loss == Decimal(2000)
    assert summaries[1].carryforward() == (0, 0)
    assert summaries[2].net == Decimal(100)
    assert tax_years([]) == []


def test_form_8949_lists_short_term_first_with_the_wash_sale_code():
    rows = form_8949(
        [
            realised("300", Term.LONG),
            realised("-100", Term.SHORT, disallowed="40"),
            realised("50", Term.SHORT, year=2024),
        ],
        2025,
    )
    assert [row.term for row in rows] == [Term.SHORT, Term.LONG]
    wash = rows[0]
    assert wash.code == "W" and wash.adjustment == Decimal("40.00") and wash.gain == Decimal("-100.00")
    printed = wash.as_tuple()
    assert printed[1] == "01/02/2025" and printed[5] == "W"
    assert rows[1].as_tuple()[6] == ""


# ---------------------------------------------------------------------------- lot choice
def lot(lot_id: str, opened: date, cost: str, quantity: int = 100) -> TaxLot:
    return TaxLot(
        lot_id=lot_id,
        instrument_id="X",
        open_date=opened,
        quantity=Decimal(quantity),
        cost_per_unit=Decimal(cost),
        currency="USD",
    )


LOTS = [
    lot("OLD-CHEAP", D(2022, 3, 1), "50"),  # long-term gain
    lot("RECENT-DEAR", D(2026, 1, 5), "140"),  # short-term loss at 120
    lot("MID", D(2025, 2, 3), "110"),  # long-term gain by September 2026
    lot("NEW-CHEAP", D(2026, 6, 1), "100"),  # short-term gain
]


def test_the_minimum_tax_order_sells_losses_first_then_the_cheapest_gains_to_tax():
    order = minimum_tax_lots(LOTS, Decimal(120), D(2026, 9, 18))
    assert order[0] == "RECENT-DEAR"
    # 70 of long-term gain at 23.8% (16.66 a share) costs more than 20 of short-term gain at 40.8% (8.16)
    assert order[-1] == "OLD-CHEAP"
    assert order.index("NEW-CHEAP") < order.index("OLD-CHEAP")


def test_compare_methods_on_one_sale():
    results = {
        item.method: item for item in compare_lot_methods(LOTS, Decimal(150), Decimal(120), Decimal(1), D(2026, 9, 18))
    }
    assert set(results) == {"FIFO", "LIFO", "Highest cost", "Minimum tax"}
    assert results["FIFO"].lots[0] == ("OLD-CHEAP", Decimal(100))
    assert results["FIFO"].long_term == Decimal(100 * 70 + 50 * 10)
    assert results["Highest cost"].lots[0][0] == "RECENT-DEAR"
    assert results["Minimum tax"].tax == min(item.tax for item in results.values())
    assert results["Minimum tax"].realised == results["Minimum tax"].short_term + results["Minimum tax"].long_term
    with pytest.raises(ValidationError, match="no lots"):
        evaluate_sale([], Decimal(1), Decimal(1), Decimal(1), D(2026, 1, 2), LotSelectionMethod.FIFO)


@settings(max_examples=60, deadline=None)
@given(
    costs=st.lists(st.integers(min_value=20, max_value=200), min_size=2, max_size=6),
    ages=st.lists(st.integers(min_value=5, max_value=900), min_size=6, max_size=6),
    price=st.integers(min_value=20, max_value=200),
    quantity=st.integers(min_value=1, max_value=150),
)
def test_no_method_ever_beats_the_minimum_tax_order(costs, ages, price, quantity):
    as_of = D(2026, 9, 18)
    lots = [
        lot(f"L{index}", D.fromordinal(as_of.toordinal() - ages[index]), str(cost), 30)
        for index, cost in enumerate(costs)
    ]
    size = min(quantity, 30 * len(lots))
    results = compare_lot_methods(lots, Decimal(size), Decimal(price), Decimal(1), as_of)
    best = next(item for item in results if item.method == "Minimum tax")
    assert all(best.tax <= item.tax + Decimal("1e-9") for item in results)


# ---------------------------------------------------------------------------- UK matching
GBP = FixedFx({"GBP": "1"}, pivot="GBP")


def uk_buy(tid: str, day: date, quantity: int, total: str):
    return purchase(
        transaction_id=tid,
        portfolio_id="P",
        instrument_id="GB-BAE",
        day=day,
        quantity=quantity,
        price=str(Decimal(total) / quantity),
        currency="GBP",
    )


def uk_sell(tid: str, day: date, quantity: int, total: str):
    return sale(
        transaction_id=tid,
        portfolio_id="P",
        instrument_id="GB-BAE",
        day=day,
        quantity=quantity,
        price=str(Decimal(total) / quantity),
        currency="GBP",
    )


def test_same_day_then_thirty_days_then_the_pool():
    result = match_disposals(
        [
            uk_buy("A1", D(2025, 1, 2), 1000, "4000"),
            uk_buy("A2", D(2025, 6, 2), 500, "2500"),
            uk_sell("S1", D(2025, 9, 1), 700, "3500"),
            uk_buy("A3", D(2025, 9, 1), 200, "900"),
            uk_buy("A4", D(2025, 9, 5), 100, "480"),
        ],
        INSTRUMENTS,
        GBP,
    )
    (disposal,) = result.disposals
    by_rule = disposal.quantity_by_rule()
    assert by_rule == {MatchRule.SAME_DAY: 200, MatchRule.BED_AND_BREAKFAST: 100, MatchRule.SECTION_104: 400}
    pool_cost = Decimal(6500) * 400 / 1500
    assert disposal.cost == Decimal(900) + Decimal(480) + pool_cost
    assert disposal.gain == Decimal(3500) - disposal.cost
    assert disposal.tax_year == "2025/26"
    assert sum(disposal.gain_by_rule().values()) == pytest.approx(disposal.gain)
    after = result.pool("GB-BAE", D(2025, 12, 31))
    assert after.quantity == 1100
    assert after.cost == Decimal(6500) - pool_cost
    assert result.pool("GB-BAE", D(2024, 12, 31)) is None
    assert after.average_cost == after.cost / 1100


def test_bed_and_breakfast_matches_earlier_disposals_first_and_only_within_thirty_days():
    result = match_disposals(
        [
            uk_buy("A1", D(2025, 1, 2), 1000, "10000"),
            uk_sell("S1", D(2025, 5, 1), 100, "800"),
            uk_sell("S2", D(2025, 5, 10), 100, "800"),
            uk_buy("A2", D(2025, 5, 31), 150, "1200"),  # 30 days after S1, 21 after S2
            uk_buy("A3", D(2025, 6, 10), 100, "900"),  # 31 days after S2: pool, not matched
        ],
        INSTRUMENTS,
        GBP,
    )
    first, second = result.disposals
    assert first.quantity_by_rule() == {MatchRule.BED_AND_BREAKFAST: 100}
    assert second.quantity_by_rule() == {MatchRule.BED_AND_BREAKFAST: 50, MatchRule.SECTION_104: 50}


def test_disposals_are_measured_in_sterling_and_splits_restate_quantities():
    fx = FixedFx({"GBP": "1.25", ("GBP", D(2025, 6, 1)): "1.35"})  # dollars per pound
    actions = [split("SP", "DEMO-SPLIT", D(2025, 6, 10), 4)]
    result = match_disposals(
        [
            purchase(
                transaction_id="B1",
                portfolio_id="P",
                instrument_id="DEMO-SPLIT",
                day=D(2025, 1, 3),
                quantity=100,
                price="500",
                currency="USD",
            ),
            sale(
                transaction_id="S1",
                portfolio_id="P",
                instrument_id="DEMO-SPLIT",
                day=D(2025, 7, 1),
                quantity=200,
                price="135",
                currency="USD",
            ),
        ],
        INSTRUMENTS,
        fx,
        actions=actions,
    )
    (disposal,) = result.disposals
    assert disposal.quantity == 200
    assert disposal.proceeds == Decimal(27000) / Decimal("1.35")
    assert disposal.cost == Decimal(50000) / Decimal("1.25") * Decimal(200) / Decimal(400)


def test_transfers_join_the_pool_and_overselling_is_refused():
    transfer = transfer_in(
        transaction_id="TI",
        portfolio_id="P",
        instrument_id="GB-BAE",
        day=D(2025, 3, 3),
        quantity=100,
        cost_per_unit="5",
        currency="GBP",
        acquired=D(2019, 1, 2),
    )
    result = match_disposals([transfer, uk_sell("S1", D(2025, 9, 1), 50, "600")], INSTRUMENTS, GBP)
    assert result.disposals[0].cost == Decimal(250)
    with pytest.raises(ValidationError, match="in the pool"):
        match_disposals([uk_sell("S1", D(2025, 9, 1), 50, "600")], INSTRUMENTS, GBP)
    with pytest.raises(ValidationError, match="security master"):
        match_disposals(
            [
                purchase(
                    transaction_id="X",
                    portfolio_id="P",
                    instrument_id="NOPE",
                    day=D(2025, 1, 2),
                    quantity=1,
                    price="1",
                    currency="GBP",
                )
            ],
            INSTRUMENTS,
            GBP,
        )


def test_uk_tax_years_exempt_amounts_and_rates():
    assert uk_tax_year(D(2026, 4, 5)) == "2025/26"
    assert uk_tax_year(D(2026, 4, 6)) == "2026/27"
    assert uk_tax_year(D(1999, 12, 31)) == "1999/00"
    assert annual_exempt_amount("2025/26") == 3000
    assert annual_exempt_amount("2023/24") == 6000
    assert annual_exempt_amount("2022/23") == 12300
    result = match_disposals(
        [
            uk_buy("A1", D(2024, 5, 1), 1000, "10000"),
            uk_sell("S1", D(2024, 9, 2), 400, "6000"),  # gain 2,000 at the old rates
            uk_sell("S2", D(2024, 12, 2), 400, "8000"),  # gain 4,000 at the new rates
        ],
        INSTRUMENTS,
        GBP,
    )
    (year,) = result.by_tax_year()
    assert year.tax_year == "2024/25" and year.disposals == 2
    assert year.net == Decimal(6000) and year.taxable == Decimal(3000)
    assert year.gains_after_rate_change == Decimal(4000)
    expected = Decimal(3000) * (Decimal(4000) / 6000 * Decimal("0.24") + Decimal(2000) / 6000 * Decimal("0.20"))
    assert year.estimated_tax() == pytest.approx(expected)
