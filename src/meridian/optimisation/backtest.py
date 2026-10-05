"""Tax alpha: the same account managed four ways through the same simulated markets.

A one-day rebalance shows what tax-aware trading saves today; whether it adds
up to anything is a question about years. The backtest follows a taxable
account tracking an equity index month by month, through markets simulated
from the Day 5 factor model, and runs four managers side by side on the very
same prices:

* **buy and hold** - invests once and never trades: no tax until the end, and a
  tracking error that grows as the index changes;
* **tax-blind** - tracks the index as closely as it can, relieving lots first
  in, first out, and never counting tax;
* **tax-aware** - trades tracking error against tax, choosing lots, but lets
  losses sit;
* **tax-aware, harvesting** - also sells lots standing at a loss, buys
  correlated substitutes to keep the tracking error in check, and banks the
  losses against gains now and later.

The index is reconstituted every quarter - its weights move towards a new
policy - which is what forces an indexer to trade, and to realise gains.

**The tax ledger is the US one**: gains short- or long-term by holding period,
netted each year (Schedule D), a net loss offsetting $3,000 of ordinary income
with the rest carried forward, and tax paid out of the account at each year
end. A loss sold within 30 days of buying the same stock is disallowed and
added to the basis of the replacement (the wash-sale rule), and a stock sold at
a loss may not be bought back for 30 days.

**Tax alpha** is the annual after-tax return over the tax-blind manager's, on
the value the account would have if it were liquidated at the end and every
remaining gain taxed - the honest comparison, since deferral that ends in a
liquidation bill is worth less than it looks on a pre-liquidation statement.
Losses harvested reset the basis lower, so part of the benefit is deferral;
liquidation value counts that. Dividends are left out: every manager would
receive the same ones.

The simulation is small and quick (a few dozen stocks, monthly steps) so it
can run over many paths: tax alpha is a distribution, largest early and in
volatile years, and one path is an anecdote.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import numpy as np

from ..accounting.tax import DEFAULT_RATES, TaxRates
from ..core.exceptions import ValidationError
from .assets import CostModel, LotState, TradableAsset
from .rebalance import TRADE_EPSILON, WHOLE_LOT, Rebalancer, RebalanceResult, RiskView, Settings
from .taxes import WASH_SALE_DAYS, TaxAccount, long_rate, short_rate

TRADING_DAYS_PER_MONTH = 21
TE_LIMIT = 0.015  # the tax-aware managers' tracking-error budget, the same for both so they compare fairly


@dataclass(frozen=True)
class Strategy:
    name: str
    settings: Settings | None  # None: buy and hold


def default_strategies(
    cash_band: tuple[float, float] = (0.005, 0.03), rates: TaxRates = DEFAULT_RATES
) -> tuple[Strategy, ...]:
    base = Settings(cash_band=cash_band, limit_buffer=0.0)
    return (
        Strategy("buy and hold", None),
        Strategy("tax-blind", replace(base, risk_aversion=200.0, tax_weight=0.0, harvest=False, lot_relief="fifo")),
        Strategy("tax-aware", replace(base, risk_aversion=20.0, harvest=False, te_limit=TE_LIMIT)),
        # a harvested loss saves the short-term rate on the client's other gains now and gives back the
        # long-term rate when the lower basis is realised at the end: net, the difference is what it is worth
        Strategy(
            "tax-aware, harvesting",
            replace(
                base,
                risk_aversion=20.0,
                harvest=True,
                loss_rate=short_rate(rates) - long_rate(rates),
                te_limit=TE_LIMIT,
            ),
        ),
    )


@dataclass(frozen=True)
class SimulationConfig:
    months: int = 36
    start: date = date(2022, 1, 31)
    nav: float = 5_000_000.0
    annual_drift: float = 0.07
    reconstitution_months: int = 3
    reconstitution_noise: float = 0.30  # log-normal dispersion of the policy weights at each reconstitution
    daily_volume: float = 50_000_000.0
    spread_bps: float = 5.0
    #: short-term gains the client realises elsewhere each year (an active manager, a hedge fund), as a fraction
    #: of the account's starting value: what harvested losses offset, and the usual reason an account harvests
    outside_gains: float = 0.02
    seed: int = 7

    def __post_init__(self) -> None:
        if self.months < 2:
            raise ValidationError("a backtest needs at least two months")
        if self.nav <= 0:
            raise ValidationError("the account must be worth something")
        if self.outside_gains < 0:
            raise ValidationError("outside gains must not be negative")


def month_end(start: date, months: int) -> date:
    year, month = divmod(start.month - 1 + months, 12)
    year += start.year
    return date(year, month + 1, calendar.monthrange(year, month + 1)[1])


@dataclass
class Market:
    """Prices of the universe and the index's weights, month by month, from the factor model."""

    keys: tuple[str, ...]
    days: list[date]
    prices: np.ndarray  # (months + 1) x n
    targets: np.ndarray  # (months + 1) x n: the index's weights at each month end, before trading
    index_returns: np.ndarray  # months: the index's return over each month
    daily_volatility: np.ndarray  # n

    @classmethod
    def simulate(cls, risk: RiskView, policy: np.ndarray, config: SimulationConfig) -> Market:
        rng = np.random.default_rng(config.seed)
        n = len(risk.keys)
        chol = risk.cholesky()
        drift = (1 + config.annual_drift) ** (1 / 12) - 1
        daily_variance = np.einsum("ik,kl,il->i", risk.exposures, risk.factor_covariance, risk.exposures)
        daily_variance = daily_variance + risk.specific
        monthly_variance = TRADING_DAYS_PER_MONTH * daily_variance
        prices = np.ones((config.months + 1, n)) * 100.0
        targets = np.zeros((config.months + 1, n))
        index_returns = np.zeros(config.months)
        policy = policy / policy.sum()
        units = policy / prices[0]
        targets[0] = policy
        for month in range(1, config.months + 1):
            factor_shock = chol @ rng.standard_normal(chol.shape[1]) * math.sqrt(TRADING_DAYS_PER_MONTH)
            specific_shock = rng.standard_normal(n) * np.sqrt(TRADING_DAYS_PER_MONTH * risk.specific)
            log_return = drift - 0.5 * monthly_variance + risk.exposures @ factor_shock + specific_shock
            prices[month] = prices[month - 1] * np.exp(log_return)
            before = units @ prices[month - 1]
            index_returns[month - 1] = units @ prices[month] / before - 1
            weights = units * prices[month] / (units @ prices[month])
            if month % config.reconstitution_months == 0:
                moved = policy * np.exp(config.reconstitution_noise * rng.standard_normal(n))
                weights = moved / moved.sum()
                units = weights / prices[month]
            targets[month] = weights
        days = [month_end(config.start, month) for month in range(config.months + 1)]
        return cls(risk.keys, days, prices, targets, index_returns, np.sqrt(daily_variance))

    @classmethod
    def from_history(
        cls,
        keys: Sequence[str],
        days: Sequence[date],
        returns: np.ndarray,
        targets: np.ndarray,
        daily_volatility: np.ndarray,
    ) -> Market:
        """A market that happened: monthly returns and the index's weights at each month end.

        ``returns`` is months x n, the return over the month ending on ``days[t + 1]``;
        ``targets`` is (months + 1) x n. The index earns its weights at the start of
        each month, so its return is ``targets[t] @ returns[t]``.
        """
        months = len(days) - 1
        if returns.shape != (months, len(keys)) or targets.shape != (months + 1, len(keys)):
            raise ValidationError("returns need one row per month and targets one per month end")
        if np.any(returns <= -1):
            raise ValidationError("a return of -100% or worse leaves no price")
        prices = 100.0 * np.vstack([np.ones(len(keys)), np.cumprod(1 + returns, axis=0)])
        weights = targets / targets.sum(axis=1, keepdims=True)
        index_returns = np.einsum("tn,tn->t", weights[:-1], returns)
        return cls(tuple(keys), list(days), prices, weights, index_returns, np.asarray(daily_volatility, dtype=float))


