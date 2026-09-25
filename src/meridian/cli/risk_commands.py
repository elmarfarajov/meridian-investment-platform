"""``meridian risk`` - the factor risk model from the command line.

Every command reads the demonstration account measured by the model estimated
on the synthetic estimation universe (``meridian.services.demo_risk``).
``run --persist`` stores the factor return history, every morning's forecast
with its outcome, and the report's exposures; ``stored`` recounts the backtest
from the database.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import numpy as np
import typer

from ..config import get_settings
from ..persistence import Database, UnitOfWork
from ..risk.comparison import summarise
from ..risk.factors import GROUPS, group_of
from ..risk.validation import christoffersen, kupiec, summarise_bias, traffic_light
from ..risk.var import scale_horizon
from ..services.demo_risk import DemoRisk, build_demo_risk
from ..services.risk_run import MODEL_ID, run_demo_risk
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(
    help="Risk: the factor model, the account's risk and where it comes from, VaR, stress tests and validation.",
    no_args_is_help=True,
)


def _demo() -> DemoRisk:
    logging.getLogger().setLevel(logging.WARNING)
    return build_demo_risk()


def _pct(value: float, places: int = 2) -> str:
    return f"{value:.{places}%}"


@app.command("model")
def model() -> None:
    """The model: its factors, how volatile each is today, and how much of the cross-section it explains."""
    risk = _demo()
    estimated = risk.estimated
    today = risk.model
    rows = []
    for index, name in enumerate(risk.factors.names):
        history = estimated.returns[:, index]
        rows.append(
            (
                group_of(name),
                name,
                _pct(today.factor_volatility(name)),
                _pct(float(np.std(history, ddof=1)) * 252**0.5),
                _pct(float(np.prod(1 + history) - 1), 1),
            )
        )
    console.print(
        render_rows(
            table(
                f"Factor risk model on {today.as_of} - {len(estimated.days):,} days, {len(risk.universe.stocks)} "
                "stocks",
                ["Group", "Factor", "Vol today", "Vol, whole history", "Cumulative return"],
                numeric=[2, 3, 4],
                caption=f"Mean cross-sectional R-squared {float(estimated.r_squared.mean()):.1%}; {today.description}.",
            ),
            rows,
        )
    )


@app.command("portfolio")
def portfolio() -> None:
    """Total and active risk of the account, and where each comes from."""
    risk = _demo()
    rows = []
    total, active, bench = risk.portfolio.by_group(), risk.active.by_group(), risk.benchmark.by_group()
    for group in (*GROUPS, "Specific"):
        rows.append((group, _pct(total[group]), _pct(bench[group]), _pct(active[group])))
    rows.append(
        ("Total", _pct(risk.portfolio.volatility), _pct(risk.benchmark.volatility), _pct(risk.active.volatility))
    )
    console.print(
        render_rows(
            table(
                f"Risk on {risk.model.as_of}: contribution to annualised volatility",
                ["Source", "Portfolio", "Benchmark", "Active (tracking error)"],
                numeric=[1, 2, 3],
                caption="Euler contributions: each column adds up to its total exactly.",
            ),
            rows,
        )
    )
    factors = sorted(risk.active.by_factor().items(), key=lambda item: -abs(item[1]))[:8]
    console.print(
        render_rows(
            table(
                "The largest active bets",
                ["Factor", "Portfolio exposure", "Benchmark exposure", "Contribution to tracking error"],
                numeric=[1, 2, 3],
            ),
            [
                (name, f"{risk.portfolio.exposure(name):+.2f}", f"{risk.benchmark.exposure(name):+.2f}", _pct(value))
                for name, value in factors
            ],
        )
    )


@app.command("contributions")
def contributions(
    active: Annotated[
        bool, typer.Option("--active", help="Contributions to tracking error, not to volatility")
    ] = False,
    top: Annotated[int, typer.Option("--top", min=1)] = 15,
) -> None:
    """Each holding's weight, marginal risk and contribution."""
    risk = _demo()
    decomposition = risk.active if active else risk.portfolio
    items = sorted(
        zip(
            decomposition.assets,
            decomposition.weights,
            decomposition.marginal,
            decomposition.asset_contributions,
            strict=True,
        ),
        key=lambda item: -abs(item[3]),
    )[:top]
    rows = [
        (
            asset,
            f"{weight:+.2%}",
            f"{marginal * 252**0.5:.2%}",
            _pct(contribution * 252**0.5),
            f"{contribution / decomposition.daily:.1%}",
        )
        for asset, weight, marginal, contribution in items
    ]
    what = "tracking error" if active else "volatility"
    console.print(
        render_rows(
            table(
                f"Contribution to {what} ({_pct(decomposition.volatility)})",
                ["Holding", "Active weight" if active else "Weight", "Marginal", "Contribution", "Share"],
                numeric=[1, 2, 3, 4],
                caption=(
                    "Marginal: the change in risk per unit of weight. Funds are looked through; "
                    "':basis' is a fund's own tracking risk."
                ),
            ),
            rows,
        )
    )


