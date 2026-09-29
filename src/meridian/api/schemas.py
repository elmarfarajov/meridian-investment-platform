"""The API's public shapes. Every response is one of these models, so the OpenAPI document is the contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Problem(Model):
    """An error, as RFC 9457 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None


class Token(Model):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    roles: list[str]


class Me(Model):
    username: str
    roles: list[str]
    permissions: list[str]
    portfolios: list[str] | None


class Health(Model):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"] | None = None
    audit_chain: Literal["intact", "broken"] | None = None


class Portfolio(Model):
    portfolio_id: str
    name: str
    base_currency: str
    benchmark_id: str | None
    account_id: str
    strategy: str | None
    inception: str
    analysed: bool


class Position(Model):
    instrument_id: str
    quantity: float
    price: float
    currency: str
    market_value_base: float
    weight: float
    unrealised_long_term: float
    unrealised_short_term: float


class Valuation(Model):
    portfolio_id: str
    as_of: str
    nav: float
    cash: float
    positions: list[Position]


class PeriodRow(Model):
    period: str
    portfolio: float
    benchmark: float
    annualised: bool


class YearRow(Model):
    year: int
    portfolio: float
    benchmark: float | None


class StatisticRow(Model):
    measure: str
    portfolio: str
    benchmark: str


class Performance(Model):
    portfolio_id: str
    periods: list[PeriodRow]
    calendar_years: list[YearRow]
    statistics: list[StatisticRow]


class Segment(Model):
    segment: str
    average_weight: float
    benchmark_weight: float
    allocation: float
    selection: float
    interaction: float


class Attribution(Model):
    portfolio_id: str
    start: str
    end: str
    portfolio: float
    benchmark: float
    active: float
    effects: dict[str, float]
    segments: list[Segment]


class VarRow(Model):
    method: str
    confidence: float
    var: float
    expected_shortfall: float


class StressRow(Model):
    scenario: str
    portfolio: float
    benchmark: float


class Risk(Model):
    portfolio_id: str
    as_of: str
    volatility: float
    tracking_error: float
    by_group: dict[str, float]
    active_by_group: dict[str, float]
    value_at_risk: list[VarRow]
    stress: list[StressRow]


class RuleRow(Model):
    rule_id: str
    title: str | None
    severity: str
    status: str
    value: float | None
    limit: str
    utilisation: float | None


class Compliance(Model):
    portfolio_id: str
    as_of: str
    mandate: str
    rules: list[RuleRow]
    open_breaches: int


class TaxLot(Model):
    lot_id: str
    instrument_id: str
    quantity: float
    basis_per_unit: float
    price: float
    opened: str
    long_term: bool
    unrealised: float


class TaxLots(Model):
    portfolio_id: str
    as_of: str
    lots: list[TaxLot]


class OrderIn(Model):
    portfolio_id: str = Field(examples=["PF-GLOBAL-EQ"])
    instrument_id: str = Field(examples=["US-MSFT"])
    side: Literal["buy", "sell"]
    amount: float = Field(gt=0, le=1e9, description="Base currency", examples=[100_000])


class PreTradeIn(Model):
    instrument_id: str = Field(examples=["US-MSFT"])
    side: Literal["buy", "sell"]
    amount: float = Field(gt=0, le=1e9)


class RuleChangeOut(Model):
    rule_id: str
    effect: str
    before: float | None
    after: float | None


class PreTrade(Model):
    decision: str
    maximum: float | None
    reasons: list[RuleChangeOut]


class OrderOut(Model):
    order_id: str
    portfolio_id: str
    instrument_id: str
    side: str
    amount: float
    status: Literal["pending approval", "approved", "rejected"]
    pretrade_decision: str
    pretrade_reasons: list[str]
    created_by: str
    decided_by: str | None
    decision_note: str | None


class Decision(Model):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


class LotOut(Model):
    lot_id: str
    units: float


class ProposedOrder(Model):
    instrument_id: str
    side: str
    units: float
    value: float
    lots: list[LotOut]


class Rebalance(Model):
    portfolio_id: str
    as_of: str
    tracking_error_before: float
    tracking_error_after: float
    active_share_after: float
    tax: float
    cost: float
    turnover: float
    compliance: str
    orders: list[ProposedOrder]


class BlockCost(Model):
    order_id: str
    instrument_id: str
    algorithm: str
    quantity: float
    filled: float
    average_price: float | None
    shortfall_bps: float
    vwap_slippage_bps: float


class TradingCosts(Model):
    trade_date: str
    paper_value: float
    shortfall_bps: float
    components_bps: dict[str, float]
    blocks: list[BlockCost]


class AuditOut(Model):
    sequence: int
    recorded_at: str
    request_id: str
    username: str | None
    method: str
    path: str
    status: int
    latency_ms: float
    idempotency_key: str | None
    previous_hash: str
    record_hash: str


class AuditPage(Model):
    records: list[AuditOut]
    next_after: int | None


class ChainStatus(Model):
    records: int
    valid: bool
    first_broken: int | None
    reason: str | None
