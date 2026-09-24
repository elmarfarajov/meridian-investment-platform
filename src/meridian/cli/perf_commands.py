"""``meridian perf`` - performance measurement and attribution from the command line.

Every command reads the demonstration account's daily returns, computed from
the book of record, and the policy benchmark. ``run --persist`` stores the daily
returns and the linked attribution for since inception and each calendar year,
after which ``stored`` reads them back out of SQL and checks that the stored
effects still explain the stored active return.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from ..config import get_settings
from ..core.exceptions import MeridianError
from ..performance.attribution import EFFECTS
from ..performance.contributions import holding_contributions
from ..performance.returns import standard_periods
from ..performance.statistics import drawdown_episodes, summary_rows
from ..persistence import Database, UnitOfWork
from ..services.demo_performance import DemoPerformance, build_demo_performance
from ..services.performance_run import run_demo_performance
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(
    help="Performance: time-weighted returns, the benchmark, Brinson attribution, risk and the factsheet.",
    no_args_is_help=True,
)

DIMENSIONS = ("sector", "region")


def _demo() -> DemoPerformance:
    logging.getLogger().setLevel(logging.WARNING)
    return build_demo_performance()


def _day(text: str | None) -> date | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        fail(f"{text!r} is not an ISO date (YYYY-MM-DD)")


def _pct(value: float) -> str:
    return f"{value:+.2%}"


def _bp(value: float) -> str:
    return f"{value * 1e4:+.0f}"


@app.command("run")
def run(
    persist: Annotated[
        bool, typer.Option("--persist/--dry-run", help="Write returns and attribution to the database")
    ] = False,
) -> None:
    """Compute returns and attribution for the report periods, check them - and persist if asked."""
    demo = _demo()
    if not persist:
        result = run_demo_performance(demo)
    else:
        database = Database(get_settings()).create_all()
        try:
            with database.session() as session:
                unit_of_work = UnitOfWork(session)
                result = run_demo_performance(demo, unit_of_work)
                unit_of_work.commit()
        finally:
            database.dispose()
    console.print(render_rows(table("Performance run", ["Step", "Result"]), result.summary_rows()))
    if persist:
        success("returns and attribution stored")


@app.command("returns")
def returns(
    yearly: Annotated[bool, typer.Option("--yearly", help="Calendar years instead of factsheet periods")] = False,
) -> None:
    """The portfolio against its benchmark: MTD to since inception, or year by year."""
    demo = _demo()
    mine, theirs = demo.portfolio_returns, demo.benchmark_returns
    if yearly:
        benchmark_years = dict(theirs.yearly())
        rows: list[tuple[str, ...]] = [
            (str(year), _pct(rate), _pct(benchmark_years[year]), _pct(rate - benchmark_years[year]))
            for year, rate in mine.yearly()
        ]
        caption = "Calendar years, linked from daily returns; the first and last years are partial."
    else:
        rows = []
        for ours, bench in zip(standard_periods(mine), standard_periods(theirs), strict=True):
            a = ours.annualised if ours.is_annualised else ours.total
            b = bench.annualised if bench.is_annualised else bench.total
            rows.append((ours.label, f"{ours.start} to {ours.end}", _pct(a), _pct(b), _pct(a - b)))
        caption = "Periods over a year are annualised; the rest are cumulative."
    columns = (
        ["Year", "Portfolio", "Benchmark", "Active"]
        if yearly
        else ["Period", "Dates", "Portfolio", "Benchmark", "Active"]
    )
    numeric = [1, 2, 3] if yearly else [2, 3, 4]
    console.print(
        render_rows(
            table(
                f"{demo.accounting.portfolio.name} - time-weighted returns in USD",
                columns,
                numeric=numeric,
                caption=caption,
            ),
            rows,
        )
    )


@app.command("attribution")
def attribution(
    by: Annotated[str, typer.Option("--by", help="sector or region")] = "sector",
    start: Annotated[str | None, typer.Option("--start", help="ISO date; the period starts after this day")] = None,
    end: Annotated[str | None, typer.Option("--end", help="ISO date")] = None,
) -> None:
    """Brinson-Fachler by segment, currency and costs apart, linked by Cariño."""
    if by not in DIMENSIONS:
        fail(f"--by must be one of {', '.join(DIMENSIONS)}")
    demo = _demo()
    try:
        result = demo.attribution(by, start=_day(start), end=_day(end))
    except (MeridianError, ValueError) as error:
        fail(str(error))
    segments = sorted(result.segments, key=lambda segment: -segment.total)
    weights = [
        (
            item.segment,
            f"{item.average_wp:.1%}",
            f"{item.average_wb:.1%}",
            _pct(item.portfolio_return),
            _pct(item.benchmark_return),
        )
        for item in segments
    ]
    weights.append(("total", "", "", _pct(result.portfolio), _pct(result.benchmark)))
    console.print(
        render_rows(
            table(
                f"{by.title()} weights and local returns, {result.start} to {result.end}",
                [by.title(), "Wp", "Wb", "Rp", "Rb"],
                numeric=[1, 2, 3, 4],
                caption="Average daily weights; returns linked in local currency.",
            ),
            weights,
        )
    )
    effects: list[tuple[str, ...]] = [
        (item.segment, _bp(item.allocation), _bp(item.selection), _bp(item.interaction), _bp(item.total))
        for item in segments
    ]
    effects += [(f"currency {code}", "", "", "", _bp(value)) for code, value in sorted(result.currency.items())]
    effects.append(("costs", "", "", "", _bp(result.costs)))
    effects.append(("total", *(_bp(result.effect(name)) for name in EFFECTS), _bp(result.active)))
    console.print(
        render_rows(
            table(
                f"Attribution by {by} (bp) - active {_pct(result.active)}",
                [by.title(), "Allocation", "Selection", "Interaction", "Total"],
                numeric=[1, 2, 3, 4],
                caption=f"Residual {result.residual:.1e}; unlinked they would miss by {_bp(result.linking_gap)} bp.",
            ),
            effects,
        )
    )


@app.command("risk")
def risk() -> None:
    """Risk and risk-adjusted return since inception, and the deepest drawdowns."""
    demo = _demo()
    console.print(
        render_rows(
            table("Risk since inception", ["Measure", "Portfolio", "Benchmark"], numeric=[1, 2]),
            summary_rows(demo.portfolio_returns, demo.benchmark_returns),
        )
    )
    rows = [
        (f"#{rank}", f"{item.depth:.1%}", item.peak, item.trough, item.recovery or "not yet", item.length)
        for rank, item in enumerate(drawdown_episodes(demo.portfolio_returns, 5), start=1)
    ]
    console.print(
        render_rows(
            table("Deepest drawdowns", ["", "Depth", "Peak", "Trough", "Recovered", "Days"], numeric=[1, 5]), rows
        )
    )


@app.command("contributions")
def contributions() -> None:
    """Each holding's contribution to the time-weighted return, linked so the column adds up."""
    demo = _demo()
    found = holding_contributions(demo.portfolio_days)
    rows = [(key, _pct(value)) for key, value in sorted(found.items(), key=lambda item: -item[1])]
    rows.append(("total", _pct(sum(found.values()))))
    console.print(
        render_rows(
            table(
                f"Contribution to the {_pct(demo.portfolio_returns.total())} time-weighted return",
                ["Holding", "Contribution"],
                numeric=[1],
            ),
            rows,
        )
    )


