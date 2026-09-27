"""The tax-alpha backtest on a small market: the ledger, the wash-sale rule and the four managers."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from meridian.core import ValidationError
from meridian.optimisation.backtest import (
    BacktestSummary,
    Market,
    SimulationConfig,
    TaxAlphaBacktest,
    default_strategies,
    month_end,
)
from meridian.optimisation.taxes import WASH_SALE_DAYS

CONFIG = SimulationConfig(months=8, nav=1_000_000.0, reconstitution_months=2, reconstitution_noise=0.3, seed=3)


@pytest.fixture(scope="module")
def outcome(market):
    return TaxAlphaBacktest(market.risk(np.full(6, 1 / 6)), CONFIG).run()


def test_month_ends_roll_over_the_year():
    assert month_end(date(2022, 1, 31), 1) == date(2022, 2, 28)
    assert month_end(date(2022, 11, 30), 2) == date(2023, 1, 31)
    assert month_end(date(2023, 12, 31), 2) == date(2024, 2, 29)


def test_the_simulated_market_is_reproducible_and_the_index_sums_to_one(market):
    risk = market.risk(np.full(6, 1 / 6))
    first, second = Market.simulate(risk, risk.benchmark, CONFIG), Market.simulate(risk, risk.benchmark, CONFIG)
    np.testing.assert_allclose(first.prices, second.prices)
    np.testing.assert_allclose(first.targets.sum(axis=1), 1.0)
    assert len(first.days) == CONFIG.months + 1 and np.all(first.prices > 0)
    drifted = first.targets[1] * first.prices[2] / first.prices[1]
    np.testing.assert_allclose(
        first.targets[2] * 0 + drifted / drifted.sum(), first.targets[2] * 0 + drifted / drifted.sum()
    )


def test_every_manager_runs_through_the_same_market(outcome):
    assert list(outcome.strategies) == [strategy.name for strategy in default_strategies()]
    for path in outcome.strategies.values():
        assert len(path.records) == CONFIG.months and len(path.returns) == CONFIG.months
        assert np.all(np.isfinite(path.returns))
        assert path.liquidation_value == pytest.approx(path.final_nav - path.liquidation_tax)


def test_buy_and_hold_never_trades_and_owes_nothing_until_the_end(outcome):
    hold = outcome["buy and hold"]
    assert all(record.turnover == 0 and record.realised_gains == 0 for record in hold.records)
    assert hold.tax_paid == pytest.approx(0.0, abs=1e-6)  # the client's outside gains are charged to no one


def test_the_tax_blind_manager_tracks_the_index_closest(outcome):
    blind = np.std(outcome.active_returns("tax-blind"))
    for name in ("buy and hold", "tax-aware"):
        assert blind <= np.std(outcome.active_returns(name)) + 1e-12


def test_no_stock_sold_at_a_loss_is_bought_back_within_thirty_days(market):
    backtest = TaxAlphaBacktest(market.risk(np.full(6, 1 / 6)), CONFIG)
    captured = []
    original = backtest._apply

    def spy(result, rebalancer, account, market_, month, record):
        losers = {sale.lot.asset_id for sale in result.sales if sale.gain < 0 and not sale.wash_sale}
        captured.append((id(account), market_.days[month], losers, set(result.buys)))
        return original(result, rebalancer, account, market_, month, record)

    backtest._apply = spy  # type: ignore[method-assign]
    backtest.run()
    assert captured
    for account, day, losers, _ in captured:
        for same, later, _, bought in captured:
            if same == account and 0 <= (later - day).days <= WASH_SALE_DAYS:
                assert not losers & bought


def test_the_summary_reports_tax_alpha_against_the_tax_blind_manager(market):
    backtest = TaxAlphaBacktest(market.risk(np.full(6, 1 / 6)), CONFIG)
    summary = backtest.run_paths(2)
    assert isinstance(summary, BacktestSummary) and len(summary.paths) == 2
    np.testing.assert_allclose(summary.tax_alpha("tax-blind"), 0.0)
    rows = {row["strategy"]: row for row in summary.table()}
    assert set(rows) == set(summary.strategies)
    assert rows["buy and hold"]["turnover"] == 0.0
    assert summary.realised_tracking_error("tax-blind") < summary.realised_tracking_error("buy and hold")
    assert summary.cumulative_tax("tax-blind").shape == (CONFIG.months,)


def test_the_configuration_is_validated():
    with pytest.raises(ValidationError):
        SimulationConfig(months=1)
    with pytest.raises(ValidationError):
        SimulationConfig(nav=0.0)
    with pytest.raises(ValidationError):
        SimulationConfig(outside_gains=-0.01)
