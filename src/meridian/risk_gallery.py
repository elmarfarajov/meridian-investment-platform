"""The Day 5 charts: the factor risk model, the account's risk, and the model's validation.

Data preparation lives here and the chart functions take plain inputs, as for
the earlier days, so every figure is rebuilt deterministically by
``meridian charts gallery`` and shows the numbers the tests assert.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .risk.comparison import eigenvalue_spectrum, summarise
from .risk.covariance import correlation_of
from .risk.factors import INDUSTRIES, STYLES, group_of
from .risk.universe import REGIMES
from .risk.validation import christoffersen, confidence_band, kupiec, rolling_bias, summarise_bias
from .services.demo_risk import DemoRisk, build_demo_risk
from .viz.risk import (
    plot_active_exposures,
    plot_asset_contributions,
    plot_bias_statistics,
    plot_book_bias,
    plot_eigenvalue_spectrum,
    plot_factor_correlation,
    plot_factor_returns,
    plot_minimum_variance,
    plot_regression_quality,
    plot_risk_decomposition,
    plot_risk_report,
    plot_specific_calibration,
    plot_stress_tests,
    plot_var_backtest,
    plot_var_methods,
    plot_volatility_forecasts,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

BIAS_WINDOW = 126
BOOK_WINDOW = 126
ANNUAL = math.sqrt(252)


def _risk() -> DemoRisk:
    return build_demo_risk()


def regimes() -> list[tuple[str, date, date]]:
    return [(regime.name, regime.start, regime.end) for regime in REGIMES if regime.name != "2020 recovery"]


def group_table(risk: DemoRisk) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    groups = {
        "Portfolio": risk.portfolio.by_group(),
        "Benchmark": risk.benchmark.by_group(),
        "Active": risk.active.by_group(),
    }
    totals = {
        "Portfolio": risk.portfolio.volatility,
        "Benchmark": risk.benchmark.volatility,
        "Active": risk.active.volatility,
    }
    return groups, totals


def decomposition_chart() -> Figure:
    risk = _risk()
    groups, totals = group_table(risk)
    factors = sorted(risk.active.by_factor().items(), key=lambda item: -abs(item[1]))[:11]
    rows = [(name, value, risk.portfolio.exposure(name), risk.benchmark.exposure(name)) for name, value in factors]
    rows.append(("Specific", risk.active.by_group()["Specific"], 0.0, 0.0))
    return plot_risk_decomposition(groups, totals, rows, risk.model.as_of)


def bias_chart() -> Figure:
    risk = _risk()
    tracks = risk.universe_tracks
    market = tracks["Cap-weighted market"]
    rolling = {method: rolling_bias(market.standardised(method), BIAS_WINDOW) for method in ("sample", "ewma", "truth")}
    random = {
        method: [
            summarise_bias(name, track.standardised(method)).bias
            for name, track in tracks.items()
            if name.startswith("Random")
        ]
        for method in ("truth", "ewma", "sample")
    }
    full = confidence_band(len(market.days))
    return plot_bias_statistics(
        market.days, rolling, confidence_band(BIAS_WINDOW), BIAS_WINDOW, random, full, regimes()
    )


def eigen_chart() -> Figure:
    risk = _risk()
    eigenvalues, ratio = eigenvalue_spectrum(risk.universe, len(risk.universe.days))
    return plot_eigenvalue_spectrum(eigenvalues, ratio, 252)


def minimum_variance_chart() -> Figure:
    risk = _risk()
    return plot_minimum_variance(risk.minimum_variance, summarise(risk.minimum_variance))


def factor_returns_chart() -> Figure:
    risk = _risk()
    estimated = risk.estimated
    styles = {name: estimated.factor(name) for name in STYLES}
    industries = {name: estimated.factor(name) for name in INDUSTRIES}
    return plot_factor_returns(estimated.days, styles, industries, regimes())


def volatility_errors(risk: DemoRisk) -> dict[str, float]:
    forecasts = risk.world_volatility
    scored = ~np.isnan(forecasts["GARCH(1,1)"])
    truth = forecasts["Truth"][scored]
    return {
        name: float(np.abs(np.log(values[scored] / truth)).mean())
        for name, values in forecasts.items()
        if name != "Truth"
    }


def volatility_chart() -> Figure:
    risk = _risk()
    forecasts = risk.world_volatility
    return plot_volatility_forecasts(risk.estimated.days, forecasts, volatility_errors(risk), regimes())


def correlation_chart() -> Figure:
    risk = _risk()
    model = risk.model
    names = risk.factors.names
    return plot_factor_correlation(
        names, correlation_of(model.factor_covariance), [model.factor_volatility(name) for name in names], model.as_of
    )


def exposures_chart() -> Figure:
    risk = _risk()
    names = risk.factors.names
    return plot_active_exposures(
        names, list(risk.portfolio.exposures), list(risk.benchmark.exposures), [group_of(name) for name in names]
    )


def contribution_rows(decomposition, top: int = 14) -> list[tuple[str, float, float, float]]:  # type: ignore[no-untyped-def]
    rows = [
        (asset, float(weight), float(marginal) * ANNUAL, float(contribution) * ANNUAL)
        for asset, weight, marginal, contribution in zip(
            decomposition.assets,
            decomposition.weights,
            decomposition.marginal,
            decomposition.asset_contributions,
            strict=True,
        )
    ]
    return sorted(rows, key=lambda row: -abs(row[3]))[:top]


def contributions_chart() -> Figure:
    risk = _risk()
    return plot_asset_contributions(
        contribution_rows(risk.portfolio),
        contribution_rows(risk.active),
        risk.portfolio.volatility,
        risk.active.volatility,
    )


def backtest_series(risk: DemoRisk) -> tuple[list[date], np.ndarray, np.ndarray]:
    forecasts = risk.book_forecasts
    return (
        [item.day for item in forecasts],
        np.array([item.realised for item in forecasts]),
        np.array([item.var for item in forecasts]),
    )


def var_backtest_chart() -> Figure:
    risk = _risk()
    days, realised, var = backtest_series(risk)
    hits = (-realised > var).astype(int)
    rolling = np.array([hits[max(0, index - 249) : index + 1].sum() for index in range(len(hits))])
    tests = [("Kupiec", kupiec(int(hits.sum()), len(hits))), ("Christoffersen", christoffersen(hits))]
    return plot_var_backtest(
        days, realised, var, rolling, [(name, test.p_value, test.rejected) for name, test in tests]
    )


def var_methods_chart() -> Figure:
    risk = _risk()
    _, simulated = risk.monte_carlo
    nav = float(risk.performance.accounting.valuations[-1].nav)
    return plot_var_methods(risk.holdings_history, simulated, risk.var_estimates, nav)


def stress_chart() -> Figure:
    risk = _risk()
    return plot_stress_tests(
        [(item.scenario.name, item.scenario.kind, item.portfolio, item.benchmark) for item in risk.stress]
    )


def book_bias_chart() -> Figure:
    risk = _risk()
    forecasts = risk.book_forecasts
    total = np.array([item.realised / item.volatility for item in forecasts])
    active = np.array([item.active / item.tracking_error for item in forecasts])
    shrunk = np.array([item.active / item.tracking_error for item in risk.with_shrinkage().book_forecasts])
    truth = risk.market_truth_z[: len(forecasts)]
    series = {
        "total risk (volatility forecast)": rolling_bias(total, BOOK_WINDOW),
        "active risk (tracking error forecast)": rolling_bias(active, BOOK_WINDOW),
        "active risk, specific risk shrunk to the universe (rejected)": rolling_bias(shrunk, BOOK_WINDOW),
        "the market's true volatility, same days": rolling_bias(truth, BOOK_WINDOW),
    }
    summaries = [
        (label, summarise_bias(label, values).bias, summarise_bias(label, values, BOOK_WINDOW).mrad)
        for label, values in (
            ("total risk", total),
            ("active risk", active),
            ("active, shrunk (rejected)", shrunk),
            ("true market volatility", truth),
        )
    ]
    return plot_book_bias(
        [item.day for item in forecasts], series, BOOK_WINDOW, confidence_band(BOOK_WINDOW), summaries
    )


def specific_calibration(risk: DemoRisk) -> tuple[list[str], list[float], list[float], list[float], list[float]]:
    shrunk_bias = np.nanstd(risk.specific_z_shrunk, axis=0, ddof=1)
    raw_bias = np.nanstd(risk.specific_z, axis=0, ddof=1)
    caps = risk.universe.caps[-1]
    deciles = np.array_split(np.argsort(caps), 10)
    labels = [f"{index + 1}" for index in range(10)]
    return (
        labels,
        [float(np.mean(shrunk_bias[group])) for group in deciles],
        [float(np.mean(raw_bias[group])) for group in deciles],
        [float(np.std(shrunk_bias[group])) for group in deciles],
        [float(np.std(raw_bias[group])) for group in deciles],
    )


def specific_chart() -> Figure:
    risk = _risk()
    labels, shrunk, raw, spread_shrunk, spread_raw = specific_calibration(risk)
    observations = risk.specific_z.shape[0]
    return plot_specific_calibration(labels, shrunk, raw, confidence_band(observations), spread_shrunk, spread_raw)


def regression_chart() -> Figure:
    risk = _risk()
    estimated = risk.estimated
    local = risk.factors.local
    significant = {name: float(np.mean(np.abs(estimated.t_stats[:, index]) > 2)) for index, name in enumerate(local)}
    return plot_regression_quality(estimated.days, estimated.r_squared, significant, regimes())


def headline(risk: DemoRisk) -> list[tuple[str, str]]:
    var = risk.var_estimates
    forecasts = risk.book_forecasts
    exceptions = sum(item.exception for item in forecasts)
    return [
        ("Volatility (forecast)", f"{risk.portfolio.volatility:.1%}"),
        ("Tracking error", f"{risk.active.volatility:.2%}"),
        ("1-day 99% VaR", f"{var[0].var:.2%}"),
        ("1-day 99% ES (Monte Carlo)", f"{var[3].es:.2%}"),
        ("Systematic share", f"{risk.portfolio.factor_share:.0%}"),
        ("World exposure", f"{risk.portfolio.exposure('World'):.2f}"),
        ("VaR exceptions", f"{exceptions} / {len(forecasts)}"),
        ("Worst stress test", f"{min(item.portfolio for item in risk.stress):+.1%}"),
    ]


def report_chart() -> Figure:
    risk = _risk()
    groups, totals = group_table(risk)
    top = [(asset, contribution) for asset, _, _, contribution in contribution_rows(risk.portfolio, 8)]
    stress = [(item.scenario.name, item.portfolio, item.benchmark) for item in risk.stress]
    days, realised, var = backtest_series(risk)
    return plot_risk_report(
        risk.performance.accounting.portfolio.name,
        risk.model.as_of,
        headline(risk),
        groups,
        totals,
        top,
        stress,
        days,
        realised,
        var,
    )


def risk_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    def item(filename: str, title: str, description: str, builder) -> GalleryItem:  # type: ignore[no-untyped-def]
        return GalleryItem(filename, title, description, builder, "risk")

    return (
        item(
            "risk-decomposition.png",
            "Risk decomposition",
            "Volatility and tracking error split into market, industries, styles, currencies and specific risk.",
            decomposition_chart,
        ),
        item(
            "bias-statistics.png",
            "Bias statistics",
            "Ten years of forecasts scored against outcomes, with the 95% band, for EWMA, the sample and the truth.",
            bias_chart,
        ),
        item(
            "eigenvalue-spectrum.png",
            "Why a sample covariance fails",
            "Eigenvalues of 500 stocks over 252 days against the Marchenko-Pastur law of pure noise.",
            eigen_chart,
        ),
        item(
            "minimum-variance.png",
            "What an optimiser builds from each estimator",
            "Minimum-variance portfolios: the risk each covariance estimator promised, and delivered.",
            minimum_variance_chart,
        ),
        item(
            "factor-returns.png",
            "Factor returns",
            "What the market paid each style and each industry, from the daily cross-sectional regressions.",
            factor_returns_chart,
        ),
        item(
            "volatility-forecasts.png",
            "Volatility forecasts against the truth",
            "GARCH, EWMA and an equal-weighted window forecasting the world factor's volatility.",
            volatility_chart,
        ),
        item(
            "factor-correlation.png",
            "The factor covariance",
            "Correlations and volatilities of the twenty-one factors on the report date.",
            correlation_chart,
        ),
        item(
            "active-exposures.png",
            "Active exposures",
            "The account's industry, style and currency exposures against its benchmark's.",
            exposures_chart,
        ),
        item(
            "risk-contributions.png",
            "Risk by holding",
            "Each holding's contribution to volatility and to tracking error.",
            contributions_chart,
        ),
        item(
            "var-backtest.png",
            "VaR backtest",
            "The account's daily returns against the morning's 99% VaR, with the Basel traffic light.",
            var_backtest_chart,
        ),
        item(
            "var-methods.png",
            "VaR four ways",
            "Parametric, Cornish-Fisher, historical and Monte Carlo VaR and expected shortfall.",
            var_methods_chart,
        ),
        item(
            "stress-tests.png",
            "Stress tests",
            "Historical replays and hypothetical shocks applied to today's exposures.",
            stress_chart,
        ),
        item(
            "book-bias.png",
            "The account's forecasts, validated",
            "Rolling bias of the account's volatility and tracking error forecasts, against the truth's own score.",
            book_bias_chart,
        ),
        item(
            "specific-risk.png",
            "Specific risk calibration",
            "Bias of specific-risk forecasts by size decile, with and without Bayesian shrinkage.",
            specific_chart,
        ),
        item(
            "regression-quality.png",
            "How much the factors explain",
            "Daily R-squared of the cross-sectional regressions and how often each factor is significant.",
            regression_chart,
        ),
        item(
            "risk-report.png",
            "The risk report",
            "The page the risk committee reads: risk by source, contributions, stress tests and the VaR backtest.",
            report_chart,
        ),
    )
