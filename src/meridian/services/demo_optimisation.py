"""Tax-aware rebalancing for the demonstration account, on its report date.

The account's positions and tax lots come from the Day 3 book, its target from
the Day 4 policy benchmark, its risk from the Day 5 model and its limits from
the Day 6 mandate:

* **assets**: every security the account holds, and every constituent of the
  benchmark it could buy - thirty more stocks, the natural substitutes when a
  loss is harvested;
* **lots**: the book's open tax lots, each with its tax basis (wash-sale
  adjustments included) and the date its holding period runs from;
* **costs**: commission of 5 bp, half the Day 2 bid-ask spread, and
  square-root impact on the Day 2 average daily volume;
* **risk**: the Day 5 factor model on its coverage assets, a fund being its
  constituents plus its basis, and the target being the policy benchmark;
* **limits**: the Day 6 mandate, compiled into constraints where it can be.

Cash in other currencies (about 1% of NAV) is counted with dollar cash: the
optimiser rebalances securities, and the treasury desk converts cash.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import cached_property, lru_cache

import numpy as np

from ..compliance.pretrade import Basket, BasketDecision, Order, PreTradeChecker
from ..marketdata.series import TimeSeries
from ..optimisation.assets import CostModel, LotState, TradableAsset
from ..optimisation.backtest import BacktestSummary, SimulationConfig, TaxAlphaBacktest
from ..optimisation.frontier import Frontier, tax_frontier
from ..optimisation.rebalance import LotSale, Rebalancer, RebalanceResult, RiskView, Settings
from ..optimisation.rounding import RoundedRebalance, round_trades
from .demo_compliance import DemoCompliance, build_demo_compliance
from .demo_performance import FUND_SCOPE
from .demo_risk import BASIS_SUFFIX, DemoRisk

PARTICIPATION_DAYS = 20
UNIVERSE_INDEX_SIZE = 100  # stocks in the backtest's index: the largest of the Day 5 estimation universe
#: the house view: tracking error priced at ten times its square against tax and cost in fractions of NAV
HOUSE = Settings(risk_aversion=10.0)
#: the same account managed without regard to tax, lots relieved first in, first out
TAX_BLIND = Settings(risk_aversion=10.0, tax_weight=0.0, lot_relief="fifo")
#: tax-aware, but letting losses sit
NO_HARVEST = Settings(risk_aversion=10.0, harvest=False)
FRONTIER_POINTS = 12
BACKTEST_PATHS = 16
BACKTEST = SimulationConfig(months=36, reconstitution_noise=0.20)
#: board lots by market: Tokyo trades in units of 100 shares; the other markets here trade single shares
BOARD_LOTS = {"JP": 100.0}


def round_lot(attributes: dict) -> float:
    return BOARD_LOTS.get(str(attributes.get("country")), 1.0)


def _last(series: TimeSeries, day: date) -> float:
    found = series.as_of(day, max_age_days=10)
    if found is None:
        raise ValueError(f"no value on {day}")
    return float(found.value)


@dataclass
class DemoOptimisation:
    compliance: DemoCompliance

    @property
    def risk(self) -> DemoRisk:
        return self.compliance.risk

    @property
    def accounting(self):  # type: ignore[no-untyped-def]
        return self.risk.performance.accounting

    @cached_property
    def as_of(self) -> date:
        return self.risk.valuation_days[-1]

    @cached_property
    def valuation(self):  # type: ignore[no-untyped-def]
        return self.accounting.valuations[-1]

    @cached_property
    def nav(self) -> float:
        return float(self.valuation.nav)

    # ------------------------------------------------------------------ market data for every asset
    @cached_property
    def specs(self) -> dict:
        found = dict(self.accounting.market.history.specs)
        found.update(self.risk.performance.universe.specs)
        return found

    @cached_property
    def closes(self) -> dict[str, list]:
        quotes: dict[str, list] = defaultdict(list)
        for dataset in (self.accounting.market.history.dataset, self.risk.performance.universe.dataset):
            for key, items in dataset.quotes.items():
                quotes[key].extend(items)
        return quotes

    def accrued(self, asset_id: str) -> float:
        """Base-currency accrued interest per unit (a bond's; zero for anything else)."""
        position = self.valuation.position(asset_id) if asset_id in self.held else None
        return float(position.accrued_per_unit * position.fx_rate) if position is not None else 0.0

    def unit_price(self, asset_id: str) -> float:
        """Base-currency clean price of one unit on the report date."""
        position = self.valuation.position(asset_id) if asset_id in self.held else None
        if position is not None:
            return float(position.price * position.scale * position.fx_rate)
        rows = sorted((quote.day, quote) for quote in self.closes[asset_id] if quote.day <= self.as_of)
        quote = rows[-1][1]
        rate = float(self.accounting.fx.rate(quote.currency, "USD", self.as_of))
        return float(quote.close) * rate

    def daily_volume(self, asset_id: str, price: float) -> float:
        rows = sorted(
            (quote.day, float(quote.volume or 0)) for quote in self.closes[asset_id] if quote.day <= self.as_of
        )
        recent = [volume for _, volume in rows[-PARTICIPATION_DAYS:]]
        return float(np.mean(recent)) * price if recent else 0.0

    def daily_volatility(self, asset_id: str) -> float:
        returns = self.risk.asset_returns.get(asset_id)
        if returns is None:
            return 0.015
        return float(np.std(returns[1][-252:], ddof=1))

    # ------------------------------------------------------------------ the assets
    @cached_property
    def held(self) -> set[str]:
        return {position.instrument_id for position in self.valuation.positions}

    @cached_property
    def candidates(self) -> list[str]:
        """Held securities first, then every benchmark constituent not held."""
        constituents = [key for key in self.compliance.constituent_attributes if key not in self.held]
        return sorted(self.held) + sorted(constituents)

    def risk_row(self, asset_id: str) -> dict[str, float]:
        if asset_id in FUND_SCOPE:
            bench = self.risk.performance.benchmark_days[self.risk.last - 1]
            row = dict(self.risk._fund_shares(asset_id, bench))
            row[f"{asset_id}{BASIS_SUFFIX}"] = 1.0
            return row
        return {asset_id: 1.0}

    def lots(self, asset_id: str, price: float) -> tuple[LotState, ...]:
        output = []
        for lot in self.accounting.book.open_lots.get(asset_id, ()):
            output.append(
                LotState(
                    lot_id=lot.lot_id,
                    asset_id=asset_id,
                    quantity=float(lot.quantity),
                    basis_per_unit=float(lot.base_cost_per_unit + lot.wash_sale_adjustment),
                    holding_start=lot.holding_period_start or lot.open_date,
                    opened=lot.open_date,
                )
            )
        return tuple(output)

    def attributes(self, asset_id: str) -> dict:
        if asset_id in self.accounting.instruments and not asset_id.startswith("CASH"):
            return dict(self.compliance.attributes(asset_id))
        return dict(self.compliance.constituent_attributes[asset_id])

    @cached_property
    def assets(self) -> list[TradableAsset]:
        output = []
        for asset_id in self.candidates:
            price = self.unit_price(asset_id)
            spec = self.specs.get(asset_id)
            lots = self.lots(asset_id, price)
            quantity = sum(lot.quantity for lot in lots)
            output.append(
                TradableAsset(
                    asset_id=asset_id,
                    price=price,
                    quantity=quantity,
                    lots=lots,
                    spread_bps=float(spec.spread_bps) if spec is not None else 6.0,
                    daily_volatility=self.daily_volatility(asset_id),
                    daily_volume=self.daily_volume(asset_id, price),
                    lot_size=round_lot(self.attributes(asset_id)),
                    attributes=self.attributes(asset_id),
                    risk_row=self.risk_row(asset_id),
                    accrued_per_unit=self.accrued(asset_id),
                )
            )
        return output

    @cached_property
    def cash(self) -> float:
        return sum(float(line.total_base) for line in self.valuation.cash) / self.nav

    # ------------------------------------------------------------------ the risk view
    @cached_property
    def risk_view(self) -> RiskView:
        model = self.risk.model
        keys = tuple(key for key in model.assets if not key.startswith("CASH:"))
        benchmark = self.risk.benchmark_weights(self.risk.last)
        return RiskView(
            keys=keys,
            exposures=model.exposure_matrix(keys),
            factor_covariance=model.factor_covariance,
            specific=np.array([model.specific_variance[key] for key in keys]),
            benchmark=np.array([benchmark.get(key, 0.0) for key in keys]),
            benchmark_cash=sum(value for key, value in benchmark.items() if key.startswith("CASH:")),
            holding_mask=np.array([not key.endswith(BASIS_SUFFIX) for key in keys]),
        )

    @cached_property
    def index_risk(self) -> RiskView:
        """The equity index the backtest's account tracks: the benchmark's stocks, re-weighted to sum to one."""
        view = self.risk_view
        keep = np.flatnonzero((view.benchmark > 0) & view.mask)
        weights = view.benchmark[keep]
        return RiskView(
            keys=tuple(view.keys[i] for i in keep),
            exposures=view.exposures[keep],
            factor_covariance=view.factor_covariance,
            specific=view.specific[keep],
            benchmark=weights / weights.sum(),
        )

    def universe_risk(self, size: int = UNIVERSE_INDEX_SIZE, specific_days: int = 126) -> RiskView:
        """An index of the Day 5 estimation universe's largest stocks, cap-weighted, on the model's last day.

        The account's own benchmark has thirty-odd stocks; a direct-indexing
        account holds hundreds, which is what gives a harvested loss its
        substitutes. Exposures are the universe's own (styles, industries and
        currencies), the factor covariance the Day 5 forecast, and specific
        risk the variance of each stock's recent regression residuals.
        """
        risk = self.risk
        estimated, history = risk.estimated, risk.universe
        position = len(estimated.days) - 1
        matrix = estimated.exposure_on(position)
        currencies = history.currency_matrix()
        exposures = np.column_stack([matrix.local(), currencies])
        caps = history.caps[estimated.first_index + position]
        chosen = np.sort(np.argsort(caps)[::-1][:size])
        specific = np.var(estimated.specific[-specific_days:, chosen], axis=0, ddof=1)
        weights = caps[chosen] / caps[chosen].sum()
        covariance = risk.model.factor_covariance
        if covariance.shape[0] != exposures.shape[1]:
            raise ValueError("the universe's exposures do not match the model's factors")
        return RiskView(
            keys=tuple(history.stocks[i].stock_id for i in chosen),
            exposures=exposures[chosen],
            factor_covariance=covariance,
            specific=specific,
            benchmark=weights,
        )

    def rebalancer(self, *, mandate: bool = True, costs: CostModel | None = None) -> Rebalancer:
        snapshot = self.compliance.today_snapshot
        return Rebalancer(
            self.as_of,
            self.nav,
            self.assets,
            self.cash,
            self.risk_view,
            costs=costs,
            mandate=self.compliance.mandate if mandate else None,
            look_through=snapshot.look_through,
        )

    @cached_property
    def pretrade(self) -> PreTradeChecker:
        """The Day 6 engine on today's snapshot, with reference data for every name the optimiser may buy."""
        reference = {**self.compliance.reference, **self.compliance.constituent_attributes}
        return PreTradeChecker(
            self.compliance.mandate,
            self.compliance.today_snapshot,
            reference=reference,
            metric_model=self.compliance.metric_model,
        )

    def post_trade(self, result: RebalanceResult, basket_id: str = "REBALANCE") -> BasketDecision:
        """The proposed trades checked as one basket by the compliance engine, independently of the optimiser."""
        orders = [
            Order(f"{basket_id}-S{number:02d}", asset_id, "sell", weight * self.nav)
            for number, (asset_id, weight) in enumerate(sorted(result.sells.items()), start=1)
        ]
        orders += [
            Order(f"{basket_id}-B{number:02d}", asset_id, "buy", weight * self.nav)
            for number, (asset_id, weight) in enumerate(sorted(result.buys.items()), start=1)
        ]
        return self.pretrade.check_basket(Basket(basket_id, tuple(orders)))

    # ------------------------------------------------------------------ the proposal
    @cached_property
    def house(self) -> Rebalancer:
        return self.rebalancer()

    @cached_property
    def proposal(self) -> RebalanceResult:
        """The rebalance the house view proposes today."""
        return self.house.solve(HOUSE)

    @cached_property
    def alternatives(self) -> dict[str, RebalanceResult]:
        """The same day rebalanced by the three managers, the house view last."""
        return {
            "tax-blind": self.house.solve(TAX_BLIND),
            "tax-aware, no harvesting": self.house.solve(NO_HARVEST),
            "tax-aware, harvesting": self.proposal,
        }

    @cached_property
    def tickets(self) -> RoundedRebalance:
        return round_trades(self.house, self.proposal, HOUSE)

    @cached_property
    def compliance_check(self) -> BasketDecision:
        return self.post_trade(self.proposal)

    @cached_property
    def relief(self) -> dict[str, list[LotSale]]:
        return self.house.relief_comparison(self.proposal)

    @cached_property
    def frontier(self) -> Frontier:
        return tax_frontier(self.house, HOUSE, points=FRONTIER_POINTS)

    @cached_property
    def backtest(self) -> BacktestSummary:
        return TaxAlphaBacktest(self.universe_risk(), BACKTEST).run_paths(BACKTEST_PATHS)

    def check_weights(self) -> float:
        """Securities plus cash must be the whole account."""
        securities = sum(asset.value for asset in self.assets) / self.nav
        return abs(securities + self.cash - 1.0)


@lru_cache(maxsize=2)
def build_demo_optimisation() -> DemoOptimisation:
    logging.getLogger().setLevel(logging.WARNING)
    return DemoOptimisation(build_demo_compliance())
