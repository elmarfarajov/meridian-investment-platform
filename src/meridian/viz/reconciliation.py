"""Charts for reconciliation against the custodian.

Two views an operations team works from:

* **The dashboard** - breaks per statement day by cause, how well each cause
  is recognised when planted where the answer is known, how long breaks stay
  open, and the value at stake.
* **One morning's statement** - the book and the custodian side by side, line
  by line, with every difference and the reason given for it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator

from ..accounting.custodian import ReconciliationScore
from ..accounting.reconciliation import Break, BreakCause, BreakKind, BreakRegister, ReconciliationReport
from .accounting import _margins, _money
from .style import PALETTE, caption, new_figure, style_axes, title_block

CAUSE_COLOURS: dict[BreakCause, str] = {
    BreakCause.FAILED_SETTLEMENT: PALETTE["navy"],
    BreakCause.DUPLICATE: PALETTE["sky"],
    BreakCause.CORPORATE_ACTION: PALETTE["violet"],
    BreakCause.TRANSPOSITION: "#9C86C0",
    BreakCause.INCOME_TIMING: PALETTE["teal"],
    BreakCause.UNBOOKED_CASH: PALETTE["slate"],
    BreakCause.PRICE_DIFFERENCE: "#7AA2CF",
    BreakCause.UNEXPLAINED: PALETTE["loss"],
}


def plot_reconciliation_dashboard(
    register: BreakRegister, score: ReconciliationScore, *, title: str = "Reconciliation against the custodian"
) -> Figure:
    """Breaks by day and cause, recall by cause against planted breaks, break lifetimes and value at stake."""
    reports = register.reports
    figure = new_figure(16.0, 9.6)
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=[1.0, 1.0],
        width_ratios=[1.45, 1.0],
        hspace=0.42,
        wspace=0.26,
        **_margins(figure, bottom=0.95),
    )

    timeline = figure.add_subplot(grid[0, :])
    days = [report.as_of for report in reports]
    bottom = np.zeros(len(days))
    for cause, colour in CAUSE_COLOURS.items():
        counts = np.array([sum(1 for item in report.breaks if item.cause is cause) for report in reports], dtype=float)
        if counts.any():
            timeline.bar(days, counts, bottom=bottom, color=colour, width=0.9, label=cause.value)
            bottom += counts
    matched = [report.match_rate for report in reports]
    twin = timeline.twinx()
    twin.plot(days, [rate * 100 for rate in matched], color=PALETTE["accent"], linewidth=0.9, alpha=0.8)
    twin.set_ylim(40, 101)
    twin.set_ylabel("lines matched (%)", color=PALETTE["accent"])
    twin.tick_params(axis="y", colors=PALETTE["accent"])
    twin.spines["right"].set_visible(True)
    twin.spines["right"].set_color(PALETTE["accent"])
    twin.grid(visible=False)
    timeline.yaxis.set_major_locator(MaxNLocator(integer=True))
    timeline.set_ylim(0, max(bottom.max(), 1) * 1.6)
    clean = sum(1 for report in reports if not report.breaks)
    style_axes(
        timeline,
        title=f"Breaks raised each morning, by the cause given ({clean} of {len(reports)} mornings had none)",
        ylabel="breaks",
    )
    timeline.legend(loc="upper left", ncol=4, fontsize=7.6)

    scorecard = figure.add_subplot(grid[1, 0])
    causes = sorted(score.causes.values(), key=lambda item: item.cause.value)
    rows = np.arange(len(causes))
    scorecard.barh(rows, [item.planted for item in causes], color=PALETTE["grid"], height=0.62, label="planted")
    scorecard.barh(
        rows,
        [item.detected for item in causes],
        color=[CAUSE_COLOURS[item.cause] for item in causes],
        height=0.36,
        label="found with the right cause",
    )
    for row, item in enumerate(causes):
        scorecard.text(item.planted + 0.4, row, f"{item.recall:.0%}", va="center", fontsize=8.5, weight="bold")
    scorecard.set_yticks(rows, labels=[item.cause.value for item in causes])
    scorecard.set_xlim(0, max((item.planted for item in causes), default=1) * 1.18)
    style_axes(
        scorecard,
        title=f"Measured: recall {score.recall:.0%}, precision {score.precision:.0%} (break-days)",
        xlabel="breaks, counted each morning they were open",
        grid="x",
    )
    scorecard.legend(loc="center right")

    lifetimes = figure.add_subplot(grid[1, 1])
    by_cause: dict[BreakCause, list[int]] = defaultdict(list)
    last = reports[-1].as_of if reports else date.today()
    for record in register.records:
        by_cause[record.cause].append(max(record.age(last), 1))
    labels = sorted(by_cause, key=lambda cause: cause.value)
    for index, cause in enumerate(labels):
        values = by_cause[cause]
        jitter = np.linspace(-0.18, 0.18, len(values)) if len(values) > 1 else [0.0]
        lifetimes.scatter(
            values, [index + offset for offset in jitter], color=CAUSE_COLOURS[cause], s=36, alpha=0.85, zorder=3
        )
        lifetimes.plot([np.mean(values)] * 2, [index - 0.3, index + 0.3], color=PALETTE["ink"], linewidth=1.4)
    lifetimes.set_yticks(range(len(labels)), labels=[cause.value for cause in labels])
    style_axes(lifetimes, title="How long each break stayed open (days; bar: mean)", xlabel="calendar days", grid="x")
    total = sum(record.largest_value for record in register.records)
    title_block(
        figure,
        title,
        "Every morning the book is compared with the custodian's statement on the custodian's terms - settled "
        "positions and settled cash - and every difference is classified by what could have caused it.",
    )
    caption(
        figure,
        f"Breaks planted on purpose into generated statements, so the reconciler can be scored like the quality rules "
        f"of Day 2. Largest value at stake per break, summed: {_money(float(total))}.",
    )
    return figure


def _find(breaks: dict[tuple[BreakKind, str], Break], kind: str, key: str) -> Break | None:
    """The break shown on a statement line: a holding line also shows a missing-holding or a price break."""
    if kind == BreakKind.CASH.value:
        return breaks.get((BreakKind.CASH, key))
    for candidate in (BreakKind.POSITION, BreakKind.MISSING_AT_CUSTODIAN, BreakKind.MISSING_IN_BOOK, BreakKind.PRICE):
        found = breaks.get((candidate, key))
        if found is not None:
            return found
    return None


def plot_reconciliation_statement(report: ReconciliationReport, lines: Sequence[tuple[str, str, str]]) -> Figure:
    """One morning: the book and the custodian side by side, with each break and its explanation."""
    breaks = {(item.kind, item.key): item for item in report.breaks}
    figure = new_figure(16.0, max(6.0, 0.34 * len(lines) + 2.6))
    height = figure.get_figheight()
    axis = figure.add_axes((0.012, 0.7 / height, 0.976, 1 - 1.9 / height))
    axis.axis("off")
    columns = [0.0, 0.14, 0.26, 0.38, 0.5, 0.62]
    headers = ["line", "book", "custodian", "difference", "cause", "explanation"]
    for column, header in zip(columns, headers, strict=True):
        axis.text(column, 1.0, header, fontsize=9, weight="bold", color=PALETTE["navy"], va="top")
    step = 0.94 / max(len(lines), 1)
    for index, (kind, key, label) in enumerate(lines):
        y = 0.94 - index * step
        shown = _find(breaks, kind, key)
        axis.text(columns[0], y, label, fontsize=8.6, va="top")
        if shown is None:
            axis.text(columns[1], y, "matched", fontsize=8.6, va="top", color=PALETTE["gain"])
            continue
        colour = CAUSE_COLOURS[shown.cause]
        axis.add_patch(Rectangle((-0.005, y - step * 0.8), 1.01, step * 0.94, color=colour, alpha=0.12))
        axis.text(columns[1], y, f"{shown.book:,.2f}", fontsize=8.6, va="top")
        axis.text(columns[2], y, f"{shown.custodian:,.2f}", fontsize=8.6, va="top")
        axis.text(columns[3], y, f"{shown.difference:+,.2f}", fontsize=8.6, va="top", weight="bold")
        causes = " + ".join(cause.value for cause in shown.causes)
        axis.text(columns[4], y, causes, fontsize=8.6, va="top", color=colour, weight="bold")
        axis.text(columns[5], y, shown.explanation, fontsize=8.2, va="top", color=PALETTE["ink"])
    title_block(
        figure,
        f"The morning of {report.as_of:%d %b %Y}: the book against the custodian",
        f"{report.positions_compared} holdings and {report.cash_compared} currencies compared; "
        f"{len(report.breaks)} breaks, {len(report.unexplained)} unexplained, {report.match_rate:.0%} of lines "
        "matched.",
    )
    caption(
        figure,
        "Holdings are compared as settled quantities (a price break shows prices in local currency), cash in each "
        "currency's own units.",
    )
    return figure


def statement_lines(
    report: ReconciliationReport, instruments: Sequence[str], currencies: Sequence[str]
) -> list[tuple[str, str, str]]:
    """The lines a statement comparison shows: every holding, every currency, then anything only one side has."""
    lines = [(BreakKind.POSITION.value, key, f"holding  {key}") for key in instruments]
    lines += [(BreakKind.CASH.value, currency, f"cash  {currency}") for currency in currencies]
    extra = sorted(
        {item.key for item in report.breaks if item.kind is BreakKind.MISSING_IN_BOOK and item.key not in instruments}
    )
    lines += [(BreakKind.POSITION.value, key, f"holding  {key} (custodian only)") for key in extra]
    return lines
