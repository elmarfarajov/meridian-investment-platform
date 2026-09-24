"""The Day 3 charts: each draws from the demonstration book, with the titles and panels it promises."""

from __future__ import annotations

from decimal import Decimal

import matplotlib.pyplot as plt
import pytest

from meridian import book_gallery
from meridian.accounting.tax import compare_lot_methods
from meridian.viz.accounting import FAMILY_SHADES, _money, holding_colours
from meridian.viz.style import PALETTE
from meridian.viz.tax import ILLUSTRATION_DATE, illustrative_lots


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def titles(figure) -> list[str]:
    return [axis.get_title(loc="left") for axis in figure.axes]


@pytest.mark.parametrize(
    ("builder", "panels", "phrase"),
    [
        (book_gallery.waterfall_chart, 2, "Net asset value"),
        (book_gallery.nav_chart, 2, "Cumulative investment result"),
        (book_gallery.fx_chart, 2, "Unrealised result"),
        (book_gallery.cash_chart, 5, "USD cash"),
        (book_gallery.settlement_chart, 2, "settlement cycle"),
        (book_gallery.income_chart, 2, "withholding"),
        (book_gallery.trial_balance_chart, 3, "Balance sheet accounts"),
        (book_gallery.restatement_chart, 3, "evening reports were wrong"),
        (book_gallery.wash_sale_chart, 3, "The loss, in dollars"),
        (book_gallery.lot_selection_chart, 2, "gain and tax by method"),
        (book_gallery.us_vs_uk_chart, 3, "Every disposal"),
        (book_gallery.realised_chart, 2, "by tax year"),
        (book_gallery.horizon_chart, 2, "days until long-term"),
        (book_gallery.reconciliation_chart, 3, "recall"),
    ],
)
def test_each_chart_has_its_panels_and_says_what_it_shows(builder, panels, phrase):
    figure = builder()
    assert len([axis for axis in figure.axes if axis.get_visible()]) >= panels
    assert any(phrase in title for title in titles(figure)), titles(figure)
    assert figure.texts, "every chart carries a title block"


def test_the_lot_map_and_the_statement_are_single_panels_with_text():
    lot_map = book_gallery.lot_map_chart()
    assert len(lot_map.axes) == 1 and lot_map.axes[0].get_legend() is not None
    statement = book_gallery.statement_chart()
    rendered = " ".join(text.get_text() for text in statement.axes[0].texts)
    assert "matched" in rendered and "custody fee" in rendered


def test_holding_colours_follow_currency_families():
    colours = holding_colours({"A": "USD", "B": "USD", "C": "EUR", "D": "JPY"})
    assert colours["A"] in FAMILY_SHADES["USD"] and colours["B"] in FAMILY_SHADES["USD"]
    assert colours["A"] != colours["B"]
    assert colours["C"] in FAMILY_SHADES["EUR"]
    assert colours["D"] == PALETTE["slate"]  # a currency without a family falls back to the neutral colour


def test_money_labels():
    assert _money(1_234_567) == "1.23m"
    assert _money(-12_300, signed=True) == "-12.3k"
    assert _money(999, signed=True) == "+999"


def test_the_illustrative_lots_make_the_methods_differ():
    choices = {
        c.method: c
        for c in compare_lot_methods(illustrative_lots(), Decimal(200), Decimal(480), Decimal(1), ILLUSTRATION_DATE)
    }
    assert choices["Minimum tax"].tax < choices["Highest cost"].tax < choices["FIFO"].tax
    assert choices["FIFO"].tax - choices["Minimum tax"].tax > Decimal(5000)
