"""The trading day in the database: orders and their audit trail, fills, allocations and costs."""

from __future__ import annotations

import pytest

from meridian.core import ValidationError
from meridian.persistence import UnitOfWork
from meridian.services.demo_execution import build_demo_execution
from meridian.services.execution_run import check_controls, run_demo_execution


@pytest.fixture(scope="module")
def demo():
    return build_demo_execution()


@pytest.fixture
def stored(unit_of_work: UnitOfWork, demo):
    result = run_demo_execution(demo, unit_of_work)
    unit_of_work.commit()
    return result


def test_the_run_stores_every_order_event_fill_allocation_and_cost(stored, demo):
    children = sum(len(result.children) for result in demo.executions)
    assert stored.stored["order"] == len(demo.blocks) + children
    assert stored.stored["fill"] == sum(len(result.records) for result in demo.executions)
    assert stored.stored["allocation"] == sum(len(items) for items in demo.allocations)
    assert stored.stored["transaction cost"] == len(demo.blocks)
    assert any(label == "blocks worked" for label, _ in stored.summary_rows())


def test_fills_recounted_in_sql_match_the_blocks(stored, unit_of_work, demo):
    filled = unit_of_work.execution.filled_by_block(demo.trade_date)
    for result in demo.executions:
        assert filled.get(result.parent.order_id, 0.0) == pytest.approx(result.parent.cumulative)
    blocks = unit_of_work.execution.blocks(demo.trade_date)
    assert len(blocks) == len(demo.blocks)
    first = demo.executions[0]
    assert len(unit_of_work.execution.children(first.parent.order_id)) == len(first.children)
    assert [event.status for event in unit_of_work.execution.events(first.parent.order_id)][
        -1
    ] == first.parent.status.value


def test_costs_by_algorithm_add_up_to_the_day(stored, unit_of_work, demo):
    by_algorithm = unit_of_work.execution.cost_by_algorithm(demo.trade_date)
    assert sum(total for total, _ in by_algorithm.values()) == pytest.approx(demo.totals()["shortfall"])
    allocations = unit_of_work.execution.allocations("PF-GLOBAL-EQ")
    assert len(allocations) == len(demo.account_costs["PF-GLOBAL-EQ"])


def test_storing_the_day_again_replaces_it(stored, unit_of_work, demo):
    again = run_demo_execution(demo, unit_of_work)
    unit_of_work.commit()
    assert again.stored == stored.stored


def test_controls_refuse_a_fill_the_market_could_not_have_given(demo, monkeypatch):
    record = demo.executions[0].records[0]
    monkeypatch.setattr(record, "price", record.price * 2)
    with pytest.raises(ValidationError, match="outside the day's prices"):
        check_controls(demo)
