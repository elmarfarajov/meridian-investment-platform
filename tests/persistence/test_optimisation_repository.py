"""Rebalancing in the database: the proposal, its orders and lots, the frontier, and tax-alpha results."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from meridian.core import ValidationError
from meridian.optimisation.backtest import SimulationConfig, TaxAlphaBacktest
from meridian.persistence import UnitOfWork
from meridian.services.demo_optimisation import build_demo_optimisation
from meridian.services.optimisation_run import check_controls, run_demo_optimisation


@pytest.fixture(scope="module")
def demo():
    return build_demo_optimisation()


@pytest.fixture
def stored(unit_of_work: UnitOfWork, demo):
    result = run_demo_optimisation(demo, unit_of_work, with_frontier=False)
    unit_of_work.commit()
    return result


def test_the_run_stores_the_proposal_its_orders_and_its_lots(stored, demo):
    assert stored.stored["proposal"] == 1
    assert stored.stored["order"] == len(demo.tickets.tickets)
    assert stored.stored["lot sale"] == len(demo.tickets.sales)
    assert stored.decision == demo.compliance_check.decision
    assert any(label == "orders" for label, _ in stored.summary_rows())


def test_the_proposal_reads_back(stored, unit_of_work, demo):
    repository = unit_of_work.optimisation
    row = repository.proposal(stored.proposal_id)
    assert row is not None and row.as_of == demo.as_of
    assert row.tracking_error_after == pytest.approx(demo.tickets.tracking_error_after)
    assert row.tax == pytest.approx(demo.tickets.tax)
    orders = repository.orders(stored.proposal_id)
    assert [order.sequence for order in orders] == list(range(1, len(orders) + 1))
    assert {order.instrument_id for order in orders} == {ticket.asset_id for ticket in demo.tickets.tickets}
    assert [row.proposal_id for row in repository.proposals("PF-GLOBAL-EQ")] == [stored.proposal_id]


def test_tax_by_term_is_summed_in_sql(stored, unit_of_work, demo):
    by_term = unit_of_work.optimisation.tax_by_term(stored.proposal_id)
    total = sum(tax for _, tax in by_term.values())
    assert total == pytest.approx(demo.tickets.tax, abs=1e-6)
    assert set(by_term) <= {"short-term", "long-term", "wash sale"}


def test_storing_again_replaces_the_proposal(stored, unit_of_work, demo):
    again = run_demo_optimisation(demo, unit_of_work, with_frontier=False)
    unit_of_work.commit()
    assert len(unit_of_work.optimisation.orders(again.proposal_id)) == len(demo.tickets.tickets)


def test_the_frontier_is_stored_with_the_proposal(unit_of_work, demo):
    result = run_demo_optimisation(demo, unit_of_work)
    unit_of_work.commit()
    points = unit_of_work.optimisation.frontier(result.proposal_id)
    assert len(points) == len(demo.frontier.points) == result.stored["frontier point"]
    assert np.all(np.diff([point.tracking_error for point in points]) < 0)


def test_a_backtest_is_stored_by_manager(unit_of_work, demo):
    summary = TaxAlphaBacktest(demo.universe_risk(20), SimulationConfig(months=4, nav=1_000_000.0)).run_paths(1)
    count = unit_of_work.optimisation.save_backtest("TEST", summary)
    unit_of_work.commit()
    rows = unit_of_work.optimisation.backtest("TEST")
    assert count == len(rows) == 4
    assert {row.strategy for row in rows} == set(summary.strategies)
    blind = next(row for row in rows if row.strategy == "tax-blind")
    assert blind.tax_alpha == pytest.approx(0.0)


def test_controls_refuse_a_proposal_that_loses_value(demo, monkeypatch):
    broken = replace(demo.proposal, cash_after=demo.proposal.cash_after + 0.01)
    monkeypatch.setattr(type(demo), "proposal", property(lambda self: broken))
    with pytest.raises(ValidationError, match="conserve value"):
        check_controls(demo, frontier=False)
