"""``meridian rates`` - curves, bonds, schedules and day counts from the command line."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from ..analytics.bonds import FixedRateBond
from ..analytics.curves import YieldCurve, bootstrap_par_curve, tenor_label
from ..core.compounding import Compounding, compounding_comparison
from ..core.daycount import DayCountConvention, compare_conventions
from ..core.enums import Frequency
from ..core.exceptions import MeridianError
from ..core.schedules import StubConvention, generate_schedule
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(help="Interest rates: curves, bond analytics, schedules and day counts.", no_args_is_help=True)

DEFAULT_TENORS = "0.25,0.5,1,2,3,5,7,10,20,30"
DEFAULT_PARS = "4.25,4.32,4.18,3.95,3.88,3.90,4.02,4.15,4.48,4.55"


def _parse_floats(raw: str, what: str) -> list[float]:
    try:
        return [float(item) for item in raw.split(",") if item.strip()]
    except ValueError:
        fail(f"could not read {what} from {raw!r}; expected comma-separated numbers")


def _build_curve(tenors: str, pars: str, valuation: date) -> YieldCurve:
    years = _parse_floats(tenors, "tenors")
    rates = [value / 100 for value in _parse_floats(pars, "par rates")]
    if len(years) != len(rates):
        fail(f"{len(years)} tenors but {len(rates)} par rates")
    try:
        return bootstrap_par_curve(valuation, years, rates, name="par curve")
    except MeridianError as error:
        fail(str(error))


@app.command("curve")
def curve(
    tenors: Annotated[str, typer.Option("--tenors", help="Comma-separated tenors in years")] = DEFAULT_TENORS,
    pars: Annotated[str, typer.Option("--par", help="Comma-separated par yields in percent")] = DEFAULT_PARS,
    valuation: Annotated[
        datetime | None, typer.Option("--valuation", formats=["%Y-%m-%d"], help="Valuation date")
    ] = None,
    chart: Annotated[Path | None, typer.Option("--chart", help="Also write the curve chart here")] = None,
) -> None:
    """Bootstrap a zero curve from par yields and show what it implies."""
    valuation_date = valuation.date() if valuation else date.today()
    built = _build_curve(tenors, pars, valuation_date)

    rows = []
    for point in built.points():
        par = built.par_rate(point.years)
        forward = built.forward_rate(point.years, point.years + 1) if point.years + 1 <= built.years[-1] else None
        rows.append(
            (
                point.label,
                f"{par * 100:.4f}%",
                f"{point.rate * 100:.4f}%",
                f"{built.discount_factor(point.years):.6f}",
                f"{forward * 100:.4f}%" if forward else "-",
            )
        )
    console.print(
        render_rows(
            table(
                f"Zero curve bootstrapped at {valuation_date.isoformat()}",
                ["Tenor", "Par", "Zero", "Discount factor", "1y forward"],
                caption="Each pillar is solved so that a par bond of that maturity prices to exactly 100.",
                numeric=[1, 2, 3, 4],
            ),
            rows,
        )
    )
    if chart:
        from ..viz.rates import plot_yield_curve

        success(f"wrote {save_figure(plot_yield_curve(built), chart)}")


@app.command("bond")
def bond(
    maturity: Annotated[datetime, typer.Argument(formats=["%Y-%m-%d"], help="Maturity date")],
    coupon: Annotated[float, typer.Option("--coupon", "-c", help="Annual coupon in percent")] = 4.0,
    issue: Annotated[datetime | None, typer.Option("--issue", formats=["%Y-%m-%d"], help="Issue date")] = None,
    settlement: Annotated[
        datetime | None, typer.Option("--settlement", "-s", formats=["%Y-%m-%d"], help="Settlement date")
    ] = None,
    price: Annotated[float | None, typer.Option("--price", "-p", help="Clean price, to solve for the yield")] = None,
    ytm: Annotated[float | None, typer.Option("--ytm", "-y", help="Yield in percent, to solve for the price")] = None,
    frequency: Annotated[int, typer.Option("--frequency", "-f", help="Coupons a year")] = 2,
    day_count: Annotated[str, typer.Option("--day-count", help="Day count convention")] = "30/360 US",
    chart: Annotated[Path | None, typer.Option("--chart", help="Write the price-yield chart here")] = None,
) -> None:
    """Price a bond, solve its yield, and show duration, convexity and DV01."""
    maturity_date = maturity.date()
    settlement_date = settlement.date() if settlement else date.today()
    issue_date = issue.date() if issue else date(settlement_date.year - 2, maturity_date.month, maturity_date.day)
    frequency_map = {1: Frequency.ANNUAL, 2: Frequency.SEMI_ANNUAL, 4: Frequency.QUARTERLY, 12: Frequency.MONTHLY}
    if frequency not in frequency_map:
        fail(f"{frequency} coupons a year is not supported; use 1, 2, 4 or 12")

    try:
        instrument = FixedRateBond.create(
            issue_date=issue_date,
            maturity=maturity_date,
            coupon_rate=coupon / 100,
            frequency=frequency_map[frequency],
            day_count=DayCountConvention(day_count),
            name=f"{coupon:g}% {maturity_date.isoformat()}",
        )
        if price is not None:
            rate = instrument.yield_to_maturity(price, settlement_date)
            clean = price
        else:
            rate = (ytm if ytm is not None else coupon) / 100
            clean = instrument.clean_price_from_yield(rate, settlement_date)
        accrued = instrument.accrued_interest(settlement_date)
        days, period_days = instrument.days_accrued(settlement_date)
        rows = [
            ("Clean price", f"{clean:.6f}"),
            ("Accrued interest", f"{accrued:.6f}  ({days}/{period_days} days)"),
            ("Dirty price", f"{clean + accrued:.6f}"),
            ("Yield to maturity", f"{rate * 100:.6f}%"),
            ("Macaulay duration", f"{instrument.macaulay_duration(rate, settlement_date):.6f} years"),
            ("Modified duration", f"{instrument.modified_duration(rate, settlement_date):.6f}"),
            ("Convexity", f"{instrument.convexity(rate, settlement_date):.4f}"),
            ("DV01 per 100 face", f"{instrument.dv01(rate, settlement_date):.6f}"),
            ("Remaining cash flows", str(len(instrument.cash_flows(settlement_date)))),
        ]
    except MeridianError as error:
        fail(str(error))

    console.print(
        render_rows(
            table(
                f"{instrument.name} settled {settlement_date.isoformat()}",
                ["Measure", "Value"],
                caption=f"{frequency} coupons a year on {day_count}, calendar {instrument.schedule.calendar_name}.",
                numeric=[1],
            ),
            rows,
        )
    )
    actual, linear, quadratic = instrument.price_change_estimate(rate, settlement_date, 100)
    console.print(
        f"[muted]+100bp: actual {actual:+.4f}, duration only {linear:+.4f}, with convexity {quadratic:+.4f}[/muted]"
    )
    if chart:
        from ..viz.rates import plot_price_yield

        success(f"wrote {save_figure(plot_price_yield(instrument, settlement_date, rate), chart)}")


@app.command("schedule")
def schedule(
    start: Annotated[datetime, typer.Argument(formats=["%Y-%m-%d"], help="First accrual date")],
    end: Annotated[datetime, typer.Argument(formats=["%Y-%m-%d"], help="Maturity")],
    frequency: Annotated[str, typer.Option("--frequency", "-f")] = "semi_annual",
    calendar: Annotated[str, typer.Option("--calendar", "-c")] = "SIFMA",
    stub: Annotated[str, typer.Option("--stub")] = "short_front",
    chart: Annotated[Path | None, typer.Option("--chart", help="Write the schedule chart here")] = None,
) -> None:
    """Generate a payment schedule and show where the business-day rules moved a date."""
    try:
        built = generate_schedule(
            start.date(),
            end.date(),
            Frequency(frequency),
            calendar=calendar,
            stub=StubConvention(stub),
        )
    except (MeridianError, ValueError) as error:
        fail(str(error))

    rows = [
        (
            str(period.index + 1),
            period.start.isoformat(),
            period.end.isoformat(),
            period.payment_date.isoformat(),
            str(period.days),
            "stub" if period.is_stub else ("moved" if period.payment_date != period.end else ""),
        )
        for period in built
    ]
    console.print(
        render_rows(
            table(
                built.describe(),
                ["#", "Accrual start", "Accrual end", "Payment", "Days", "Note"],
                caption=f"Rolled backwards from {built.end.isoformat()} on the {built.roll.value} rule.",
                numeric=[0, 4],
            ),
            rows,
        )
    )
    if chart:
        from ..viz.cashflows import plot_schedule

        success(f"wrote {save_figure(plot_schedule(built), chart)}")


@app.command("daycount")
def daycount(
    start: Annotated[datetime, typer.Argument(formats=["%Y-%m-%d"])],
    end: Annotated[datetime, typer.Argument(formats=["%Y-%m-%d"])],
    notional: Annotated[int, typer.Option("--notional", "-n")] = 10_000_000,
    rate: Annotated[float, typer.Option("--rate", "-r", help="Annual rate in percent")] = 5.0,
) -> None:
    """Compare every day-count convention over the same period."""
    results = compare_conventions(start.date(), end.date(), notional=notional, annual_rate=str(rate / 100))
    rows = [
        (convention.value, f"{float(fraction):.8f}", convention.denominator_label, f"{float(accrued):,.2f}")
        for convention, (fraction, accrued) in results.items()
    ]
    spread = max(float(accrued) for _, accrued in results.values()) - min(
        float(accrued) for _, accrued in results.values()
    )
    console.print(
        render_rows(
            table(
                f"{start.date().isoformat()} to {end.date().isoformat()}",
                ["Convention", "Year fraction", "Denominator", f"Interest on {notional:,}"],
                caption=f"{spread:,.2f} between the highest and the lowest convention.",
                numeric=[1, 3],
            ),
            rows,
        )
    )


@app.command("compounding")
def compounding(
    rate: Annotated[float, typer.Option("--rate", "-r", help="Nominal rate in percent")] = 5.0,
    years: Annotated[float, typer.Option("--years", "-y")] = 10.0,
) -> None:
    """Show what the compounding convention does to the same quoted rate."""
    rows = [
        (convention.value.replace("_", " "), f"{factor:.8f}", f"{effective * 100:.6f}%")
        for convention, (factor, effective) in compounding_comparison(rate / 100, years).items()
    ]
    console.print(
        render_rows(
            table(
                f"{rate:g}% over {years:g} years",
                ["Compounding", "Discount factor", "Effective annual"],
                caption="The same nominal rate is a different amount of money under each convention.",
                numeric=[1, 2],
            ),
            rows,
        )
    )
    spread = max(factor for factor, _ in compounding_comparison(rate / 100, years).values()) - min(
        factor for factor, _ in compounding_comparison(rate / 100, years).values()
    )
    console.print(f"[muted]{spread * 100:.2f} cents in the unit between simple and continuous[/muted]")


@app.command("forward")
def forward(
    near: Annotated[float, typer.Argument(help="Near horizon in years")],
    far: Annotated[float, typer.Argument(help="Far horizon in years")],
    tenors: Annotated[str, typer.Option("--tenors")] = DEFAULT_TENORS,
    pars: Annotated[str, typer.Option("--par")] = DEFAULT_PARS,
) -> None:
    """The forward rate the curve implies between two horizons."""
    built = _build_curve(tenors, pars, date.today())
    try:
        rate = built.forward_rate(near, far, Compounding.SEMI_ANNUAL)
    except MeridianError as error:
        fail(str(error))
    console.print(
        f"[key]{tenor_label(near)} into {tenor_label(far - near)}[/key]: "
        f"[key]{rate * 100:.4f}%[/key] [muted](semi-annual)[/muted]"
    )