@app.command("factsheet")
def factsheet(
    out: Annotated[Path, typer.Option("--out", help="Where to write the PNG")] = Path("factsheet.png"),
) -> None:
    """Draw the one-page performance report."""
    from ..performance_gallery import factsheet_chart

    save_figure(factsheet_chart(), out)
    success(f"wrote {out}")


@app.command("stored")
def stored(
    by: Annotated[str, typer.Option("--by", help="sector or region")] = "sector",
) -> None:
    """Read the stored attribution back from the database (after run --persist)."""
    if by not in DIMENSIONS:
        fail(f"--by must be one of {', '.join(DIMENSIONS)}")
    portfolio_id = _demo().accounting.portfolio.portfolio_id
    database = Database(get_settings())
    try:
        with database.session() as session:
            repository = UnitOfWork(session).performance
            effects = repository.effects(portfolio_id, by)
            if not effects:
                fail("nothing stored yet - run `meridian perf run --persist` first")
            periods = sorted({(row.period_start, row.period_end) for row in effects})
            rows = []
            for first, last in periods:
                chosen = [row for row in effects if (row.period_start, row.period_end) == (first, last)]
                portfolio, benchmark = repository.linked(portfolio_id, first, last)
                explained = sum(
                    row.allocation + row.selection + row.interaction + row.currency + row.costs for row in chosen
                )
                rows.append(
                    (
                        f"{first} to {last}",
                        _pct(portfolio),
                        _pct(benchmark),
                        _bp(portfolio - benchmark),
                        _bp(explained),
                        f"{explained - (portfolio - benchmark):.1e}",
                    )
                )
    finally:
        database.dispose()
    console.print(
        render_rows(
            table(
                f"Stored attribution by {by}, from the database",
                ["Period", "Portfolio", "Benchmark", "Active bp", "Explained bp", "Gap"],
                numeric=[1, 2, 3, 4, 5],
                caption="Returns relinked in Python from the stored daily rows; effects summed from the stored rows.",
            ),
            rows,
        )
    )
