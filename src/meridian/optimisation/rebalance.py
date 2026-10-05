"""The rebalance: trade towards a target at the least tax and cost for the risk it removes.

The decision variables are, for every asset, the weight **bought**, and for
every tax lot, the weight **sold** from it - so the optimiser chooses not only
how much of a stock to sell but which lots to sell it from, the specific
identification a US taxpayer may elect. After the trades the weights are

    w = w0 + buy - (lots sold, summed by asset)

and the problem is, with everything in fractions of NAV and tracking error
annualised,

    minimise   risk_aversion * TE(w)^2  +  tax(sells)  +  cost(buys, sells)  +  penalty * soft-rule slack
    subject to the mandate's compilable rules, cash within its band, no short
               sales, no buying what the wash-sale rule forbids,
               and optionally TE(w) <= limit or tax <= budget.

**Tracking error** comes from the Day 5 factor model in its factor form,
``TE^2 = 252 (|| F^1/2 X' y ||^2 + || D^1/2 y ||^2)`` with y the active
position in the model's coverage assets - a second-order cone, never a dense
covariance matrix. **Tax** is linear in the lots sold (negative for losses, when
harvesting). **Cost** is linear commission and half-spread plus the x^1.5
market impact, written as the epigraph of a three-dimensional power cone and
paid out of cash.

**Lot relief.** By default the optimiser picks the lots (specific
identification). A manager whose broker relieves lots by a fixed rule - first
in first out, last in first out, highest cost first - decides only how much of
each asset to sell, and the rule picks the lots afterwards; "sell a lot only
once every older lot is gone" is not a convex constraint, so the rule is applied
to the solution rather than inside the problem. :meth:`Rebalancer.relieve`
applies any rule to any set of trades, which is how the value of choosing lots
is measured: the same trades, relieved four ways.

Two rules are not convex and are met in rounds, each round recorded:

* **wash sales** by repair: solve, find any asset whose loss lots are sold
  while the asset is also bought, forbid buying it, and solve again;
* **a floor on active share** by the convex-concave procedure. Active share,
  half the sum of absolute active weights, is convex, so a *lower* bound on it
  is not. Fixing the sign s of each active weight gives a linear function that
  never exceeds it, ``AS >= 1/2 sum s_i a_i``, and requiring the linear
  function to clear the floor is a convex restriction that guarantees the
  floor. The signs start from the current portfolio, which clears the floor,
  and are updated from each solution until they settle - each round feasible,
  and each no worse than the last.

Limits are applied inside a small **buffer** (5 bp by default), as a trading
desk does, so the portfolio the optimiser proposes passes the compliance engine
that measures it independently rather than landing on the limit to the last
decimal.

The problem is convex, solved by Clarabel (an interior-point conic solver) in
a fraction of a second for a few dozen assets and lots.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import cvxpy as cp
import numpy as np

from ..accounting.tax import DEFAULT_RATES, TaxRates
from ..compliance.language import Mandate
from ..compliance.snapshot import Holding
from ..core.exceptions import ValidationError
from .assets import CostModel, LotState, TradableAsset
from .constraints import active_share_rule, compile_mandate, excluded_assets, lookthrough_matrix
from .taxes import has_replacement, lot_tax_rate, recently_bought

ANNUAL = 252
SOFT_PENALTY = 10.0  # per unit of a soft rule's excess, and never less than the price of risk (see _build)
MAX_ROUNDS = 12
TRADE_EPSILON = 1e-7
WHOLE_LOT = 1e-6  # a sale this close to a lot's size relieves the whole lot
OBJECTIVE_SCALE = 1e4  # the objective in basis points of NAV: better conditioned for the interior-point solver
RIDGE = 1e-6  # on squared trades: 1% of NAV traded costs 1e-10, far below a hundredth of a basis point
RELIEF_METHODS: tuple[str, ...] = ("specific", "fifo", "lifo", "hifo")


@dataclass(frozen=True)
class RiskView:
    """The risk model in the coverage assets the portfolio maps onto."""

    keys: tuple[str, ...]
    exposures: np.ndarray  # C x K
    factor_covariance: np.ndarray  # K x K, daily
    specific: np.ndarray  # C, daily variance
    benchmark: np.ndarray  # C, target weights in coverage assets
    benchmark_cash: float = 0.0  # the target's cash, which active share counts
    #: coverage assets that are holdings for active share (a fund's basis is not a holding); None: all
    holding_mask: np.ndarray | None = None

    @property
    def mask(self) -> np.ndarray:
        return np.ones(len(self.keys), dtype=bool) if self.holding_mask is None else self.holding_mask

    def cholesky(self) -> np.ndarray:
        size = self.factor_covariance.shape[0]
        return np.linalg.cholesky(self.factor_covariance + 1e-14 * np.eye(size))

    def tracking_error(self, coverage_weights: np.ndarray) -> float:
        active = coverage_weights - self.benchmark
        exposure = self.exposures.T @ active
        variance = float(exposure @ self.factor_covariance @ exposure + active @ (self.specific * active))
        return math.sqrt(max(variance, 0.0) * ANNUAL)

    def volatility(self, coverage_weights: np.ndarray) -> float:
        exposure = self.exposures.T @ coverage_weights
        variance = float(
            exposure @ self.factor_covariance @ exposure + coverage_weights @ (self.specific * coverage_weights)
        )
        return math.sqrt(max(variance, 0.0) * ANNUAL)

    def active_share(self, coverage_weights: np.ndarray, cash: float) -> float:
        active = (coverage_weights - self.benchmark)[self.mask]
        return 0.5 * (float(np.abs(active).sum()) + abs(cash - self.benchmark_cash))


@dataclass(frozen=True)
class Settings:
    risk_aversion: float = 1.0  # weight on annual TE squared, against tax and cost in fractions of NAV
    tax_weight: float = 1.0  # 0 ignores tax (the tax-blind manager)
    harvest: bool = True  # value realised losses as tax saved
    loss_value: float = 1.0  # discount on a harvested loss
    loss_rate: float | None = None  # the rate a harvested loss saves; None: the lot's own term rate
    cost_weight: float = 1.0
    te_limit: float | None = None  # annual; a budget, met with a penalised slack when trading rules make it unreachable
    tax_budget: float | None = None  # fraction of NAV, as a constraint
    cash_band: tuple[float, float] = (0.01, 0.10)
    forbidden_buys: frozenset[str] = frozenset()
    lot_relief: str = "specific"  # or fifo | lifo | hifo: a fixed rule picks the lots after the solve
    include_soft_rules: bool = True
    allow_buys: bool = True
    limit_buffer: float = 0.0005  # mandate limits are met this far inside
    ccp_rounds: int = 4  # convex-concave rounds for an active-share floor

    def __post_init__(self) -> None:
        if self.lot_relief not in RELIEF_METHODS:
            raise ValidationError(
                f"unknown lot relief {self.lot_relief!r}; expected one of {', '.join(RELIEF_METHODS)}"
            )
        low, high = self.cash_band
        if not 0 <= low <= high:
            raise ValidationError("the cash band must satisfy 0 <= lower <= upper")
        if self.risk_aversion < 0 or self.tax_weight < 0 or self.cost_weight < 0 or self.limit_buffer < 0:
            raise ValidationError("weights and the buffer must not be negative")


@dataclass(frozen=True)
class LotSale:
    lot: LotState
    weight: float  # fraction of NAV sold
    units: float
    gain: float  # base currency
    tax: float  # base currency, at the lot's own rate (negative for a loss; zero for a loss the wash-sale rule defers)
    long_term: bool
    wash_sale: bool = False  # a loss disallowed because the asset was bought within 30 days


@dataclass(frozen=True)
class SolveRound:
    """One solve of the rebalance: what it proposed, and what the next round had to fix."""

    number: int
    tracking_error: float
    active_share: float
    tax: float
    objective: float
    forbidden: int  # assets barred from purchase by the wash-sale rule going into this round
    restricted: bool  # the active-share floor linearised


@dataclass
class RebalanceResult:
    as_of: date
    nav: float
    status: str
    before: dict[str, float]
    after: dict[str, float]
    cash_before: float
    cash_after: float
    buys: dict[str, float]
    sales: list[LotSale]
    tracking_error_before: float
    tracking_error_after: float
    volatility_after: float
    active_share_before: float
    active_share_after: float
    cost: float  # fraction of NAV
    objective: float
    repairs: list[str] = field(default_factory=list)
    compiled_rules: list[str] = field(default_factory=list)
    skipped_rules: list[str] = field(default_factory=list)
    soft_violation: float = 0.0
    rounds: int = 1
    solver: str = "CLARABEL"
    history: list[SolveRound] = field(default_factory=list)
    start: str = "current portfolio"  # where the active-share rounds started from

    @property
    def tax(self) -> float:
        """Tax on the realisations at each lot's own rate, base currency (before netting)."""
        return sum(sale.tax for sale in self.sales)

    @property
    def realised_gains(self) -> float:
        return sum(sale.gain for sale in self.sales if sale.gain > 0)

    @property
    def realised_losses(self) -> float:
        return -sum(sale.gain for sale in self.sales if sale.gain < 0)

    @property
    def sells(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for sale in self.sales:
            totals[sale.lot.asset_id] = totals.get(sale.lot.asset_id, 0.0) + sale.weight
        return totals

    @property
    def turnover(self) -> float:
        """Purchases plus sales, as a fraction of NAV (two-way)."""
        return sum(self.buys.values()) + sum(self.sells.values())


#: tried in order until one solves: Clarabel, Clarabel given longer, then SCS (first-order, slower, robust)
SOLVER_CHAIN: tuple[tuple[str, dict[str, float]], ...] = (
    ("CLARABEL", {}),
    ("CLARABEL", {"max_iter": 500, "static_regularization_constant": 1e-7}),
    ("SCS", {"eps_abs": 1e-9, "eps_rel": 1e-9, "max_iters": 100_000}),
)


def _solve_with_fallback(problem: cp.Problem) -> str:
    """Solve with the first solver in the chain that reaches an optimum; the name of the one that did."""
    last = "not attempted"
    for name, options in SOLVER_CHAIN:
        try:
            problem.solve(solver=name, **options)
        except cp.error.SolverError:
            last = f"{name} failed"
            continue
        if problem.status in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
            return name
        last = f"{name}: {problem.status}"
        if problem.status in (cp.INFEASIBLE, cp.UNBOUNDED):
            break
    raise ValidationError(f"the rebalance could not be solved ({last})")


@dataclass
class _Problem:
    """One convex problem, with the handles needed to read its solution."""

    problem: cp.Problem
    buy_free: cp.Variable
    sold_free: cp.Variable
    buy_map: np.ndarray
    sold_map: np.ndarray
    forced: np.ndarray
    compiled_rules: list[str]
    skipped_rules: list[str]
    soft: cp.Expression | None


class Rebalancer:
    def __init__(
        self,
        as_of: date,
        nav: float,
        assets: Sequence[TradableAsset],
        cash: float,
        risk: RiskView,
        *,
        costs: CostModel | None = None,
        rates: TaxRates = DEFAULT_RATES,
        mandate: Mandate | None = None,
        look_through: Mapping[str, Sequence[Holding]] | None = None,
    ) -> None:
        if nav <= 0:
            raise ValidationError("net asset value must be positive")
        self.as_of = as_of
        self.nav = nav
        self.assets = tuple(assets)
        self.cash = cash
        self.risk = risk
        self.costs = costs or CostModel()
        self.rates = rates
        self.mandate = mandate
        self.look_through = look_through or {}
        self.lots = [lot for asset in self.assets for lot in asset.lots]
        self.asset_index = {asset.asset_id: index for index, asset in enumerate(self.assets)}
        if len(self.asset_index) != len(self.assets):
            raise ValidationError("each asset may appear once")
        self.lot_asset = np.array([self.asset_index[lot.asset_id] for lot in self.lots], dtype=int)
        self.w0 = np.array([asset.value / nav for asset in self.assets])
        self.lot_weights = np.array(
            [lot.quantity * self.assets[self.asset_index[lot.asset_id]].unit_value / nav for lot in self.lots]
        )
        self.selling = np.zeros((len(self.assets), len(self.lots)))
        self.selling[self.lot_asset, np.arange(len(self.lots))] = 1.0
        self.mapping = lookthrough_matrix(self.assets, risk.keys)
        self.recent = recently_bought(self.assets, as_of)
        #: asset index -> the exclusion rule that keeps it out: never bought, and sold in full if held
        self.excluded = excluded_assets(mandate, self.assets, self.look_through) if mandate is not None else {}

    # ------------------------------------------------------------------ measures
    def lot_rates(self, settings: Settings) -> np.ndarray:
        """Tax per unit of NAV sold from each lot, as the optimiser values it."""
        return np.array(
            [
                lot_tax_rate(
                    lot,
                    self.assets[self.asset_index[lot.asset_id]].price,
                    self.as_of,
                    rates=self.rates,
                    harvest=settings.harvest,
                    wash_blocked=has_replacement(lot, self.recent),
                    loss_value=settings.loss_value,
                    loss_rate=settings.loss_rate,
                    unit_value=self.assets[self.asset_index[lot.asset_id]].unit_value,
                )
                for lot in self.lots
            ]
        )

    def evaluate(self, weights: np.ndarray) -> float:
        return self.risk.tracking_error(self.mapping.T @ weights)

    def active_share(self, weights: np.ndarray, cash: float) -> float:
        return self.risk.active_share(self.mapping.T @ weights, cash)

    def _signs(self, weights: np.ndarray, cash: float) -> tuple[np.ndarray, float]:
        active = self.mapping.T @ weights - self.risk.benchmark
        signs = np.where(active >= 0, 1.0, -1.0)
        return signs, 1.0 if cash - self.risk.benchmark_cash >= 0 else -1.0

    # ------------------------------------------------------------------ lot relief
    def _relief_order(self, position: int, method: str, rates: np.ndarray | None = None) -> tuple[float, str]:
        lot = self.lots[position]
        if method == "specific":
            assert rates is not None
            return (float(rates[position]), lot.lot_id)  # the least tax per unit sold first
        if method == "fifo":
            return (float(lot.opened.toordinal()), lot.lot_id)
        if method == "lifo":
            return (-float(lot.opened.toordinal()), lot.lot_id)
        return (-lot.basis_per_unit, lot.lot_id)  # hifo: highest basis first, the smallest gain

    def relieve(self, sold: np.ndarray, method: str, rates: np.ndarray | None = None) -> np.ndarray:
        """Reassign each asset's total sale to its lots by a rule.

        ``specific`` with ``rates`` sells the least tax per unit first - what
        the optimiser chooses whenever tax counts, and the cheapest lots even
        when it does not (the lots of one asset differ only in their tax, so a
        tax-blind solve is indifferent between them); without rates it keeps
        the allocation given.
        """
        if method not in RELIEF_METHODS:
            raise ValidationError(f"unknown lot relief {method!r}")
        if method == "specific" and rates is None:
            return sold.copy()
        output = np.zeros_like(sold)
        by_asset: dict[int, list[int]] = {}
        for position, lot in enumerate(self.lots):
            by_asset.setdefault(self.asset_index[lot.asset_id], []).append(position)
        for positions in by_asset.values():
            remaining = float(sold[positions].sum())
            for position in sorted(positions, key=lambda item: self._relief_order(item, method, rates)):
                take = min(remaining, float(self.lot_weights[position]))
                output[position] = take
                remaining -= take
        return output

    def sales(self, sold: np.ndarray) -> list[LotSale]:
        """The lot sales a vector of weights sold per lot amounts to, each taxed at its own rate."""
        output = []
        for position in np.flatnonzero(sold > TRADE_EPSILON):
            lot = self.lots[position]
            asset = self.assets[self.asset_index[lot.asset_id]]
            units = float(sold[position]) * self.nav / asset.unit_value
            gain = units * (asset.price - lot.basis_per_unit)
            wash = gain < 0 and has_replacement(lot, self.recent)
            rate = lot_tax_rate(lot, asset.price, self.as_of, rates=self.rates, harvest=True, wash_blocked=wash)
            tax = rate * units * asset.price
            output.append(LotSale(lot, float(sold[position]), units, gain, tax, lot.is_long_term(self.as_of), wash))
        return output

    def sold_vector(self, sales: Sequence[LotSale]) -> np.ndarray:
        index = {lot.lot_id: position for position, lot in enumerate(self.lots)}
        output = np.zeros(len(self.lots))
        for sale in sales:
            output[index[sale.lot.lot_id]] += sale.weight
        return output

    def relief_comparison(self, result: RebalanceResult) -> dict[str, list[LotSale]]:
        """The same trades relieved every way: what choosing the lots is worth."""
        sold = self.sold_vector(result.sales)
        return {method: self.sales(self.relieve(sold, method)) for method in RELIEF_METHODS}

    # ------------------------------------------------------------------ solve
    def solve(self, settings: Settings | None = None) -> RebalanceResult:
        """Solve, repairing wash sales and restricting active share in rounds until neither needs more.

        When an active-share floor binds, the convex-concave procedure is
        started twice - from the signs of the current portfolio's active
        weights and from those of the unrestricted solution - and the better
        of the two settled solutions is kept: each start finds a local
        optimum of a problem that is not convex, and two starts rarely agree
        on a worse one.
        """
        settings = settings or Settings()
        first = self._settle(settings, "portfolio")
        if not any(item.restricted for item in first.history):
            return first
        try:
            second = self._settle(settings, "solution")
        except ValidationError:
            return first
        best, other = (first, second) if first.objective <= second.objective else (second, first)
        best.repairs.append(
            f"active share: convex-concave rounds started from the {best.start} and from the {other.start}; "
            f"the {best.start} start settled lower"
        )
        return best

    def _settle(self, settings: Settings, start: str) -> RebalanceResult:
        repairs: list[str] = []
        forbidden = set(settings.forbidden_buys)
        rates = self.lot_rates(settings)
        loss_lots = rates < -1e-12
        rule = active_share_rule(self.mandate, settings.include_soft_rules) if self.mandate is not None else None
        signs: tuple[np.ndarray, float] | None = None
        ccp = 0
        history: list[SolveRound] = []
        for round_number in range(1, MAX_ROUNDS + 1):
            result, bought, sold = self._solve_once(settings, forbidden, rates, signs)
            result.rounds = round_number
            history.append(
                SolveRound(
                    round_number,
                    result.tracking_error_after,
                    result.active_share_after,
                    result.tax,
                    result.objective,
                    len(forbidden),
                    signs is not None,
                )
            )
            result.history = history
            result.start = "current portfolio" if start == "portfolio" else "unrestricted solution"
            conflicts = sorted(
                {
                    self.lots[position].asset_id
                    for position in np.flatnonzero((sold > TRADE_EPSILON) & loss_lots)
                    if bought[self.asset_index[self.lots[position].asset_id]] > TRADE_EPSILON
                }
            )
            if conflicts:
                for asset_id in conflicts:
                    repairs.append(f"{asset_id}: loss lots sold and the asset bought - buying forbidden (wash sale)")
                    forbidden.add(asset_id)
                continue
            if rule is not None:
                floor = rule[1] + settings.limit_buffer
                after = np.array([result.after[asset.asset_id] for asset in self.assets])
                if signs is None and result.active_share_after < floor - 1e-9:
                    signs = (
                        self._signs(self.w0, self.cash)
                        if start == "portfolio"
                        else self._signs(after, result.cash_after)
                    )
                    repairs.append(
                        f"{rule[0]}: active share {result.active_share_after:.1%} below its floor - "
                        "restricted by the convex-concave procedure"
                    )
                    continue
                if signs is not None and ccp < settings.ccp_rounds:
                    updated = self._signs(after, result.cash_after)
                    if not (np.array_equal(updated[0], signs[0]) and updated[1] == signs[1]):
                        signs, ccp = updated, ccp + 1
                        continue
            result.repairs = repairs
            return result
        raise ValidationError(f"the rebalance did not settle in {MAX_ROUNDS} rounds")

    def _build(
        self,
        settings: Settings,
        forbidden: set[str],
        rates: np.ndarray,
        signs: tuple[np.ndarray, float] | None,
    ) -> _Problem:
        n, m = len(self.assets), len(self.lots)
        # An asset that may not be bought, or a lot that must be sold whole, is taken out of the problem
        # rather than pinned by an equality: "buy == 0" on a non-negative variable leaves the feasible set
        # without an interior, and an interior-point solver then stalls short of the optimum.
        closed = {self.asset_index[asset] for asset in forbidden if asset in self.asset_index} | set(self.excluded)
        buyable = [] if not settings.allow_buys else [i for i in range(n) if i not in closed]
        forced = np.array([self.lot_asset[j] in self.excluded for j in range(m)], dtype=bool)
        free = np.flatnonzero(~forced)
        # when nothing may be bought, or no lot is free to sell, a one-element placeholder stands in: its
        # column in the map is zero, so it moves nothing, and the ridge holds it at zero
        buy_free = cp.Variable(max(len(buyable), 1), nonneg=True, name="buy")
        sold_free = cp.Variable(max(len(free), 1), nonneg=True, name="sold")
        buy_map = np.zeros((n, buy_free.size))
        buy_map[buyable, np.arange(len(buyable))] = 1.0
        sold_map = np.zeros((m, sold_free.size))
        sold_map[free, np.arange(len(free))] = 1.0
        free_caps = self.lot_weights[free] if len(free) else np.ones(1)
        buy = buy_map @ buy_free
        sold = sold_map @ sold_free + np.where(forced, self.lot_weights, 0.0)
        traded_sell = self.selling @ sold
        weights = self.w0 + buy - traded_sell

        linear = np.array([self.costs.linear(asset) for asset in self.assets])
        impact = np.array([self.costs.impact(asset, self.nav) for asset in self.assets])
        # Impact x^1.5 through its epigraph in the 3-D power cone, t^(2/3) * 1^(1/3) >= x, which Clarabel
        # handles natively. cvxpy's default rewrites x^1.5 as a tower of second-order cones, and on these
        # tiny trade sizes that tower stalled the solver short of its tolerances.
        impacted = np.flatnonzero(impact > 0)
        constraints: list[cp.Constraint] = []
        cost = linear @ (buy + traded_sell)
        if impacted.size:
            impact_buy = cp.Variable(impacted.size, nonneg=True, name="impact_buy")
            impact_sell = cp.Variable(impacted.size, nonneg=True, name="impact_sell")
            ones = np.ones(impacted.size)
            constraints += [
                cp.constraints.PowCone3D(impact_buy, ones, buy[impacted], 2 / 3),
                cp.constraints.PowCone3D(impact_sell, ones, traded_sell[impacted], 2 / 3),
            ]
            cost = cost + impact[impacted] @ (impact_buy + impact_sell)
        # cash before costs is affine; after costs it is concave (cost is convex), so the floor
        # applies after costs and every ceiling - the band's and the mandate's - before them
        cash_gross = self.cash - cp.sum(buy) + cp.sum(sold)
        cash = cash_gross - cost

        chol = self.risk.cholesky()
        coverage = self.mapping.T @ weights
        active = coverage - self.risk.benchmark
        specific_root = np.sqrt(self.risk.specific)
        factor_part = chol.T @ (self.risk.exposures.T @ active)
        specific_part = cp.multiply(specific_root, active)
        te_squared = ANNUAL * (cp.sum_squares(factor_part) + cp.sum_squares(specific_part))
        tracking_error = math.sqrt(ANNUAL) * cp.norm(cp.hstack([factor_part, specific_part]), 2)
        volatility = math.sqrt(ANNUAL) * cp.norm(
            cp.hstack([chol.T @ (self.risk.exposures.T @ coverage), cp.multiply(specific_root, coverage)]), 2
        )
        mask = self.risk.mask
        cash_active = cash_gross - self.risk.benchmark_cash
        share_exact = 0.5 * (cp.norm1(active[mask]) + cp.abs(cash_active))
        share_minorant = None
        if signs is not None:
            share_minorant = 0.5 * (signs[0][mask] @ active[mask] + signs[1] * cash_active)
        tax = rates @ sold

        cash_excess = cp.Variable(nonneg=True, name="cash_excess")
        constraints += [
            # no short sales: selling at most each lot is enough, since the lots make up the position;
            # stating "weights >= 0" as well would repeat a constraint and make the problem degenerate
            sold_free <= free_caps,
            cash >= settings.cash_band[0],
            # the ceiling is soft: cash above it with nothing left to buy (every name barred by the wash-sale
            # rule, say) must not make the month infeasible; the floor can always be met by selling
            cash_gross <= settings.cash_band[1] + cash_excess,
        ]
        budget_slack = None
        if settings.te_limit is not None:
            # soft: when the wash-sale rule and the cash band leave no portfolio within the budget, the
            # optimiser gets as close as it can instead of declaring the month infeasible
            budget_slack = cp.Variable(nonneg=True, name="te_budget_slack")
            constraints.append(tracking_error <= settings.te_limit + budget_slack)
        if settings.tax_budget is not None:
            constraints.append(tax <= settings.tax_budget)
        compiled_rules: list[str] = []
        skipped: list[str] = []
        soft = None
        if self.mandate is not None:
            compiled = compile_mandate(
                self.mandate,
                self.assets,
                weights,
                cash_gross,
                self.look_through,
                tracking_error=tracking_error,
                volatility=volatility,
                active_share=share_exact,
                active_share_minorant=share_minorant,
                include_soft=settings.include_soft_rules,
                buffer=settings.limit_buffer,
            )
            constraints += compiled.constraints
            compiled_rules, skipped, soft = compiled.compiled, compiled.skipped, compiled.soft_slack

        if budget_slack is not None:
            soft = budget_slack if soft is None else soft + budget_slack
        soft = cash_excess if soft is None else soft + cash_excess
        objective = settings.risk_aversion * te_squared + settings.tax_weight * tax + settings.cost_weight * cost
        # a ridge far below any cost: when tax is ignored the lots of one asset are interchangeable and the
        # optimum is a face, not a point; the ridge picks one and lets the interior-point method converge
        objective = objective + RIDGE * (cp.sum_squares(buy_free) + cp.sum_squares(sold_free))
        if soft is not None:
            # a soft limit is priced above anything the risk term could gain by breaking it, whatever the
            # risk aversion: at a high one a fixed penalty would be cheap and the limit ignored
            objective = objective + SOFT_PENALTY * max(1.0, settings.risk_aversion) * soft
        problem = cp.Problem(cp.Minimize(OBJECTIVE_SCALE * objective), constraints)
        return _Problem(problem, buy_free, sold_free, buy_map, sold_map, forced, compiled_rules, skipped, soft)

    def _solve_once(
        self,
        settings: Settings,
        forbidden: set[str],
        rates: np.ndarray,
        signs: tuple[np.ndarray, float] | None = None,
    ) -> tuple[RebalanceResult, np.ndarray, np.ndarray]:
        built = self._build(settings, forbidden, rates, signs)
        problem = built.problem
        solver = _solve_with_fallback(problem)

        bought = np.clip(built.buy_map @ np.asarray(built.buy_free.value).reshape(-1), 0.0, None)
        sold_value = np.clip(
            built.sold_map @ np.asarray(built.sold_free.value).reshape(-1)
            + np.where(built.forced, self.lot_weights, 0.0),
            0.0,
            self.lot_weights,
        )
        sold_value[sold_value < TRADE_EPSILON] = 0.0
        # a lot sold to within a millionth of its size is sold whole: the remnant is solver noise, and a
        # dust lot left behind would carry an absurd basis per unit into every later problem
        whole = sold_value > self.lot_weights * (1 - WHOLE_LOT)
        sold_value[whole] = self.lot_weights[whole]
        sold_value = self.relieve(sold_value, settings.lot_relief, rates)
        bought[bought < TRADE_EPSILON] = 0.0
        sold_by_asset = self.selling @ sold_value
        after = self.w0 + bought - sold_by_asset
        cost_value = float(
            sum(
                self.costs.cost(asset, self.nav, bought[i]) + self.costs.cost(asset, self.nav, sold_by_asset[i])
                for i, asset in enumerate(self.assets)
            )
        )
        cash_after = self.cash - float(bought.sum()) + float(sold_value.sum()) - cost_value
        result = RebalanceResult(
            as_of=self.as_of,
            nav=self.nav,
            status=str(problem.status),
            solver=solver,
            before={asset.asset_id: float(self.w0[i]) for i, asset in enumerate(self.assets)},
            after={asset.asset_id: float(after[i]) for i, asset in enumerate(self.assets)},
            cash_before=self.cash,
            cash_after=cash_after,
            buys={self.assets[i].asset_id: float(bought[i]) for i in np.flatnonzero(bought)},
            sales=self.sales(sold_value),
            tracking_error_before=self.evaluate(self.w0),
            tracking_error_after=self.evaluate(after),
            volatility_after=self.risk.volatility(self.mapping.T @ after),
            active_share_before=self.active_share(self.w0, self.cash),
            active_share_after=self.active_share(after, cash_after),
            cost=cost_value,
            objective=float(problem.value) / OBJECTIVE_SCALE,
            compiled_rules=built.compiled_rules,
            skipped_rules=built.skipped_rules,
            soft_violation=0.0 if built.soft is None else float(built.soft.value or 0.0),
        )
        return result, bought, sold_value