@app.command("var")
def var(horizon: Annotated[int, typer.Option("--horizon", min=1, help="Days, by square-root-of-time")] = 1) -> None:
    """Value at risk and expected shortfall at 99%, four ways."""
    risk = _demo()
    nav = float(risk.performance.accounting.valuations[-1].nav)
    rows = []
    for estimate in risk.var_estimates:
        scaled = scale_horizon(estimate, horizon) if horizon > 1 else estimate
        rows.append(
            (estimate.method, _pct(scaled.var), f"{scaled.var * nav:,.0f}", _pct(scaled.es), f"{scaled.es * nav:,.0f}")
        )
    console.print(
        render_rows(
            table(
                f"{horizon}-day 99% VaR and expected shortfall on a NAV of {nav:,.0f} USD",
                ["Method", "VaR", "VaR (USD)", "ES", "ES (USD)"],
                numeric=[1, 2, 3, 4],
                caption=(
                    "Losses, as positive numbers. Historical simulation applies today's holdings "
                    "to the demonstration window."
                ),
            ),
            rows,
        )
    )


@app.command("stress")
def stress() -> None:
    """Historical replays and hypothetical shocks against today's factor exposures."""
    risk = _demo()
    rows = [
        (
            item.scenario.name,
            item.scenario.kind,
            f"{item.portfolio:+.2%}",
            f"{item.benchmark:+.2%}",
            f"{item.active:+.2%}",
        )
        for item in risk.stress
    ]
    console.print(
        render_rows(
            table(
                "Stress tests",
                ["Scenario", "Kind", "Portfolio", "Benchmark", "Active"],
                numeric=[2, 3, 4],
                caption="Factor moves only; stock-specific returns are not part of a scenario.",
            ),
            rows,
        )
    )


@app.command("backtest")
def backtest() -> None:
    """How the account's daily forecasts fared: bias statistics and VaR exceptions."""
    risk = _demo()
    forecasts = risk.book_forecasts
    total = summarise_bias("Total risk", np.array([item.realised / item.volatility for item in forecasts]))
    active = summarise_bias("Active risk", np.array([item.active / item.tracking_error for item in forecasts]))
    truth = summarise_bias("The market's true volatility", risk.market_truth_z)
    rows = [
        (s.name, f"{s.bias:.3f}", f"{s.low:.3f} - {s.high:.3f}", f"{s.mrad:.3f}", s.verdict)
        for s in (total, active, truth)
    ]
    console.print(
        render_rows(
            table(
                f"Bias statistics over {len(forecasts)} days",
                ["Forecast", "Bias", "95% band", "MRAD", "Verdict"],
                numeric=[1, 3],
                caption=(
                    "A correct forecast has bias one. The last row is the yardstick: "
                    "the true volatility scored on the same days."
                ),
            ),
            rows,
        )
    )
    hits = np.array([item.exception for item in forecasts], dtype=int)
    tests = [kupiec(int(hits.sum()), len(hits)), christoffersen(hits)]
    light = traffic_light(int(hits[-250:].sum()))
    console.print(
        render_rows(
            table("99% VaR backtest", ["Test", "Statistic", "p-value", "Result"], numeric=[1, 2]),
            [
                (test.name, f"{test.statistic:.2f}", f"{test.p_value:.3f}", "rejected" if test.rejected else "passed")
                for test in tests
            ]
            + [("Basel traffic light, last 250 days", f"{light.exceptions} exceptions", "", light.zone)],
        )
    )


