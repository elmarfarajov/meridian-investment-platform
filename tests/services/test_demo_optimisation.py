"""The demonstration account rebalanced: the book's lots, the Day 5 risk, the Day 6 mandate, one proposal."""

from __future__ import annotations

import numpy as np
import pytest

from meridian import optimisation_gallery
from meridian.optimisation.backtest import TE_LIMIT
from meridian.optimisation.rebalance import RELIEF_METHODS
from meridian.optimisation.taxes import WASH_SALE_DAYS
from meridian.services.demo_optimisation import HOUSE, build_demo_optimisation


@pytest.fixture(scope="module")
def demo():
    return build_demo_optimisation()


def test_the_assets_are_the_book_and_the_benchmark(demo):
    held = [asset for asset in demo.assets if asset.lots]
    assert len(demo.assets) == 40 and len(held) == 10
    assert sum(len(asset.lots) for asset in demo.assets) == 31
    assert demo.check_weights() < 1e-9  # securities (accrued interest included) and cash are the whole account
    japan = [asset for asset in demo.assets if asset.attributes.get("country") == "JP"]
    assert japan and all(asset.lot_size == 100 for asset in japan)


def test_the_optimiser_measures_active_share_as_the_compliance_engine_does(demo):
    rebalancer = demo.house
    optimiser = rebalancer.active_share(rebalancer.w0, rebalancer.cash)
    engine = demo.compliance.today_snapshot.metrics["active_share"]
    assert optimiser == pytest.approx(engine, abs=0.005)
    assert rebalancer.evaluate(rebalancer.w0) == pytest.approx(0.058, abs=0.002)


def test_the_proposal_cuts_tracking_error_and_harvests_losses(demo):
    result = demo.proposal
    assert result.status == "optimal"
    assert result.tracking_error_after < 0.6 * result.tracking_error_before
    assert result.tax < 0 and result.realised_losses > result.realised_gains
    assert sum(result.after.values()) + result.cash_after + result.cost == pytest.approx(1.0, abs=1e-9)
    assert result.active_share_after >= 0.30 - 1e-6  # the mandate's floor, met by the convex-concave rounds
    losers = {sale.lot.asset_id for sale in result.sales if sale.gain < 0}
    assert not losers & set(result.buys)
    assert any("wash sale" in note for note in result.repairs)


def test_the_compliance_engine_does_not_block_the_proposal(demo):
    decision = demo.compliance_check
    assert decision.decision in ("allowed", "warning")
    assert not [change for change in decision.changes if change.effect in ("new breach", "worse breach")]


def test_choosing_lots_is_worth_money_on_the_same_trades(demo):
    taxes = {method: sum(sale.tax for sale in sales) for method, sales in demo.relief.items()}
    assert set(taxes) == set(RELIEF_METHODS)
    assert taxes["specific"] <= min(taxes.values()) + 1e-6
    assert taxes["lifo"] - taxes["specific"] > 10_000


def test_the_managers_differ_as_they_should(demo):
    blind, aware, harvest = (
        demo.alternatives[name] for name in ("tax-blind", "tax-aware, no harvesting", "tax-aware, harvesting")
    )
    assert harvest.tax < aware.tax < blind.tax
    assert blind.tracking_error_after <= harvest.tracking_error_after


def test_the_orders_are_whole_lots_close_to_the_optimiser(demo):
    rounded = demo.tickets
    assert rounded.status == "optimal" and rounded.tickets
    assert rounded.drift < 0.002 * demo.nav
    assert rounded.tracking_error_after == pytest.approx(demo.proposal.tracking_error_after, abs=5e-4)
    for ticket in rounded.tickets:
        asset = demo.house.assets[demo.house.asset_index[ticket.asset_id]]
        assert ticket.units % asset.lot_size == pytest.approx(0.0, abs=1e-9)


def test_the_backtest_universe_is_the_day5_estimation_universe(demo):
    risk = demo.universe_risk(50)
    assert len(risk.keys) == 50 and risk.benchmark.sum() == pytest.approx(1.0)
    assert risk.exposures.shape == (50, risk.factor_covariance.shape[0])
    assert np.all(risk.specific > 0)


def test_the_gallery_constants_match_the_library():
    assert optimisation_gallery.TE_BUDGET == TE_LIMIT
    assert optimisation_gallery.WASH_SALE_WINDOW == WASH_SALE_DAYS
    assert HOUSE.risk_aversion == 10.0
