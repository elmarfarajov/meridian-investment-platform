"""The Day 3 revisit charts draw, and draw the figures the tests check."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from meridian import tax_reference_gallery as gallery


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def _texts(figure):
    return " ".join(text.get_text() for text in figure.findobj(lambda item: hasattr(item, "get_text")))


def test_the_scorecard_reports_every_figure_and_the_erratum():
    text = _texts(gallery.scorecard_chart())
    assert "42 of 42 published figures reproduced" in text
    assert "HMRC prints £4,236" in text


def test_the_wash_sale_panels_show_the_publication_s_amounts():
    text = _texts(gallery.wash_chart())
    for amount in (r"\$250 of \$250", r"\$750 of \$1,000", r"\$1,000 of \$1,000", r"\$3,300 of \$3,300"):
        assert amount in text


def test_the_uk_chart_reaches_every_rule():
    text = _texts(gallery.uk_matching_chart())
    assert "day 31: outside the rule" in text and "Pool runs out" in text and "Two sales on one day" in text


def test_the_treasury_chart_marks_the_settlement_accrual():
    text = _texts(gallery.treasury_chart())
    assert "1,588.40" in text and "1,557.29" in text


def test_every_random_book_carries_its_disallowed_loss():
    import random

    from meridian.core.enums import LotSelectionMethod

    rng = random.Random(7)
    for method in (LotSelectionMethod.FIFO, LotSelectionMethod.LIFO, LotSelectionMethod.HIFO) * 5:
        disallowed, carried = gallery._random_book(rng, method)
        assert disallowed == pytest.approx(carried, abs=1e-9)


@pytest.mark.parametrize("item", gallery.tax_reference_items(), ids=lambda item: item.filename)
def test_every_chart_draws(item):
    figure = item.builder()
    assert figure.axes
