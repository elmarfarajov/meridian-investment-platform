"""The trading day after the rebalance: blocks, algorithms, allocations, costs and the client report."""

from __future__ import annotations

import pytest

from meridian.execution.orders import OrderStatus
from meridian.reporting.client_pack import TOTAL_PAGES, ClientPack
from meridian.services.demo_execution import FOLLOWERS, IMPACT, build_demo_execution, choose_algorithm


@pytest.fixture(scope="module")
def demo():
    return build_demo_execution()


def test_the_proposal_becomes_blocks_for_three_accounts(demo):
    assert str(demo.trade_date) == "2026-09-21"  # the Monday after the Friday decision
    assert {order.portfolio_id for order in demo.account_orders} == set(FOLLOWERS)
    assert len(demo.blocks) == 26 and demo.rfq_orders == ["US-T-2032"]
    for block in demo.blocks:
        assert block.order.quantity == pytest.approx(block.requested)
        assert {member.instrument_id for member in block.members} == {block.order.instrument_id}


def test_the_algorithm_wheel_routes_by_size(demo):
    assert choose_algorithm(0.005).name == "vwap"
    assert choose_algorithm(0.05).name == "is"
    assert choose_algorithm(0.3).name == "pov"
    for result, cost in zip(demo.executions, demo.costs, strict=True):
        assert result.params.name == choose_algorithm(cost.size_adv).name
        if cost.size_adv < 0.10:
            assert result.parent.status is OrderStatus.FILLED
        else:  # POV at 15% of all the volume can trade 15/85 of the rest of the market's day, and no more
            day = float(result.market.volumes.sum())
            finishes = cost.quantity <= 0.15 / 0.85 * day
            assert result.parent.status is (OrderStatus.FILLED if finishes else OrderStatus.EXPIRED)


def test_the_day_costs_what_the_desk_controls_plus_what_the_market_did(demo):
    totals = demo.totals()
    paper = totals["paper value"]
    controllable = (
        (totals["spread"] + totals["temporary impact"] + totals["permanent impact"] + totals["fees"]) / paper * 1e4
    )
    assert 5 < controllable < 20
    parts = sum(
        totals[name]
        for name in ("delay", "spread", "temporary impact", "permanent impact", "timing", "opportunity", "fees")
    )
    assert parts == pytest.approx(totals["shortfall"])


def test_allocations_give_every_account_the_block_price(demo):
    for block, allocations in zip(demo.blocks, demo.allocations, strict=True):
        assert sum(item.quantity for item in allocations) == pytest.approx(block.order.cumulative, abs=1.0)
        prices = {round(item.price, 10) for item in allocations if item.quantity > 0}
        assert len(prices) <= 1
    accounts = demo.account_costs
    total = sum(item.shortfall for items in accounts.values() for item in items)
    assert total == pytest.approx(demo.totals()["shortfall"], rel=1e-6)  # accounts' costs add up to the blocks'


def test_waiting_for_the_close_trades_the_least(demo):
    filled = {
        name: sum(cost.filled * cost.decision for cost in costs) / sum(cost.paper_value for cost in costs)
        for name, costs in demo.comparison.items()
    }
    assert filled["close"] == min(filled.values())
    assert filled["vwap"] > 0.9 * max(filled.values())


def test_the_measured_impact_recovers_the_truth_and_the_observed_does_not_pin_it(demo):
    measured, observed = demo.calibration["measured"], demo.calibration["observed"]
    assert measured.coefficient == pytest.approx(IMPACT.temporary, abs=0.02)
    assert observed.standard_error > 20 * measured.standard_error
    assert len(demo.desk_history) == 400


def test_the_client_report_is_a_nine_page_pdf(demo, tmp_path):
    pack = ClientPack(demo)
    assert len(pack.pages()) == TOTAL_PAGES == 9
    path = pack.write(tmp_path / "report.pdf")
    content = path.read_bytes()
    assert content.startswith(b"%PDF") and content.count(b"/Type /Page\n") + content.count(b"/Type /Page ") >= 9
    assert b"Meridian Investment Platform" in content
    with pytest.raises(Exception, match="PDF"):
        pack.write(tmp_path / "report.png")


def test_the_reports_figures_come_from_the_mandate_and_the_blocks_not_from_its_text(demo):
    pack = ClientPack(demo)
    # Day 8 wrote "the mandate's 6% soft limit", "30% floor", "two other accounts" and "26 block orders" into the text
    assert pack.limit("tracking_error") == pytest.approx(0.06)
    assert pack.limit("active_share") == pytest.approx(0.30)
    accounts = {member.portfolio_id for block in demo.blocks for member in block.members}
    assert pack.other_accounts == len(accounts) - 1
    assert pack.blocks_traded == sum(
        1 for block in demo.blocks if any(member.portfolio_id == pack.portfolio_id for member in block.members)
    )


def test_the_report_never_promises_to_carry_an_expired_order(demo):
    import inspect

    from meridian.reporting import client_pack

    assert "carried to the next session" not in inspect.getsource(client_pack)  # nothing carries expired blocks
