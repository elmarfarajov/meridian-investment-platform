"""``meridian compliance`` - the mandate, checked, from the command line.

``rules`` lists the account's investment restrictions as written; ``parse``
checks a rule's syntax before it goes into a mandate; ``check`` runs the
mandate on a day; ``pretrade`` tests an order before it is sent; ``breaches``
shows the register; ``replay`` puts the book's own history through the
pre-trade check it never had; ``ucits`` asks whether the account would
qualify as a UCITS fund. ``run --persist`` stores the rules, every day's
results, the register and the pre-trade decisions.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from ..compliance.language import Rule, bound_text, measure_text, to_text
from ..compliance.parser import parse_rule
from ..compliance.pretrade import Order
from ..config import get_settings
from ..core.exceptions import ValidationError
from ..persistence import Database, UnitOfWork
from ..services.compliance_run import run_demo_compliance
from ..services.demo_compliance import DemoCompliance, build_demo_compliance
from ..viz.style import save_figure
from ._common import console, fail, render_rows, success, table

app = typer.Typer(
    help="Compliance: the mandate as rules, checked every day and before every order, and the breach register.",
    no_args_is_help=True,
)

STATUS_STYLE = {"pass": "good", "warning": "highlight", "breach": "bad", "not evaluable": "muted"}


def _demo() -> DemoCompliance:
    logging.getLogger().setLevel(logging.WARNING)
    return build_demo_compliance()


def _value(value: float | None, percent: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value:.2%}" if percent else f"{value:,.0f}"


@app.command("rules")
def rules() -> None:
    """The account's investment restrictions, as written."""
    demo = _demo()
    mandate = demo.mandate
    rows = [(rule.rule_id, rule.severity, rule.name, measure_text(rule.measure)) for rule in mandate.rules]
    console.print(
        render_rows(
            table(
                f"{mandate.name}, version {mandate.version}, effective {mandate.effective}",
                ["Rule", "Severity", "Title", "Measure"],
                caption="Hard limits block a trade; soft limits need a recorded override.",
            ),
            rows,
        )
    )


@app.command("parse")
def parse(
    text: Annotated[str, typer.Argument(help="A rule, e.g. 'rule cap hard weight where sector = \"Energy\" <= 5%'")],
) -> None:
    """Check a rule's syntax and show it as the engine reads it."""
    try:
        rule = parse_rule(text)
    except ValidationError as error:
        fail(str(error))
    console.print(to_text(rule))
    success(f"{rule.rule_id}: a {rule.severity} rule on {type(rule.measure).__name__}")


@app.command("check")
def check_day(
    as_of: Annotated[str | None, typer.Option("--as-of", help="ISO date; the last day by default")] = None,
) -> None:
    """Every rule on one day: value, limit, utilisation and status."""
    demo = _demo()
    if as_of is None:
        report = demo.today
    else:
        try:
            day = date.fromisoformat(as_of)
        except ValueError:
            fail(f"{as_of!r} is not an ISO date (YYYY-MM-DD)")
        days = [report.day for report in demo.history.reports]
        if day not in days:
            fail(f"{day} is not a checked day ({days[0]} to {days[-1]}, business days)")
        report = demo.history.reports[days.index(day)]
    rows = []
    for result in report.results:
        rule = result.rule
        style = STATUS_STYLE[result.status]
        percent = type(rule.measure).__name__ != "CountOf"
        rows.append(
            (
                rule.rule_id,
                rule.severity,
                _value(result.value, percent),
                _bound(rule),
                "-" if result.utilisation is None else f"{result.utilisation:.0%}",
                result.group or (result.contributors[0][0] if result.contributors else ""),
                f"[{style}]{result.status}[/{style}]",
            )
        )
    counts = ", ".join(f"{report.count(status)} {status}" for status in STATUS_STYLE if report.count(status))
    console.print(
        render_rows(
            table(
                f"Compliance on {report.day}: {counts}",
                ["Rule", "Severity", "Value", "Limit", "Used", "Largest part", "Status"],
                numeric=[2, 4],
            ),
            rows,
        )
    )


def _bound(rule: Rule) -> str:
    text = bound_text(rule)
    return text if text else "= 0"


@app.command("pretrade")
def pretrade(
    instrument: Annotated[str, typer.Argument(help="Instrument id, e.g. US-MSFT")],
    amount: Annotated[float, typer.Argument(help="Order size in US dollars")],
    side: Annotated[str, typer.Option("--side", help="buy or sell")] = "buy",
) -> None:
    """Test an order against the mandate before it is sent, and find the largest that fits."""
    demo = _demo()
    try:
        decision = demo.pretrade.check(Order("CLI-ORDER", instrument, side, amount))
    except (ValidationError, KeyError) as error:
        fail(str(error))
    colour = {"allowed": "good", "warning": "highlight", "override required": "highlight", "blocked": "bad"}[
        decision.decision
    ]
    rows = [
        (
            change.rule_id,
            change.after.rule.severity,
            _value(change.before.value),
            _value(change.after.value),
            change.effect,
        )
        for change in decision.reasons
    ]
    console.print(
        render_rows(
            table(
                f"{side} {amount:,.0f} USD of {instrument}: {decision.decision}",
                ["Rule", "Severity", "Before", "After", "Effect"],
                numeric=[2, 3],
                caption="Only rules the order would change are listed.",
            ),
            rows or [("-", "", "", "", "no rule changes")],
        )
    )
    console.print(
        f"[{colour}]{decision.decision}[/{colour}] - the largest order within every hard limit is "
        f"{decision.maximum:,.0f} USD"
    )