@dataclass
class MonthRecord:
    day: date
    nav: float  # before this month's trades, after last year's tax
    tracking_error: float  # ex ante, after the trades
    realised_gains: float
    realised_losses: float
    harvested: float  # losses realised this month (wash-sale disallowances excluded)
    disallowed: float
    tax_paid: float  # at a year end, the year's bill (negative: a refund of the ordinary-income offset)
    turnover: float
    cost: float  # base currency
    unrealised: float  # gain standing in the account after the trades
    carryforward: float
    cash: float = 0.0  # fraction of NAV after the trades (and any tax paid)


@dataclass
class StrategyPath:
    strategy: str
    records: list[MonthRecord] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)  # monthly, after costs and tax paid
    liquidation_tax: float = 0.0
    final_nav: float = 0.0

    @property
    def liquidation_value(self) -> float:
        return self.final_nav - self.liquidation_tax

    @property
    def tax_paid(self) -> float:
        return sum(record.tax_paid for record in self.records)

    @property
    def pre_tax_growth(self) -> float:
        """Growth of one dollar before tax: the monthly returns linked, each year's tax an outflow, not a loss."""
        return float(np.prod(1 + np.array(self.returns)))

    @property
    def harvested(self) -> float:
        return sum(record.harvested for record in self.records)


