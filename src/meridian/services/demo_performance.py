"""Performance and attribution for the demonstration account, end to end.

The account is measured against its policy benchmark - 80% world equity, 15% the
US Treasury, 5% cash - where world equity is **Meridian World Equity**, a
synthetic capitalisation-weighted index of thirty-six stocks. Six are the
demonstration book's own single stocks, whose prices come from the Day 2 market;
thirty are companions generated in the same synthetic market, sharing its
market and sector factors (``SyntheticMarket.companion``), so the index and the
book move together the way a real portfolio and its index do.

The companions' identifiers are plainly synthetic (``BM-US-FIN-1``): they stand
for the kinds of company a world index holds - a large bank, an integrated oil
company, a Swiss food group, a Japanese carmaker - without claiming to be one.
Starting capitalisations are chosen so the index looks like a world index:
roughly three quarters North America, with the UK, Europe, Switzerland and Japan
making up the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache

from ..domain.instruments import Bond
from ..marketdata.providers.synthetic import InstrumentSpec, SyntheticHistory, demo_market
from ..marketdata.series import TimeSeries
from ..performance.attribution import AttributionResult, attribute, benchmark_look_through, monthly
from ..performance.benchmark import BenchmarkDay, Constituent, EquityIndex, PolicyBenchmark, bond_total_returns
from ..performance.contributions import PortfolioDay, decompose
from ..performance.returns import ReturnSeries, daily_returns
from .demo_accounting import BOND_ID, DemoAccounting, build_demo_accounting
from .demo_market import DEMO_END, DEMO_START

POLICY = {"equity": 0.80, "fixed income": 0.15, "cash": 0.05}
BENCHMARK_NAME = "Policy benchmark: 80% Meridian World Equity, 15% US Treasury, 5% cash"

#: The demonstration book's own stocks in the index, with starting capitalisations in USD billions.
BOOK_CONSTITUENTS: tuple[tuple[str, str, str, str, str, str, float], ...] = (
    ("US-AAPL", "Apple Inc", "Information Technology", "North America", "USD", "XNYS", 3400.0),
    ("US-MSFT", "Microsoft Corporation", "Information Technology", "North America", "USD", "XNYS", 3100.0),
    ("US-JNJ", "Johnson & Johnson", "Health Care", "North America", "USD", "XNYS", 380.0),
    ("GB-BAE", "BAE Systems plc", "Industrials", "United Kingdom", "GBP", "XLON", 115.0),
    ("DE-BAYN", "Bayer AG", "Health Care", "Europe ex UK", "EUR", "TARGET", 66.0),
    ("CH-ROG", "Roche Holding AG", "Health Care", "Switzerland", "CHF", "TARGET", 530.0),
)

#: Synthetic companions: identifier, description, sector, region, currency, calendar, cap, vol, drift, beta.
COMPANIONS: tuple[tuple[str, str, str, str, str, str, float, float, float, float], ...] = (
    (
        "BM-US-IT-1",
        "US semiconductor leader",
        "Information Technology",
        "North America",
        "USD",
        "XNYS",
        2200,
        0.42,
        0.14,
        1.45,
    ),
    (
        "BM-US-IT-2",
        "US enterprise software",
        "Information Technology",
        "North America",
        "USD",
        "XNYS",
        600,
        0.30,
        0.10,
        1.20,
    ),
    (
        "BM-US-COM-1",
        "US search and advertising",
        "Communication Services",
        "North America",
        "USD",
        "XNYS",
        2000,
        0.28,
        0.10,
        1.10,
    ),
    (
        "BM-US-COM-2",
        "US social media",
        "Communication Services",
        "North America",
        "USD",
        "XNYS",
        1500,
        0.35,
        0.12,
        1.25,
    ),
    (
        "BM-US-CD-1",
        "US online retail",
        "Consumer Discretionary",
        "North America",
        "USD",
        "XNYS",
        1800,
        0.32,
        0.09,
        1.20,
    ),
    (
        "BM-US-CD-2",
        "US electric vehicles",
        "Consumer Discretionary",
        "North America",
        "USD",
        "XNYS",
        400,
        0.55,
        0.05,
        1.60,
    ),
    ("BM-US-FIN-1", "US money-centre bank", "Financials", "North America", "USD", "XNYS", 550, 0.24, 0.08, 1.05),
    ("BM-US-FIN-2", "US payments network", "Financials", "North America", "USD", "XNYS", 450, 0.22, 0.09, 0.95),
    (
        "BM-US-FIN-3",
        "US diversified holding company",
        "Financials",
        "North America",
        "USD",
        "XNYS",
        300,
        0.18,
        0.07,
        0.80,
    ),
    ("BM-US-HC-1", "US managed care", "Health Care", "North America", "USD", "XNYS", 450, 0.24, 0.07, 0.75),
    ("BM-US-HC-2", "US large pharmaceuticals", "Health Care", "North America", "USD", "XNYS", 300, 0.22, 0.06, 0.60),
    ("BM-US-IND-1", "US aerospace and engines", "Industrials", "North America", "USD", "XNYS", 250, 0.26, 0.08, 1.05),
    ("BM-US-IND-2", "US machinery", "Industrials", "North America", "USD", "XNYS", 200, 0.27, 0.07, 1.10),
    ("BM-US-ENE-1", "US integrated oil", "Energy", "North America", "USD", "XNYS", 450, 0.25, 0.04, 0.85),
    ("BM-US-CS-1", "US household products", "Consumer Staples", "North America", "USD", "XNYS", 400, 0.16, 0.05, 0.50),
    ("BM-US-CS-2", "US discount retail", "Consumer Staples", "North America", "USD", "XNYS", 350, 0.18, 0.07, 0.60),
    ("BM-GB-FIN-1", "UK global bank", "Financials", "United Kingdom", "GBP", "XLON", 330, 0.25, 0.07, 1.00),
    ("BM-GB-ENE-1", "UK integrated oil", "Energy", "United Kingdom", "GBP", "XLON", 440, 0.24, 0.04, 0.85),
    ("BM-GB-CS-1", "UK consumer goods", "Consumer Staples", "United Kingdom", "GBP", "XLON", 220, 0.17, 0.04, 0.55),
    (
        "BM-EU-IT-1",
        "European lithography equipment",
        "Information Technology",
        "Europe ex UK",
        "EUR",
        "TARGET",
        620,
        0.38,
        0.12,
        1.35,
    ),
    (
        "BM-EU-CD-1",
        "European luxury goods",
        "Consumer Discretionary",
        "Europe ex UK",
        "EUR",
        "TARGET",
        770,
        0.30,
        0.06,
        1.15,
    ),
    ("BM-EU-FIN-1", "European insurer", "Financials", "Europe ex UK", "EUR", "TARGET", 260, 0.21, 0.07, 0.95),
    (
        "BM-EU-IND-1",
        "European industrial conglomerate",
        "Industrials",
        "Europe ex UK",
        "EUR",
        "TARGET",
        330,
        0.25,
        0.07,
        1.05,
    ),
    ("BM-EU-CS-1", "European beverages", "Consumer Staples", "Europe ex UK", "EUR", "TARGET", 200, 0.18, 0.03, 0.60),
    (
        "BM-CH-CS-1",
        "Swiss food and beverages",
        "Consumer Staples",
        "Switzerland",
        "CHF",
        "TARGET",
        570,
        0.15,
        0.03,
        0.45,
    ),
    ("BM-CH-FIN-1", "Swiss private bank", "Financials", "Switzerland", "CHF", "TARGET", 220, 0.23, 0.06, 0.95),
    ("BM-JP-CD-1", "Japanese carmaker", "Consumer Discretionary", "Japan", "JPY", "XTKS", 620, 0.27, 0.06, 0.95),
    ("BM-JP-IT-1", "Japanese electronics", "Information Technology", "Japan", "JPY", "XTKS", 330, 0.30, 0.08, 1.10),
    ("BM-JP-FIN-1", "Japanese megabank", "Financials", "Japan", "JPY", "XTKS", 260, 0.26, 0.07, 1.00),
    ("BM-JP-IND-1", "Japanese trading house", "Industrials", "Japan", "JPY", "XTKS", 220, 0.24, 0.07, 0.95),
)

#: Funds are looked through: the US index fund to the North American constituents, the world fund to all.
FUND_SCOPE: dict[str, str | None] = {"US-IVV": "North America", "IE-IWDA": None}


def companion_specs() -> list[InstrumentSpec]:
    return [
        InstrumentSpec(
            instrument_id=key,
            currency=currency,
            calendar=calendar,
            initial_price=100.0,
            annual_vol=vol,
            annual_drift=drift,
            beta=beta,
            sector=sector,
            price_places=2 if currency != "JPY" else 0,
        )
        for key, _, sector, _, currency, calendar, _, vol, drift, beta in COMPANIONS
    ]


@lru_cache(maxsize=2)
def benchmark_universe(seed: int = 7) -> SyntheticHistory:
    """The thirty companions, generated in the demonstration market's own factors."""
    return demo_market(seed).companion(companion_specs(), DEMO_START, DEMO_END)


