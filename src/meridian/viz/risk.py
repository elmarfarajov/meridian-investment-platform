"""Charts for the factor risk model.

What a risk team has to show, one chart per question:

* **How much risk, and from where?** The Euler decomposition of volatility and
  tracking error into the market, industries, styles, currencies and stock
  specific risk; the active bets behind it; each holding's contribution.
* **Is the forecast right?** Bias statistics over time with their confidence
  band, on the estimation universe and on the account itself; volatility
  forecasts against the truth; the VaR backtest with its exceptions and the
  Basel zones.
* **Why a factor model?** The eigenvalues of a sample covariance against
  Marchenko-Pastur, and what an optimiser builds from each estimator.
* **What would a bad day cost?** VaR four ways, and stress tests.
* **The page the risk committee reads**: a one-page risk report.

Colours follow meaning: navy the market, teal industries, violet styles, sky
currencies, slate what is specific to one stock; green and red only for gains
and losses; amber only to point at something.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.dates import YearLocator
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..risk.comparison import ESTIMATORS, EstimatorSummary, Trial
from ..risk.covariance import marchenko_pastur_bounds, marchenko_pastur_density
from ..risk.var import RiskEstimate
from .accounting import _margins
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block, x_of

GROUP_COLOURS = {
    "World": PALETTE["navy"],
    "Industry": PALETTE["teal"],
    "Style": PALETTE["violet"],
    "Currency": PALETTE["sky"],
    "Specific": PALETTE["slate"],
}
METHOD_COLOURS = {
    "Truth": PALETTE["ink"],
    "truth": PALETTE["ink"],
    "ewma": PALETTE["navy"],
    "EWMA": PALETTE["navy"],
    "sample": PALETTE["sky"],
    "Sample": PALETTE["sky"],
    "GARCH(1,1)": PALETTE["teal"],
    "EWMA (42-day half-life)": PALETTE["navy"],
    "Equal-weighted 252 days": PALETTE["sky"],
}
ESTIMATOR_COLOURS = dict(
    zip(ESTIMATORS, [PALETTE["sky"], PALETTE["violet"], PALETTE["teal"], PALETTE["navy"]], strict=True)
)
_DIVERGING = LinearSegmentedColormap.from_list("corr", ["#B3202C", "#F2D4D6", "#FFFFFF", "#D3E0F0", "#1B3A6B"], N=256)
ANNUAL = math.sqrt(252)

Regime = tuple[str, date, date]


def _pct(value: float, places: int = 1, signed: bool = False) -> str:
    return f"{value:+.{places}%}" if signed else f"{value:.{places}%}"


def _percent_axis(axis, which: str = "y", places: int = 0) -> None:  # type: ignore[no-untyped-def]
    formatter = lambda value, _: f"{value:.{places}%}"  # noqa: E731
    (axis.yaxis if which == "y" else axis.xaxis).set_major_formatter(formatter)


def _shade_regimes(axis, regimes: Sequence[Regime], *, label: bool = True) -> None:  # type: ignore[no-untyped-def]
    for index, (name, start, end) in enumerate(regimes):
        axis.axvspan(x_of(start), x_of(end), color=PALETTE["accent"], alpha=0.10, linewidth=0)
        if label:
            axis.annotate(
                name,
                (x_of(start), 1.0),
                xycoords=("data", "axes fraction"),
                xytext=(2, -10 - 9 * (index % 2)),
                textcoords="offset points",
                fontsize=6.8,
                color=PALETTE["muted"],
            )


# ---------------------------------------------------------------------------- 1. decomposition
def plot_risk_decomposition(
    groups: Mapping[str, Mapping[str, float]],
    totals: Mapping[str, float],
    active_factors: Sequence[tuple[str, float, float, float]],
    as_of: date,
) -> Figure:
    """``groups``: Portfolio / Benchmark / Active -> group -> annualised contribution.

    ``active_factors``: (factor, contribution to tracking error, portfolio exposure, benchmark exposure).
    """
    figure = new_figure(15.8, 7.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.32, **_margins(figure, bottom=1.0, left=0.09))
    axis = figure.add_subplot(grid[0])
    rows = list(groups)
    order = ["World", "Industry", "Style", "Currency", "Specific"]
    for row, name in enumerate(rows):
        left_positive, left_negative = 0.0, 0.0
        for group in order:
            value = groups[name].get(group, 0.0)
            start = left_positive if value >= 0 else left_negative
            axis.barh(
                row,
                value,
                left=start,
                height=0.56,
                color=GROUP_COLOURS[group],
                edgecolor=PALETTE["surface"],
                linewidth=2,
            )
            if abs(value) >= 0.012:
                axis.text(
                    start + value / 2,
                    row,
                    f"{value:.1%}",
                    ha="center",
                    va="center",
                    fontsize=8.2,
                    color="white",
                    weight="bold",
                )
            if value >= 0:
                left_positive += value
            else:
                left_negative += value
        axis.text(
            left_positive + 0.002,
            row,
            f"  {totals[name]:.2%}",
            va="center",
            fontsize=10,
            weight="bold",
            color=PALETTE["ink"],
        )
    axis.set_yticks(
        range(len(rows)), labels=[f"{name}\n{'volatility' if name != 'Active' else 'tracking error'}" for name in rows]
    )
    axis.invert_yaxis()
    axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.set_xlim(right=max(totals.values()) * 1.22)
    _percent_axis(axis, "x")
    style_axes(axis, title="Where the risk comes from (contribution to annualised risk)", grid="x")
    axis.legend(handles=[Patch(color=GROUP_COLOURS[g], label=g) for g in order], loc="lower right", ncol=5, fontsize=8)

    detail = figure.add_subplot(grid[1])
    items = sorted(active_factors, key=lambda item: item[1])
    positions = np.arange(len(items))
    colours = [GROUP_COLOURS["Specific"] if name == "Specific" else _factor_colour(name) for name, *_ in items]
    detail.barh(positions, [value for _, value, _, _ in items], color=colours, height=0.62)
    for position, (name, value, mine, theirs) in enumerate(items):
        label = f" {value:+.2%}" + ("" if name == "Specific" else f"   (exposure {mine:+.2f} vs {theirs:+.2f})")
        detail.text(max(value, 0.0), position, label, va="center", fontsize=7.8, color=PALETTE["ink"])
    detail.set_yticks(positions, labels=[name for name, *_ in items], fontsize=8.5)
    detail.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    detail.set_xlim(
        min(0.0, min(value for _, value, _, _ in items)) * 1.4 - 0.001, max(value for _, value, _, _ in items) * 1.55
    )
    _percent_axis(detail, "x", 1)
    style_axes(detail, title="What the tracking error is made of", grid="x")
    title_block(
        figure,
        f"Risk decomposition on {as_of:%d %B %Y}",
        "Euler contributions: each bar adds up to its total exactly. The market dominates the account's volatility; "
        "its tracking error is mostly stock-specific - the price of picking stocks.",
    )
    caption(
        figure,
        "Annualised from daily forecasts. Index funds are looked through; a fund's own tracking risk is specific.",
    )
    return figure


def _factor_colour(name: str) -> str:
    from ..risk.factors import group_of

    return GROUP_COLOURS[group_of(name)]


# ---------------------------------------------------------------------------- 2. bias statistics
def plot_bias_statistics(
    days: Sequence[date],
    rolling: Mapping[str, np.ndarray],
    band: tuple[float, float],
    window: int,
    random_bias: Mapping[str, Sequence[float]],
    full_band: tuple[float, float],
    regimes: Sequence[Regime],
) -> Figure:
    """Rolling bias of the market portfolio by forecaster, and the full-period bias of random portfolios."""
    figure = new_figure(15.8, 8.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[2.6, 1.0], wspace=0.14, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    axis.axhspan(*band, color=PALETTE["band"], zorder=0)
    axis.axhline(1.0, color=PALETTE["muted"], linewidth=0.8)
    labels = {
        "truth": "truth (the generator's own risk)",
        "ewma": "EWMA forecast",
        "sample": "equal-weighted 252-day forecast",
    }
    widths = {"truth": 0.9, "ewma": 1.8, "sample": 1.4}
    for method, values in rolling.items():
        axis.plot(
            days,
            values,
            color=METHOD_COLOURS[method],
            linewidth=widths[method],
            label=labels[method],
            alpha=0.7 if method == "truth" else 1.0,
        )
    _shade_regimes(axis, regimes)
    axis.set_ylim(0.4, 2.2)
    style_axes(
        axis,
        title=f"Bias statistic of the cap-weighted market, rolling {window} days",
        ylabel="standard deviation of return / forecast",
    )
    axis.legend(loc="upper right", fontsize=8)
    annotate(
        axis,
        f"95% band for a correct model: {band[0]:.2f} - {band[1]:.2f}",
        (0.01, 0.04),
        xycoords="axes fraction",
        highlight=True,
    )

    strip = figure.add_subplot(grid[1])
    strip.axhspan(*full_band, color=PALETTE["band"], zorder=0)
    strip.axhline(1.0, color=PALETTE["muted"], linewidth=0.8)
    rng = np.random.default_rng(0)
    for position, (method, values) in enumerate(random_bias.items()):
        jitter = rng.uniform(-0.18, 0.18, len(values))
        strip.scatter(
            position + jitter,
            values,
            s=26,
            color=METHOD_COLOURS[method],
            edgecolor=PALETTE["surface"],
            linewidth=0.8,
            zorder=3,
        )
        inside = float(np.mean([(full_band[0] <= value <= full_band[1]) for value in values]))
        strip.annotate(
            f"{inside:.0%} in band",
            (position, max(values)),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=PALETTE["ink"],
            weight="bold",
        )
    strip.set_xticks(
        range(len(random_bias)), labels=[{"truth": "truth", "ewma": "EWMA", "sample": "sample"}[m] for m in random_bias]
    )
    strip.set_xlim(-0.6, len(random_bias) - 0.4)
    style_axes(strip, title="Thirty random portfolios, whole period")
    title_block(
        figure,
        "Is the forecast the right size? Bias statistics on ten years of the estimation universe",
        "Each day's return over the forecast made the evening before should have standard deviation one. The "
        "equal-weighted forecast is late into every crisis and late out of it; EWMA keeps close to the truth.",
    )
    caption(figure, "Shaded: regimes of the synthetic universe. Bias above the band means risk was under-forecast.")
    return figure


# ---------------------------------------------------------------------------- 3. eigenvalues
def plot_eigenvalue_spectrum(eigenvalues: np.ndarray, ratio: float, observations: int) -> Figure:
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.5, 1.0], wspace=0.22, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    positive = eigenvalues[eigenvalues > 1e-8]
    variance = 1.0 - float(eigenvalues[0]) / len(eigenvalues)  # what the market eigenvalue leaves for the noise
    _, high = marchenko_pastur_bounds(ratio, variance)
    bins = np.linspace(0, max(high * 1.6, 6.0), 70)
    axis.hist(
        np.clip(positive, 0, bins[-1]),
        bins=bins,
        density=True,
        color=PALETTE["sky"],
        alpha=0.75,
        label=f"{len(positive)} non-zero eigenvalues",
    )
    grid_x = np.linspace(1e-3, high, 800)
    # the density of the non-zero part (the law puts mass 1 - 1/q at zero when q > 1)
    scale = ratio if ratio > 1 else 1.0
    axis.plot(
        grid_x,
        marchenko_pastur_density(grid_x, ratio, variance) * scale,
        color=PALETTE["ink"],
        linewidth=1.8,
        label=f"Marchenko-Pastur: pure noise (variance {variance:.2f})",
    )
    axis.axvline(high, color=PALETTE["ink"], linewidth=0.8, linestyle=":")
    outside = int(np.sum(positive > high))
    axis.annotate(
        f"{outside} eigenvalues above the noise\nedge ({high:.2f}): the only\nstructure in the matrix",
        (high, axis.get_ylim()[1] * 0.5),
        xytext=(12, 0),
        textcoords="offset points",
        fontsize=8.5,
        color=PALETTE["accent"],
        weight="bold",
    )
    style_axes(axis, title="Eigenvalues of the sample correlation matrix", xlabel="eigenvalue")
    axis.legend(loc="upper right", fontsize=8)

    top = figure.add_subplot(grid[1])
    head = eigenvalues[:12]
    top.bar(
        np.arange(1, len(head) + 1), head, color=[PALETTE["navy"]] + [PALETTE["teal"]] * (len(head) - 1), width=0.62
    )
    top.axhline(high, color=PALETTE["ink"], linewidth=0.8, linestyle=":")
    top.annotate(
        f"market: {head[0]:.0f}", (1, head[0]), xytext=(8, -4), textcoords="offset points", fontsize=8.5, weight="bold"
    )
    top.set_yscale("log")
    style_axes(top, title="The largest twelve (log scale)", xlabel="rank")
    zero = int(np.sum(eigenvalues <= 1e-8))
    title_block(
        figure,
        f"Why a sample covariance fails: {len(eigenvalues)} stocks, {observations} days",
        f"With more stocks than days the matrix has {zero} zero eigenvalues - directions it says are riskless - and "
        "the rest spread across the band pure noise would fill. Only a handful of eigenvalues carry information.",
    )
    caption(
        figure,
        f"q = N / T = {ratio:.2f}. Correlations of dollar returns over the last {observations} days of the universe; "
        "the noise law is scaled to the variance the largest eigenvalue leaves.",
    )
    return figure


# ---------------------------------------------------------------------------- 4. minimum variance
def plot_minimum_variance(trials: Sequence[Trial], summaries: Sequence[EstimatorSummary]) -> Figure:
    figure = new_figure(15.5, 7.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.35, 1.0], wspace=0.25, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    for name in ESTIMATORS:
        chosen = [trial for trial in trials if trial.estimator == name]
        axis.scatter(
            [trial.promised for trial in chosen],
            [trial.delivered for trial in chosen],
            s=30,
            color=ESTIMATOR_COLOURS[name],
            edgecolor=PALETTE["surface"],
            linewidth=0.8,
            label=name,
            zorder=3,
        )
    top = max(max(trial.delivered for trial in trials), max(trial.promised for trial in trials)) * 1.05
    axis.plot([0, top], [0, top], color=PALETTE["muted"], linewidth=0.9, linestyle="--")
    axis.text(top * 0.72, top * 0.76, "delivered = promised", rotation=33, fontsize=8, color=PALETTE["muted"])
    axis.set_xlim(-0.004, top)
    axis.set_ylim(0, top)
    _percent_axis(axis, "x")
    _percent_axis(axis)
    style_axes(
        axis,
        title="Each month: the risk promised, and the risk delivered",
        xlabel="forecast volatility of the portfolio",
        ylabel="realised volatility next month",
        grid="both",
    )
    axis.legend(loc="lower right", fontsize=8)

    bars = figure.add_subplot(grid[1])
    positions = np.arange(len(summaries))
    bars.barh(
        positions + 0.2, [row.promised for row in summaries], height=0.36, color=PALETTE["grid"], label="promised"
    )
    bars.barh(
        positions - 0.2,
        [row.delivered for row in summaries],
        height=0.36,
        color=[ESTIMATOR_COLOURS[row.estimator] for row in summaries],
        label="delivered",
    )
    for position, row in enumerate(summaries):
        bars.text(row.delivered, position - 0.2, f" {row.delivered:.1%}", va="center", fontsize=8.5, weight="bold")
        bars.text(row.promised, position + 0.2, f" {row.promised:.1%}", va="center", fontsize=8, color=PALETTE["muted"])
    bars.set_yticks(positions, labels=[row.estimator.replace(" (", "\n(") for row in summaries], fontsize=8.5)
    bars.invert_yaxis()
    bars.set_xlim(0, max(row.delivered for row in summaries) * 1.35)
    _percent_axis(bars, "x")
    style_axes(bars, title="On average", grid="x")
    bars.legend(loc="lower right", fontsize=8)
    title_block(
        figure,
        "An optimiser finds the errors in a covariance matrix",
        "The minimum-variance portfolio of 500 stocks, rebuilt every month from 252 days. The sample covariance "
        "promises a riskless portfolio; shrinkage promises too little; the factor model delivers what it promises.",
    )
    caption(
        figure,
        "Fully invested, unconstrained. The factor model is inverted by the Woodbury identity, never as a 500 x 500 "
        "matrix.",
    )
    return figure


# ---------------------------------------------------------------------------- 5. factor returns
def plot_factor_returns(
    days: Sequence[date],
    styles: Mapping[str, np.ndarray],
    industries: Mapping[str, np.ndarray],
    regimes: Sequence[Regime],
) -> Figure:
    figure = new_figure(15.8, 8.6)
    outer = figure.add_gridspec(1, 2, width_ratios=[1.25, 1.0], wspace=0.14, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(outer[0])
    colours = [PALETTE["navy"], PALETTE["teal"], PALETTE["violet"], PALETTE["sky"], PALETTE["gain"]]
    for (name, values), colour in zip(styles.items(), colours, strict=False):
        path = np.cumprod(1 + values) - 1
        axis.plot(days, path, color=colour, linewidth=1.6)
        axis.annotate(f" {name} {path[-1]:+.0%}", (days[-1], path[-1]), fontsize=8.5, color=PALETTE["ink"], va="center")
    axis.axhline(0, color=PALETTE["muted"], linewidth=0.8)
    _shade_regimes(axis, regimes)
    _percent_axis(axis)
    style_axes(axis, title="Style factors, cumulative return of a unit exposure")
    inner = outer[1].subgridspec(4, 3, hspace=0.55, wspace=0.18)
    for index, (name, values) in enumerate(industries.items()):
        panel = figure.add_subplot(inner[index // 3, index % 3])
        path = np.cumprod(1 + values) - 1
        panel.fill_between(days, path, 0, where=path >= 0, color=PALETTE["gain"], alpha=0.25, linewidth=0)
        panel.fill_between(days, path, 0, where=path < 0, color=PALETTE["loss"], alpha=0.25, linewidth=0)
        panel.plot(days, path, color=PALETTE["teal"], linewidth=1.0)
        panel.set_title(f"{name}  {path[-1]:+.0%}", fontsize=7.8, loc="left")
        panel.tick_params(labelsize=6, labelbottom=index >= len(industries) - 3)
        panel.xaxis.set_major_locator(YearLocator(3))
        _percent_axis(panel)
        panel.grid(visible=True, axis="y")
        for spine in ("top", "right"):
            panel.spines[spine].set_visible(False)
    title_block(
        figure,
        "What the market paid each factor, 2017 to 2026",
        "Daily factor returns from the cross-sectional regressions. Industries are relative to the world factor; "
        "styles "
        "are the return to one standard deviation of exposure. The shaded regimes are where risk models are tested.",
    )
    caption(
        figure,
        "Styles go quiet from April 2024: the demonstration market the book lives in has no style premia beyond beta.",
    )
    return figure


# ---------------------------------------------------------------------------- 6. volatility forecasts
def plot_volatility_forecasts(
    days: Sequence[date], forecasts: Mapping[str, np.ndarray], errors: Mapping[str, float], regimes: Sequence[Regime]
) -> Figure:
    figure = new_figure(15.8, 7.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[3.0, 1.0], wspace=0.16, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    for name, values in forecasts.items():
        axis.plot(
            days,
            values * ANNUAL,
            color=METHOD_COLOURS[name],
            linewidth=0.9 if name == "Truth" else 1.4,
            label=name,
            zorder=5 if name == "Truth" else 3,
            alpha=0.9,
        )
    _shade_regimes(axis, regimes)
    _percent_axis(axis)
    style_axes(axis, title="The world factor's volatility, forecast one day ahead (annualised)")
    axis.legend(loc="upper right", fontsize=8)
    bars = figure.add_subplot(grid[1])
    names = list(errors)
    bars.bar(
        range(len(names)), [errors[name] for name in names], color=[METHOD_COLOURS[name] for name in names], width=0.6
    )
    for position, name in enumerate(names):
        bars.text(position, errors[name], f"{errors[name]:.1%}", ha="center", va="bottom", fontsize=9, weight="bold")
    bars.set_xticks(
        range(len(names)), labels=[name.replace(" (", "\n(").replace(" 252", "\n252") for name in names], fontsize=8
    )
    _percent_axis(bars)
    style_axes(bars, title="Average error against the truth")
    title_block(
        figure,
        "Forecasting volatility: GARCH, EWMA and the equal-weighted window against the truth",
        "The universe records the true conditional volatility, so each forecaster can be scored exactly. GARCH knows "
        "volatility reverts to its long-run level after a spike; EWMA forgets at a fixed rate; the window is always "
        "late.",
    )
    caption(
        figure,
        "Error: mean absolute log ratio of forecast to true volatility. GARCH refitted monthly on four years (arch "
        "package).",
    )
    return figure


# ---------------------------------------------------------------------------- 7. factor correlation
def plot_factor_correlation(
    names: Sequence[str], correlation: np.ndarray, vols: Sequence[float], as_of: date
) -> Figure:
    figure = new_figure(14.5, 11.0)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 0.22], wspace=0.16, **_margins(figure, bottom=0.8, left=0.16))
    axis = figure.add_subplot(grid[0])
    image = axis.imshow(correlation, cmap=_DIVERGING, vmin=-1, vmax=1)
    axis.set_xticks(range(len(names)), labels=names, rotation=90, fontsize=7.6)
    axis.set_yticks(range(len(names)), labels=names, fontsize=7.6)
    for (row, column), value in np.ndenumerate(correlation):
        if row != column and abs(value) >= 0.3:
            axis.text(
                column,
                row,
                f"{value:.1f}",
                ha="center",
                va="center",
                fontsize=5.8,
                color="white" if abs(value) > 0.6 else PALETTE["ink"],
            )
    axis.grid(visible=False)
    axis.set_title("Correlations of the factors (EWMA, 200-day half-life)")
    bar = figure.colorbar(image, cax=axis.inset_axes((1.015, 0.0, 0.018, 0.35)))
    bar.ax.tick_params(labelsize=7)
    side = figure.add_subplot(grid[1], sharey=axis)
    side.barh(range(len(names)), vols, color=[_factor_colour(name) for name in names], height=0.7)
    for position, vol in enumerate(vols):
        side.text(vol, position, f" {vol:.1%}", va="center", fontsize=7)
    side.tick_params(labelleft=False)
    side.set_xlim(0, max(vols) * 1.45)
    _percent_axis(side, "x")
    style_axes(side, title="Volatility", grid="x")
    title_block(
        figure,
        f"The factor covariance on {as_of:%d %B %Y}",
        "Twenty-one factors instead of 125,250 stock covariances. The beta factor rides on the world factor; "
        "currencies "
        "and industries are nearly independent of each other.",
    )
    return figure


# ---------------------------------------------------------------------------- 8. active exposures
def plot_active_exposures(
    names: Sequence[str], portfolio: Sequence[float], benchmark: Sequence[float], groups: Sequence[str]
) -> Figure:
    figure = new_figure(15.8, 8.8)
    grid = figure.add_gridspec(
        1, 3, width_ratios=[1.0, 1.0, 1.0], wspace=0.35, **_margins(figure, bottom=0.95, left=0.1)
    )
    panels = (
        ("Industry", "Industries (share of value)"),
        ("Style", "Styles (standard deviations)"),
        ("Currency", "Currencies (share of value)"),
    )
    for column, (group, title) in enumerate(panels):
        axis = figure.add_subplot(grid[column])
        chosen = [
            index
            for index, item in enumerate(groups)
            if item == group and (abs(portfolio[index]) > 1e-6 or abs(benchmark[index]) > 1e-6)
        ]
        positions = np.arange(len(chosen))
        mine = np.array([portfolio[index] for index in chosen])
        theirs = np.array([benchmark[index] for index in chosen])
        axis.barh(positions + 0.19, mine, height=0.36, color=GROUP_COLOURS[group], label="portfolio")
        axis.barh(positions - 0.19, theirs, height=0.36, color=PALETTE["grid"], label="benchmark")
        for position, (a, b) in enumerate(zip(mine, theirs, strict=True)):
            difference = a - b
            text = f"{difference:+.2f}" if group == "Style" else f"{difference:+.1%}"
            axis.text(
                1.02,
                position,
                text,
                transform=axis.get_yaxis_transform(),
                va="center",
                fontsize=8,
                weight="bold",
                color=PALETTE["gain"] if difference >= 0 else PALETTE["loss"],
                clip_on=False,
            )
        axis.set_yticks(positions, labels=[names[index].replace("FX ", "") for index in chosen], fontsize=8.2)
        axis.invert_yaxis()
        axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
        if group != "Style":
            _percent_axis(axis, "x")
        style_axes(axis, title=title, grid="x")
        if column == 0:
            axis.legend(loc="lower right", fontsize=8)
    title_block(
        figure,
        "The account's bets against its benchmark",
        "Factor exposures of the account (coloured) and the policy benchmark (grey); the active exposure is on the "
        "right "
        "of each panel. The account is overweight health care, technology and industrials, and holds almost no yen.",
    )
    caption(
        figure,
        "Styles are in cross-sectional standard deviations of the estimation universe; a mega-cap index has a large "
        "size exposure.",
    )
    return figure


# ---------------------------------------------------------------------------- 9. contributions by holding
def plot_asset_contributions(
    rows: Sequence[tuple[str, float, float, float]],
    active_rows: Sequence[tuple[str, float, float, float]],
    total: float,
    tracking: float,
) -> Figure:
    """``rows``: (holding, weight, annualised marginal, annualised contribution), largest first."""
    figure = new_figure(15.8, 8.0)
    grid = figure.add_gridspec(1, 2, wspace=0.42, **_margins(figure, bottom=0.95, left=0.1))
    for column, (items, label, overall) in enumerate(
        ((rows, "volatility", total), (active_rows, "tracking error", tracking))
    ):
        axis = figure.add_subplot(grid[column])
        positions = np.arange(len(items))
        values = [contribution for *_, contribution in items]
        colours = [
            PALETTE["slate"] if name.endswith(":basis") else PALETTE["navy"] if column == 0 else PALETTE["violet"]
            for name, *_ in items
        ]
        axis.barh(positions, values, color=colours, height=0.62)
        for position, (_, weight, marginal, contribution) in enumerate(items):
            axis.text(
                max(contribution, 0),
                position,
                f" {contribution:.2%}  (w {weight:+.1%}, marginal {marginal:.1%})",
                va="center",
                fontsize=7.6,
            )
        axis.set_yticks(positions, labels=[name for name, *_ in items], fontsize=8.2)
        axis.invert_yaxis()
        axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
        axis.set_xlim(min(0.0, min(values)) * 1.3, max(values) * 2.1)
        _percent_axis(axis, "x", 1)
        style_axes(axis, title=f"Contribution to {label} ({overall:.2%})", grid="x")
    title_block(
        figure,
        "Which holdings carry the risk",
        "A holding's contribution is its weight times its marginal risk; the contributions add up to the total. "
        "A fund's ':basis' line is the risk that it does not track its own index.",
    )
    caption(figure, "Marginal: the change in annualised risk per unit of weight added.")
    return figure


# ---------------------------------------------------------------------------- 10. VaR backtest
def plot_var_backtest(
    days: Sequence[date],
    realised: np.ndarray,
    var: np.ndarray,
    rolling_exceptions: np.ndarray,
    tests: Sequence[tuple[str, float, bool]],
) -> Figure:
    figure = new_figure(15.8, 8.6)
    grid = figure.add_gridspec(2, 1, height_ratios=[2.2, 1.0], hspace=0.32, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    colours = [PALETTE["gain"] if value >= 0 else PALETTE["loss"] for value in realised]
    axis.bar(days, realised, color=colours, width=1.2, alpha=0.8)
    axis.plot(days, -var, color=PALETTE["ink"], linewidth=1.2, label="99% VaR forecast the morning before")
    hits = -realised > var
    axis.scatter(
        np.asarray(days, dtype=object)[hits],
        realised[hits],
        s=70,
        facecolor="none",
        edgecolor=PALETTE["accent"],
        linewidth=2,
        zorder=5,
        label="exception",
    )
    _percent_axis(axis, places=1)
    style_axes(axis, title="The account's daily return against the morning's VaR")
    axis.legend(loc="upper left", fontsize=8)
    text = "   ".join(f"{name}: p = {p:.2f} ({'rejected' if rejected else 'passed'})" for name, p, rejected in tests)
    count = int(hits.sum())
    annotate(
        axis,
        f"{count} exception{'s' if count != 1 else ''} in {len(days)} days (expected {0.01 * len(days):.1f})   " + text,
        (0.01, 0.04),
        xycoords="axes fraction",
        highlight=True,
    )
    zones = figure.add_subplot(grid[1], sharex=axis)
    zones.axhspan(-0.5, 4.5, color="#CFE8DB", zorder=0)
    zones.axhspan(4.5, 9.5, color="#F7E3B5", zorder=0)
    zones.axhspan(9.5, 12, color="#F2D4D6", zorder=0)
    zones.step(days, rolling_exceptions, where="post", color=PALETTE["ink"], linewidth=1.4)
    for level, name in ((2, "green"), (7, "yellow"), (10.7, "red")):
        zones.text(
            1.005, level, name, transform=zones.get_yaxis_transform(), fontsize=8, color=PALETTE["muted"], va="center"
        )
    zones.set_ylim(-0.5, 12)
    style_axes(zones, title="Exceptions in the trailing 250 days: the Basel traffic light")
    title_block(
        figure,
        "Backtesting the account's value at risk",
        "Every morning the model forecast a 99% one-day VaR from what it knew; the day's return was then recorded. "
        "The window was calmer than its own true risk, so the VaR was exceeded less often than one day in a hundred.",
    )
    caption(
        figure,
        "Parametric VaR from the factor model's forecast volatility. It widens after a US market holiday, when one "
        "valuation day's return spans two trading days.",
    )
    return figure


# ---------------------------------------------------------------------------- 11. VaR methods
def plot_var_methods(
    history: np.ndarray, simulated: np.ndarray, estimates: Sequence[RiskEstimate], nav: float
) -> Figure:
    figure = new_figure(15.8, 7.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.6, 1.0], wspace=0.22, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    bins = np.linspace(-0.045, 0.045, 90)
    axis.hist(
        np.clip(simulated, bins[0], bins[-1]),
        bins=bins,
        density=True,
        color=PALETTE["sky"],
        alpha=0.35,
        label="Monte Carlo from the factor model (t, 50,000 days)",
    )
    axis.hist(
        np.clip(history, bins[0], bins[-1]),
        bins=bins,
        density=True,
        histtype="step",
        color=PALETTE["navy"],
        linewidth=1.6,
        label="today's holdings on the demonstration's days",
    )
    styles = [":", "--", "-.", "-"]
    colours = [PALETTE["ink"], PALETTE["violet"], PALETTE["navy"], PALETTE["teal"]]
    for estimate, line, colour in zip(estimates, styles, colours, strict=False):
        axis.axvline(
            -estimate.var,
            color=colour,
            linestyle=line,
            linewidth=1.3,
            label=f"{estimate.method}: VaR {estimate.var:.2%}",
        )
    _percent_axis(axis, "x", 1)
    style_axes(axis, title="One day's return, and where each method puts the 1% tail", xlabel="daily return")
    axis.legend(loc="upper right", fontsize=7.6)
    bars = figure.add_subplot(grid[1])
    positions = np.arange(len(estimates))
    bars.barh(
        positions + 0.19,
        [estimate.var * nav for estimate in estimates],
        height=0.36,
        color=PALETTE["navy"],
        label="VaR",
    )
    bars.barh(
        positions - 0.19,
        [estimate.es * nav for estimate in estimates],
        height=0.36,
        color=PALETTE["loss"],
        label="expected shortfall",
    )
    for position, estimate in enumerate(estimates):
        bars.text(estimate.es * nav, position - 0.19, f" {estimate.es * nav:,.0f}", va="center", fontsize=8)
        bars.text(estimate.var * nav, position + 0.19, f" {estimate.var * nav:,.0f}", va="center", fontsize=8)
    bars.set_yticks(positions, labels=[estimate.method.replace(" (", "\n(") for estimate in estimates], fontsize=8.2)
    bars.invert_yaxis()
    bars.set_xlim(0, max(estimate.es for estimate in estimates) * nav * 1.3)
    bars.xaxis.set_major_formatter(lambda value, _: f"{value / 1e3:,.0f}k")
    style_axes(bars, title="In dollars, one day, 99%", grid="x")
    bars.legend(loc="lower right", fontsize=8)
    title_block(
        figure,
        "Value at risk and expected shortfall, four ways",
        "Normal VaR from the forecast volatility; Cornish-Fisher corrected for skew and kurtosis; historical "
        "simulation; "
        "and Monte Carlo from the factor model with fat tails. Expected shortfall is the average of the bad days.",
    )
    caption(figure, f"On a net asset value of {nav:,.0f} dollars.")
    return figure


# ---------------------------------------------------------------------------- 12. stress tests
def plot_stress_tests(results: Sequence[tuple[str, str, float, float]]) -> Figure:
    figure = new_figure(15.5, 7.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.6, 1.0], wspace=0.35, **_margins(figure, bottom=0.95, left=0.16))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(results))
    axis.barh(positions + 0.19, [item[2] for item in results], height=0.36, color=PALETTE["navy"], label="portfolio")
    axis.barh(positions - 0.19, [item[3] for item in results], height=0.36, color=PALETTE["grid"], label="benchmark")
    for position, (_, _, mine, _) in enumerate(results):
        axis.text(mine, position + 0.19, f" {mine:+.1%} ", va="center", ha="right" if mine < 0 else "left", fontsize=8)
    axis.set_yticks(positions, labels=[f"{name}\n({kind})" for name, kind, *_ in results], fontsize=8.2)
    axis.invert_yaxis()
    axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    low = min(min(item[2], item[3]) for item in results)
    axis.set_xlim(low * 1.25, max(0.05, max(item[2] for item in results) * 1.4))
    _percent_axis(axis, "x")
    style_axes(axis, title="Loss of today's portfolio and benchmark", grid="x")
    axis.legend(loc="lower left", fontsize=8)
    active = figure.add_subplot(grid[1], sharey=axis)
    values = [item[2] - item[3] for item in results]
    active.barh(
        positions, values, color=[PALETTE["gain"] if value >= 0 else PALETTE["loss"] for value in values], height=0.5
    )
    for position, value in enumerate(values):
        active.text(value, position, f" {value:+.2%} ", va="center", ha="right" if value < 0 else "left", fontsize=8)
    active.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    active.tick_params(labelleft=False)
    span = max(abs(value) for value in values) * 1.6
    active.set_xlim(-span, span)
    _percent_axis(active, "x", 1)
    style_axes(active, title="Portfolio less benchmark", grid="x")
    title_block(
        figure,
        "Stress tests: if a bad week happened to today's portfolio",
        "Historical replays compound the factors' returns over a past crisis; hypothetical shocks are chosen by the "
        "risk "
        "committee. Both are applied to today's factor exposures.",
    )
    caption(figure, "Factor moves only: stock-specific returns in a replayed window belonged to other stocks.")
    return figure


# ---------------------------------------------------------------------------- 13. the book's bias
def plot_book_bias(
    days: Sequence[date],
    series: Mapping[str, np.ndarray],
    window: int,
    band: tuple[float, float],
    summaries: Sequence[tuple[str, float, float]],
) -> Figure:
    """``series``: label -> rolling bias; ``summaries``: (label, bias, MRAD)."""
    figure = new_figure(15.8, 7.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[2.4, 1.0], wspace=0.16, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    axis.axhspan(*band, color=PALETTE["band"], zorder=0)
    axis.axhline(1.0, color=PALETTE["muted"], linewidth=0.8)
    colours = [PALETTE["navy"], PALETTE["violet"], PALETTE["accent"], PALETTE["ink"]]
    styles = ["-", "-", "--", ":"]
    for (label, values), colour, line in zip(series.items(), colours, styles, strict=False):
        axis.plot(days, values, color=colour, linestyle=line, linewidth=1.6 if line == "-" else 1.2, label=label)
    axis.set_ylim(0.4, 1.8)
    style_axes(
        axis,
        title=f"Rolling {window}-day bias of the account's own forecasts",
        ylabel="standard deviation of return / forecast",
    )
    axis.legend(loc="upper left", fontsize=8)
    table = figure.add_subplot(grid[1])
    table.axis("off")
    cells = [[label, f"{bias:.3f}", f"{value:.3f}"] for label, bias, value in summaries]
    rendered = table.table(
        cellText=cells,
        colLabels=["forecast", "bias", "MRAD"],
        loc="center",
        cellLoc="center",
        colWidths=[0.62, 0.19, 0.19],
    )
    rendered.auto_set_font_size(False)
    rendered.set_fontsize(8.4)
    rendered.scale(1, 1.8)
    for (row, _), cell in rendered.get_celld().items():
        cell.set_edgecolor(PALETTE["grid"])
        if row == 0:
            cell.set_text_props(weight="bold", color=PALETTE["navy"])
    table.set_title("Whole window", loc="left")
    title_block(
        figure,
        "Did the account's risk forecasts hold up?",
        "Total risk scores what the market's true volatility itself scores over these days - the window was calm. The "
        "tracking error forecast is close to one; shrinking specific risk towards the universe, the rejected variant, "
        "under-forecast it.",
    )
    caption(figure, f"{len(days)} scored days after a {90}-day warm-up; the 95% band is for {window}-day windows.")
    return figure


# ---------------------------------------------------------------------------- 14. specific risk calibration
def plot_specific_calibration(
    buckets: Sequence[str],
    shrunk: Sequence[float],
    raw: Sequence[float],
    band: tuple[float, float],
    spread_shrunk: Sequence[float],
    spread_raw: Sequence[float],
) -> Figure:
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.4, 1.0], wspace=0.22, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    positions = np.arange(len(buckets))
    axis.axhspan(*band, color=PALETTE["band"], zorder=0)
    axis.axhline(1.0, color=PALETTE["muted"], linewidth=0.8)
    axis.plot(positions, raw, color=PALETTE["navy"], marker="o", markersize=7, linewidth=1.8, label="EWMA (the model)")
    axis.plot(
        positions,
        shrunk,
        color=PALETTE["accent"],
        marker="o",
        markersize=7,
        linewidth=1.3,
        linestyle="--",
        label="with Bayesian shrinkage (rejected)",
    )
    axis.set_xticks(positions, labels=buckets, fontsize=8)
    style_axes(
        axis,
        title="Bias of specific-risk forecasts by size decile",
        xlabel="market capitalisation decile (1 = smallest)",
    )
    axis.legend(loc="upper right", fontsize=8)
    spread = figure.add_subplot(grid[1])
    spread.bar(positions - 0.2, spread_raw, width=0.4, color=PALETTE["navy"], label="EWMA")
    spread.bar(positions + 0.2, spread_shrunk, width=0.4, color=PALETTE["grid"], label="shrunk")
    spread.set_xticks(positions, labels=[bucket.split()[0] for bucket in buckets], fontsize=8)
    style_axes(spread, title="Spread of the stocks' own bias statistics (lower is better)")
    spread.legend(loc="upper right", fontsize=8)
    title_block(
        figure,
        "Specific risk: Bayesian shrinkage, tested and rejected",
        "Shrinkage pulls each stock towards the average of stocks its size - a cure for noisy estimates. Here the "
        "differences are real and persistent, and shrinking them away widens the spread of the stocks' own biases.",
    )
    caption(
        figure,
        "Estimation universe, all scored days. The account's own backtest reached the same verdict (see "
        "book-bias.png).",
    )
    return figure


# ---------------------------------------------------------------------------- 15. regression quality
def plot_regression_quality(
    days: Sequence[date], r_squared: np.ndarray, significant: Mapping[str, float], regimes: Sequence[Regime]
) -> Figure:
    figure = new_figure(15.8, 7.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[2.0, 1.0], wspace=0.25, **_margins(figure, bottom=0.95, left=0.07))
    axis = figure.add_subplot(grid[0])
    axis.plot(days, r_squared, color=PALETTE["grid"], linewidth=0.6)
    cumulative = np.concatenate([[0.0], np.cumsum(r_squared)])
    starts = np.maximum(np.arange(len(r_squared)) - 62, 0)
    smooth = (cumulative[1:] - cumulative[starts]) / (np.arange(len(r_squared)) + 1 - starts)
    axis.plot(days, smooth, color=PALETTE["navy"], linewidth=1.8, label="trailing 63-day average")
    _shade_regimes(axis, regimes)
    axis.set_ylim(0, 1)
    _percent_axis(axis)
    style_axes(axis, title="Share of each day's cross-section the factors explain (R-squared)")
    axis.legend(loc="upper right", fontsize=8)
    bars = figure.add_subplot(grid[1])
    names = list(significant)
    bars.barh(
        range(len(names)),
        [significant[name] for name in names],
        color=[_factor_colour(name) for name in names],
        height=0.6,
    )
    for position, name in enumerate(names):
        bars.text(significant[name], position, f" {significant[name]:.0%}", va="center", fontsize=8)
    bars.axvline(0.05, color=PALETTE["accent"], linewidth=1.2, linestyle="--")
    bars.text(0.052, len(names) - 0.4, "5%: chance", fontsize=7.6, color=PALETTE["muted"])
    bars.set_yticks(range(len(names)), labels=names, fontsize=8)
    bars.invert_yaxis()
    bars.set_xlim(0, 1)
    _percent_axis(bars, "x")
    style_axes(bars, title="Days with |t| > 2", grid="x")
    title_block(
        figure,
        "How much the factors explain",
        "In a crisis stocks move together and the factors explain more; on a quiet day most of a stock's move is its "
        "own. "
        "A factor that is significant on far more than 5% of days is paying for its place in the model.",
    )
    caption(
        figure,
        "Weighted least squares with square-root-of-capitalisation weights; industries constrained to sum to zero. "
        "R-squared falls in April 2024, when the universe starts replaying the Day 2 market, which has no style "
        "premia.",
    )
    return figure


# ---------------------------------------------------------------------------- 16. the risk report
def plot_risk_report(
    name: str,
    as_of: date,
    headline: Sequence[tuple[str, str]],
    groups: Mapping[str, Mapping[str, float]],
    totals: Mapping[str, float],
    top_holdings: Sequence[tuple[str, float]],
    stress: Sequence[tuple[str, float, float]],
    var_days: Sequence[date],
    realised: np.ndarray,
    var: np.ndarray,
) -> Figure:
    figure = new_figure(11.7, 16.5)
    grid = figure.add_gridspec(
        4, 2, height_ratios=[0.7, 1.0, 1.0, 1.0], hspace=0.55, wspace=0.34, **_margins(figure, top=1.5, bottom=0.8)
    )
    tiles = figure.add_subplot(grid[0, :])
    tiles.axis("off")
    for index, (label, shown) in enumerate(headline):
        x = (index % 4) / 4 + 0.01
        y = 0.72 if index < 4 else 0.12
        tiles.text(x, y + 0.2, label, fontsize=9, color=PALETTE["muted"], transform=tiles.transAxes)
        tiles.text(x, y - 0.08, shown, fontsize=19, weight="bold", color=PALETTE["ink"], transform=tiles.transAxes)
    decomposition = figure.add_subplot(grid[1, :])
    order = ["World", "Industry", "Style", "Currency", "Specific"]
    for row, key in enumerate(groups):
        left = 0.0
        for group in order:
            value = max(groups[key].get(group, 0.0), 0.0)
            decomposition.barh(
                row,
                value,
                left=left,
                height=0.55,
                color=GROUP_COLOURS[group],
                edgecolor=PALETTE["surface"],
                linewidth=2,
            )
            if value > 0.006:
                decomposition.text(
                    left + value / 2,
                    row,
                    f"{value:.1%}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white",
                    weight="bold",
                )
            left += value
        decomposition.text(left, row, f"  {totals[key]:.2%}", va="center", fontsize=10, weight="bold")
    decomposition.set_yticks(range(len(groups)), labels=list(groups))
    decomposition.invert_yaxis()
    decomposition.set_xlim(0, max(totals.values()) * 1.2)
    _percent_axis(decomposition, "x")
    style_axes(decomposition, title="Risk by source (contribution to annualised risk)", grid="x")
    decomposition.legend(
        handles=[Patch(color=GROUP_COLOURS[g], label=g) for g in order], loc="lower right", ncol=5, fontsize=7.5
    )
    holdings = figure.add_subplot(grid[2, 0])
    names = [item for item, _ in top_holdings][::-1]
    values = [value for _, value in top_holdings][::-1]
    holdings.barh(range(len(names)), values, color=PALETTE["navy"], height=0.6)
    holdings.set_yticks(range(len(names)), labels=names, fontsize=8)
    _percent_axis(holdings, "x", 1)
    style_axes(holdings, title="Largest contributions to volatility", grid="x")
    scenarios = figure.add_subplot(grid[2, 1])
    labels = [item for item, _, _ in stress][::-1]
    scenarios.barh(
        np.arange(len(labels)) + 0.18,
        [item for _, item, _ in stress][::-1],
        height=0.36,
        color=PALETTE["navy"],
        label="portfolio",
    )
    scenarios.barh(
        np.arange(len(labels)) - 0.18,
        [item for _, _, item in stress][::-1],
        height=0.36,
        color=PALETTE["grid"],
        label="benchmark",
    )
    scenarios.set_yticks(range(len(labels)), labels=labels, fontsize=7.6)
    scenarios.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    _percent_axis(scenarios, "x")
    style_axes(scenarios, title="Stress tests", grid="x")
    scenarios.legend(loc="lower left", fontsize=7.5)
    backtest = figure.add_subplot(grid[3, :])
    backtest.bar(
        var_days,
        realised,
        color=[PALETTE["gain"] if value >= 0 else PALETTE["loss"] for value in realised],
        width=1.2,
        alpha=0.8,
    )
    backtest.plot(var_days, -var, color=PALETTE["ink"], linewidth=1.1)
    hits = -realised > var
    backtest.scatter(
        np.asarray(var_days, dtype=object)[hits],
        realised[hits],
        s=60,
        facecolor="none",
        edgecolor=PALETTE["accent"],
        linewidth=2,
        zorder=5,
    )
    _percent_axis(backtest, places=1)
    count = int(hits.sum())
    style_axes(
        backtest,
        title=f"Daily return against the 99% VaR: {count} exception{'s' if count != 1 else ''} in {len(var_days)} days",
    )
    backtest.legend(
        handles=[Line2D([], [], color=PALETTE["ink"], label="VaR forecast the morning before")],
        loc="upper left",
        fontsize=7.5,
    )
    title_block(figure, f"{name} - risk report", f"As of {as_of:%d %B %Y}. Factor model forecast, in US dollars.")
    caption(
        figure,
        "Model: 21 factors (world, 11 industries, 5 styles, 4 currencies), EWMA covariance, estimated on 500 stocks.",
    )
    return figure