@app.command("breaches")
def breaches(open_only: Annotated[bool, typer.Option("--open", help="Only breaches still open")] = False) -> None:
    """The breach register: when each opened and closed, active or passive, and how it ended."""
    demo = _demo()
    last = demo.today.day
    rows = [
        (
            breach.breach_id,
            breach.rule_id,
            f"{breach.severity}/{breach.grade}",
            breach.kind,
            breach.opened,
            breach.closed or "-",
            breach.days,
            f"{breach.peak_utilisation:.0%}",
            breach.state(last),
        )
        for breach in demo.breaches
        if not open_only or breach.closed is None
    ]
    console.print(
        render_rows(
            table(
                f"Breach register, {len(rows)} breaches",
                ["Id", "Rule", "Severity", "Cause", "Opened", "Closed", "Days", "Peak", "State"],
                numeric=[6, 7],
                caption="Active: a trade since the previous check touched the breach. Passive: the market moved.",
            ),
            rows or [("-", "no breaches", "", "", "", "", "", "", "")],
        )
    )


@app.command("replay")
def replay() -> None:
    """The book's own trades, put through the pre-trade check - one at a time and as each day's basket."""
    demo = _demo()
    rows = [
        (
            item.day,
            item.order.side,
            item.order.instrument_id,
            f"{item.order.amount:,.0f}",
            item.decision,
            item.basket_decision,
        )
        for item in demo.replayed
        if item.decision != "allowed" or item.basket_decision != "allowed"
    ]
    console.print(
        render_rows(
            table(
                f"{len(demo.replayed)} historical orders; those the check would have questioned",
                ["Day", "Side", "Instrument", "USD", "On its own", "With the day's basket"],
                numeric=[3],
                caption="Checked against the portfolio of the evening before; a rebalance is judged as a whole.",
            ),
            rows,
        )
    )


@app.command("ucits")
def ucits() -> None:
    """Would the account qualify as a UCITS fund? The directive's diversification rules, today."""
    demo = _demo()
    report = demo.ucits.reports[-1]
    rows = [(r.rule.name, _value(r.value), _bound(r.rule), r.status) for r in report.results]
    console.print(
        render_rows(table(f"UCITS eligibility screen on {report.day}", ["Rule", "Value", "Limit", "Status"]), rows)
    )


@app.command("report")
def report(
    out: Annotated[Path, typer.Option("--out", help="Where to write the PNG")] = Path("compliance-report.png"),
) -> None:
    """Draw the one-page compliance report."""
    from ..compliance_gallery import report_chart

    save_figure(report_chart(), out)
    success(f"wrote {out}")


@app.command("run")
def run(
    persist: Annotated[bool, typer.Option("--persist/--dry-run", help="Write rules, results and the register")] = False,
) -> None:
    """Check the controls and, with --persist, store the rules, every day's results, the register and the orders."""
    demo = _demo()
    if not persist:
        result = run_demo_compliance(demo)
    else:
        database = Database(get_settings()).create_all()
        try:
            with database.session() as session:
                unit_of_work = UnitOfWork(session)
                result = run_demo_compliance(demo, unit_of_work)
                unit_of_work.commit()
        finally:
            database.dispose()
    console.print(render_rows(table("Compliance run", ["Step", "Result"]), result.summary_rows()))
    if persist:
        success("rules, results, breaches and pre-trade decisions stored")


@app.command("stored")
def stored() -> None:
    """Read the register and today's status counts back from the database (after run --persist)."""
    database = Database(get_settings())
    try:
        with database.session() as session:
            repository = UnitOfWork(session).compliance
            register = repository.breaches("PF-GLOBAL-EQ")
            if not register:
                fail("nothing stored yet - run `meridian compliance run --persist` first")
            counts = repository.status_counts("PF-GLOBAL-EQ")
            days = repository.breach_days("PF-GLOBAL-EQ")
    finally:
        database.dispose()
    rows = [(f"results: {status}", f"{count:,}") for status, count in sorted(counts.items())]
    rows += [(f"days in breach: {kind}, {severity}", f"{total:,}") for (kind, severity), total in sorted(days.items())]
    rows.append(("breaches in the register", f"{len(register)}"))
    console.print(render_rows(table("Recounted from the database", ["Measure", "Value"], numeric=[1]), rows))