def constituents() -> tuple[Constituent, ...]:
    book = tuple(
        Constituent(key, name, sector, region, ccy, cal, cap)
        for key, name, sector, region, ccy, cal, cap in BOOK_CONSTITUENTS
    )
    extra = tuple(
        Constituent(key, name, sector, region, ccy, cal, cap)
        for key, name, sector, region, ccy, cal, cap, *_ in COMPANIONS
    )
    return book + extra


@dataclass
class DemoPerformance:
    accounting: DemoAccounting
    universe: SyntheticHistory

    @cached_property
    def total_return_series(self) -> dict[str, TimeSeries]:
        series = dict(self.universe.economic_value)
        series.update(self.accounting.market.history.economic_value)
        return series

    @cached_property
    def equity_index(self) -> EquityIndex:
        return EquityIndex("Meridian World Equity", constituents(), self.total_return_series, self.accounting.fx)

    @cached_property
    def bond_returns(self) -> dict:
        bond = self.accounting.instruments[BOND_ID]
        assert isinstance(bond, Bond)
        clean = self.accounting.prices.series(BOND_ID)
        assert clean is not None
        return bond_total_returns(bond, clean, self.accounting.valuation_days)

    @cached_property
    def policy(self) -> PolicyBenchmark:
        return PolicyBenchmark(BENCHMARK_NAME, self.equity_index, POLICY, self.bond_returns)

    @cached_property
    def benchmark_days(self) -> list[BenchmarkDay]:
        return self.policy.build(self.accounting.valuation_days)

    @cached_property
    def portfolio_days(self) -> list[PortfolioDay]:
        demo = self.accounting
        return decompose(demo.valuator, demo.valuations, demo.daily_bridges)

    @cached_property
    def portfolio_returns(self) -> ReturnSeries:
        return ReturnSeries.from_daily(daily_returns(self.accounting.daily_bridges), "Global Equity Core")

    @cached_property
    def benchmark_returns(self) -> ReturnSeries:
        days = self.benchmark_days
        return ReturnSeries(tuple(item.day for item in days), tuple(item.rate for item in days), "Policy benchmark")

    @cached_property
    def equity_returns(self) -> ReturnSeries:
        rows = self.equity_index.days(self.accounting.valuation_days)
        return ReturnSeries(
            tuple(day for day, _ in rows),
            tuple(sum(weight * (local + move) for _, weight, local, move in items) for _, items in rows),
            "Meridian World Equity",
        )

    def attribution(self, dimension: str = "sector", start=None, end=None) -> AttributionResult:  # type: ignore[no-untyped-def]
        return attribute(
            self.portfolio_days,
            self.benchmark_days,
            self.accounting.instruments,
            dimension=dimension,
            look_through=benchmark_look_through(FUND_SCOPE),
            start=start,
            end=end,
        )

    @cached_property
    def by_sector(self) -> AttributionResult:
        return self.attribution("sector")

    @cached_property
    def by_region(self) -> AttributionResult:
        return self.attribution("region")

    @cached_property
    def monthly_by_sector(self) -> list[AttributionResult]:
        return monthly(self.by_sector)


@lru_cache(maxsize=2)
def build_demo_performance(seed: int = 7) -> DemoPerformance:
    return DemoPerformance(build_demo_accounting(seed), benchmark_universe(seed))
