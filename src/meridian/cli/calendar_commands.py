"""``meridian calendar`` - inspect the trading calendars and draw them."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from ..core.calendars import (
    BusinessDayConvention,
    JointCalendar,
    available_calendars,
    calendar_aliases,
    get_calendar,
)
from ..core.exceptions import CalendarError
from ..viz.calendars import divergent_days, plot_divergence_matrix, plot_settlement_ladder, plot_trading_calendar
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(help="Trading calendars: holidays, business days and settlement dates.", no_args_is_help=True)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@app.command("list")
def list_calendars() -> None:
    """List the calendars the platform knows about."""
    aliases: dict[str, list[str]] = {}
    for alias, target in calendar_aliases().items():
        aliases.setdefault(target, []).append(alias)
    rows = []
    for name in available_calendars():
        calendar = get_calendar(name)
        rows.append(
            (
                name,
                calendar.description,
                calendar.timezone,
                ", ".join(sorted(aliases.get(name, []))) or "-",
                len(calendar.holidays(date.today().year)),
            )
        )
    console.print(
        render_rows(
            table(
                "Available calendars",
                ["Code", "Market", "Timezone", "Aliases", "Holidays this year"],
                caption="Holidays are derived from statutory rules, not from a file that can go stale. "
                "Join calendars with a plus, e.g. XNYS+XTKS.",
                numeric=[4],
            ),
            rows,
        )
    )


@app.command("holidays")
def holidays(
    name: Annotated[str, typer.Argument(help="Calendar name or alias, e.g. XNYS, XLON, TARGET")],
    year: Annotated[int, typer.Option("--year", "-y", help="Calendar year")] = date.today().year,
) -> None:
    """Show every market holiday for one calendar and year."""
    try:
        calendar = get_calendar(name)
    except (CalendarError, KeyError):
        fail(f"unknown calendar {name!r}; try one of {', '.join(available_calendars())}")
    holidays_found = calendar.named_holidays_between(date(year, 1, 1), date(year, 12, 31))
    rows = [
        (
            holiday.day.isoformat(),
            WEEKDAYS[holiday.day.weekday()],
            holiday.name,
            "weekend" if holiday.day.weekday() >= 5 else "",
        )
        for holiday in holidays_found
    ]
    console.print(
        render_rows(
            table(
                f"{calendar.description} holidays, {year}",
                ["Date", "Weekday", "Holiday", "Note"],
                caption=f"{len(holidays_found)} closures, computed from the statutory rules",
            ),
            rows,
        )
    )


@app.command("settle")
def settle(
    trade_date: Annotated[datetime, typer.Argument(help="Trade date, YYYY-MM-DD", formats=["%Y-%m-%d"])],
    name: Annotated[str, typer.Option("--calendar", "-c", help="Calendar name or alias")] = "XNYS",
    days: Annotated[int, typer.Option("--days", "-d", help="Settlement cycle, e.g. 1 for T+1")] = 1,
) -> None:
    """Work out a settlement date, skipping weekends and market holidays."""
    calendar = get_calendar(name)
    traded = trade_date.date()
    settlement = calendar.add_business_days(traded, days)
    skipped = (settlement - traded).days - days
    console.print(
        f"[key]{calendar.name}[/key]  T+{days}: "
        f"{traded.isoformat()} ({WEEKDAYS[traded.weekday()]}) -> "
        f"[key]{settlement.isoformat()}[/key] ({WEEKDAYS[settlement.weekday()]})"
    )
    if skipped:
        console.print(f"[muted]{skipped} non-business day(s) skipped[/muted]")
    adjusted = calendar.adjust(traded, BusinessDayConvention.MODIFIED_FOLLOWING)
    if adjusted != traded:
        console.print(f"[muted]trade date itself is not a business day; modified following gives {adjusted}[/muted]")


@app.command("chart")
def chart(
    year: Annotated[int, typer.Option("--year", "-y", help="Calendar year")] = date.today().year,
    calendars: Annotated[
        str, typer.Option("--calendars", "-c", help="Comma-separated calendar names")
    ] = "XNYS,XLON,TARGET",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Output PNG path")] = None,
) -> None:
    """Draw the year's trading calendars, the holidays and the days markets disagree."""
    names = tuple(item.strip() for item in calendars.split(",") if item.strip())
    if not names:
        fail("no calendars given")
    try:
        figure = plot_trading_calendar(year, names)
    except (CalendarError, KeyError) as error:
        fail(str(error))
    destination = out or Path("reports") / f"trading-calendar-{year}.png"
    path = save_figure(figure, destination)
    divergences = divergent_days([get_calendar(item) for item in names], year)
    success(f"wrote {path}")
    console.print(
        f"[muted]{len(divergences)} weekday(s) in {year} when one of these markets trades and another is shut[/muted]"
    )


@app.command("matrix")
def matrix(
    year: Annotated[int, typer.Option("--year", "-y")] = date.today().year,
    calendars: Annotated[str, typer.Option("--calendars", "-c")] = "XNYS,XLON,TARGET,XETR,XSWX,XTKS",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the matrix chart here")] = None,
) -> None:
    """Count, for every pair of markets, the weekdays on which only one of them trades."""
    names = [item.strip() for item in calendars.split(",") if item.strip()]
    try:
        resolved = [get_calendar(name) for name in names]
    except CalendarError as error:
        fail(str(error))
    rows = []
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            days = divergent_days([left, right], year)
            worst = days[0].isoformat() if days else "-"
            rows.append((f"{left.name} / {right.name}", len(days), worst))
    rows.sort(key=lambda row: row[1], reverse=True)
    console.print(
        render_rows(
            table(
                f"Calendar divergence, {year}",
                ["Pair", "Mismatched weekdays", "First"],
                caption="Every one of these days is a potential settlement break on a cross-border trade.",
                numeric=[1],
            ),
            rows,
        )
    )
    if out:
        success(f"wrote {save_figure(plot_divergence_matrix(year, names), out)}")


@app.command("ladder")
def ladder(
    trade_date: Annotated[datetime, typer.Argument(help="Trade date, YYYY-MM-DD", formats=["%Y-%m-%d"])],
    calendars: Annotated[str, typer.Option("--calendars", "-c")] = "XNYS,XLON,TARGET,XTKS",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the ladder chart here")] = None,
) -> None:
    """Show where T+0 to T+3 land in each market, and in the joint settlement calendar."""
    names = [item.strip() for item in calendars.split(",") if item.strip()]
    try:
        resolved = [get_calendar(name) for name in names]
    except CalendarError as error:
        fail(str(error))
    traded = trade_date.date()
    joint = JointCalendar(names)
    rows = []
    for calendar in [*resolved, joint]:
        landings = [calendar.add_business_days(traded, cycle) for cycle in (1, 2, 3)]
        rows.append(
            (
                calendar.name,
                *[f"{day.isoformat()} ({WEEKDAYS[day.weekday()][:3]})" for day in landings],
            )
        )
    console.print(
        render_rows(
            table(
                f"Settlement from {traded.isoformat()}",
                ["Calendar", "T+1", "T+2", "T+3"],
                caption="The last row is the joint calendar a cross-border trade has to clear.",
            ),
            rows,
        )
    )
    if out:
        success(f"wrote {save_figure(plot_settlement_ladder(traded, names), out)}")