@app.command("validate")
def validate() -> None:
    """The model against the truth on the estimation universe, and why the sample covariance fails."""
    risk = _demo()
    tracks = risk.universe_tracks
    rows = []
    for method, label in (("truth", "Truth"), ("ewma", "EWMA"), ("sample", "Equal-weighted sample")):
        market = summarise_bias(label, tracks["Cap-weighted market"].standardised(method))
        random = [
            summarise_bias(name, track.standardised(method))
            for name, track in tracks.items()
            if name.startswith("Random")
        ]
        rows.append(
            (
                label,
                f"{market.bias:.3f}",
                f"{market.mrad:.3f}",
                f"{np.mean([s.low <= s.bias <= s.high for s in random]):.0%}",
                f"{np.mean([s.mrad for s in random]):.3f}",
            )
        )
    console.print(
        render_rows(
            table(
                f"Forecasts scored on {len(tracks['Cap-weighted market'].days):,} days of the estimation universe",
                ["Forecaster", "Market bias", "Market MRAD", "Random portfolios in band", "Random MRAD"],
                numeric=[1, 2, 3, 4],
            ),
            rows,
        )
    )
    console.print(
        render_rows(
            table(
                "Minimum-variance portfolios: what each estimator promised, and delivered next month",
                ["Estimator", "Promised", "Delivered", "Gross exposure"],
                numeric=[1, 2, 3],
                caption="500 stocks, 252 days: the sample covariance is singular and promises a riskless portfolio.",
            ),
            [
                (row.estimator, _pct(row.promised), _pct(row.delivered), f"{row.gross:.1f}x")
                for row in summarise(risk.minimum_variance)
            ],
        )
    )


@app.command("report")
def report(
    out: Annotated[Path, typer.Option("--out", help="Where to write the PNG")] = Path("risk-report.png"),
) -> None:
    """Draw the one-page risk report."""
    from ..risk_gallery import report_chart

    save_figure(report_chart(), out)
    success(f"wrote {out}")


@app.command("run")
def run(
    persist: Annotated[bool, typer.Option("--persist/--dry-run", help="Write the model history and forecasts")] = False,
) -> None:
    """Check the controls and, with --persist, store factor returns, forecasts and exposures."""
    risk = _demo()
    if not persist:
        result = run_demo_risk(risk)
    else:
        database = Database(get_settings()).create_all()
        try:
            with database.session() as session:
                unit_of_work = UnitOfWork(session)
                result = run_demo_risk(risk, unit_of_work)
                unit_of_work.commit()
        finally:
            database.dispose()
    console.print(render_rows(table("Risk run", ["Step", "Result"]), result.summary_rows()))
    if persist:
        success("risk model history and forecasts stored")


@app.command("stored")
def stored() -> None:
    """Recount the backtest and the factor volatilities from the database (after run --persist)."""
    portfolio_id = "PF-GLOBAL-EQ"
    database = Database(get_settings())
    try:
        with database.session() as session:
            repository = UnitOfWork(session).risk
            hits, days = repository.exception_count(portfolio_id)
            if days == 0:
                fail("nothing stored yet - run `meridian risk run --persist` first")
            vols = [
                (name, _pct(repository.realised_volatility(MODEL_ID, name)))
                for name in ("World", "Beta", "Size", "Momentum", "FX JPY")
            ]
    finally:
        database.dispose()
    console.print(
        render_rows(
            table("Recounted from the database", ["Measure", "Value"], numeric=[1]),
            [("VaR exceptions", f"{hits} in {days} days")]
            + [(f"{name} volatility (SQL)", value) for name, value in vols],
        )
    )