@dataclass
class _Account:
    lots: list[LotState]
    cash: float
    ledger: TaxAccount
    loss_sales: dict[str, date] = field(default_factory=dict)
    counter: int = 0

    def next_id(self, asset_id: str) -> str:
        self.counter += 1
        return f"{asset_id}#{self.counter:04d}"


class TaxAlphaBacktest:
    def __init__(
        self,
        risk: RiskView,
        config: SimulationConfig | None = None,
        *,
        strategies: Sequence[Strategy] | None = None,
        rates: TaxRates = DEFAULT_RATES,
        costs: CostModel | None = None,
    ) -> None:
        self.risk = risk
        self.config = config or SimulationConfig()
        self.strategies = tuple(strategies or default_strategies())
        self.rates = rates
        self.costs = costs or CostModel()
        if risk.benchmark.sum() <= 0:
            raise ValidationError("the index needs positive weights")

    # ------------------------------------------------------------------ one path
    def run(self, seed: int | None = None, progress: Callable[[str], None] | None = None) -> PathOutcome:
        config = self.config if seed is None else replace(self.config, seed=seed)
        return self.run_market(Market.simulate(self.risk, self.risk.benchmark, config), config, progress)

    def run_market(
        self, market: Market, config: SimulationConfig | None = None, progress: Callable[[str], None] | None = None
    ) -> PathOutcome:
        """The four managers through one given market: simulated, or history."""
        config = replace(config or self.config, months=len(market.days) - 1, start=market.days[0])
        if market.keys != self.risk.keys:
            raise ValidationError("the market and the risk model must cover the same assets")
        strategies = {
            strategy.name: self._run_strategy(strategy, market, config, progress) for strategy in self.strategies
        }
        returns = market.prices[1:] / market.prices[:-1] - 1
        return PathOutcome(config.seed, market.days, market.index_returns, strategies, returns.std(axis=1))

    def _assets(self, account: _Account, market: Market, month: int) -> list[TradableAsset]:
        by_asset: dict[str, list[LotState]] = {}
        for lot in account.lots:
            by_asset.setdefault(lot.asset_id, []).append(lot)
        output = []
        for index, key in enumerate(market.keys):
            lots = tuple(by_asset.get(key, ()))
            output.append(
                TradableAsset(
                    asset_id=key,
                    price=float(market.prices[month, index]),
                    quantity=sum(lot.quantity for lot in lots),
                    lots=lots,
                    spread_bps=self.config.spread_bps,
                    daily_volatility=float(market.daily_volatility[index]),
                    daily_volume=self.config.daily_volume,
                    risk_row={key: 1.0},
                )
            )
        return output

    def _value(self, account: _Account, market: Market, month: int) -> float:
        index = {key: position for position, key in enumerate(market.keys)}
        held = sum(lot.quantity * market.prices[month, index[lot.asset_id]] for lot in account.lots)
        return float(held + account.cash)

    def _run_strategy(
        self, strategy: Strategy, market: Market, config: SimulationConfig, progress: Callable[[str], None] | None
    ) -> StrategyPath:
        path = StrategyPath(strategy.name)
        account = _Account([], config.nav, TaxAccount(self.rates))
        start_cash = strategy.settings.cash_band[0] if strategy.settings is not None else 0.005
        for index, key in enumerate(market.keys):
            weight = market.targets[0, index] * (1 - start_cash)
            if weight <= 0:
                continue
            quantity = weight * config.nav / market.prices[0, index]
            account.lots.append(
                LotState(
                    account.next_id(key), key, quantity, float(market.prices[0, index]), market.days[0], market.days[0]
                )
            )
            account.cash -= weight * config.nav
        previous = config.nav
        for month in range(1, config.months + 1):
            day = market.days[month]
            nav = self._value(account, market, month)
            path.returns.append(nav / previous - 1)
            record = MonthRecord(day, nav, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, account.ledger.carryforward)
            if strategy.settings is not None:
                self._rebalance(strategy.settings, account, market, month, record)
            else:
                risk = replace(self.risk, benchmark=market.targets[month])
                held = self._assets(account, market, month)
                weights = np.array([asset.value for asset in held]) / nav
                record.tracking_error = risk.tracking_error(weights)
            if day.month == 12:
                record.tax_paid = self._close_year(account.ledger, day.year)
                account.cash -= record.tax_paid
                record.carryforward = account.ledger.carryforward
            column = {key: position for position, key in enumerate(market.keys)}
            record.unrealised = float(
                sum(
                    lot.quantity * (market.prices[month, column[lot.asset_id]] - lot.basis_per_unit)
                    for lot in account.lots
                )
            )
            record.cash = account.cash / self._value(account, market, month)
            path.records.append(record)
            previous = self._value(account, market, month)
            if progress is not None:
                progress(f"{strategy.name} {day}")
        path.final_nav = previous
        path.liquidation_tax = self._liquidation_tax(account, market)
        return path

    def _rebalance(
        self, settings: Settings, account: _Account, market: Market, month: int, record: MonthRecord
    ) -> None:
        day = market.days[month]
        nav = self._value(account, market, month)
        assets = self._assets(account, market, month)
        forbidden = frozenset(key for key, sold in account.loss_sales.items() if (day - sold).days <= WASH_SALE_DAYS)
        risk = replace(self.risk, benchmark=market.targets[month])
        rebalancer = Rebalancer(day, nav, assets, account.cash / nav, risk, costs=self.costs, rates=self.rates)
        result = rebalancer.solve(replace(settings, forbidden_buys=settings.forbidden_buys | forbidden))
        self._apply(result, rebalancer, account, market, month, record)

    def _apply(
        self,
        result: RebalanceResult,
        rebalancer: Rebalancer,
        account: _Account,
        market: Market,
        month: int,
        record: MonthRecord,
    ) -> None:
        day = market.days[month]
        nav = rebalancer.nav
        index = {key: position for position, key in enumerate(market.keys)}
        remaining = {lot.lot_id: lot for lot in account.lots}
        for sale in result.sales:
            lot = remaining[sale.lot.lot_id]
            units = min(sale.units, lot.quantity)
            left = lot.quantity - units
            if left <= WHOLE_LOT * lot.quantity:
                units = lot.quantity
                del remaining[lot.lot_id]
            else:
                remaining[lot.lot_id] = replace(lot, quantity=left)
            gain = sale.gain * units / sale.units if sale.units > 0 else 0.0
            if gain < 0 and sale.wash_sale:
                record.disallowed -= gain
                self._defer_loss(remaining, lot, -gain, day)
                continue
            account.ledger.realise(day, gain, sale.long_term)
            if gain >= 0:
                record.realised_gains += gain
            else:
                record.realised_losses -= gain
                record.harvested -= gain
                account.loss_sales[lot.asset_id] = day
        for asset_id, weight in result.buys.items():
            if weight <= TRADE_EPSILON:
                continue
            price = float(market.prices[month, index[asset_id]])
            quantity = weight * nav / price
            lot_id = account.next_id(asset_id)
            remaining[lot_id] = LotState(lot_id, asset_id, quantity, price, day, day)
        account.lots = list(remaining.values())
        account.cash = result.cash_after * nav
        record.tracking_error = result.tracking_error_after
        record.turnover = result.turnover
        record.cost = result.cost * nav

    @staticmethod
    def _defer_loss(lots: dict[str, LotState], sold: LotState, loss: float, day: date) -> None:
        """A disallowed loss joins the basis of the newest other lot of the same stock bought within the window."""
        window = day - timedelta(days=WASH_SALE_DAYS)
        candidates = [
            lot
            for lot in lots.values()
            if lot.asset_id == sold.asset_id and lot.lot_id != sold.lot_id and lot.opened >= window
        ]
        if not candidates:
            return
        newest = max(candidates, key=lambda lot: (lot.opened, lot.lot_id))
        lots[newest.lot_id] = replace(newest, basis_per_unit=newest.basis_per_unit + loss / newest.quantity)

    def _liquidation_tax(self, account: _Account, market: Market) -> float:
        """The tax on selling everything at the last month's prices, with the year's netting and carryforward."""
        month = len(market.days) - 1
        day = market.days[month]
        index = {key: position for position, key in enumerate(market.keys)}
        ledger = TaxAccount(self.rates)
        ledger.carried = account.ledger.carried
        if day.month != 12:  # the year is still open: this year's realisations net with the liquidation
            ledger.years = (
                {day.year: replace(account.ledger.years[day.year])} if day.year in account.ledger.years else {}
            )
        for lot in account.lots:
            gain = lot.quantity * (market.prices[month, index[lot.asset_id]] - lot.basis_per_unit)
            ledger.realise(day, float(gain), lot.is_long_term(day))
        return self._close_year(ledger, day.year)

    def _close_year(self, ledger: TaxAccount, year: int) -> float:
        """The year's tax attributable to the account: with the client's outside gains, less their tax alone.

        The client realises short-term gains elsewhere every year; the account's
        net losses offset them. What the account is charged (or credited) is
        the difference its realisations make to the client's bill.
        """
        outside = self.config.outside_gains * self.config.nav
        if outside > 0:
            ledger.realise(date(year, 12, 31), outside, False)
        return ledger.close_year(year) - outside * short_rate(self.rates)

    # ------------------------------------------------------------------ many paths
    def run_paths(self, paths: int, progress: Callable[[str], None] | None = None) -> BacktestSummary:
        outcomes = [self.run(seed=self.config.seed + number) for number in range(paths)]
        if progress is not None:
            progress(f"{paths} paths")
        return BacktestSummary(self.config, outcomes)


