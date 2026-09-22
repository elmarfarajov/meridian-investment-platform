"""``meridian market`` - the end-of-day pricing desk from the command line.

Every command runs against the demonstration market, which is deterministic,
so the numbers an operator sees here are the numbers the documentation shows.
``price --persist`` writes the run into the configured database, after which
``history`` reads point-in-time observations back out of it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Annotated

import typer

from ..config import get_settings
from ..domain.corporate_actions import AdjustmentMode
from ..marketdata.adjustments import adjust_history, adjustment_factors
from ..persistence import Database, UnitOfWork, seed_reference_data
from ..quality.findings import Severity
from ..quality.rules import rule_catalogue
from ..seed import demo_book
from ..services import build_demo_market, demo_quality_report, demo_reference_data, run_demo_pricing
from ..viz.quality import findings_table, plot_quality_dashboard
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(
    help="Market data: pricing runs, quality checks, corporate actions and identifiers.", no_args_is_help=True
)


def _quiet() -> None:
    """The pricing service logs each step; at the terminal the tables say the same thing more clearly."""
    logging.getLogger().setLevel(logging.WARNING)


@app.command("rules")
def rules() -> None:
    """List every quality rule with the dimension it reports on."""
    console.print(render_rows(table("Quality rules", ["Rule", "Dimension", "Checks for"]), rule_catalogue()))


@app.command("quality")
def quality(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Findings to list")] = 15,
    chart: Annotated[Path | None, typer.Option("--chart", help="Also write the dashboard chart here")] = None,
) -> None:
    """Run the quality engine over the demonstration exchange feed and show the verdict."""
    report = demo_quality_report(build_demo_market())
    console.print(
        render_rows(
            table(
                f"Quality by series ({report.overall:.2%} overall)",
                ["Series", "Source", "Observed", "Expected", "Coverage", "Score", "Errors", "Warnings"],
                numeric=[2, 3, 4, 5, 6, 7],
            ),
            report.summary_rows(),
        )
    )
    severities = report.by_severity()
    console.print(
        render_rows(
            table(
                f"Findings: {severities[Severity.CRITICAL]} critical, {severities[Severity.ERROR]} errors, "
                f"{severities[Severity.WARNING]} warnings",
                ["Series", "Date", "Rule", "Severity", "Detail"],
            ),
            findings_table(report.findings, limit),
        )
    )
    if chart is not None:
        success(f"wrote {save_figure(plot_quality_dashboard(report), chart)}")


@app.command("price")
def price(
    persist: Annotated[bool, typer.Option("--persist/--dry-run", help="Write the run to the database")] = False,
) -> None:
    """Run the end-of-day pricing process: collect, record, validate, reconcile, publish."""
    _quiet()
    market = build_demo_market()
    if not persist:
        result = run_demo_pricing(market)
    else:
        settings = get_settings()
        database = Database(settings).create_all()
        try:
            with database.session() as session:
                unit_of_work = UnitOfWork(session)
                book = demo_book()
                seed_reference_data(
                    unit_of_work,
                    instruments=book.instruments,
                    benchmarks=book.benchmarks,
                    clients=book.clients,
                    households=book.households,
                    accounts=book.accounts,
                    portfolios=book.portfolios,
                )
                result = run_demo_pricing(market, unit_of_work=unit_of_work, backfill=True)
                unit_of_work.corporate_actions.add_all(market.actions)
                unit_of_work.xref.save(demo_reference_data())
        finally:
            database.dispose()
    console.print(render_rows(table("End-of-day pricing run", ["Step", "Result"]), result.summary()))
    challenges = [
        (item.instrument_id, item.day.isoformat(), item.source, str(item.value), item.reason)
        for item in result.golden.challenges()[:10]
    ]
    if challenges:
        console.print(
            render_rows(table("First price challenges", ["Instrument", "Date", "Chosen", "Price", "Why"]), challenges)
        )


@app.command("history")
def history(
    instrument: Annotated[str, typer.Argument(help="Instrument id, e.g. US-AAPL")],
    known_at: Annotated[
        str | None, typer.Option("--known-at", help="ISO date: the series as known that evening")
    ] = None,
    source: Annotated[str | None, typer.Option("--source")] = None,
    tail: Annotated[int, typer.Option("--tail")] = 10,
) -> None:
    """Read raw observations back as they were known at a past moment (after ``price --persist``)."""
    moment = None
    if known_at:
        moment = datetime.combine(date.fromisoformat(known_at), time(23, 59), tzinfo=timezone.utc)
    database = Database(get_settings())
    try:
        with database.session() as session:
            series = UnitOfWork(session).observations.as_known_at(instrument, moment, source=source)
    finally:
        database.dispose()
    if not series:
        if moment is not None:
            fail(f"nothing about {instrument} was known by the evening of {known_at}")
        fail(f"no observations for {instrument}; run `meridian market price --persist` first")
    rows = [(point.day.isoformat(), f"{point.value.normalize():f}") for point in list(series)[-tail:]]
    label = f"as known at {known_at}" if known_at else "as known now"
    console.print(render_rows(table(f"{instrument} {label}", ["Date", "Close"], numeric=[1]), rows))


@app.command("actions")
def actions(instrument: Annotated[str | None, typer.Option("--instrument")] = None) -> None:
    """The corporate actions in the demonstration market, with their price factors."""
    market = build_demo_market()
    rows = []
    for action in market.actions:
        if instrument and action.instrument_id != instrument:
            continue
        series = market.clean.close_series(action.instrument_id)
        factors = adjustment_factors(series, [action], AdjustmentMode.TOTAL_RETURN)
        factor = f"{factors[0].factor:.6f}" if factors else "-"
        rows.append(
            (action.ex_date.isoformat(), action.instrument_id, action.action_type.value, factor, action.describe())
        )
    console.print(render_rows(table("Corporate actions", ["Ex-date", "Instrument", "Type", "Factor", "Terms"]), rows))


@app.command("adjust")
def adjust(
    instrument: Annotated[str, typer.Argument()] = "DEMO-SPLIT",
    tail: Annotated[int, typer.Option("--tail")] = 8,
) -> None:
    """Raw against back-adjusted closes around the instrument's corporate actions."""
    market = build_demo_market()
    raw = market.clean.close_series(instrument)
    if not raw:
        fail(f"no prices for {instrument}")
    capital = adjust_history(raw, market.actions, AdjustmentMode.CAPITAL, instrument_id=instrument)
    total = adjust_history(raw, market.actions, AdjustmentMode.TOTAL_RETURN, instrument_id=instrument)
    events = [action.ex_date for action in market.actions if action.instrument_id == instrument]
    days = sorted({day for event in events for day in raw.days if abs((day - event).days) <= 3})[-tail * 2 :]
    rows = [
        (day.isoformat(), str(raw[day]), f"{capital[day]:.4f}", f"{total[day]:.4f}", "ex" if day in events else "")
        for day in days or raw.days[-tail:]
    ]
    console.print(
        render_rows(
            table(f"{instrument}: raw and adjusted", ["Date", "Raw", "Capital", "Total return", ""], numeric=[1, 2, 3]),
            rows,
        )
    )


@app.command("xref")
def xref(
    value: Annotated[str, typer.Argument(help="Any identifier: ticker, ISIN, CUSIP, SEDOL")],
    on: Annotated[str, typer.Option("--on", help="ISO date to resolve on")] = date.today().isoformat(),
) -> None:
    """Resolve an identifier as of a date, and show everything it has ever meant."""
    reference = demo_reference_data()
    day = date.fromisoformat(on)
    found = reference.resolve_any(value, day)
    if found:
        for scheme, instrument in found:
            console.print(f"[key]{value.upper()}[/key] ({scheme.value}) on {day} -> [good]{instrument}[/good]")
    else:
        console.print(f"[key]{value.upper()}[/key] identified nothing on {day}")
    rows = [
        (
            entry.scheme.value,
            entry.instrument_id,
            entry.valid_from.isoformat(),
            "open" if entry.is_open else str(entry.valid_to),
        )
        for entry in reference.entries()
        if entry.value == value.strip().upper()
    ]
    if rows:
        console.print(render_rows(table("History", ["Scheme", "Instrument", "From", "Until"]), rows))
