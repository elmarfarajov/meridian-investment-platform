"""``meridian calendar`` - inspect the trading calendars and draw them."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from ..core.calendars import BusinessDayConvention, available_calendars, get_calendar
from ..core.exceptions import CalendarError
from ..viz.calendars import divergent_days, plot_trading_calendar
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(help="Trading calendars: holidays, business days and settlement dates.", no_args_is_help=True)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@app.command("list")
def list_calendars() -> None:
    """List the calendars the platform knows about."""
    rows = []
    for name in available_calendars():
        calendar = get_calendar(name)
        rows.append((name, calendar.name, calendar.timezone, len(calendar.holidays(date.today().year))))
    console.print(
        render_rows(
            table(
                "Available calendars",
                ["Alias", "Calendar", "Timezone", "Holidays this year"],
                caption="Holidays are derived from statutory rules, not from a file that can go stale.",
                numeric=[3],
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
    days = sorted(calendar.holidays(year))
    rows = [(day.isoformat(), WEEKDAYS[day.weekday()]) for day in days]
    console.print(
        render_rows(
            table(f"{calendar.name} holidays, {year}", ["Date", "Weekday"], caption=f"{len(days)} closures"),
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
