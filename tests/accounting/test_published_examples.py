"""The engine against the IRS's and HMRC's own worked examples, and the UK rules they exposed."""

from datetime import date
from decimal import Decimal

import pytest

from meridian.accounting.builders import purchase, rights_take_up, sale
from meridian.accounting.sources import FixedFx
from meridian.accounting.uk_matching import MatchRule, match_disposals
from meridian.devtools.tax_reference import KNOWN_ERRATA, all_cases, errata, hmrc_cases, irs_cases
from meridian.seed import demo_instruments

INSTRUMENTS = {item.instrument_id: item for item in demo_instruments()}
GBP = FixedFx({})


@pytest.mark.parametrize("case", all_cases(), ids=lambda case: case.source)
def test_every_published_figure_is_reproduced(case):
    for figure in case.figures:
        assert figure.agrees, (case.source, figure.label, figure.published, figure.computed)


def test_the_cases_cover_both_authorities():
    assert len(irs_cases()) == 4 and len(hmrc_cases()) == 8
    assert sum(len(case.figures) for case in all_cases()) == 42


def test_irs_figures_agree_to_the_cent_and_hmrc_to_the_pound():
    assert all(figure.tolerance <= Decimal("0.005") for case in irs_cases() for figure in case.figures)
    hmrc_money = [figure for case in hmrc_cases() for figure in case.figures if figure.tolerance == 1]
    assert hmrc_money and all(abs(figure.difference) <= 1 for figure in hmrc_money)


def test_hmrc_s_one_arithmetic_slip_is_recorded_not_matched_silently():
    browne = next(case for case in hmrc_cases() if case.source == "CG51590 Example 2")
    pool = next(figure for figure in browne.figures if figure.label == "pool cost after the disposal")
    assert pool.computed == Decimal(4235) and pool.published == Decimal(4236)
    assert errata(browne, pool) == KNOWN_ERRATA[("CG51590 Example 2", "pool cost after the disposal")]


def _row(kind, transaction_id, day, quantity, total):
    maker = purchase if kind == "buy" else sale
    return maker(transaction_id=transaction_id, portfolio_id="P", instrument_id="GB-BAE", day=day, quantity=quantity,
                 price=str(Decimal(total) / quantity), currency="GBP")  # fmt: skip


def test_disposals_on_one_day_are_one_disposal():
    rows = [
        _row("buy", "B1", date(2024, 1, 3), 1000, "1000"),
        _row("buy", "B2", date(2024, 6, 3), 100, "300"),
        _row("sell", "S1", date(2024, 6, 3), 100, "250"),
        _row("sell", "S2", date(2024, 6, 3), 100, "250"),
    ]
    result = match_disposals(rows, INSTRUMENTS, GBP)
    first, second = sorted(result.disposals, key=lambda item: item.disposal_id)
    # the 100 shares bought that day match both sales half and half, not the first one in full
    assert first.quantity_by_rule()[MatchRule.SAME_DAY] == 50
    assert second.quantity_by_rule()[MatchRule.SAME_DAY] == 50
    assert first.cost == second.cost


def test_rights_taken_up_join_the_pool_and_are_never_matched_by_the_thirty_day_rule():
    rows = [
        _row("buy", "B1", date(2024, 1, 3), 1000, "1000"),
        _row("sell", "S1", date(2024, 6, 3), 500, "750"),
        rights_take_up(
            transaction_id="R1",
            portfolio_id="P",
            instrument_id="GB-BAE",
            day=date(2024, 6, 10),
            quantity=200,
            price="0.5",
            currency="GBP",
            rights_issue_id="RI-2024",
        ),
    ]
    result = match_disposals(rows, INSTRUMENTS, GBP)
    (disposal,) = result.disposals
    assert disposal.quantity_by_rule() == {MatchRule.SECTION_104: 500}
    assert result.pools["GB-BAE"][-1].quantity == 700  # 1,000 - 500 + 200
    as_purchase = match_disposals([*rows[:2], _row("buy", "R1", date(2024, 6, 10), 200, "100")], INSTRUMENTS, GBP)
    assert as_purchase.disposals[0].quantity_by_rule()[MatchRule.BED_AND_BREAKFAST] == 200


def test_a_disposal_the_pool_cannot_cover_is_matched_with_later_acquisitions():
    rows = [
        _row("buy", "B1", date(2024, 1, 3), 100, "100"),
        _row("sell", "S1", date(2024, 3, 1), 150, "300"),
        _row("buy", "B2", date(2024, 6, 3), 200, "600"),
    ]
    result = match_disposals(rows, INSTRUMENTS, GBP)
    by_rule = result.disposals[0].quantity_by_rule()
    assert by_rule == {MatchRule.SECTION_104: 100, MatchRule.LATER_ACQUISITION: 50}
    assert result.disposals[0].cost == Decimal(100) + Decimal(150)
    assert result.pools["GB-BAE"][-1].quantity == 150  # the rest of the later purchase joins the pool