def annualised(value: float, start: float, months: int) -> float:
    return float((value / start) ** (12 / months) - 1)


@dataclass
class PathOutcome:
    seed: int
    days: list[date]
    index_returns: np.ndarray
    strategies: dict[str, StrategyPath]
    dispersion: np.ndarray  # months: cross-sectional standard deviation of the stocks' returns

    def __getitem__(self, strategy: str) -> StrategyPath:
        return self.strategies[strategy]

    def active_returns(self, strategy: str) -> np.ndarray:
        return np.array(self.strategies[strategy].returns) - self.index_returns


@dataclass
class BacktestSummary:
    config: SimulationConfig
    paths: list[PathOutcome]

    @property
    def strategies(self) -> list[str]:
        return list(self.paths[0].strategies)

    def after_tax_return(self, strategy: str, *, liquidate: bool = True) -> np.ndarray:
        """Annual after-tax return, one per path: on liquidation (every gain taxed at the end), or as held."""
        return np.array(
            [
                annualised(
                    path[strategy].liquidation_value if liquidate else path[strategy].final_nav,
                    self.config.nav,
                    self.config.months,
                )
                for path in self.paths
            ]
        )

    def pre_tax_return(self, strategy: str) -> np.ndarray:
        """Annual return before any tax, trading costs included: what the portfolio itself earned.

        Time-weighted: tax paid leaves the account as a withdrawal does. Adding the
        tax back to the final value instead would leave out what that tax would
        have earned had it stayed invested.
        """
        return np.array([annualised(path[strategy].pre_tax_growth, 1.0, self.config.months) for path in self.paths])

    def tax_drag(self, strategy: str) -> np.ndarray:
        """Pre-tax return less after-tax return on liquidation: what tax costs a year, one per path."""
        return self.pre_tax_return(strategy) - self.after_tax_return(strategy)

    def tax_saved(self, strategy: str, against: str = "tax-blind") -> np.ndarray:
        """Tax alpha as after-tax active return less pre-tax active return: the drag avoided, luck in tracking apart."""
        return self.tax_drag(against) - self.tax_drag(strategy)

    def tax_alpha(self, strategy: str, against: str = "tax-blind", *, liquidate: bool = True) -> np.ndarray:
        return self.after_tax_return(strategy, liquidate=liquidate) - self.after_tax_return(
            against, liquidate=liquidate
        )

    def realised_tracking_error(self, strategy: str) -> float:
        """Annualised standard deviation of the monthly return against the index, pooled over the paths."""
        active = np.concatenate([path.active_returns(strategy) for path in self.paths])
        return float(np.std(active, ddof=1) * math.sqrt(12)) if active.size > 1 else 0.0

    def harvested(self, strategy: str) -> np.ndarray:
        """Losses harvested over the whole backtest, as a fraction of the starting value, one per path."""
        return np.array([path[strategy].harvested / self.config.nav for path in self.paths])

    def cumulative_tax(self, strategy: str) -> np.ndarray:
        """Tax paid by each month end, fraction of the starting value, averaged over the paths."""
        paid = np.array([[record.tax_paid for record in path[strategy].records] for path in self.paths])
        return np.cumsum(paid, axis=1).mean(axis=0) / self.config.nav

    def table(self) -> list[dict[str, float | str]]:
        rows: list[dict[str, float | str]] = []
        for strategy in self.strategies:
            rows.append(
                {
                    "strategy": strategy,
                    "pre_tax": float(np.mean(self.pre_tax_return(strategy))),
                    "after_tax": float(np.mean(self.after_tax_return(strategy))),
                    "tax_alpha": float(np.mean(self.tax_alpha(strategy))),
                    "tax_alpha_held": float(np.mean(self.tax_alpha(strategy, liquidate=False))),
                    "tax_saved": float(np.mean(self.tax_saved(strategy))),
                    "tracking_error": self.realised_tracking_error(strategy),
                    "harvested": float(np.mean(self.harvested(strategy))),
                    "turnover": float(
                        np.mean([sum(r.turnover for r in path[strategy].records) for path in self.paths])
                        / (self.config.months / 12)
                    ),
                }
            )
        return rows
