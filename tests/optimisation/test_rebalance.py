"""The rebalance: value conserved, lots chosen for their tax, wash sales repaired, limits kept."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.compliance.parser import parse_mandate
from meridian.core import ValidationError
from meridian.optimisation.rebalance import RELIEF_METHODS, Settings


def total_value(result) -> float:
    return sum(result.after.values()) + result.cash_after + result.cost


def test_trades_conserve_value_and_move_towards_the_target(rebalancer):
    result = rebalancer.solve(Settings(risk_aversion=10))
    assert result.status == "optimal"
    assert total_value(result) == pytest.approx(1.0, abs=1e-9)  # what is not held is cash, or paid in costs
    assert result.tracking_error_after < 0.5 * result.tracking_error_before
    assert all(weight >= -1e-9 for weight in result.after.values())  # no short sales
    assert result.cash_after >= 0.01 - 1e-7 and result.cash_after + result.cost <= 0.10 + 1e-7


def test_more_risk_aversion_buys_less_tracking_error_for_more_tax(rebalancer):
    loose = rebalancer.solve(Settings(risk_aversion=0.5))
    tight = rebalancer.solve(Settings(risk_aversion=50))
    assert tight.tracking_error_after < loose.tracking_error_after
    assert tight.tax >= loose.tax - 1e-6
    assert tight.turnover > loose.turnover


def test_the_optimiser_sells_the_cheapest_lots_first(rebalancer):
    result = rebalancer.solve(Settings(risk_aversion=10))
    sold = {sale.lot.lot_id: sale.weight for sale in result.sales}
    whole = {item.lot_id: weight for item, weight in zip(rebalancer.lots, rebalancer.lot_weights, strict=True)}
    # AAA's lots cost, per unit of value sold: A3 a saving (a loss); A2 40.8% of a 10% gain, 4.1%;
    # A1 23.8% of a 40% gain, 9.5% - the lower rate does not make the long-term lot the cheaper one
    assert sold.get("A3", 0.0) == pytest.approx(whole["A3"])
    assert sold.get("A2", 0.0) > 0
    if sold.get("A1", 0.0) > 1e-6:
        assert sold["A2"] == pytest.approx(whole["A2"])


def test_choosing_lots_beats_every_fixed_rule_on_the_same_trades(rebalancer):
    result = rebalancer.solve(Settings(risk_aversion=10))
    taxes = {method: sum(sale.tax for sale in sales) for method, sales in rebalancer.relief_comparison(result).items()}
    assert set(taxes) == set(RELIEF_METHODS)
    assert taxes["specific"] <= min(taxes.values()) + 1e-6
    assert taxes["lifo"] >= taxes["specific"]


def test_a_tax_blind_manager_pays_more_tax_for_the_same_trades(rebalancer):
    blind = rebalancer.solve(Settings(risk_aversion=10, tax_weight=0.0, lot_relief="fifo"))
    aware = rebalancer.solve(Settings(risk_aversion=10))
    assert aware.tax < blind.tax


def test_a_loss_is_never_harvested_while_the_stock_is_bought(rebalancer):
    result = rebalancer.solve(Settings(risk_aversion=30))
    losers = {sale.lot.asset_id for sale in result.sales if sale.gain < 0}
    assert not losers & set(result.buys)
    forbidden = rebalancer.solve(Settings(risk_aversion=30, forbidden_buys=frozenset({"CCC", "DDD"})))
    assert "CCC" not in forbidden.buys and "DDD" not in forbidden.buys


def test_harvesting_realises_more_losses_than_letting_them_sit(rebalancer):
    harvest = rebalancer.solve(Settings(risk_aversion=2))
    sit = rebalancer.solve(Settings(risk_aversion=2, harvest=False))
    assert harvest.realised_losses >= sit.realised_losses
    assert harvest.tax <= sit.tax + 1e-6


def test_a_tax_budget_is_respected(rebalancer):
    free = rebalancer.solve(Settings(risk_aversion=50))
    budget = free.tax / rebalancer.nav - 0.002
    capped = rebalancer.solve(Settings(risk_aversion=50, tax_budget=budget))
    rates = rebalancer.lot_rates(Settings())
    assert rates @ rebalancer.sold_vector(capped.sales) <= budget + 1e-6
    assert capped.tracking_error_after >= free.tracking_error_after - 1e-9


def test_an_unreachable_tracking_error_budget_is_approached_not_refused(market):
    rebalancer = market.rebalancer()
    result = rebalancer.solve(Settings(risk_aversion=1, te_limit=0.0, allow_buys=False))
    assert result.soft_violation > 0 and not result.buys


def test_lot_relief_keeps_totals_and_fills_by_its_rule(rebalancer):
    sold = np.zeros(len(rebalancer.lots))
    sold[0] = rebalancer.lot_weights[0] * 0.5
    sold[2] = rebalancer.lot_weights[2] * 0.5  # AAA: half of A1 and half of A3
    for method in RELIEF_METHODS:
        relieved = rebalancer.relieve(sold, method)
        assert relieved.sum() == pytest.approx(sold.sum())
        assert np.all(relieved <= rebalancer.lot_weights + 1e-15)
    fifo = rebalancer.relieve(sold, "fifo")
    assert fifo[0] == pytest.approx(sold.sum())  # the oldest lot, A1, is big enough to take it all
    hifo = rebalancer.relieve(sold, "hifo")
    assert hifo[2] == pytest.approx(rebalancer.lot_weights[2])  # the highest basis, A3, first and whole
    assert hifo[1] == pytest.approx(sold.sum() - rebalancer.lot_weights[2])  # then A2, the next highest
    with pytest.raises(ValidationError):
        rebalancer.relieve(sold, "random")


@settings(max_examples=40, deadline=None)
@given(
    bases=st.lists(st.floats(min_value=20.0, max_value=200.0), min_size=2, max_size=6),
    share=st.floats(min_value=0.05, max_value=1.0),
)
def test_highest_cost_first_realises_the_least_gain_of_the_fixed_rules(market, bases, share):
    lots = {"AAA": tuple(market.lot(f"L{i}", "AAA", 100.0, basis, 30 * (i + 1)) for i, basis in enumerate(bases))}
    rebalancer = market.rebalancer(assets=market.assets(lots))
    sold = np.zeros(len(rebalancer.lots))
    sold[0] = rebalancer.lot_weights.sum() * share
    gains = {
        method: sum(sale.gain for sale in rebalancer.sales(rebalancer.relieve(sold, method)))
        for method in ("fifo", "lifo", "hifo")
    }
    assert gains["hifo"] <= min(gains["fifo"], gains["lifo"]) + 1e-6


def test_an_excluded_holding_is_sold_whole_and_never_bought(market):
    assets = market.assets(**{"BBB": {"industry": "Tobacco"}, "CCC": {"industry": "Tobacco"}})
    mandate = parse_mandate(
        'mandate "Test" version 1 effective 2026-01-01\n'
        'rule exclusions "Exclusions" hard\n    no holdings where industry in ("Tobacco")\n'
    )
    rebalancer = market.rebalancer(assets=assets, mandate=mandate)
    result = rebalancer.solve(Settings(risk_aversion=10))
    assert result.after["BBB"] == pytest.approx(0.0, abs=1e-12)
    assert "CCC" not in result.buys
    assert "exclusions" in result.compiled_rules


def test_mandate_limits_hold_inside_their_buffer(market):
    mandate = parse_mandate(
        'mandate "Test" version 1 effective 2026-01-01\n'
        'rule issuer "Issuer" hard\n    max weight by issuer <= 20%\n'
        'rule cash "Cash" hard\n    weight where asset_class = "cash" between 2% and 6%\n'
    )
    rebalancer = market.rebalancer(mandate=mandate)
    result = rebalancer.solve(Settings(risk_aversion=0.2, limit_buffer=0.001))
    assert max(result.after.values()) <= 0.20 - 0.001 + 1e-7
    assert 0.02 + 0.001 - 1e-7 <= result.cash_after + result.cost <= 0.06 - 0.001 + 1e-7


def test_an_active_share_floor_is_met_by_the_convex_concave_rounds(market):
    mandate = parse_mandate(
        'mandate "Test" version 1 effective 2026-01-01\n'
        'rule active_share "Not a closet indexer" soft\n    active_share >= 25%\n'
    )
    rebalancer = market.rebalancer(mandate=mandate)
    free = market.rebalancer().solve(Settings(risk_aversion=100))
    assert free.active_share_after < 0.25  # left alone, the optimiser would hug the index
    held = rebalancer.solve(Settings(risk_aversion=100))
    assert held.active_share_after >= 0.25
    assert any("convex-concave" in line for line in held.repairs)
    assert held.tracking_error_after > free.tracking_error_after


def test_settings_are_validated():
    with pytest.raises(ValidationError, match="lot relief"):
        Settings(lot_relief="average")
    with pytest.raises(ValidationError, match="cash band"):
        Settings(cash_band=(0.1, 0.05))
    with pytest.raises(ValidationError, match="negative"):
        Settings(risk_aversion=-1)
    assert replace(Settings(), lot_relief="hifo").lot_relief == "hifo"


def test_the_problem_needs_a_positive_nav(market):
    with pytest.raises(ValidationError):
        market.rebalancer().__class__(market.as_of, 0.0, market.assets(), 0.0, market.risk())
