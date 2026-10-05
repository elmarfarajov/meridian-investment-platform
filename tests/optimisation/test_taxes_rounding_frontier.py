"""Tax per lot and per year, rounding to tradable orders, and the tracking-error / tax frontier."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from meridian.accounting.tax import DEFAULT_RATES
from meridian.core import ValidationError
from meridian.optimisation.assets import CostModel, LotState, TradableAsset
from meridian.optimisation.frontier import tax_frontier
from meridian.optimisation.rebalance import Settings
from meridian.optimisation.rounding import round_trades
from meridian.optimisation.taxes import (
    ORDINARY_OFFSET,
    TaxAccount,
    has_replacement,
    long_rate,
    lot_tax_rate,
    recently_bought,
    short_rate,
)

DAY = date(2026, 9, 25)


def one_lot(basis: float, opened: date) -> LotState:
    return LotState("L", "X", 10.0, basis, opened, opened)


# ---------------------------------------------------------------------- tax per lot
def test_a_lot_is_taxed_at_its_term_rate_on_its_gain_share():
    young, old = one_lot(80.0, date(2026, 3, 1)), one_lot(80.0, date(2024, 3, 1))
    assert lot_tax_rate(young, 100.0, DAY) == pytest.approx(short_rate() * 0.2)
    assert lot_tax_rate(old, 100.0, DAY) == pytest.approx(long_rate() * 0.2)
    assert short_rate() == pytest.approx(0.408) and long_rate() == pytest.approx(0.238)


def test_a_loss_is_a_saving_unless_it_is_not_harvested_or_the_wash_sale_rule_defers_it():
    loser = one_lot(125.0, date(2026, 3, 1))
    assert lot_tax_rate(loser, 100.0, DAY) == pytest.approx(-short_rate() * 0.25)
    assert lot_tax_rate(loser, 100.0, DAY, harvest=False) == 0.0
    assert lot_tax_rate(loser, 100.0, DAY, wash_blocked=True) == 0.0
    assert lot_tax_rate(loser, 100.0, DAY, loss_rate=0.17, loss_value=0.5) == pytest.approx(-0.17 * 0.25 * 0.5)


def test_accrued_interest_is_sold_but_not_taxed_as_a_gain():
    bond = one_lot(90.0, date(2024, 1, 1))
    clean = lot_tax_rate(bond, 100.0, DAY)
    dirty = lot_tax_rate(bond, 100.0, DAY, unit_value=102.0)
    assert dirty == pytest.approx(clean * 100.0 / 102.0)
    asset = TradableAsset("B", 100.0, 10.0, (bond,), accrued_per_unit=2.0)
    assert asset.value == pytest.approx(1020.0)


def test_recently_bought_finds_the_wash_sale_window():
    fresh = TradableAsset("N", 10.0, 10.0, (LotState("n", "N", 10.0, 10.0, date(2026, 9, 1), date(2026, 9, 1)),))
    stale = TradableAsset("O", 10.0, 10.0, (LotState("o", "O", 10.0, 10.0, date(2026, 7, 1), date(2026, 7, 1)),))
    assert recently_bought([fresh, stale], DAY) == {"N": frozenset({"n"})}


def test_the_shares_sold_are_never_their_own_replacement():
    newest = LotState("n", "N", 10.0, 12.0, date(2026, 9, 1), date(2026, 9, 1))
    older = LotState("m", "N", 10.0, 15.0, date(2026, 3, 1), date(2026, 3, 1))
    recent = recently_bought([TradableAsset("N", 10.0, 20.0, (newest, older))], DAY)
    assert not has_replacement(newest, recent)  # bought three weeks ago, sold at a loss: still a loss
    assert has_replacement(older, recent)  # the newer purchase replaces it: a wash sale


def test_assets_are_validated():
    with pytest.raises(ValidationError, match="price"):
        TradableAsset("X", 0.0, 0.0)
    with pytest.raises(ValidationError, match="lots hold"):
        TradableAsset("X", 10.0, 5.0, (one_lot(9.0, DAY),))
    with pytest.raises(ValidationError, match="lot size"):
        TradableAsset("X", 10.0, 0.0, lot_size=0.0)


def test_costs_are_linear_plus_square_root_impact():
    asset = TradableAsset("X", 10.0, 0.0, spread_bps=10.0, daily_volatility=0.02, daily_volume=1_000_000.0)
    model = CostModel(commission_bps=5.0, impact_coefficient=0.1)
    assert model.linear(asset) == pytest.approx(10e-4)
    small, large = model.cost(asset, 1_000_000.0, 0.01), model.cost(asset, 1_000_000.0, 0.04)
    # four times the trade: four times the linear cost, eight times the impact
    impact = model.impact(asset, 1_000_000.0)
    assert large - 4 * small == pytest.approx(impact * (0.04**1.5 - 4 * 0.01**1.5))
    assert model.impact(TradableAsset("Y", 10.0, 0.0), 1.0) == 0.0


# ---------------------------------------------------------------------- tax per year
def test_the_year_nets_short_against_long_and_carries_the_rest():
    account = TaxAccount()
    account.realise(date(2025, 3, 1), 10_000.0, long_term=False)
    account.realise(date(2025, 6, 1), -4_000.0, long_term=True)
    tax = account.close_year(2025)
    assert tax == pytest.approx(6_000.0 * short_rate())  # the long loss offsets the short gain
    assert account.carryforward == 0.0

    account.realise(date(2026, 2, 1), -20_000.0, long_term=False)
    account.realise(date(2026, 5, 1), 5_000.0, long_term=True)
    refund = account.close_year(2026)
    # $3,000 against ordinary income, at the ordinary rate: the 3.8% NIIT is charged only on a positive net
    assert refund == pytest.approx(-ORDINARY_OFFSET * float(DEFAULT_RATES.short_term))
    assert account.carryforward == pytest.approx(20_000.0 - 5_000.0 - ORDINARY_OFFSET)

    account.realise(date(2027, 1, 10), 30_000.0, long_term=True)
    tax = account.close_year(2027)
    assert tax == pytest.approx((30_000.0 - 12_000.0) * long_rate())
    assert account.carryforward == 0.0
    assert account.total_paid == pytest.approx(sum(account.paid.values()))


# ---------------------------------------------------------------------- rounding
def test_rounding_gives_whole_lots_above_the_minimum_ticket_in_the_chosen_direction(market):
    lots = market.lots()
    assets = market.assets(lots)
    assets[3] = TradableAsset(**{**assets[3].__dict__, "lot_size": 100.0})  # DDD trades in board lots of 100
    rebalancer = market.rebalancer(assets=assets)
    settings = Settings(risk_aversion=10)
    result = rebalancer.solve(settings)
    rounded = round_trades(rebalancer, result, settings, min_ticket=5_000.0)
    assert rounded.status == "optimal" and rounded.tickets
    for ticket in rounded.tickets:
        asset = rebalancer.assets[rebalancer.asset_index[ticket.asset_id]]
        assert ticket.units / asset.lot_size == pytest.approx(round(ticket.units / asset.lot_size))
        assert ticket.value >= 5_000.0 - 1e-6
        proposed = rounded.continuous[ticket.asset_id]
        assert (ticket.side == "buy") == (proposed > 0)
        if ticket.side == "sell":
            assert ticket.units <= asset.quantity + 1e-9
            assert sum(units for _, units in ticket.lots) == pytest.approx(ticket.units)
    assert rounded.cash_after >= 0.01 - 1e-6
    assert rounded.tracking_error_after == pytest.approx(result.tracking_error_after, abs=0.002)
    assert rounded.drift < 0.02 * rebalancer.nav


def test_a_large_minimum_ticket_drops_the_small_trades(market):
    rebalancer = market.rebalancer()
    settings = Settings(risk_aversion=10)
    result = rebalancer.solve(settings)
    smallest = min(
        abs(value) for value in round_trades(rebalancer, result, settings, min_ticket=1.0).continuous.values()
    )
    rounded = round_trades(rebalancer, result, settings, min_ticket=smallest * 3)
    assert rounded.dropped or rounded.raised


# ---------------------------------------------------------------------- the frontier
def test_the_frontier_is_the_lower_envelope_of_every_rebalance_found(market):
    rebalancer = market.rebalancer()
    frontier = tax_frontier(rebalancer, Settings(), points=5, risk_aversions=(1.0, 10.0, 100.0))
    taxes, errors = frontier.taxes(), frontier.tracking_errors()
    assert len(frontier.points) >= 2
    assert np.all(np.diff(taxes) >= 0) and np.all(np.diff(errors) < 0)  # more tax always buys less tracking error
    for point in frontier.dominated:  # nothing found beats the envelope
        assert point.tracking_error >= frontier.at_tax(point.tax) - 1e-5
    chosen = rebalancer.solve(Settings(risk_aversion=10))
    assert frontier.excess(chosen) >= -1e-5
    assert frontier.at_tax(taxes[0] - 1.0) == float("inf")
    with pytest.raises(ValidationError):
        tax_frontier(rebalancer, points=2)
