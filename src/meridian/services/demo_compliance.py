"""Compliance for the demonstration account: its mandate, checked every day and before every order.

Everything a rule can ask about comes from the earlier days of the platform:

* **holdings and weights** from the Day 3 valuations, cash in each currency
  included, so the weights add up to one;
* **reference data** from the security master - sector, industry, issuer,
  country, currency - and a credit rating for the bond;
* **liquidity** from the Day 2 market data: days to liquidate is the position
  in shares over 20% of the average daily volume of the last twenty sessions,
  the participation rate a desk can trade without moving the price;
* **look-through** from the Day 4 benchmark: an index fund is its index's
  constituents in their weights on the day;
* **risk metrics** from the Day 5 model: each morning's volatility, tracking
  error and VaR forecast, and the active share against the policy benchmark.

The companion stocks of the benchmark carry synthetic industry labels so that
the exclusion list has something to find: one of them, a UK consumer goods
company, is classed as tobacco - reachable only through the world index fund.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import cached_property, lru_cache
from importlib import resources

import numpy as np

from ..accounting.valuation import PortfolioValuation
from ..compliance.engine import ComplianceReport, check
from ..compliance.language import Mandate
from ..compliance.monitor import Breach, ComplianceHistory, build_register
from ..compliance.parser import parse_mandate
from ..compliance.pretrade import Basket, Order, PreTradeChecker, PreTradeDecision
from ..compliance.snapshot import CASH_PREFIX, Attribute, Holding, Snapshot
from ..core.enums import TransactionType
from ..core.exceptions import ValidationError
from ..domain.instruments import Bond, Equity, Fund, instrument_price_scale
from ..performance.benchmark import BenchmarkDay
from .demo_performance import BOOK_CONSTITUENTS, COMPANIONS, FUND_SCOPE
from .demo_risk import BOOK_WARM_UP, DemoRisk, build_demo_risk

MANDATE_FILE = "global_equity_core.mandate"
PARTICIPATION = 0.20
ADV_WINDOW = 20
BOND_LIQUIDITY_DAYS = 1.0  # a Treasury trades in size the same day

#: Credit ratings by issuer (the security master holds none for the Treasury).
RATINGS = {"US-TREASURY": "AA+"}

#: Industry labels of the benchmark's companion stocks (synthetic, as the stocks are).
COMPANION_INDUSTRIES = {
    "BM-GB-CS-1": "Tobacco",
    "BM-US-IND-1": "Aerospace and Defence",
    "BM-US-ENE-1": "Integrated Oil and Gas",
    "BM-GB-ENE-1": "Integrated Oil and Gas",
    "BM-US-FIN-1": "Banks",
    "BM-GB-FIN-1": "Banks",
    "BM-JP-FIN-1": "Banks",
}
REGION_COUNTRY = {
    "North America": "US",
    "United Kingdom": "GB",
    "Europe ex UK": "EU",
    "Switzerland": "CH",
    "Japan": "JP",
}
TRADE_TYPES = {TransactionType.BUY, TransactionType.SELL, TransactionType.TRANSFER_IN, TransactionType.TRANSFER_OUT}

#: The orders the pre-trade chart and CLI walk through.
DEMO_ORDERS: tuple[Order, ...] = (
    Order("ORD-001", "US-MSFT", "buy", 100_000.0),
    Order("ORD-002", "US-MSFT", "sell", 50_000.0),
    Order("ORD-003", "US-AAPL", "buy", 50_000.0),
    Order("ORD-004", "US-JNJ", "buy", 150_000.0),
    Order("ORD-005", "IE-IWDA", "buy", 250_000.0),
    Order("ORD-006", "US-T-2032", "buy", 200_000.0),
    Order("ORD-007", "GB-BAE", "buy", 120_000.0),
    Order("ORD-008", "DE-BAYN", "sell", 100_000.0),
)


def load_mandate(name: str = MANDATE_FILE) -> Mandate:
    text = resources.files("meridian.compliance").joinpath("mandates").joinpath(name).read_text(encoding="utf-8")
    return parse_mandate(text)


def mandate_source(name: str = MANDATE_FILE) -> str:
    return resources.files("meridian.compliance").joinpath("mandates").joinpath(name).read_text(encoding="utf-8")


@dataclass(frozen=True)
class ReplayedOrder:
    """A historical trade put through the pre-trade check it never had."""

    day: date
    order: Order
    decision: str  # checked on its own
    reasons: tuple[str, ...]
    basket_decision: str = ""  # checked with the day's other orders
    basket_reasons: tuple[str, ...] = ()


@dataclass
class DemoCompliance:
    risk: DemoRisk
    mandate: Mandate

    # ------------------------------------------------------------------ reference data
    @property
    def accounting(self):  # type: ignore[no-untyped-def]
        return self.risk.performance.accounting

    @cached_property
    def valuations(self) -> list[PortfolioValuation]:
        return list(self.accounting.valuations)

    @cached_property
    def days(self) -> list[date]:
        return [valuation.day for valuation in self.valuations]

    def attributes(self, instrument_id: str) -> dict[str, Attribute]:
        instrument = self.accounting.instruments[instrument_id]
        currency = str(instrument.currency)
        base: dict[str, Attribute] = {"currency": currency, "country": instrument.country}
        if isinstance(instrument, Equity):
            return base | {
                "asset_class": "equity",
                "sector": instrument.sector,
                "industry": instrument.industry,
                "issuer": instrument.issuer_id or instrument_id,
            }
        if isinstance(instrument, Fund):
            return base | {"asset_class": "fund", "issuer": instrument_id}
        if isinstance(instrument, Bond):
            issuer = instrument.issuer_id or instrument_id
            return base | {
                "asset_class": "fixed income",
                "issuer": issuer,
                "rating": instrument.rating or RATINGS.get(issuer),
                "country": instrument.country or "US",
            }
        return base | {"asset_class": "other"}

    @cached_property
    def reference(self) -> dict[str, dict[str, Attribute]]:
        """Attributes of every security the book can hold, for orders in names not yet held."""
        return {
            key: self.attributes(key) for key, item in self.accounting.instruments.items() if not key.startswith("CASH")
        }

    @cached_property
    def average_volume(self) -> dict[str, dict[date, float]]:
        """Each instrument's average daily volume over the previous twenty sessions, by day."""
        output: dict[str, dict[date, float]] = {}
        for key, quotes in self.accounting.market.history.dataset.quotes.items():
            rows = sorted((quote.day, float(quote.volume or 0)) for quote in quotes)
            volumes = np.array([volume for _, volume in rows])
            cumulative = np.concatenate([[0.0], np.cumsum(volumes)])
            averages: dict[date, float] = {}
            for index, (day, _) in enumerate(rows):
                start = max(0, index - ADV_WINDOW)
                count = index - start
                averages[day] = float((cumulative[index] - cumulative[start]) / count) if count else float(volumes[0])
            output[key] = averages
        return output

    def days_to_liquidate(self, instrument_id: str, quantity: float, day: date) -> float:
        instrument = self.accounting.instruments[instrument_id]
        if isinstance(instrument, Bond):
            return BOND_LIQUIDITY_DAYS
        averages = self.average_volume.get(instrument_id, {})
        known = [value for when, value in averages.items() if when <= day]
        adv = known[-1] if known else 0.0
        return math.inf if adv <= 0 else abs(quantity) / (PARTICIPATION * adv)

    # ------------------------------------------------------------------ look-through
    @cached_property
    def constituent_attributes(self) -> dict[str, dict[str, Attribute]]:
        issuers = {
            key: self.attributes(key)["issuer"]
            for key in self.accounting.instruments
            if key in {row[0] for row in BOOK_CONSTITUENTS}
        }
        output: dict[str, dict[str, Attribute]] = {}
        for row in (*BOOK_CONSTITUENTS, *COMPANIONS):
            key, sector, region, currency = str(row[0]), str(row[2]), str(row[3]), str(row[4])
            book = self.accounting.instruments.get(key)
            industry = getattr(book, "industry", None) if book is not None else COMPANION_INDUSTRIES.get(key, sector)
            output[key] = {
                "asset_class": "equity",
                "sector": sector,
                "industry": industry,
                "issuer": issuers.get(key, key),
                "country": getattr(book, "country", None) or REGION_COUNTRY.get(region),
                "currency": currency,
            }
        return output

    def look_through(self, benchmark_day: BenchmarkDay) -> dict[str, tuple[Holding, ...]]:
        output: dict[str, tuple[Holding, ...]] = {}
        for fund, region in FUND_SCOPE.items():
            pieces = [
                piece
                for piece in benchmark_day.pieces
                if piece.key in self.constituent_attributes and (region is None or piece.region == region)
            ]
            total = sum(piece.weight for piece in pieces)
            output[fund] = tuple(
                Holding(piece.key, piece.weight / total, self.constituent_attributes[piece.key]) for piece in pieces
            )
        return output

    # ------------------------------------------------------------------ metrics
    @cached_property
    def metrics_by_day(self) -> dict[date, dict[str, float]]:
        output: dict[date, dict[str, float]] = {}
        for forecast in self.risk.book_forecasts:
            scale = math.sqrt(252 / forecast.weekdays)
            output[forecast.day] = {
                "volatility": forecast.volatility * scale,
                "tracking_error": forecast.tracking_error * scale,
                "var_99": forecast.var / math.sqrt(forecast.weekdays),
            }
        for index in range(BOOK_WARM_UP, len(self.risk.valuation_days)):
            day = self.risk.valuation_days[index]
            portfolio = self.risk.portfolio_weights(index)
            benchmark = self.risk.benchmark_weights(index)
            keys = {key for key in portfolio.keys() | benchmark.keys() if not key.endswith(":basis")}
            share = 0.5 * sum(abs(portfolio.get(key, 0.0) - benchmark.get(key, 0.0)) for key in keys)
            output.setdefault(day, {})["active_share"] = share
        return output

    # ------------------------------------------------------------------ snapshots
    def snapshot(self, index: int) -> Snapshot:
        valuation = self.valuations[index]
        nav = float(valuation.nav)
        holdings: list[Holding] = []
        for position in valuation.positions:
            attributes = self.attributes(position.instrument_id)
            attributes["days_to_liquidate"] = self.days_to_liquidate(
                position.instrument_id, float(position.quantity), valuation.day
            )
            holdings.append(Holding(position.instrument_id, float(position.total_base) / nav, attributes))
        for line in valuation.cash:
            value = float(line.total_base)  # cash, receivables, payables (negative), income due, reclaims
            if abs(value) > 0:
                holdings.append(
                    Holding(
                        f"{CASH_PREFIX}{line.currency}",
                        value / nav,
                        {
                            "asset_class": "cash",
                            "currency": line.currency,
                            "issuer": f"cash {line.currency}",
                            "days_to_liquidate": 0.0,
                        },
                    )
                )
        total = sum(holding.weight for holding in holdings)
        if abs(total - 1.0) > 1e-9:
            raise ValidationError(f"{valuation.day}: holdings add up to {total:.6f} of NAV, not one")
        benchmark_day = self.risk.performance.benchmark_days[max(index - 1, 0)]
        return Snapshot(
            valuation.day,
            nav,
            tuple(holdings),
            self.metrics_by_day.get(valuation.day, {}),
            self.look_through(benchmark_day),
        )

    @cached_property
    def history(self) -> ComplianceHistory:
        reports = [
            check(self.mandate, self.snapshot(index))
            for index, day in enumerate(self.days)
            if day >= self.mandate.effective  # before its effective date the account was still being funded
        ]
        return ComplianceHistory(reports, build_register(reports, self.traded, self.groups_of))

    @property
    def today(self) -> ComplianceReport:
        return self.history.reports[-1]

    @cached_property
    def traded(self) -> dict[date, set[str]]:
        output: dict[date, set[str]] = defaultdict(set)
        for transaction in self.accounting.book.transactions:
            if transaction.transaction_type in TRADE_TYPES and transaction.instrument_id:
                output[transaction.trade_date].add(transaction.instrument_id)
        return dict(output)

    @cached_property
    def groups_of(self) -> dict[str, set[str]]:
        """Every label an instrument's trades can touch: its own attributes, and a fund's constituents'."""
        output: dict[str, set[str]] = {}
        snapshot = self.snapshot(len(self.valuations) - 1)
        for key, attributes in self.reference.items():
            labels = {str(value) for name, value in attributes.items() if name != "asset_class" and value is not None}
            for constituent in snapshot.look_through.get(key, ()):
                labels |= {constituent.key} | {
                    str(value) for value in constituent.attributes.values() if value is not None
                }
            output[key] = labels
        return output

    @property
    def breaches(self) -> list[Breach]:
        return self.history.breaches

    # ------------------------------------------------------------------ pre-trade
    def metric_model(self, snapshot: Snapshot) -> dict[str, float]:
        """Volatility, tracking error and VaR of a proposed portfolio, from the Day 5 model on the last day."""
        weights: dict[str, float] = defaultdict(float)
        index = self.risk.last
        bench = self.risk.performance.benchmark_days[index - 1]
        for holding in snapshot.holdings:
            if holding.key in FUND_SCOPE:
                for constituent, share in self.risk._fund_shares(holding.key, bench).items():
                    weights[constituent] += holding.weight * share
                weights[f"{holding.key}:basis"] += holding.weight
            else:
                key = holding.key.replace(CASH_PREFIX, "CASH:")
                weights[key] += holding.weight
        model = self.risk.model
        known = {key: value for key, value in weights.items() if key in model.exposures}
        total = model.decompose(known)
        active = dict(known)
        for key, value in self.risk.benchmark_weights(index).items():
            active[key] = active.get(key, 0.0) - value
        tracking = model.decompose(active)
        metrics = dict(snapshot.metrics)
        metrics.update(
            {"volatility": total.volatility, "tracking_error": tracking.volatility, "var_99": 2.3263 * total.daily}
        )
        return metrics

    @cached_property
    def pretrade(self) -> PreTradeChecker:
        return PreTradeChecker(
            self.mandate, self.today_snapshot, reference=self.reference, metric_model=self.metric_model
        )

    @cached_property
    def today_snapshot(self) -> Snapshot:
        return self.snapshot(len(self.valuations) - 1)

    @cached_property
    def demo_decisions(self) -> list[PreTradeDecision]:
        return [self.pretrade.check(order) for order in DEMO_ORDERS]

    @cached_property
    def replayed(self) -> list[ReplayedOrder]:
        """Every buy and sell of the Day 3 book, checked against the portfolio of the evening before.

        The book was traded without a compliance engine; this is what one would
        have said. Risk metrics are not re-forecast for past days, so metric
        rules keep the morning's value.
        """
        index_of = {day: index for index, day in enumerate(self.days)}
        singles: list[ReplayedOrder] = []
        counter = 0
        for transaction in sorted(self.accounting.book.transactions, key=lambda item: item.trade_date):
            kind = transaction.transaction_type
            if kind not in (TransactionType.BUY, TransactionType.SELL) or not transaction.instrument_id:
                continue
            previous = max((day for day in self.days if day < transaction.trade_date), default=None)
            if previous is None or previous < self.mandate.effective:
                continue
            instrument = self.accounting.instruments[transaction.instrument_id]
            rate = float(self.accounting.fx.rate(str(transaction.currency), "USD", previous))
            amount = float(transaction.quantity * transaction.price * instrument_price_scale(instrument)) * rate
            counter += 1
            order = Order(
                f"HIST-{counter:03d}",
                transaction.instrument_id,
                "buy" if kind is TransactionType.BUY else "sell",
                amount,
            )
            checker = PreTradeChecker(self.mandate, self.snapshot(index_of[previous]), reference=self.reference)
            decision = checker.check(order, find_maximum=False)
            reasons = tuple(f"{change.rule_id}: {change.effect}" for change in decision.reasons)
            singles.append(ReplayedOrder(transaction.trade_date, order, decision.decision, reasons))
        output: list[ReplayedOrder] = []
        for day in sorted({item.day for item in singles}):
            todays = [item for item in singles if item.day == day]
            previous = max(when for when in self.days if when < day)
            checker = PreTradeChecker(self.mandate, self.snapshot(index_of[previous]), reference=self.reference)
            basket = checker.check_basket(Basket(f"BASKET-{day.isoformat()}", tuple(item.order for item in todays)))
            reasons = tuple(f"{change.rule_id}: {change.effect}" for change in basket.reasons)
            output.extend(
                ReplayedOrder(item.day, item.order, item.decision, item.reasons, basket.decision, reasons)
                for item in todays
            )
        return output

    @cached_property
    def ucits(self) -> ComplianceHistory:
        """The UCITS eligibility screen run over the same days: would the account qualify?"""
        screen = load_mandate("ucits_screen.mandate")
        reports = [
            check(screen, self.snapshot(index)) for index, day in enumerate(self.days) if day >= screen.effective
        ]
        return ComplianceHistory(reports)


@lru_cache(maxsize=2)
def build_demo_compliance() -> DemoCompliance:
    logging.getLogger().setLevel(logging.WARNING)
    return DemoCompliance(build_demo_risk(), load_mandate())
