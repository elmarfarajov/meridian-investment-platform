"""Tax-loss harvesting through a century of real returns: the market built from history, and what it found."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from meridian.core import ValidationError
from meridian.optimisation.backtest import Market
from meridian.services import century_tax_alpha as century

HARVESTING = "tax-aware, harvesting"


def test_a_market_from_history_compounds_the_returns_and_earns_the_opening_weights():
    returns = np.array([[0.10, -0.20], [0.05, 0.00]])
    targets = np.array([[3.0, 1.0], [0.5, 0.5], [0.6, 0.4]])
    days = [date(2024, 12, 31), date(2025, 1, 31), date(2025, 2, 28)]
    market = Market.from_history(("A", "B"), days, returns, targets, np.array([0.01, 0.01]))
    assert market.prices[-1] == pytest.approx([115.5, 80.0])
    assert market.targets[0] == pytest.approx([0.75, 0.25])  # normalised
    assert market.index_returns == pytest.approx([0.75 * 0.10 + 0.25 * -0.20, 0.5 * 0.05])
    with pytest.raises(ValidationError, match="one row per month"):
        Market.from_history(("A", "B"), days, returns[:1], targets, np.array([0.01, 0.01]))


def test_a_window_sees_only_the_past_and_tracks_the_real_market():
    item = century.window(date(2000, 12, 31))
    assert item.label == "2001-2010" and item.end == date(2010, 12, 31)
    assert item.market.prices.shape == (121, 12)
    # the risk model is the 60 months to the start: the 2008 crash is nowhere in it
    history = century.french_history()
    months = tuple(month for month in history.months if month <= item.start)[-60:]
    expected = np.cov(century.returns_matrix(history, months), rowvar=False) / 21
    assert item.risk.factor_covariance == pytest.approx(expected)
    # the index rebuilt from the twelve industries is the market French publishes
    published = [history.cap_weighted(month) for month in history.months if item.start < month <= item.end]
    assert item.market.index_returns == pytest.approx(published, abs=1e-12)


@pytest.fixture(scope="module")
def decades() -> tuple[century.DecadeResult, ...]:
    return century.decades()


def test_harvesting_paid_the_least_tax_in_every_decade(decades):
    assert [result.label for result in decades][:2] == ["1931-1940", "1941-1950"]
    for result in decades:
        assert result.tax_saved(HARVESTING) > 0, result.label
        least = min(result.tax_drag(name) for name in result.outcome.strategies)
        assert result.tax_drag(HARVESTING) < least + 0.0001  # in the 1990s, nothing to harvest: tax-aware ties it


def test_harvesting_was_worth_most_when_the_market_fell(decades):
    by_label = {result.label: result for result in decades}
    best = max(decades, key=lambda result: result.tax_saved(HARVESTING))
    assert best.label == "1931-1940" and best.tax_saved(HARVESTING) > 0.004
    assert by_label["1931-1940"].harvested(HARVESTING) > 0.25  # a quarter of the account realised as losses
    # in the long bull market of the 1950s there was almost nothing to harvest
    assert by_label["1951-1960"].harvested(HARVESTING) < 0.01


def test_the_saving_is_separate_from_luck_in_tracking(decades):
    for result in decades:
        after_active = result.after_tax(HARVESTING) - result.after_tax("tax-blind")
        assert after_active == pytest.approx(result.tracking_difference(HARVESTING) + result.tax_saved(HARVESTING))
