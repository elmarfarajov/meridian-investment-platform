"""Charts for market data quality.

A quality check that nobody looks at is a quality check that does not exist.
These are the pictures an operations team works from: where the problems are
(the dashboard and the coverage calendar), what one of them looks like up
close (the anomaly chart), why the statistics are built the way they are (the
robust score against the classical one), and how well the whole thing works
when it is measured against faults whose location is known (the scorecard).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle

from ..core.calendars import get_calendar
from ..marketdata.quotes import MarketDataset
from ..quality.context import SeriesContext
from ..quality.engine import QualityReport, attach_market_proxy
from ..quality.evaluation import DetectionScore
from ..quality.findings import Dimension, Finding, Severity
from ..quality.robust import rolling_classical_z, rolling_robust_z
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block, x_of

DIMENSION_COLOURS: dict[Dimension, str] = {
    Dimension.COMPLETENESS: PALETTE["navy"],
    Dimension.TIMELINESS: PALETTE["teal"],
    Dimension.VALIDITY: PALETTE["violet"],
    Dimension.ACCURACY: PALETTE["loss"],
    Dimension.CONSISTENCY: PALETTE["sky"],
}
SEVERITY_COLOURS: dict[Severity, str] = {
    Severity.INFO: PALETTE["grid"],
    Severity.WARNING: PALETTE["sky"],
    Severity.ERROR: PALETTE["loss"],
    Severity.CRITICAL: "#6E1119",
}
# Pale enough that dark text stays legible on every cell; red is reserved for the genuinely bad end.
_SCORE_MAP = LinearSegmentedColormap.from_list("quality", ["#E7A6AB", "#F3E7CC", "#E4F1E9", "#A9D5BD"], N=256)


def _margins(
    figure: Figure, *, top: float = 1.15, bottom: float = 0.55, left: float = 0.07, right: float = 0.975
) -> dict:
    """Subplot margins in inches, so every chart leaves the same room for its title block."""
    height = figure.get_figheight()
    return {"top": 1 - top / height, "bottom": bottom / height, "left": left, "right": right}


# ---------------------------------------------------------------------------- dashboard
def plot_quality_dashboard(report: QualityReport, *, title: str = "Market data quality dashboard") -> Figure:
    """Scores per series and dimension, findings per rule, and where in time the problems sit."""
    figure = new_figure(15.0, 10.8)
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=[1.25, 1.0],
        width_ratios=[1.3, 1.0],
        hspace=0.36,
        wspace=0.28,
        **_margins(figure, top=1.35, bottom=0.75),
    )

    # -- scores heat table
    table_axis = figure.add_subplot(grid[0, 0])
    scores = sorted(report.scores, key=lambda item: (item.overall, item.key))
    dimensions = list(Dimension)
    matrix = np.array([[score.dimensions[dimension] for dimension in dimensions] + [score.overall] for score in scores])
    table_axis.imshow(matrix, cmap=_SCORE_MAP, vmin=0.98, vmax=1.0, aspect="auto")
    labels = [dimension.value.title() for dimension in dimensions] + ["Overall"]
    table_axis.set_xticks(range(len(labels)), labels=labels, rotation=0)
    table_axis.set_yticks(range(len(scores)), labels=[score.key for score in scores])
    table_axis.tick_params(axis="both", length=0, labelsize=8)
    table_axis.xaxis.tick_top()
    for row, score in enumerate(scores):
        for column, value in enumerate(matrix[row]):
            text = "100%" if value >= 0.99995 else f"{value:.2%}"
            weight = "bold" if column == len(labels) - 1 else "normal"
            table_axis.text(
                column, row, text, ha="center", va="center", fontsize=7.4, color=PALETTE["ink"], weight=weight
            )
        light = {"green": PALETTE["gain"], "amber": "#C9A227", "red": PALETTE["loss"]}[score.status]
        table_axis.add_patch(Rectangle((len(labels) - 0.5, row - 0.32), 0.18, 0.64, color=light, clip_on=False))
    table_axis.axvline(len(labels) - 1.5, color=PALETTE["surface"], linewidth=3)
    for spine in table_axis.spines.values():
        spine.set_visible(False)
    table_axis.grid(visible=False)
    table_axis.set_title("Score by series and dimension (worst first)", pad=26)

    # -- findings by rule and severity
    rule_axis = figure.add_subplot(grid[0, 1])
    table = report.by_rule_and_severity()
    rules = sorted(table, key=lambda name: sum(table[name].values()))
    left = np.zeros(len(rules))
    for severity in (Severity.WARNING, Severity.ERROR, Severity.CRITICAL):
        counts = np.array([table[name][severity] for name in rules], dtype=float)
        if counts.any():
            rule_axis.barh(
                rules, counts, left=left, color=SEVERITY_COLOURS[severity], label=severity.value.title(), height=0.62
            )
        left += counts
    for index, total in enumerate(left):
        rule_axis.text(total + 0.15, index, f"{int(total)}", va="center", fontsize=8, color=PALETTE["muted"])
    style_axes(rule_axis, title="Findings by rule and severity", xlabel="Findings", grid="x")
    rule_axis.legend(loc="lower right")
    rule_axis.tick_params(axis="y", labelsize=8)

    # -- swimlanes: where in time
    lane_axis = figure.add_subplot(grid[1, :])
    keys = [score.key for score in sorted(report.scores, key=lambda item: item.key)]
    rows = {key: index for index, key in enumerate(keys)}
    for index in range(len(keys)):
        if index % 2 == 0:
            lane_axis.axhspan(index - 0.5, index + 0.5, color=PALETTE["band"], zorder=0, linewidth=0)
    for finding in report.findings:
        lane = rows.get(finding.key)
        if lane is None:
            continue
        colour = DIMENSION_COLOURS[finding.dimension]
        if finding.end_day and finding.end_day > finding.day:
            lane_axis.plot(
                [finding.day, finding.end_day], [lane, lane], color=colour, linewidth=6, solid_capstyle="butt", zorder=3
            )
        else:
            marker = "D" if finding.severity is Severity.CRITICAL else "o"
            lane_axis.scatter(
                [finding.day], [lane], color=colour, s=34, marker=marker, zorder=4, edgecolor="white", linewidth=0.6
            )
    lane_axis.set_yticks(range(len(keys)), labels=keys)
    lane_axis.set_ylim(len(keys) - 0.5, -0.5)
    first_days = [days[0] for days in report.expected_days.values() if days]
    if first_days:
        lane_axis.set_xlim(x_of(min(first_days)), x_of(report.as_of))
    style_axes(lane_axis, title="Where the findings sit in time (runs drawn as bars)", grid="x")
    lane_axis.tick_params(axis="y", labelsize=8)
    lane_axis.legend(
        handles=[Patch(color=colour, label=dimension.value.title()) for dimension, colour in DIMENSION_COLOURS.items()],
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        ncol=5,
    )

    severities = report.by_severity()
    title_block(
        figure,
        title,
        f"{len(report.scores)} series, {len(report.findings)} findings "
        f"({severities[Severity.CRITICAL]} critical, {severities[Severity.ERROR]} errors, "
        f"{severities[Severity.WARNING]} warnings); observation-weighted score {report.overall:.2%}.",
    )
    caption(
        figure,
        "Scores are the share of each series' expected trading days untouched by a finding of that dimension, "
        "weighted 25/15/20/25/15 into the overall score. Green >= 99.5%, amber >= 98%, red below or on any critical.",
    )
    return figure


# ---------------------------------------------------------------------------- one series up close
def _contexts(
    dataset: MarketDataset, calendars: Mapping[str, str], actions: Sequence[object], as_of: date
) -> dict[str, SeriesContext]:
    contexts = {
        key: SeriesContext.build(
            key,
            dataset.for_instrument(key),
            calendars.get(key, "XNYS"),
            as_of=as_of,
            actions=actions,  # type: ignore[arg-type]
        )
        for key in dataset.instruments
    }
    attach_market_proxy(list(contexts.values()))
    return contexts


def plot_anomaly_detection(
    damaged: MarketDataset,
    clean: MarketDataset,
    report: QualityReport,
    instrument_id: str,
    *,
    calendars: Mapping[str, str],
    actions: Sequence[object] = (),
    threshold: float = 9.0,
) -> Figure:
    """One feed with its faults: the price, what the rules saw, and the robust score behind it."""
    as_of = report.as_of
    context = _contexts(damaged, calendars, actions, as_of)[instrument_id]
    findings = [item for item in report.for_key(instrument_id)]
    received = damaged.close_series(instrument_id)
    truth = clean.close_series(instrument_id)
    focus = [item.day for item in findings]
    start = min(focus) - timedelta(days=45) if focus else received.first.day
    end = max(item.last_day for item in findings) + timedelta(days=30) if findings else received.last.day

    figure = new_figure(14.0, 8.4)
    grid = figure.add_gridspec(2, 1, height_ratios=[1.6, 1.0], hspace=0.12, **_margins(figure, bottom=0.8))
    price_axis = figure.add_subplot(grid[0])
    score_axis = figure.add_subplot(grid[1], sharex=price_axis)

    window_truth = truth.between(start, end)
    window = received.between(start, end)
    price_axis.plot(window_truth.days, window_truth.floats(), color=PALETTE["grid"], linewidth=4.5, label="True close")
    price_axis.plot(window.days, window.floats(), color=PALETTE["navy"], linewidth=1.5, label="Received from the feed")
    for finding in findings:
        colour = DIMENSION_COLOURS[finding.dimension]
        if finding.rule == "missing_days":
            price_axis.axvspan(
                x_of(finding.day) - 0.5, x_of(finding.last_day) + 0.5, color=colour, alpha=0.12, linewidth=0
            )
            annotate(
                price_axis,
                f"{int(finding.observed or 0)} missing days",
                (x_of(finding.day), max(window.floats())),
                fontsize=8,
            )
        elif finding.rule == "stale_mark":
            price_axis.axvspan(
                x_of(finding.day) - 0.5, x_of(finding.last_day) + 0.5, color=colour, alpha=0.18, linewidth=0
            )
            level = float(received.get(finding.day) or window.first.value)
            annotate(
                price_axis,
                "stale: the feed repeated one close",
                (x_of(finding.day), level),
                xytext=(0, 26),
                textcoords="offset points",
                fontsize=8,
            )
        elif finding.rule in {"spike_reversal", "non_positive_price", "unexplained_jump"}:
            printed = received.get(finding.day)
            if printed is not None:
                price_axis.scatter(
                    [finding.day],
                    [float(printed)],
                    s=80,
                    facecolor="none",
                    edgecolor=PALETTE["accent"],
                    linewidth=2,
                    zorder=5,
                )
                annotate(
                    price_axis,
                    finding.rule.replace("_", " "),
                    (x_of(finding.day), float(printed)),
                    highlight=True,
                    xytext=(8, 8),
                    textcoords="offset points",
                )
    style_axes(price_axis, title=f"{instrument_id}: the feed as received, against the truth", ylabel="Close")
    price_axis.legend(loc="lower left")
    price_axis.tick_params(labelbottom=False)

    returns = context.residual_returns
    scores = rolling_robust_z([value for _, value in returns], 60, min_periods=20)
    days = [day for day, _ in returns]
    shown = [(day, score) for day, score in zip(days, scores, strict=True) if score is not None and start <= day <= end]
    clipped = [max(-40.0, min(40.0, score)) for _, score in shown]
    colours = [PALETTE["loss"] if abs(score) >= threshold else PALETTE["slate"] for _, score in shown]
    score_axis.bar([day for day, _ in shown], clipped, color=colours, width=1.2)
    score_axis.axhspan(-threshold, threshold, color=PALETTE["band"], zorder=0)
    for level in (threshold, -threshold):
        score_axis.axhline(level, color=PALETTE["loss"], linewidth=0.8, linestyle="--")
    score_axis.axhline(0, color=PALETTE["ink"], linewidth=0.6)
    style_axes(
        score_axis, title="Robust z-score of the day's return, net of the market (clipped at +/-40)", ylabel="Robust z"
    )
    annotate(score_axis, f"flag beyond +/-{threshold:g}", (0.005, 0.86), xycoords="axes fraction")

    title_block(
        figure,
        "Finding the bad prints",
        "Planted faults in one exchange feed, and the rules that caught them. The shaded bands are runs; the circled "
        "points are single bad prints.",
    )
    caption(
        figure,
        "Robust z = (return - rolling median) / (1.4826 x rolling MAD) over the previous 60 returns, after corporate "
        "actions and the leave-one-out market median are taken out. The window never includes the day being judged.",
    )
    return figure


# ---------------------------------------------------------------------------- robust against classical
def plot_robust_vs_classical(*, seed: int = 21, threshold: float = 6.0) -> Figure:
    """Masking, drawn: three bad ticks in one window defeat the classical score and not the robust one."""
    rng = np.random.default_rng(seed)
    returns = rng.standard_t(5, 220) * 0.0095
    spikes = {120: 0.11, 128: -0.095, 137: 0.12}
    for index, value in spikes.items():
        returns[index] = value
    classical = rolling_classical_z(returns.tolist(), 60, min_periods=20)
    robust = rolling_robust_z(returns.tolist(), 60, min_periods=20)

    figure = new_figure(13.0, 8.2)
    grid = figure.add_gridspec(3, 1, height_ratios=[1.1, 1.0, 1.0], hspace=0.3, **_margins(figure, bottom=0.75))
    axes = [figure.add_subplot(grid[0])]
    axes += [figure.add_subplot(grid[row], sharex=axes[0]) for row in (1, 2)]
    x = np.arange(len(returns))
    axes[0].bar(
        x, returns * 100, color=[PALETTE["loss"] if index in spikes else PALETTE["slate"] for index in x], width=0.9
    )
    style_axes(axes[0], title="Daily returns with three bad ticks, nine days apart", ylabel="Return (%)")

    def draw(axis: Axes, scores: Sequence[float | None], label: str) -> int:
        values = np.array([abs(score) if score is not None else np.nan for score in scores])
        caught = [index for index in spikes if values[index] >= threshold]
        axis.bar(
            x,
            np.minimum(values, 30),
            color=[PALETTE["loss"] if index in spikes else PALETTE["sky"] for index in x],
            width=0.9,
        )
        axis.axhline(threshold, color=PALETTE["ink"], linestyle="--", linewidth=0.9)
        style_axes(axis, title=f"{label}: catches {len(caught)} of {len(spikes)}", ylabel="|z| (capped at 30)")
        for index in spikes:
            verdict = "caught" if index in caught else "missed"
            annotate(
                axis,
                verdict,
                (index, min(values[index], 30)),
                xytext=(0, 5),
                textcoords="offset points",
                ha="center",
                highlight=verdict == "missed",
            )
        return len(caught)

    draw(axes[1], classical, "Classical z-score (mean and standard deviation)")
    draw(axes[2], robust, "Robust z-score (median and MAD)")
    axes[2].set_xlabel("Trading day")
    title_block(
        figure,
        "Why the median, not the mean",
        "The first bad tick inflates the standard deviation that the next two are judged against, so they hide behind "
        "it. The median and MAD do not move.",
    )
    caption(
        figure,
        f"Student-t(5) returns at 0.95% daily volatility; 60-day trailing windows; threshold |z| = {threshold:g}. "
        "The MAD has a 50% breakdown point: half the window can be garbage before it is fooled.",
    )
    return figure


# ---------------------------------------------------------------------------- scorecard
_FAULT_LABELS = {
    "stale_run": "Stale run",
    "spike": "Spike (bad tick)",
    "missing_run": "Missing days",
    "unrecorded_split": "Unrecorded split",
    "unit_error": "Unit error (x100)",
    "crossed_quote": "Crossed quote",
    "holiday_print": "Print on a closed day",
    "non_positive": "Zero price",
    "fx_triangle_break": "FX triangle break",
}


def plot_detection_scorecard(score: DetectionScore, *, seeds: int = 3) -> Figure:
    """Recall by fault type and precision by rule, measured against planted faults."""
    figure = new_figure(14.0, 6.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.1], wspace=0.42, **_margins(figure, bottom=0.8, left=0.13))

    recall_axis = figure.add_subplot(grid[0])
    kinds = sorted(score.kinds, key=lambda item: (item.recall, item.kind.value))
    labels = [_FAULT_LABELS.get(item.kind.value, item.kind.value) for item in kinds]
    recall_axis.barh(labels, [item.recall * 100 for item in kinds], color=PALETTE["gain"], height=0.6)
    for index, item in enumerate(kinds):
        recall_axis.text(
            2, index, f"{item.detected} of {item.planted}", va="center", color="white", fontsize=8, weight="bold"
        )
    recall_axis.set_xlim(0, 100)
    style_axes(recall_axis, title="Recall: planted faults found, by type", xlabel="Recall (%)", grid="x")

    precision_axis = figure.add_subplot(grid[1])
    rules = sorted(score.rules, key=lambda item: (item.precision, item.flagged))
    names = [item.rule for item in rules]
    hits = [item.true_positives for item in rules]
    misses = [item.false_positives for item in rules]
    precision_axis.barh(names, hits, color=PALETTE["navy"], height=0.6, label="On a planted fault")
    precision_axis.barh(names, misses, left=hits, color=PALETTE["loss"], height=0.6, label="False alarm")
    for index, rule in enumerate(rules):
        precision_axis.text(
            rule.flagged + 0.4, index, f"{rule.precision:.0%}", va="center", fontsize=8, color=PALETTE["muted"]
        )
    style_axes(precision_axis, title="Precision: what each rule flagged", xlabel="Findings", grid="x")
    precision_axis.legend(loc="lower right")
    precision_axis.tick_params(axis="y", labelsize=8)

    title_block(
        figure,
        "Measured, not asserted",
        f"{score.planted} faults planted across {seeds} independently seeded markets: recall {score.recall:.0%}, "
        f"precision {score.precision:.0%}, F1 {score.f1:.2f}.",
    )
    caption(
        figure,
        "A finding is a hit if it overlaps a planted fault in the same series within four days. The false alarms are "
        "genuine fat-tailed market moves in the synthetic data, which is what they would be on a real desk.",
    )
    return figure


# ---------------------------------------------------------------------------- coverage calendar
_RECEIVED, _CLOSED, _MISSING, _FLAGGED, _EXTRA = 0, 1, 2, 3, 4


def plot_coverage_calendar(
    dataset: MarketDataset,
    report: QualityReport,
    calendars: Mapping[str, str],
    start: date,
    end: date,
) -> Figure:
    """Expected against received, day by day, on each instrument's own exchange calendar."""
    keys = list(dataset.instruments)
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    days = [day for day in days if day.weekday() < 5]
    blocked = {(key, day) for key, _, day in report.blocked_points()}
    grid_values = np.zeros((len(keys), len(days)), dtype=int)
    for row, key in enumerate(keys):
        calendar = get_calendar(calendars.get(key, "XNYS"))
        received = set(dataset.close_series(key).days)
        for column, day in enumerate(days):
            open_day = calendar.is_business_day(day)
            if not open_day:
                grid_values[row, column] = _EXTRA if day in received else _CLOSED
            elif day not in received:
                grid_values[row, column] = _MISSING
            elif (key, day) in blocked:
                grid_values[row, column] = _FLAGGED
            else:
                grid_values[row, column] = _RECEIVED

    colours = {
        _RECEIVED: "#CFDCEC",
        _CLOSED: PALETTE["surface"],
        _MISSING: PALETTE["loss"],
        _FLAGGED: PALETTE["accent"],
        _EXTRA: PALETTE["violet"],
    }
    image = np.zeros((*grid_values.shape, 3))
    for state, colour in colours.items():
        value = colour.lstrip("#")
        image[grid_values == state] = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    figure = new_figure(15.0, 1.8 + 0.42 * len(keys) + 1.9)
    axis = figure.add_subplot()
    figure.subplots_adjust(**_margins(figure, bottom=1.25, left=0.1))
    axis.imshow(image, aspect="auto", interpolation="nearest")
    for row in range(len(keys)):
        for column in range(len(days)):
            if grid_values[row, column] == _CLOSED:
                axis.add_patch(
                    Rectangle(
                        (column - 0.5, row - 0.5), 1, 1, fill=False, hatch="///", edgecolor="#AEB9C9", linewidth=0
                    )
                )
    axis.set_yticks(range(len(keys)), labels=[f"{key}  ({calendars.get(key, 'XNYS')})" for key in keys])
    month_starts = [index for index, day in enumerate(days) if index == 0 or day.month != days[index - 1].month]
    axis.set_xticks(month_starts, labels=[days[index].strftime("%b %Y") for index in month_starts])
    axis.set_xticks(np.arange(-0.5, len(days), 1), minor=True)
    axis.set_yticks(np.arange(-0.5, len(keys), 1), minor=True)
    axis.grid(which="minor", color=PALETTE["surface"], linewidth=0.8)
    axis.grid(which="major", visible=False)
    axis.tick_params(which="both", length=0, labelsize=8)
    for spine in axis.spines.values():
        spine.set_visible(False)
    counts = Counter(grid_values.flatten().tolist())
    axis.legend(
        handles=[
            Patch(color=colours[_RECEIVED], label=f"Received ({counts[_RECEIVED]})"),
            Patch(facecolor=PALETTE["surface"], edgecolor="#AEB9C9", hatch="///", label="Exchange closed"),
            Patch(color=colours[_MISSING], label=f"Expected, missing ({counts[_MISSING]})"),
            Patch(color=colours[_FLAGGED], label=f"Received, withheld by a check ({counts[_FLAGGED]})"),
            Patch(color=colours[_EXTRA], label=f"Received on a closed day ({counts[_EXTRA]})"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.07),
        ncol=5,
    )
    title_block(
        figure,
        "Expected against received",
        "Every weekday for every instrument, judged against that instrument's own exchange calendar - which is why "
        "London and Frankfurt close on days New York trades, and the reverse.",
    )
    caption(figure, f"{start:%d %b %Y} to {end:%d %b %Y}. Hatched cells are exchange holidays and are not expected.")
    return figure


def findings_table(findings: Sequence[Finding], limit: int = 20) -> list[tuple[str, str, str, str, str]]:
    """Rows for the CLI: key, date, rule, severity, message."""
    ordered = sorted(findings, key=lambda item: (-item.severity.rank, item.key, item.day))
    return [(item.key, item.day.isoformat(), item.rule, item.severity.value, item.message) for item in ordered[:limit]]
