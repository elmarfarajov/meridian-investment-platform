"""A synthetic market that behaves like a real one where it matters.

The platform cannot depend on a paid data feed, and tests cannot depend on the
network. A random walk would do for plumbing, but it would make every quality
rule look good: normal returns have no tails, constant volatility has no
clusters, and a robust outlier test has nothing to be robust against.

So the generator reproduces the stylised facts a quality rule has to survive:

* **Fat tails.** Innovations are Student-t (five degrees of freedom by default),
  rescaled to unit variance, so three-sigma days happen several times more often
  than a normal distribution allows.
* **Volatility clustering.** Idiosyncratic variance follows a GARCH(1,1)
  process: a large move raises the variance of the next few days.

The two interact, and the parameters are chosen so that they do not break each
other. GARCH(1,1) has a finite fourth moment only if
``beta**2 + 2*alpha*beta + kappa*alpha**2 < 1``, where ``kappa`` is the
innovations' kurtosis - infinite for Student-t with four degrees of freedom.
Without a finite fourth moment the variance of the realised variance is
infinite, and a two-year sample can come out 50% more volatile than specified.
The defaults (t with 5 degrees of freedom, ``alpha = 0.06``, ``beta = 0.92``)
satisfy the condition and keep the persistence at 0.98.
* **Correlation.** Returns load on a market factor and a sector factor, so a
  sell-off hits everything at once - which is what separates a genuine market
  move from a bad tick in one name.
* **Calendars.** Each instrument trades on its own exchange calendar. Returns on
  days the exchange is shut accumulate into the next open day, as they do.
* **Corporate actions.** Splits and dividends move the quoted price on the
  ex-date. The economic value - one original share with dividends reinvested -
  is kept alongside as ground truth, so the adjustment code can be tested
  against the answer rather than against itself.

Everything is driven by one seed: the same request always returns the same
market, to the last decimal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np

from ...core.calendars import get_calendar
from ...core.exceptions import ValidationError
from ...domain.corporate_actions import CashDividend, CorporateAction, StockSplit
from ..quotes import FxQuote, MarketDataset, Quote
from ..series import TimeSeries

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """How one synthetic instrument behaves."""

    instrument_id: str
    currency: str = "USD"
    calendar: str = "XNYS"
    initial_price: float = 100.0
    annual_vol: float = 0.25
    annual_drift: float = 0.06
    beta: float = 1.0
    sector: str = "General"
    spread_bps: float = 6.0
    tail_dof: float = 5.0
    average_volume: float = 1_500_000.0
    price_places: int = 2
    splits: tuple[tuple[date, int, int], ...] = ()
    dividends: tuple[tuple[date, float], ...] = ()

    def __post_init__(self) -> None:
        if self.initial_price <= 0:
            raise ValidationError(f"{self.instrument_id}: the initial price must be positive")
        if not 0 < self.annual_vol < 3:
            raise ValidationError(f"{self.instrument_id}: annual volatility {self.annual_vol} is implausible")
        if self.tail_dof <= 2:
            raise ValidationError(f"{self.instrument_id}: Student-t needs more than 2 degrees of freedom")


@dataclass(frozen=True, slots=True)
class FxSpec:
    """A currency pair quoted against the pivot: ``EURUSD``, or ``USDJPY``."""

    base: str
    quote: str
    initial_rate: float
    annual_vol: float = 0.08
    places: int = 6

    @property
    def pair(self) -> str:
        return f"{self.base}{self.quote}"


@dataclass
class SyntheticHistory:
    """What the generator produced, including the answers a test needs."""

    dataset: MarketDataset
    corporate_actions: tuple[CorporateAction, ...]
    economic_value: dict[str, TimeSeries]
    log_returns: dict[str, list[float]]
    market_factor: list[tuple[date, float]]
    specs: dict[str, InstrumentSpec] = field(default_factory=dict)

    def raw_series(self, instrument_id: str) -> TimeSeries:
        return self.dataset.close_series(instrument_id)


def _round(value: float, places: int) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)


def student_t_kurtosis(dof: float) -> float:
    """Kurtosis of a Student-t distribution: 3(v-2)/(v-4), infinite for four degrees of freedom or fewer."""
    return math.inf if dof <= 4 else 3.0 * (dof - 2.0) / (dof - 4.0)


def garch_fourth_moment_finite(alpha: float, beta: float, dof: float) -> bool:
    """Whether a GARCH(1,1) with Student-t innovations has a finite fourth moment."""
    kurtosis = student_t_kurtosis(dof)
    return math.isfinite(kurtosis) and beta**2 + 2 * alpha * beta + kurtosis * alpha**2 < 1


def weekdays(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


class SyntheticMarket:
    """A deterministic, stylised-facts market that also satisfies the provider contract."""

    def __init__(
        self,
        instruments: Sequence[InstrumentSpec],
        fx: Sequence[FxSpec] = (),
        *,
        seed: int = 7,
        source: str = "synthetic",
        market_vol: float = 0.16,
        sector_vol: float = 0.07,
        garch_alpha: float = 0.06,
        garch_beta: float = 0.92,
        pivot: str = "USD",
    ) -> None:
        if garch_alpha < 0 or garch_beta < 0 or garch_alpha + garch_beta >= 1:
            raise ValidationError("GARCH(1,1) needs alpha, beta >= 0 and alpha + beta < 1 to be stationary")
        identifiers = [spec.instrument_id for spec in instruments]
        if len(set(identifiers)) != len(identifiers):
            raise ValidationError("instrument specs must have unique identifiers")
        self.instruments = {spec.instrument_id: spec for spec in instruments}
        self.fx_specs = {spec.pair: spec for spec in fx}
        self.seed = seed
        self.source = source
        self.market_vol = market_vol
        self.sector_vol = sector_vol
        self.garch_alpha = garch_alpha
        self.garch_beta = garch_beta
        self.pivot = pivot.upper()
        self._cache: dict[tuple[date, date], SyntheticHistory] = {}

    # ------------------------------------------------------------------ provider protocol
    @property
    def name(self) -> str:
        return self.source

    def quotes(self, instrument_ids: Sequence[str], start: date, end: date) -> list[Quote]:
        unknown = sorted(set(instrument_ids) - set(self.instruments))
        if unknown:
            raise ValidationError(f"{self.source}: no specification for {', '.join(unknown)}")
        history = self.generate(start, end)
        wanted = set(instrument_ids)
        return [quote for key, items in history.dataset.quotes.items() if key in wanted for quote in items]

    def fx_quotes(self, pairs: Sequence[str], start: date, end: date) -> list[FxQuote]:
        history = self.generate(start, end)
        return [rate for pair in pairs for rate in history.dataset.fx.get(pair.upper(), [])]

    # ------------------------------------------------------------------ generation
    def generate(self, start: date, end: date) -> SyntheticHistory:
        if end <= start:
            raise ValidationError("a synthetic history needs end after start")
        key = (start, end)
        if key not in self._cache:
            self._cache[key] = self._generate(start, end)
        return self._cache[key]

    def _generate(self, start: date, end: date) -> SyntheticHistory:
        rng = np.random.default_rng(self.seed)
        grid = weekdays(start, end)
        steps = len(grid)
        dt = 1.0 / TRADING_DAYS_PER_YEAR

        market = self._market_factor(rng, steps)
        sectors = sorted({spec.sector for spec in self.instruments.values()})
        sector_moves = {sector: rng.standard_normal(steps) * self.sector_vol * math.sqrt(dt) for sector in sectors}

        quotes: list[Quote] = []
        actions: list[CorporateAction] = []
        economic: dict[str, TimeSeries] = {}
        log_returns: dict[str, list[float]] = {}

        for spec in sorted(self.instruments.values(), key=lambda item: item.instrument_id):
            daily = self._instrument_returns(rng, spec, market, sector_moves[spec.sector])
            generated = self._price_path(rng, spec, grid, daily)
            quotes.extend(generated[0])
            actions.extend(generated[1])
            economic[spec.instrument_id] = generated[2]
            log_returns[spec.instrument_id] = generated[3]

        fx = self._fx_paths(rng, grid)
        return SyntheticHistory(
            dataset=MarketDataset.from_records(quotes, fx),
            corporate_actions=tuple(sorted(actions, key=lambda item: (item.ex_date, item.action_id))),
            economic_value=economic,
            log_returns=log_returns,
            market_factor=list(zip(grid, market.tolist(), strict=True)),
            specs=dict(self.instruments),
        )

    def _student_t(self, rng: np.random.Generator, dof: float, size: int) -> np.ndarray:
        """Student-t draws rescaled to unit variance, so ``dof`` changes the tails and not the volatility."""
        return rng.standard_t(dof, size) * math.sqrt((dof - 2.0) / dof)

    def _market_factor(self, rng: np.random.Generator, steps: int) -> np.ndarray:
        """A market return path with its own volatility clustering."""
        long_run = self.market_vol**2 / TRADING_DAYS_PER_YEAR
        return self._garch_path(rng, steps, long_run, 5.0)

    def _garch_path(self, rng: np.random.Generator, steps: int, long_run: float, dof: float) -> np.ndarray:
        omega = long_run * (1 - self.garch_alpha - self.garch_beta)
        shocks = self._student_t(rng, dof, steps)
        variance = long_run
        path = np.empty(steps)
        for index in range(steps):
            innovation = math.sqrt(variance) * shocks[index]
            path[index] = innovation
            variance = omega + self.garch_alpha * innovation**2 + self.garch_beta * variance
        return path

    def _instrument_returns(
        self, rng: np.random.Generator, spec: InstrumentSpec, market: np.ndarray, sector: np.ndarray
    ) -> np.ndarray:
        """Daily log returns on the weekday grid: drift + beta * market + sector + GARCH-t residual."""
        dt = 1.0 / TRADING_DAYS_PER_YEAR
        systematic = spec.beta**2 * self.market_vol**2 + self.sector_vol**2
        residual_annual = max(spec.annual_vol**2 - systematic, (0.35 * spec.annual_vol) ** 2)
        residual = self._garch_path(rng, len(market), residual_annual * dt, spec.tail_dof)
        drift = (spec.annual_drift - 0.5 * spec.annual_vol**2) * dt
        return drift + spec.beta * market + sector + residual

    def _price_path(
        self, rng: np.random.Generator, spec: InstrumentSpec, grid: list[date], daily: np.ndarray
    ) -> tuple[list[Quote], list[CorporateAction], TimeSeries, list[float]]:
        calendar = get_calendar(spec.calendar)
        trading = [index for index, day in enumerate(grid) if calendar.is_business_day(day)]
        if len(trading) < 2:
            raise ValidationError(f"{spec.instrument_id}: fewer than two trading days in the requested window")

        splits = {calendar.adjust(day): (numerator, denominator) for day, numerator, denominator in spec.splits}
        dividends = {calendar.adjust(day): amount for day, amount in spec.dividends}

        quotes: list[Quote] = []
        actions: list[CorporateAction] = []
        economic_points: list[tuple[date, float]] = []
        returns: list[float] = []

        price = spec.initial_price
        wealth = spec.initial_price  # one original share, dividends reinvested, splits absorbed
        previous_index = trading[0]
        for position, index in enumerate(trading):
            day = grid[index]
            if position == 0:
                log_return = 0.0
            else:
                # returns on days the exchange was shut accumulate into the next open day
                log_return = float(daily[previous_index + 1 : index + 1].sum())
                returns.append(log_return)
            previous_index = index

            dividend = dividends.get(day)
            if dividend is not None and position > 0:
                if dividend >= price:
                    raise ValidationError(f"{spec.instrument_id}: a dividend of {dividend} exceeds the price")
                actions.append(
                    CashDividend(
                        action_id=f"{spec.instrument_id}-DIV-{day.isoformat()}",
                        instrument_id=spec.instrument_id,
                        ex_date=day,
                        record_date=day,
                        pay_date=calendar.add_business_days(day, 10),
                        amount=_round(dividend, spec.price_places),
                        currency=spec.currency,
                    )
                )
                price -= float(_round(dividend, spec.price_places))
            split_terms = splits.get(day)
            if split_terms is not None and position > 0:
                numerator, denominator = split_terms
                actions.append(
                    StockSplit(
                        action_id=f"{spec.instrument_id}-SPLIT-{day.isoformat()}",
                        instrument_id=spec.instrument_id,
                        ex_date=day,
                        numerator=numerator,
                        denominator=denominator,
                    )
                )
                price *= denominator / numerator

            price *= math.exp(log_return)
            wealth *= math.exp(log_return)
            economic_points.append((day, wealth))

            close = _round(price, spec.price_places)
            half_spread = spec.spread_bps / 20_000 * (1 + 0.35 * abs(float(rng.standard_normal())))
            bid = _round(price * (1 - half_spread), spec.price_places)
            ask = _round(price * (1 + half_spread), spec.price_places)
            if ask <= bid:
                ask = bid + Decimal(1).scaleb(-spec.price_places)
            volume = int(spec.average_volume * math.exp(0.35 * float(rng.standard_normal()) + 12 * abs(log_return)))
            quotes.append(
                Quote(
                    instrument_id=spec.instrument_id,
                    day=day,
                    close=close,
                    currency=spec.currency,
                    source=self.source,
                    bid=bid,
                    ask=ask,
                    volume=volume,
                )
            )

        economic = TimeSeries(
            ((day, _round(value, 8)) for day, value in economic_points), name=f"{spec.instrument_id} (economic)"
        )
        return quotes, actions, economic, returns

    def _fx_paths(self, rng: np.random.Generator, grid: list[date]) -> list[FxQuote]:
        """Pairs against the pivot follow independent GBMs; FX trades every weekday."""
        dt = 1.0 / TRADING_DAYS_PER_YEAR
        rates: list[FxQuote] = []
        for pair in sorted(self.fx_specs):
            spec = self.fx_specs[pair]
            if self.pivot not in {spec.base, spec.quote}:
                raise ValidationError(f"{pair}: synthetic FX is generated against {self.pivot}; request crosses")
            shocks = self._student_t(rng, 6.0, len(grid)) * spec.annual_vol * math.sqrt(dt)
            level = spec.initial_rate
            for day, shock in zip(grid, shocks, strict=True):
                level *= math.exp(float(shock) - 0.5 * spec.annual_vol**2 * dt)
                rates.append(
                    FxQuote(
                        base=spec.base, quote=spec.quote, day=day, rate=_round(level, spec.places), source=self.source
                    )
                )
        return rates


def cross_rates(
    rates: Sequence[FxQuote], base: str, quote: str, *, pivot: str = "USD", places: int = 6
) -> list[FxQuote]:
    """Derive a cross (``EURGBP``) from two pivot legs on every day both exist.

    Crosses are derived rather than simulated, so the triangle closes exactly -
    and a break in it is always a data error, never the generator's noise.
    """
    base, quote, pivot = base.upper(), quote.upper(), pivot.upper()
    legs: dict[str, dict[date, Decimal]] = {}
    for rate in rates:
        legs.setdefault(rate.pair, {})[rate.day] = rate.rate

    def to_pivot(currency: str, day: date) -> Decimal | None:
        """Pivot units per one unit of ``currency``."""
        if currency == pivot:
            return Decimal(1)
        direct = legs.get(f"{currency}{pivot}", {}).get(day)
        if direct is not None:
            return direct
        inverse = legs.get(f"{pivot}{currency}", {}).get(day)
        return Decimal(1) / inverse if inverse is not None else None

    days = sorted({rate.day for rate in rates})
    crossed: list[FxQuote] = []
    for day in days:
        base_leg, quote_leg = to_pivot(base, day), to_pivot(quote, day)
        if base_leg is None or quote_leg is None:
            continue
        value = (base_leg / quote_leg).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
        crossed.append(FxQuote(base=base, quote=quote, day=day, rate=value, source=rates[0].source if rates else ""))
    return crossed


def demo_market(seed: int = 7) -> SyntheticMarket:
    """The synthetic counterpart of the demonstration book, used by the CLI and the gallery.

    The instrument identifiers match the seeded book so that a synthetic history
    can be loaded straight into the database; the parameters are illustrative,
    chosen to look like each name's sector rather than to reproduce its history.
    """
    return SyntheticMarket(
        [
            InstrumentSpec(
                "US-AAPL",
                "USD",
                "XNYS",
                169.0,
                0.27,
                0.10,
                1.15,
                "Information Technology",
                dividends=(
                    (date(2024, 5, 10), 0.25),
                    (date(2024, 8, 12), 0.25),
                    (date(2024, 11, 8), 0.25),
                    (date(2025, 2, 10), 0.25),
                    (date(2025, 5, 12), 0.26),
                    (date(2025, 8, 11), 0.26),
                ),
            ),
            InstrumentSpec(
                "US-MSFT",
                "USD",
                "XNYS",
                420.0,
                0.24,
                0.09,
                1.05,
                "Information Technology",
                dividends=(
                    (date(2024, 5, 15), 0.75),
                    (date(2024, 8, 15), 0.75),
                    (date(2024, 11, 21), 0.83),
                    (date(2025, 2, 20), 0.83),
                ),
            ),
            InstrumentSpec(
                "US-JNJ",
                "USD",
                "XNYS",
                152.0,
                0.16,
                0.05,
                0.55,
                "Health Care",
                dividends=(
                    (date(2024, 5, 21), 1.24),
                    (date(2024, 8, 27), 1.24),
                    (date(2024, 11, 26), 1.24),
                    (date(2025, 2, 25), 1.24),
                ),
            ),
            InstrumentSpec(
                "GB-BAE",
                "GBP",
                "XLON",
                12.9,
                0.22,
                0.08,
                0.70,
                "Industrials",
                price_places=3,
                dividends=((date(2024, 10, 17), 0.123), (date(2025, 4, 17), 0.199)),
            ),
            InstrumentSpec(
                "DE-BAYN",
                "EUR",
                "TARGET",
                27.4,
                0.34,
                -0.02,
                0.95,
                "Health Care",
                dividends=((date(2025, 4, 28), 0.11),),
            ),
            InstrumentSpec(
                "CH-ROG",
                "CHF",
                "TARGET",
                268.0,
                0.19,
                0.04,
                0.65,
                "Health Care",
                dividends=((date(2025, 3, 14), 9.70),),
            ),
            InstrumentSpec(
                "US-IVV",
                "USD",
                "XNYS",
                520.0,
                0.16,
                0.08,
                1.0,
                "Index",
                spread_bps=1.0,
                tail_dof=6.0,
                average_volume=5_000_000,
            ),
            InstrumentSpec("IE-IWDA", "USD", "TARGET", 88.4, 0.15, 0.07, 0.95, "Index", spread_bps=2.0, tail_dof=6.0),
            InstrumentSpec(
                "DEMO-SPLIT",
                "USD",
                "XNYS",
                480.0,
                0.38,
                0.14,
                1.35,
                "Information Technology",
                splits=((date(2025, 6, 10), 4, 1),),
                dividends=((date(2024, 12, 12), 1.10), (date(2025, 9, 11), 0.30)),
            ),
        ],
        [
            FxSpec("EUR", "USD", 1.085, 0.07),
            FxSpec("GBP", "USD", 1.265, 0.08),
            FxSpec("USD", "CHF", 0.905, 0.07),
            FxSpec("USD", "JPY", 151.2, 0.10, places=4),
        ],
        seed=seed,
    )
